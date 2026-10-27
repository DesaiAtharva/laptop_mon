"""Policy serializers."""
from rest_framework import serializers
from apps.policies.models import AppRule, MonitoringPolicy


class AppRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppRule
        fields = ["id", "app_identifier", "classification", "version"]


class MonitoringPolicySerializer(serializers.ModelSerializer):
    signature = serializers.CharField(read_only=True)
    app_rules = AppRuleSerializer(many=True, read_only=True)

    class Meta:
        model = MonitoringPolicy
        fields = [
            "id",
            "version",
            "valid_until",
            "screenshot_interval_seconds",
            "idle_threshold_seconds",
            "retention_days",
            "capture_windows",
            "exclusion_rules",
            "window_title_collection",
            "min_agent_version",
            "max_agent_version",
            "effective_date",
            "signature",
            "app_rules",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_at", "updated_at", "signature"]


class PolicyUpdateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(required=True)
    screenshot_interval_seconds = serializers.IntegerField(required=False, min_value=15, max_value=3600)
    idle_threshold_seconds = serializers.IntegerField(required=False, min_value=30, max_value=1800)
    retention_days = serializers.IntegerField(required=False, min_value=1, max_value=365)
    window_title_collection = serializers.BooleanField(required=False)
    min_agent_version = serializers.CharField(required=False)
    max_agent_version = serializers.CharField(required=False)
    capture_windows = serializers.JSONField(required=False)
    exclusion_rules = serializers.JSONField(required=False)
