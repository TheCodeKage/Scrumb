from rest_framework.serializers import ModelSerializer, CharField
from .models import Skill, Developer, Team, Membership, Invitation


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