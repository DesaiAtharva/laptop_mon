"""Serializers for accounts and authentication."""
from rest_framework import serializers
from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "name", "mfa_enabled", "created_at"]
        read_only_fields = ["id", "created_at"]


class PasswordLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class OIDCCallbackSerializer(serializers.Serializer):
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=True)
    nonce = serializers.CharField(required=True)
    # Claims passed directly or simulated for tests
    email = serializers.EmailField(required=False)
    name = serializers.CharField(required=False, allow_blank=True, default="")
    mfa_authenticated = serializers.BooleanField(required=False, default=False)


class SessionRevokeSerializer(serializers.Serializer):
    all = serializers.BooleanField(required=False, default=False)
    target_user_id = serializers.UUIDField(required=False, allow_null=True, default=None)
