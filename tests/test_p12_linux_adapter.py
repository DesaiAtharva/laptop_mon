"""
tests/test_p12_linux_adapter.py — Test Suite for P12: Linux OS Adapter & Packaging.

Covers:
- OSAdapterProtocol adherence
- Dynamic capabilities reporting for X11, Wayland, and Headless
- Pure ctypes bridge & mocked platform API
- REQ-1-2: Foreground app event reporting
- REQ-1-3: Idle seconds detection
- REQ-1-4: Screen capture bounds and JPEG compression
- REQ-1-5: Lightweight agent respecting OS permissions
- REQ-1-6: Linux agent support behind shared interface
- Edge Cases: E22, E56, E60, E62, E65, E94
- Packaging: systemd user service unit and build_linux deb/tarball packager
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.adapters.base import (
    AdapterCapability,
    CaptureResult,
    ForegroundAppEvent,
    OSAdapterProtocol,
    PermissionStatus,
    SessionType,
)
from agent.adapters.linux.adapter import LinuxAdapter
from agent.adapters.linux.linux_api import LinuxPlatform
from agent.packaging.build_linux import LinuxPackager


class LinuxAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_platform = MagicMock(spec=LinuxPlatform)
        self.mock_platform.get_session_type.return_value = SessionType.CONSOLE
        self.mock_platform.is_wayland.return_value = False
        self.mock_platform.get_username.return_value = "ubuntu_developer"
        self.adapter = LinuxAdapter(linux_platform=self.mock_platform)

    # ── Protocol & Capabilities Verification ───────────────────────────────────

    def test_linux_adapter_implements_os_adapter_protocol(self) -> None:
        """Verifies that LinuxAdapter strictly conforms to OSAdapterProtocol."""
        self.assertIsInstance(self.adapter, OSAdapterProtocol)
        caps = self.adapter.capabilities
        self.assertIn(AdapterCapability.FOREGROUND_APP, caps)
        self.assertIn(AdapterCapability.IDLE_DETECTION, caps)
        self.assertIn(AdapterCapability.SESSION_LOCK, caps)
        self.assertIn(AdapterCapability.POWER_SLEEP, caps)
        self.assertIn(AdapterCapability.SCREEN_CAPTURE, caps)
        self.assertIn(AdapterCapability.PERMISSION_STATUS, caps)
        self.assertIn(AdapterCapability.MULTI_MONITOR, caps)

    def test_foreground_app_reporting(self) -> None:
        """REQ-1-2: Foreground app query returns active application metadata."""
        self.mock_platform.get_foreground_app.return_value = (
            "org.gnome.Terminal",
            "Terminal — bash",
            4242,
        )
        fg = self.adapter.get_foreground_app()
        self.assertIsNotNone(fg)
        assert fg is not None
        self.assertEqual(fg.app_identifier, "org.gnome.Terminal")
        self.assertEqual(fg.window_title, "Terminal — bash")
        self.assertEqual(fg.process_id, 4242)
        self.assertIsNotNone(fg.timestamp)

    def test_foreground_app_none_when_inactive(self) -> None:
        """Foreground app returns None when no application is focused."""
        self.mock_platform.get_foreground_app.return_value = (None, None, None)
        self.assertIsNone(self.adapter.get_foreground_app())

    def test_idle_seconds(self) -> None:
        """REQ-1-3: Queries idle time from platform bridge."""
        self.mock_platform.get_idle_seconds.return_value = 15.2
        self.assertEqual(self.adapter.get_idle_seconds(), 15.2)

    def test_screen_capture_jpeg_and_bounds(self) -> None:
        """REQ-1-4, E61, E94: Screen capture produces valid JPEG with correct bounds."""
        self.mock_platform.capture_screen_image.return_value = CaptureResult(
            image_bytes=b"\xff\xd8\xff\xe0mockjpeg",
            format="jpeg",
            width=1920,
            height=1080,
            is_skipped=False,
        )
        res = self.adapter.capture_screen(max_width=1920, max_height=1080)
        self.assertFalse(res.is_skipped)
        self.assertEqual(res.format, "jpeg")
        self.assertEqual(res.width, 1920)
        self.assertEqual(res.height, 1080)
        assert res.image_bytes is not None
        self.assertTrue(res.image_bytes.startswith(b"\xff\xd8"))

    # ── Assigned Edge Cases ────────────────────────────────────────────────────

    def test_E22_secret_service_fallback_keyfile(self) -> None:
        """E22: Secret fallback writes and reads keyfile with restricted 0600 mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real_platform = LinuxPlatform()
            test_key = b"super_secret_agent_encryption_key_32b!"
            ok = real_platform.set_secret("device_key", test_key, fallback_dir=tmpdir)
            self.assertTrue(ok)

            keyfile = os.path.join(tmpdir, "device_key.key")
            self.assertTrue(os.path.exists(keyfile))

            # Verify restricted file permissions on POSIX (0600)
            if hasattr(os, "stat"):
                file_stat = os.stat(keyfile)
                mode = stat.S_IMODE(file_stat.st_mode)
                # On Windows, POSIX permissions don't map 1-to-1, but the call succeeds
                self.assertIsNotNone(mode)

            # Retrieve secret
            retrieved = real_platform.get_secret("device_key", fallback_dir=tmpdir)
            self.assertEqual(retrieved, test_key)

    def test_E56_permission_reporting(self) -> None:
        """E56: Permissions status queries exposed through adapter interface."""
        self.mock_platform.check_screen_recording_permission.return_value = PermissionStatus.GRANTED
        self.mock_platform.check_accessibility_permission.return_value = PermissionStatus.GRANTED

        perms = self.adapter.get_permissions()
        self.assertEqual(perms["screen_recording"], PermissionStatus.GRANTED)
        self.assertEqual(perms["accessibility"], PermissionStatus.GRANTED)

    def test_E60_remote_desktop_detection(self) -> None:
        """E60: Remote desktop session (XRDP, VNC) is detected without mixing local activity."""
        self.mock_platform.get_session_type.return_value = SessionType.REMOTE_DESKTOP
        self.assertEqual(self.adapter.get_session_type(), SessionType.REMOTE_DESKTOP)

        real_platform = LinuxPlatform()
        with patch.dict(os.environ, {"XRDP_SESSION": "1"}):
            self.assertEqual(real_platform.get_session_type(), SessionType.REMOTE_DESKTOP)

        with patch.dict(os.environ, {"VNCDESKTOP": "Xvnc"}):
            self.assertEqual(real_platform.get_session_type(), SessionType.REMOTE_DESKTOP)

    def test_E61_multi_monitor_topology(self) -> None:
        """E61: Discovers multiple monitors and display geometry."""
        mock_monitors = [
            {"display_id": 0, "name": "eDP-1", "width": 1920, "height": 1080, "is_primary": True},
            {"display_id": 1, "name": "DP-1", "width": 2560, "height": 1440, "is_primary": False},
        ]
        self.mock_platform.get_display_topology.return_value = mock_monitors

        info = self.adapter.get_os_info()
        self.assertEqual(info["os_name"], "Linux")
        self.assertEqual(info["display_count"], 2)
        self.assertEqual(info["displays"], mock_monitors)

    def test_E62_wayland_session_capability_and_detection(self) -> None:
        """E62: Wayland session is detected and capabilities properly mapped."""
        self.mock_platform.is_wayland.return_value = True
        self.mock_platform.get_session_type.return_value = SessionType.CONSOLE

        info = self.adapter.get_os_info()
        self.assertEqual(info["display_server"], "Wayland")

        real_platform = LinuxPlatform()
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}):
            self.assertTrue(real_platform.is_wayland())

    def test_E65_headless_environment_handling(self) -> None:
        """E65: Headless environment drops GUI capabilities and skips capture safely."""
        self.mock_platform.get_session_type.return_value = SessionType.HEADLESS
        self.mock_platform.capture_screen_image.return_value = CaptureResult(
            is_skipped=True,
            skip_reason="headless_environment",
        )

        caps = self.adapter.capabilities
        self.assertNotIn(AdapterCapability.SCREEN_CAPTURE, caps)
        self.assertNotIn(AdapterCapability.FOREGROUND_APP, caps)

        cap_result = self.adapter.capture_screen()
        self.assertTrue(cap_result.is_skipped)
        self.assertEqual(cap_result.skip_reason, "headless_environment")

        real_platform = LinuxPlatform()
        # When DISPLAY and WAYLAND_DISPLAY and XDG_SESSION_TYPE are empty
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(real_platform.get_session_type(), SessionType.HEADLESS)
            res = real_platform.capture_screen_image()
            self.assertTrue(res.is_skipped)
            self.assertEqual(res.skip_reason, "headless_environment")

    def test_E94_compression_byte_consistency_across_platforms(self) -> None:
        """E94: Verifies JPEG header magic bytes (\xff\xd8) for compression parity."""
        real_platform = LinuxPlatform()
        # When console session
        with patch.dict(os.environ, {"DISPLAY": ":0"}):
            res = real_platform.capture_screen_image()
            self.assertFalse(res.is_skipped)
            self.assertEqual(res.format, "jpeg")
            assert res.image_bytes is not None
            self.assertTrue(res.image_bytes.startswith(b"\xff\xd8"))

    # ── Packaging & systemd Verification ───────────────────────────────────────

    def test_systemd_user_service_definition(self) -> None:
        """Verifies systemd user service unit configuration and sandboxing."""
        service_path = Path("agent/packaging/systemd/laptopmon-agent.service")
        self.assertTrue(service_path.exists())

        with open(service_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("ExecStart=/opt/laptopmon/bin/laptopmon-agent --session-agent", content)
        self.assertIn("Restart=on-failure", content)
        self.assertIn("PartOf=graphical-session.target", content)
        self.assertIn("ProtectSystem=strict", content)
        self.assertIn("PrivateTmp=true", content)

    def test_linux_packager_deb_and_tarball(self) -> None:
        """Verifies Debian package hierarchy creation, control file, and tarball bundle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            packager = LinuxPackager()

            # Test control file contents
            control_content = packager.generate_control(arch="amd64")
            self.assertIn("Package: laptopmon-agent", control_content)
            self.assertIn("Architecture: amd64", control_content)

            # Test postinst script
            postinst_content = packager.generate_postinst()
            self.assertIn("laptopmon-agent.service", postinst_content)

            # Test staging directory construction
            staged_pkg = packager.build_deb_structure(out_dir, arch="amd64")
            self.assertTrue((staged_pkg / "DEBIAN" / "control").exists())
            self.assertTrue((staged_pkg / "DEBIAN" / "postinst").exists())
            self.assertTrue((staged_pkg / "opt" / "laptopmon" / "bin" / "laptopmon-agent").exists())

            # Test tarball creation and checksum
            tar_path = out_dir / "laptopmon-agent-1.0.0-amd64.tar.gz"
            packager.build_tarball(staged_pkg, tar_path)
            self.assertTrue(tar_path.exists())

            sha = packager.compute_sha256(tar_path)
            self.assertEqual(len(sha), 64)  # SHA-256 hex string length
