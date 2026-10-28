"""
agent/core/privacy_filter.py — Privacy Exclusion & Sensitive Data Redaction.

Adheres to:
- REQ-1-8: Never capture keylogging, passwords, or scrape private messages.
- E67: Window title has sensitive data -> redacted by default or suppressed completely.
- E68: Screenshot has sensitive data / password manager active -> capture skipped.
- §10.1: Skipped capture records ONLY that it was skipped, not reasons or contents.
- Filter and redact BEFORE durable storage.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from agent.core.policy import PolicyManager

# Known password managers and sensitive apps to always skip before capture (E68)
SENSITIVE_APP_PATTERNS = [
    r"1password",
    r"bitwarden",
    r"keepass",
    r"lastpass",
    r"dashlane",
    r"authenticator",
    r"keychain",
    r"kdbx",
    r"credentialmanager",
]

# Regex patterns for sensitive content in window titles (E67, E88)
REDACTION_PATTERNS = [
    # Credit card-like sequences (13-16 digits)
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED-CARD]"),
    # Bearer tokens or API keys
    (re.compile(r"(?i)\b(bearer|token|apikey|secret|password|passwd|auth)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    # JWT tokens
    (re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"), "[REDACTED-JWT]"),
    # Passwords or private keys
    (re.compile(r"(?i)BEGIN [A-Z ]*PRIVATE KEY"), "[REDACTED-KEY]"),
]


class PrivacyFilter:
    """
    Applies privacy exclusions and redactions before telemetry or screenshots are stored.
    """

    def __init__(self, policy_manager: PolicyManager) -> None:
        self.policy_manager = policy_manager

    def should_skip_screenshot(self, app_identifier: str, window_title: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Determines if screenshot must be skipped due to policy exclusion or password manager (E68).
        Returns (is_skipped, skip_marker).
        Note: The skip_marker stored in the record is generic (e.g. 'skipped_by_privacy_filter')
        to avoid leaking sensitive app names per §10.1.
        """
        app_lower = app_identifier.lower()

        # 1. Check password manager / credential vault patterns
        for pattern in SENSITIVE_APP_PATTERNS:
            if re.search(pattern, app_lower):
                return True, "skipped_by_privacy_filter"

        # 2. Check window title for sensitive patterns if present
        if window_title:
            title_lower = window_title.lower()
            for pattern in SENSITIVE_APP_PATTERNS:
                if re.search(pattern, title_lower):
                    return True, "skipped_by_privacy_filter"

        # 3. Check policy exclusion rules
        if self.policy_manager.is_app_excluded(app_identifier):
            return True, "skipped_by_privacy_filter"

        return False, None

    def filter_window_title(self, window_title: Optional[str]) -> Optional[str]:
        """
        Applies window title collection policy and redaction (E67).
        - If policy disables window titles: returns None.
        - If policy enables: redacts sensitive strings before returning.
        """
        if not window_title:
            return None

        if not self.policy_manager.should_collect_window_titles():
            return None

        redacted = window_title
        for pattern, replacement in REDACTION_PATTERNS:
            redacted = pattern.sub(replacement, redacted)

        return redacted

    def redact_text(self, text: str) -> str:
        """General text redaction utility for logs and diagnostics (E88)."""
        redacted = text
        for pattern, replacement in REDACTION_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted
