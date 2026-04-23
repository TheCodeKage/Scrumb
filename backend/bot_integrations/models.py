import uuid

from django.db import models

from projects.models import Project


# Create your models here.
class DiscordGuild(models.Model):
    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=100, blank=True, null=True)


class DiscordBotIntegration(models.Model):
    discord_guild = models.ForeignKey(DiscordGuild, on_delete=models.CASCADE, related_name='bot_integrations')
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='discord_bot_integration')
    channel_id = models.BigIntegerField(blank=True, null=True)


class Notification(models.Model):
    bot_integration = models.ForeignKey(DiscordBotIntegration, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_sent = models.BooleanField(default=False)


class InstallationState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    guild = models.ForeignKey(DiscordGuild, on_delete=models.CASCADE, related_name='installation_states')
