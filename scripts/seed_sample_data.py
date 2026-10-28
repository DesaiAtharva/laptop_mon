"""Seed rich initial sample data into laptop_mon MySQL database."""
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

# Ensure repo root and backend are on path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
os.environ.setdefault("USE_MYSQL", "true")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PASSWORD", "root")
os.environ.setdefault("MYSQL_DATABASE", "laptop_mon")

import django
django.setup()

from apps.accounts.models import User
from apps.tenancy.models import Tenant, Membership, MembershipRole, TenantStatus
from apps.policies.models import MonitoringPolicy
from apps.devices.models import Device, DeviceStatus
from apps.analytics.models import DailyMetrics
from apps.billing.models import Plan, Subscription, SubscriptionStatus

def seed():
    print("Seeding sample data into MySQL database 'laptop_mon'...")

    # 1. Tenant
    tenant, _ = Tenant.objects.get_or_create(
        name="Acme Corporation",
        defaults={
            "status": TenantStatus.ACTIVE,
        }
    )
    print(f"Tenant: {tenant.name} ({tenant.id})")

    # 2. Users & Memberships
    users_data = [
        ("admin@acme.com", "Alice Admin", MembershipRole.ADMIN),
        ("manager@acme.com", "Bob Manager", MembershipRole.MANAGER),
        ("employee@acme.com", "Charlie Employee", MembershipRole.EMPLOYEE),
    ]

    users = {}
    for email, name, role in users_data:
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={
                "name": name,
                "is_active": True,
                "is_staff": role == MembershipRole.ADMIN,
                "is_superuser": role == MembershipRole.ADMIN,
            }
        )
        user.set_password("password123")
        user.save()
        users[role] = user

        Membership.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults={
                "role": role,
                "has_screenshot_permission": True,
            }
        )
        print(f"User: {name} ({email}) - Role: {role} (password: password123)")

    # 3. Billing Plan & Subscription
    plan, _ = Plan.objects.get_or_create(
        slug="enterprise-tier",
        defaults={
            "name": "Enterprise Plan",
            "seat_limit": 100,
            "price_per_seat_cents": 1500,
            "is_active": True,
        }
    )
    now = datetime.now(timezone.utc)
    Subscription.objects.get_or_create(
        tenant=tenant,
        defaults={
            "plan": plan,
            "status": SubscriptionStatus.ACTIVE,
            "seat_count": 25,
            "current_period_start": now - timedelta(days=10),
            "current_period_end": now + timedelta(days=20),
        }
    )
    print("Billing subscription configured (25 seats active).")

    # 4. Monitoring Policy
    policy, _ = MonitoringPolicy.objects.get_or_create(
        tenant=tenant,
        version=1,
        defaults={
            "valid_until": now + timedelta(days=365),
            "screenshot_interval_seconds": 300,
            "idle_threshold_seconds": 180,
            "retention_days": 30,
            "window_title_collection": True,
        }
    )
    print(f"Monitoring Policy: v{policy.version} for {tenant.name}")

    # 5. Device
    device, _ = Device.objects.get_or_create(
        tenant=tenant,
        membership=Membership.objects.get(tenant=tenant, user=users[MembershipRole.EMPLOYEE]),
        hostname="WORK-LAPTOP-01",
        defaults={
            "os": "Windows 11 Pro 23H2",
            "status": DeviceStatus.ACTIVE,
            "agent_version": "1.0.0",
            "hardware_id": "HW-WIN-DELL-7420-XYZ",
            "last_seen_at": now,
        }
    )
    print(f"Enrolled Device: {device.hostname} (Status: {device.status})")

    # 6. Sample Daily Metrics
    today = now.date()
    DailyMetrics.objects.get_or_create(
        tenant=tenant,
        device=device,
        local_date=today,
        calc_version=1,
        defaults={
            "observed_session_seconds": 28800.0, # 8 hours
            "active_seconds": 21600.0,           # 6 hours
            "idle_seconds": 3600.0,              # 1 hour
            "productive_seconds": 18000.0,       # 5 hours
            "neutral_seconds": 2400.0,
            "distracting_seconds": 1200.0,
            "productive_share": 0.833,           # 83.3%
            "monitoring_coverage": 1.0,
        }
    )
    print(f"Sample Daily Metrics generated for {today} (Productivity Share: 83.3%).")
    print("\nAll sample data successfully committed to MySQL!")

if __name__ == "__main__":
    seed()
