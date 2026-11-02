"""Audit log URLs."""
from django.urls import path, re_path
from apps.audit.views import AuditLogListView

urlpatterns = [
    re_path(r"^audit-logs/?$", AuditLogListView.as_view(), name="audit-log-list"),
]

