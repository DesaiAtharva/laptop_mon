"""User and Session models adhering to §7.2 and §11."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any, Optional
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from apps.common.models import BaseTimestampedModel, BaseUUIDModel


class CustomUserManager(BaseUserManager):
    """Manager for custom user model using lowercase email as unique identifier."""

    def create_user(
        self,
        email: str,
        password: Optional[str] = None,
        name: str = "",
        **extra_fields: Any,
    ) -> User:
        if not email:
            raise ValueError("The Email field must be set.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, name=name, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: Optional[str] = None,
        name: str = "",
        **extra_fields: Any,
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("mfa_enabled", True)
        return self.create_user(email, password, name, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, BaseTimestampedModel):
    """User model representing a platform identity (§7.2).

    Attributes:
        id: UUID primary key.
        email: Unique normalized email address.
        name: Display name.
        mfa_enabled: Flag indicating if Multi-Factor Authentication is active.
        created_at: UTC timestamp of creation.
    """

    email = models.EmailField(unique=True, db_index=True, max_length=255)
    name = models.CharField(max_length=255, blank=True, default="")
    mfa_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email


class UserSession(BaseUUIDModel):
    """Tracks active user sessions with explicit revocation capability (E48).

    Allows immediate invalidation of all sessions if an account is compromised.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    token_hash = models.CharField(max_length=64, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "user_sessions"
        ordering = ["-created_at"]

    @classmethod
    def create_session(
        cls,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: str = "",
        lifetime_hours: int = 24,
    ) -> tuple[UserSession, str]:
        """Create a new session, returning the session object and the raw token."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = timezone.now() + timezone.timedelta(hours=lifetime_hours)

        session = cls.objects.create(
            user=user,
            token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent[:512],
            expires_at=expires_at,
        )
        return session, raw_token

    @property
    def is_valid(self) -> bool:
        """Check if the session has not been revoked and has not expired."""
        if self.revoked_at is not None:
            return False
        return self.expires_at > timezone.now()

    def revoke(self) -> None:
        """Immediately revoke this session (E48)."""
        if not self.revoked_at:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

    @classmethod
    def revoke_all_for_user(cls, user: User) -> int:
        """Immediately revoke all active sessions for a user (E48)."""
        now = timezone.now()
        return cls.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
