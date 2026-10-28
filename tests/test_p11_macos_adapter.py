"""
tests/test_p11_macos_adapter.py — Test Suite for P11: macOS OS Adapter & Packaging.

Covers:
- OSAdapterProtocol adherence
- Pure ctypes bridge & mocked platform API
- REQ-1-6: macOS agent support behind shared interface
- REQ-4-1: Core code isolation
- Edge Cases: E14, E56, E59, E61, E63
- Packaging files: LaunchAgent plist and build_macos packager
"""

import os
import plistlib
import unittest
from unittest.mock import MagicMock, patch

from agent.adapters.base import (
    AdapterCapability,
    CaptureResult,
    ForegroundAppEvent,
    OSAdapterProtocol,
    PermissionStatus,
    SessionType,
)
from agent.adapters.macos.adapter import MacOSAdapter
from agent.adapters.macos.macos_api import MacOSPlatform
from agent.packaging.build_macos import MacOSPackager


class MacOSAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_platform = MagicMock(spec=MacOSPlatform)
        self.adapter = MacOSAdapter(macos_platform=self.mock_platform)

    # ── Protocol & Capabilities Verification ───────────────────────────────────

    def test_macos_adapter_implements_os_adapter_protocol(self) -> None:
        """Verifies that MacOSAdapter strictly conforms to OSAdapterProtocol."""
        self.assertIsInstance(self.adapter, OSAdapterProtocol)
        caps = self.adapter.capabilities
        self.assertIn(AdapterCapability.FOREGROUND_APP, caps)
        self.assertIn(AdapterCapability.IDLE_DETECTION, caps)
        self.assertIn(AdapterCapability.SESSION_LOCK, caps)
        self.assertIn(AdapterCapability.POWER_SLEEP, caps)
        self.assertIn(AdapterCapability.SCREEN_CAPTURE, caps)
        self.assertIn(AdapterCapability.PERMISSION_STATUS, caps)
        self.assertIn(AdapterCapability.MULTI_MONITOR, caps)

    # ── Foreground App & Bundle Identifier (REQ-1-6) ───────────────────────────

    def test_foreground_app_bundle_identifier(self) -> None:
        """Verifies that macOS foreground app returns bundle identifier, not raw binary path."""
        self.mock_platform.get_foreground_app.return_value = (
            "com.apple.Safari",
            "Apple — Start Page",
            12345,
        )
        fg = self.adapter.get_foreground_app()
        self.assertIsNotNone(fg)
        assert fg is not None
        self.assertEqual(fg.app_identifier, "com.apple.Safari")
        self.assertEqual(fg.window_title, "Apple — Start Page")
        self.assertEqual(fg.process_id, 12345)
        self.assertIsNotNone(fg.timestamp)

    def test_foreground_app_none_when_inactive(self) -> None:
        """Verifies foreground app returns None if no application is active."""
        self.mock_platform.get_foreground_app.return_value = (None, None, None)
        fg = self.adapter.get_foreground_app()
        self.assertIsNone(fg)

    def test_idle_seconds(self) -> None:
        """Verifies idle seconds query forwards to platform layer."""
        self.mock_platform.get_idle_seconds.return_value = 42.5
        self.assertEqual(self.adapter.get_idle_seconds(), 42.5)

    # ── Assigned Edge Cases ────────────────────────────────────────────────────

    def test_E14_os_update_or_reboot_verification(self) -> None:
        """E14: Re-verification after OS update checks permissions and generates guidance."""
        self.mock_platform.check_screen_recording_permission.return_value = PermissionStatus.GRANTED
        self.mock_platform.check_accessibility_permission.return_value = PermissionStatus.GRANTED

        report = self.adapter.verify_after_os_update()
        self.assertTrue(report["os_update_verified"])
        self.assertTrue(report["permissions_ok"])
        self.assertEqual(report["instructions"], "All permissions intact.")

    def test_E56_screen_recording_permission_denied_or_revoked(self) -> None:
        """E56: Denied screen recording permission returns skipped capture safely."""
        self.mock_platform.check_screen_recording_permission.return_value = PermissionStatus.DENIED
        self.mock_platform.check_accessibility_permission.return_value = PermissionStatus.GRANTED
        self.mock_platform.capture_screen_image.return_value = CaptureResult(
            is_skipped=True,
            skip_reason="permission_denied",
        )

        perms = self.adapter.get_permissions()
        self.assertEqual(perms["screen_capture"], PermissionStatus.DENIED)
        self.assertEqual(perms["accessibility"], PermissionStatus.GRANTED)

        cap = self.adapter.capture_screen()
        self.assertTrue(cap.is_skipped)
        self.assertEqual(cap.skip_reason, "permission_denied")

    def test_E59_fast_user_switching_console_session(self) -> None:
        """E59: Fast user switching detects non-console session and active console user."""
        self.mock_platform.get_session_type.return_value = SessionType.CONSOLE
        self.mock_platform.get_console_username.return_value = "sarah_connor"

        self.assertEqual(self.adapter.get_session_type(), SessionType.CONSOLE)
        self.assertEqual(self.adapter.get_os_username(), "sarah_connor")

    def test_E61_multi_monitor_topology_discovery(self) -> None:
        """E61: Multi-monitor configuration discovers all active displays and scale factors."""
        mock_displays = [
            {"display_id": 1, "width": 1728, "height": 1117, "scale": 2.0, "is_main": True},
            {"display_id": 2, "width": 3840, "height": 2160, "scale": 1.0, "is_main": False},
        ]
        self.mock_platform.get_display_topology.return_value = mock_displays

        info = self.adapter.get_os_info()
        self.assertEqual(info["os_name"], "macOS")
        self.assertEqual(info["display_count"], 2)
        self.assertEqual(info["displays"], mock_displays)

    def test_E61_screen_capture_bounded(self) -> None:
        """E61: Screen capture respects resolution caps and JPEG compression."""
        self.mock_platform.capture_screen_image.return_value = CaptureResult(
            image_bytes=b"\xff\xd8\xff\xe0mockjpeg",
            format="jpeg",
            width=800,
            height=600,
            is_skipped=False,
        )
        res = self.adapter.capture_screen(max_width=800, max_height=600)
        self.assertFalse(res.is_skipped)
        self.assertEqual(res.format, "jpeg")
        self.assertEqual(res.width, 800)
        self.assertEqual(res.height, 600)
        assert res.image_bytes is not None
        self.assertTrue(res.image_bytes.startswith(b"\xff\xd8"))

    def test_E63_macos_permission_reset_detection(self) -> None:
        """E63: TCC permission reset (e.g. after major OS update) detected without prompt loops."""
        self.mock_platform.check_screen_recording_permission.return_value = PermissionStatus.DENIED
        self.mock_platform.check_accessibility_permission.return_value = PermissionStatus.PROMPT_NEEDED

        report = self.adapter.verify_after_os_update()
        self.assertFalse(report["permissions_ok"])
        self.assertIn("Re-authorization required", report["instructions"])
        self.assertEqual(report["permissions"]["screen_capture"], PermissionStatus.DENIED)
        self.assertEqual(report["permissions"]["accessibility"], PermissionStatus.PROMPT_NEEDED)

    def test_battery_saver_low_power_mode(self) -> None:
        """Verifies battery saver state detection."""
        self.mock_platform.is_battery_saver.return_value = True
        self.assertTrue(self.adapter.is_battery_saver())

        self.mock_platform.is_battery_saver.return_value = False
        self.assertFalse(self.adapter.is_battery_saver())

    # ── Packaging & LaunchAgent Verification ───────────────────────────────────

    def test_launchagent_plist_validity(self) -> None:
        """Verifies that the LaunchAgent plist is valid XML and defines proper user-session keys."""
        plist_path = os.path.join(
            "agent", "packaging", "launchd", "com.laptopmon.agent.plist"
        )
        self.assertTrue(os.path.exists(plist_path))

        with open(plist_path, "rb") as f:
            data = plistlib.load(f)

        self.assertEqual(data.get("Label"), "com.laptopmon.agent")
        self.assertTrue(data.get("RunAtLoad"))
        self.assertEqual(data.get("LimitLoadToSessionType"), "Aqua")
        self.assertIn("/Applications/LaptopMon.app/Contents/MacOS/LaptopMon", data.get("ProgramArguments", []))


    def test_macos_packager_manifest_and_entitlements(self) -> None:
        """Verifies packager builds Info.plist, entitlements, and package metadata."""
        packager = MacOSPackager()
        info_plist = packager.generate_info_plist()
        self.assertIn("CFBundleIdentifier", info_plist)
        self.assertEqual(info_plist["CFBundleIdentifier"], "com.laptopmon.agent")
        self.assertIn("LSUIElement", info_plist)  # Menu bar/agent background app

        entitlements = packager.generate_entitlements()
        self.assertIn("com.apple.security.cs.allow-jit", entitlements)
        self.assertIn("com.apple.security.cs.disable-library-validation", entitlements)



class LiveMacOSPlatformFallbackTests(unittest.TestCase):
    """
    Verifies that the real MacOSPlatform class instantiates safely and handles
    running on non-macOS test environments gracefully without crashing.
    """

    def test_platform_safe_instantiation(self) -> None:
        platform = MacOSPlatform()
        # On Windows host runner, ctypes dynamic libraries for CoreGraphics won't load,
        # so methods fall back to safe non-crashing defaults.
        session_type = platform.get_session_type()
        self.assertIsInstance(session_type, SessionType)

        idle = platform.get_idle_seconds()
        self.assertIsInstance(idle, float)
        self.assertGreaterEqual(idle, 0.0)

        app_info = platform.get_foreground_app()
        self.assertIsInstance(app_info, tuple)
        self.assertEqual(len(app_info), 3)

        perms_screen = platform.check_screen_recording_permission()
        self.assertIsInstance(perms_screen, PermissionStatus)

        perms_acc = platform.check_accessibility_permission()
        self.assertIsInstance(perms_acc, PermissionStatus)

        topology = platform.get_display_topology()
        self.assertIsInstance(topology, list)
        self.assertGreaterEqual(len(topology), 1)
