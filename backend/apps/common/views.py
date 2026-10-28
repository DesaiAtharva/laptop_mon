"""Health, Readiness, and Observability endpoints (§12.1, §12.3, E87)."""
from __future__ import annotations

import time
from typing import Any, Dict
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.models import Device, DeviceStatus
from apps.screenshots.storage import get_storage_backend
from apps.tenancy.models import Tenant, TenantStatus

SERVER_START_TIME = time.time()


class LivenessCheckView(APIView):
    """GET /health/live — Fast liveness probe indicating process is responsive."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(
            {
                "status": "alive",
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class ReadinessCheckView(APIView):
    """GET /health/ready — Comprehensive readiness probe verifying DB, Cache, and Object Storage (E87)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        checks: Dict[str, str] = {}
        all_ready = True

        # 1. Database connectivity
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    checks["database"] = "healthy"
                else:
                    checks["database"] = "unhealthy"
                    all_ready = False
        except Exception as exc:
            checks["database"] = f"unhealthy: {exc}"
            all_ready = False

        # 2. Redis Cache connectivity
        try:
            cache_key = "health:ping"
            cache.set(cache_key, "pong", timeout=10)
            val = cache.get(cache_key)
            if val == "pong":
                checks["cache"] = "healthy"
            else:
                checks["cache"] = "unhealthy: cache read failed"
                all_ready = False
        except Exception as exc:
            checks["cache"] = f"unhealthy: {exc}"
            all_ready = False

        # 3. Object Storage backend connectivity
        try:
            storage = get_storage_backend()
            if hasattr(storage, "client"):
                # Real MinIO / S3 client
                storage.client.list_buckets()
                checks["storage"] = "healthy"
            else:
                # Memory backend or custom storage
                checks["storage"] = "healthy"
        except Exception as exc:
            checks["storage"] = f"unhealthy: {exc}"
            all_ready = False

        http_status = status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        response_payload = {
            "status": "ready" if all_ready else "degraded",
            "timestamp": timezone.now().isoformat(),
            "checks": checks,
        }
        return Response(response_payload, status=http_status)


class MetricsView(APIView):
    """GET /metrics — OpenMetrics/Prometheus exposition endpoint (§12.1, §12.3)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        uptime = int(time.time() - SERVER_START_TIME)

        try:
            active_tenants = Tenant.objects.filter(status=TenantStatus.ACTIVE).count()
            active_devices = Device.objects.filter(status=DeviceStatus.ACTIVE).count()
        except Exception:
            active_tenants = 0
            active_devices = 0

        lines = [
            "# HELP laptopmon_uptime_seconds Process uptime in seconds",
            "# TYPE laptopmon_uptime_seconds counter",
            f"laptopmon_uptime_seconds {uptime}",
            "# HELP laptopmon_active_tenants_count Number of active organizational tenants",
            "# TYPE laptopmon_active_tenants_count gauge",
            f"laptopmon_active_tenants_count {active_tenants}",
            "# HELP laptopmon_active_devices_count Number of active monitored devices",
            "# TYPE laptopmon_active_devices_count gauge",
            f"laptopmon_active_devices_count {active_devices}",
            "# HELP laptopmon_slo_api_availability Target API availability percentage",
            "# TYPE laptopmon_slo_api_availability gauge",
            "laptopmon_slo_api_availability 99.9",
            "# HELP laptopmon_slo_p95_ingestion_latency_seconds Target p95 ingestion latency threshold",
            "# TYPE laptopmon_slo_p95_ingestion_latency_seconds gauge",
            "laptopmon_slo_p95_ingestion_latency_seconds 30.0",
        ]

        metrics_text = "\n".join(lines) + "\n"
        return HttpResponse(metrics_text, content_type="text/plain; version=0.0.4; charset=utf-8")
