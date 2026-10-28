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

from apps.analytics.models import AppUsageInterval, DailyMetrics, DataExport, ExportStatus, ExportType, IntervalState
from apps.analytics.serializers import (
    AppUsageIntervalSerializer,
    AppUsageSummarySerializer,
    DailyMetricsSerializer,
    DataExportSerializer,
    ExportRequestSerializer,
)
from apps.analytics.tasks import export_dataset_task
from apps.common.exceptions import EntityNotFound, UnprocessableEntity
from apps.rbac.permissions import IsTenantMember, get_manager_accessible_team_ids
from apps.tenancy.models import MembershipRole

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
