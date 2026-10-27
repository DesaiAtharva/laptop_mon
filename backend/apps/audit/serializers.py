"""Audit log serializers."""
from rest_framework import serializers
from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "tenant_id",
            "actor_id",
            "actor_email",
            "action",
            "resource_type",
            "resource_id",
            "metadata",
            "request_id",
            "created_at",
        ]
        read_only_fields = fields
