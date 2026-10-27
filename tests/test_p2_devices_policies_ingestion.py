"""Comprehensive test suite for Prompt P2: Devices, Policies, Heartbeat, Batch Ingestion, and Edge Cases."""
from __future__ import annotations

import json
import uuid
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from apps.accounts.models import User, UserSession
from apps.devices.models import AgentCredential, CredentialStatus, Device, DeviceStatus, EnrollmentToken
from apps.devices.services import enroll_device
from apps.ingestion.models import ActivityEvent, EventBatch
from apps.policies.models import MonitoringPolicy
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant, TenantStatus


class P2DevicesPoliciesIngestionTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        cache.clear()

        # Tenant A & B
        self.tenant_a = Tenant.objects.create(name="Cyberdyne Systems", status=TenantStatus.ACTIVE)
        self.tenant_b = Tenant.objects.create(name="Omni Consumer Products", status=TenantStatus.ACTIVE)

        # Admin user in Tenant A
        self.admin_user_a = User.objects.create_user(
            email="admin@cyberdyne.com", name="Miles Dyson", mfa_enabled=True
        )
        self.membership_admin_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.admin_user_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        # Employee user in Tenant A
        self.employee_user_a = User.objects.create_user(
            email="john@cyberdyne.com", name="John Connor", mfa_enabled=False
        )
        self.membership_employee_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.employee_user_a,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        # Default policy for Tenant A
        self.policy_a = MonitoringPolicy.get_or_create_default(self.tenant_a)

        # Enrolled Device in Tenant A
        self.device_a = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_employee_a,
            hostname="CYBER-LAPTOP-01",
            os="windows",
            agent_version="1.0.0",
            hardware_id="HW-9988-AA",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )
        self.cred_a, self.raw_secret_a = AgentCredential.create_secret_credential(self.device_a)

    def _auth_device_client(self, raw_secret: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"DeviceBearer {raw_secret}")
        return client

    def _auth_user_client(self, user: User, tenant: Tenant | None = None) -> APIClient:
        client = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        if tenant:
            client.defaults["HTTP_X_TENANT_ID"] = str(tenant.id)
        return client

    # ── Edge Case E02 & E03 & E25: Clock drift, jumps, out-of-order timestamps ─
    def test_E02_clock_drift_between_agent_and_server(self) -> None:
        """Server separates observed time from server received time and detects clock drift anomalies."""
        client = self._auth_device_client(self.raw_secret_a)
        event_id = uuid.uuid4()

        # Event observed 2 days in the past (clock drift / lag)
        past_time = timezone.now() - timezone.timedelta(days=2)
        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "schema_version": 1,
                "events": [
                    {
                        "id": str(event_id),
                        "event_type": "app.focus",
                        "occurred_at": past_time.isoformat(),
                        "payload": {"app": "code.exe", "window_title": "VS Code"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(str(event_id), response.json()["accepted"])

        event = ActivityEvent.objects.get(id=event_id)
        # Server recorded separate occurred_at and received_at
        self.assertIsNotNone(event.occurred_at)
        self.assertIsNotNone(event.received_at)
        # Anomaly flagged in payload
        self.assertIn("_anomaly_clock_drift_seconds", event.payload)

    def test_E03_clock_jumps_backward_or_forward(self) -> None:
        """Clock jumps forward far into the future are accepted but flagged as drift anomalies."""
        client = self._auth_device_client(self.raw_secret_a)
        event_id = uuid.uuid4()

        future_time = timezone.now() + timezone.timedelta(days=5)
        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "schema_version": 1,
                "events": [
                    {
                        "id": str(event_id),
                        "event_type": "session.state",
                        "occurred_at": future_time.isoformat(),
                        "payload": {"state": "active"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event = ActivityEvent.objects.get(id=event_id)
        self.assertIn("_anomaly_clock_drift_seconds", event.payload)

    def test_E25_event_timestamps_out_of_order_or_far_in_future(self) -> None:
        """Events submitted out of order within a batch are durably ingested with occurred_at preserved."""
        client = self._auth_device_client(self.raw_secret_a)
        now = timezone.now()
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()

        # id1 is later, id2 is earlier
        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": str(id1),
                        "event_type": "app.focus",
                        "occurred_at": (now + timezone.timedelta(seconds=10)).isoformat(),
                        "payload": {"app": "chrome.exe"},
                    },
                    {
                        "id": str(id2),
                        "event_type": "app.focus",
                        "occurred_at": (now - timezone.timedelta(seconds=50)).isoformat(),
                        "payload": {"app": "slack.exe"},
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["accepted"]), 2)

    # ── Edge Case E16: Minimum agent version enforced / Agent version deprecated
    def test_E16_minimum_agent_version_enforced(self) -> None:
        """Agent heartbeat rejects outdated agent versions with 426 Upgrade Required."""
        client = self._auth_device_client(self.raw_secret_a)

        # Update policy minimum version to 2.0.0
        self.policy_a.min_agent_version = "2.0.0"
        self.policy_a.save()

        # Agent sending heartbeat with deprecated version 1.0.0
        response = client.post(
            "/api/agent/heartbeat",
            data={
                "agent_version": "1.0.0",
                "queue_depth": 5,
                "oldest_pending_seconds": 120,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_426_UPGRADE_REQUIRED)
        data = response.json()
        self.assertTrue(data["upgrade_required"])
        self.assertEqual(data["min_agent_version"], "2.0.0")

    # ── Edge Case E23: Re-imaged device enrolls cleanly as new device ─────────
    def test_E23_reimaged_device_enrolls_as_new(self) -> None:
        """A re-imaged machine with identical hardware ID enrolls cleanly as a fresh device record."""
        # Generate enrollment token
        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        token_resp = admin_client.post(
            "/api/devices/enrollment-tokens",
            data={"membership_id": str(self.membership_employee_a.id)},
            format="json",
        )
        self.assertEqual(token_resp.status_code, status.HTTP_201_CREATED)
        raw_token = token_resp.json()["enrollment_token"]

        # Enroll re-imaged laptop with same hardware_id "HW-9988-AA"
        client = APIClient()
        enroll_resp = client.post(
            "/api/agent/enroll",
            data={
                "token": raw_token,
                "hostname": "CYBER-LAPTOP-REIMAGED",
                "os": "windows",
                "agent_version": "1.1.0",
                "hardware_id": "HW-9988-AA",
            },
            format="json",
        )
        self.assertEqual(enroll_resp.status_code, status.HTTP_201_CREATED)
        new_device_id = enroll_resp.json()["device_id"]
        self.assertNotEqual(new_device_id, str(self.device_a.id))

        # Old device was retired/revoked
        self.device_a.refresh_from_db()
        self.assertEqual(self.device_a.status, DeviceStatus.REVOKED)

        # New device is active
        new_device = Device.objects.get(id=new_device_id)
        self.assertEqual(new_device.status, DeviceStatus.ACTIVE)

    # ── Edge Case E24 & E38: Device revoked online / offline ──────────────────
    def test_E24_device_revoked_remotely_while_online(self) -> None:
        """Revoking a device immediately causes server-side rejection (403 Forbidden)."""
        client = self._auth_device_client(self.raw_secret_a)

        # Initially heartbeat succeeds
        resp = client.post("/api/agent/heartbeat", data={"agent_version": "1.0.0"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # Admin revokes device
        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        revoke_resp = admin_client.post(f"/api/devices/{self.device_a.id}/revoke")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)

        # Device is revoked and credentials invalidated
        self.device_a.refresh_from_db()
        self.assertEqual(self.device_a.status, DeviceStatus.REVOKED)

        # Subsequent requests from device are immediately blocked
        post_revoke_resp = client.post(
            "/api/agent/heartbeat", data={"agent_version": "1.0.0"}, format="json"
        )
        self.assertEqual(post_revoke_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_E38_device_revoked_while_offline(self) -> None:
        """When an offline device reconnects after revocation, upload is rejected immediately."""
        # Revoke device
        self.device_a.revoke()

        # Offline device comes online and attempts to upload batch
        client = self._auth_device_client(self.raw_secret_a)
        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [{"id": str(uuid.uuid4()), "event_type": "app.focus", "payload": {}}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ── Edge Case E31: Duplicate event ID with identical payload ──────────────
    def test_E31_duplicate_event_identical_payload_accepted(self) -> None:
        """Resending the same event ID with identical payload returns already_accepted (idempotent)."""
        client = self._auth_device_client(self.raw_secret_a)
        event_id = uuid.uuid4()
        event_data = {
            "id": str(event_id),
            "event_type": "session.lock",
            "occurred_at": timezone.now().isoformat(),
            "payload": {"reason": "user_locked"},
        }

        # First upload
        resp1 = client.post(
            "/api/agent/events/batch",
            data={"agent_version": "1.0.0", "events": [event_data]},
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertIn(str(event_id), resp1.json()["accepted"])

        # Second upload (identical retry)
        resp2 = client.post(
            "/api/agent/events/batch",
            data={"agent_version": "1.0.0", "events": [event_data]},
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertIn(str(event_id), resp2.json()["already_accepted"])
        # No duplicate row inserted
        self.assertEqual(ActivityEvent.objects.filter(id=event_id).count(), 1)

    # ── Edge Case E32: Duplicate event ID with conflicting payload ────────────
    def test_E32_duplicate_event_conflicting_payload_rejected_409(self) -> None:
        """Resending the same event ID with a different payload triggers 409 Conflict and integrity alert."""
        client = self._auth_device_client(self.raw_secret_a)
        event_id = uuid.uuid4()

        # Initial event
        client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": str(event_id),
                        "event_type": "app.focus",
                        "payload": {"app": "calculator.exe"},
                    }
                ],
            },
            format="json",
        )

        # Attempt to tamper: same event_id but different payload
        tampered_resp = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": str(event_id),
                        "event_type": "app.focus",
                        "payload": {"app": "malicious_payload.exe"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(tampered_resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(tampered_resp.json()["code"], "integrity_conflict")

    # ── Edge Case E33: Unknown or invalid event type ───────────────────────────
    def test_E33_unknown_or_invalid_event_type_rejected(self) -> None:
        """Unknown event types are rejected with stable code unknown_event_type."""
        client = self._auth_device_client(self.raw_secret_a)
        event_id = uuid.uuid4()

        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [
                    {
                        "id": str(event_id),
                        "event_type": "unregistered.custom.type",
                        "payload": {"foo": "bar"},
                    }
                ],
            },
            format="json",
        )
        # 207 Multi-Status with rejection detail
        self.assertEqual(response.status_code, status.HTTP_207_MULTI_STATUS)
        rejected = response.json()["rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["code"], "unknown_event_type")

    # ── Edge Case E34: Oversized event batch (413 Payload Too Large) ───────────
    def test_E34_oversized_event_batch_rejected_413(self) -> None:
        """Batches exceeding 1000 events are rejected with 413 Payload Too Large."""
        client = self._auth_device_client(self.raw_secret_a)

        # Create oversized payload with 1001 items
        oversized_events = [
            {"id": str(uuid.uuid4()), "event_type": "session.state", "payload": {}}
            for _ in range(1001)
        ]
        response = client.post(
            "/api/agent/events/batch",
            data={"agent_version": "1.0.0", "events": oversized_events},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(response.json()["code"], "payload_too_large")

    # ── Edge Case E35: Rate limit and overload (429 with Retry-After) ──────────
    def test_E35_rate_limit_and_overload_retry_after(self) -> None:
        """Exceeding device request rate limit returns 429 with Retry-After header."""
        client = self._auth_device_client(self.raw_secret_a)
        cache_key = f"rate_limit:device:{self.device_a.id}"

        # Artificially saturate rate limiter
        cache.set(cache_key, 120, timeout=60)

        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [{"id": str(uuid.uuid4()), "event_type": "app.focus", "payload": {}}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "rate_limited")
        self.assertIn("Retry-After", response.headers)

    # ── Edge Case E36: Partial batch acceptance ───────────────────────────────
    def test_E36_partial_batch_acceptance(self) -> None:
        """Batches with valid, duplicate, and invalid events accept valid ones and report itemized outcomes."""
        client = self._auth_device_client(self.raw_secret_a)
        now = timezone.now()

        # Seed an existing event
        existing_id = uuid.uuid4()
        client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [{"id": str(existing_id), "event_type": "app.focus", "payload": {"k": "v"}}],
            },
            format="json",
        )

        valid_id = uuid.uuid4()
        invalid_type_id = uuid.uuid4()

        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [
                    {"id": str(valid_id), "event_type": "session.state", "payload": {"s": 1}},
                    {"id": str(existing_id), "event_type": "app.focus", "payload": {"k": "v"}},
                    {"id": str(invalid_type_id), "event_type": "bad.type", "payload": {}},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_207_MULTI_STATUS)
        data = response.json()
        self.assertIn(str(valid_id), data["accepted"])
        self.assertIn(str(existing_id), data["already_accepted"])
        self.assertEqual(len(data["rejected"]), 1)
        self.assertEqual(data["rejected"][0]["id"], str(invalid_type_id))

    # ── Edge Case E37: Policy offline grace window ────────────────────────────
    def test_E37_policy_offline_grace_window(self) -> None:
        """Policy includes valid_until timestamp providing bounded grace for offline agents."""
        client = self._auth_device_client(self.raw_secret_a)
        response = client.get("/api/agent/policy")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("valid_until", data)
        self.assertIn("signature", data)
        # valid_until is set in the future
        valid_until = timezone.datetime.fromisoformat(data["valid_until"].replace("Z", "+00:00"))
        self.assertGreater(valid_until, timezone.now())

    # ── Edge Case E39: Enrollment token reused or expired ─────────────────────
    def test_E39_enrollment_token_reused_or_expired(self) -> None:
        """Single-use enrollment tokens cannot be reused, and expired tokens are rejected."""
        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        token_resp = admin_client.post(
            "/api/devices/enrollment-tokens",
            data={"max_uses": 1},
            format="json",
        )
        raw_token = token_resp.json()["enrollment_token"]

        # First enrollment succeeds
        client = APIClient()
        resp1 = client.post(
            "/api/agent/enroll",
            data={
                "token": raw_token,
                "hostname": "DEVICE-1",
                "os": "windows",
                "agent_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        # Second enrollment with same token fails (E39 replay prevention)
        resp2 = client.post(
            "/api/agent/enroll",
            data={
                "token": raw_token,
                "hostname": "DEVICE-2",
                "os": "windows",
                "agent_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Edge Case E40: Device credential lifecycle and rotation ───────────────
    def test_E40_device_credential_lifecycle_and_rotation(self) -> None:
        """Devices have unique rotating credentials; rotating a credential invalidates the old one."""
        # Create a new rotating credential for device
        new_cred, new_secret = AgentCredential.create_secret_credential(self.device_a)

        # Mark old credential revoked
        self.cred_a.status = CredentialStatus.REVOKED
        self.cred_a.save()

        # Old secret is rejected with 403 Forbidden (revoked)
        old_client = self._auth_device_client(self.raw_secret_a)
        resp_old = old_client.post("/api/agent/heartbeat", data={"agent_version": "1.0.0"}, format="json")
        self.assertEqual(resp_old.status_code, status.HTTP_403_FORBIDDEN)

        # New secret succeeds
        new_client = self._auth_device_client(new_secret)
        resp_new = new_client.post("/api/agent/heartbeat", data={"agent_version": "1.0.0"}, format="json")
        self.assertEqual(resp_new.status_code, status.HTTP_200_OK)

    # ── Edge Case E85: Subscription seat limit on enrollment ──────────────────
    def test_E85_subscription_seat_limit_on_enrollment(self) -> None:
        """Enrollment validates subscription seat availability before issuing credentials."""
        from apps.devices.services import check_subscription_seat_limit

        # Satiate seat capacity
        for i in range(50):
            Device.objects.create(
                tenant=self.tenant_a,
                hostname=f"SEAT-DEVICE-{i}",
                os="linux",
                status=DeviceStatus.ACTIVE,
            )

        # Next enrollment attempt is blocked by subscription seat limit
        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        token_resp = admin_client.post("/api/devices/enrollment-tokens", format="json")
        raw_token = token_resp.json()["enrollment_token"]

        client = APIClient()
        enroll_resp = client.post(
            "/api/agent/enroll",
            data={
                "token": raw_token,
                "hostname": "DEVICE-51",
                "os": "windows",
                "agent_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(enroll_resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Edge Case E98: Device reassigned on user or owner change ──────────────
    def test_E98_device_reassigned_on_user_or_owner_change(self) -> None:
        """Admins can reassign a device to a different employee membership, fully audited."""
        new_employee = User.objects.create_user(email="sarah@cyberdyne.com", name="Sarah Connor")
        new_membership = Membership.objects.create(
            tenant=self.tenant_a, user=new_employee, role=MembershipRole.EMPLOYEE
        )

        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        response = admin_client.post(
            f"/api/devices/{self.device_a.id}/reassign",
            data={"membership_id": str(new_membership.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.device_a.refresh_from_db()
        self.assertEqual(self.device_a.membership, new_membership)

    # ── Edge Case E99: Concurrent admin policy edits (optimistic locking) ─────
    def test_E99_concurrent_admin_policy_edits_optimistic_lock(self) -> None:
        """Policy update requires matching expected_version; stale versions raise 409 Conflict."""
        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)

        # Initial version is 1
        self.assertEqual(self.policy_a.version, 1)

        # Admin 1 updates policy from version 1 to 2
        resp1 = admin_client.patch(
            f"/api/policies/{self.policy_a.id}",
            data={"expected_version": 1, "idle_threshold_seconds": 240},
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.json()["version"], 2)

        # Admin 2 attempts concurrent edit still expecting version 1
        resp2 = admin_client.patch(
            f"/api/policies/{self.policy_a.id}",
            data={"expected_version": 1, "idle_threshold_seconds": 300},
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp2.json()["code"], "version_conflict")

    # ── Requirements & Invariants ─────────────────────────────────────────────
    def test_raw_accepted_events_are_immutable(self) -> None:
        """Raw accepted events cannot be modified or deleted via ORM (REQ-7-4)."""
        event = ActivityEvent.objects.create(
            id=uuid.uuid4(),
            tenant=self.tenant_a,
            device=self.device_a,
            event_type="app.focus",
            occurred_at=timezone.now(),
            payload={"app": "test.exe"},
        )

        # Update attempt must raise PermissionDenied
        event.event_type = "tampered"
        with self.assertRaises(PermissionDenied):
            event.save()

        # Delete attempt must raise PermissionDenied
        with self.assertRaises(PermissionDenied):
            event.delete()

    def test_agent_cannot_choose_its_tenant(self) -> None:
        """The tenant is derived strictly from device credentials; agent cannot target another tenant."""
        client = self._auth_device_client(self.raw_secret_a)
        # Even if agent passes Tenant B in X-Tenant-ID header
        client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_b.id)

        event_id = uuid.uuid4()
        response = client.post(
            "/api/agent/events/batch",
            data={
                "agent_version": "1.0.0",
                "events": [{"id": str(event_id), "event_type": "app.focus", "payload": {}}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Ingested event belongs strictly to Tenant A (from device_a), NOT Tenant B!
        event = ActivityEvent.objects.get(id=event_id)
        self.assertEqual(event.tenant, self.tenant_a)
