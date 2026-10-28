"""Comprehensive tests for Prompt P9: Billing, Invitations, Email, and Tenant Lifecycle.

Requirements & Edge Cases:
- REQ-15-3: Per-tenant quotas enforced server-side.
- E43: Tenant suspended (blocks API/enrollment, audits, reversible).
- E44: Tenant deleted (cascade deletion across all related models, cache invalidated).
- E83: Invitation email delivery fails (async graceful error recording, UI link fallback).
- E84: Payment webhook duplicated or out of order (idempotency, HMAC verification, timestamp ordering).
- E85: Subscription limit reached (enrollment rejected with clear reason and upgrade path).
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.audit.models import AuditLog
from apps.billing.models import (
    Plan,
    Subscription,
    SubscriptionStatus,
    UsageRecord,
    WebhookEvent,
)
from apps.billing.services import (
    DEFAULT_WEBHOOK_SECRET,
    enforce_subscription_seat_limit,
    process_billing_webhook,
    verify_webhook_signature,
)
from apps.devices.models import Device, DeviceStatus
from apps.devices.services import check_subscription_seat_limit
from apps.tenancy.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Team,
    Tenant,
    TenantStatus,
)
from apps.tenancy.services import (
    accept_invitation,
    delete_tenant_cascade,
    send_invitation_email,
    suspend_tenant,
)


class P9BillingAndLifecycleTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        # Create Tenant
        self.tenant = Tenant.objects.create(name="Stark Industries", status=TenantStatus.ACTIVE)

        # Users
        self.admin_user = User.objects.create_user(
            email="tony@stark.com", name="Tony Stark", mfa_enabled=True
        )
        self.employee_user = User.objects.create_user(
            email="peter@stark.com", name="Peter Parker", mfa_enabled=False
        )

        # Memberships
        self.membership_admin = Membership.objects.create(
            tenant=self.tenant,
            user=self.admin_user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.membership_employee = Membership.objects.create(
            tenant=self.tenant,
            user=self.employee_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        # Plan & Subscription (2 seats)
        self.plan = Plan.objects.create(
            name="Starter Plan",
            slug="starter",
            seat_limit=2,
            price_per_seat_cents=500,
            features={"retention_days": 30},
        )
        self.subscription = Subscription.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            seat_count=2,
            status=SubscriptionStatus.ACTIVE,
            external_subscription_id="sub_test_12345",
            external_customer_id="cus_test_12345",
            last_event_timestamp=None,
        )

    def _auth_client(self, user: User, tenant: Tenant | None = None) -> APIClient:
        client = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        if tenant:
            client.defaults["HTTP_X_TENANT_ID"] = str(tenant.id)
        return client

    # --------------------------------------------------------------------------
    # REQ-15-3 & E85: Server-side seat quota enforcement
    # --------------------------------------------------------------------------
    def test_REQ_15_3_server_side_seat_quota_enforcement(self) -> None:
        """REQ-15-3: Server-side per-tenant quota enforcement.
        Enrolling up to max_seats succeeds; exceeding raises validation error."""
        # Active devices: 0 / 2
        enforce_subscription_seat_limit(self.tenant)

        # Enroll Device 1
        Device.objects.create(
            tenant=self.tenant,
            hostname="Laptop-01",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        # Active devices: 1 / 2 -> still allowed
        enforce_subscription_seat_limit(self.tenant)

        # Enroll Device 2
        Device.objects.create(
            tenant=self.tenant,
            hostname="Laptop-02",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )

        # Active devices: 2 / 2 -> reached limit. Further enrollment must be rejected (E85)
        with self.assertRaises(DRFValidationError) as ctx:
            enforce_subscription_seat_limit(self.tenant)
        self.assertEqual(ctx.exception.detail["code"], "SEAT_LIMIT_REACHED")

    def test_E85_subscription_limit_reached_and_upgrade(self) -> None:
        """E85: Subscription limit reached error handling and upgrade path."""
        # Create 2 active devices
        for i in range(2):
            Device.objects.create(
                tenant=self.tenant,
                hostname=f"Laptop-0{i}",
                os="windows",
                status=DeviceStatus.ACTIVE,
            )

        # check_subscription_seat_limit raises ValidationError
        with self.assertRaises(DRFValidationError) as ctx:
            check_subscription_seat_limit(self.tenant)
        self.assertIn("seat limit", str(ctx.exception.detail).lower())

        # Upgrade plan to 10 seats
        self.subscription.seat_count = 10
        self.subscription.save()

        # Now check_subscription_seat_limit passes
        check_subscription_seat_limit(self.tenant)

        # Inactive/canceled subscription blocks enrollment
        self.subscription.status = SubscriptionStatus.CANCELED
        self.subscription.save()
        with self.assertRaises(DRFValidationError) as ctx:
            check_subscription_seat_limit(self.tenant)
        self.assertEqual(ctx.exception.detail["code"], "SUBSCRIPTION_INACTIVE")

    # --------------------------------------------------------------------------
    # E83: Invitation email delivery failure
    # --------------------------------------------------------------------------
    def test_E83_invitation_email_delivery_failure_graceful_handling(self) -> None:
        """E83: When SMTP relay fails, invitation record persists with delivery_status='failed'
        and error message, returning the invitation token for UI link copy."""
        client = self._auth_client(self.admin_user, self.tenant)

        with patch("django.core.mail.send_mail", side_effect=Exception("SMTP Connection refused")):
            response = client.post(
                f"/api/tenants/{self.tenant.id}/invitations",
                {"email": "rhodey@stark.com", "role": "manager"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["delivery_status"], "failed")
        self.assertIn("SMTP Connection refused", data["delivery_error"])
        raw_token = data["invitation_token"]
        self.assertTrue(len(raw_token) > 10)

        # Verify record in database
        inv = Invitation.objects.get(email="rhodey@stark.com", tenant=self.tenant)
        self.assertEqual(inv.delivery_status, "failed")
        self.assertEqual(inv.status, InvitationStatus.PENDING)
        self.assertIn("SMTP Connection refused", inv.delivery_error)

        # The invitation can still be claimed with the token
        new_user = User.objects.create_user(email="rhodey@stark.com", name="James Rhodes")
        membership = accept_invitation(token_str=raw_token, user=new_user)
        self.assertEqual(membership.user, new_user)
        self.assertEqual(membership.role, MembershipRole.MANAGER)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvitationStatus.ACCEPTED)

    # --------------------------------------------------------------------------
    # E84: Payment webhook idempotency and out-of-order handling
    # --------------------------------------------------------------------------
    def test_E84_webhook_signature_verification(self) -> None:
        """E84: Payment webhook signature verification accepts valid HMAC and rejects invalid."""
        payload_bytes = b'{"id": "evt_test_sig", "type": "invoice.payment_succeeded"}'
        secret = "test_webhook_secret_key"

        expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

        # Valid raw signature
        self.assertTrue(verify_webhook_signature(payload_bytes, expected_sig, secret=secret))

        # Valid Stripe-style header (t=...,v1=...)
        stripe_header = f"t=1600000000,v1={expected_sig}"
        self.assertTrue(verify_webhook_signature(payload_bytes, stripe_header, secret=secret))

        # Invalid signature
        self.assertFalse(verify_webhook_signature(payload_bytes, "invalid_sig", secret=secret))
        self.assertFalse(verify_webhook_signature(payload_bytes, "", secret=secret))

    def test_E84_webhook_duplicate_idempotency(self) -> None:
        """E84: Duplicate payment webhook is detected and acknowledged idempotently without state re-execution."""
        payload = {
            "id": "evt_duplicate_test_001",
            "type": "customer.subscription.updated",
            "created": int(timezone.now().timestamp()),
            "data": {
                "object": {
                    "id": "sub_test_12345",
                    "status": "active",
                    "quantity": 5,
                }
            },
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = hmac.new(DEFAULT_WEBHOOK_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

        # First call: processes event
        res1 = process_billing_webhook(
            payload=payload,
            raw_payload_bytes=payload_bytes,
            signature_header=sig,
        )
        self.assertEqual(res1["status"], "processed")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.seat_count, 5)

        # Second call with exact same event ID: returns skipped_duplicate
        res2 = process_billing_webhook(
            payload=payload,
            raw_payload_bytes=payload_bytes,
            signature_header=sig,
        )
        self.assertEqual(res2["status"], "skipped_duplicate")
        self.assertIn("idempotently", res2["message"])

        # Ensure only 1 WebhookEvent record created
        self.assertEqual(WebhookEvent.objects.filter(event_id="evt_duplicate_test_001").count(), 1)

    def test_E84_webhook_out_of_order_protection(self) -> None:
        """E84: An older webhook arriving out of order does not overwrite a newer state."""
        now = timezone.now()
        # Subscription is currently active with recent timestamp
        self.subscription.status = SubscriptionStatus.ACTIVE
        self.subscription.last_event_timestamp = now
        self.subscription.save()

        # Older event timestamp (2 hours in past)
        older_time = now - datetime.timedelta(hours=2)
        payload = {
            "id": "evt_out_of_order_999",
            "type": "customer.subscription.deleted",
            "created": int(older_time.timestamp()),
            "data": {
                "object": {
                    "id": "sub_test_12345",
                    "status": "canceled",
                }
            },
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        sig = hmac.new(DEFAULT_WEBHOOK_SECRET.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

        res = process_billing_webhook(
            payload=payload,
            raw_payload_bytes=payload_bytes,
            signature_header=sig,
        )

        self.assertEqual(res["status"], "skipped_out_of_order")
        self.assertIn("older than subscription's last processed event time", res["reverted_reason"])

        # Verify subscription was NOT canceled
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    # --------------------------------------------------------------------------
    # E43: Tenant suspension
    # --------------------------------------------------------------------------
    def test_E43_tenant_suspension_and_reactivation(self) -> None:
        """E43: Tenant suspension transitions status, audits reason, and un-suspending restores access."""
        # Suspend tenant
        suspend_tenant(self.tenant, reason="Payment invoice past due 14 days", actor=self.admin_user)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.SUSPENDED)
        self.assertFalse(self.tenant.is_active)

        # Audit log written
        audit = AuditLog.objects.filter(action="tenant.suspended", tenant=self.tenant).first()
        self.assertIsNotNone(audit)
        self.assertIn("past due", audit.metadata.get("reason", ""))

        # Check API endpoint suspension control
        client = self._auth_client(self.admin_user, self.tenant)
        # Re-activate via API
        resp = client.post(
            f"/api/tenants/{self.tenant.id}/suspend",
            {"active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, TenantStatus.ACTIVE)
        self.assertTrue(self.tenant.is_active)

    # --------------------------------------------------------------------------
    # E44: Tenant cascade deletion
    # --------------------------------------------------------------------------
    def test_E44_tenant_cascade_deletion(self) -> None:
        """E44: Permanent tenant deletion cascades across all associated tables cleanly."""
        tenant_id = self.tenant.id

        # Create associated records: device, team, invitation, usage record
        Team.objects.create(tenant=self.tenant, name="Avionics")
        Device.objects.create(
            tenant=self.tenant,
            hostname="Tony-Mark-85",
            os="windows",
        )
        Invitation.create_invitation(
            tenant=self.tenant,
            email="pepper@stark.com",
            role=MembershipRole.MANAGER,
        )
        UsageRecord.objects.create(
            tenant=self.tenant,
            subscription=self.subscription,
            active_seats=2,
            active_devices=2,
            storage_bytes=1048576,
        )

        # Cascade delete tenant
        result = delete_tenant_cascade(tenant_id, actor=self.admin_user)
        self.assertTrue(result["success"])

        # Verify all records removed
        self.assertFalse(Tenant.objects.filter(id=tenant_id).exists())
        self.assertFalse(Membership.objects.filter(tenant_id=tenant_id).exists())
        self.assertFalse(Team.objects.filter(tenant_id=tenant_id).exists())
        self.assertFalse(Device.objects.filter(tenant_id=tenant_id).exists())
        self.assertFalse(Invitation.objects.filter(tenant_id=tenant_id).exists())
        self.assertFalse(Subscription.objects.filter(tenant_id=tenant_id).exists())
        self.assertFalse(UsageRecord.objects.filter(tenant_id=tenant_id).exists())

    # --------------------------------------------------------------------------
    # Billing API endpoints
    # --------------------------------------------------------------------------
    def test_billing_plans_and_overview_api(self) -> None:
        """Verify /api/billing/plans and /api/billing/overview endpoints."""
        client_admin = self._auth_client(self.admin_user, self.tenant)

        # 1. Plans list
        resp = client_admin.get("/api/billing/plans")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        plans_data = resp.json()
        self.assertTrue(len(plans_data) >= 1)
        self.assertEqual(plans_data[0]["slug"], "starter")

        # 2. Overview as Org Admin
        resp = client_admin.get("/api/billing/overview")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        overview = resp.json()
        self.assertEqual(overview["seat_limit"], 2)
        self.assertEqual(overview["active_device_count"], 0)
        self.assertEqual(overview["remaining_seats"], 2)
        self.assertTrue(overview["can_enroll_more"])

        # 3. Overview as Employee (RBAC denial)
        client_emp = self._auth_client(self.employee_user, self.tenant)
        resp = client_emp.get("/api/billing/overview")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
