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
def get_status_emoji(status: str | None) -> str:
    if not status:
        return "⚪"

    status = status.lower()

    if status in ["good", "on_track", "healthy"]:
        return "🟢"
    elif status in ["warning", "at_risk", "delayed"]:
        return "🟡"
    elif status in ["critical", "behind", "failing"]:
        return "🔴"
    else:
        return "⚪"


def compile_message(project: Project):
    health_data = health(project)
    stalled_tasks_data = stalled_tasks(project)
    roast_data = roast(project)

    lines = []

    # ---------------- HEALTH SECTION ----------------
    if health_data:
        status_emoji = get_status_emoji(health_data.get("status"))

        lines.append(f"📊 **Project Health: {health_data.get('project_name')}**")
        lines.append(f"{status_emoji} Status: {health_data.get('status')}")
        lines.append(f"📈 Completion: {health_data.get('completion_percentage')}%")
        lines.append(f"⚡ Velocity: {health_data.get('daily_velocity')} tasks/day")
        lines.append(f"⏳ Days until guarantee: {health_data.get('days_until_guarantee')}")
        lines.append(f"📅 Expected completion: {health_data.get('expected_complete_by')}")
        lines.append(f"🚨 {health_data.get('current_panic_requirement')}")
        lines.append("")

    else:
        lines.append("📊 **Project Health:** No data available")
        lines.append("")

    # ---------------- STALLED TASKS ----------------
    stalled_tasks_list = stalled_tasks_data.get("stalled_tasks", [])

    lines.append(f"⚠️ **Stalled Tasks ({len(stalled_tasks_list)}):**")

    if stalled_tasks_list:
        for task in stalled_tasks_list[:5]:  # limit to avoid spam
            lines.append(f"- {task}")

        if len(stalled_tasks_list) > 5:
            lines.append(f"...and {len(stalled_tasks_list) - 5} more")
    else:
        lines.append("No stalled tasks 🎉")

    lines.append("")

    # ---------------- ROAST SECTION ----------------
    roast_text = roast_data.get("roast")

    if roast_text:
        # prevent extremely long messages
        if len(roast_text) > 1000:
            roast_text = roast_text[:1000] + "..."

        lines.append("🔥 **Roast:**")
        lines.append("```")
        lines.append(roast_text)
        lines.append("```")

    return "\n".join(lines)


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
