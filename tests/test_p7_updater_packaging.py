"""
tests/test_p7_updater_packaging.py — Comprehensive Test Suite for Prompt P7.

Covers:
- Packaging, code signing, and bundle lightness (< 60 MB)
- Agent installer with silent arguments (/TOKEN=, /SERVER=, /QUIET)
- Agent uninstaller with pending data safety policy (REQ-15-2, E13)
- Atomic updater with SHA-256 verification, staging, and self-test verification (REQ-4-5)
- Automatic rollback to known-good version without losing local queues (REQ-4-6, E15)
- Never update during shutdown (REQ-4-7)
- Edge Cases: E13, E14, E15, E16, E91, E92
- Backend release manifest endpoints with rollout percentages and RBAC audit logging
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from agent.adapters.base import PermissionStatus
from agent.core.updater import (
    AgentUpdater,
    ReleaseManifest,
    ShutdownInProgressError,
    SignatureVerificationError,
    VersionIncompatibleError,
)
from agent.installer.install import install, parse_arguments as parse_install_args
from agent.installer.uninstall import (
    check_pending_events,
    export_pending_events,
    parse_arguments as parse_uninstall_args,
    uninstall,
)
from agent.packaging.build_windows import build_package
from agent.packaging.signing import (
    compute_file_sha256,
    sign_manifest,
    verify_manifest_signature,
)
from apps.accounts.models import User, UserSession
from apps.audit.models import AuditLog
from apps.devices.models import AgentCredential, Device, DeviceStatus
from apps.releases.models import AgentRelease
from apps.tenancy.models import Membership, MembershipRole, MembershipStatus, Tenant, TenantStatus


class AgentPackagingAndSigningTests(unittest.TestCase):
    """Tests for packaging, signing, and bundle lightness."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.repo_root = Path(__file__).resolve().parent.parent

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_manifest_signing_and_tamper_rejection(self) -> None:
        """REQ-4-5: Manifest signatures verify and any tampering is rejected."""
        manifest = {
            "version": "1.2.0",
            "channel": "stable",
            "platform": "windows",
            "sha256": "abc123def456",
        }
        sig = sign_manifest(manifest)
        self.assertTrue(verify_manifest_signature(manifest, sig))

        # Tampered manifest must be rejected
        tampered = dict(manifest)
        tampered["version"] = "1.2.1"
        self.assertFalse(verify_manifest_signature(tampered, sig))

    def test_packaging_enforces_bundle_lightness(self) -> None:
        """Enforces installed/bundle size < 60 MB and generates zip + manifest."""
        out_dir = Path(self.temp_dir) / "dist"
        res = build_package(repo_root=self.repo_root, version="1.0.0-test", output_dir=out_dir)

        self.assertTrue(res["success"])
        zip_path = Path(res["zip_path"])
        self.assertTrue(zip_path.exists())

        # Check size < 60 MB
        size_bytes = zip_path.stat().st_size
        self.assertLess(size_bytes, 60 * 1024 * 1024)

        # Check manifest contents
        manifest_path = Path(res["manifest_path"])
        self.assertTrue(manifest_path.exists())
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["version"], "1.0.0-test")
            self.assertEqual(data["sha256"], compute_file_sha256(zip_path))
            self.assertTrue(verify_manifest_signature(data, data["signature"]))


class AgentInstallerUninstallerTests(unittest.TestCase):
    """Tests for installer CLI arguments, silent setup, and uninstaller data safety."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.install_dir = Path(self.temp_dir) / "LaptopMon"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_REQ_15_1_silent_installer_arguments(self) -> None:
        """REQ-15-1: Silent installer creates layout, writes config, and parses slash args."""
        argv = [
            f"/TARGET_DIR={self.install_dir}",
            "/TOKEN=enrollment-token-xyz-123",
            "/SERVER=https://mon.enterprise.com",
            "/QUIET",
            "/NO_STARTUP",
        ]
        args = parse_install_args(argv)
        self.assertEqual(args.target_dir, str(self.install_dir))
        self.assertEqual(args.token, "enrollment-token-xyz-123")
        self.assertEqual(args.server, "https://mon.enterprise.com")
        self.assertTrue(args.quiet)
        self.assertTrue(args.no_startup)

        res = install(
            target_dir=args.target_dir,
            token=args.token,
            server=args.server,
            quiet=args.quiet,
            register_startup=False,
        )
        self.assertTrue(res["success"])
        self.assertTrue((self.install_dir / "bin").exists())
        self.assertTrue((self.install_dir / "data").exists())
        self.assertTrue((self.install_dir / "logs").exists())

        config_path = self.install_dir / "config.json"
        self.assertTrue(config_path.exists())
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            self.assertEqual(cfg["enrollment_token"], "enrollment-token-xyz-123")
            self.assertEqual(cfg["server_url"], "https://mon.enterprise.com")

    def _create_sample_journal(self, data_dir: Path, pending_count: int = 5) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "journal.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "CREATE TABLE journal ("
                "id TEXT PRIMARY KEY, event_type TEXT, timestamp TEXT, payload TEXT, status TEXT"
                ")"
            )
            for i in range(pending_count):
                conn.execute(
                    "INSERT INTO journal VALUES (?, ?, ?, ?, ?)",
                    (f"evt-{i}", "window.switch", "2026-10-28T12:00:00Z", '{"title": "doc"}', "pending"),
                )
            conn.commit()
        finally:
            conn.close()

    def test_E13_uninstaller_pending_unsynced_data(self) -> None:
        """REQ-15-2 & E13: Uninstaller refuses deletion if pending unsynced events remain."""
        install_res = install(target_dir=self.install_dir, quiet=True, register_startup=False)
        self.assertTrue(install_res["success"])

        data_dir = self.install_dir / "data"
        self._create_sample_journal(data_dir, pending_count=3)
        self.assertEqual(check_pending_events(data_dir), 3)

        # 1. Attempt uninstall without export or force-delete -> must be BLOCKED
        res_blocked = uninstall(install_dir=self.install_dir, quiet=True, unregister_startup=False)
        self.assertFalse(res_blocked["success"])
        self.assertEqual(res_blocked["error"], "PENDING_DATA_BLOCKED")
        self.assertEqual(res_blocked["pending_count"], 3)
        self.assertTrue(self.install_dir.exists())

        # 2. Attempt uninstall with --export-path -> exports unacknowledged data and succeeds
        export_file = Path(self.temp_dir) / "exported_events.json"
        res_exported = uninstall(
            install_dir=self.install_dir,
            export_path=export_file,
            quiet=True,
            unregister_startup=False,
        )
        self.assertTrue(res_exported["success"])
        self.assertEqual(res_exported["exported_count"], 3)
        self.assertTrue(export_file.exists())
        with open(export_file, "r", encoding="utf-8") as f:
            exported_data = json.load(f)
            self.assertEqual(exported_data["exported_pending_count"], 3)
            self.assertEqual(len(exported_data["events"]), 3)
        self.assertFalse(self.install_dir.exists())

    def test_uninstaller_force_delete(self) -> None:
        """REQ-15-2: Uninstaller allows deliberate purge when force_delete=True."""
        install(target_dir=self.install_dir, quiet=True, register_startup=False)
        data_dir = self.install_dir / "data"
        self._create_sample_journal(data_dir, pending_count=2)

        res = uninstall(install_dir=self.install_dir, force_delete=True, quiet=True, unregister_startup=False)
        self.assertTrue(res["success"])
        self.assertFalse(self.install_dir.exists())


class AgentUpdaterTests(unittest.TestCase):
    """Tests for updater staging, hash/signature validation, atomic swap, and rollback."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.install_dir = Path(self.temp_dir) / "LaptopMon"
        self.bin_dir = self.install_dir / "bin"
        self.data_dir = self.install_dir / "data"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initial executable and version manifest
        self.exe_path = self.bin_dir / "agent.exe"
        initial_bytes = b"INITIAL_AGENT_V1.0.0"
        self.exe_path.write_bytes(initial_bytes)
        (self.bin_dir / "version.json").write_text(
            json.dumps({"version": "1.0.0", "sha256": hashlib.sha256(initial_bytes).hexdigest()}),
            encoding="utf-8",
        )

        self.updater = AgentUpdater(
            current_version="1.0.0",
            install_dir=str(self.install_dir),
            base_api_url="http://localhost:8000",
            public_key_or_cert="TEST_PUBKEY",
            signature_verifier=lambda payload, sig, pubkey: sig == "valid_test_sig",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_REQ_4_5_update_hash_and_signature_verification(self) -> None:
        """REQ-4-5: Tampered download package fails verification and is rejected."""
        good_payload = b"VALID_NEW_BINARY_V1.1.0"
        good_hash = hashlib.sha256(good_payload).hexdigest()

        manifest = ReleaseManifest(
            version="1.1.0",
            channel="stable",
            platform="windows",
            package_url="http://mock/agent.zip",
            sha256=good_hash,
            signature="valid_test_sig",
            min_agent_version="1.0.0",
        )

        # Mock download returning good payload
        self.updater.http_client = lambda url: good_payload
        success = self.updater.apply_update(manifest)
        self.assertTrue(success)
        self.assertEqual(self.updater.current_version, "1.1.0")

        # Now test hash mismatch rejection
        manifest_corrupt = ReleaseManifest(
            version="1.2.0",
            channel="stable",
            platform="windows",
            package_url="http://mock/agent.zip",
            sha256="wrong_hash_1234567890",
            signature="valid_test_sig",
            min_agent_version="1.0.0",
        )
        with self.assertRaises(SignatureVerificationError):
            self.updater.apply_update(manifest_corrupt)

        # Test invalid signature rejection
        manifest_bad_sig = ReleaseManifest(
            version="1.3.0",
            channel="stable",
            platform="windows",
            package_url="http://mock/agent.zip",
            sha256=good_hash,
            signature="tampered_or_invalid_signature",
            min_agent_version="1.0.0",
        )
        with self.assertRaises(SignatureVerificationError):
            self.updater.apply_update(manifest_bad_sig)

    def test_REQ_4_7_never_update_during_shutdown(self) -> None:
        """REQ-4-7: Updater aborts immediately if OS shutdown is detected."""
        manifest = ReleaseManifest(
            version="1.1.0",
            channel="stable",
            platform="windows",
            package_url="http://mock/agent.zip",
            sha256=hashlib.sha256(b"DATA").hexdigest(),
            signature="valid_test_sig",
            min_agent_version="1.0.0",
        )
        with self.assertRaises(ShutdownInProgressError):
            self.updater.apply_update(manifest, is_shutting_down=True)

        # Original binary remains untouched
        self.assertEqual(self.exe_path.read_bytes(), b"INITIAL_AGENT_V1.0.0")

    def test_E15_interrupted_update_automatic_rollback(self) -> None:
        """REQ-4-6 & E15: Failed self-test triggers atomic rollback to known-good version."""
        # Create journal with unacknowledged events in data_dir
        journal_file = self.data_dir / "journal.db"
        journal_file.write_text("PRESERVED_LOCAL_QUEUE_DATA", encoding="utf-8")

        new_payload = b"NEW_BINARY_FAILS_VERIFICATION"
        manifest = ReleaseManifest(
            version="1.2.0",
            channel="stable",
            platform="windows",
            package_url="http://mock/agent.zip",
            sha256=hashlib.sha256(new_payload).hexdigest(),
            signature="valid_test_sig",
            min_agent_version="1.0.0",
        )
        self.updater.http_client = lambda url: new_payload

        # Mock verify_self_integrity to simulate failed verification on new binary
        with patch.object(self.updater, "verify_self_integrity", return_value=False):
            success = self.updater.apply_update(manifest)

        self.assertFalse(success)
        # Verify rollback restored the original binary
        self.assertEqual(self.exe_path.read_bytes(), b"INITIAL_AGENT_V1.0.0")
        # Verify local queues and journal were never touched or destroyed
        self.assertTrue(journal_file.exists())
        self.assertEqual(journal_file.read_text(encoding="utf-8"), "PRESERVED_LOCAL_QUEUE_DATA")

    def test_E14_os_update_or_reboot_preserves_policy_and_data(self) -> None:
        """E14: Reboot hook re-verifies permissions and policy and preserves journal state."""
        journal_file = self.data_dir / "journal.db"
        journal_file.write_text("JOURNAL_ACROSS_REBOOT", encoding="utf-8")

        mock_adapter = MagicMock()
        mock_adapter.get_permissions.return_value = {
            "screen_capture": PermissionStatus.GRANTED,
            "accessibility": PermissionStatus.GRANTED,
        }
        mock_policy_mgr = MagicMock()
        mock_policy_mgr.is_policy_valid.return_value = True

        status_report = self.updater.on_os_update_or_reboot(mock_adapter, mock_policy_mgr)
        self.assertTrue(status_report["reboot_detected"])
        self.assertTrue(status_report["permissions_ok"])
        self.assertTrue(status_report["policy_valid"])
        self.assertTrue(journal_file.exists())
        self.assertEqual(journal_file.read_text(encoding="utf-8"), "JOURNAL_ACROSS_REBOOT")

    def test_E91_tampering_corrupted_binary_rollback_or_halt(self) -> None:
        """E91 & LIM-005: Local admin binary corruption is detected by self-integrity checks."""
        # Initial state: verify_self_integrity is True
        self.assertTrue(self.updater.verify_self_integrity())

        # Corrupt the binary on disk
        self.exe_path.write_bytes(b"CORRUPTED_TAMPERED_EXE_PAYLOAD")

        # Integrity check detects tampering
        self.assertFalse(self.updater.verify_self_integrity())

        # Rollback attempt without backup safely returns False and does not crash
        res = self.updater.rollback()
        self.assertFalse(res)


class BackendReleaseViewsTests(TestCase):
    """Tests for backend release endpoints: rollout bucketing, compatibility checks, and RBAC."""

    def setUp(self) -> None:
        self.client = APIClient()
        cache.clear()

        self.tenant = Tenant.objects.create(name="Stark Industries", status=TenantStatus.ACTIVE)
        self.admin_user = User.objects.create_user(email="tony@stark.com", name="Tony Stark")
        self.admin_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.admin_user,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        self.employee_user = User.objects.create_user(email="peter@stark.com", name="Peter Parker")
        self.employee_membership = Membership.objects.create(
            tenant=self.tenant,
            user=self.employee_user,
            role=MembershipRole.EMPLOYEE,
            status=MembershipStatus.ACTIVE,
        )

        self.device = Device.objects.create(
            tenant=self.tenant,
            membership=self.employee_membership,
            hostname="STARK-LAPTOP-01",
            os="windows",
            agent_version="1.0.0",
            status=DeviceStatus.ACTIVE,
            last_seen_at=timezone.now(),
        )
        self.cred, self.raw_secret = AgentCredential.create_secret_credential(self.device)

    def _auth_device(self) -> APIClient:
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"DeviceBearer {self.raw_secret}")
        return c

    def _auth_user(self, user: User) -> APIClient:
        c = APIClient()
        session, raw_token = UserSession.create_session(user=user)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        c.defaults["HTTP_X_TENANT_ID"] = str(self.tenant.id)
        return c

    def test_backend_release_manifest_creation_and_audit(self) -> None:
        """Admin creates release manifest; audit log entry is recorded with log_audit_event."""
        admin_client = self._auth_user(self.admin_user)
        payload = {
            "version": "1.1.0",
            "channel": "stable",
            "platform": "windows",
            "package_url": "https://storage.enterprise.com/LaptopMonAgent-1.1.0.zip",
            "sha256_checksum": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "signature": "dev-sig",
            "rollout_percentage": 100,
            "min_agent_version": "1.0.0",
        }
        res = admin_client.post("/api/releases/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["version"], "1.1.0")

        # Verify audit log was created
        audit_entry = AuditLog.objects.filter(action="agent.release.created").first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.actor, self.admin_user)

    def test_backend_release_creation_rbac_denied_for_employee(self) -> None:
        """Negative test: Non-admin users cannot create release manifests."""
        emp_client = self._auth_user(self.employee_user)
        payload = {
            "version": "2.0.0",
            "channel": "stable",
            "platform": "windows",
            "package_url": "https://storage.enterprise.com/agent-2.0.0.zip",
            "sha256_checksum": "1122334455667788112233445566778811223344556677881122334455667788",
            "signature": "sig",
        }
        res = emp_client.post("/api/releases/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_fetches_latest_release_with_rollout_percentage(self) -> None:
        """Agent queries latest release; respects rollout percentage bucketing."""
        dev_client = self._auth_device()

        # Release at 0% rollout -> not delivered to device
        AgentRelease.objects.create(
            version="1.5.0",
            channel="stable",
            platform="windows",
            package_url="https://storage.enterprise.com/1.5.0.zip",
            sha256_checksum="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            signature="sig",
            rollout_percentage=0,
        )

        res_none = dev_client.get("/api/agent/releases/latest/?channel=stable&current_version=1.0.0")
        self.assertEqual(res_none.status_code, status.HTTP_200_OK)
        self.assertFalse(res_none.data["update_available"])

        # Release at 100% rollout -> delivered to device
        AgentRelease.objects.create(
            version="1.6.0",
            channel="stable",
            platform="windows",
            package_url="https://storage.enterprise.com/1.6.0.zip",
            sha256_checksum="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            signature="sig",
            rollout_percentage=100,
        )

        res_avail = dev_client.get("/api/agent/releases/latest/?channel=stable&current_version=1.0.0")
        self.assertEqual(res_avail.status_code, status.HTTP_200_OK)
        self.assertTrue(res_avail.data["update_available"])
        self.assertEqual(res_avail.data["version"], "1.6.0")

    def test_E16_version_mismatch_agent_server(self) -> None:
        """E16: Releases with incompatible min/max agent version constraints are skipped."""
        dev_client = self._auth_device()

        # Release requiring min_agent_version="2.0.0" cannot be applied to agent 1.0.0
        AgentRelease.objects.create(
            version="2.1.0",
            channel="stable",
            platform="windows",
            package_url="https://storage.enterprise.com/2.1.0.zip",
            sha256_checksum="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            signature="sig",
            rollout_percentage=100,
            min_agent_version="2.0.0",
        )

        res = dev_client.get("/api/agent/releases/latest/?channel=stable&current_version=1.0.0")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Incompatible release is skipped
        self.assertFalse(res.data["update_available"])


class AntivirusAllowlistingDocTests(unittest.TestCase):
    """Test ensuring allowlisting documentation and anti-evasion stance are present."""

    def test_E92_antivirus_allowlisting_documentation(self) -> None:
        """E92: IT allowlisting doc exists and documents Authenticode, SHA-256, and non-evasion."""
        doc_path = Path(__file__).resolve().parent.parent / "docs" / "SIGNING_AND_ALLOWLISTING.md"
        self.assertTrue(doc_path.exists())
        content = doc_path.read_text(encoding="utf-8")
        self.assertIn("Transparency & Anti-Evasion Pledge", content)
        self.assertIn("Authenticode", content)
        self.assertIn("timestamp.digicert.com", content)
        self.assertIn("LIM-005", content)
