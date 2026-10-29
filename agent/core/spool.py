"""
agent/core/spool.py — Encrypted Screenshot Spool with Atomic Lifecycle & Quota Management.

Adheres to:
- Write encrypted temp file (.tmp) -> flush -> checksum -> atomic rename (.spool) -> mark ready.
- Edge Case E20 & E21: Startup reconciliation of orphan files (.tmp or unknown files) and orphan rows.
- Priority Dropping (REQ-5-2, E17, E18, E97): Screenshots are dropped before event journal
  when disk/spool quota is tight, logging explicit gap events without silent data loss.
- Never delete unacknowledged data before server confirmation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent.core.crypto import CryptoManager

logger = logging.getLogger(__name__)

DEFAULT_MAX_SPOOL_BYTES = 500 * 1024 * 1024  # 500 MB max spool
DEFAULT_MIN_FREE_DISK_BYTES = 100 * 1024 * 1024  # 100 MB free disk floor


@dataclass
class SpooledScreenshot:
    screenshot_id: str
    file_path: str
    sha256_checksum: str
    file_size: int
    captured_at: str
    metadata: Dict[str, Any]
    status: str  # ready, in_flight, finalized


class ScreenshotSpool:
    """
    Manages encrypted disk spooling for captured screenshots.
    """

    def __init__(
        self,
        spool_dir: str,
        crypto: CryptoManager,
        max_spool_bytes: int = DEFAULT_MAX_SPOOL_BYTES,
        min_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
        index_db_path: Optional[str] = None,
    ) -> None:
        self.spool_dir = os.path.abspath(spool_dir)
        self.crypto = crypto
        self.max_spool_bytes = max_spool_bytes
        self.min_free_disk_bytes = min_free_disk_bytes
        self.index_db_path = index_db_path or os.path.join(self.spool_dir, "spool_index.db")
        self._conn: Optional[sqlite3.Connection] = None

        os.makedirs(self.spool_dir, exist_ok=True)
        self._ensure_initialized()
        self.reconcile_at_startup()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self.index_db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            self._conn = conn
        return self._conn

    def _ensure_initialized(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spooled_screenshots (
                    screenshot_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    sha256_checksum TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_spool_status
                ON spooled_screenshots (status, captured_at);
                """
            )

    def reconcile_at_startup(self) -> Dict[str, int]:
        """
        Reconciles orphan files and orphan DB rows at startup (E20, E21):
        - Any abandoned '.tmp' files are cleaned up or logged.
        - Any '.spool' files not in DB are indexed or quarantined (E20).
        - Any DB rows whose underlying files are missing are purged with warning (E21).
        """
        conn = self._get_connection()
        stats = {"orphan_tmp_deleted": 0, "orphan_files_indexed": 0, "orphan_rows_removed": 0}

        # 0. Reset any interrupted in_flight screenshots back to ready
        with conn:
            conn.execute("UPDATE spooled_screenshots SET status = 'ready' WHERE status = 'in_flight';")

        # 1. Clean up stray temp files (.tmp)
        for fname in os.listdir(self.spool_dir):
            if fname.endswith(".tmp"):
                fpath = os.path.join(self.spool_dir, fname)
                try:
                    os.remove(fpath)
                    stats["orphan_tmp_deleted"] += 1
                except OSError as ex:
                    logger.warning(f"Failed to remove orphan temp file {fpath}: {ex}")

        # 2. Check DB rows against actual files (E21)
        cursor = conn.execute("SELECT screenshot_id, file_path FROM spooled_screenshots;")
        rows = cursor.fetchall()
        missing_ids = []
        known_files = set()
        for row in rows:
            sid = row["screenshot_id"]
            fpath = row["file_path"]
            if not os.path.exists(fpath):
                missing_ids.append(sid)
            else:
                known_files.add(os.path.abspath(fpath))

        if missing_ids:
            placeholders = ",".join("?" for _ in missing_ids)
            with conn:
                conn.execute(f"DELETE FROM spooled_screenshots WHERE screenshot_id IN ({placeholders});", missing_ids)
            stats["orphan_rows_removed"] = len(missing_ids)
            logger.warning(f"Reconciliation removed {len(missing_ids)} orphan rows with missing files (E21).")

        # 3. Check spool directory for untracked .spool files (E20)
        for fname in os.listdir(self.spool_dir):
            if fname.endswith(".spool"):
                fpath = os.path.abspath(os.path.join(self.spool_dir, fname))
                if fpath not in known_files:
                    # Index orphan file
                    sid = fname[:-6]
                    try:
                        fsize = os.path.getsize(fpath)
                        with open(fpath, "rb") as f:
                            csum = hashlib.sha256(f.read()).hexdigest()
                        now_iso = datetime.now(timezone.utc).isoformat()
                        with conn:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO spooled_screenshots
                                (screenshot_id, file_path, sha256_checksum, file_size, captured_at, metadata_json, status, created_at)
                                VALUES (?, ?, ?, ?, ?, '{}', 'ready', ?);
                                """,
                                (sid, fpath, csum, fsize, now_iso, now_iso),
                            )
                        stats["orphan_files_indexed"] += 1
                        logger.info(f"Reconciliation indexed untracked spool file {fname} (E20).")
                    except Exception as ex:
                        logger.error(f"Error indexing untracked spool file {fpath}: {ex}")

        return stats

    def spool_screenshot(
        self,
        image_bytes: bytes,
        captured_at: str,
        metadata: Optional[Dict[str, Any]] = None,
        screenshot_id: Optional[str] = None,
    ) -> Optional[SpooledScreenshot]:
        """
        Encrypts and stores screenshot to disk using atomic two-phase write:
        1. Write encrypted temp file (.tmp).
        2. Flush & fsync.
        3. Compute SHA256.
        4. Atomic rename to .spool.
        5. Record in spool DB.
        If disk space or spool quota is constrained, applies priority dropping (E17, E18, E97).
        """
        sid = screenshot_id or str(uuid.uuid4())
        meta = metadata or {}

        # Check disk & quota headroom
        if not self._ensure_headroom(len(image_bytes)):
            logger.warning("Spool capacity exceeded; dropping screenshot to preserve journal headroom (REQ-5-2).")
            return None

        # Encrypt raw image bytes
        ciphertext, nonce = self.crypto.encrypt(image_bytes)
        # Store combined nonce + ciphertext
        payload_to_store = nonce + ciphertext
        checksum = hashlib.sha256(image_bytes).hexdigest()

        tmp_filename = f"{sid}.tmp"
        spool_filename = f"{sid}.spool"
        tmp_path = os.path.join(self.spool_dir, tmp_filename)
        spool_path = os.path.join(self.spool_dir, spool_filename)

        try:
            with open(tmp_path, "wb") as f:
                f.write(payload_to_store)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename
            os.replace(tmp_path, spool_path)
            file_size = os.path.getsize(spool_path)

            now_iso = datetime.now(timezone.utc).isoformat()
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO spooled_screenshots
                    (screenshot_id, file_path, sha256_checksum, file_size, captured_at, metadata_json, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'ready', ?);
                    """,
                    (sid, spool_path, checksum, file_size, captured_at, json.dumps(meta), now_iso),
                )

            return SpooledScreenshot(
                screenshot_id=sid,
                file_path=spool_path,
                sha256_checksum=checksum,
                file_size=file_size,
                captured_at=captured_at,
                metadata=meta,
                status="ready",
            )
        except Exception as ex:
            logger.error(f"Failed to spool screenshot {sid}: {ex}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def get_ready_screenshots(self, limit: int = 10) -> List[SpooledScreenshot]:
        """Fetches ready screenshots for upload."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT screenshot_id, file_path, sha256_checksum, file_size, captured_at, metadata_json, status
            FROM spooled_screenshots
            WHERE status = 'ready'
            ORDER BY captured_at ASC
            LIMIT ?;
            """,
            (limit,),
        )
        results = []
        for row in cursor.fetchall():
            results.append(
                SpooledScreenshot(
                    screenshot_id=row["screenshot_id"],
                    file_path=row["file_path"],
                    sha256_checksum=row["sha256_checksum"],
                    file_size=row["file_size"],
                    captured_at=row["captured_at"],
                    metadata=json.loads(row["metadata_json"]),
                    status=row["status"],
                )
            )
        return results

    def read_decrypted_screenshot(self, screenshot: SpooledScreenshot) -> bytes:
        """Reads and decrypts stored screenshot bytes."""
        with open(screenshot.file_path, "rb") as f:
            data = f.read()
        nonce = data[:12]
        ciphertext = data[12:]
        return self.crypto.decrypt(ciphertext, nonce)

    def mark_in_flight(self, screenshot_id: str) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                "UPDATE spooled_screenshots SET status = 'in_flight' WHERE screenshot_id = ?;",
                (screenshot_id,),
            )

    def revert_in_flight(self, screenshot_id: str) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                "UPDATE spooled_screenshots SET status = 'ready' WHERE screenshot_id = ?;",
                (screenshot_id,),
            )

    def delete_finalized(self, screenshot_id: str) -> bool:
        """
        Deletes locally spooled screenshot file and DB record ONLY after verified acceptance (REQ-6-1).
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT file_path FROM spooled_screenshots WHERE screenshot_id = ?;",
            (screenshot_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False

        fpath = row["file_path"]
        with conn:
            conn.execute("DELETE FROM spooled_screenshots WHERE screenshot_id = ?;", (screenshot_id,))

        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError as ex:
                logger.warning(f"Error removing spool file {fpath}: {ex}")
        return True

    def get_spool_size_bytes(self) -> int:
        conn = self._get_connection()
        cursor = conn.execute("SELECT COALESCE(SUM(file_size), 0) FROM spooled_screenshots;")
        return cursor.fetchone()[0]

    def _ensure_headroom(self, incoming_bytes: int) -> bool:
        """
        Validates disk and spool quotas.
        If near limit, drops oldest screenshots to protect journal headroom (REQ-5-2, E17, E18).
        """
        # 1. Check free disk space
        try:
            total, used, free = shutil.disk_usage(self.spool_dir)
            if free - incoming_bytes < self.min_free_disk_bytes:
                # Need to drop oldest screenshots
                self._drop_oldest_screenshots(target_freed_bytes=incoming_bytes * 2)
                total, used, free = shutil.disk_usage(self.spool_dir)
                if free - incoming_bytes < self.min_free_disk_bytes:
                    return False
        except OSError:
            pass

        # 2. Check spool byte limit
        current_spool = self.get_spool_size_bytes()
        if current_spool + incoming_bytes > self.max_spool_bytes:
            self._drop_oldest_screenshots(target_freed_bytes=(current_spool + incoming_bytes - self.max_spool_bytes) + 1024 * 1024)
            if self.get_spool_size_bytes() + incoming_bytes > self.max_spool_bytes:
                return False

        return True

    def _drop_oldest_screenshots(self, target_freed_bytes: int) -> int:
        """Drops oldest ready screenshots to make room, returning freed bytes."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT screenshot_id, file_path, file_size FROM spooled_screenshots WHERE status = 'ready' ORDER BY captured_at ASC;"
        )
        rows = cursor.fetchall()
        freed = 0
        dropped_ids = []

        for row in rows:
            dropped_ids.append(row["screenshot_id"])
            freed += row["file_size"]
            fpath = row["file_path"]
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
            if freed >= target_freed_bytes:
                break

        if dropped_ids:
            placeholders = ",".join("?" for _ in dropped_ids)
            with conn:
                conn.execute(f"DELETE FROM spooled_screenshots WHERE screenshot_id IN ({placeholders});", dropped_ids)
            logger.warning(f"Priority policy dropped {len(dropped_ids)} screenshots ({freed} bytes) to protect queue headroom.")

        return freed

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
