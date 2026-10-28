"""Storage planning and capacity calculation helper strictly adhering to §10.3."""
from __future__ import annotations

from typing import Any, Dict


def calculate_screenshot_storage_capacity(
    work_hours: float = 8.0,
    screenshot_interval_seconds: int = 300,
    avg_compressed_screenshot_bytes: int = 150_000,
    device_count: int = 1,
    retention_days: int = 30,
) -> Dict[str, Any]:
    """Computes storage requirements using the §10.3 capacity formula:
    
    bytes_per_device_per_day = (
      (work_hours * 3600 / screenshot_interval_seconds)
      * avg_compressed_screenshot_bytes
    )
    """
    if screenshot_interval_seconds <= 0:
        raise ValueError("Screenshot interval seconds must be positive (> 0).")

    screenshots_per_device_per_day = (work_hours * 3600.0) / float(screenshot_interval_seconds)
    bytes_per_device_per_day = screenshots_per_device_per_day * float(avg_compressed_screenshot_bytes)
    mb_per_device_per_day = bytes_per_device_per_day / (1024.0 * 1024.0)

    total_bytes_per_day = bytes_per_device_per_day * float(device_count)
    total_gb_per_month = (total_bytes_per_day * 30.0) / (1024.0 * 1024.0 * 1024.0)
    retention_horizon_gb = (total_bytes_per_day * float(retention_days)) / (1024.0 * 1024.0 * 1024.0)

    return {
        "screenshots_per_device_per_day": round(screenshots_per_device_per_day, 1),
        "bytes_per_device_per_day": int(bytes_per_device_per_day),
        "mb_per_device_per_day": round(mb_per_device_per_day, 2),
        "device_count": device_count,
        "total_gb_per_month": round(total_gb_per_month, 2),
        "retention_horizon_gb": round(retention_horizon_gb, 2),
    }
