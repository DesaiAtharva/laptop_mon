"""Tenancy serializers for organizations, memberships, invitations, and teams."""
from rest_framework import serializers
from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.tenancy.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Team,
    TeamMember,
    Tenant,
    TenantStatus,
)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "created_at", "updated_at"]


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "tenant", "name", "created_at"]
        read_only_fields = ["id", "tenant", "created_at"]


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    teams = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = [
            "id",
            "tenant_id",
            "user",
            "role",
            "status",
            "has_screenshot_permission",
            "teams",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant_id", "user", "created_at", "updated_at"]

    def get_teams(self, obj: Membership) -> list[dict[str, str]]:
        return [
            {"id": str(tm.team.id), "name": tm.team.name}
            for tm in obj.team_memberships.select_related("team").all()
        ]


class MembershipUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=MembershipRole.choices, required=False)
    status = serializers.ChoiceField(choices=MembershipStatus.choices, required=False)
    has_screenshot_permission = serializers.BooleanField(required=False)
    team_id = serializers.UUIDField(required=False, allow_null=True)


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=MembershipRole.choices, default=MembershipRole.EMPLOYEE)


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "tenant_id", "email", "role", "status", "expires_at", "created_at"]
        read_only_fields = fields
