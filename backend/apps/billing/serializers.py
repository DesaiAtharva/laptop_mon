from __future__ import annotations

from rest_framework import serializers
from apps.billing.models import Plan, Subscription, UsageRecord


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id",
            "name",
            "slug",
            "seat_limit",
            "price_per_seat_cents",
            "features",
            "is_active",
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    plan_id = serializers.UUIDField(write_only=True, required=False)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "plan_id",
            "status",
            "seat_count",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "external_customer_id",
            "external_subscription_id",
        ]


class BillingOverviewSerializer(serializers.Serializer):
    subscription = SubscriptionSerializer()
    active_device_count = serializers.IntegerField()
    remaining_seats = serializers.IntegerField()
    can_enroll_more = serializers.BooleanField()
