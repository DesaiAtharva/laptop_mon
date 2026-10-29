"""Request ID correlation, Security Headers, and Size Limiter middleware (§3.2, §8.1, §15.2, REQ-3-1)."""
from __future__ import annotations

import contextvars
import json
import uuid
from typing import Callable, Optional
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

# Context variable storing current request correlation ID
correlation_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_current_correlation_id() -> str:
    """Retrieve the current request's correlation ID or generate a new one."""
    cid = correlation_id_ctx.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_ctx.set(cid)
    return cid


class RequestIDMiddleware:
    """Middleware that assigns a unique correlation ID to every incoming request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        request.correlation_id = correlation_id  # type: ignore[attr-defined]
        token = correlation_id_ctx.set(correlation_id)

        try:
            response = self.get_response(request)
        finally:
            correlation_id_ctx.reset(token)

        response["X-Correlation-ID"] = correlation_id
        return response


class SecurityHeadersMiddleware:
    """Middleware that injects strict security headers on all responses (§3.2, §15.2)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        # 1. Content Security Policy (strict dashboard & API protection)
        response["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )

        # 2. Frame Options (Clickjacking defense)
        response["X-Frame-Options"] = "DENY"

        # 3. MIME type sniffing prevention
        response["X-Content-Type-Options"] = "nosniff"

        # 4. Strict Transport Security (HSTS) (REQ-3-1)
        response["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # 5. Referrer Policy
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 6. Browser Feature & Permission Policy
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response


class RequestSizeLimiterMiddleware:
    """Middleware that enforces strict request body size caps, returning 413 on overflow (§8.1, E34)."""

    DEFAULT_MAX_BYTES = 15 * 1024 * 1024  # 15 MB for image uploads / batches
    JSON_MAX_BYTES = 2 * 1024 * 1024      # 2 MB for standard JSON APIs

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        content_length = request.META.get("CONTENT_LENGTH")
        if content_length:
            try:
                length = int(content_length)
                max_allowed = (
                    self.DEFAULT_MAX_BYTES
                    if request.path.startswith("/api/agent/screenshots")
                    else self.JSON_MAX_BYTES
                )

                if length > max_allowed:
                    cid = getattr(request, "correlation_id", str(uuid.uuid4()))
                    return JsonResponse(
                        {
                            "code": "payload_too_large",
                            "message": f"Request body size ({length} bytes) exceeds allowed limit ({max_allowed} bytes).",
                            "correlation_id": cid,
                        },
                        status=413,
                    )
            except (ValueError, TypeError):
                pass

        return self.get_response(request)
