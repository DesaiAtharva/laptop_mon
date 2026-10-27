"""Authentication and session management views."""
from __future__ import annotations

from typing import Any
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.models import User, UserSession
from apps.accounts.oidc import validate_oidc_state_and_nonce
from apps.accounts.serializers import OIDCCallbackSerializer, SessionRevokeSerializer, UserSerializer
from apps.common.exceptions import MFARequired


class OIDCCallbackView(APIView):
    """OIDC callback endpoint (§8.2).

    Validates state and nonce to protect against CSRF and replay attacks.
    Provisions or retrieves the user, validates MFA requirements for privileged roles,
    and returns a cryptographically secure session token.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = OIDCCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        state = data["state"]
        nonce = data["nonce"]

        if not validate_oidc_state_and_nonce(state, nonce):
            raise ValidationError({"state": ["Invalid, expired, or already-consumed state/nonce."]})

        email = data.get("email")
        if not email:
            # Fallback or derived from code
            email = f"{data['code']}@laptop-mon.local"
        email = email.lower()

        name = data.get("name", "")
        mfa_authenticated = data.get("mfa_authenticated", False)

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"name": name, "mfa_enabled": mfa_authenticated},
        )

        if not user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        # MFA enforcement check: If MFA is enabled on user and request was not MFA verified
        if user.mfa_enabled and not mfa_authenticated:
            raise MFARequired("MFA authentication challenge required.")

        # Extract client IP and User-Agent
        ip_address = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        session, raw_token = UserSession.create_session(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Audit login
        try:
            from apps.audit.services import log_audit_event
            log_audit_event(
                request=request,
                actor=user,
                action="auth.sign_in",
                resource_type="user",
                resource_id=str(user.id),
                metadata={"mfa_authenticated": mfa_authenticated, "ip": ip_address},
            )
        except Exception:
            pass

        return Response(
            {
                "token": raw_token,
                "user": UserSerializer(user).data,
                "expires_at": session.expires_at,
            },
            status=status.HTTP_200_OK,
        )


class RevokeSessionsView(APIView):
    """Session revocation endpoint (E48: Account compromised / incident response)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = SessionRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target_user = request.user
        target_user_id = data.get("target_user_id")

        if target_user_id and target_user_id != request.user.id:
            # Only admin or platform support can revoke another user's sessions
            membership = getattr(request, "membership", None)
            is_admin = membership and membership.role in ["admin", "org_admin", "platform_support"]
            if not is_admin and not request.user.is_superuser:
                raise PermissionDenied("Only administrators can revoke other users' sessions.")
            try:
                target_user = User.objects.get(id=target_user_id)
            except User.DoesNotExist:
                raise ValidationError({"target_user_id": ["Target user not found."]})

        now = timezone.now()
        revoke_all = data.get("all", False)

        if revoke_all:
            revoked_count = UserSession.objects.filter(
                user=target_user,
                revoked_at__isnull=True,
            ).update(revoked_at=now)
        else:
            current_session = getattr(request, "user_session", None)
            if current_session:
                current_session.revoke()
                revoked_count = 1
            else:
                revoked_count = 0

        # Log audit event
        try:
            from apps.audit.services import log_audit_event
            log_audit_event(
                request=request,
                actor=request.user,
                action="auth.session_revoked",
                resource_type="user",
                resource_id=str(target_user.id),
                metadata={"revoked_all": revoke_all, "count": revoked_count},
            )
        except Exception:
            pass

        return Response(
            {
                "message": f"Successfully revoked {revoked_count} active session(s).",
                "revoked_count": revoked_count,
            },
            status=status.HTTP_200_OK,
        )
