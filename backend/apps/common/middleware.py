"""Request ID correlation middleware."""
import contextvars
import uuid
from typing import Callable, Optional
from django.http import HttpRequest, HttpResponse

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
    """Middleware that assigns a unique correlation ID to every incoming request.

    Returns the correlation ID in the 'X-Correlation-ID' response header and
    makes it available throughout request processing.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Accept inbound correlation ID if provided, otherwise generate a fresh UUID v4
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Bind to request and contextvar
        request.correlation_id = correlation_id  # type: ignore[attr-defined]
        token = correlation_id_ctx.set(correlation_id)

        try:
            response = self.get_response(request)
        finally:
            correlation_id_ctx.reset(token)

        response["X-Correlation-ID"] = correlation_id
        return response
