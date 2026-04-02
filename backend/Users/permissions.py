from rest_framework.permissions import BasePermission, IsAuthenticated
from .models import Membership


class IsTeamMember(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.memberships.filter(
            developer=request.user.developer,
        ).exists()


class IsTeamLeader(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.memberships.filter(
            developer=request.user.developer,
            role=Membership.Role.LEADER
        ).exists()
