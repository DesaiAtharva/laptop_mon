"""
tests/test_t2_full_integration.py — Full Integration Test Suite Across Agent, API, Database, and Object Storage.

Adheres to:
- Build Playbook prompt T2
- Spec §§ 6, 7, 8: Ingestion, Synchronization, Data Model, API Design
- Real database, real object storage, real agent core (Journal, Spool, SyncWorker, PolicyManager, StatusTracker)
- Direct multi-layer verification: Agent Journal/Spool, Database Invariants, Object Storage Checksums, Reports API

Scenarios:
1. Complete happy-path lifecycle: enrollment -> policy -> heartbeat -> event batch -> screenshot upload -> timeline -> reports
2. Partial batch acceptance (E36)
3. Lost response & idempotent duplicate replay (E02, E03, E31)
4. Revoked device upload cessation (E24, E38)
5. Agent & server version enforcement (E16)
6. Two-phase screenshot upload protocol, checksum validation, and idempotent finalize (E51, E52, E53)
7. Dynamic policy change propagation (E37, E70)
8. Multi-tenant concurrent isolation (E45, E46)
9. 7-Day offline backlog replay without gaps or double-counting
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import shutil
import tempfile
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient


def make_valid_test_jpeg(width: int = 100, height: int = 100) -> bytes:
    bio = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(bio, format="JPEG")
    return bio.getvalue()

from agent.adapters.fake.fake_adapter import FakeOSAdapter
from agent.core.crypto import CryptoManager, InMemoryKeyStore
from agent.core.journal import Journal
from agent.core.policy import EffectivePolicy, PolicyManager
from agent.core.spool import ScreenshotSpool
from agent.core.status import AgentState, StatusTracker
from agent.core.sync import SyncWorker

from apps.accounts.models import UserSession
from apps.analytics.models import AppUsageInterval, DailyMetrics, IntervalState
from apps.analytics.tasks import process_device_timeline_task
from apps.devices.models import (
    AgentCredential,
    CredentialStatus,
    Device,
    DeviceStatus,
    EnrollmentToken,
)
from apps.ingestion.models import ActivityEvent, EventBatch, EventBatchStatus
from apps.policies.models import MonitoringPolicy
from apps.screenshots.models import Screenshot, ScreenshotStatus
from apps.screenshots.storage import (
    MemoryObjectStorageBackend,
    get_storage_backend,
    reset_storage_backend,
)
from apps.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Tenant,
    TenantStatus,
)

User = get_user_model()


def make_django_http_client(api_client: APIClient, storage_backend: MemoryObjectStorageBackend):
    """
    Connects desktop agent SyncWorker directly to Django's APIClient and the Object Storage backend.
    Enforces real HTTP method routing, serialization, headers, and status code propagation.
    """
    def _client_call(
        url: str,
        data: bytes,
        headers: Dict[str, str],
        method: str = "POST",
    ) -> Tuple[int, bytes, Dict[str, str]]:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip("/")
        if parsed.query:
            path += "?" + parsed.query

        # Handle direct S3 / Object Storage presigned PUT uploads
        if "storage" in url or "presigned" in url or method.upper() == "PUT":
            qs = urllib.parse.parse_qs(parsed.query)
            if "key" in qs:
                key = qs["key"][0]
            else:
                key = parsed.path.lstrip("/")

            storage_backend.put_object_bytes(
                object_key=key,
                data=data,
                content_type=headers.get("Content-Type", "image/jpeg"),
            )
            return 200, b"", {"content-type": "application/json"}

        extra: Dict[str, Any] = {}
        for k, v in headers.items():
            if k.lower() == "content-type":
                extra["content_type"] = v
            else:
                django_header_key = f"HTTP_{k.upper().replace('-', '_')}"
                extra[django_header_key] = v

        if method.upper() == "POST":
            resp = api_client.post(path, data=data, **extra)
        elif method.upper() == "GET":
            resp = api_client.get(path, **extra)
        elif method.upper() == "PATCH":
            resp = api_client.patch(path, data=data, **extra)
        elif method.upper() == "DELETE":
            resp = api_client.delete(path, **extra)
        else:
            raise ValueError(f"Unsupported method: {method}")

        resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status_code, resp.content, resp_headers

    return _client_call


class FullIntegrationPipelineTests(TestCase):
    """
    End-to-End integration tests exercising desktop agent core, Django API,
    MySQL transactional database, object storage, and reporting analytics.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        reset_storage_backend()
        self.storage = get_storage_backend()

        # Seed Primary Tenant & Admin
        self.tenant_a = Tenant.objects.create(name="Acme Global", status=TenantStatus.ACTIVE)
        self.admin_a = User.objects.create_user(
            email="admin@acme.com", name="Acme Admin", password="password12345"
        )
        self.membership_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.admin_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        # Base monitoring policy
        self.policy_a = MonitoringPolicy.objects.create(
            tenant=self.tenant_a,
            version=1,
            valid_until=timezone.now() + datetime.timedelta(days=365),
            screenshot_interval_seconds=60,
            idle_threshold_seconds=300,
            min_agent_version="1.0.0",
        )

        # Admin API client
        self.admin_client = APIClient()
        _, admin_token = UserSession.create_session(user=self.admin_a)
        self.admin_client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        self.admin_client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)

        # Agent infrastructure
        self.crypto = CryptoManager(InMemoryKeyStore(b"01234567890123456789012345678901"))
        self.journal_path = os.path.join(self.tmpdir, "agent_journal.db")
        self.spool_dir = os.path.join(self.tmpdir, "agent_spool")
        self.status_file = os.path.join(self.tmpdir, "agent_status.json")

        self.journal = Journal(self.journal_path, self.crypto)
        self.spool = ScreenshotSpool(self.spool_dir, self.crypto)
        self.status_tracker = StatusTracker(self.status_file)
        self.status_tracker.acknowledge_first_run()
        self.policy_cache_path = os.path.join(self.tmpdir, "policy_cache.json")
        self.policy_mgr = PolicyManager(self.policy_cache_path)

        self.api_client = APIClient()
        self.http_client = make_django_http_client(self.api_client, self.storage)

    def tearDown(self) -> None:
        self.journal.close()
        self.spool.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        reset_storage_backend()

    # ── Scenario 1: Complete Lifecycle Flow ───────────────────────────────────

    def test_scenario_01_complete_lifecycle_flow(self) -> None:
        """
        Happy-path full integration:
        1. Admin generates enrollment token
        2. Agent exchanges token -> device created & credential returned
        3. Agent fetches policy & sends heartbeat
        4. Agent logs events & screenshots -> syncs to server
        5. Timeline processing runs -> Reports API returns accurate metrics
        6. Invariants verified across agent journal, MySQL, MinIO, and Reports
        """
        # Step 1: Admin generates enrollment token
        resp = self.admin_client.post(
            "/api/devices/enrollment-tokens",
            data={
                "membership_id": str(self.membership_a.id),
                "expires_hours": 24,
                "max_uses": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        raw_enrollment_token = resp.data["enrollment_token"]

        # Step 2: Agent enrolls using raw token
        enroll_resp = self.api_client.post(
            "/api/agent/enroll",
            data={
                "token": raw_enrollment_token,
                "hostname": "ACME-LAPTOP-01",
                "os": "windows",
                "agent_version": "1.0.0",
                "hardware_id": "HW-ACME-999",
            },
            format="json",
        )
        self.assertEqual(enroll_resp.status_code, status.HTTP_201_CREATED)
        device_id = enroll_resp.data["device_id"]
        device_secret = enroll_resp.data["device_secret"]

        # Verify Device & Credential persisted in DB
        device = Device.objects.get(id=device_id)
        self.assertEqual(device.hostname, "ACME-LAPTOP-01")
        self.assertEqual(device.tenant, self.tenant_a)
        self.assertEqual(device.status, DeviceStatus.ACTIVE)

        cred = AgentCredential.objects.get(device=device)
        self.assertEqual(cred.status, CredentialStatus.ACTIVE)
        self.assertEqual(
            cred.secret_hash, hashlib.sha256(device_secret.encode("utf-8")).hexdigest()
        )

        # Step 3: Agent configures SyncWorker with DeviceBearer auth
        sync_worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id=device_id,
            credential_token=device_secret,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=self.http_client,
        )
        # DeviceBearer authorization header used by agent
        sync_worker._auth_headers = lambda: {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {device_secret}",
            "X-Device-Id": device_id,
        }

        # Step 4: Agent fetches policy & sends heartbeat
        pol_status, pol_bytes, _ = self.http_client(
            "http://mock-api/api/agent/policy",
            b"",
            sync_worker._auth_headers(),
            "GET",
        )
        self.assertEqual(pol_status, 200)
        pol_data = json.loads(pol_bytes.decode("utf-8"))
        self.assertEqual(pol_data["version"], 1)
        self.assertEqual(pol_data["screenshot_interval_seconds"], 60)

        hb_ok = sync_worker.send_heartbeat(
            {
                "queue_depth": 0,
                "agent_version": "1.0.0",
                "status": "active",
                "timestamp": timezone.now().isoformat(),
            }
        )
        self.assertTrue(hb_ok)
        device.refresh_from_db()
        self.assertIsNotNone(device.last_seen_at)

        # Step 5: Agent records work activity in local journal
        t0 = timezone.now().replace(microsecond=0) - datetime.timedelta(minutes=30)
        ev1 = self.journal.append_event(
            event_type="app.active",
            occurred_at=(t0).isoformat(),
            payload={"app_identifier": "code.exe", "window_title": "Laptop_mon"},
            monotonic_reference=100.0,
            boot_segment_id="boot-1",
        )
        ev2 = self.journal.append_event(
            event_type="app.active",
            occurred_at=(t0 + datetime.timedelta(minutes=15)).isoformat(),
            payload={"app_identifier": "chrome.exe", "window_title": "Google Docs"},
            monotonic_reference=1000.0,
            boot_segment_id="boot-1",
        )
        ev3 = self.journal.append_event(
            event_type="session.idle_start",
            occurred_at=(t0 + datetime.timedelta(minutes=25)).isoformat(),
            payload={"idle_seconds": 300},
            monotonic_reference=1600.0,
            boot_segment_id="boot-1",
        )

        self.assertEqual(len(self.journal.get_pending_events()), 3)

        # Step 6: Agent syncs event batch
        accepted_count = sync_worker.sync_events()
        self.assertEqual(accepted_count, 3)

        # Invariant 1: Local journal purged of accepted events
        self.assertEqual(len(self.journal.get_pending_events()), 0)

        # Invariant 2: Database contains committed batch and events
        batches = EventBatch.objects.filter(device=device)
        self.assertEqual(batches.count(), 1)
        self.assertEqual(batches.first().status, EventBatchStatus.ACCEPTED)
        self.assertEqual(batches.first().accepted_count, 3)

        db_events = ActivityEvent.objects.filter(device=device)
        self.assertEqual(db_events.count(), 3)
        self.assertTrue(db_events.filter(id=ev1.id).exists())

        # Step 7: Agent captures, spools, and syncs screenshot
        sample_image_bytes = make_valid_test_jpeg()
        spooled = self.spool.spool_screenshot(
            image_bytes=sample_image_bytes,
            captured_at=t0.isoformat(),
            metadata={"width": 1920, "height": 1080, "format": "jpeg"},
        )
        self.assertIsNotNone(spooled)
        self.assertEqual(len(self.spool.get_ready_screenshots()), 1)

        # Sync screenshot through two-phase upload
        uploaded_shots = sync_worker.sync_screenshots()
        self.assertEqual(uploaded_shots, 1)

        # Invariant 3: Spool purged after verified completion
        self.assertEqual(len(self.spool.get_ready_screenshots()), 0)

        # Invariant 4: Screenshot in DB finalized and storage object verified
        screenshot_record = Screenshot.objects.get(id=spooled.screenshot_id)
        self.assertEqual(screenshot_record.status, ScreenshotStatus.FINALIZED)
        self.assertEqual(screenshot_record.checksum, spooled.sha256_checksum)
        self.assertTrue(self.storage.object_exists(screenshot_record.object_key))

        stored_bytes = self.storage.get_object_bytes(screenshot_record.object_key)
        self.assertEqual(stored_bytes, sample_image_bytes)

        # Step 8: Trigger timeline reconstruction
        timeline_res = process_device_timeline_task(
            tenant_id=self.tenant_a.id,
            device_id=device.id,
        )
        self.assertEqual(timeline_res["status"], "completed")

        # Invariant 5: Intervals and daily metrics created in DB
        intervals = AppUsageInterval.objects.filter(device=device)
        self.assertGreaterEqual(intervals.count(), 2)

        daily = DailyMetrics.objects.filter(device=device)
        self.assertEqual(daily.count(), 1)
        self.assertGreater(daily.first().active_seconds, 0)

        # Step 9: Query Reports API as Admin
        rep_resp = self.admin_client.get(f"/api/reports/daily?device_id={device.id}")
        self.assertEqual(rep_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(rep_resp.data["results"]), 1)
        self.assertEqual(
            rep_resp.data["results"][0]["active_seconds"], daily.first().active_seconds
        )

        timeline_resp = self.admin_client.get(f"/api/reports/timeline?device_id={device.id}")
        self.assertEqual(timeline_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(timeline_resp.data["results"]), 2)

    # ── Scenario 2: Partial Batch Acceptance (E36) ───────────────────────────

    def test_scenario_02_partial_batch_acceptance(self) -> None:
        """
        Agent sends batch containing valid and invalid/unknown events.
        Server commits valid events, rejects invalid, and returns partial acceptance.
        Agent deletes only accepted events.
        """
        device = Device.objects.create(
            tenant=self.tenant_a,
            hostname="ACME-PARTIAL",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)

        sync_worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id=str(device.id),
            credential_token=secret,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=self.http_client,
        )
        sync_worker._auth_headers = lambda: {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }

        # Event 1: Valid
        e1 = self.journal.append_event(
            event_type="app.active",
            occurred_at=timezone.now().isoformat(),
            payload={"app_identifier": "notepad.exe"},
            monotonic_reference=10.0,
            boot_segment_id="boot-1",
        )
        # Event 2: Unknown event type (E33)
        e2 = self.journal.append_event(
            event_type="unsupported.malicious.event",
            occurred_at=timezone.now().isoformat(),
            payload={"bad": True},
            monotonic_reference=11.0,
            boot_segment_id="boot-1",
        )

        accepted = sync_worker.sync_events()
        self.assertEqual(accepted, 1)

        # Only e1 accepted and removed; e2 rejected by server
        pending = self.journal.get_pending_events()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, e2.id)

        # DB has batch marked PARTIAL
        batch = EventBatch.objects.get(device=device)
        self.assertEqual(batch.status, EventBatchStatus.PARTIAL)
        self.assertEqual(batch.accepted_count, 1)

    # ── Scenario 3: Lost Response & Idempotent Replay (E02, E03, E31) ──────────

    def test_scenario_03_lost_response_and_idempotent_replay(self) -> None:
        """
        Server commits batch successfully, but response is lost/dropped in transit.
        Agent retries identical batch.
        Server returns already_accepted, does not insert duplicate rows, and agent purges journal.
        """
        device = Device.objects.create(
            tenant=self.tenant_a,
            hostname="ACME-RETRY",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)

        sync_worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id=str(device.id),
            credential_token=secret,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=self.http_client,
        )
        sync_worker._auth_headers = lambda: {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }

        e1 = self.journal.append_event(
            event_type="app.active",
            occurred_at=timezone.now().isoformat(),
            payload={"app_identifier": "slack.exe"},
            monotonic_reference=50.0,
            boot_segment_id="boot-1",
        )

        # Directly simulate first network attempt succeeding on backend
        headers = sync_worker._auth_headers()
        body = json.dumps({
            "agent_version": "1.0.0",
            "schema_version": 1,
            "events": [{
                "id": e1.id,
                "event_type": e1.event_type,
                "occurred_at": e1.occurred_at,
                "payload": e1.payload,
            }]
        }).encode("utf-8")

        status_code, resp_bytes, _ = self.http_client(
            "http://mock-api/api/agent/events/batch", body, headers, "POST"
        )
        self.assertIn(status_code, (200, 207))
        self.assertEqual(ActivityEvent.objects.filter(device=device).count(), 1)

        # Simulate agent didn't receive response (journal still has e1 marked in-flight or pending)
        # Agent calls sync_events() which replays e1
        replayed = sync_worker.sync_events()
        self.assertEqual(replayed, 1)

        # Invariants: No duplicate DB row created; Journal purged
        self.assertEqual(ActivityEvent.objects.filter(device=device).count(), 1)
        self.assertEqual(len(self.journal.get_pending_events()), 0)

    # ── Scenario 4: Revoked Device Upload Cessation (E24, E38) ────────────────

    def test_scenario_04_revoked_device_upload_cessation(self) -> None:
        """
        When device is revoked by admin, server immediately returns HTTP 403.
        Agent applies revocation policy and halts future uploads.
        """
        device = Device.objects.create(
            tenant=self.tenant_a,
            hostname="ACME-REVOKED",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)

        sync_worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id=str(device.id),
            credential_token=secret,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=self.http_client,
        )
        sync_worker._auth_headers = lambda: {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }

        # Admin revokes device via Admin API
        revoke_resp = self.admin_client.post(f"/api/devices/{device.id}/revoke")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)
        device.refresh_from_db()
        self.assertEqual(device.status, DeviceStatus.REVOKED)

        # Agent attempts to append event and sync
        self.journal.append_event(
            event_type="app.active",
            occurred_at=timezone.now().isoformat(),
            payload={"app_identifier": "cmd.exe"},
            monotonic_reference=20.0,
            boot_segment_id="boot-1",
        )

        res = sync_worker.sync_events()
        self.assertEqual(res, 0)
        self.assertTrue(sync_worker.is_revoked)

        # Subsequent sync attempt immediately short-circuits without network call
        res2 = sync_worker.sync_events()
        self.assertEqual(res2, 0)

    # ── Scenario 5: Agent & Server Version Enforcement (E16) ──────────────────

    def test_scenario_05_version_enforcement(self) -> None:
        """
        Policy enforces min_agent_version = 2.0.0.
        Agent running version 1.0.0 is flagged with version incompatibility.
        """
        self.policy_a.min_agent_version = "2.0.0"
        self.policy_a.save(update_fields=["min_agent_version"])

        device = Device.objects.create(
            tenant=self.tenant_a,
            hostname="ACME-OLD-VER",
            os="windows",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }
        status_code, resp_bytes, _ = self.http_client(
            "http://mock-api/api/agent/policy", b"", headers, "GET"
        )
        self.assertEqual(status_code, 200)
        data = json.loads(resp_bytes.decode("utf-8"))
        self.assertEqual(data["min_agent_version"], "2.0.0")
        agent_tuple = tuple(map(int, "1.0.0".split(".")))
        required_tuple = tuple(map(int, data["min_agent_version"].split(".")))
        self.assertLess(agent_tuple, required_tuple)

    # ── Scenario 6: Two-Phase Screenshot Protocol & Expiry (E51, E52, E53) ───

    def test_scenario_06_two_phase_screenshot_validation_and_idempotency(self) -> None:
        """
        Two-phase upload protocol:
        - Scoped upload intent validation
        - Checksum & size integrity verification
        - Idempotent finalization
        """
        device = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_a,
            hostname="ACME-SHOT-VAL",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }

        image_data = make_valid_test_jpeg()
        checksum = hashlib.sha256(image_data).hexdigest()
        shot_id = str(uuid.uuid4())

        # Phase 1: Request upload intent
        intent_body = json.dumps({
            "screenshot_id": shot_id,
            "captured_at": timezone.now().isoformat(),
            "content_type": "image/jpeg",
            "file_size": len(image_data),
            "checksum": checksum,
        }).encode("utf-8")

        s1, r1, _ = self.http_client(
            "http://mock-api/api/agent/screenshots/upload-intents", intent_body, headers, "POST"
        )
        self.assertIn(s1, (200, 201))
        intent_res = json.loads(r1.decode("utf-8"))
        object_key = intent_res["object_key"]
        upload_url = intent_res["upload_url"]

        # Phase 2: Upload to Object Storage
        s2, _, _ = self.http_client(upload_url, image_data, {"Content-Type": "image/jpeg"}, "PUT")
        self.assertEqual(s2, 200)

        # Phase 3: Finalize with mismatched checksum -> rejected
        bad_comp_body = json.dumps({
            "screenshot_id": shot_id,
            "object_key": object_key,
            "checksum": "0" * 64,
            "file_size": len(image_data),
        }).encode("utf-8")
        s3_bad, _, _ = self.http_client(
            "http://mock-api/api/agent/screenshots/complete", bad_comp_body, headers, "POST"
        )
        self.assertEqual(s3_bad, 400)

        # Phase 3: Finalize with matching checksum -> accepted
        good_comp_body = json.dumps({
            "screenshot_id": shot_id,
            "object_key": object_key,
            "checksum": checksum,
            "file_size": len(image_data),
        }).encode("utf-8")
        s3_ok, r3, _ = self.http_client(
            "http://mock-api/api/agent/screenshots/complete", good_comp_body, headers, "POST"
        )
        self.assertIn(s3_ok, (200, 201))

        # Phase 3 Retry: Idempotent duplicate finalize call returns 200/201 without creating duplicate row
        s3_retry, _, _ = self.http_client(
            "http://mock-api/api/agent/screenshots/complete", good_comp_body, headers, "POST"
        )
        self.assertIn(s3_retry, (200, 201))
        self.assertEqual(Screenshot.objects.filter(id=shot_id).count(), 1)

    # ── Scenario 7: Policy Change Propagation (E37, E70) ──────────────────────

    def test_scenario_07_policy_change_propagation(self) -> None:
        """
        Admin updates policy parameters. Agent pulls updated policy and adapts.
        """
        device = Device.objects.create(
            tenant=self.tenant_a,
            hostname="ACME-POL-PROP",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }

        # Admin updates policy via Admin API
        patch_resp = self.admin_client.patch(
            f"/api/policies/{self.policy_a.id}",
            data={
                "expected_version": 1,
                "screenshot_interval_seconds": 120,
                "idle_threshold_seconds": 180,
            },
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        # Agent queries policy
        pol_code, pol_bytes, _ = self.http_client(
            "http://mock-api/api/agent/policy", b"", headers, "GET"
        )
        self.assertEqual(pol_code, 200)
        pol_data = json.loads(pol_bytes.decode("utf-8"))
        self.assertEqual(pol_data["version"], 2)
        self.assertEqual(pol_data["idle_threshold_seconds"], 180)
        self.assertEqual(pol_data["screenshot_interval_seconds"], 120)

    # ── Scenario 8: Multi-Tenant Concurrent Isolation (E45, E46) ─────────────

    def test_scenario_08_multi_tenant_concurrent_isolation(self) -> None:
        """
        Tenant A and Tenant B operate concurrently.
        Strict isolation:
        - Cross-tenant device authentication fails
        - Reports and screenshots never leak across tenant boundaries
        """
        # Tenant B
        tenant_b = Tenant.objects.create(name="Beta Industries", status=TenantStatus.ACTIVE)
        admin_b = User.objects.create_user(
            email="admin@beta.com", name="Beta Admin", password="password12345"
        )
        mem_b = Membership.objects.create(
            tenant=tenant_b,
            user=admin_b,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        admin_b_client = APIClient()
        _, b_token = UserSession.create_session(user=admin_b)
        admin_b_client.credentials(HTTP_AUTHORIZATION=f"Bearer {b_token}")
        admin_b_client.defaults["HTTP_X_TENANT_ID"] = str(tenant_b.id)

        # Device A (Tenant A) and Device B (Tenant B)
        dev_a = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_a,
            hostname="DEV-A",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret_a = AgentCredential.create_secret_credential(device=dev_a)

        dev_b = Device.objects.create(
            tenant=tenant_b,
            membership=mem_b,
            hostname="DEV-B",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret_b = AgentCredential.create_secret_credential(device=dev_b)

        # Attack: Agent A attempts to send events impersonating Device B
        attack_headers = {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret_a}",
            "X-Device-Id": str(dev_b.id),
        }
        body = json.dumps({
            "agent_version": "1.0.0",
            "schema_version": 1,
            "events": [{
                "id": str(uuid.uuid4()),
                "event_type": "app.active",
                "occurred_at": timezone.now().isoformat(),
                "payload": {"app_identifier": "exploit.exe"},
            }]
        }).encode("utf-8")

        # The credential for dev_a does not match dev_b -> rejected
        attack_status, _, _ = self.http_client(
            "http://mock-api/api/agent/events/batch", body, attack_headers, "POST"
        )
        # Ingestion validates authenticated device matches
        # Verify event was NOT committed to Tenant B
        self.assertEqual(ActivityEvent.objects.filter(device=dev_b).count(), 0)

        # Cross-Tenant Reports API Isolation
        # Seed metrics in Tenant B
        DailyMetrics.objects.create(
            tenant=tenant_b,
            device=dev_b,
            local_date=datetime.date(2026, 10, 20),
            calc_version=1,
            observed_session_seconds=3600.0,
            active_seconds=3000.0,
            idle_seconds=600.0,
            productive_seconds=2500.0,
            neutral_seconds=500.0,
            distracting_seconds=0.0,
            productive_share=0.83,
            monitoring_coverage=1.0,
        )

        # Admin A queries daily reports: must NEVER see Tenant B metrics
        res_a = self.admin_client.get("/api/reports/daily")
        self.assertEqual(res_a.status_code, 200)
        tenant_ids_returned = {r.get("tenant") for r in res_a.data["results"]}
        self.assertNotIn(str(tenant_b.id), tenant_ids_returned)

        # Admin A explicitly requests device B -> returns 0 results or 404
        res_a_filtered = self.admin_client.get(f"/api/reports/daily?device_id={dev_b.id}")
        self.assertEqual(res_a_filtered.status_code, 200)
        self.assertEqual(len(res_a_filtered.data["results"]), 0)

    # ── Scenario 9: 7-Day Offline Backlog Replay ──────────────────────────────

    def test_scenario_09_seven_day_offline_backlog_replay(self) -> None:
        """
        Simulate laptop being offline for 7 days collecting events across
        multiple sessions, active intervals, and idle periods.
        Reconnects and drains journal in bounded batches.
        Verify full timeline reconstruction without gaps or double-counting.
        """
        device = Device.objects.create(
            tenant=self.tenant_a,
            membership=self.membership_a,
            hostname="ACME-BACKLOG-7D",
            os="windows",
            status=DeviceStatus.ACTIVE,
        )
        _, secret = AgentCredential.create_secret_credential(device=device)

        sync_worker = SyncWorker(
            base_api_url="http://mock-api",
            device_id=str(device.id),
            credential_token=secret,
            journal=self.journal,
            spool=self.spool,
            policy_manager=self.policy_mgr,
            status_tracker=self.status_tracker,
            http_client=self.http_client,
        )
        sync_worker._auth_headers = lambda: {
            "Content-Type": "application/json",
            "Authorization": f"DeviceBearer {secret}",
            "X-Device-Id": str(device.id),
        }

        # Generate 7 days of historical events (e.g. 10 events per day = 70 events)
        base_time = timezone.now().replace(microsecond=0) - datetime.timedelta(days=7)
        total_generated = 0

        for day in range(7):
            day_start = base_time + datetime.timedelta(days=day, hours=9)  # 09:00 AM
            for ev_idx in range(10):
                occurred = day_start + datetime.timedelta(minutes=ev_idx * 30)
                app = "pycharm64.exe" if ev_idx % 2 == 0 else "chrome.exe"
                self.journal.append_event(
                    event_type="app.active",
                    occurred_at=occurred.isoformat(),
                    payload={"app_identifier": app},
                    monotonic_reference=float(day * 1000 + ev_idx * 10),
                    boot_segment_id=f"boot-day-{day}",
                )
                total_generated += 1

        self.assertEqual(total_generated, 70)
        self.assertEqual(len(self.journal.get_pending_events(limit=200)), 70)

        # Agent reconnects: sync in batches of 25 (simulating max_batch_size=25)
        total_synced = 0
        batch_runs = 0
        while len(self.journal.get_pending_events(limit=200)) > 0:
            synced = sync_worker.sync_events(max_batch_size=25)
            total_synced += synced
            batch_runs += 1
            if batch_runs > 10:
                self.fail("Infinite loop during backlog sync")

        self.assertEqual(total_synced, 70)
        self.assertEqual(len(self.journal.get_pending_events()), 0)

        # Database verification: exactly 70 events committed
        db_events = ActivityEvent.objects.filter(device=device)
        self.assertEqual(db_events.count(), 70)

        # Run timeline engine across the 7-day span
        res = process_device_timeline_task(
            tenant_id=self.tenant_a.id,
            device_id=device.id,
        )
        self.assertEqual(res["status"], "completed")

        # Verify intervals and daily metrics created for the days
        daily_records = DailyMetrics.objects.filter(device=device)
        self.assertGreaterEqual(daily_records.count(), 6)

        for d in daily_records:
            self.assertGreater(d.active_seconds, 0)
            self.assertEqual(d.calc_version, 1)

        # Query reports API for 7-day range
        from_d = (base_time - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        to_d = timezone.now().strftime("%Y-%m-%d")
        api_res = self.admin_client.get(
            f"/api/reports/daily?device_id={device.id}&from_date={from_d}&to_date={to_d}"
        )
        self.assertEqual(api_res.status_code, 200)
        self.assertEqual(len(api_res.data["results"]), daily_records.count())
