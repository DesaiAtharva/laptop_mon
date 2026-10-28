"""Billing business logic, quota enforcement, and webhook state machine (§15.3, E84, E85)."""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import log_audit_event
from apps.billing.models import (
    Plan,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
)
from apps.devices.models import Device, DeviceStatus
from apps.tenancy.models import Tenant

logger = logging.getLogger("billing")

DEFAULT_WEBHOOK_SECRET = getattr(settings, "BILLING_WEBHOOK_SECRET", "whsec_test_secret_for_payment_webhooks")


def enforce_subscription_seat_limit(tenant: Tenant) -> None:
    """Enforces per-tenant quotas server-side before enrolling devices (REQ-15-3, E85)."""
    sub = getattr(tenant, "subscription", None)

    # If subscription exists, verify status and seat quota
    if sub is not None:
        if sub.status in (SubscriptionStatus.CANCELED, SubscriptionStatus.UNPAID):
            raise ValidationError({
                "detail": "Organization subscription is canceled or unpaid. Device enrollment suspended (E85).",
                "code": "SUBSCRIPTION_INACTIVE",
            })

        active_device_count = Device.objects.filter(tenant=tenant, status=DeviceStatus.ACTIVE).count()
        if active_device_count >= sub.seat_count:
            raise ValidationError({
                "detail": (
                    f"Organization subscription seat limit ({sub.seat_count} seats) reached (E85). "
                    "Please upgrade plan or add seats."
                ),
                "code": "SEAT_LIMIT_REACHED",
            })
    else:
        # Default starter/trial cap if no formal subscription record yet (e.g. 10 devices)
        active_device_count = Device.objects.filter(tenant=tenant, status=DeviceStatus.ACTIVE).count()
        default_limit = 10
        if active_device_count >= default_limit:
            raise ValidationError({
                "detail": (
                    f"Organization trial seat limit ({default_limit} seats) reached (E85). "
                    "Please subscribe to a paid plan."
                ),
                "code": "SEAT_LIMIT_REACHED",
            })


def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: Optional[str] = None) -> bool:
    """Verify cryptographic HMAC-SHA256 signature on payment webhooks (E84)."""
    if not signature_header:
        return False

    sec = (secret or DEFAULT_WEBHOOK_SECRET).encode("utf-8")
    expected = hmac.new(sec, payload_bytes, hashlib.sha256).hexdigest()

    # Supports either raw hex digest or t=...,v1=... header format
    if signature_header.startswith("v1="):
        signature_hash = signature_header.split("v1=")[1].split(",")[0].strip()
    elif "v1=" in signature_header:
        for part in signature_header.split(","):
            if part.strip().startswith("v1="):
                signature_hash = part.split("=")[1].strip()
                break
        else:
            signature_hash = signature_header.strip()
    else:
        signature_hash = signature_header.strip()

    return hmac.compare_digest(expected, signature_hash)


@transaction.atomic
def process_billing_webhook(
    payload: Dict[str, Any],
    raw_payload_bytes: bytes,
    signature_header: str,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Processes incoming billing webhook adhering to idempotency and order-independent state machine (E84).

    Guarantees:
    - Signature verification (rejects unsigned/spoofed requests).
    - Idempotent processing: duplicate event IDs return 200 without duplicate state transition.
    - Order-independent state machine: older out-of-order events do not revert newer subscription states.
    - Audit logging of subscription updates and payment failures.
    """
    # 1. Signature check
    if not verify_webhook_signature(raw_payload_bytes, signature_header, secret):
        raise ValidationError({"detail": "Invalid webhook signature (E84).", "code": "INVALID_SIGNATURE"})

    event_id = payload.get("id")
    event_type = payload.get("type", "unknown")
    event_created = payload.get("created")

    if not event_id:
        raise ValidationError({"detail": "Missing event id in webhook payload.", "code": "MALFORMED_WEBHOOK"})

    # 2. Idempotency Check (E84)
    existing = WebhookEvent.objects.filter(event_id=event_id).first()
    if existing:
        logger.info("Webhook %s already processed with status %s. Skipping (E84).", event_id, existing.status)
        return {
            "status": "skipped_duplicate",
            "message": "Duplicate event acknowledged idempotently.",
            "event_id": event_id,
        }

    # Event timestamp
    if event_created:
        event_time = datetime.datetime.fromtimestamp(event_created, tz=datetime.timezone.utc)
    else:
        event_time = timezone.now()

    event_obj = payload.get("data", {}).get("object", {})
    external_sub_id = event_obj.get("subscription") or event_obj.get("id")
    external_cust_id = event_obj.get("customer")
    tenant_id_str = event_obj.get("metadata", {}).get("tenant_id")

    # Resolve subscription
    sub: Optional[Subscription] = None
    if external_sub_id:
        sub = Subscription.objects.filter(external_subscription_id=external_sub_id).first()
    if not sub and external_cust_id:
        sub = Subscription.objects.filter(external_customer_id=external_cust_id).first()
    if not sub and tenant_id_str:
        sub = Subscription.objects.filter(tenant_id=tenant_id_str).first()

    status_result = "processed"
    reverted_reason = None

    if sub:
        # 3. Order-independent state machine check (E84)
        if sub.last_event_timestamp and event_time < sub.last_event_timestamp:
            status_result = "skipped_out_of_order"
            reverted_reason = (
                f"Event time {event_time} is older than subscription's last processed "
                f"event time {sub.last_event_timestamp}. Dropping to prevent state regression (E84)."
            )
            logger.warning("Out-of-order billing event: %s", reverted_reason)
        else:
            # Apply state transition
            sub.last_event_timestamp = event_time

            if event_type in ("customer.subscription.created", "customer.subscription.updated"):
                new_status = event_obj.get("status", sub.status)
                if new_status in SubscriptionStatus.values:
                    sub.status = new_status
                if "quantity" in event_obj:
                    sub.seat_count = int(event_obj["quantity"])
                sub.save()

                log_audit_event(
                    action="billing.subscription_updated",
                    resource_type="subscription",
                    resource_id=str(sub.id),
                    tenant=sub.tenant,
                    metadata={"status": sub.status, "seat_count": sub.seat_count, "event_type": event_type},
                )

            elif event_type == "customer.subscription.deleted":
                sub.status = SubscriptionStatus.CANCELED
                sub.save()

                log_audit_event(
                    action="billing.subscription_canceled",
                    resource_type="subscription",
                    resource_id=str(sub.id),
                    tenant=sub.tenant,
                    metadata={"event_type": event_type},
                )

            elif event_type == "invoice.payment_failed":
                sub.status = SubscriptionStatus.PAST_DUE
                sub.save()

                log_audit_event(
                    action="billing.payment_failed",
                    resource_type="subscription",
                    resource_id=str(sub.id),
                    tenant=sub.tenant,
                    metadata={"event_type": event_type, "amount_due": event_obj.get("amount_due")},
                )

            elif event_type == "invoice.payment_succeeded":
                if sub.status == SubscriptionStatus.PAST_DUE:
                    sub.status = SubscriptionStatus.ACTIVE
                    sub.save()

    # Record WebhookEvent record
    WebhookEvent.objects.create(
        event_id=event_id,
        provider="stripe",
        event_type=event_type,
        payload=payload,
        status=status_result,
    )

    return {
        "status": status_result,
        "event_id": event_id,
        "event_type": event_type,
        "reverted_reason": reverted_reason,
    }
