"""Screenshot API views strictly adhering to §6.2, §8.3, §8.4, and §10."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from django.core.exceptions import PermissionDenied
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import (
    ApplicationConflict,
    ApplicationError,
    EntityNotFound,
    PayloadTooLarge,
    UnprocessableEntity,
)
from apps.devices.authentication import DeviceBearerAuthentication
from apps.devices.models import Device
from apps.rbac.permissions import (
    HasScreenshotPermission,
    IsOrgAdmin,
    IsTenantMember,
    get_manager_accessible_team_ids,
)
from apps.screenshots.models import Screenshot, ScreenshotStatus
from apps.screenshots.serializers import (
    LegalDeleteRequestSerializer,
    LegalHoldRequestSerializer,
    RetroactiveExclusionRequestSerializer,
    ScreenshotCompleteRequestSerializer,
    ScreenshotMetadataSerializer,
    ScreenshotUploadIntentRequestSerializer,
)
from apps.screenshots.services import (
    ChecksumMismatchError,
    ImageValidationError,
    ScreenshotServiceError,
    apply_legal_hold,
    apply_retroactive_exclusion,
    complete_screenshot_upload,
    create_upload_intent,
    execute_legal_deletion,
    generate_screenshot_view_url,
)
from apps.tenancy.models import MembershipRole

logger = logging.getLogger(__name__)


class AgentScreenshotUploadIntentView(APIView):
    """POST /api/agent/screenshots/upload-intents (§6.2, §8.3, E51)."""

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        device: Device = getattr(request, "device", None) or (request.user if isinstance(request.user, Device) else None)
        if not isinstance(device, Device):
            raise PermissionDenied("Authentication requires an active enrolled device credential.")

        serializer = ScreenshotUploadIntentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity(
                message="Invalid upload intent request schema.",
                field_errors=serializer.errors,
            )

        data = serializer.validated_data
        try:
            result = create_upload_intent(
                device=device,
                screenshot_id=data["screenshot_id"],
                captured_at=data["captured_at"],
                policy_version=data["policy_version"],
                content_type=data["content_type"],
                file_size=data["file_size"],
            )
            return Response(result, status=status.HTTP_200_OK)
        except ImageValidationError as e:
            raise UnprocessableEntity(message=str(e), code="INVALID_CONTENT_TYPE_OR_SIZE")
        except PermissionDenied as e:
            raise ApplicationError(message=str(e), code="DEVICE_OR_TENANT_REVOKED", status_code=403)


class AgentScreenshotCompleteView(APIView):
    """POST /api/agent/screenshots/complete (§6.2, §8.3, E52, E53)."""

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        device: Device = getattr(request, "device", None) or (request.user if isinstance(request.user, Device) else None)
        if not isinstance(device, Device):
            raise PermissionDenied("Authentication requires an active enrolled device credential.")

        serializer = ScreenshotCompleteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity(
                message="Invalid screenshot completion request schema.",
                field_errors=serializer.errors,
            )

        data = serializer.validated_data
        try:
            result = complete_screenshot_upload(
                device=device,
                screenshot_id=data["screenshot_id"],
                checksum=data["checksum"],
                file_size=data["file_size"],
                width=data.get("width"),
                height=data.get("height"),
            )
            return Response(result, status=status.HTTP_200_OK)
        except ChecksumMismatchError as e:
            raise ApplicationError(message=str(e), code="CHECKSUM_MISMATCH", status_code=400)
        except ImageValidationError as e:
            raise UnprocessableEntity(message=str(e), code="UNTRUSTED_IMAGE_REJECTED")
        except ScreenshotServiceError as e:
            msg = str(e)
            if "not found" in msg.lower():
                raise EntityNotFound(message=msg, code="SCREENSHOT_NOT_FOUND")
            if "already been deleted" in msg.lower():
                raise ApplicationConflict(message=msg, code="SCREENSHOT_DELETED")
            raise UnprocessableEntity(message=msg, code="FINALIZE_VERIFICATION_FAILED")


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class ScreenshotListView(APIView):
    """GET /api/screenshots (§8.4, §10.2).
    
    Metadata gallery search behind separate screenshot permission flag.
    """

    permission_classes = [IsTenantMember, HasScreenshotPermission]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        qs = Screenshot.objects.for_tenant(tenant).exclude(status=ScreenshotStatus.DELETED)

        # Scoping by role (§2.2, E47)
        if membership.role == MembershipRole.MANAGER:
            manager_team_ids = get_manager_accessible_team_ids(membership)
            qs = qs.filter(device__membership__team_memberships__team_id__in=manager_team_ids)
        elif membership.role == MembershipRole.EMPLOYEE:
            qs = qs.filter(device__membership=membership)

        device_id = request.query_params.get("device_id")
        if device_id:
            qs = qs.filter(device_id=device_id)

        from_date = request.query_params.get("from_date")
        if from_date:
            dt = parse_datetime(from_date)
            if dt:
                qs = qs.filter(captured_at__gte=dt)

        to_date = request.query_params.get("to_date")
        if to_date:
            dt = parse_datetime(to_date)
            if dt:
                qs = qs.filter(captured_at__lte=dt)

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ScreenshotMetadataSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ScreenshotViewUrlView(APIView):
    """POST /api/screenshots/{id}/view-url (§8.4, §10.2, REQ-10-4, E49)."""

    permission_classes = [IsTenantMember, HasScreenshotPermission]

    def post(self, request: Request, pk: uuid.UUID) -> Response:
        membership = getattr(request, "membership")
        correlation_id = getattr(request, "correlation_id", "")
        try:
            result = generate_screenshot_view_url(
                screenshot_id=pk,
                membership=membership,
                request_user=request.user,
                request_id=correlation_id,
            )
            return Response(result, status=status.HTTP_200_OK)
        except ScreenshotServiceError:
            # E45: Cross-tenant / non-existent returns safe 404
            raise EntityNotFound(message="Screenshot not found.", code="SCREENSHOT_NOT_FOUND")
        except PermissionDenied as e:
            raise ApplicationError(message=str(e), code="FORBIDDEN", status_code=403)


class ScreenshotLegalHoldView(APIView):
    """POST /api/screenshots/legal-hold (§11.2, E90)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        serializer = LegalHoldRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity(
                message="Invalid legal hold request data.",
                field_errors=serializer.errors,
            )

        data = serializer.validated_data
        correlation_id = getattr(request, "correlation_id", "")

        device = None
        if data.get("device_id"):
            device = Device.objects.for_tenant(membership.tenant).filter(id=data["device_id"]).first()
            if not device:
                raise EntityNotFound("Target device for legal hold not found.")

        hold_record = apply_legal_hold(
            tenant=membership.tenant,
            actor=request.user,
            reason=data["reason"],
            screenshot_ids=data.get("screenshot_ids"),
            device=device,
            request_id=correlation_id,
        )

        return Response(
            {
                "status": "applied",
                "hold_record_id": str(hold_record.id),
                "is_active": hold_record.is_active,
            },
            status=status.HTTP_200_OK,
        )


class ScreenshotLegalDeleteView(APIView):
    """POST /api/screenshots/legal-delete (§11.2, E90)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        serializer = LegalDeleteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity(
                message="Invalid legal deletion request data.",
                field_errors=serializer.errors,
            )

        data = serializer.validated_data
        correlation_id = getattr(request, "correlation_id", "")

        result = execute_legal_deletion(
            tenant=membership.tenant,
            actor=request.user,
            reason=data["reason"],
            screenshot_ids=data["screenshot_ids"],
            request_id=correlation_id,
        )

        return Response(result, status=status.HTTP_200_OK)


class ScreenshotRetroactiveExclusionView(APIView):
    """POST /api/screenshots/retroactive-exclusion (E55)."""

    permission_classes = [IsOrgAdmin]

    def post(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        serializer = RetroactiveExclusionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise UnprocessableEntity(
                message="Invalid retroactive exclusion request data.",
                field_errors=serializer.errors,
            )

        data = serializer.validated_data
        correlation_id = getattr(request, "correlation_id", "")

        result = apply_retroactive_exclusion(
            tenant=membership.tenant,
            actor=request.user,
            app_identifier=data["app_identifier"],
            action=data["action"],
            policy_version=data["policy_version"],
            request_id=correlation_id,
        )

        return Response(result, status=status.HTTP_200_OK)


class RawBinaryUploadParser:
    """Accepts raw binary bytes for presigned image uploads."""
    media_type = "*/*"

    def parse(self, stream: Any, media_type: Optional[str] = None, parser_context: Optional[Dict[str, Any]] = None) -> bytes:
        return stream.read()


class StorageUploadView(APIView):
    """PUT /api/agent/screenshots/storage-upload (Direct presigned upload)."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    parser_classes = [RawBinaryUploadParser]

    def put(self, request: Request) -> Response:
        import hashlib, hmac
        from django.conf import settings
        from django.utils import timezone
        from apps.screenshots.storage import get_storage_backend

        key = request.query_params.get("key")
        content_type = request.query_params.get("type", "image/jpeg")
        expires_str = request.query_params.get("expires")
        sig = request.query_params.get("sig")

        if not (key and expires_str and sig):
            return Response({"error": "Missing key, expires, or sig parameter."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exp_ts = int(expires_str)
            if int(timezone.now().timestamp()) > exp_ts:
                return Response({"error": "Presigned upload URL has expired."}, status=status.HTTP_403_FORBIDDEN)
        except ValueError:
            return Response({"error": "Invalid expires parameter."}, status=status.HTTP_400_BAD_REQUEST)

        secret = getattr(settings, "SECRET_KEY", "fallback-secret").encode("utf-8")
        expected_sig = hmac.new(secret, f"upload:{key}:{content_type}:{exp_ts}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning("Storage upload signature mismatch: got %s vs expected %s for key=%s", sig, expected_sig, key)
            return Response({"error": "Invalid signature."}, status=status.HTTP_403_FORBIDDEN)

        storage = get_storage_backend()
        data = request.data if isinstance(request.data, bytes) else request.body
        storage.put_object_bytes(key, data, content_type)
        return Response(status=status.HTTP_200_OK)


class StorageViewView(APIView):
    """GET /api/screenshots/storage-view (Direct presigned view)."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Any:
        import hashlib, hmac
        from django.conf import settings
        from django.http import HttpResponse
        from django.utils import timezone
        from apps.screenshots.storage import get_storage_backend

        key = request.query_params.get("key")
        expires_str = request.query_params.get("expires")
        sig = request.query_params.get("sig")

        if not (key and expires_str and sig):
            return Response({"error": "Missing key, expires, or sig."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exp_ts = int(expires_str)
            if int(timezone.now().timestamp()) > exp_ts:
                return Response({"error": "Presigned view URL has expired."}, status=status.HTTP_403_FORBIDDEN)
        except ValueError:
            return Response({"error": "Invalid expires parameter."}, status=status.HTTP_400_BAD_REQUEST)

        secret = getattr(settings, "SECRET_KEY", "fallback-secret").encode("utf-8")
        expected_sig = hmac.new(secret, f"view:{key}:{exp_ts}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return Response({"error": "Invalid signature."}, status=status.HTTP_403_FORBIDDEN)

        storage = get_storage_backend()
        if not storage.object_exists(key):
            return Response({"error": "Screenshot object not found."}, status=status.HTTP_404_NOT_FOUND)

        data = storage.get_object_bytes(key)
        content_type = "image/webp" if key.endswith(".webp") else "image/jpeg"
        return HttpResponse(data, content_type=content_type)
