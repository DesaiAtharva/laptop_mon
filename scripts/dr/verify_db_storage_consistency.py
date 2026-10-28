#!/usr/bin/env python3
"""Database-to-Object-Storage consistency audit script (§15, E86, E87)."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

# Setup Django environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.testing")

import django
django.setup()

from apps.screenshots.models import Screenshot, ScreenshotStatus
from apps.screenshots.storage import get_storage_backend


def verify_db_storage_consistency(tenant_id: str | None = None) -> Dict[str, Any]:
    """Audits consistency between MySQL Screenshot records and Object Storage blobs (E86, E87).
    
    Identifies:
    - Missing objects (record exists as finalized, but blob missing from storage).
    - Unverified records (pending/failed uploads).
    - Consistency percentage.
    """
    storage = get_storage_backend()
    qs = Screenshot.objects.all()
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    total_records = qs.count()
    finalized_count = 0
    missing_blobs: List[str] = []
    verified_blobs: List[str] = []

    for screenshot in qs.iterator():
        if screenshot.status == ScreenshotStatus.FINALIZED:
            finalized_count += 1
            if screenshot.object_key:
                try:
                    exists = storage.object_exists(screenshot.object_key)
                    if exists:
                        verified_blobs.append(screenshot.object_key)
                    else:
                        missing_blobs.append(f"{screenshot.id} (key: {screenshot.object_key})")
                except Exception as exc:
                    missing_blobs.append(f"{screenshot.id} (error: {exc})")

    consistency_rate = (
        100.0 if finalized_count == 0 else (len(verified_blobs) / finalized_count) * 100.0
    )

    report = {
        "total_records": total_records,
        "finalized_count": finalized_count,
        "verified_blobs": len(verified_blobs),
        "missing_blobs_count": len(missing_blobs),
        "missing_blobs": missing_blobs,
        "consistency_percentage": round(consistency_rate, 2),
        "status": "consistent" if len(missing_blobs) == 0 else "inconsistent",
    }

    print(f"--- DB & Storage Consistency Audit ---")
    print(f"Total Screenshots: {total_records}")
    print(f"Finalized: {finalized_count}")
    print(f"Verified Objects: {len(verified_blobs)}")
    print(f"Missing Blobs: {len(missing_blobs)}")
    print(f"Consistency: {report['consistency_percentage']}%")
    print(f"Overall Status: {report['status'].upper()}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify MySQL and Object Storage consistency")
    parser.add_argument("--tenant-id", type=str, default=None, help="Filter by specific tenant UUID")
    args = parser.parse_args()

    result = verify_db_storage_consistency(args.tenant_id)
    sys.exit(0 if result["status"] == "consistent" else 1)
