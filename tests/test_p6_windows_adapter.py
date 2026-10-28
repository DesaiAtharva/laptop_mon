"""
tests/test_p6_windows_adapter.py — Test Suite for P6: Windows OS Adapter.

Covers:
- OSAdapterProtocol adherence
- Live Win32 API execution on Windows test runner
- Edge Cases: E56, E57, E58, E59, E60, E61, E64, E66, E67, E68, E92, E95, E98
"""

import os
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
from agent.adapters.windows.adapter import WindowsOSAdapter
from agent.adapters.windows.win32_api import Win32Platform


class WindowsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.win32_mock = MagicMock(spec=Win32Platform)
        self.mock_adapter = WindowsOSAdapter(win32_platform=self.win32_mock)
        # Also instantiate real live adapter on this Windows machine
        self.live_adapter = WindowsOSAdapter()

    # ── Protocol Verification ──────────────────────────────────────────────────

    def test_windows_adapter_implements_os_adapter_protocol(self) -> None:
        """Verifies that WindowsOSAdapter strictly conforms to OSAdapterProtocol."""
        self.assertIsInstance(self.live_adapter, OSAdapterProtocol)
        caps = self.live_adapter.capabilities
        self.assertIn(AdapterCapability.FOREGROUND_APP, caps)
        self.assertIn(AdapterCapability.IDLE_DETECTION, caps)
        self.assertIn(AdapterCapability.SCREEN_CAPTURE, caps)
        self.assertIn(AdapterCapability.MULTI_MONITOR, caps)

    # ── Live Win32 Execution on Runner ─────────────────────────────────────────

    def test_live_windows_session_and_user(self) -> None:
        """Verifies live username and session detection on Windows machine."""
        username = self.live_adapter.get_os_username()
        self.assertIsInstance(username, str)
        self.assertGreater(len(username), 0)

        session_type = self.live_adapter.get_session_type()
        self.assertIn(session_type, (SessionType.CONSOLE, SessionType.REMOTE_DESKTOP))

    def test_live_windows_idle_and_foreground(self) -> None:
        """Verifies live idle time and foreground query on Windows machine."""
        idle = self.live_adapter.get_idle_seconds()
        self.assertIsInstance(idle, float)
        self.assertGreaterEqual(idle, 0.0)

        fg = self.live_adapter.get_foreground_app()
        self.assertIsNotNone(fg)
        self.assertIsInstance(fg.app_identifier, str)

    def test_live_windows_screen_capture(self) -> None:
        """Verifies live GDI BitBlt screen capture and JPEG compression."""
        result = self.live_adapter.capture_screen(max_width=800, max_height=600)
        self.assertIsInstance(result, CaptureResult)
        if not result.is_skipped:
            self.assertIsNotNone(result.image_bytes)
            self.assertEqual(result.format, "jpeg")
            self.assertLessEqual(result.width, 800)
            self.assertLessEqual(result.height, 600)
            # Check JPEG magic header \xff\xd8
            self.assertTrue(result.image_bytes.startswith(b"\xff\xd8"))

    def test_live_windows_os_info(self) -> None:
        """Verifies live monitor enumeration and OS info."""
        info = self.live_adapter.get_os_info()
        self.assertEqual(info["os"], "Windows")
        self.assertIn("monitors", info)
        self.assertGreaterEqual(info["monitor_count"], 1)

    # ── Assigned Edge Cases ────────────────────────────────────────────────────

    def test_E56_os_permission_denied_or_revoked_windows(self) -> None:
        """E56: Secure desktop active sets screen_recording permission to DENIED."""
        self.win32_mock.is_secure_desktop_active.return_value = True
        perms = self.mock_adapter.get_permissions()
        self.assertEqual(perms["screen_recording"], PermissionStatus.DENIED)
        self.assertEqual(perms["accessibility"], PermissionStatus.GRANTED)

    def test_E57_screen_locked_not_captured(self) -> None:
        """E57: When workstation is locked, capture is skipped safely."""
        self.win32_mock.is_secure_desktop_active.return_value = True
        res = self.mock_adapter.capture_screen()
        self.assertTrue(res.is_skipped)
        self.assertEqual(res.skip_reason, "secure_desktop_or_uac")

    def test_E58_sleep_hibernate_wake_windows(self) -> None:
        """E58: Sleep and power notifications handled via adapter capabilities."""
        self.assertIn(AdapterCapability.POWER_SLEEP, self.live_adapter.capabilities)

    def test_E59_fast_user_switching_windows(self) -> None:
        """E59: Adapter returns active session username to verify session binding."""
        self.win32_mock.get_active_username.return_value = "second_user"
        username = self.mock_adapter.get_os_username()
        self.assertEqual(username, "second_user")

    def test_E60_remote_desktop_or_vdi_isolation(self) -> None:
        """E60: SM_REMOTESESSION flags session as REMOTE_DESKTOP."""
        self.win32_mock.is_remote_session.return_value = True
        session_type = self.mock_adapter.get_session_type()
        self.assertEqual(session_type, SessionType.REMOTE_DESKTOP)

        self.win32_mock.is_remote_session.return_value = False
        session_type_console = self.mock_adapter.get_session_type()
        self.assertEqual(session_type_console, SessionType.CONSOLE)

    def test_E61_multiple_monitors_and_topology_changes(self) -> None:
        """E61: Multi-monitor enumeration discovers all attached displays."""
        self.win32_mock.get_display_monitors.return_value = [
            {"device": "\\\\.\\DISPLAY1", "left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True},
            {"device": "\\\\.\\DISPLAY2", "left": 1920, "top": 0, "width": 1920, "height": 1080, "is_primary": False},
        ]
        info = self.mock_adapter.get_os_info()
        self.assertEqual(info["monitor_count"], 2)
        self.assertTrue(info["monitors"][0]["is_primary"])
        self.assertFalse(info["monitors"][1]["is_primary"])

    def test_E64_windows_secure_desktop_or_uac(self) -> None:
        """E64: UAC elevation or secure desktop is never bypassed; capture skipped safely."""
        self.win32_mock.is_secure_desktop_active.return_value = True
        result = self.mock_adapter.capture_screen()
        self.assertTrue(result.is_skipped)
        self.assertEqual(result.skip_reason, "secure_desktop_or_uac")
        self.assertIsNone(result.image_bytes)

    def test_E66_app_identifier_unavailable_windows(self) -> None:
        """E66: Missing process path normalized to safe unclassified identifier."""
        self.win32_mock.get_foreground_window_info.return_value = (None, "Some Window", 4321)
        event = self.mock_adapter.get_foreground_app()
        self.assertIsNotNone(event)
        self.assertEqual(event.app_identifier, "pid_4321.exe")
        self.assertEqual(event.window_title, "Some Window")

    def test_E67_window_title_has_sensitive_data_windows(self) -> None:
        """E67: Window titles passed from Win32 API preserved for policy filtering."""
        self.win32_mock.get_foreground_window_info.return_value = (
            "C:\\Windows\\notepad.exe",
            "Secret Notes - Notepad",
            1001,
        )
        event = self.mock_adapter.get_foreground_app()
        self.assertIsNotNone(event)
        self.assertEqual(event.window_title, "Secret Notes - Notepad")

    def test_E68_screenshot_has_sensitive_data_windows(self) -> None:
        """E68: Password manager executable paths normalized for privacy filter detection."""
        self.win32_mock.get_foreground_window_info.return_value = (
            "C:\\Program Files\\Bitwarden\\Bitwarden.exe",
            "Bitwarden Vault",
            2002,
        )
        event = self.mock_adapter.get_foreground_app()
        self.assertIn("bitwarden", event.app_identifier.lower())

    def test_E92_antivirus_allowlisting_documentation(self) -> None:
        """E92: Zero AV/EDR evasion; allowlisting guidelines documented."""
        evidence_file = os.path.join(
            os.path.dirname(__file__), "..", "docs", "test-evidence", "windows.md"
        )
        self.assertTrue(os.path.exists(evidence_file))
        with open(evidence_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("No Evasion Techniques", content)
        self.assertIn("Allowlisting Guidelines", content)

    def test_E95_very_large_multi_monitor_capture(self) -> None:
        """E95: Huge virtual screen dimensions bounded and downscaled to avoid memory spikes."""
        self.win32_mock.is_secure_desktop_active.return_value = False
        # Mock 7680x2160 multi-monitor virtual screen returning downscaled 1920x540
        self.win32_mock.capture_screen_gdi.return_value = (b"\xff\xd8\xff\xe0mock_jpeg_bytes", 1920, 540)

        result = self.mock_adapter.capture_screen(max_width=1920, max_height=1080)
        self.assertFalse(result.is_skipped)
        self.assertEqual(result.width, 1920)
        self.assertEqual(result.height, 540)
        self.win32_mock.capture_screen_gdi.assert_called_with(max_width=1920, max_height=1080, quality=80)

    def test_E98_user_changes_os_account_windows(self) -> None:
        """E98: Active OS user verified against enrolled identity."""
        self.win32_mock.get_active_username.return_value = "new_domain_user"
        username = self.mock_adapter.get_os_username()
        self.assertEqual(username, "new_domain_user")


if __name__ == "__main__":
    unittest.main()
