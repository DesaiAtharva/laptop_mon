"""Device serializers."""
from rest_framework import serializers
from apps.devices.models import Device, EnrollmentToken


class DeviceSerializer(serializers.ModelSerializer):
    membership_email = serializers.EmailField(source="membership.user.email", read_only=True, default=None)

    class Meta:
        model = Device
        fields = [
            "id",
            "tenant_id",
            "membership_id",
            "membership_email",
            "hostname",
            "os",
            "status",
            "agent_version",
            "hardware_id",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreateEnrollmentTokenSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField(required=False, allow_null=True)
    expires_hours = serializers.IntegerField(required=False, default=24, min_value=1, max_value=720)
    max_uses = serializers.IntegerField(required=False, default=1, min_value=1, max_value=100)


class AgentEnrollSerializer(serializers.Serializer):
    token = serializers.CharField(required=True)
    hostname = serializers.CharField(required=True, max_length=255)
    os = serializers.CharField(required=True, max_length=64)
    agent_version = serializers.CharField(required=True, max_length=64)
    hardware_id = serializers.CharField(required=False, allow_blank=True, default="")


class DeviceReassignSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField(required=True)
