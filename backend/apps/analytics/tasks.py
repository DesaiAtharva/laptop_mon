"""Celery tasks with runtime authorization, idempotency, and deadlock resilience."""
from __future__ import annotations

import csv
import datetime
import io
import logging
import time
from typing import Any, Callable, Dict, Optional, TypeVar
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.models import User
from apps.analytics.metrics import persist_device_timeline_and_metrics
from apps.analytics.models import AppUsageInterval, DailyMetrics, DataExport, ExportStatus, ExportType
from apps.audit.services import log_audit_event
from apps.devices.models import Device
from apps.rbac.permissions import get_manager_accessible_team_ids
from apps.screenshots.storage import get_storage_backend
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant, TenantStatus

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_deadlock(max_retries: int = 3, initial_delay: float = 0.1) -> Callable[[F], F]:
    """Decorator retrying database operations on deadlock with exponential backoff (§9, E77)."""
    def decorator(func: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            delay = initial_delay
            while True:
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    err_msg = str(e).lower()
                    if ("deadlock" in err_msg or "lock" in err_msg or "locked" in err_msg) and retries < max_retries:
                        retries += 1
                        logger.warning(
                            "Database deadlock/lock encountered in %s (attempt %d/%d). Backing off %.2fs: %s",
                            func.__name__,
                            retries,
                            max_retries,
                            delay,
                            e,
                        )
                        time.sleep(delay)
                        delay *= 2
                    else:
                        raise
        return wrapper  # type: ignore
    return decorator


def process_device_timeline_task(
    tenant_id: uuid.UUID | str,
    device_id: uuid.UUID | str,
    window_start_iso: Optional[str] = None,
    window_end_iso: Optional[str] = None,
    calc_version: int = 1,
) -> Dict[str, Any]:
    """Celery task calculating timeline intervals and daily metrics (§9.3, REQ-8-3, E75).
    
    Invariants:
    - Authorization verified on execution (REQ-8-3).
    - Idempotent: duplicate invocations produce identical results (E75).
    - Deadlock resilient (E77).
    """
    # 1. Authorization check at runtime (REQ-8-3)
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant or tenant.status != TenantStatus.ACTIVE:
        logger.error("process_device_timeline_task rejected: tenant %s is not active", tenant_id)
        return {"status": "rejected", "reason": "tenant_not_active"}

    device = Device.objects.filter(id=device_id, tenant=tenant).first()
    if not device:
        logger.error("process_device_timeline_task rejected: device %s not found in tenant %s", device_id, tenant_id)
        return {"status": "rejected", "reason": "device_not_found"}

    # 2. Idempotency lock via cache (E75)
    lock_key = f"lock:timeline:{tenant_id}:{device_id}:{calc_version}"
    if not cache.add(lock_key, "locked", timeout=120):
        logger.info("Timeline task already in progress for %s. Skipping duplicate (E75).", lock_key)
        return {"status": "skipped_duplicate_in_progress"}

    try:
        window_start = parse_datetime(window_start_iso) if window_start_iso else None
        window_end = parse_datetime(window_end_iso) if window_end_iso else None

        @retry_on_deadlock(max_retries=3)
        def _execute() -> Dict[str, Any]:
            return persist_device_timeline_and_metrics(
                device=device,
                window_start=window_start,
                window_end=window_end,
                calc_version=calc_version,
            )

        result = _execute()
        return {"status": "completed", **result}
    finally:
        cache.delete(lock_key)


def export_dataset_task(export_id: uuid.UUID | str, user_id: uuid.UUID | str) -> Dict[str, Any]:
    """Background task generating CSV dataset export with rechecked authorization (§8.4, E81, E82)."""
    export = DataExport.objects.filter(id=export_id).first()
    if not export:
        return {"status": "failed", "reason": "export_not_found"}

    # 1. Re-check authorization at runtime (REQ-8-3)
    user = User.objects.filter(id=user_id, is_active=True).first()
    membership = (
        Membership.objects.filter(tenant=export.tenant, user=user, status=MembershipStatus.ACTIVE).first()
        if user
        else None
    )

    if not user or not membership:
        export.status = ExportStatus.FAILED
        export.error_message = "Authorization revoked before export execution (REQ-8-3)."
        export.save(update_fields=["status", "error_message", "updated_at"])
        return {"status": "failed", "reason": "authorization_revoked"}

    export.status = ExportStatus.PROCESSING
    export.save(update_fields=["status", "updated_at"])

    max_rows = getattr(settings, "ANALYTICS_MAX_EXPORT_ROWS", 50000)
    filters = export.filters or {}

    try:
        # 2. Build QuerySet scoped by role
        if export.export_type == ExportType.DAILY_METRICS:
            qs = DailyMetrics.objects.for_tenant(export.tenant)
            if membership.role == MembershipRole.MANAGER:
                manager_teams = get_manager_accessible_team_ids(membership)
                qs = qs.filter(device__membership__team_memberships__team_id__in=manager_teams)
            elif membership.role == MembershipRole.EMPLOYEE:
                qs = qs.filter(device__membership=membership)

            if "from_date" in filters:
                qs = qs.filter(local_date__gte=filters["from_date"])
            if "to_date" in filters:
                qs = qs.filter(local_date__lte=filters["to_date"])

            row_count = qs.count()
            if row_count > max_rows:
                export.status = ExportStatus.FAILED
                export.error_message = f"Query result ({row_count} rows) exceeds maximum export limit ({max_rows} rows) (E82)."
                export.save(update_fields=["status", "error_message", "updated_at"])
                return {"status": "failed", "reason": "row_limit_exceeded"}

            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                "Device ID", "Local Date", "Calc Version", "Observed Session Sec",
                "Active Sec", "Idle Sec", "Productive Sec", "Neutral Sec", "Distracting Sec",
                "Productive Share", "Monitoring Coverage"
            ])
            for m in qs.select_related("device").iterator(chunk_size=1000):
                writer.writerow([
                    str(m.device.id), m.local_date.isoformat(), m.calc_version,
                    m.observed_session_seconds, m.active_seconds, m.idle_seconds,
                    m.productive_seconds, m.neutral_seconds, m.distracting_seconds,
                    m.productive_share, m.monitoring_coverage
                ])

        elif export.export_type == ExportType.TIMELINE:
            qs = AppUsageInterval.objects.for_tenant(export.tenant)
            if membership.role == MembershipRole.MANAGER:
                manager_teams = get_manager_accessible_team_ids(membership)
                qs = qs.filter(device__membership__team_memberships__team_id__in=manager_teams)
            elif membership.role == MembershipRole.EMPLOYEE:
                qs = qs.filter(device__membership=membership)

            row_count = qs.count()
            if row_count > max_rows:
                export.status = ExportStatus.FAILED
                export.error_message = f"Query result exceeds maximum export limit ({max_rows} rows) (E82)."
                export.save(update_fields=["status", "error_message", "updated_at"])
                return {"status": "failed", "reason": "row_limit_exceeded"}

            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["Device ID", "Started At", "Ended At", "Duration Sec", "App", "Classification", "State"])
            for inv in qs.select_related("device").iterator(chunk_size=1000):
                writer.writerow([
                    str(inv.device.id), inv.started_at.isoformat(), inv.ended_at.isoformat(),
                    inv.duration_seconds, inv.app_identifier, inv.app_classification, inv.state
                ])
        else:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["Export", "Not Supported"])
            row_count = 0

        # Save CSV in object storage
        storage = get_storage_backend()
        file_key = f"tenants/{export.tenant.id}/exports/{export.id}.csv"
        csv_bytes = buffer.getvalue().encode("utf-8")
        storage.put_object_bytes(file_key, csv_bytes, content_type="text/csv")
        download_url = storage.generate_presigned_view_url(file_key, expires_in=86400)

        export.status = ExportStatus.COMPLETED
        export.file_key = file_key
        export.download_url = download_url
        export.row_count = row_count
        export.expires_at = timezone.now() + datetime.timedelta(days=7)
        export.save(update_fields=["status", "file_key", "download_url", "row_count", "expires_at", "updated_at"])

        # Audit export (§11.1)
        log_audit_event(
            action="report.exported",
            resource_type="data_export",
            resource_id=str(export.id),
            actor=user,
            tenant=export.tenant,
            metadata={"export_type": export.export_type, "row_count": row_count},
        )

        return {"status": "completed", "export_id": str(export.id), "row_count": row_count}

    except Exception as e:
        logger.exception("Export failed for %s: %s", export.id, str(e))
        export.status = ExportStatus.FAILED
        export.error_message = str(e)
        export.save(update_fields=["status", "error_message", "updated_at"])
        return {"status": "failed", "reason": str(e)}
