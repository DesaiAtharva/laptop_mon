"""Tenant context resolution and enforcement middleware (E43, E44, E45, E46)."""
from __future__ import annotations

from typing import Callable
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework.exceptions import APIException
from apps.common.middleware import get_current_correlation_id
from apps.tenancy.context import resolve_tenant_context


class TenantContextMiddleware:
    """Enforces tenant isolation and resolves the active tenant context for non-DRF views."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        try:
            resolve_tenant_context(request, user)
        except APIException as exc:
            return JsonResponse(
                {
                    "code": getattr(exc, "default_code", "error"),
                    "message": getattr(exc, "detail", str(exc)),
                    "field_errors": {},
                    "correlation_id": get_current_correlation_id(),
                },
                status=exc.status_code,
            )

        return self.get_response(request)
