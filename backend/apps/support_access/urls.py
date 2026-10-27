"""Support access URLs."""
from django.urls import path
from apps.support_access.views import (
    ApproveSupportAccessView,
    RequestSupportAccessView,
    RevokeSupportAccessView,
)

urlpatterns = [
    path("request", RequestSupportAccessView.as_view(), name="support-request"),
    path("<uuid:pk>/approve", ApproveSupportAccessView.as_view(), name="support-approve"),
    path("<uuid:pk>/revoke", RevokeSupportAccessView.as_view(), name="support-revoke"),
]
