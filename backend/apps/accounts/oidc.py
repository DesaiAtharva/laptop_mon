"""OIDC state and nonce validation service."""
from __future__ import annotations

import secrets
from typing import Any, Dict, Optional
from django.core.cache import cache


def generate_oidc_flow_params() -> Dict[str, str]:
    """Generate state and nonce parameters for initiating an OIDC flow.

    Stores them with short expiry (10 minutes) for callback validation.
    """
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    cache.set(f"oidc_flow:{state}", nonce, timeout=600)
    return {"state": state, "nonce": nonce}


def validate_oidc_state_and_nonce(state: str, nonce: str) -> bool:
    """Validate that the state and nonce match an initiated, unexpired flow.

    Consumes the state upon validation to prevent replay attacks.
    """
    if not state or not nonce:
        return False

    cache_key = f"oidc_flow:{state}"
    expected_nonce = cache.get(cache_key)
    if expected_nonce is None:
        return False

    # Consume token
    cache.delete(cache_key)
    return secrets.compare_digest(expected_nonce, nonce)
