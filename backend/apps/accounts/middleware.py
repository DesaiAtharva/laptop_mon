"""Middleware validating session revocation state on authenticated requests."""
from typing import Callable
from django.http import HttpRequest, HttpResponse, JsonResponse
from apps.common.middleware import get_current_correlation_id


class SessionRevocationMiddleware:
    """Ensures that any session flagged as revoked immediately terminates the request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user_session = getattr(request, "user_session", None)
        if user_session is not None and not user_session.is_valid:
            return JsonResponse(
                {
                    "code": "session_revoked",
                    "message": "Session has been revoked or expired.",
                    "field_errors": {},
                    "correlation_id": get_current_correlation_id(),
                },
                status=401,
            )

        return self.get_response(request)
