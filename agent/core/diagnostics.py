"""
agent/core/diagnostics.py — Redacted Diagnostics, Support Bundles, Heartbeats & Network Probes.

Adheres to:
- E88: Redacted logging & crash dumps (no secrets, tokens, or passwords leaked).
- REQ-12-1 & §12.1: Heartbeat payload containing all required agent health signals:
  agent_version, queue_depth, oldest_pending_age, permission_state, last_sync_at, crash_free_session.
- E04: Captive portal and DNS failure detection.
- E05: Proxy and VPN connectivity diagnostics.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.adapters.base import PermissionStatus
from agent.core.privacy_filter import REDACTION_PATTERNS

AGENT_VERSION = "1.0.0"


class RedactingFormatter(logging.Formatter):
    """
    Logging formatter that scrubs secrets, credentials, tokens, and credit cards (E88).
    """

    def format(self, record: logging.LogRecord) -> str:
        orig = super().format(record)
        redacted = orig
        for pattern, replacement in REDACTION_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted


def setup_agent_logger(log_file_path: Optional[str] = None) -> logging.Logger:
    """Configures structured redacting logger for the agent."""
    logger = logging.getLogger("agent")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = RedactingFormatter(
        '{"time":"%(asctime)s", "level":"%(levelname)s", "name":"%(name)s", "msg":"%(message)s"}'
    )

    if not logger.handlers:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        logger.addHandler(console)

        if log_file_path:
            import os
            os.makedirs(os.path.dirname(os.path.abspath(log_file_path)), exist_ok=True)
            file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger


class NetworkDiagnostics:
    """
    Probes network connectivity, captive portals, and proxy/VPN configurations (E04, E05).
    """

    @staticmethod
    def check_dns(hostname: str = "api.company.local") -> bool:
        """Tests DNS resolution without crashing (E04)."""
        try:
            socket.gethostbyname(hostname)
            return True
        except socket.gaierror:
            return False

    @staticmethod
    def probe_connectivity(endpoint_url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Probes endpoint to detect captive portal, proxy issues, or connection failures (E04, E05).
        """
        results: Dict[str, Any] = {
            "dns_ok": False,
            "connected": False,
            "is_captive_portal": False,
            "proxy_detected": False,
            "status_code": None,
            "error": None,
        }

        # Check proxy env
        import os
        if os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY"):
            results["proxy_detected"] = True

        try:
            req = urllib.request.Request(
                endpoint_url,
                headers={"User-Agent": f"LaptopMonAgent/{AGENT_VERSION}"},
            )
            # Do not follow redirects silently if testing for captive portals
            with urllib.request.urlopen(req, timeout=timeout) as response:
                results["dns_ok"] = True
                results["connected"] = True
                results["status_code"] = response.getcode()
                # If redirected to a login page or response has unexpected title
                final_url = response.geturl()
                if final_url != endpoint_url and "captive" in final_url.lower():
                    results["is_captive_portal"] = True
        except urllib.error.HTTPError as ex:
            results["dns_ok"] = True
            results["status_code"] = ex.code
            results["error"] = str(ex)
        except urllib.error.URLError as ex:
            results["error"] = str(ex.reason)
            if isinstance(ex.reason, socket.gaierror):
                results["dns_ok"] = False
        except Exception as ex:
            results["error"] = str(ex)

        return results


class DiagnosticsCollector:
    """
    Builds telemetry heartbeats and user-visible support bundles.
    """

    def __init__(
        self,
        agent_version: str = AGENT_VERSION,
    ) -> None:
        self.agent_version = agent_version

    def build_heartbeat_payload(
        self,
        queue_depth: int,
        oldest_pending_age_seconds: float,
        permissions: Dict[str, PermissionStatus],
        last_sync_at: Optional[str] = None,
        crash_free_sessions: int = 1,
    ) -> Dict[str, Any]:
        """
        Constructs heartbeat dictionary adhering strictly to §12.1.
        """
        perm_dict = {
            k: v.value if isinstance(v, PermissionStatus) else str(v)
            for k, v in permissions.items()
        }
        return {
            "agent_version": self.agent_version,
            "queue_depth": queue_depth,
            "oldest_pending_age_seconds": round(oldest_pending_age_seconds, 2),
            "permission_state": perm_dict,
            "last_sync_at": last_sync_at,
            "crash_free_sessions": crash_free_sessions,
            "reported_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_support_bundle(
        self,
        status_info: Dict[str, Any],
        os_info: Dict[str, Any],
        recent_logs: List[str],
    ) -> Dict[str, Any]:
        """
        Builds a safe, redacted support bundle for employee / IT diagnostics (E88).
        """
        # Redact logs
        redacted_logs = []
        for line in recent_logs:
            redacted = line
            for pattern, replacement in REDACTION_PATTERNS:
                redacted = pattern.sub(replacement, redacted)
            redacted_logs.append(redacted)

        return {
            "agent_version": self.agent_version,
            "bundle_generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status_info,
            "os_info": os_info,
            "logs": redacted_logs,
        }
