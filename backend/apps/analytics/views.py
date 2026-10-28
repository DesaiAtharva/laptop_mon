"""Views for Reports and Exports API strictly adhering to §8.4, §9, E81, and E82."""
from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from django.conf import settings
from django.db.models import Sum
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone
from apps.analytics.models import (
    AppUsageInterval,
    DailyMetrics,
    DataExport,
    Dispute,
    DisputeStatus,
    ExportStatus,
    ExportType,
    IntervalState,
)
from apps.analytics.serializers import (
    AppUsageIntervalSerializer,
    AppUsageSummarySerializer,
    DailyMetricsSerializer,
    DataExportSerializer,
    DisputeCreateSerializer,
    DisputeSerializer,
    ExportRequestSerializer,
)
from apps.analytics.tasks import export_dataset_task
from apps.audit.services import log_audit_event
from apps.common.exceptions import EntityNotFound, UnprocessableEntity
from apps.devices.models import Device
from apps.policies.models import AppRule, MonitoringPolicy
from apps.rbac.permissions import IsTenantMember, get_manager_accessible_team_ids
from apps.tenancy.models import MembershipRole, TeamMember

logger = logging.getLogger(__name__)


class StandardReportPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def scope_queryset_by_role(qs: Any, request: Request, device_field: str = "device") -> Any:
    """Applies role-based scoping to analytics querysets (§2.2, E47).
    
    - Admin: sees all devices in tenant.
    - Manager: sees ONLY devices belonging to users in assigned teams.
    - Employee: sees ONLY own devices.
    """
    membership = getattr(request, "membership")
    if membership.role == MembershipRole.ADMIN or request.user.is_superuser:
        return qs
    if membership.role == MembershipRole.MANAGER:
        manager_team_ids = get_manager_accessible_team_ids(membership)
        filter_path = f"{device_field}__membership__team_memberships__team_id__in"
        return qs.filter(**{filter_path: manager_team_ids})
    if membership.role == MembershipRole.EMPLOYEE:
        filter_path = f"{device_field}__membership"
        return qs.filter(**{filter_path: membership})
    return qs.none()


def validate_date_range_budget(from_date: Optional[datetime.date], to_date: Optional[datetime.date]) -> None:
    """Enforces query budget constraints (§9, E81)."""
    if from_date and to_date:
        if to_date < from_date:
            raise UnprocessableEntity("to_date cannot be earlier than from_date.", code="INVALID_DATE_RANGE")
        max_days = getattr(settings, "ANALYTICS_MAX_DATE_RANGE_DAYS", 90)
        delta_days = (to_date - from_date).days
        if delta_days > max_days:
            raise UnprocessableEntity(
                f"Date range ({delta_days} days) exceeds the {max_days}-day limit. Use the exports API for bulk data (E81).",
                code="QUERY_BUDGET_EXCEEDED",
            )


class DailyReportsView(APIView):
    """GET /api/reports/daily (§8.4, §9.2)."""

    permission_classes = [IsTenantMember]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        qs = DailyMetrics.objects.for_tenant(tenant).select_related("device")
        qs = scope_queryset_by_role(qs, request)

        device_id = request.query_params.get("device_id")
        if device_id:
            qs = qs.filter(device_id=device_id)

        from_date_str = request.query_params.get("from_date")
        to_date_str = request.query_params.get("to_date")
        from_date = parse_date(from_date_str) if from_date_str else None
        to_date = parse_date(to_date_str) if to_date_str else None

        validate_date_range_budget(from_date, to_date)

        if from_date:
            qs = qs.filter(local_date__gte=from_date)
        if to_date:
            qs = qs.filter(local_date__lte=to_date)

        calc_version = request.query_params.get("calc_version")
        if calc_version:
            qs = qs.filter(calc_version=int(calc_version))

        paginator = StandardReportPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = DailyMetricsSerializer(page, many=True)

        resp = paginator.get_paginated_response(serializer.data)
        resp.data["timezone"] = getattr(tenant, "timezone", "UTC")
        return resp


class TimelineReportsView(APIView):
    """GET /api/reports/timeline (§8.4, §9.1)."""

    permission_classes = [IsTenantMember]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        qs = AppUsageInterval.objects.for_tenant(tenant).select_related("device")
        qs = scope_queryset_by_role(qs, request)

        device_id = request.query_params.get("device_id")
        if device_id:
            qs = qs.filter(device_id=device_id)

        from_dt_str = request.query_params.get("from_date")
        to_dt_str = request.query_params.get("to_date")
        from_dt = parse_datetime(from_dt_str) if from_dt_str else None
        to_dt = parse_datetime(to_dt_str) if to_dt_str else None

        if from_dt and to_dt:
            if (to_dt - from_dt).days > getattr(settings, "ANALYTICS_MAX_DATE_RANGE_DAYS", 90):
                raise UnprocessableEntity("Time range exceeds query budget limit.", code="QUERY_BUDGET_EXCEEDED")

        if from_dt:
            qs = qs.filter(started_at__gte=from_dt)
        if to_dt:
            qs = qs.filter(ended_at__lte=to_dt)

        state_param = request.query_params.get("state")
        if state_param:
            qs = qs.filter(state=state_param)

        paginator = StandardReportPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = AppUsageIntervalSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AppUsageSummaryView(APIView):
    """GET /api/reports/app-usage (§8.4)."""

    permission_classes = [IsTenantMember]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        qs = AppUsageInterval.objects.for_tenant(tenant).filter(state=IntervalState.ACTIVE)
        qs = scope_queryset_by_role(qs, request)

        device_id = request.query_params.get("device_id")
        if device_id:
            qs = qs.filter(device_id=device_id)

        from_dt_str = request.query_params.get("from_date")
        to_dt_str = request.query_params.get("to_date")
        from_dt = parse_datetime(from_dt_str) if from_dt_str else None
        to_dt = parse_datetime(to_dt_str) if to_dt_str else None

        if from_dt:
            qs = qs.filter(started_at__gte=from_dt)
        if to_dt:
            qs = qs.filter(ended_at__lte=to_dt)

        # Aggregate total duration per app
        grouped = (
            qs.values("app_identifier", "app_classification")
            .annotate(total_seconds=Sum("duration_seconds"))
            .order_by("-total_seconds")
        )

        total_active_seconds = sum(item["total_seconds"] or 0.0 for item in grouped)

        data = []
        for item in grouped:
            sec = float(item["total_seconds"] or 0.0)
            pct = round((sec / total_active_seconds * 100.0), 2) if total_active_seconds > 0 else 0.0
            data.append({
                "app_identifier": item["app_identifier"],
                "app_classification": item["app_classification"],
                "total_seconds": round(sec, 2),
                "percentage_of_active": pct,
            })

        serializer = AppUsageSummarySerializer(data, many=True)
        return Response({
            "total_active_seconds": round(total_active_seconds, 2),
            "applications": serializer.data,
        })


class DataExportCreateView(APIView):
    """POST /api/exports (§8.4, E81, E82)."""

    permission_classes = [IsTenantMember]

    def post(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        serializer = ExportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity("Invalid export request data.", field_errors=serializer.errors)

        data = serializer.validated_data
        export = DataExport.objects.create(
            tenant=membership.tenant,
            user=request.user,
            status=ExportStatus.PENDING,
            export_type=data["export_type"],
            filters=data.get("filters", {}),
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        )

        # Trigger background task (in dev/eager mode runs synchronously)
        export_dataset_task(export_id=export.id, user_id=request.user.id)
        export.refresh_from_db()

        out_serializer = DataExportSerializer(export)
        return Response(out_serializer.data, status=status.HTTP_202_ACCEPTED)


class DataExportDetailView(APIView):
    """GET /api/exports/{id} (§8.4)."""

    permission_classes = [IsTenantMember]

    def get(self, request: Request, pk: uuid.UUID) -> Response:
        membership = getattr(request, "membership")
        export = DataExport.objects.for_tenant(membership.tenant).filter(id=pk).first()
        if not export:
            raise EntityNotFound("Export not found.")

        # Employee can only view own exports
        if membership.role == MembershipRole.EMPLOYEE and export.user_id != request.user.id:
            raise EntityNotFound("Export not found.")

        serializer = DataExportSerializer(export)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SelfViewReportView(APIView):
    """GET /api/reports/self-view (§2.1, §11.3, REQ-2-1, REQ-11-3).
    
    Provides employee transparency dashboard data:
    - User and tenant info
    - Active enrolled devices and sync lag
    - Effective monitoring policy & privacy boundaries
    - Recent daily metrics (observed, active, productive, gaps)
    - Active disputes
    """

    permission_classes = [IsTenantMember]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant
        user = request.user

        # 1. Enrolled devices
        devices = Device.objects.filter(tenant=tenant, membership=membership)
        device_list = []
        is_active_monitoring = False
        latest_sync = None
        for d in devices:
            device_list.append({
                "id": str(d.id),
                "hostname": d.hostname,
                "os": d.os,
                "status": d.status,
                "agent_version": d.agent_version,
                "last_seen_at": d.last_seen_at,
            })
            if d.status == "active":
                is_active_monitoring = True
            if d.last_seen_at and (latest_sync is None or d.last_seen_at > latest_sync):
                latest_sync = d.last_seen_at

        # 2. Effective policy
        policy = MonitoringPolicy.get_or_create_default(tenant)

        # 3. Recent metrics (last 14 days)
        fourteen_days_ago = timezone.now().date() - datetime.timedelta(days=14)
        metrics_qs = DailyMetrics.objects.filter(
            tenant=tenant,
            device__in=devices,
            local_date__gte=fourteen_days_ago,
        ).order_by("-local_date")
        metrics_data = DailyMetricsSerializer(metrics_qs, many=True).data

        # 4. Disputes
        disputes_qs = Dispute.objects.filter(tenant=tenant, membership=membership).order_by("-created_at")[:10]
        disputes_data = DisputeSerializer(disputes_qs, many=True).data

        return Response({
            "employee": {
                "user_id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": membership.role,
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
            },
            "monitoring_state": {
                "active": is_active_monitoring,
                "status": "active" if is_active_monitoring else "inactive",
                "devices": device_list,
                "last_sync_at": latest_sync,
            },
            "policy": {
                "version": policy.version,
                "screenshot_interval_seconds": policy.screenshot_interval_seconds,
                "idle_threshold_seconds": policy.idle_threshold_seconds,
                "retention_days": policy.retention_days,
                "window_title_collection": policy.window_title_collection,
                "exclusion_rules": policy.exclusion_rules,
            },
            "privacy_notice": {
                "transparency_principles": [
                    "Monitoring is policy-driven, transparent, and auditable.",
                    "No keystroke logging, password capture, or private-message scraping.",
                    "Missing telemetry is an explicit gap — never assumed as active or productive work.",
                    "Screenshots exclude private apps and password managers.",
                    "You have the right to inspect all data collected about you and submit classification disputes.",
                ],
                "retention_days": policy.retention_days,
                "support_contact": f"privacy@{tenant.name.lower().replace(' ', '')}.com",
            },
            "recent_metrics": metrics_data,
            "disputes": disputes_data,
        }, status=status.HTTP_200_OK)


class DisputeListCreateView(APIView):
    """GET /api/disputes and POST /api/disputes (§11.3, E89)."""

    permission_classes = [IsTenantMember]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        qs = Dispute.objects.for_tenant(tenant).select_related("membership__user", "reviewed_by")

        if membership.role == MembershipRole.ADMIN or request.user.is_superuser:
            pass
        elif membership.role == MembershipRole.MANAGER:
            team_ids = get_manager_accessible_team_ids(membership)
            qs = qs.filter(membership__team_memberships__team_id__in=team_ids).distinct()
        else:
            qs = qs.filter(membership=membership)

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        serializer = DisputeSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        serializer = DisputeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity("Invalid dispute submission.", field_errors=serializer.errors)

        dispute = serializer.save(tenant=tenant, membership=membership)

        log_audit_event(
            action="dispute.created",
            resource_type="dispute",
            resource_id=str(dispute.id),
            actor=request.user,
            tenant=tenant,
            metadata={
                "target_app": dispute.target_app,
                "reason": dispute.reason,
                "desired_classification": dispute.desired_classification,
            },
            request=request,
        )

        return Response(DisputeSerializer(dispute).data, status=status.HTTP_201_CREATED)


class DisputeDetailView(APIView):
    """GET and PATCH /api/disputes/{id} (§11.3, E89)."""

    permission_classes = [IsTenantMember]

    def _get_dispute(self, request: Request, pk: uuid.UUID) -> Dispute:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        dispute = Dispute.objects.for_tenant(tenant).filter(id=pk).select_related("membership__user").first()
        if not dispute:
            raise EntityNotFound("Dispute not found.")

        # Check access
        if membership.role == MembershipRole.ADMIN or request.user.is_superuser:
            return dispute
        if membership.role == MembershipRole.MANAGER:
            team_ids = get_manager_accessible_team_ids(membership)
            is_member_in_team = TeamMember.objects.filter(membership=dispute.membership, team_id__in=team_ids).exists()
            if not is_member_in_team and dispute.membership != membership:
                raise EntityNotFound("Dispute not found.")
            return dispute
        if dispute.membership != membership:
            raise EntityNotFound("Dispute not found.")
        return dispute

    def get(self, request: Request, pk: uuid.UUID) -> Response:
        dispute = self._get_dispute(request, pk)
        return Response(DisputeSerializer(dispute).data, status=status.HTTP_200_OK)

    def patch(self, request: Request, pk: uuid.UUID) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant
        dispute = self._get_dispute(request, pk)

        new_status = request.data.get("status")
        resolution_notes = request.data.get("resolution_notes", "")

        # Employees can only cancel their own dispute
        if membership.role == MembershipRole.EMPLOYEE:
            if new_status and new_status == DisputeStatus.REJECTED:
                dispute.status = DisputeStatus.REJECTED
                dispute.resolution_notes = "Withdrawn by employee"
                dispute.save(update_fields=["status", "resolution_notes", "updated_at"])
                return Response(DisputeSerializer(dispute).data, status=status.HTTP_200_OK)
            raise UnprocessableEntity("Employees cannot resolve disputes; can only cancel.")

        # Managers / Admins can review, resolve, or reject
        if new_status:
            if new_status not in DisputeStatus.values:
                raise UnprocessableEntity(f"Invalid dispute status: {new_status}")
            dispute.status = new_status
            if new_status in (DisputeStatus.RESOLVED, DisputeStatus.REJECTED):
                dispute.resolved_at = timezone.now()
                dispute.reviewed_by = request.user

        if resolution_notes:
            dispute.resolution_notes = resolution_notes

        dispute.save()

        # If resolved and desired classification provided, update or create AppRule
        if dispute.status == DisputeStatus.RESOLVED and dispute.target_app and dispute.desired_classification:
            policy = MonitoringPolicy.get_or_create_default(tenant)
            AppRule.objects.update_or_create(
                tenant=tenant,
                policy=policy,
                app_identifier=dispute.target_app.lower(),
                defaults={
                    "classification": dispute.desired_classification,
                    "version": policy.version,
                },
            )

        log_audit_event(
            action="dispute.updated",
            resource_type="dispute",
            resource_id=str(dispute.id),
            actor=request.user,
            tenant=tenant,
            metadata={
                "status": dispute.status,
                "resolution_notes": dispute.resolution_notes,
                "resolved": dispute.status == DisputeStatus.RESOLVED,
            },
            request=request,
        )

        return Response(DisputeSerializer(dispute).data, status=status.HTTP_200_OK)
