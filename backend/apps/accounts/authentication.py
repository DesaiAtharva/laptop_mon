"""Authentication backend verifying bearer tokens and enforcing session revocation (E48)."""
from __future__ import annotations

import hashlib
from typing import Optional, Tuple
from django.utils import timezone
from rest_framework import authentication, exceptions
from apps.accounts.models import User, UserSession


class BearerTokenAuthentication(authentication.BaseAuthentication):
    """Authenticates against UserSession records using SHA-256 token hashing.

    Enforces session validity and immediate revocation (E48).
    """

    keyword = "Bearer"

    def authenticate(self, request: authentication.Request) -> Optional[Tuple[User, UserSession]]:
        auth_header = authentication.get_authorization_header(request).split()

        if not auth_header or auth_header[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth_header) == 1:
            raise exceptions.AuthenticationFailed("Invalid bearer token header. No token provided.")
        elif len(auth_header) > 2:
            raise exceptions.AuthenticationFailed("Invalid bearer token header. Token string contains spaces.")

        try:
            raw_token = auth_header[1].decode("utf-8")
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string contains invalid characters.")

        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        try:
            session = UserSession.objects.select_related("user").get(token_hash=token_hash)
        except UserSession.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or expired session token.")

        if session.revoked_at is not None:
            raise exceptions.AuthenticationFailed("Session has been revoked.")

        if session.expires_at <= timezone.now():
            raise exceptions.AuthenticationFailed("Session has expired.")

        if not session.user.is_active:
            raise exceptions.AuthenticationFailed("User account is disabled.")

        request.user_session = session  # type: ignore[attr-defined]

        # Resolve tenant context immediately upon authentication
        try:
            from apps.tenancy.context import resolve_tenant_context
            resolve_tenant_context(request, session.user)
        except Exception:
            # Re-raise DRF exceptions (ValidationError, NotFound, TenantSuspended, TenantDeleted)
            raise

        return (session.user, session)

    def authenticate_header(self, request: authentication.Request) -> str:
        return self.keyword
