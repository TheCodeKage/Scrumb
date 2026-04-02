from rest_framework.permissions import BasePermission
from Users.models import Membership


class IsTeamMember(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.team.memberships.filter(
            developer=request.user.developer,
        ).exists()


class IsTeamLeader(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.team.memberships.filter(
            developer=request.user.developer,
            role=Membership.Role.LEADER
        ).exists()
