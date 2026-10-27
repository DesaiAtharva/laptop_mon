"""Root URL configuration for Laptop Productivity Monitoring SaaS."""
from django.urls import include, path

urlpatterns = [
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.tenancy.urls")),
    path("api/audit-logs/", include("apps.audit.urls")),
    path("api/support-access/", include("apps.support_access.urls")),
]
