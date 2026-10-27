"""Device enrollment and lifecycle service (§8.3, E23, E39, E40, E85)."""
from __future__ import annotations

import hashlib
from typing import Any, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.audit.services import log_audit_event
from apps.devices.models import AgentCredential, Device, DeviceStatus, EnrollmentToken
from apps.policies.models import MonitoringPolicy
from apps.tenancy.models import Tenant


def check_subscription_seat_limit(tenant: Tenant) -> None:
    """Subscription seat limit check hook (E85, detailed billing integration in P9)."""
    # Enforce default trial/seat cap of e.g. 50 devices per tenant if not on enterprise plan
    active_device_count = Device.objects.filter(tenant=tenant, status=DeviceStatus.ACTIVE).count()
    max_seats = 50  # Hook parameter
    if active_device_count >= max_seats:
        raise ValidationError({"detail": "Organization subscription device limit reached. Please upgrade plan."})


@transaction.atomic
def enroll_device(
    token_str: str,
    hostname: str,
    os_name: str,
    agent_version: str,
    hardware_id: str = "",
) -> Tuple[Device, str, MonitoringPolicy]:
    """Exchanges a single-use enrollment token for per-device credentials (§8.3, E39).

    Guarantees:
    - Replay prevention on tokens (E39)
    - Re-imaged device enrolls cleanly as a new device (E23)
    - Per-device unique credential generation (E40)
    - Subscription seat validation (E85)
    """
    token_hash = hashlib.sha256(token_str.strip().encode("utf-8")).hexdigest()

    token_obj = (
        EnrollmentToken.objects.select_for_update()
        .filter(token_hash=token_hash)
        .first()
    )

    if not token_obj or not token_obj.is_valid:
        raise ValidationError({"token": ["Invalid, expired, or already-consumed enrollment token."]})

    tenant = token_obj.tenant

    # Enforce seat limits
    check_subscription_seat_limit(tenant)

    # Re-imaging: If same hardware_id enrolled earlier, old device is superseded/retired (E23)
    if hardware_id:
        existing_devices = Device.objects.filter(
            tenant=tenant, hardware_id=hardware_id, status=DeviceStatus.ACTIVE
        )
        for d in existing_devices:
            d.revoke()

    # Create new device
    device = Device.objects.create(
        tenant=tenant,
        membership=token_obj.membership,
        hostname=hostname,
        os=os_name,
        agent_version=agent_version,
        hardware_id=hardware_id,
        status=DeviceStatus.ACTIVE,
        last_seen_at=timezone.now(),
    )

    # Issue per-device rotating credential (E40)
    credential, raw_secret = AgentCredential.create_secret_credential(device)

    # Consume token
    token_obj.use_count += 1
    token_obj.used_at = timezone.now()
    token_obj.save(update_fields=["use_count", "used_at", "updated_at"])

    # Retrieve or create default effective policy
    policy = MonitoringPolicy.get_or_create_default(tenant)

    log_audit_event(
        tenant=tenant,
        actor=token_obj.created_by,
        action="device.enrolled",
        resource_type="device",
        resource_id=str(device.id),
        metadata={
            "hostname": hostname,
            "os": os_name,
            "agent_version": agent_version,
            "hardware_id": hardware_id,
        },
    )

    return device, raw_secret, policy
