from datetime import timedelta
from uuid import UUID

from django.utils.timezone import now, localtime

from projects.analytics import health, stalled_tasks, roast, raw_health
from projects.logic import cut_tasks
from services.AI.api_caller import get_panic_recommendations
from .models import DiscordBotIntegration, Notification, CronSchedule, NotificationAction, Timeout
from projects.models import Project, ProjectSettings

project_settings_map = {
    ProjectSettings.PanicPolicy.ASK_LEADER: None,
    ProjectSettings.PanicPolicy.ASK_LEADER_ARCHIVE: Timeout.ActionType.CUT,
    ProjectSettings.PanicPolicy.ASK_LEADER_REVIEW: Timeout.ActionType.DELAY
}


# ----------------------------- Message Sending Functions ----------------------------------------------------
def send_message(
        message: str,
        project: Project | None = None,
        bot_integration: DiscordBotIntegration | None = None,
):
    if not project and not bot_integration:
        return None

    if project:
        if not project.discord_bot_integration:
            return None
        bot_integration = project.discord_bot_integration

    return Notification.objects.create(message=message, bot_integration=bot_integration)


def add_notification_action(notification: Notification, project: Project, recommendations: list[str], deadline: timedelta):
    notification_actions = []
    action_type = project_settings_map.get(project.settings.panic_policy) if project else None
    timeout = Timeout.objects.create(project=project, action_type=action_type)
    for action in [NotificationAction.ActionType.DELAY, NotificationAction.ActionType.CUT]:
        notification_actions.append(NotificationAction(
            notification=notification,
            action_type=action,
            timeout=timeout,
            panic_recommendations=recommendations,
            deadline_update=deadline
        ))
    if notification_actions:
        NotificationAction.objects.bulk_create(notification_actions)


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


def compile_message(project: Project, roaster_mode: bool = True, health_data: dict | None = None):
    stalled_tasks_data = stalled_tasks(project)

    if roaster_mode:
        roast_data = roast(project)
    else:
        roast_data = {"roast": ""}

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
    threshold_date = (localtime(now()) + timedelta(days=7)).date()

    for cron_job in CronSchedule.get_current_batch():
        try:
            project = cron_job.project
            shame_mode = project.settings.shame_policy

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

            raw_health_data = raw_health(project)
            health_data = health(raw_health_data=raw_health_data,)

            # process job
            if not shame_mode == ProjectSettings.ShamePolicy.NONE:
                send_message(compile_message(project, shame_mode == ProjectSettings.ShamePolicy.SHAME, health_data),
                             project=project)

            # check panic
            panic_policy = project.settings.panic_policy
            if health_data and health_data.get("status") == "TERMINAL" and panic_policy != ProjectSettings.PanicPolicy.NONE:
                panic_recommendations = get_panic_recommendations(project, raw_health_data.get('target_cut', 0))
                print(panic_recommendations)
                updated_deadline = project.guarantee_date + timedelta(days=raw_health_data.get('expected_complete_by', 0))
                print(updated_deadline)
                if panic_policy == ProjectSettings.PanicPolicy.FORCE_ARCHIVE:
                    cut_tasks(panic_recommendations, project)
                    print("cut tasks")
                    send_message(
                        f"🚨 **Panic Alert for {project.name}!** 🚨\n\n"
                        f"{health_data.get('current_panic_requirement')}\n\n"
                        f"Following tasks have been cut:\n" + "\n".join(f"- {rec}" for rec in panic_recommendations),
                        project=project
                    )

                elif panic_policy == ProjectSettings.PanicPolicy.DELAY_DEADLINE:
                    project.guarantee_date = updated_deadline
                    print("delay deadline")
                    project.save()
                    send_message(
                        f"🚨 **Panic Alert for {project.name}!** 🚨\n\n"
                        f"{health_data.get('current_panic_requirement')}\n\n"
                        f"Deadline has been extended by {raw_health_data.get('expected_complete_by', 0)} days. Please focus on getting back on track!",
                        project=project
                    )

                else:
                    panic_message = send_message(
                        f"🚨 **Panic Alert for {project.name}!** 🚨\n\n"
                        f"{health_data.get('current_panic_requirement')}\n\n"
                        f"Please take immediate action to reduce scope and get back on track!",
                        project=project
                    )
                    add_notification_action(panic_message, project, panic_recommendations, updated_deadline)

            cron_job.mark_as_processed()

        except Exception as e:
            print(f"Error processing cron job {cron_job.id}: {e}")

        for timeout in Timeout.get_current_batch():
            if timeout.action_type == Timeout.ActionType.CUT:
                action = timeout.actions.filter(action_type=NotificationAction.ActionType.CUT).first()
                if action:
                    cut_tasks(action.panic_recommendations, timeout.project)
            elif timeout.ActionType == Timeout.ActionType.DELAY:
                timeout.project.guarantee_date = timeout.actions.filter(action_type=NotificationAction.ActionType.DELAY).first().deadline_update
                timeout.project.save()
            timeout.process_timeout()


# ----------------------------- Discord Button Actions ----------------------------------------------------
def process_interaction(button_id: UUID):
    if not button_id:
        return None

    interaction = NotificationAction.objects.filter(id=button_id).select_related('timeout').first()
    if not interaction:
        return None

    if not interaction.enabled:
        return None

    if interaction.action_type == NotificationAction.ActionType.DELAY:
        interaction.timeout.project.guarantee_date = interaction.deadline_update
        interaction.timeout.project.save()
    elif interaction.action_type == NotificationAction.ActionType.CUT:
        cut_tasks(interaction.panic_recommendations, interaction.timeout.project)

    interaction.enabled = False
    interaction.save()

    return True