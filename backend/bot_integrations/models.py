import uuid

from django.db.models import Q
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


class Timeout(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)

    class ActionType(models.TextChoices):
        CUT = 'cut_tasks', 'Cut Tasks'
        DELAY = 'delay_deadline', 'Delay Deadline'

    action_type = models.CharField(max_length=20, choices=ActionType.choices, blank=True, null=True)
    timeout_time = models.DateTimeField(default=timezone.now() + timedelta(hours=6))

    def process_timeout(self):
        self.actions.update(enabled=False)
        self.delete()

    @staticmethod
    def get_current_batch():
        return Timeout.objects.filter(timeout_time__lte=timezone.now()).order_by('timeout_time')


class NotificationAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='actions')

    class ActionType(models.TextChoices):
        CUT = 'cut_tasks', 'Cut Tasks'
        DELAY = 'delay_deadline', 'Delay Deadline'

    action_type = models.CharField(max_length=20, choices=ActionType.choices, blank=True, null=True)
    timeout = models.ForeignKey(Timeout, on_delete=models.CASCADE, related_name='actions')
    enabled = models.BooleanField(default=True)

    panic_recommendations = models.JSONField(default=list, blank=True, null=True)
    deadline_update = models.DateTimeField(blank=True, null=True)


class InstallationState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    guild = models.ForeignKey(DiscordGuild, on_delete=models.CASCADE, related_name='installation_states')


class CronSchedule(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='cron_schedule')
    scheduled_hour = models.PositiveSmallIntegerField(validators=[MaxValueValidator(23)])
    scheduled_day_of_week = models.SmallIntegerField(validators=[MaxValueValidator(6)])
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
        hour = CronSchedule.get_empty_batch_daily()
        if hour is not None:
            self.scheduled_day_of_week = -1
            self.scheduled_hour = hour
            self.save()

    def demote_to_weekly(self):
        self.scheduled_day_of_week, self.scheduled_hour = self.get_empty_batch_weekly()
        self.save()

    @staticmethod
    def reset_daily_schedules():
        CronSchedule.objects.filter(scheduled_day_of_week__lt=0).update(processed=False)

    @staticmethod
    def reset_weekly_schedules():
        CronSchedule.objects.filter(scheduled_day_of_week__gte=0).update(processed=False)

    @staticmethod
    def get_current_batch(day_start_hour: int = 8, day_length: int = 12):
        now = timezone.localtime(timezone.now())

        current_day_of_week = now.weekday()
        current_hour = now.hour - day_start_hour

        # before 8 AM → no jobs
        if current_hour < 0:
            return CronSchedule.objects.none()

        # after 8 PM → treat as end of day (optional safety)
        if current_hour > day_length - 1:
            current_hour = day_length - 1

        return CronSchedule.objects.filter(
            processed=False,
            active=True,
            scheduled_hour__lte=current_hour
        ).filter(
            Q(scheduled_day_of_week=current_day_of_week) |
            Q(scheduled_day_of_week__lt=0)
        ).select_related('project', 'project__settings')

    @staticmethod
    def get_empty_batch_weekly(BATCH_SIZE: int = 40):
        for i in range(7):
            for j in range(12):
                if CronSchedule.objects.filter(scheduled_day_of_week=i, scheduled_hour=j).count() < BATCH_SIZE:
                    return i, j
        return None, None

    @staticmethod
    def get_empty_batch_daily(BATCH_SIZE: int = 10):
        for j in range(12):
            if CronSchedule.objects.filter(scheduled_day_of_week__lt=0, scheduled_hour=j).count() < BATCH_SIZE:
                return j
        return None
