from django.urls import include, path
from apps.common.views import LivenessCheckView, MetricsView, ReadinessCheckView

urlpatterns = [
    path("health/live", LivenessCheckView.as_view(), name="health-live"),
    path("health/ready", ReadinessCheckView.as_view(), name="health-ready"),
    path("metrics", MetricsView.as_view(), name="metrics"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.tenancy.urls")),
    path("api/", include("apps.devices.urls")),
    path("api/", include("apps.policies.urls")),
    path("api/", include("apps.ingestion.urls")),
    path("api/audit-logs/", include("apps.audit.urls")),
    path("api/support-access/", include("apps.support_access.urls")),
    path("api/", include("apps.screenshots.urls")),
    path("api/", include("apps.analytics.urls")),
    path("api/", include("apps.releases.urls")),
    path("api/billing/", include("apps.billing.urls")),
]
