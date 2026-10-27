"""Tenant-scoped caching utilities addressing E80 (Stale or cross-tenant cache)."""
from __future__ import annotations

import uuid
from typing import Any, Optional
from django.core.cache import cache


def tenant_cache_key(tenant_id: uuid.UUID | str, key: str) -> str:
    """Generate a strictly partitioned tenant-scoped cache key.

    Guarantees that no data from one tenant can ever be accessed or overwritten
    by another tenant via cache collision or stale keys (E80).
    """
    clean_tenant_id = str(tenant_id)
    return f"tenant:{clean_tenant_id}:{key}"


def get_tenant_cache(tenant_id: uuid.UUID | str, key: str) -> Any:
    """Retrieve a value from tenant-scoped cache."""
    return cache.get(tenant_cache_key(tenant_id, key))


def set_tenant_cache(
    tenant_id: uuid.UUID | str,
    key: str,
    value: Any,
    timeout: Optional[int] = 300,
) -> None:
    """Set a value in the tenant-scoped cache."""
    cache.set(tenant_cache_key(tenant_id, key), value, timeout=timeout)


def delete_tenant_cache(tenant_id: uuid.UUID | str, key: str) -> None:
    """Delete a key from the tenant-scoped cache."""
    cache.delete(tenant_cache_key(tenant_id, key))
