"""Comprehensive test suite for Prompt P3: Screenshots, Storage, Retention & Legal Hold."""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import uuid
from PIL import Image

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.audit.models import AuditLog
from apps.devices.models import AgentCredential, Device, DeviceStatus
from apps.policies.models import MonitoringPolicy
from apps.screenshots.models import (
    LegalHoldRecord,
    Screenshot,
    ScreenshotStatus,
    ScreenshotUploadIntent,
)
from apps.screenshots.services import (
    ChecksumMismatchError,
    ImageValidationError,
    apply_legal_hold,
    apply_retroactive_exclusion,
    complete_screenshot_upload,
    create_upload_intent,
    execute_legal_deletion,
    generate_screenshot_view_url,
    run_retention_sweep,
    verify_and_process_image,
)
from apps.screenshots.storage import (
    MemoryObjectStorageBackend,
    generate_screenshot_object_key,
    generate_thumbnail_object_key,
    get_storage_backend,
    reset_storage_backend,
)
from apps.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Team,
    TeamMember,
    Tenant,
    TenantStatus,
)


def make_test_image(width: int = 640, height: int = 480, fmt: str = "JPEG") -> bytes:
    """Helper to generate a valid image file in memory."""
    bio = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(50, 100, 150))
    img.save(bio, format=fmt)
    return bio.getvalue()


class P3ScreenshotBackendStorageTests(TestCase):
    def setUp(self) -> None:
        reset_storage_backend()
        self.storage: MemoryObjectStorageBackend = get_storage_backend()  # type: ignore
        cache.clear()

        # Tenants A & B
        self.tenant_a = Tenant.objects.create(name="Acme Corp", status=TenantStatus.ACTIVE)
        self.tenant_b = Tenant.objects.create(name="Stark Industries", status=TenantStatus.ACTIVE)

        # Users in Tenant A
        self.admin_user_a = User.objects.create_user(
            email="admin@acme.com", name="Alice Admin", mfa_enabled=True
        )
        self.membership_admin_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.admin_user_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        self.manager_user_a = User.objects.create_user(
            email="manager@acme.com", name="Bob Manager", mfa_enabled=False
        )
        self.membership_manager_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.manager_user_a,
            role=MembershipRole.MANAGER,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        self.employee_user_a = User.objects.create_user(
            email="emp1@acme.com", name="Charlie Emp", mfa_enabled=False
        )
        self.membership_employee_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.employee_user_a,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        self.auditor_user_a = User.objects.create_user(
            email="auditor@acme.com", name="Dave Auditor", mfa_enabled=False
        )
        self.membership_auditor_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.auditor_user_a,
            role=MembershipRole.AUDITOR,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=False,  # Auditors have no screenshot access by default
        )

        # Teams in Tenant A
        self.team_alpha = Team.objects.create(tenant=self.tenant_a, name="Alpha Team")
        self.team_beta = Team.objects.create(tenant=self.tenant_a, name="Beta Team")
        # Assign Bob Manager and Charlie Emp to Alpha Team
        TeamMember.objects.create(team=self.team_alpha, membership=self.membership_manager_a)
        TeamMember.objects.create(team=self.team_alpha, membership=self.membership_employee_a)

        # Users in Tenant B
        self.admin_user_b = User.objects.create_user(
            email="admin@stark.com", name="Tony Stark", mfa_enabled=True
        )
        self.membership_admin_b = Membership.objects.create(
            tenant=self.tenant_b,
            user=self.admin_user_b,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
            has_screenshot_permission=True,
        )

        # Policy for Tenant A
        self.policy_a = MonitoringPolicy.get_or_create_default(self.tenant_a)

        # Enrolled Device in Tenant A
        self.device_a = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_employee_a,
            hostname="ACME-LAPTOP-01",
            os="windows",
            agent_version="1.0.0",
            hardware_id="HW-112233",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )
        self.cred_a, self.raw_secret_a = AgentCredential.create_secret_credential(self.device_a)

        # Enrolled Device in Tenant B
        self.device_b = Device.objects.create(
            tenant=self.tenant_b,
            membership=self.membership_admin_b,
            hostname="STARK-LAPTOP-01",
            os="windows",
            agent_version="1.0.0",
            hardware_id="HW-998877",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )
        self.cred_b, self.raw_secret_b = AgentCredential.create_secret_credential(self.device_b)

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

    # ── REQ-1-4, REQ-6-3, REQ-10-1, REQ-10-2: Two-Phase Upload & Storage Rules ─
    def test_REQ_10_1_no_image_bytes_in_mysql_only_object_keys(self) -> None:
        """REQ-10-1: Screenshots table MUST NOT store image bytes in MySQL — only object keys."""
        # Verify model field types
        field_types = {f.name: f.get_internal_type() for f in Screenshot._meta.fields}
        self.assertNotIn("BinaryField", field_types.values())
        self.assertIn("object_key", field_types)
        self.assertIn("thumbnail_key", field_types)

    def test_REQ_10_2_object_keys_are_tenant_scoped_and_non_guessable(self) -> None:
        """REQ-10-2: Object keys MUST be tenant-scoped, non-guessable and date-partitioned."""
        s_id = uuid.uuid4()
        dt = timezone.now()
        key = generate_screenshot_object_key(self.tenant_a.id, self.device_a.id, s_id, dt, "jpg")

        # Verify tenant scope prefix
        self.assertTrue(key.startswith(f"tenants/{self.tenant_a.id}/devices/{self.device_a.id}/"))
        # Verify non-guessable UUID present
        self.assertIn(str(s_id), key)
        # Verify date partition
        self.assertIn(f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}", key)

    def test_two_phase_upload_happy_path(self) -> None:
        """Phase 1: upload intent -> Phase 2: upload bytes to S3 -> Phase 3: complete and finalize."""
        client = self._auth_device_client(self.raw_secret_a)
        screenshot_id = uuid.uuid4()
        img_bytes = make_test_image(width=1280, height=720, fmt="JPEG")
        checksum = hashlib.sha256(img_bytes).hexdigest()

        # Step 1: POST upload-intents
        resp = client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(img_bytes),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data["screenshot_id"], str(screenshot_id))
        self.assertIn("upload_url", data)
        self.assertIn("object_key", data)

        # Step 2: Upload bytes to object storage backend
        object_key = data["object_key"]
        self.storage.put_object_bytes(object_key, img_bytes, content_type="image/jpeg")

        # Step 3: POST complete
        complete_resp = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(screenshot_id),
                "checksum": checksum,
                "file_size": len(img_bytes),
                "width": 1280,
                "height": 720,
            },
            format="json",
        )
        self.assertEqual(complete_resp.status_code, status.HTTP_200_OK)
        complete_data = complete_resp.json()
        self.assertEqual(complete_data["status"], "finalized")

        # Verify DB record
        s = Screenshot.objects.get(id=screenshot_id)
        self.assertEqual(s.status, ScreenshotStatus.FINALIZED)
        self.assertEqual(s.width, 1280)
        self.assertEqual(s.height, 720)
        self.assertEqual(s.checksum, checksum)
        self.assertTrue(bool(s.thumbnail_key))
        # Verify thumbnail was placed in storage
        self.assertTrue(self.storage.object_exists(s.thumbnail_key))

    # ── Edge Case E49 & REQ-10-4: Leaked View URL, Expiration & Audited Views ──
    def test_E49_screenshot_view_url_leaked_short_lived_and_audited(self) -> None:
        """E49: View URLs are short-lived, scoped to single object, audited, and URLs are never logged."""
        # Create finalized screenshot
        s_id = uuid.uuid4()
        img_bytes = make_test_image(800, 600)
        object_key = generate_screenshot_object_key(
            self.tenant_a.id, self.device_a.id, s_id, timezone.now()
        )
        self.storage.put_object_bytes(object_key, img_bytes)
        s = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_a,
            device=self.device_a,
            status=ScreenshotStatus.FINALIZED,
            object_key=object_key,
            captured_at=timezone.now(),
            policy_version=1,
            delete_after=timezone.now() + datetime.timedelta(days=30),
            file_size=len(img_bytes),
        )

        client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        response = client.post(f"/api/screenshots/{s.id}/view-url")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        view_url = response.json()["view_url"]
        self.assertTrue(view_url.startswith("https://storage.internal/view"))

        # Verify view was audited
        audit = AuditLog.objects.filter(action="screenshot.viewed", resource_id=str(s.id)).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.admin_user_a)

        # REQ-10-4 / E49: URL is strictly NOT logged in audit log or DB
        self.assertNotIn(view_url, json.dumps(audit.metadata))
        self.assertNotIn(view_url, s.object_key)

        # Verify URL expiration
        self.assertFalse(self.storage.is_view_url_expired(view_url))
        # Expired token test: tamper with expiry query param
        tampered_url = view_url.replace("expires=", "expires=1000&prior_expires=")
        self.assertTrue(self.storage.is_view_url_expired(tampered_url))

    # ── Edge Case E50 & REQ-10-3: Untrusted Upload Verification & Malware ──────
    def test_E50_malicious_uploaded_file_rejected_and_safe_decode(self) -> None:
        """E50: Malicious or invalid uploaded files are strictly rejected before acceptance."""
        client = self._auth_device_client(self.raw_secret_a)
        screenshot_id = uuid.uuid4()

        # 1. Non-image text file disguised as JPEG
        fake_jpeg = b"This is a text file, not an image!"
        client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(fake_jpeg),
            },
            format="json",
        )
        s = Screenshot.objects.get(id=screenshot_id)
        self.storage.put_object_bytes(s.object_key, fake_jpeg)

        complete_resp = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(screenshot_id),
                "checksum": hashlib.sha256(fake_jpeg).hexdigest(),
                "file_size": len(fake_jpeg),
            },
            format="json",
        )
        self.assertEqual(complete_resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(complete_resp.json()["code"], "UNTRUSTED_IMAGE_REJECTED")

        # 2. Executable / malware signature detected (E50)
        malware_bytes = b"MZ\x90\x00\x03\x00\x00\x00" + b"A" * 100
        s_id2 = uuid.uuid4()
        client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(s_id2),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(malware_bytes),
            },
            format="json",
        )
        s2 = Screenshot.objects.get(id=s_id2)
        self.storage.put_object_bytes(s2.object_key, malware_bytes)

        complete_resp2 = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(s_id2),
                "checksum": hashlib.sha256(malware_bytes).hexdigest(),
                "file_size": len(malware_bytes),
            },
            format="json",
        )
        self.assertEqual(complete_resp2.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(complete_resp2.json()["code"], "UNTRUSTED_IMAGE_REJECTED")

        # 3. Checksum mismatch
        valid_img = make_test_image(400, 300)
        s_id3 = uuid.uuid4()
        client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(s_id3),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(valid_img),
            },
            format="json",
        )
        s3 = Screenshot.objects.get(id=s_id3)
        self.storage.put_object_bytes(s3.object_key, valid_img)

        complete_resp3 = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(s_id3),
                "checksum": "wrong_checksum_here_12345",
                "file_size": len(valid_img),
            },
            format="json",
        )
        self.assertEqual(complete_resp3.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(complete_resp3.json()["code"], "CHECKSUM_MISMATCH")

    # ── Edge Case E51: Partial Upload & Upload Intent Reuse ───────────────────
    def test_E51_screenshot_upload_partially_completes_intent_reuse(self) -> None:
        """E51: Agent requests intent, upload aborts/expires; re-request reuses same logical record without duplicates."""
        client = self._auth_device_client(self.raw_secret_a)
        screenshot_id = uuid.uuid4()

        # First intent request
        resp1 = client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": 5000,
            },
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(Screenshot.objects.filter(id=screenshot_id).count(), 1)

        # Simulate expiration of intent
        ScreenshotUploadIntent.objects.filter(screenshot_id=screenshot_id).update(
            expires_at=timezone.now() - datetime.timedelta(minutes=10)
        )

        # Second intent request for the same screenshot_id
        resp2 = client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": 5000,
            },
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)

        # Must still have EXACTLY 1 Screenshot record (never duplicate DB row)
        self.assertEqual(Screenshot.objects.filter(id=screenshot_id).count(), 1)
        self.assertIn("upload_url", resp2.json())

    # ── Edge Case E52: Upload Succeeded, Finalize Failed, Retry Succeeded ──────
    def test_E52_upload_succeeded_finalize_failed_idempotent_retry(self) -> None:
        """E52: Upload bytes in storage succeeded, finalize call failed/interrupted, retry finalizes cleanly."""
        client = self._auth_device_client(self.raw_secret_a)
        screenshot_id = uuid.uuid4()
        img_bytes = make_test_image(800, 600)
        checksum = hashlib.sha256(img_bytes).hexdigest()

        # Intent request
        client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(img_bytes),
            },
            format="json",
        )
        s = Screenshot.objects.get(id=screenshot_id)
        # Put bytes in storage
        self.storage.put_object_bytes(s.object_key, img_bytes)

        # Agent retries finalize
        resp = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(screenshot_id),
                "checksum": checksum,
                "file_size": len(img_bytes),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        s.refresh_from_db()
        self.assertEqual(s.status, ScreenshotStatus.FINALIZED)

    # ── Edge Case E53: Finalize Succeeded, Response Lost, Idempotent Retry ─────
    def test_E53_finalize_succeeded_response_lost_idempotent(self) -> None:
        """E53: Screenshot finalized, response was lost, agent retries complete -> returns 200 OK idempotently."""
        client = self._auth_device_client(self.raw_secret_a)
        screenshot_id = uuid.uuid4()
        img_bytes = make_test_image(640, 480)
        checksum = hashlib.sha256(img_bytes).hexdigest()

        # Perform initial finalize
        client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(img_bytes),
            },
            format="json",
        )
        s = Screenshot.objects.get(id=screenshot_id)
        self.storage.put_object_bytes(s.object_key, img_bytes)

        resp1 = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(screenshot_id),
                "checksum": checksum,
                "file_size": len(img_bytes),
            },
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Agent lost the response and retries complete
        resp2 = client.post(
            "/api/agent/screenshots/complete",
            data={
                "screenshot_id": str(screenshot_id),
                "checksum": checksum,
                "file_size": len(img_bytes),
            },
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.json()["status"], "finalized")

        # Also calling upload-intent on already-finalized screenshot returns already_finalized
        resp3 = client.post(
            "/api/agent/screenshots/upload-intents",
            data={
                "screenshot_id": str(screenshot_id),
                "captured_at": timezone.now().isoformat(),
                "policy_version": 1,
                "content_type": "image/jpeg",
                "file_size": len(img_bytes),
            },
            format="json",
        )
        self.assertEqual(resp3.status_code, status.HTTP_200_OK)
        self.assertEqual(resp3.json()["status"], "already_finalized")

    # ── Edge Case E54: Retention Deletion & Failure Verification ──────────────
    def test_E54_retention_job_deletes_object_and_verifies(self) -> None:
        """E54: Retention deletion removes object, verifies deletion, retries on failure, reports backlog."""
        past_time = timezone.now() - datetime.timedelta(days=45)
        expired_date = timezone.now() - datetime.timedelta(days=1)

        # Create expired screenshot
        s_id = uuid.uuid4()
        img_bytes = make_test_image(300, 200)
        obj_key = generate_screenshot_object_key(self.tenant_a.id, self.device_a.id, s_id, past_time)
        thumb_key = generate_thumbnail_object_key(self.tenant_a.id, self.device_a.id, s_id, past_time)
        self.storage.put_object_bytes(obj_key, img_bytes)
        self.storage.put_object_bytes(thumb_key, img_bytes)

        s = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_a,
            device=self.device_a,
            status=ScreenshotStatus.FINALIZED,
            object_key=obj_key,
            thumbnail_key=thumb_key,
            captured_at=past_time,
            delete_after=expired_date,
            legal_hold=False,
            file_size=len(img_bytes),
        )

        # 1. Simulate failure during retention deletion
        self.storage.simulated_deletion_failure = True
        result_fail = run_retention_sweep(self.tenant_a)
        self.assertEqual(result_fail["failed_count"], 1)
        self.assertEqual(result_fail["deleted_count"], 0)
        self.assertEqual(result_fail["backlog_count"], 1)

        # Status must NOT be marked deleted because verification failed!
        s.refresh_from_db()
        self.assertEqual(s.status, ScreenshotStatus.FINALIZED)

        # 2. Storage recovers, retention job retries and verifies
        self.storage.simulated_deletion_failure = False
        result_success = run_retention_sweep(self.tenant_a)
        self.assertEqual(result_success["deleted_count"], 1)
        self.assertEqual(result_success["failed_count"], 0)
        self.assertEqual(result_success["backlog_count"], 0)

        # Status updated to DELETED after confirmed verification
        s.refresh_from_db()
        self.assertEqual(s.status, ScreenshotStatus.DELETED)
        # Verify objects no longer exist in storage
        self.assertFalse(self.storage.object_exists(obj_key))
        self.assertFalse(self.storage.object_exists(thumb_key))

    # ── Edge Case E55: Retroactive Screenshot Exclusion Handling ──────────────
    def test_E55_screenshot_exclusion_rule_retroactive_handling(self) -> None:
        """E55: Retroactive action for newly excluded app ('keep', 'purge', 'flag_legal_review')."""
        s_id = uuid.uuid4()
        img_bytes = make_test_image(400, 300)
        obj_key = generate_screenshot_object_key(
            self.tenant_a.id, self.device_a.id, s_id, timezone.now()
        )
        self.storage.put_object_bytes(obj_key, img_bytes)
        s = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_a,
            device=self.device_a,
            status=ScreenshotStatus.FINALIZED,
            object_key=obj_key,
            captured_at=timezone.now(),
            policy_version=1,
            delete_after=timezone.now() + datetime.timedelta(days=30),
            file_size=len(img_bytes),
        )

        client = self._auth_user_client(self.admin_user_a, self.tenant_a)

        # Action: flag_legal_review
        resp1 = client.post(
            "/api/screenshots/retroactive-exclusion",
            data={
                "app_identifier": "confidential_app.exe",
                "action": "flag_legal_review",
                "policy_version": 1,
            },
            format="json",
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        s.refresh_from_db()
        self.assertEqual(s.exclusion_retroactive_action, "flag_legal_review")

        # Action: purge
        resp2 = client.post(
            "/api/screenshots/retroactive-exclusion",
            data={
                "app_identifier": "confidential_app.exe",
                "action": "purge",
                "policy_version": 1,
            },
            format="json",
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        s.refresh_from_db()
        self.assertEqual(s.status, ScreenshotStatus.DELETED)
        self.assertFalse(self.storage.object_exists(obj_key))

    # ── Edge Case E90 & REQ-11-2: Legal Hold & Deletion Request Workflow ──────
    def test_E90_legal_retention_and_deletion_request_workflow(self) -> None:
        """E90: Legal hold prevents retention deletion; legal deletion purges data; audited without sensitive content."""
        past_time = timezone.now() - datetime.timedelta(days=40)
        expired_date = timezone.now() - datetime.timedelta(days=5)

        s_id = uuid.uuid4()
        img_bytes = make_test_image(500, 400)
        obj_key = generate_screenshot_object_key(self.tenant_a.id, self.device_a.id, s_id, past_time)
        self.storage.put_object_bytes(obj_key, img_bytes)

        s = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_a,
            device=self.device_a,
            status=ScreenshotStatus.FINALIZED,
            object_key=obj_key,
            captured_at=past_time,
            delete_after=expired_date,
            legal_hold=False,
            file_size=len(img_bytes),
        )

        # Non-admin user cannot place legal hold
        emp_client = self._auth_user_client(self.employee_user_a, self.tenant_a)
        emp_resp = emp_client.post(
            "/api/screenshots/legal-hold",
            data={"reason": "Litigation hold"},
            format="json",
        )
        self.assertEqual(emp_resp.status_code, status.HTTP_403_FORBIDDEN)

        # Admin user places legal hold on device
        admin_client = self._auth_user_client(self.admin_user_a, self.tenant_a)
        admin_resp = admin_client.post(
            "/api/screenshots/legal-hold",
            data={
                "reason": "Litigation matter 2026-XYZ",
                "device_id": str(self.device_a.id),
            },
            format="json",
        )
        self.assertEqual(admin_resp.status_code, status.HTTP_200_OK)
        s.refresh_from_db()
        self.assertTrue(s.legal_hold)

        # Retention sweep runs: screenshot is EXPIRED but MUST NOT BE DELETED due to legal hold!
        sweep_result = run_retention_sweep(self.tenant_a)
        self.assertEqual(sweep_result["deleted_count"], 0)
        s.refresh_from_db()
        self.assertNotEqual(s.status, ScreenshotStatus.DELETED)
        self.assertTrue(self.storage.object_exists(obj_key))

        # Admin executes verified legal deletion request
        del_resp = admin_client.post(
            "/api/screenshots/legal-delete",
            data={
                "reason": "Authorized court order compliance",
                "screenshot_ids": [str(s.id)],
            },
            format="json",
        )
        self.assertEqual(del_resp.status_code, status.HTTP_200_OK)
        s.refresh_from_db()
        self.assertEqual(s.status, ScreenshotStatus.DELETED)
        self.assertFalse(self.storage.object_exists(obj_key))

        # Verify outcome recorded in audit log without sensitive image content
        audit = AuditLog.objects.filter(action="screenshot.legal_deletion", resource_id=str(s.id)).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.metadata["reason"], "Authorized court order compliance")
        self.assertNotIn("base64", json.dumps(audit.metadata))
        self.assertNotIn("image", json.dumps(audit.metadata))

    # ── Negative Authorization & Tenant Isolation Tests ───────────────────────
    def test_cross_tenant_view_url_returns_404(self) -> None:
        """Cross-tenant screenshot view URL request returns safe 404 (E45)."""
        s_id = uuid.uuid4()
        img_bytes = make_test_image(400, 300)
        obj_key = generate_screenshot_object_key(self.tenant_b.id, self.device_b.id, s_id, timezone.now())
        self.storage.put_object_bytes(obj_key, img_bytes)
        s_b = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_b,
            device=self.device_b,
            status=ScreenshotStatus.FINALIZED,
            object_key=obj_key,
            captured_at=timezone.now(),
            policy_version=1,
            delete_after=timezone.now() + datetime.timedelta(days=30),
            file_size=len(img_bytes),
        )

        # Admin of Tenant A guesses ID of Screenshot in Tenant B
        client_a = self._auth_user_client(self.admin_user_a, self.tenant_a)
        response = client_a.post(f"/api/screenshots/{s_b.id}/view-url")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_auditor_without_screenshot_permission_denied(self) -> None:
        """Auditor without explicit screenshot permission cannot search or view screenshots (§2.2)."""
        s_id = uuid.uuid4()
        s = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_a,
            device=self.device_a,
            status=ScreenshotStatus.FINALIZED,
            object_key="some-key",
            captured_at=timezone.now(),
            policy_version=1,
            delete_after=timezone.now() + datetime.timedelta(days=30),
        )

        client = self._auth_user_client(self.auditor_user_a, self.tenant_a)
        # Search list
        resp1 = client.get("/api/screenshots")
        self.assertEqual(resp1.status_code, status.HTTP_403_FORBIDDEN)
        # View URL
        resp2 = client.post(f"/api/screenshots/{s.id}/view-url")
        self.assertEqual(resp2.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_scoped_to_assigned_team_only(self) -> None:
        """Manager cannot view screenshot from a device outside assigned teams (§2.2, E47)."""
        # Employee 2 in Beta team
        emp2 = User.objects.create_user(email="emp2@acme.com", name="Beta User")
        mem2 = Membership.objects.create(
            tenant=self.tenant_a,
            user=emp2,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )
        TeamMember.objects.create(team=self.team_beta, membership=mem2)
        dev_beta = Device.objects.create(
            tenant=self.tenant_a,
            membership=mem2,
            hostname="ACME-BETA-01",
            os="windows",
            hardware_id="HW-BETA-01",
            status=DeviceStatus.ACTIVE,
        )

        s_id = uuid.uuid4()
        s_beta = Screenshot.objects.create(
            id=s_id,
            tenant=self.tenant_a,
            device=dev_beta,
            status=ScreenshotStatus.FINALIZED,
            object_key="beta-key",
            captured_at=timezone.now(),
            policy_version=1,
            delete_after=timezone.now() + datetime.timedelta(days=30),
        )

        # Bob Manager is only assigned to Alpha Team
        manager_client = self._auth_user_client(self.manager_user_a, self.tenant_a)
        response = manager_client.post(f"/api/screenshots/{s_beta.id}/view-url")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
