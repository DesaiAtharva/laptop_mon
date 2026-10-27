"""Ingestion URL patterns."""
from django.urls import path
from apps.ingestion.views import AgentEventBatchIngestView, AgentHeartbeatView

urlpatterns = [
    path("agent/heartbeat", AgentHeartbeatView.as_view(), name="agent-heartbeat"),
    path("agent/events/batch", AgentEventBatchIngestView.as_view(), name="agent-events-batch"),
]
