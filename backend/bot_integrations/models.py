import uuid
from django.utils import timezone
from datetime import timedelta

from django.core.validators import MaxValueValidator
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


class CronSchedule(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='cron_schedule')
    scheduled_hour = models.PositiveSmallIntegerField(validators=[MaxValueValidator(23)])
    scheduled_day_of_week = models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)])
    processed = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"Cron schedule for project {self.project.name} at hour {self.scheduled_hour} on day {self.scheduled_day_of_week}"

    def mark_as_processed(self):
        if self.processed:
            return

        self.processed = True
        self.save()

    @property
    def is_daily(self):
        return self.scheduled_day_of_week < 0

    @property
    def is_active(self):
        return self.active

    def deactivate(self):
        self.active = False
        self.save()

    def activate(self):
        self.active = True
        self.save()

    def promote_to_daily(self):
        self.scheduled_day_of_week = -1

    def demote_to_weekly(self):
        self.scheduled_day_of_week, self.scheduled_hour = self.get_empty_batch_weekly()

    @staticmethod
    def reset_daily_schedules():
        CronSchedule.objects.filter(scheduled_day_of_week__lt=0).update(processed=False)

    @staticmethod
    def reset_weekly_schedules():
        CronSchedule.objects.filter(scheduled_day_of_week__gte=0).update(processed=False)

    @staticmethod
    def get_current_batch(day_start_hour: int = 8):
        now = timezone.now()
        current_day_of_week = now.weekday()
        current_hour = now.hour - day_start_hour
        current_half_hour = 0 if now.minute < 28 else 1

        if current_hour < 0:
            return CronSchedule.objects.none()

        return CronSchedule.objects.filter(
            scheduled_day_of_week=current_day_of_week,
            scheduled_hour__gte=2*current_hour+current_half_hour,
            processed=False
        ).select_related('project')

    @staticmethod
    def get_empty_batch_weekly(BATCH_SIZE: int = 40):
        for i in range(7):
            for j in range(24):
                if CronSchedule.objects.filter(scheduled_day_of_week=i, scheduled_hour=j).count() < BATCH_SIZE:
                    return i, j
        return None, None

    @staticmethod
    def get_empty_batch_daily(BATCH_SIZE: int = 10):
        for j in range(24):
            if CronSchedule.objects.filter(scheduled_day_of_week__lt=0, scheduled_hour=j).count() < BATCH_SIZE:
                return j
        return None
