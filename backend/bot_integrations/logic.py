from .models import DiscordBotIntegration, Notification
from projects.models import Project


def send_message(
        message: str,
        project: Project | None=None,
        bot_integration: DiscordBotIntegration | None=None,
):
    if not project and not bot_integration:
        return

    if project:
        if not project.discord_bot_integration:
            return
        bot_integration = project.discord_bot_integration

    Notification.objects.create(message=message, bot_integration=bot_integration)
