"""Serializers for Reports and Exports API (§8.4)."""
from __future__ import annotations

from rest_framework import serializers
from apps.analytics.models import AppUsageInterval, DailyMetrics, DataExport, Dispute, ExportType


class DailyMetricsSerializer(serializers.ModelSerializer):
    """Serialized daily productivity metrics (§8.4, §9.2)."""

    device_id = serializers.UUIDField(source="device.id", read_only=True)
    device_hostname = serializers.CharField(source="device.hostname", read_only=True)

    class Meta:
        model = DailyMetrics
        fields = [
            "device_id",
            "device_hostname",
            "local_date",
            "calc_version",
            "observed_session_seconds",
            "active_seconds",
            "idle_seconds",
            "productive_seconds",
            "neutral_seconds",
            "distracting_seconds",
            "productive_share",
            "monitoring_coverage",
            "sync_lag_seconds",
            "crash_free_sessions",
            "data_freshness_at",
        ]
        read_only_fields = fields


class AppUsageIntervalSerializer(serializers.ModelSerializer):
    """Serialized usage interval (§7.2, §8.4)."""

    device_id = serializers.UUIDField(source="device.id", read_only=True)

    class Meta:
        model = AppUsageInterval
        fields = [
            "id",
            "device_id",
            "app_identifier",
            "app_classification",
            "app_classification_version",
            "started_at",
            "ended_at",
            "duration_seconds",
            "state",
            "calc_version",
            "is_inferred",
        ]
        read_only_fields = fields


class AppUsageSummarySerializer(serializers.Serializer):
    """Aggregated app usage summary."""

    app_identifier = serializers.CharField()
    app_classification = serializers.CharField()
    total_seconds = serializers.FloatField()
    percentage_of_active = serializers.FloatField()


class ExportRequestSerializer(serializers.Serializer):
    """Payload for POST /api/exports (§8.4)."""

    export_type = serializers.ChoiceField(choices=ExportType.choices, default=ExportType.DAILY_METRICS)
    filters = serializers.DictField(required=False, default=dict)


class DataExportSerializer(serializers.ModelSerializer):
    """Serialized data export status and metadata (§8.4)."""

    class Meta:
        model = DataExport
        fields = [
            "id",
            "status",
            "export_type",
            "row_count",
            "download_url",
            "error_message",
            "expires_at",
            "created_at",
        ]
        read_only_fields = fields


class DisputeSerializer(serializers.ModelSerializer):
    """Serialized dispute object (§11.3, E89)."""

    employee_name = serializers.CharField(source="membership.user.name", read_only=True)
    employee_email = serializers.CharField(source="membership.user.email", read_only=True)
    reviewed_by_name = serializers.CharField(source="reviewed_by.name", read_only=True)

    class Meta:
        model = Dispute
        fields = [
            "id",
            "membership_id",
            "employee_name",
            "employee_email",
            "interval_id",
            "target_app",
            "target_date",
            "reason",
            "desired_classification",
            "status",
            "resolution_notes",
            "reviewed_by_name",
            "resolved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "membership_id",
            "employee_name",
            "employee_email",
            "reviewed_by_name",
            "resolved_at",
            "created_at",
            "updated_at",
        ]


class DisputeCreateSerializer(serializers.ModelSerializer):
    """Payload for submitting a dispute (E89)."""

    class Meta:
        model = Dispute
        fields = [
            "interval",
            "target_app",
            "target_date",
            "reason",
            "desired_classification",
        ]
