from datetime import timedelta
from django.utils.timezone import now

from projects.analytics import health, stalled_tasks, roast
from .models import DiscordBotIntegration, Notification, CronSchedule
from projects.models import Project


# ----------------------------- Message Sending Functions ----------------------------------------------------
def send_message(
        message: str,
        project: Project | None = None,
        bot_integration: DiscordBotIntegration | None = None,
):
    if not project and not bot_integration:
        return

    if project:
        if not project.discord_bot_integration:
            return
        bot_integration = project.discord_bot_integration

    Notification.objects.create(message=message, bot_integration=bot_integration)


# ----------------------------- Message Retrieval Functions ----------------------------------------------------
def compile_message(project: Project):
    health_data = health(project)
    stalled_tasks_data = stalled_tasks(project)
    roast_data = roast(project)
    return f"Health: {health_data}\nStalled Tasks: {stalled_tasks_data['stalled_tasks']}\nRoast: {roast_data['roast']}"


# ----------------------------- Cron Job Functions ----------------------------------------------------
def add_cron_job(project: Project, is_daily: bool = False):
    if is_daily:
        scheduled_week, scheduled_hour = -1, CronSchedule.get_empty_batch_daily()
    else:
        scheduled_week, scheduled_hour = CronSchedule.get_empty_batch_weekly()

    CronSchedule.objects.create(
        project=project,
        scheduled_day_of_week=scheduled_week,
        scheduled_hour=scheduled_hour
    )


def remove_cron_job(project: Project):
    CronSchedule.objects.filter(project=project).delete()


def get_cron_jobs(scheduled_hour: int, scheduled_day_of_week: int = -1):
    return CronSchedule.objects.filter(scheduled_hour=scheduled_hour, scheduled_day_of_week=scheduled_day_of_week)


def process_cron_jobs():
    threshold_date = (now() + timedelta(days=7)).date()

    for cron_job in CronSchedule.get_current_batch():
        try:
            project = cron_job.project

            # deactivate if expired
            if cron_job.is_active and now().date() >= project.guarantee_date:
                cron_job.deactivate()
                continue

            # reactivate if valid again
            if not cron_job.is_active and now().date() < project.guarantee_date:
                cron_job.activate()
                continue

            # promote to daily
            if not cron_job.is_daily and project.guarantee_date <= threshold_date:
                cron_job.promote_to_daily()
                continue

            # demote to weekly
            if cron_job.is_daily and project.guarantee_date > threshold_date:
                cron_job.demote_to_weekly()
                continue

            # process job
            send_message(compile_message(project), project=project)
            cron_job.mark_as_processed()

        except Exception as e:
            print(f"Error processing cron job {cron_job.id}: {e}")
