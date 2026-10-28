"""
agent/adapters/fake/fake_adapter.py — Scriptable Deterministic Fake OS Adapter.

Used for unit tests, offline tests, integration tests, and fault injection simulations.
Core code uses this without knowing it is a test adapter.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from agent.adapters.base import (
    AdapterCapability,
    CaptureResult,
    ForegroundAppEvent,
    OSAdapterProtocol,
    PermissionStatus,
    PowerEvent,
    PowerEventType,
    SessionEvent,
    SessionEventType,
    SessionType,
)


class FakeOSAdapter:
    """
    Scriptable in-memory OS adapter for tests.
    """

    def __init__(self) -> None:
        self._capabilities: Set[AdapterCapability] = {
            AdapterCapability.FOREGROUND_APP,
            AdapterCapability.IDLE_DETECTION,
            AdapterCapability.SESSION_LOCK,
            AdapterCapability.POWER_SLEEP,
            AdapterCapability.SCREEN_CAPTURE,
            AdapterCapability.PERMISSION_STATUS,
            AdapterCapability.MULTI_MONITOR,
        }
        self.session_type: SessionType = SessionType.CONSOLE
        self.os_username: str = "testuser"
        self.current_foreground_app: Optional[ForegroundAppEvent] = None
        self.idle_seconds: float = 0.0
        self.permissions: Dict[str, PermissionStatus] = {
            "screen_recording": PermissionStatus.GRANTED,
            "accessibility": PermissionStatus.GRANTED,
        }
        self.battery_saver: bool = False
        self.os_info: Dict[str, Any] = {
            "os": "FakeOS",
            "version": "1.0.0",
            "arch": "x86_64",
            "monitors": [{"id": 1, "width": 1920, "height": 1080, "primary": True}],
        }

        # Pre-canned screenshot response
        self.mock_capture_result: Optional[CaptureResult] = None
        self.capture_call_count: int = 0
        self.fail_capture: bool = False
        self.fail_capture_exception: Optional[Exception] = None

    @property
    def capabilities(self) -> Set[AdapterCapability]:
        return set(self._capabilities)

    def set_capabilities(self, caps: Set[AdapterCapability]) -> None:
        self._capabilities = set(caps)

    def get_session_type(self) -> SessionType:
        return self.session_type

    def get_os_username(self) -> str:
        return self.os_username

    def get_foreground_app(self) -> Optional[ForegroundAppEvent]:
        return self.current_foreground_app

    def set_foreground_app(
        self,
        app_identifier: str,
        window_title: Optional[str] = None,
        process_id: Optional[int] = 1234,
        timestamp: Optional[str] = None,
    ) -> ForegroundAppEvent:
        from datetime import datetime, timezone

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        event = ForegroundAppEvent(
            timestamp=ts,
            app_identifier=app_identifier,
            window_title=window_title,
            process_id=process_id,
        )
        self.current_foreground_app = event
        return event

    def get_idle_seconds(self) -> float:
        return self.idle_seconds

    def set_idle_seconds(self, seconds: float) -> None:
        self.idle_seconds = max(0.0, float(seconds))

    def capture_screen(
        self,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: int = 80,
    ) -> CaptureResult:
        self.capture_call_count += 1
        if self.fail_capture_exception:
            raise self.fail_capture_exception
        if self.fail_capture:
            return CaptureResult(
                image_bytes=None,
                format="jpeg",
                is_skipped=True,
                skip_reason="Simulated capture failure",
            )
        if self.mock_capture_result is not None:
            return self.mock_capture_result

        # Default synthetic 1x1 JPEG-like payload
        # Minimal JPEG header bytes for tests
        minimal_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\xff\xd9"
        return CaptureResult(
            image_bytes=minimal_jpeg,
            format="jpeg",
            width=max_width or 1920,
            height=max_height or 1080,
            is_skipped=False,
        )

    def get_permissions(self) -> Dict[str, PermissionStatus]:
        return dict(self.permissions)

    def set_permission(self, capability: str, status: PermissionStatus) -> None:
        self.permissions[capability] = status

    def is_battery_saver(self) -> bool:
        return self.battery_saver

    def set_battery_saver(self, enabled: bool) -> None:
        self.battery_saver = enabled

    def get_os_info(self) -> Dict[str, Any]:
        return dict(self.os_info)
