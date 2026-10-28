"""
agent/adapters/windows/adapter.py — Production Windows Adapter Implementation.

Implements OSAdapterProtocol adhering to:
- Spec §4.2 Windows capabilities & §10.1 screen capture rules.
- Pure ctypes Win32 API calls via win32_api.py (zero OS imports in core).
- E56: Permissions & capabilities exposure.
- E57: Lock screen not captured by default.
- E59 & E98: Interactive console session and user binding.
- E60: Remote Desktop (RDP / VDI) detection and isolation.
- E61 & E95: Multi-monitor topology discovery and bounded downscaled capture.
- E64: Secure Desktop / UAC detection (safe skip, never bypassed).
- E66: Missing process path normalized to safe unclassified identifier.
- E67 & E68: Coordinates with privacy filter before capture.
- E92: Documented signing and allowlisting (no AV/EDR evasion).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import platform
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from agent.adapters.base import (
    AdapterCapability,
    CaptureResult,
    ForegroundAppEvent,
    OSAdapterProtocol,
    PermissionStatus,
    SessionType,
)
from agent.adapters.windows.win32_api import Win32Platform

logger = logging.getLogger(__name__)


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.wintypes.DWORD),
        ("BatteryFullLifeTime", ctypes.wintypes.DWORD),
    ]


class WindowsOSAdapter:
    """
    Windows desktop OS adapter implementing OSAdapterProtocol.
    """

    def __init__(self, win32_platform: Optional[Win32Platform] = None) -> None:
        self.win32 = win32_platform or Win32Platform()
        self._capabilities: Set[AdapterCapability] = {
            AdapterCapability.FOREGROUND_APP,
            AdapterCapability.IDLE_DETECTION,
            AdapterCapability.SESSION_LOCK,
            AdapterCapability.POWER_SLEEP,
            AdapterCapability.SCREEN_CAPTURE,
            AdapterCapability.PERMISSION_STATUS,
            AdapterCapability.MULTI_MONITOR,
        }

    @property
    def capabilities(self) -> Set[AdapterCapability]:
        return set(self._capabilities)

    def get_session_type(self) -> SessionType:
        """
        Detects if current session is local console or remote desktop (E60).
        """
        try:
            if self.win32.is_remote_session():
                return SessionType.REMOTE_DESKTOP
            return SessionType.CONSOLE
        except Exception as ex:
            logger.warning(f"Error checking remote session: {ex}")
            return SessionType.UNKNOWN

    def get_os_username(self) -> str:
        """Returns the active Windows session username (E59, E98)."""
        return self.win32.get_active_username()

    def get_foreground_app(self) -> Optional[ForegroundAppEvent]:
        """
        Retrieves active foreground application via Win32 API.
        Normalizes executable path; handles missing identifiers cleanly (E66).
        """
        try:
            path, title, pid = self.win32.get_foreground_window_info()
            now_iso = datetime.now(timezone.utc).isoformat()

            # Normalize path or handle unavailable identifier (E66)
            if path:
                norm_app_id = os.path.normpath(path)
            elif pid:
                norm_app_id = f"pid_{pid}.exe"
            else:
                norm_app_id = "unknown_process.exe"

            return ForegroundAppEvent(
                timestamp=now_iso,
                app_identifier=norm_app_id,
                window_title=title,
                process_id=pid,
            )
        except Exception as ex:
            logger.error(f"Error querying foreground app: {ex}")
            return None

    def get_idle_seconds(self) -> float:
        """Retrieves user idle seconds via GetLastInputInfo."""
        try:
            return self.win32.get_idle_seconds()
        except Exception as ex:
            logger.error(f"Error querying idle seconds: {ex}")
            return 0.0

    def capture_screen(
        self,
        max_width: Optional[int] = 1920,
        max_height: Optional[int] = 1080,
        quality: int = 80,
    ) -> CaptureResult:
        """
        Captures the virtual screen across all monitors via GDI BitBlt.
        Adheres to:
        - E64: If secure desktop or UAC prompt is active, skips capture safely without bypass.
        - E57: Lock screen is not captured by default.
        - E95: Downscales very large multi-monitor resolutions to bound memory and file size.
        """
        # 1. Check secure desktop / UAC prompt / winlogon (E64)
        try:
            if self.win32.is_secure_desktop_active():
                return CaptureResult(
                    image_bytes=None,
                    format="jpeg",
                    is_skipped=True,
                    skip_reason="secure_desktop_or_uac",
                )
        except Exception as ex:
            logger.warning(f"Error checking secure desktop status: {ex}")

        # 2. Capture virtual screen
        try:
            bound_w = max_width or 1920
            bound_h = max_height or 1080
            jpeg_bytes, w, h = self.win32.capture_screen_gdi(
                max_width=bound_w,
                max_height=bound_h,
                quality=quality,
            )
            if not jpeg_bytes:
                return CaptureResult(
                    image_bytes=None,
                    format="jpeg",
                    is_skipped=True,
                    skip_reason="capture_failed",
                )

            return CaptureResult(
                image_bytes=jpeg_bytes,
                format="jpeg",
                width=w,
                height=h,
                is_skipped=False,
            )
        except Exception as ex:
            logger.error(f"Error capturing Windows screen: {ex}")
            return CaptureResult(
                image_bytes=None,
                format="jpeg",
                is_skipped=True,
                skip_reason=str(ex),
            )

    def get_permissions(self) -> Dict[str, PermissionStatus]:
        """
        Returns permission status for sensitive capabilities (E56).
        If secure desktop is active, screen recording is temporarily denied.
        """
        status: Dict[str, PermissionStatus] = {
            "screen_recording": PermissionStatus.GRANTED,
            "accessibility": PermissionStatus.GRANTED,
        }
        try:
            if self.win32.is_secure_desktop_active():
                status["screen_recording"] = PermissionStatus.DENIED
        except Exception:
            pass
        return status

    def is_battery_saver(self) -> bool:
        """
        Checks whether Windows Battery Saver mode is currently enabled (E96).
        """
        try:
            sps = SYSTEM_POWER_STATUS()
            if self.win32.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                # SystemStatusFlag == 1 indicates Battery Saver is active
                return bool(sps.SystemStatusFlag == 1)
            return False
        except Exception:
            return False

    def get_os_info(self) -> Dict[str, Any]:
        """
        Returns Windows system metadata, version, architecture, and monitor topology (E61).
        """
        monitors = []
        try:
            monitors = self.win32.get_display_monitors()
        except Exception as ex:
            logger.warning(f"Error enumerating monitors: {ex}")

        return {
            "os": "Windows",
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "monitors": monitors,
            "monitor_count": len(monitors),
            "is_remote_session": self.win32.is_remote_session(),
        }
