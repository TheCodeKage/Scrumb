from django.db import models
from django.contrib.auth.models import User
from django.db.models import Q


# Create your models here.
class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(
        blank=True, null=True
    )


class Developer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='developer')
    skills = models.ManyToManyField(Skill)


class PreviousProject(models.Model):
    project_name = models.CharField(max_length=100)
    project_description = models.TextField()
    project_link = models.URLField(blank=True, null=True)
    developer = models.ForeignKey(Developer, on_delete=models.CASCADE, related_name='previous_projects')


class Team(models.Model):
    name = models.CharField(max_length=100)

    members = models.ManyToManyField(
        Developer,
        related_name='teams',
        through='Membership'
    )

    def __str__(self):
        return self.name  # was broken before — members.all() returns a queryset, not a string

    def is_member(self, developer):
        return Membership.objects.filter(team=self, developer=developer).exists()

    def is_leader(self, developer):
        return Membership.objects.filter(team=self, developer=developer, role=Membership.Role.LEADER).exists()

    @property
    def active_join_requests(self):
        return Invitation.objects.filter(team=self, status=Invitation.Status.PENDING, initiated_by=Invitation.Initiator.DEVELOPER)

    @property
    def invitations(self):
        return Invitation.objects.filter(team=self, status=Invitation.Status.PENDING, initiated_by=Invitation.Initiator.TEAM)

    def get_team_data(self):
        memberships = self.memberships.select_related("developer__user").prefetch_related(
            "developer__skills",
            "developer__previous_projects"
        )

        result = []

        for m in memberships:
            dev = m.developer

            result.append({
                "username": dev.user.username,
                "role": m.role,
                "skills": [s.name for s in dev.skills.all()],
                "projects": [
                    {
                        "name": p.project_name,
                        "description": p.project_description[:300],
                        "link": p.project_link
                    }
                    for p in dev.previous_projects.all()
                ]
            })

        return {
            "team_name": self.name,
            "members": result
        }


class Membership(models.Model):

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    developer = models.ForeignKey(Developer, on_delete=models.CASCADE, related_name='memberships')

    class Role(models.TextChoices):
        LEADER = 'leader', 'Leader'
        MEMBER = 'member', 'Member'

    role = models.CharField(max_length=100, choices=Role.choices, default=Role.MEMBER)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('team', 'developer')  # one record per team-developer pair


class Invitation(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invitations')
    developer = models.ForeignKey(Developer, on_delete=models.CASCADE, related_name='invitations')

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        DECLINED = 'declined', 'Declined'

    class Initiator(models.TextChoices):
        TEAM = 'team', 'Team'
        DEVELOPER = 'developer', 'Developer'

    initiated_by = models.CharField(max_length=100, choices=Initiator.choices, default=Initiator.TEAM)
    status = models.CharField(max_length=100, choices=Status.choices, default=Status.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'developer'],
                condition=Q(status='pending'),
                name='unique_team_developer'
            )
        ]

    def join_requests(self, developer: Developer):
        return Invitation.objects.filter(
            initiated_by=self.Initiator.DEVELOPER,
            developer=developer,
            status=self.Status.PENDING
        )

    def active_invitations(self, developer: Developer):
        return Invitation.objects.filter(
            initiated_by=self.Initiator.TEAM,
            developer=developer,
            status=self.Status.PENDING
        )


class TeamLog(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='logs')
    developer = models.ForeignKey(Developer, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)
