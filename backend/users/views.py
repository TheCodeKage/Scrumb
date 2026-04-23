from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from services.api_responses import success_response, error_response
from .models import Team, Membership, Developer, Invitation, Skill
from .serializers import TeamSerializer, DeveloperSerializer, InvitationSerializer
from .permissions import IsTeamMember, IsTeamLeader, ActionPermissionMixin
from .logic import send_invitation, send_join_request, accept_join_request, accept_invitation, decline_invitation


class DeveloperViewSet(viewsets.ModelViewSet):
    serializer_class = DeveloperSerializer
    permission_classes = [IsAuthenticated]

    allowed_actions = ['add_skill', 'remove_skill', 'get_skills', 'get']

    def get_queryset(self):
        return Developer.objects.filter(user=self.request.user).prefetch_related(
            'skills',
        )

    def get_skill(self, request, pk=None, add=True):
        developer = self.get_object()
        skill = request.data.get('skill')

        if not skill:
            return error_response(
                message="Skill is required",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"field": "skill", "detail": "Skill is required"}],
            )
        if not Skill.objects.filter(name=skill).exists():
            return error_response(
                message="Skill not found",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "skill", "detail": "Skill not found"}],
            )

        if add:
            developer.skills.add(Skill.objects.get(name=skill))
        else:
            developer.skills.remove(Skill.objects.get(name=skill))
        return success_response(message="Skill added" if add else "Skill removed")

    @action(detail=True, methods=['post'])
    def add_skill(self, request, pk=None):
        return self.get_skill(request, pk, add=True)

    @action(detail=True, methods=['post'])
    def remove_skill(self, request, pk=None):
        return self.get_skill(request, pk, add=False)

    @action(detail=True, methods=['get'])
    def get_skills(self, request, pk=None):
        developer = self.get_object()
        return success_response(message="Skills fetched", data=list(developer.skills.values()))


class TeamViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    serializer_class = TeamSerializer

    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['name']

    permission_map = {
        'update': [IsAuthenticated, IsTeamLeader],
        'partial_update': [IsAuthenticated, IsTeamLeader],
        'destroy': [IsAuthenticated, IsTeamLeader],
        'invite': [IsAuthenticated, IsTeamLeader],
        'join_request': [IsAuthenticated],
        'join_requests': [IsAuthenticated, IsTeamMember],
        'approve_join_request': [IsAuthenticated, IsTeamLeader],
        'leave': [IsAuthenticated, IsTeamMember],
        'kick': [IsAuthenticated, IsTeamLeader],
    }

    def get_queryset(self):
        user = self.request.user.developer
        show_all = self.request.query_params.get('show_all', 'false').lower() == 'true'

        if (self.action in ('get', 'list') and show_all) or self.action == 'join_request':
            return Team.objects.all()

        return Team.objects.filter(members=user)


    def perform_create(self, serializer):
        team = serializer.save()
        Membership.objects.create(team=team, developer=self.request.user.developer, role=Membership.Role.LEADER)
        return team

    @action(detail=True, methods=['post'])
    def invite(self, request, pk=None):
        team = self.get_object()
        invited_username = request.data.get('username')

        if not invited_username:
            return error_response(
                message="Username is required",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"field": "username", "detail": "Username is required"}],
            )

        if not Developer.objects.filter(user__username=invited_username).exists():
            return error_response(
                message="Developer not found",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "username", "detail": "Developer not found"}],
            )

        invited_developer = Developer.objects.get(user__username=invited_username)
        success, error = send_invitation(request.user.developer, invited_developer, team)

        if not success:
            return error_response(message=error, status_code=status.HTTP_400_BAD_REQUEST)

        return success_response(message="Invitation sent")

    @action(detail=True, methods=['post'])
    def join_request(self, request, pk=None):
        team = self.get_object()
        success, error = send_join_request(request.user.developer, team)
        if not success:
            return error_response(message=error, status_code=status.HTTP_400_BAD_REQUEST)
        return success_response(message="Join request sent")

    @action(detail=True, methods=['get'])
    def join_requests(self, request, pk=None):
        team = self.get_object()
        return success_response(message="Join requests fetched", data=list(team.active_join_requests.values()))

    @action(detail=True, methods=['post'])
    def approve_join_request(self, request, pk=None):
        team = self.get_object()
        invitation_id = request.data.get('invitation_id')

        if not invitation_id:
            return error_response(
                message="Invitation ID is required",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"field": "invitation_id", "detail": "Invitation ID is required"}],
            )

        if not team.invitations.filter(id=invitation_id).exists():
            return error_response(
                message="Invitation not found",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "invitation_id", "detail": "Invitation not found"}],
            )

        invitation = team.invitations.get(id=invitation_id)
        success, error = accept_join_request(invitation)

        if not success:
            return error_response(message=error, status_code=status.HTTP_400_BAD_REQUEST)

        return success_response(message="Join request approved")

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        team = self.get_object()
        Membership.objects.filter(team=team, developer=request.user.developer).delete()
        return success_response(message="Team left")

    @action(detail=True, methods=['post'])
    def kick(self, request, pk=None):
        team = self.get_object()
        kicked_username = request.data.get('username')

        if not kicked_username:
            return error_response(
                message="Username is required",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"field": "username", "detail": "Username is required"}],
            )

        kicked_developer = Developer.objects.filter(
            user__username=kicked_username,
            memberships__team=team
        ).first()

        if not kicked_developer:
            return error_response(
                message="Developer not found in this team",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "username", "detail": "Developer not found"}],
            )

        if kicked_developer.user == request.user:
            return error_response(
                message="You cannot kick yourself",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        deleted, _ = kicked_developer.memberships.filter(team=team).delete()

        if deleted == 0:
            return error_response(
                message="Developer is not part of this team",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return success_response(message="Developer kicked successfully")


class InvitationViewSet(ActionPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = InvitationSerializer

    allowed_actions = ['list', 'get', 'accept', 'decline']

    def get_queryset(self):
        return Invitation.objects.filter(developer=self.request.user.developer)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        invitation = self.get_object()

        success, error = accept_invitation(invitation)

        if not success:
            return error_response(message=error, status_code=status.HTTP_400_BAD_REQUEST)

        return success_response(message="Invitation accepted")

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        invitation = self.get_object()

        success, error = decline_invitation(invitation)

        if not success:
            return error_response(message=error, status_code=status.HTTP_400_BAD_REQUEST)

        return success_response(message="Invitation declined")
