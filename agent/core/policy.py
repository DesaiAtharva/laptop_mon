"""
agent/core/policy.py — Local Policy Manager, Cache & Offline Grace Enforcement.

Adheres to:
- REQ-5-1 & E01: Agent starts offline under a valid cached policy.
- E37: Offline policy expiration check against valid_until grace period.
  Fail closed on sensitive capture (screenshots pause) when policy expires or cannot be verified.
- E38: Server-side device revocation handling (hold, delete or export local data based on tenant policy).
- Exclusions, capture windows, and window-title collection settings.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PolicyRule:
    app_identifier: str
    classification: str  # productive, neutral, distracting, excluded


@dataclass
class EffectivePolicy:
    version: int
    valid_until: str  # ISO-8601 UTC
    screenshot_interval_seconds: int = 300
    idle_threshold_seconds: int = 300
    retention_days: int = 30
    window_title_collection: bool = False
    exclusion_rules: List[str] = field(default_factory=list)
    app_rules: List[PolicyRule] = field(default_factory=list)
    capture_windows: List[Dict[str, Any]] = field(default_factory=list)
    is_revoked: bool = False
    revocation_action: str = "hold"  # hold, delete, export


class PolicyManager:
    """
    Manages local caching and enforcement of monitoring policies.
    """

    def __init__(self, cache_file_path: str) -> None:
        self.cache_file_path = cache_file_path
        self._policy: Optional[EffectivePolicy] = None
        self.load_cached_policy()

    def load_cached_policy(self) -> Optional[EffectivePolicy]:
        """Loads policy from cache file if present."""
        if not os.path.exists(self.cache_file_path):
            return None
        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rules = [
                PolicyRule(app_identifier=r["app_identifier"], classification=r["classification"])
                for r in data.get("app_rules", [])
            ]
            self._policy = EffectivePolicy(
                version=data.get("version", 1),
                valid_until=data.get("valid_until", ""),
                screenshot_interval_seconds=data.get("screenshot_interval_seconds", 300),
                idle_threshold_seconds=data.get("idle_threshold_seconds", 300),
                retention_days=data.get("retention_days", 30),
                window_title_collection=data.get("window_title_collection", False),
                exclusion_rules=data.get("exclusion_rules", []),
                app_rules=rules,
                capture_windows=data.get("capture_windows", []),
                is_revoked=data.get("is_revoked", False),
                revocation_action=data.get("revocation_action", "hold"),
            )
            return self._policy
        except Exception as ex:
            logger.error(f"Error loading cached policy: {ex}")
            return None

    def update_policy(self, policy_data: Dict[str, Any]) -> EffectivePolicy:
        """Updates and persists newly received policy from server."""
        rules_raw = policy_data.get("app_rules", [])
        rules = [
            PolicyRule(app_identifier=r["app_identifier"], classification=r["classification"])
            for r in rules_raw
        ]
        policy = EffectivePolicy(
            version=policy_data.get("version", 1),
            valid_until=policy_data.get("valid_until", ""),
            screenshot_interval_seconds=policy_data.get("screenshot_interval_seconds", 300),
            idle_threshold_seconds=policy_data.get("idle_threshold_seconds", 300),
            retention_days=policy_data.get("retention_days", 30),
            window_title_collection=policy_data.get("window_title_collection", False),
            exclusion_rules=policy_data.get("exclusion_rules", []),
            app_rules=rules,
            capture_windows=policy_data.get("capture_windows", []),
            is_revoked=policy_data.get("is_revoked", False),
            revocation_action=policy_data.get("revocation_action", "hold"),
        )

        os.makedirs(os.path.dirname(os.path.abspath(self.cache_file_path)), exist_ok=True)
        # Write atomically via temp file
        tmp_path = f"{self.cache_file_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(policy_data, f, indent=2)
        os.replace(tmp_path, self.cache_file_path)

        self._policy = policy
        return policy

    def get_effective_policy(self) -> Optional[EffectivePolicy]:
        return self._policy

    def is_policy_valid(self, now: Optional[datetime] = None) -> bool:
        """
        Validates if current policy is active and within valid_until grace period (E37).
        """
        if self._policy is None:
            return False
        if self._policy.is_revoked:
            return False
        if not self._policy.valid_until:
            return True

        current_time = now or datetime.now(timezone.utc)
        try:
            valid_until_dt = datetime.fromisoformat(self._policy.valid_until.replace("Z", "+00:00"))
            return current_time <= valid_until_dt
        except Exception:
            return False

    def can_capture_screenshots(self, now: Optional[datetime] = None) -> bool:
        """
        Fails closed: screenshots disabled if policy is expired, revoked, or interval is 0 (E37, E38).
        """
        if not self.is_policy_valid(now):
            return False
        assert self._policy is not None
        return self._policy.screenshot_interval_seconds > 0

    def is_app_excluded(self, app_identifier: str) -> bool:
        """Returns True if the application is in exclusion list or classified as excluded."""
        if not self._policy:
            return False
        app_id_lower = app_identifier.lower()
        for excl in self._policy.exclusion_rules:
            if excl.lower() in app_id_lower:
                return True
        for rule in self._policy.app_rules:
            if rule.app_identifier.lower() in app_id_lower and rule.classification == "excluded":
                return True
        return False

    def should_collect_window_titles(self) -> bool:
        """Window titles off by default; only collected if policy explicitly enables them (§10.1)."""
        if not self.is_policy_valid():
            return False
        assert self._policy is not None
        return self._policy.window_title_collection

    def mark_revoked(self, action: str = "hold") -> None:
        """Records server-side device revocation (E38)."""
        if self._policy:
            self._policy.is_revoked = True
            self._policy.revocation_action = action
            data = {
                "version": self._policy.version,
                "valid_until": self._policy.valid_until,
                "screenshot_interval_seconds": 0,
                "idle_threshold_seconds": self._policy.idle_threshold_seconds,
                "retention_days": self._policy.retention_days,
                "window_title_collection": False,
                "exclusion_rules": self._policy.exclusion_rules,
                "app_rules": [{"app_identifier": r.app_identifier, "classification": r.classification} for r in self._policy.app_rules],
                "capture_windows": self._policy.capture_windows,
                "is_revoked": True,
                "revocation_action": action,
            }
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
