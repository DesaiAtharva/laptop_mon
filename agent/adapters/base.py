"""
agent/adapters/base.py — Adapter Interface and Capability Protocol.

Authoritative protocol for per-OS desktop adapters (Windows, macOS, Linux, fake).
Core code (agent/core/*) MUST NEVER import OS-specific modules. It interacts
with the OS solely through this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Protocol, Set


class AdapterCapability(Enum):
    FOREGROUND_APP = auto()
    IDLE_DETECTION = auto()
    SESSION_LOCK = auto()
    POWER_SLEEP = auto()
    SCREEN_CAPTURE = auto()
    PERMISSION_STATUS = auto()
    MULTI_MONITOR = auto()


class SessionType(Enum):
    CONSOLE = "console"
    REMOTE_DESKTOP = "remote_desktop"
    HEADLESS = "headless"
    UNKNOWN = "unknown"


class PowerEventType(Enum):
    SLEEP = "sleep"
    WAKE = "wake"
    DISPLAY_OFF = "display_off"
    DISPLAY_ON = "display_on"


class SessionEventType(Enum):
    LOCK = "lock"
    UNLOCK = "unlock"
    LOGON = "logon"
    LOGOFF = "logoff"
    USER_SWITCH = "user_switch"


class PermissionStatus(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    PROMPT_NEEDED = "prompt_needed"
    NOT_SUPPORTED = "not_supported"


@dataclass(frozen=True)
class ForegroundAppEvent:
    timestamp: str  # ISO-8601 UTC string
    app_identifier: str  # e.g. process image path or bundle ID
    window_title: Optional[str] = None
    process_id: Optional[int] = None


@dataclass(frozen=True)
class PowerEvent:
    timestamp: str
    event_type: PowerEventType
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionEvent:
    timestamp: str
    event_type: SessionEventType
    os_username: Optional[str] = None
    session_id: Optional[str] = None


@dataclass(frozen=True)
class CaptureResult:
    image_bytes: Optional[bytes] = None
    format: str = "jpeg"
    width: int = 0
    height: int = 0
    is_skipped: bool = False
    skip_reason: Optional[str] = None  # Internal diagnostic only; redacted before upload


class OSAdapterProtocol(Protocol):
    """
    Protocol that every platform adapter (Windows, macOS, Linux, fake) must implement.
    Core code relies exclusively on these methods.
    """

    @property
    def capabilities(self) -> Set[AdapterCapability]:
        """Returns the set of capabilities supported by this adapter."""
        ...

    def get_session_type(self) -> SessionType:
        """Returns the current interactive session type (console, RDP, headless)."""
        ...

    def get_os_username(self) -> str:
        """Returns the currently active OS username."""
        ...

    def get_foreground_app(self) -> Optional[ForegroundAppEvent]:
        """Returns the currently focused foreground window application, if available."""
        ...

    def get_idle_seconds(self) -> float:
        """Returns seconds since last user input (keyboard/mouse)."""
        ...

    def capture_screen(
        self,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: int = 80,
    ) -> CaptureResult:
        """Captures primary/active screens, compressed as JPEG or WebP."""
        ...

    def get_permissions(self) -> Dict[str, PermissionStatus]:
        """Returns permission status for each sensitive capability (screen recording, accessibility)."""
        ...

    def is_battery_saver(self) -> bool:
        """Returns True if the system is on battery saver or low power mode."""
        ...

    def get_os_info(self) -> Dict[str, Any]:
        """Returns operating system name, version, architecture, and display topology."""
        ...
