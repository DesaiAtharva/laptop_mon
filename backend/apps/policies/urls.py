"""Policy URL patterns."""
from django.urls import path, re_path
from apps.policies.views import AgentPolicyView, PolicyDetailUpdateView, PolicyListView

urlpatterns = [
    re_path(r"^agent/policy/?$", AgentPolicyView.as_view(), name="agent-policy"),
    re_path(r"^policies/?$", PolicyListView.as_view(), name="policy-list"),
    re_path(r"^policies/(?P<pk>[0-9a-f-]+)/?$", PolicyDetailUpdateView.as_view(), name="policy-detail-update"),
]
