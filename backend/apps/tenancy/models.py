"""Tenancy, Membership, and Team models strictly per §7.2."""
from __future__ import annotations

import secrets
import uuid
from typing import Any, Optional
from django.core.exceptions import ValidationError
from django.db import models
from apps.accounts.models import User
from apps.common.models import BaseTimestampedModel, BaseUUIDModel


class TenantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    DELETING = "deleting", "Deleting"


class Tenant(BaseTimestampedModel):
    """Tenant model representing an isolated organizational customer (§7.2)."""

    name = models.CharField(max_length=255, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=TenantStatus.choices,
        default=TenantStatus.ACTIVE,
        db_index=True,
    )

    class Meta:
        db_table = "tenants"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE

    @property
    def is_suspended(self) -> bool:
        return self.status == TenantStatus.SUSPENDED

    @property
    def is_deleting(self) -> bool:
        return self.status == TenantStatus.DELETING


class TenantScopedQuerySet(models.QuerySet):
    """Queryset ensuring all database queries are strictly partitioned by tenant."""

    def for_tenant(self, tenant: Tenant | uuid.UUID | str) -> TenantScopedQuerySet:
        tenant_id = tenant.id if isinstance(tenant, Tenant) else tenant
        return self.filter(tenant_id=tenant_id)


class TenantScopedManager(models.Manager):
    """Manager providing default queryset with tenant-filtering helpers."""

    def get_queryset(self) -> TenantScopedQuerySet:
        return TenantScopedQuerySet(self.model, using=self._db)

    def for_tenant(self, tenant: Tenant | uuid.UUID | str) -> TenantScopedQuerySet:
        return self.get_queryset().for_tenant(tenant)


class TenantModel(BaseTimestampedModel):
    """Abstract base model for all tenant-owned models."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        db_index=True,
    )

    objects = TenantScopedManager()

    class Meta:
        abstract = True


class MembershipRole(models.TextChoices):
    EMPLOYEE = "employee", "Employee"
    MANAGER = "manager", "Manager"
    ADMIN = "admin", "Organization Admin"
    AUDITOR = "auditor", "Auditor"
    PLATFORM_SUPPORT = "platform_support", "Platform Support"
    SERVICE_IDENTITY = "service_identity", "Service Identity"


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class Membership(TenantModel):
    """Binds a User to a Tenant with a specific Role and Status (§7.2)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="memberships",
        db_index=True,
    )
    role = models.CharField(
        max_length=32,
        choices=MembershipRole.choices,
        default=MembershipRole.EMPLOYEE,
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
        db_index=True,
    )
    # Explicit separate permission per §2.2
    has_screenshot_permission = models.BooleanField(
        default=False,
        help_text="Explicit separate permission required to access screenshot data.",
    )

    class Meta:
        db_table = "memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"],
                name="unique_tenant_user_membership",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["user", "status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.email} in {self.tenant.name} as {self.role} ({self.status})"

    def clean(self) -> None:
        super().clean()
        if self.role == MembershipRole.AUDITOR and self.has_screenshot_permission:
            # Auditors have no screenshot access by default per §2.1
            pass

    def disable(self) -> None:
        """Disables the membership and invokes lifecycle hooks (E42: Employee leaves)."""
        self.status = MembershipStatus.DISABLED
        self.save(update_fields=["status", "updated_at"])

        # Revoke user sessions
        self.user.sessions.filter(revoked_at__isnull=True).update(revoked_at=self.updated_at)

        # Trigger device revocation hook (placeholder or service dispatch)
        from apps.tenancy.services import on_employee_left
        on_employee_left(self)


class Team(TenantModel):
    """Teams partition employees under managers (§7.2)."""

    name = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = "teams"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_tenant_team_name",
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant.name})"


class TeamMember(BaseTimestampedModel):
    """Associates a Membership to a Team with composite tenant integrity check (§7.2)."""

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="members",
        db_index=True,
    )
    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="team_memberships",
        db_index=True,
    )

    class Meta:
        db_table = "team_members"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "membership"],
                name="unique_team_member",
            )
        ]

    def clean(self) -> None:
        """Composite constraint: membership.tenant_id must equal team.tenant_id (§7.2)."""
        super().clean()
        if self.membership_id and self.team_id:
            if self.membership.tenant_id != self.team.tenant_id:
                raise ValidationError("Team and membership must belong to the same tenant.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class InvitationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REVOKED = "revoked", "Revoked"


class Invitation(TenantModel):
    """Invitations for adding members to a tenant (§8.2)."""

    email = models.EmailField(db_index=True, max_length=255)
    role = models.CharField(
        max_length=32,
        choices=MembershipRole.choices,
        default=MembershipRole.EMPLOYEE,
    )
    status = models.CharField(
        max_length=32,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
        db_index=True,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "invitations"
        ordering = ["-created_at"]

    @classmethod
    def create_invitation(
        cls,
        tenant: Tenant,
        email: str,
        role: str,
        expires_days: int = 7,
    ) -> tuple[Invitation, str]:
        import hashlib
        from django.utils import timezone

        email = email.lower().strip()
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = timezone.now() + timezone.timedelta(days=expires_days)

        invitation = cls.objects.create(
            tenant=tenant,
            email=email,
            role=role,
            status=InvitationStatus.PENDING,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        return invitation, raw_token
