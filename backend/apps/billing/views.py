"""Billing endpoints: overview, plans, and webhook ingestion (§15.3, E84)."""
from __future__ import annotations

import json
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.billing.serializers import PlanSerializer, SubscriptionSerializer
from apps.billing.services import process_billing_webhook
from apps.devices.models import Device, DeviceStatus
from apps.rbac.permissions import IsOrgAdmin


class PlanListView(APIView):
    """GET /api/billing/plans (§15.3)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request) -> Response:
        plans = Plan.objects.filter(is_active=True).order_by("price_per_seat_cents")
        return Response(PlanSerializer(plans, many=True).data, status=status.HTTP_200_OK)


class BillingOverviewView(APIView):
    """GET /api/billing/overview (§15.3, REQ-15-3)."""

    permission_classes = [IsOrgAdmin]

    def get(self, request: Request) -> Response:
        membership = getattr(request, "membership")
        tenant = membership.tenant

        sub = getattr(tenant, "subscription", None)
        if not sub:
            # Create default starter subscription if none exists
            default_plan, _ = Plan.objects.get_or_create(
                slug="starter",
                defaults={"name": "Starter Plan", "seat_limit": 10, "price_per_seat_cents": 500},
            )
            sub = Subscription.objects.create(
                tenant=tenant,
                plan=default_plan,
                seat_count=10,
                status=SubscriptionStatus.ACTIVE,
            )

        active_count = Device.objects.filter(tenant=tenant, status=DeviceStatus.ACTIVE).count()
        remaining = max(0, sub.seat_count - active_count)
        can_enroll = sub.is_active_or_trialing and remaining > 0

        return Response({
            "subscription": SubscriptionSerializer(sub).data,
            "active_device_count": active_count,
            "seat_limit": sub.seat_count,
            "remaining_seats": remaining,
            "can_enroll_more": can_enroll,
        }, status=status.HTTP_200_OK)


class BillingWebhookView(APIView):
    """POST /api/billing/webhook (E84).
    
    Verifies HMAC signature and processes billing event idempotently.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        raw_body = request.body
        sig_header = (
            request.headers.get("Stripe-Signature")
            or request.headers.get("X-Webhook-Signature")
            or ""
        )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return Response({"error": "Malformed JSON payload"}, status=status.HTTP_400_BAD_REQUEST)

        res = process_billing_webhook(
            payload=payload,
            raw_payload_bytes=raw_body,
            signature_header=sig_header,
        )

        return Response(res, status=status.HTTP_200_OK)
