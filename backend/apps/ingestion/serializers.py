"""Serializers for agent heartbeat and event batch ingestion."""
from rest_framework import serializers


class AgentHeartbeatSerializer(serializers.Serializer):
    agent_version = serializers.CharField(required=True)
    queue_depth = serializers.IntegerField(required=False, default=0, min_value=0)
    oldest_pending_seconds = serializers.IntegerField(required=False, default=0, min_value=0)
    permission_state = serializers.JSONField(required=False, default=dict)
    active_window = serializers.CharField(required=False, allow_blank=True, default="")
    idle_seconds = serializers.IntegerField(required=False, default=0, min_value=0)


class SingleEventSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=True)
    event_type = serializers.CharField(required=True)
    occurred_at = serializers.DateTimeField(required=True)
    payload = serializers.JSONField(required=False, default=dict)


class EventBatchUploadSerializer(serializers.Serializer):
    agent_version = serializers.CharField(required=True)
    schema_version = serializers.IntegerField(required=False, default=1)
    events = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )
