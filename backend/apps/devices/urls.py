"""Device URL patterns."""
from django.urls import path
from apps.devices.views import (
    AgentEnrollView,
    CreateEnrollmentTokenView,
    DeviceListView,
    ReassignDeviceView,
    RevokeDeviceView,
)

urlpatterns = [
    path("devices", DeviceListView.as_view(), name="device-list"),
    path("devices/enrollment-tokens", CreateEnrollmentTokenView.as_view(), name="device-enrollment-token"),
    path("devices/<uuid:pk>/revoke", RevokeDeviceView.as_view(), name="device-revoke"),
    path("devices/<uuid:pk>/reassign", ReassignDeviceView.as_view(), name="device-reassign"),
    path("agent/enroll", AgentEnrollView.as_view(), name="agent-enroll"),
]
