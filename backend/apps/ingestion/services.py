"""Event ingestion and heartbeat processing service strictly per §6.1, §8.3, §12.1."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from apps.audit.services import log_audit_event
from apps.common.exceptions import ApplicationConflict, PayloadTooLarge, RateLimitedException
from apps.devices.models import Device, DeviceStatus
from apps.ingestion.models import ActivityEvent, EventBatch, EventBatchStatus
from apps.policies.models import MonitoringPolicy

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 1000
MAX_REQUESTS_PER_MINUTE = 120

KNOWN_EVENT_TYPES = {
    "app.focus",
    "app.active",
    "session.state",
    "session.lock",
    "session.unlock",
    "session.sleep",
    "session.resume",
    "session.wake",
    "session.idle_start",
    "session.idle_end",
    "device.startup",
    "device.shutdown",
    "screenshot.captured",
    "screenshot.skipped",
    "telemetry.gap",
    "heartbeat",
}


def parse_semver(version_str: str) -> Tuple[int, ...]:
    """Parse semver string into comparable tuple."""
    try:
        parts = version_str.strip().split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception:
        return (0, 0, 0)


def check_agent_version_compatibility(agent_version: str, policy: MonitoringPolicy) -> Tuple[bool, bool]:
    """Evaluates agent version compatibility against policy (§12.1, E16).

    Returns:
        (is_compatible, is_upgrade_required)
    """
    agent_ver = parse_semver(agent_version)
    min_ver = parse_semver(policy.min_agent_version)
    max_ver = parse_semver(policy.max_agent_version)

    if agent_ver < min_ver:
        return False, True
    if agent_ver > max_ver:
        return False, False
    return True, False


def check_device_rate_limit(device: Device) -> None:
    """Enforces per-device ingestion rate limits (E35). Degrades gracefully on cache outage (E76)."""
    try:
        cache_key = f"rate_limit:device:{device.id}"
        current_count = cache.get(cache_key, 0)
        if current_count >= MAX_REQUESTS_PER_MINUTE:
            raise RateLimitedException(
                "Device event ingestion rate limit exceeded. Please back off.",
                retry_after=60,
            )
        cache.set(cache_key, current_count + 1, timeout=60)
    except RateLimitedException:
        raise
    except Exception as ex:
        logger.warning("Cache unavailable for rate limit check; degrading gracefully (E76): %s", ex)


def canonical_json(data: Any) -> str:
    """Deterministic JSON representation for tamper detection (E31, E32)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


@transaction.atomic
def process_event_batch(
    device: Device,
    raw_events: List[Dict[str, Any]],
    agent_version: str,
    schema_version: int = 1,
) -> Dict[str, Any]:
    """Processes and durably commits an event batch (§6.1, E02, E03, E25, E31–E36).

    Commit semantics:
    - Writes durably before acknowledging
    - Idempotent deduplication (E31)
    - Conflict 409 on different payload for same event ID (E32)
    - Rejection of unknown event types (E33)
    - Partial acceptance per event (E36)
    - Oversized batch detection (E34)
    """
    if len(raw_events) > MAX_BATCH_SIZE:
        raise PayloadTooLarge(
            f"Event batch contains {len(raw_events)} events, exceeding the maximum limit of {MAX_BATCH_SIZE}."
        )

    check_device_rate_limit(device)

    now = timezone.now()
    batch = EventBatch.objects.create(
        tenant=device.tenant,
        device=device,
        agent_version=agent_version,
        schema_version=schema_version,
        total_events=len(raw_events),
    )

    accepted_instances: List[ActivityEvent] = []
    accepted_ids: List[str] = []
    already_accepted_ids: List[str] = []
    rejected: List[Dict[str, Any]] = []

    for item in raw_events:
        event_id_raw = item.get("id")
        if not event_id_raw:
            rejected.append({"id": None, "code": "missing_id", "message": "Event missing unique ID."})
            continue

        try:
            event_id = uuid.UUID(str(event_id_raw))
        except (ValueError, TypeError):
            rejected.append({"id": str(event_id_raw), "code": "invalid_id", "message": "Event ID is not a valid UUID."})
            continue

        event_type = item.get("event_type", "")
        if event_type not in KNOWN_EVENT_TYPES:
            # E33: Unknown event type rejected with stable code
            rejected.append({
                "id": str(event_id),
                "code": "unknown_event_type",
                "message": f"Unknown event type '{event_type}'.",
            })
            continue

        occurred_at_raw = item.get("occurred_at")
        occurred_at = parse_datetime(str(occurred_at_raw)) if occurred_at_raw else None
        if not occurred_at:
            occurred_at = now

        payload = item.get("payload") or {}

        # Clock drift handling (E02, E03, E25): flag anomaly if timestamp is implausible
        drift_seconds = abs((now - occurred_at).total_seconds())
        if drift_seconds > 86400:  # Far in future or past (> 24 hours)
            payload["_anomaly_clock_drift_seconds"] = int(drift_seconds)

        # Idempotency & Tamper detection (E31, E32)
        existing = ActivityEvent.objects.filter(id=event_id, tenant=device.tenant).first()
        if existing:
            if canonical_json(existing.payload) == canonical_json(payload):
                # E31: Same ID + same payload -> already accepted
                already_accepted_ids.append(str(event_id))
                continue
            else:
                # E32: Same ID + different payload -> 409 Conflict & security alert
                log_audit_event(
                    tenant=device.tenant,
                    action="security.event_integrity_tamper",
                    resource_type="activity_event",
                    resource_id=str(event_id),
                    metadata={
                        "device_id": str(device.id),
                        "existing_payload": existing.payload,
                        "conflicting_payload": payload,
                    },
                )
                raise ApplicationConflict(
                    f"Integrity conflict: Event ID {event_id} already exists with a different payload.",
                    code="integrity_conflict",
                )

        event_obj = ActivityEvent(
            id=event_id,
            tenant=device.tenant,
            device=device,
            batch=batch,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            upload_status="accepted",
        )
        accepted_instances.append(event_obj)
        accepted_ids.append(str(event_id))

    # Bulk insert accepted events
    if accepted_instances:
        ActivityEvent.objects.bulk_create(accepted_instances)

    # Update batch stats
    batch.accepted_count = len(accepted_ids) + len(already_accepted_ids)
    if rejected and not accepted_ids and not already_accepted_ids:
        batch.status = EventBatchStatus.REJECTED
    elif rejected:
        batch.status = EventBatchStatus.PARTIAL
    else:
        batch.status = EventBatchStatus.ACCEPTED
    batch.save(update_fields=["accepted_count", "status"])

    # Update device last_seen_at
    device.last_seen_at = now
    device.save(update_fields=["last_seen_at"])

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "accepted": accepted_ids,
        "already_accepted": already_accepted_ids,
        "rejected": rejected,
    }
