from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from .models import Team, Membership, Developer, Invitation, Skill
from .serializers import TeamSerializer, DeveloperSerializer, InvitationSerializer
from .permissions import IsTeamMember, IsTeamLeader
from mixins import ActionPermissionMixin
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
            return Response({"error": "Skill is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not Skill.objects.filter(name=skill).exists():
            return Response({"error": "Skill not found"}, status=status.HTTP_404_NOT_FOUND)

        if add:
            developer.skills.add(Skill.objects.get(name=skill))
        else:
            developer.skills.remove(Skill.objects.get(name=skill))
        return Response({"status": "Skill added" if add else "Skill removed"})

    @action(detail=True, methods=['post'])
    def add_skill(self, request, pk=None):
        return self.get_skill(request, pk, add=True)

    @action(detail=True, methods=['post'])
    def remove_skill(self, request, pk=None):
        return self.get_skill(request, pk, add=False)

    @action(detail=True, methods=['get'])
    def get_skills(self, request, pk=None):
        developer = self.get_object()
        return Response(developer.skills.values())


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
            return Response({"error": "Username is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not Developer.objects.filter(user__username=invited_username).exists():
            return Response({"error": "Developer not found"}, status=status.HTTP_404_NOT_FOUND)

        invited_developer = Developer.objects.get(user__username=invited_username)
        success, error = send_invitation(request.user.developer, invited_developer, team)

        if not success:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": "Invitation sent"})

    @action(detail=True, methods=['post'])
    def join_request(self, request, pk=None):
        team = self.get_object()
        success, error = send_join_request(request.user.developer, team)
        if not success:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"status": "Join request sent"})

    @action(detail=True, methods=['get'])
    def join_requests(self, request, pk=None):
        team = self.get_object()
        return Response(team.active_join_requests.values())

    @action(detail=True, methods=['post'])
    def approve_join_request(self, request, pk=None):
        team = self.get_object()
        invitation_id = request.data.get('invitation_id')

        if not invitation_id:
            return Response({"error": "Invitation ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not team.invitations.filter(id=invitation_id).exists():
            return Response({"error": "Invitation not found"}, status=status.HTTP_404_NOT_FOUND)

        invitation = team.invitations.get(id=invitation_id)
        success, error = accept_join_request(invitation)

        if not success:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": "Join request approved"})


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
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": "Invitation accepted"})

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        invitation = self.get_object()

        success, error = decline_invitation(invitation)

        if not success:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": "Invitation declined"})
