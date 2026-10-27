"""Tenancy URLs."""
from django.urls import path
from apps.tenancy.views import (
    CreateTenantView,
    MeTenantsView,
    TenantInvitationsView,
    TenantMemberDetailView,
    TenantMembersListView,
)

urlpatterns = [
    path("me/tenants", MeTenantsView.as_view(), name="me-tenants"),
    path("tenants", CreateTenantView.as_view(), name="tenant-create"),
    path("tenants/<uuid:tenant_id>/members", TenantMembersListView.as_view(), name="tenant-members"),
    path("tenants/<uuid:tenant_id>/invitations", TenantInvitationsView.as_view(), name="tenant-invitations"),
    path("tenants/<uuid:tenant_id>/members/<uuid:member_id>", TenantMemberDetailView.as_view(), name="tenant-member-detail"),
]
