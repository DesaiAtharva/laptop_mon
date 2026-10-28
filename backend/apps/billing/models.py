"""Billing, Subscription, Usage, and Webhook models strictly adhering to §7.2, §15.3, and E84."""
from __future__ import annotations

import uuid
from typing import Any, Optional
from django.db import models
from django.utils import timezone
from apps.common.models import BaseUUIDModel
from apps.tenancy.models import Tenant, TenantModel


class Plan(BaseUUIDModel):
    """SaaS pricing and feature tier plan (§15.3)."""

    name = models.CharField(max_length=128, unique=True)
    slug = models.SlugField(max_length=64, unique=True)
    seat_limit = models.PositiveIntegerField(
        default=10,
        help_text="Maximum allowed active monitored devices under this plan (E85).",
    )
    price_per_seat_cents = models.PositiveIntegerField(default=500)
    features = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "billing_plans"
        ordering = ["price_per_seat_cents"]

    def __str__(self) -> str:
        return f"{self.name} ({self.seat_limit} seats)"


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "Trialing"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past Due"
    CANCELED = "canceled", "Canceled"
    UNPAID = "unpaid", "Unpaid"


class Subscription(BaseUUIDModel):
    """Tenant subscription with verified server-side seat limits (§15.3, REQ-15-3)."""

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="subscription",
        db_index=True,
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=32,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
        db_index=True,
    )
    seat_count = models.PositiveIntegerField(
        default=10,
        help_text="Purchased seat capacity (REQ-15-3, E85).",
    )
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    external_customer_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    external_subscription_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    last_event_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of latest webhook processed, preventing out-of-order state regression (E84).",
    )

    class Meta:
        db_table = "billing_subscriptions"

    def __str__(self) -> str:
        return f"Subscription for {self.tenant.name} ({self.status}) - {self.seat_count} seats"

    @property
    def is_active_or_trialing(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)


class UsageRecord(TenantModel):
    """Historical billing usage snapshot (§15.3)."""

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="usage_records",
    )
    active_seats = models.PositiveIntegerField()
    active_devices = models.PositiveIntegerField()
    storage_bytes = models.BigIntegerField(default=0)
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "billing_usage_records"
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["tenant", "recorded_at"]),
        ]


class WebhookEvent(BaseUUIDModel):
    """Idempotent audit log of received billing webhooks (E84)."""

    event_id = models.CharField(max_length=128, unique=True, db_index=True)
    provider = models.CharField(max_length=64, default="stripe")
    event_type = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField()
    status = models.CharField(max_length=32, default="processed")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "billing_webhook_events"
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"Webhook {self.event_id} ({self.event_type}) - {self.status}"
