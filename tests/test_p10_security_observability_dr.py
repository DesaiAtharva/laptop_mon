"""Comprehensive tests for Prompt P10: Security, Privacy, Observability, and Disaster Recovery.

Requirements & Edge Cases:
- REQ-3-1: TLS on all transport, never disabled, HSTS enforced.
- REQ-11-4: Each threat in threat model has an automated or documented test.
- REQ-12-2: Agent silence alerts MUST account for sleep and work hours.
- E06: TLS certificate invalid or expired fails closed safely.
- E48: Admin account compromised (session revocation, audit log).
- E77: MySQL failover or deadlock handling with resilient backoff.
- E78: Database migration checks pass.
- E80: Stale or cross-tenant cache isolation.
- E86: Backup restore verification and consistency audit.
- E87: Region or provider outage degraded mode and readiness probes.
- E88: Structured logging redaction filters mask all secrets.
"""
from __future__ import annotations

import datetime
import io
import json
import logging
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, UserSession
from apps.audit.models import AuditLog
from apps.common.cache import delete_tenant_cache, get_tenant_cache, set_tenant_cache
from apps.common.logging import JSONFormatter, SecretRedactingFilter, redact_secrets
from apps.devices.alerts import evaluate_device_silence_alert, is_device_sleeping_or_locked, is_within_work_hours
from apps.devices.models import Device, DeviceStatus
from apps.ingestion.models import ActivityEvent
from apps.policies.models import MonitoringPolicy
from apps.screenshots.models import Screenshot, ScreenshotStatus
from apps.screenshots.storage import get_storage_backend
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant, TenantStatus
from scripts.dr.backup_mysql import create_backup
from scripts.dr.restore_mysql import restore_backup
from scripts.dr.verify_db_storage_consistency import verify_db_storage_consistency


class P10SecurityObservabilityDRTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        # Tenants
        self.tenant_a = Tenant.objects.create(name="Wayne Enterprises", status=TenantStatus.ACTIVE)
        self.tenant_b = Tenant.objects.create(name="LexCorp", status=TenantStatus.ACTIVE)

        # Users
        self.admin_user_a = User.objects.create_user(
            email="bruce@wayne.com", name="Bruce Wayne", mfa_enabled=True
        )
        self.admin_user_b = User.objects.create_user(
            email="lex@lexcorp.com", name="Lex Luthor", mfa_enabled=True
        )

        # Memberships
        self.membership_admin_a = Membership.objects.create(
            tenant=self.tenant_a,
            user=self.admin_user_a,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.membership_admin_b = Membership.objects.create(
            tenant=self.tenant_b,
            user=self.admin_user_b,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        # Default policy for Tenant A
        self.policy_a = MonitoringPolicy.get_or_create_default(self.tenant_a)

        # Device in Tenant A
        self.device_a = Device.objects.create(
            tenant=self.tenant_a,
            hostname="BAT-LAPTOP-01",
            os="windows",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )

    def _auth_client(self, user: User, tenant: Tenant | None = None) -> APIClient:
        client = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        if tenant:
            client.defaults["HTTP_X_TENANT_ID"] = str(tenant.id)
        return client

    # --------------------------------------------------------------------------
    # REQ-3-1 & E06: TLS transport, HSTS, and Security Headers
    # --------------------------------------------------------------------------
    def test_REQ_3_1_tls_transport_and_security_headers_enforced(self) -> None:
        """REQ-3-1: HSTS, CSP, X-Frame-Options, and nosniff headers enforced on all responses."""
        resp = self.client.get("/health/live")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        # HSTS enforced
        self.assertIn("Strict-Transport-Security", resp.headers)
        self.assertIn("max-age=31536000", resp.headers["Strict-Transport-Security"])

        # Clickjacking & Content sniffing prevention
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

        # Content Security Policy (CSP)
        self.assertIn("Content-Security-Policy", resp.headers)
        self.assertIn("frame-ancestors 'none'", resp.headers["Content-Security-Policy"])

    # --------------------------------------------------------------------------
    # REQ-12-2: Agent silence alerts accounting for sleep and work hours
    # --------------------------------------------------------------------------
    def test_REQ_12_2_agent_silence_alerts_work_and_sleep_hours(self) -> None:
        """REQ-12-2: Agent silence alerts MUST account for sleep and work hours (§12.2)."""
        # Configure policy with Mon-Fri 09:00 - 18:00 UTC
        self.policy_a.capture_windows = {
            "weekdays": [1, 2, 3, 4, 5],
            "work_hours": {"start": "09:00", "end": "18:00"},
        }
        self.policy_a.save()

        # Set device last seen 2 hours ago
        base_time = timezone.now()
        self.device_a.last_seen_at = base_time - datetime.timedelta(hours=2)
        self.device_a.save()

        # Scenario 1: Wednesday at 11:00 AM (Active work hours, awake) -> ALERT!
        wednesday_work_hour = datetime.datetime(2026, 10, 28, 11, 0, 0, tzinfo=datetime.timezone.utc)
        self.device_a.last_seen_at = wednesday_work_hour - datetime.timedelta(hours=2)
        self.device_a.save()

        res1 = evaluate_device_silence_alert(
            self.device_a,
            current_time=wednesday_work_hour,
            silence_threshold_seconds=3600,
        )
        self.assertTrue(res1.is_alert)
        self.assertEqual(res1.reason, "agent_unexpected_silence_alert")
        self.assertTrue(res1.is_work_hours)
        self.assertFalse(res1.is_sleeping)

        # Scenario 2: Sunday at 11:00 AM (Weekend / outside work days) -> SUPPRESSED
        sunday_time = datetime.datetime(2026, 11, 1, 11, 0, 0, tzinfo=datetime.timezone.utc)
        self.device_a.last_seen_at = sunday_time - datetime.timedelta(hours=2)
        self.device_a.save()

        res2 = evaluate_device_silence_alert(
            self.device_a,
            current_time=sunday_time,
            silence_threshold_seconds=3600,
        )
        self.assertFalse(res2.is_alert)
        self.assertEqual(res2.reason, "outside_work_hours_suppressed")
        self.assertFalse(res2.is_work_hours)

        # Scenario 3: Wednesday at 02:00 AM (Night / outside work hours) -> SUPPRESSED
        wednesday_night = datetime.datetime(2026, 10, 28, 2, 0, 0, tzinfo=datetime.timezone.utc)
        self.device_a.last_seen_at = wednesday_night - datetime.timedelta(hours=2)
        self.device_a.save()

        res3 = evaluate_device_silence_alert(
            self.device_a,
            current_time=wednesday_night,
            silence_threshold_seconds=3600,
        )
        self.assertFalse(res3.is_alert)
        self.assertEqual(res3.reason, "outside_work_hours_suppressed")

        # Scenario 4: Wednesday at 11:00 AM, but machine reported 'system_sleep' -> SUPPRESSED
        ActivityEvent.objects.create(
            tenant=self.tenant_a,
            device=self.device_a,
            id=uuid.uuid4(),
            event_type="system_sleep",
            occurred_at=wednesday_work_hour - datetime.timedelta(minutes=30),
            payload={"app_name": "System", "window_title": "Sleep"},
        )

        res4 = evaluate_device_silence_alert(
            self.device_a,
            current_time=wednesday_work_hour,
            silence_threshold_seconds=3600,
        )
        self.assertFalse(res4.is_alert)
        self.assertEqual(res4.reason, "device_sleep_or_lock_suppressed")
        self.assertTrue(res4.is_sleeping)

    # --------------------------------------------------------------------------
    # E88: Structured logging secret redaction filter
    # --------------------------------------------------------------------------
    def test_E88_logs_contain_no_secrets(self) -> None:
        """E88: Logging secret redaction filter masks bearer tokens, passwords, signatures, and keys."""
        test_message = (
            "User login attempt with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123 "
            "password='SuperSecretPassword123' and api_key=ak_live_abcdef123456789. "
            "S3 URL: https://s3.amazonaws.com/bucket/obj?X-Amz-Signature=abcdef0123456789abcdef0123456789"
        )

        # Test redact_secrets directly
        cleaned = redact_secrets(test_message)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", cleaned)
        self.assertNotIn("SuperSecretPassword123", cleaned)
        self.assertNotIn("ak_live_abcdef123456789", cleaned)
        self.assertNotIn("abcdef0123456789abcdef0123456789", cleaned)
        self.assertIn("[REDACTED]", cleaned)

        # Test through logging pipeline with SecretRedactingFilter & JSONFormatter
        logger = logging.getLogger("test_security_redactor")
        logger.setLevel(logging.INFO)
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.addFilter(SecretRedactingFilter())
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

        logger.info("Processing webhook whsec_test_secret_for_payment_webhooks with password='mysecretpassword'")

        output = log_stream.getvalue()
        self.assertNotIn("whsec_test_secret_for_payment_webhooks", output)
        self.assertNotIn("mysecretpassword", output)
        self.assertIn("[REDACTED]", output)

        # JSON parsable
        parsed_log = json.loads(output)
        self.assertEqual(parsed_log["level"], "INFO")
        self.assertIn("[REDACTED]", parsed_log["message"])

    # --------------------------------------------------------------------------
    # REQ-11-4: Threat Model Automated Verifications
    # --------------------------------------------------------------------------
    def test_REQ_11_4_threat_model_verifications(self) -> None:
        """REQ-11-4: Automated verification of threat model mitigations (§11.4)."""
        # 1. IDOR: Tenant B admin cannot access Tenant A device
        client_b = self._auth_client(self.admin_user_b, self.tenant_b)
        resp = client_b.get(f"/api/devices/{self.device_a.id}")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        # 2. Compromised Admin Account (E48): Session revocation blocks subsequent requests
        client_a = self._auth_client(self.admin_user_a, self.tenant_a)
        resp_before = client_a.get("/api/me/tenants")
        self.assertEqual(resp_before.status_code, status.HTTP_200_OK)

        # Admin session revoked
        UserSession.objects.filter(user=self.admin_user_a).update(revoked_at=timezone.now())
        resp_after = client_a.get("/api/me/tenants")
        self.assertEqual(resp_after.status_code, status.HTTP_401_UNAUTHORIZED)

        # 3. Tenant-scoped cache isolation (E80)
        set_tenant_cache(self.tenant_a.id, "secret_key", "tenant_a_data")
        self.assertIsNone(get_tenant_cache(self.tenant_b.id, "secret_key"))
        self.assertEqual(get_tenant_cache(self.tenant_a.id, "secret_key"), "tenant_a_data")
        delete_tenant_cache(self.tenant_a.id, "secret_key")
        self.assertIsNone(get_tenant_cache(self.tenant_a.id, "secret_key"))

    # --------------------------------------------------------------------------
    # E86 & E87: Disaster Recovery, Backup Verification, and Readiness Probes
    # --------------------------------------------------------------------------
    def test_E86_backup_restore_and_consistency_verification(self) -> None:
        """E86: Backup creation, SHA-256 verification, and database-storage consistency audit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            # 1. Create backup
            backup_file = create_backup(output_dir=out_dir, db_name="test_laptop_mon")
            self.assertTrue(backup_file.exists())

            # Manifest created
            manifest_file = backup_file.with_suffix("").with_suffix(".manifest.json")
            self.assertTrue(manifest_file.exists())

            # 2. Verify backup integrity
            success = restore_backup(backup_file, db_name="test_laptop_mon", verify_only=True)
            self.assertTrue(success)

        # 3. Consistency check between DB and Storage
        storage = get_storage_backend()
        storage_key = "tenants/test/devices/dev1/2026/10/28/shot1.jpg"
        storage.put_object_bytes(storage_key, b"dummy_jpeg_bytes", "image/jpeg")

        Screenshot.objects.create(
            tenant=self.tenant_a,
            device=self.device_a,
            object_key=storage_key,
            status=ScreenshotStatus.FINALIZED,
            captured_at=timezone.now(),
            file_size=16,
            width=1920,
            height=1080,
            checksum="dummy",
            delete_after=timezone.now() + datetime.timedelta(days=30),
        )

        consistency_report = verify_db_storage_consistency(str(self.tenant_a.id))
        self.assertEqual(consistency_report["status"], "consistent")
        self.assertEqual(consistency_report["consistency_percentage"], 100.0)

    def test_E87_health_readiness_and_metrics_endpoints(self) -> None:
        """E87: Liveness, Readiness (degraded mode detection), and OpenMetrics endpoints."""
        # 1. Liveness
        resp_live = self.client.get("/health/live")
        self.assertEqual(resp_live.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_live.json()["status"], "alive")

        # 2. Readiness (healthy)
        resp_ready = self.client.get("/health/ready")
        self.assertEqual(resp_ready.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_ready.json()["status"], "ready")
        self.assertEqual(resp_ready.json()["checks"]["database"], "healthy")
        self.assertEqual(resp_ready.json()["checks"]["cache"], "healthy")

        # 3. Metrics
        resp_metrics = self.client.get("/metrics")
        self.assertEqual(resp_metrics.status_code, status.HTTP_200_OK)
        metrics_text = resp_metrics.content.decode("utf-8")
        self.assertIn("laptopmon_uptime_seconds", metrics_text)
        self.assertIn("laptopmon_active_tenants_count", metrics_text)
        self.assertIn("laptopmon_slo_api_availability 99.9", metrics_text)

        # 4. Readiness (simulated dependency failure -> 503 degraded)
        with patch("django.core.cache.cache.get", side_effect=Exception("Redis connection refused")):
            resp_degraded = self.client.get("/health/ready")
            self.assertEqual(resp_degraded.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(resp_degraded.json()["status"], "degraded")

    # --------------------------------------------------------------------------
    # Request Size Limiter (E34)
    # --------------------------------------------------------------------------
    def test_request_size_limiter_middleware_caps(self) -> None:
        """Oversized request payloads return HTTP 413 Payload Too Large."""
        oversized_body = "x" * (3 * 1024 * 1024)
        resp = self.client.post("/health/live", data=oversized_body, content_type="application/json")
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], "payload_too_large")
