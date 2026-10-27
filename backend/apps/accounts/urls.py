"""Accounts URL patterns."""
from django.urls import path
from apps.accounts.views import OIDCCallbackView, RevokeSessionsView

urlpatterns = [
    path("oidc/callback", OIDCCallbackView.as_view(), name="oidc-callback"),
    path("session/revoke", RevokeSessionsView.as_view(), name="session-revoke"),
]
