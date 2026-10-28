"""Tenancy URLs."""
from django.urls import path
from apps.tenancy.views import (
    AcceptInvitationView,
    CreateTenantView,
    MeTenantsView,
    TenantDeletionView,
    TenantInvitationsView,
    TenantMemberDetailView,
    TenantMembersListView,
    TenantSuspensionView,
)

urlpatterns = [
    path("me/tenants", MeTenantsView.as_view(), name="me-tenants"),
    path("tenants", CreateTenantView.as_view(), name="tenant-create"),
    path("tenants/<uuid:tenant_id>/members", TenantMembersListView.as_view(), name="tenant-members"),
    path("tenants/<uuid:tenant_id>/invitations", TenantInvitationsView.as_view(), name="tenant-invitations"),
    path("tenants/<uuid:tenant_id>/members/<uuid:member_id>", TenantMemberDetailView.as_view(), name="tenant-member-detail"),
    path("tenants/<uuid:tenant_id>/suspend", TenantSuspensionView.as_view(), name="tenant-suspend"),
    path("tenants/<uuid:tenant_id>", TenantDeletionView.as_view(), name="tenant-delete"),
    path("invitations/accept", AcceptInvitationView.as_view(), name="invitation-accept"),
]
