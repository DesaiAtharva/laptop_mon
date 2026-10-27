"""Serializers for support access."""
from rest_framework import serializers
from apps.support_access.models import SupportAccessGrant


class SupportAccessRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportAccessGrant
        fields = ["id", "tenant", "requester", "reason", "status", "expires_at", "created_at"]
        read_only_fields = ["id", "requester", "status", "expires_at", "created_at"]


class SupportAccessApproveSerializer(serializers.Serializer):
    duration_hours = serializers.IntegerField(min_value=1, max_value=8, default=4)
