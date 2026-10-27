"""Policy URL patterns."""
from django.urls import path
from apps.policies.views import AgentPolicyView, PolicyDetailUpdateView, PolicyListView

urlpatterns = [
    path("agent/policy", AgentPolicyView.as_view(), name="agent-policy"),
    path("policies", PolicyListView.as_view(), name="policy-list"),
    path("policies/<uuid:pk>", PolicyDetailUpdateView.as_view(), name="policy-detail-update"),
]
