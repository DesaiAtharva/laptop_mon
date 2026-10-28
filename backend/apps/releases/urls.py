from django.urls import path

from apps.releases.views import AdminReleaseListCreateView, AgentReleaseLatestView

urlpatterns = [
    path("agent/releases/latest/", AgentReleaseLatestView.as_view(), name="agent-releases-latest"),
    path("releases/", AdminReleaseListCreateView.as_view(), name="admin-releases-list-create"),
]
