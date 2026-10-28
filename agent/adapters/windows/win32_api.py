"""
agent/adapters/windows/win32_api.py — Pure ctypes Win32 API Interop for Windows Adapter.

Adheres to:
- Pure Python ctypes standard library (no pywin32 dependency).
- Event-driven foreground app tracking via WinEvent hook or API query.
- Process image path normalization via QueryFullProcessImageNameW.
- Idle time detection via GetLastInputInfo.
- Remote Desktop (RDP/VDI) detection via GetSystemMetrics(SM_REMOTESESSION) (E60).
- Multi-monitor topology discovery via EnumDisplayMonitors (E61, E95).
- Secure desktop / UAC detection via OpenInputDesktop without bypass (E64).
- GDI-based screen capture with bounding & downscaling (E95).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Constants
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_REMOTESESSION = 0x1000

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
DESKTOP_SWITCHDESKTOP = 0x0100


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.UINT),
        ("dwTime", ctypes.wintypes.DWORD),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]


class Win32Platform:
    """
    Win32 API bindings wrapper.
    """

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.gdi32 = ctypes.windll.gdi32
        self.advapi32 = ctypes.windll.advapi32

    def get_foreground_window_info(self) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """
        Returns (app_image_path, window_title, pid) of the current foreground window.
        If process image cannot be resolved, returns None for image path (E66).
        """
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None, None, None

        # 1. Get window title
        length = self.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buf, length + 1)
        window_title = buf.value if length > 0 else None

        # 2. Get PID
        pid = ctypes.wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None, window_title, None

        # 3. Get Process Image Name
        h_proc = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h_proc:
            return None, window_title, pid.value

        try:
            path_buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.wintypes.DWORD(1024)
            success = self.kernel32.QueryFullProcessImageNameW(h_proc, 0, path_buf, ctypes.byref(size))
            if success:
                return path_buf.value, window_title, pid.value
            return None, window_title, pid.value
        finally:
            self.kernel32.CloseHandle(h_proc)

    def get_idle_seconds(self) -> float:
        """
        Calculates seconds since last input event using GetLastInputInfo and GetTickCount64.
        """
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not self.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0

        current_tick = self.kernel32.GetTickCount64()
        last_input_tick = lii.dwTime
        # dwTime is 32-bit millisecond count from system start
        # Use modulo difference or 64-bit reference
        diff_ms = (current_tick & 0xFFFFFFFF) - last_input_tick
        if diff_ms < 0:
            diff_ms += 0x100000000
        return max(0.0, float(diff_ms) / 1000.0)

    def get_active_username(self) -> str:
        """Returns the active Windows username."""
        buf = ctypes.create_unicode_buffer(256)
        size = ctypes.wintypes.DWORD(256)
        if self.advapi32.GetUserNameW(buf, ctypes.byref(size)):
            return buf.value
        return os.environ.get("USERNAME", "unknown")

    def is_remote_session(self) -> bool:
        """
        Returns True if running inside a Remote Desktop (RDP) or Terminal Services session (E60).
        """
        return bool(self.user32.GetSystemMetrics(SM_REMOTESESSION))

    def is_secure_desktop_active(self) -> bool:
        """
        Checks whether the input desktop is currently switched to a secure desktop,
        such as UAC prompt, lock screen, or winlogon (E64).
        If OpenInputDesktop fails, we are on a secure desktop that cannot be captured.
        """
        h_desk = self.user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not h_desk:
            return True
        self.user32.CloseDesktop(h_desk)
        return False

    def get_display_monitors(self) -> List[Dict[str, Any]]:
        """
        Enumerates all active display monitors with their bounds and primary flag (E61).
        """
        monitors: List[Dict[str, Any]] = []

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(RECT),
            ctypes.c_double,
        )

        def callback(h_monitor, _hdc_monitor, _lprc_monitor, _dw_data):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if self.user32.GetMonitorInfoW(h_monitor, ctypes.byref(info)):
                rect = info.rcMonitor
                is_primary = bool(info.dwFlags & 1)
                monitors.append({
                    "device": info.szDevice,
                    "left": rect.left,
                    "top": rect.top,
                    "right": rect.right,
                    "bottom": rect.bottom,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                    "is_primary": is_primary,
                })
            return 1

        self.user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(callback), 0)
        return monitors

    def capture_screen_gdi(
        self,
        max_width: int = 1920,
        max_height: int = 1080,
        quality: int = 80,
    ) -> Tuple[Optional[bytes], int, int]:
        """
        Captures screen via Win32 GDI BitBlt and converts to compressed JPEG.
        Bounds resolution and downscales gracefully to avoid memory bloat (E95).
        Returns (jpeg_bytes, width, height).
        """
        from PIL import Image

        # Get virtual screen metrics covering all monitors
        left = self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        # Fallback to primary screen if virtual screen returns 0
        if width <= 0 or height <= 0:
            left, top = 0, 0
            width = self.user32.GetSystemMetrics(SM_CXSCREEN)
            height = self.user32.GetSystemMetrics(SM_CYSCREEN)

        if width <= 0 or height <= 0:
            return None, 0, 0

        h_screen_dc = self.user32.GetDC(0)
        h_mem_dc = self.gdi32.CreateCompatibleDC(h_screen_dc)
        h_bitmap = self.gdi32.CreateCompatibleBitmap(h_screen_dc, width, height)
        h_old_bitmap = self.gdi32.SelectObject(h_mem_dc, h_bitmap)

        try:
            # Copy screen pixels into memory bitmap
            self.gdi32.BitBlt(h_mem_dc, 0, 0, width, height, h_screen_dc, left, top, SRCCOPY)

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # Top-down DIB
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB

            buffer_size = width * height * 4
            buffer = ctypes.create_string_buffer(buffer_size)

            lines = self.gdi32.GetDIBits(
                h_mem_dc, h_bitmap, 0, height, buffer, ctypes.byref(bmi), DIB_RGB_COLORS
            )
            if lines != height:
                return None, 0, 0

            # Convert BGRA to RGB via Pillow
            img = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")

            # Apply bounded downscaling if screen is very large (E95)
            orig_w, orig_h = img.size
            if orig_w > max_width or orig_h > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            final_w, final_h = img.size
            out_io = io.BytesIO()
            img.save(out_io, format="JPEG", quality=quality, optimize=True)
            return out_io.getvalue(), final_w, final_h

        finally:
            self.gdi32.SelectObject(h_mem_dc, h_old_bitmap)
            self.gdi32.DeleteObject(h_bitmap)
            self.gdi32.DeleteDC(h_mem_dc)
            self.user32.ReleaseDC(0, h_screen_dc)
