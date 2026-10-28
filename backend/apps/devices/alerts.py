"""Agent silence alerts accounting for sleep and work hours (§12.2, REQ-12-2)."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional
from django.utils import timezone

from apps.devices.models import Device, DeviceStatus
from apps.ingestion.models import ActivityEvent
from apps.policies.models import MonitoringPolicy


@dataclass
class DeviceSilenceEvaluation:
    device_id: str
    hostname: str
    is_alert: bool
    reason: str
    silence_seconds: float
    is_work_hours: bool
    is_sleeping: bool


def is_within_work_hours(policy: MonitoringPolicy, dt: datetime.datetime) -> bool:
    """Checks whether the specified datetime falls within policy-defined work hours and days."""
    windows = policy.capture_windows or {}
    weekdays = windows.get("weekdays", [1, 2, 3, 4, 5])  # 1=Mon, ..., 7=Sun
    work_hours = windows.get("work_hours", {"start": "09:00", "end": "18:00"})

    # Check day of week (ISO weekday: Monday is 1, Sunday is 7)
    if dt.isoweekday() not in weekdays:
        return False

    start_str = work_hours.get("start", "09:00")
    end_str = work_hours.get("end", "18:00")

    try:
        start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
    except (ValueError, TypeError):
        start_time = datetime.time(9, 0)
        end_time = datetime.time(18, 0)

    current_time = dt.time()
    if start_time <= end_time:
        return start_time <= current_time <= end_time
    else:
        # Over-midnight shift
        return current_time >= start_time or current_time <= end_time


def is_device_sleeping_or_locked(device: Device) -> bool:
    """Checks if the device's latest reported activity indicated sleep, hibernate, or lock."""
    latest_event = (
        ActivityEvent.objects.filter(device=device)
        .order_by("-occurred_at")
        .first()
    )
    if not latest_event:
        return False

    event_type = getattr(latest_event, "event_type", "").lower()
    sleeping_states = (
        "system_sleep",
        "system_hibernate",
        "display_sleep",
        "session_lock",
        "session_locked",
        "sleep",
        "lock",
    )
    return any(state in event_type for state in sleeping_states)


def evaluate_device_silence_alert(
    device: Device,
    current_time: Optional[datetime.datetime] = None,
    silence_threshold_seconds: int = 3600,
) -> DeviceSilenceEvaluation:
    """Evaluates agent silence strictly accounting for work hours and sleep states (REQ-12-2, §12.2).
    
    Rules:
    - If device status is REVOKED: never alert.
    - If device has no last_seen_at: never alert.
    - If silence is within threshold: no alert.
    - If silence occurs during non-work hours (nights, weekends): suppress alert.
    - If last known state was sleep or lock: suppress alert.
    - Only raise alert if silence occurs during active work hours while un-slept.
    """
    now = current_time or timezone.now()

    if device.status == DeviceStatus.REVOKED:
        return DeviceSilenceEvaluation(
            device_id=str(device.id),
            hostname=device.hostname,
            is_alert=False,
            reason="device_revoked",
            silence_seconds=0.0,
            is_work_hours=False,
            is_sleeping=False,
        )

    if not device.last_seen_at:
        return DeviceSilenceEvaluation(
            device_id=str(device.id),
            hostname=device.hostname,
            is_alert=False,
            reason="never_seen",
            silence_seconds=0.0,
            is_work_hours=False,
            is_sleeping=False,
        )

    silence_seconds = max(0.0, (now - device.last_seen_at).total_seconds())

    if silence_seconds <= silence_threshold_seconds:
        return DeviceSilenceEvaluation(
            device_id=str(device.id),
            hostname=device.hostname,
            is_alert=False,
            reason="within_active_threshold",
            silence_seconds=silence_seconds,
            is_work_hours=False,
            is_sleeping=False,
        )

    # Resolve policy
    policy = MonitoringPolicy.get_or_create_default(device.tenant)
    in_work_hours = is_within_work_hours(policy, now)
    sleeping = is_device_sleeping_or_locked(device)

    if not in_work_hours:
        return DeviceSilenceEvaluation(
            device_id=str(device.id),
            hostname=device.hostname,
            is_alert=False,
            reason="outside_work_hours_suppressed",
            silence_seconds=silence_seconds,
            is_work_hours=False,
            is_sleeping=sleeping,
        )

    if sleeping:
        return DeviceSilenceEvaluation(
            device_id=str(device.id),
            hostname=device.hostname,
            is_alert=False,
            reason="device_sleep_or_lock_suppressed",
            silence_seconds=silence_seconds,
            is_work_hours=True,
            is_sleeping=True,
        )

    # Active work hours, not sleeping, and silent > threshold
    return DeviceSilenceEvaluation(
        device_id=str(device.id),
        hostname=device.hostname,
        is_alert=True,
        reason="agent_unexpected_silence_alert",
        silence_seconds=silence_seconds,
        is_work_hours=True,
        is_sleeping=False,
    )
