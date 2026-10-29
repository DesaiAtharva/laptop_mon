"""Accounts URL patterns."""
from django.urls import path, re_path
from apps.accounts.views import OIDCCallbackView, PasswordLoginView, RevokeSessionsView

urlpatterns = [
    re_path(r"^login/?$", PasswordLoginView.as_view(), name="password-login"),
    re_path(r"^oidc/callback/?$", OIDCCallbackView.as_view(), name="oidc-callback"),
    re_path(r"^session/revoke/?$", RevokeSessionsView.as_view(), name="session-revoke"),
]
