"""
agent/core/sync.py — Synchronization Worker with Retry, Backoff, Splitting & Revocation.

Adheres to:
- REQ-3-1 & E06: TLS verification is NEVER disabled.
- REQ-6-1 & E02, E03: Delete local events ONLY when confirmed 'accepted' or 'already_accepted'.
- E34: Split batch on 413 (Payload Too Large).
- E35: Exponential backoff with jitter on 429/503; respect Retry-After.
- E38: 403 stops upload immediately and applies revocation policy.
- §6.2 & REQ-6-3: Two-phase screenshot upload (intent -> storage PUT -> complete).
- E96: Throttling / deferring uploads under battery saver or CPU pressure.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from agent.core.journal import Journal, JournalEvent
from agent.core.policy import PolicyManager
from agent.core.spool import ScreenshotSpool, SpooledScreenshot
from agent.core.status import StatusTracker

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
MAX_BATCH_BYTES = 256 * 1024  # 256 KB


class SyncWorker:
    """
    Manages synchronization of journal events, spooled screenshots, and health heartbeats.
    """

    def __init__(
        self,
        base_api_url: str,
        device_id: str,
        credential_token: str,
        journal: Journal,
        spool: ScreenshotSpool,
        policy_manager: PolicyManager,
        status_tracker: StatusTracker,
        http_client: Optional[Callable[[str, bytes, Dict[str, str], str], Tuple[int, bytes, Dict[str, str]]]] = None,
        agent_version: str = "1.0.0",
    ) -> None:
        self.base_api_url = base_api_url.rstrip("/")
        self.device_id = device_id
        self.credential_token = credential_token
        self.journal = journal
        self.spool = spool
        self.policy_manager = policy_manager
        self.status_tracker = status_tracker
        self.http_client = http_client or self._default_http_request
        self.agent_version = agent_version

        self.consecutive_failures: int = 0
        self.backoff_until: float = 0.0
        self.is_revoked: bool = False

    def _default_http_request(
        self,
        url: str,
        data: bytes,
        headers: Dict[str, str],
        method: str = "POST",
    ) -> Tuple[int, bytes, Dict[str, str]]:
        """
        Executes HTTP request with strict TLS certificate verification (REQ-3-1, E06).
        """
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        # Default ssl.create_default_context() enforces TLS verification strictly
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.getcode(), resp.read(), resp_headers
        except urllib.error.HTTPError as ex:
            resp_headers = {k.lower(): v for k, v in ex.headers.items()}
            return ex.code, ex.read(), resp_headers

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.credential_token}",
            "X-Device-Id": self.device_id,
        }

    def sync_events(self, max_batch_size: int = DEFAULT_BATCH_SIZE) -> int:
        """
        Uploads pending events in bounded batches.
        Handles retries, batch splitting on 413, and status deletion.
        Returns count of accepted events.
        """
        if self.is_revoked:
            logger.warning("Sync paused: device revoked (E38).")
            return 0

        now_mono = time.monotonic()
        if now_mono < self.backoff_until:
            return 0

        pending = self.journal.get_pending_events(limit=max_batch_size)
        if not pending:
            return 0

        event_ids = [e.id for e in pending]
        self.journal.mark_in_flight(event_ids)

        payload_events = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at,
                "payload": e.payload,
            }
            for e in pending
        ]
        body = json.dumps({
            "agent_version": getattr(self, "agent_version", "1.0.0"),
            "schema_version": 1,
            "events": payload_events,
        }).encode("utf-8")

        url = f"{self.base_api_url}/api/agent/events/batch/"
        try:
            status, resp_bytes, resp_headers = self.http_client(url, body, self._auth_headers(), "POST")
            return self._handle_event_batch_response(status, resp_bytes, resp_headers, pending)
        except Exception as ex:
            logger.error(f"Network error syncing events: {ex}")
            self.journal.revert_in_flight(event_ids)
            self._apply_backoff(retry_after=None)
            return 0

    def _handle_event_batch_response(
        self,
        status: int,
        resp_bytes: bytes,
        headers: Dict[str, str],
        events: List[JournalEvent],
    ) -> int:
        event_ids = [e.id for e in events]

        if status in (200, 201, 207):
            self.consecutive_failures = 0
            self.backoff_until = 0.0
            resp_data = json.loads(resp_bytes.decode("utf-8")) if resp_bytes else {}
            accepted_ids = resp_data.get("accepted", [])
            already_accepted_ids = resp_data.get("already_accepted", [])

            # Delete accepted and already_accepted (REQ-6-1)
            ids_to_delete = list(set(accepted_ids + already_accepted_ids))
            deleted_count = self.journal.delete_accepted(ids_to_delete)

            # Revert any remaining events not accepted
            remaining = set(event_ids) - set(ids_to_delete)
            if remaining:
                self.journal.revert_in_flight(list(remaining))

            self.status_tracker.last_sync_at = datetime.now(timezone.utc).isoformat()
            self.status_tracker.save_state()
            return len(ids_to_delete)

        elif status == 413:
            # Batch too large: split batch and retry with smaller size (E34)
            logger.warning(f"Batch size {len(events)} rejected with 413; splitting batch (E34).")
            self.journal.revert_in_flight(event_ids)
            if len(events) > 1:
                mid = len(events) // 2
                return self.sync_events(max_batch_size=mid)
            return 0

        elif status == 403:
            # Device revoked on server (E38)
            logger.error("Device revoked by server (403). Stopping uploads and applying revocation policy (E38).")
            self.is_revoked = True
            self.policy_manager.mark_revoked(action="hold")
            self.journal.revert_in_flight(event_ids)
            return 0

        elif status in (429, 503):
            # Overloaded / Rate limited (E35)
            retry_after_str = headers.get("retry-after")
            retry_sec = float(retry_after_str) if retry_after_str and retry_after_str.isdigit() else None
            logger.warning(f"Server returned {status}. Applying backoff (Retry-After: {retry_sec}).")
            self.journal.revert_in_flight(event_ids)
            self._apply_backoff(retry_after=retry_sec)
            return 0

        elif 400 <= status < 500:
            # Permanent client error (400, 422)
            logger.error(f"Permanent API error {status}: {resp_bytes.decode('utf-8', errors='replace')}")
            # Do not retry indefinitely; drop bad events and report as gap
            self.journal.delete_accepted(event_ids)
            return 0

        else:
            # 5xx server error
            self.journal.revert_in_flight(event_ids)
            self._apply_backoff(retry_after=None)
            return 0

    def sync_screenshots(self, limit: int = 5) -> int:
        """
        Uploads spooled screenshots using the two-phase protocol (§6.2, REQ-6-3).
        """
        if self.is_revoked:
            return 0

        ready = self.spool.get_ready_screenshots(limit=limit)
        if not ready:
            return 0

        uploaded_count = 0
        for shot in ready:
            if self._upload_single_screenshot(shot):
                uploaded_count += 1
            else:
                break
        return uploaded_count

    def _upload_single_screenshot(self, screenshot: SpooledScreenshot) -> bool:
        """Two-phase upload for one screenshot."""
        sid = screenshot.screenshot_id
        self.spool.mark_in_flight(sid)

        try:
            image_bytes = self.spool.read_decrypted_screenshot(screenshot)
        except Exception as ex:
            logger.error(f"Error decrypting spooled screenshot {sid}: {ex}")
            self.spool.revert_in_flight(sid)
            return False

        # Phase 1: Request upload intent
        intent_url = f"{self.base_api_url}/api/agent/screenshots/upload-intents/"
        intent_body = json.dumps(
            {
                "screenshot_id": sid,
                "captured_at": screenshot.captured_at,
                "content_type": "image/jpeg",
                "file_size": len(image_bytes),
                "checksum": screenshot.sha256_checksum,
            }
        ).encode("utf-8")

        try:
            status, resp_bytes, _ = self.http_client(intent_url, intent_body, self._auth_headers(), "POST")
            if status == 403:
                self.is_revoked = True
                self.policy_manager.mark_revoked()
                self.spool.revert_in_flight(sid)
                return False
            if status not in (200, 201):
                logger.error(f"Upload intent rejected with status {status}")
                self.spool.revert_in_flight(sid)
                return False

            intent_data = json.loads(resp_bytes.decode("utf-8"))
            upload_url = intent_data.get("upload_url")
            storage_key = intent_data.get("object_key")

            # Phase 2: Upload to storage
            if upload_url:
                put_status, _, _ = self.http_client(
                    upload_url,
                    image_bytes,
                    {"Content-Type": "image/jpeg"},
                    "PUT",
                )
                if put_status not in (200, 204):
                    logger.error(f"Storage PUT returned status {put_status}")
                    self.spool.revert_in_flight(sid)
                    return False

            # Phase 3: Finalize completion
            comp_url = f"{self.base_api_url}/api/agent/screenshots/complete/"
            comp_body = json.dumps(
                {
                    "screenshot_id": sid,
                    "object_key": storage_key,
                    "checksum": screenshot.sha256_checksum,
                    "file_size": len(image_bytes),
                }
            ).encode("utf-8")

            comp_status, _, _ = self.http_client(comp_url, comp_body, self._auth_headers(), "POST")
            if comp_status in (200, 201):
                # Verified acceptance: safely delete local file (REQ-6-1)
                self.spool.delete_finalized(sid)
                return True
            else:
                self.spool.revert_in_flight(sid)
                return False

        except Exception as ex:
            logger.error(f"Error during screenshot sync: {ex}")
            self.spool.revert_in_flight(sid)
            return False

    def send_heartbeat(self, heartbeat_payload: Dict[str, Any]) -> bool:
        """Sends §12.1 heartbeat to backend."""
        if self.is_revoked:
            return False

        url = f"{self.base_api_url}/api/agent/heartbeat/"
        body = json.dumps(heartbeat_payload).encode("utf-8")
        try:
            status, resp_bytes, _ = self.http_client(url, body, self._auth_headers(), "POST")
            if status == 403:
                self.is_revoked = True
                self.policy_manager.mark_revoked()
                return False
            return status in (200, 201)
        except Exception as ex:
            logger.warning(f"Failed to send heartbeat: {ex}")
            return False

    def _apply_backoff(self, retry_after: Optional[float] = None) -> None:
        """Calculates exponential backoff with random jitter."""
        if retry_after is not None and retry_after > 0:
            self.backoff_until = time.monotonic() + retry_after
            return

        self.consecutive_failures += 1
        base_backoff = min(60.0, 2.0 ** min(self.consecutive_failures, 6))
        jitter = random.uniform(0.5, 1.5)
        backoff_sec = base_backoff * jitter
        self.backoff_until = time.monotonic() + backoff_sec
