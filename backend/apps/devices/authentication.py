"""Device authentication using per-device credentials (§2.1, §8.3, E24, E38, E40)."""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional, Tuple
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework import authentication, exceptions
from apps.common.exceptions import TenantSuspended
from apps.devices.models import AgentCredential, CredentialStatus, Device, DeviceStatus
from apps.tenancy.models import TenantStatus


class DeviceBearerAuthentication(authentication.BaseAuthentication):
    """Authenticates agent requests via per-device bearer credentials.

    Header format:
        Authorization: DeviceBearer <secret>
    """

    keyword = "DeviceBearer"

    def authenticate(self, request: authentication.Request) -> Optional[Tuple[Any, Device]]:
        auth_header = authentication.get_authorization_header(request).split()

        if not auth_header or auth_header[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth_header) != 2:
            raise exceptions.AuthenticationFailed("Invalid device bearer header. Expected 'DeviceBearer <secret>'.")

        try:
            raw_secret = auth_header[1].decode("utf-8")
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid device secret encoding.")

        secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

        try:
            credential = AgentCredential.objects.select_related("device__tenant", "device__membership__user").get(
                secret_hash=secret_hash
            )
        except AgentCredential.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or unassigned device credential.")

        device = credential.device
        if device.status == DeviceStatus.REVOKED or credential.status == CredentialStatus.REVOKED:
            # Immediate rejection for revoked devices (E24, E38)
            raise exceptions.PermissionDenied("Device access has been revoked.")

        if not credential.is_valid:
            raise exceptions.AuthenticationFailed("Device credential has expired or is invalid.")

        # Cross-device impersonation check (E40)
        device_id_header = request.headers.get("X-Device-ID")
        if device_id_header:
            try:
                target_device_id = uuid.UUID(device_id_header)
                if device.id != target_device_id:
                    raise exceptions.PermissionDenied("Device credential does not match the requested device ID.")
            except (ValueError, TypeError):
                raise exceptions.AuthenticationFailed("Invalid X-Device-ID header.")

        tenant = device.tenant
        if tenant.status == TenantStatus.SUSPENDED:
            raise TenantSuspended("Tenant organization is suspended.")
        if tenant.status == TenantStatus.DELETING:
            raise exceptions.NotFound("Tenant organization not found or is being deleted.")

        # Update last used timestamp
        credential.last_used_at = timezone.now()
        credential.save(update_fields=["last_used_at"])

        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_seen_at"])

        request.device = device  # type: ignore[attr-defined]
        request.tenant = tenant  # type: ignore[attr-defined]
        request.membership = device.membership  # type: ignore[attr-defined]

        user = device.membership.user if device.membership else AnonymousUser()
        return (user, device)

    def authenticate_header(self, request: authentication.Request) -> str:
        return self.keyword
