"""Audit log API views."""
from typing import Any
from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response
from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer
from apps.rbac.permissions import IsAuditor


class AuditLogListView(generics.ListAPIView):
    """List audit logs strictly scoped to the authenticated tenant (§8.4, §11.1).

    Accessible by Auditors and Organization Admins only.
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuditor]

    def get_queryset(self) -> Any:
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return AuditLog.objects.none()
        return (
            AuditLog.objects.filter(tenant=tenant)
            .select_related("actor")
            .order_by("-created_at")
        )
