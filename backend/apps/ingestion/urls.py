"""Ingestion URL patterns."""
from django.urls import path, re_path
from apps.ingestion.views import AgentEventBatchIngestView, AgentHeartbeatView

urlpatterns = [
    re_path(r"^agent/heartbeat/?$", AgentHeartbeatView.as_view(), name="agent-heartbeat"),
    re_path(r"^agent/events/batch/?$", AgentEventBatchIngestView.as_view(), name="agent-events-batch"),
]
