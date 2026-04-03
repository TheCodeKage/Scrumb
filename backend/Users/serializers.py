from rest_framework.serializers import ModelSerializer, CharField
from .models import Skill, Developer, Team, Membership, Invitation
from dj_rest_auth.serializers import PasswordResetSerializer as Base
from django.conf import settings


class SkillSerializer(ModelSerializer):
    class Meta:
        model = Skill
        fields = '__all__'


class DeveloperSerializer(ModelSerializer):
    skills = SkillSerializer(many=True, read_only=True)
    username = CharField(source='user.username', read_only=True)

    class Meta:
        model = Developer
        fields = ('id', 'username', 'skills')


class MemberSerializer(ModelSerializer):
    developer = DeveloperSerializer(read_only=True)
    
    class Meta:
        model = Membership
        fields = ('id', 'developer', 'role', 'created_at', 'updated_at')


class TeamSerializer(ModelSerializer):
    members = MemberSerializer(many=True, read_only=True, source='memberships')

    class Meta:
        model = Team
        fields = ('id', 'name', 'members')


class InvitationSerializer(ModelSerializer):
    team = TeamSerializer()
    developer = DeveloperSerializer()
    
    class Meta:
        model = Invitation
        fields = ('id', 'team', 'developer', 'initiated_by', 'status', 'created_at', 'updated_at')


class PasswordResetSerializer(Base):
    def get_email_options(self):
        return {
            'extra_email_context': {
                'frontend_url': settings.FRONTEND_URL,
            },
            'domain_override': settings.FRONTEND_URL.replace('https://', '').replace('http://', ''),
            'use_https': settings.FRONTEND_URL.startswith('https'),
        }
