"""Structured JSON logging and secret redaction filter adhering strictly to §3.2, §11.4, and E88."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Pattern

# Regular expressions for identifying sensitive secrets
SECRET_PATTERNS: List[Pattern[str]] = [
    # Bearer tokens & Authorization headers
    re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{12,}", re.IGNORECASE),
    re.compile(r"(?i)(authorization['\":\s=]+bearer\s+)[^\s'\",]+", re.IGNORECASE),
    # Common password fields in query strings or JSON
    re.compile(r"(?i)(password['\":\s=]+)[^\s'\",&]{3,}", re.IGNORECASE),
    re.compile(r"(?i)(secret['\":\s=]+)[^\s'\",&]{6,}", re.IGNORECASE),
    re.compile(r"(?i)(client_secret['\":\s=]+)[^\s'\",&]{6,}", re.IGNORECASE),
    # API keys / Webhook secrets / Stripe keys
    re.compile(r"(?i)(api[_-]?key['\":\s=]+)[a-zA-Z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"whsec_[a-zA-Z0-9_]{16,}", re.IGNORECASE),
    re.compile(r"sk_live_[a-zA-Z0-9_]{16,}", re.IGNORECASE),
    re.compile(r"sk_test_[a-zA-Z0-9_]{16,}", re.IGNORECASE),
    # S3 / MinIO access keys and presigned query signatures
    re.compile(r"(?i)(X-Amz-Signature=)[0-9a-fA-F]{16,}", re.IGNORECASE),
    re.compile(r"(?i)(X-Amz-Credential=)[^&\s'\"]+", re.IGNORECASE),
    re.compile(r"(?i)(Signature=)[0-9a-fA-F]{16,}", re.IGNORECASE),
    # Private SSH/RSA keys
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"),
]

REDACTED_SUBSTITUTE = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Scans and redacts sensitive tokens, credentials, and presigned parameters (E88)."""
    if not isinstance(text, str):
        text = str(text)

    cleaned = text
    for pattern in SECRET_PATTERNS:
        # If pattern has a capturing group for key prefix, preserve the prefix and redact only the secret
        if pattern.groups == 1:
            cleaned = pattern.sub(r"\1" + REDACTED_SUBSTITUTE, cleaned)
        else:
            cleaned = pattern.sub(REDACTED_SUBSTITUTE, cleaned)
    return cleaned


class SecretRedactingFilter(logging.Filter):
    """Logging filter that traverses log record attributes and masks secrets before output (E88)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        elif isinstance(record.msg, dict):
            record.msg = self._clean_dict(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = self._clean_dict(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    redact_secrets(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        return True

    def _clean_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for k, v in data.items():
            if any(term in k.lower() for term in ("password", "secret", "token", "authorization", "key")):
                cleaned[k] = REDACTED_SUBSTITUTE
            elif isinstance(v, str):
                cleaned[k] = redact_secrets(v)
            elif isinstance(v, dict):
                cleaned[k] = self._clean_dict(v)
            else:
                cleaned[k] = v
        return cleaned


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        # Ensure record message is formatted
        message = record.getMessage()
        # Double-check redaction on finalized message
        message = redact_secrets(message)

        log_data: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "line": record.lineno,
        }

        # Include correlation / request ID if present
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_data["request_id"] = request_id

        # Include tenant context if present
        tenant_id = getattr(record, "tenant_id", None)
        if tenant_id:
            log_data["tenant_id"] = str(tenant_id)

        # Include exception information if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)
