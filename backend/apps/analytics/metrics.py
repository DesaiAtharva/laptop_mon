"""Daily metrics calculation engine adhering to §9.2 and §9.3 (REQ-9-5)."""
from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.analytics.models import AppUsageInterval, DailyMetrics, IntervalState
from apps.analytics.timeline import IntervalDraft, TimelineReconstructionEngine
from apps.devices.models import Device
from apps.ingestion.models import ActivityEvent
from apps.policies.models import AppClassification
from apps.tenancy.models import Tenant


def compute_daily_aggregates_from_intervals(
    device: Device,
    intervals: List[IntervalDraft],
    tz: ZoneInfo,
    calc_version: int = 1,
    scheduled_work_hours: float = 8.0,
    freshness_at: Optional[datetime.datetime] = None,
) -> Dict[datetime.date, Dict[str, Any]]:
    """Groups intervals by local calendar date and computes §9.2 metrics."""
    by_date: Dict[datetime.date, List[IntervalDraft]] = defaultdict(list)
    for interval in intervals:
        local_date = interval.started_at.astimezone(tz).date()
        by_date[local_date].append(interval)

    results: Dict[datetime.date, Dict[str, Any]] = {}
    work_seconds = max(1.0, scheduled_work_hours * 3600.0)

    for local_date, day_intervals in by_date.items():
        observed_sec = 0.0
        active_sec = 0.0
        idle_sec = 0.0
        productive_sec = 0.0
        neutral_sec = 0.0
        distracting_sec = 0.0

        for inv in day_intervals:
            dur = inv.duration_seconds
            # Observed session: agent running and not in gap or offline state (§9.2)
            if inv.state not in (IntervalState.TELEMETRY_GAP, IntervalState.OFFLINE):
                observed_sec += dur

            if inv.state == IntervalState.ACTIVE:
                active_sec += dur
                cls = inv.app_classification
                if cls == AppClassification.PRODUCTIVE:
                    productive_sec += dur
                elif cls == AppClassification.DISTRACTING:
                    distracting_sec += dur
                else:
                    neutral_sec += dur

            elif inv.state == IntervalState.IDLE:
                idle_sec += dur

        denominator = productive_sec + neutral_sec + distracting_sec
        productive_share = (productive_sec / denominator) if denominator > 0 else 0.0
        coverage = min(1.0, observed_sec / work_seconds)

        results[local_date] = {
            "observed_session_seconds": round(observed_sec, 2),
            "active_seconds": round(active_sec, 2),
            "idle_seconds": round(idle_sec, 2),
            "productive_seconds": round(productive_sec, 2),
            "neutral_seconds": round(neutral_sec, 2),
            "distracting_seconds": round(distracting_sec, 2),
            "productive_share": round(productive_share, 4),
            "monitoring_coverage": round(coverage, 4),
            "sync_lag_seconds": 0.0,
            "crash_free_sessions": 1,
            "data_freshness_at": freshness_at or timezone.now(),
        }

    return results


def persist_device_timeline_and_metrics(
    device: Device,
    window_start: Optional[datetime.datetime] = None,
    window_end: Optional[datetime.datetime] = None,
    calc_version: int = 1,
) -> Dict[str, Any]:
    """Recomputes intervals and daily metrics for a device in an affected time window (§9.3, E74).
    
    Idempotent and atomic.
    """
    tenant = device.tenant
    tz = ZoneInfo(getattr(tenant, "timezone", "UTC") or "UTC")

    # Fetch relevant events for device
    qs = ActivityEvent.objects.filter(device=device)
    if window_start:
        # Include safety overlap buffer of 1 hour (E74)
        buffered_start = window_start - datetime.timedelta(hours=1)
        qs = qs.filter(occurred_at__gte=buffered_start)
    if window_end:
        buffered_end = window_end + datetime.timedelta(hours=1)
        qs = qs.filter(occurred_at__lte=buffered_end)

    events = list(qs)
    if not events:
        return {"intervals_count": 0, "days_calculated": 0}

    engine = TimelineReconstructionEngine(tenant=tenant, calc_version=calc_version)
    draft_intervals = engine.reconstruct_device_timeline(
        device=device,
        events=events,
        window_start=window_start,
        window_end=window_end,
    )

    freshness = max(e.received_at for e in events) if events else timezone.now()
    daily_aggregates = compute_daily_aggregates_from_intervals(
        device=device,
        intervals=draft_intervals,
        tz=tz,
        calc_version=calc_version,
        scheduled_work_hours=getattr(settings, "ANALYTICS_DEFAULT_WORK_HOURS_PER_DAY", 8.0),
        freshness_at=freshness,
    )

    with transaction.atomic():
        # Clear prior intervals for this device, calc_version, and time window
        delete_qs = AppUsageInterval.objects.filter(device=device, calc_version=calc_version)
        if window_start:
            delete_qs = delete_qs.filter(started_at__gte=window_start)
        if window_end:
            delete_qs = delete_qs.filter(ended_at__lte=window_end)
        delete_qs.delete()

        # Bulk create new intervals
        interval_records = [
            AppUsageInterval(
                tenant=tenant,
                device=device,
                app_identifier=d.app_identifier,
                app_classification=d.app_classification,
                app_classification_version=d.app_classification_version,
                started_at=d.started_at,
                ended_at=d.ended_at,
                duration_seconds=d.duration_seconds,
                state=d.state,
                calc_version=calc_version,
                is_inferred=d.is_inferred,
            )
            for d in draft_intervals
        ]
        AppUsageInterval.objects.bulk_create(interval_records, batch_size=500)

        # Update or create DailyMetrics records (unique grain: device, local_date, calc_version)
        for local_date, metrics_data in daily_aggregates.items():
            DailyMetrics.objects.update_or_create(
                device=device,
                local_date=local_date,
                calc_version=calc_version,
                defaults={
                    "tenant": tenant,
                    "observed_session_seconds": metrics_data["observed_session_seconds"],
                    "active_seconds": metrics_data["active_seconds"],
                    "idle_seconds": metrics_data["idle_seconds"],
                    "productive_seconds": metrics_data["productive_seconds"],
                    "neutral_seconds": metrics_data["neutral_seconds"],
                    "distracting_seconds": metrics_data["distracting_seconds"],
                    "productive_share": metrics_data["productive_share"],
                    "monitoring_coverage": metrics_data["monitoring_coverage"],
                    "sync_lag_seconds": metrics_data["sync_lag_seconds"],
                    "crash_free_sessions": metrics_data["crash_free_sessions"],
                    "data_freshness_at": metrics_data["data_freshness_at"],
                },
            )

    return {
        "intervals_count": len(interval_records),
        "days_calculated": len(daily_aggregates),
    }
