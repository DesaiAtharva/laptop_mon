"""Custom exception handler adhering strictly to §8.1 Error Contracts."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.response import Response
from apps.common.middleware import get_current_correlation_id

logger = logging.getLogger(__name__)


class ApplicationConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict detected."
    default_code = "conflict"


class TenantSuspended(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Tenant is currently suspended."
    default_code = "tenant_suspended"


class TenantDeleted(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Tenant not found or has been deleted."
    default_code = "tenant_deleted"


class MFARequired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Multi-Factor Authentication (MFA) is required for this role."
    default_code = "mfa_required"


class PayloadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Batch payload exceeds maximum size limit."
    default_code = "payload_too_large"


class RateLimitedException(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Ingestion rate limit exceeded. Please back off."
    default_code = "rate_limited"

    def __init__(self, detail: Optional[str] = None, retry_after: int = 60) -> None:
        super().__init__(detail=detail)
        self.retry_after = retry_after



def custom_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[Response]:
    """DRF exception handler formatting all error responses per §8.1.

    Response format:
    {
      "code": "machine_readable_stable_code",
      "message": "Human readable description",
      "field_errors": {},
      "correlation_id": "uuid"
    }
    """
    from rest_framework.views import exception_handler

    response = exception_handler(exc, context)
    correlation_id = get_current_correlation_id()

    if response is None:
        logger.exception("Unhandled server exception: %s", exc, extra={"correlation_id": correlation_id})
        return Response(
            {
                "code": "internal_server_error",
                "message": "An internal server error occurred.",
                "field_errors": {},
                "correlation_id": correlation_id,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = "error"
    message = "An error occurred."
    field_errors: Dict[str, Any] = {}

    if isinstance(exc, ValidationError):
        code = getattr(exc, "default_code", "validation_error")
        message = "Validation failed for provided parameters."
        if isinstance(exc.detail, dict):
            detail_dict = dict(exc.detail)
            if "code" in detail_dict:
                val = detail_dict.pop("code")
                code = str(val[0] if isinstance(val, list) else val)
            if "message" in detail_dict:
                val = detail_dict.pop("message")
                message = str(val[0] if isinstance(val, list) else val)
            field_errors = {
                k: [str(item) for item in (v if isinstance(v, list) else [v])]
                for k, v in detail_dict.items()
            }
        elif isinstance(exc.detail, list):
            field_errors = {"non_field_errors": [str(item) for item in exc.detail]}
        else:
            message = str(exc.detail)
    elif isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        code = "unauthenticated"
        message = getattr(exc, "detail", "Authentication credentials were not provided or are invalid.")
        if not isinstance(message, str):
            message = str(message)
    elif isinstance(exc, PermissionDenied):
        code = getattr(exc, "default_code", "permission_denied")
        message = getattr(exc, "detail", "You do not have permission to perform this action.")
        if not isinstance(message, str):
            message = str(message)
    elif isinstance(exc, NotFound):
        code = "not_found"
        message = getattr(exc, "detail", "Resource not found.")
        if not isinstance(message, str):
            message = str(message)
    elif isinstance(exc, APIException):
        code = getattr(exc.detail, "code", None) or getattr(exc, "code", None) or getattr(exc, "default_code", "api_error")
        message = getattr(exc, "detail", str(exc))
        if not isinstance(message, str):
            message = str(message)
    else:
        message = str(exc)

    formatted_data = {
        "code": code,
        "message": message,
        "field_errors": field_errors,
        "correlation_id": correlation_id,
    }

    response.data = formatted_data
    if isinstance(exc, RateLimitedException):
        response["Retry-After"] = str(exc.retry_after)
    return response
