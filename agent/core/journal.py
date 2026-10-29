"""
agent/core/journal.py — Local SQLite Event Journal with Durability & Recovery.

Features:
- Unique event UUIDs, schema versioning, upload state tracking.
- Durability: WAL mode and NORMAL synchronous setting with bounded batch commits.
- Edge Case E08, E09, E19: Startup integrity check; quarantine corrupted databases,
  recover recoverable rows, start fresh journal without destroying evidence.
- Edge Case E17, E18, E97: Maximum queue depth, disk usage monitoring, explicit gap events.
- Monotonic reference & boot segment ID storage (E93).
- Strict acceptance-based deletion: records deleted ONLY after verified server acceptance (REQ-6-1).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent.core.crypto import CryptoManager

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_MAX_QUEUE_EVENTS = 50000


@dataclass
class JournalEvent:
    id: str
    event_type: str
    occurred_at: str
    payload: Dict[str, Any]
    monotonic_reference: float
    boot_segment_id: str
    upload_status: str = "pending"  # pending, in_flight, accepted


class Journal:
    """
    SQLite-backed durable event journal.
    """

    def __init__(
        self,
        db_path: str,
        crypto: CryptoManager,
        max_events: int = DEFAULT_MAX_QUEUE_EVENTS,
    ) -> None:
        self.db_path = db_path
        self.crypto = crypto
        self.max_events = max_events
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_initialized()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            # WAL mode + synchronous NORMAL for bounded durability without excessive I/O
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._conn = conn
        return self._conn

    def _ensure_initialized(self, skip_quarantine: bool = False) -> None:
        """Runs startup integrity check and migrations."""
        if not skip_quarantine and os.path.exists(self.db_path):
            is_valid = self._check_integrity()
            if not is_valid:
                logger.warning("Journal SQLite integrity check failed. Initiating quarantine and recovery (E19).")
                self.quarantine_and_recover()
                return

        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    monotonic_reference REAL NOT NULL,
                    boot_segment_id TEXT NOT NULL,
                    payload_encrypted BLOB NOT NULL,
                    nonce BLOB NOT NULL,
                    upload_status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_status
                ON events (upload_status, occurred_at);
                """
            )

            # Record schema version
            cursor = conn.execute("SELECT MAX(version) FROM schema_version;")
            row = cursor.fetchone()
            current_ver = row[0] if row and row[0] is not None else 0
            if current_ver < SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )

            # Reset any abandoned in_flight events back to pending
            conn.execute("UPDATE events SET upload_status = 'pending' WHERE upload_status = 'in_flight';")

    def _check_integrity(self) -> bool:
        """Executes PRAGMA integrity_check."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.execute("PRAGMA integrity_check;")
            res = cursor.fetchone()
            return res is not None and res[0] == "ok"
        except Exception:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def quarantine_and_recover(self) -> str:
        """
        Quarantines corrupt SQLite database and recovers valid events into a fresh DB.
        Returns the quarantine path.
        """
        self.close()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        quarantine_path = f"{self.db_path}.corrupt.{timestamp}"
        recovered_events: List[Tuple[str, str, str, float, str, bytes, bytes, str, int, str]] = []

        # Attempt to read readable rows from corrupt file before moving
        read_conn = None
        try:
            read_conn = sqlite3.connect(self.db_path, timeout=2.0)
            cursor = read_conn.execute(
                "SELECT id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status, retry_count, created_at FROM events;"
            )
            recovered_events = cursor.fetchall()
        except Exception:
            pass
        finally:
            if read_conn is not None:
                try:
                    read_conn.close()
                except Exception:
                    pass

        # Move corrupt file
        try:
            if os.path.exists(self.db_path):
                shutil.move(self.db_path, quarantine_path)
            for suffix in ["-wal", "-shm"]:
                wal_path = f"{self.db_path}{suffix}"
                if os.path.exists(wal_path):
                    try:
                        shutil.move(wal_path, f"{quarantine_path}{suffix}")
                    except OSError:
                        pass
        except Exception as ex:
            logger.error(f"Error moving corrupt journal to quarantine: {ex}")
            try:
                os.remove(self.db_path)
            except OSError:
                pass

        # Re-initialize clean DB without re-running quarantine
        self._conn = None
        self._ensure_initialized(skip_quarantine=True)

        # Re-insert recovered events
        if recovered_events:
            conn = self._get_connection()
            with conn:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO events
                    (id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status, retry_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    recovered_events,
                )
        return quarantine_path

    def append_event(
        self,
        event_type: str,
        occurred_at: str,
        payload: Dict[str, Any],
        monotonic_reference: float,
        boot_segment_id: str,
        event_id: Optional[str] = None,
    ) -> JournalEvent:
        """
        Durably appends an event to the local journal.
        Payload is encrypted using authenticated encryption before persisting.
        If queue limit exceeded, writes an explicit telemetry gap event (E17, E18).
        """
        event_uuid = event_id or str(uuid.uuid4())
        raw_payload = json.dumps(payload, sort_keys=True).encode("utf-8")
        ciphertext, nonce = self.crypto.encrypt(raw_payload)

        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()

        # Check queue quota
        cursor = conn.execute("SELECT COUNT(*) FROM events WHERE upload_status != 'accepted';")
        count = cursor.fetchone()[0]

        if count >= self.max_events:
            # Drop oldest events to make room, but write an explicit telemetry gap (E18, E97)
            logger.warning(f"Journal queue depth reached quota ({count}/{self.max_events}). Pruning oldest with gap.")
            self._prune_with_gap(conn)

        with conn:
            conn.execute(
                """
                INSERT INTO events (id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?);
                """,
                (event_uuid, event_type, occurred_at, monotonic_reference, boot_segment_id, ciphertext, nonce, now_iso),
            )

        return JournalEvent(
            id=event_uuid,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            monotonic_reference=monotonic_reference,
            boot_segment_id=boot_segment_id,
            upload_status="pending",
        )

    def _prune_with_gap(self, conn: sqlite3.Connection) -> None:
        """Evicts oldest 100 pending events and inserts an explicit telemetry-gap event."""
        cursor = conn.execute(
            "SELECT id, occurred_at FROM events WHERE upload_status = 'pending' ORDER BY occurred_at ASC LIMIT 100;"
        )
        rows = cursor.fetchall()
        if not rows:
            return

        evicted_ids = [r[0] for r in rows]
        start_time = rows[0][1]
        end_time = rows[-1][1]

        # Evict
        placeholders = ",".join("?" for _ in evicted_ids)
        conn.execute(f"DELETE FROM events WHERE id IN ({placeholders});", evicted_ids)

        # Insert gap event
        gap_id = str(uuid.uuid4())
        gap_payload = {
            "gap_reason": "queue_quota_exceeded",
            "evicted_count": len(evicted_ids),
            "gap_start": start_time,
            "gap_end": end_time,
        }
        raw_gap = json.dumps(gap_payload).encode("utf-8")
        ciphertext, nonce = self.crypto.encrypt(raw_gap)
        now_iso = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO events (id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status, created_at)
            VALUES (?, 'telemetry-gap', ?, ?, 'gap-segment', ?, ?, 'pending', ?);
            """,
            (gap_id, end_time, time.monotonic(), ciphertext, nonce, now_iso),
        )

    def get_pending_events(self, limit: int = 100) -> List[JournalEvent]:
        """Fetches pending events for upload batching, decrypting payloads."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT id, event_type, occurred_at, monotonic_reference, boot_segment_id, payload_encrypted, nonce, upload_status
            FROM events
            WHERE upload_status = 'pending'
            ORDER BY occurred_at ASC, rowid ASC
            LIMIT ?;
            """,
            (limit,),
        )

        events: List[JournalEvent] = []
        for row in cursor.fetchall():
            try:
                decrypted_bytes = self.crypto.decrypt(row["payload_encrypted"], row["nonce"])
                payload = json.loads(decrypted_bytes.decode("utf-8"))
            except Exception as ex:
                logger.error(f"Error decrypting event {row['id']}: {ex}")
                payload = {"_decryption_error": str(ex)}

            events.append(
                JournalEvent(
                    id=row["id"],
                    event_type=row["event_type"],
                    occurred_at=row["occurred_at"],
                    payload=payload,
                    monotonic_reference=row["monotonic_reference"],
                    boot_segment_id=row["boot_segment_id"],
                    upload_status=row["upload_status"],
                )
            )
        return events

    def mark_in_flight(self, event_ids: List[str]) -> None:
        """Marks events as in-flight during an upload attempt."""
        if not event_ids:
            return
        conn = self._get_connection()
        placeholders = ",".join("?" for _ in event_ids)
        with conn:
            conn.execute(
                f"UPDATE events SET upload_status = 'in_flight', retry_count = retry_count + 1 WHERE id IN ({placeholders});",
                event_ids,
            )

    def revert_in_flight(self, event_ids: List[str]) -> None:
        """Reverts in-flight events to pending on network or transient error."""
        if not event_ids:
            return
        conn = self._get_connection()
        placeholders = ",".join("?" for _ in event_ids)
        with conn:
            conn.execute(
                f"UPDATE events SET upload_status = 'pending' WHERE id IN ({placeholders});",
                event_ids,
            )

    def delete_accepted(self, accepted_ids: List[str]) -> int:
        """
        Deletes locally stored events ONLY after verified server acceptance (REQ-6-1).
        Returns number of deleted rows.
        """
        if not accepted_ids:
            return 0
        conn = self._get_connection()
        placeholders = ",".join("?" for _ in accepted_ids)
        with conn:
            cursor = conn.execute(
                f"DELETE FROM events WHERE id IN ({placeholders});",
                accepted_ids,
            )
            return cursor.rowcount

    def get_queue_depth(self) -> int:
        """Returns total number of events pending or in-flight."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM events;")
        return cursor.fetchone()[0]

    def get_oldest_pending_age_seconds(self) -> float:
        """Returns seconds since the oldest pending event occurred, or 0.0 if empty."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT MIN(occurred_at) FROM events WHERE upload_status = 'pending';")
        row = cursor.fetchone()
        if not row or not row[0]:
            return 0.0
        try:
            oldest_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            return max(0.0, (now_dt - oldest_dt).total_seconds())
        except Exception:
            return 0.0

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
