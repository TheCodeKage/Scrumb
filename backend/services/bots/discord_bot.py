from __future__ import annotations

from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

from discord import Client, app_commands
from discord import Interaction, TextChannel
from discord.client import Intents
from discord.ext import tasks
from discord.ui import Button, View

if TYPE_CHECKING:
    from discord import Guild
    from uuid import UUID

from services.bots.bootstrap import setup_django

setup_django()

from django.db.models import Q
from django.db import transaction
from bot_integrations.models import DiscordGuild, Notification, InstallationState
from django.conf import settings

client = Client(intents=Intents.default())
tree = app_commands.CommandTree(client)


async def send_message(channel_id: int, message: str, view: View | None = None):
    channel = client.get_channel(channel_id)

    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except Exception as e:
            print(f"Failed to fetch/send message: {e}")
            return

    if view:
        await channel.send(message, view=view)
    else:
        await channel.send(message)


# ----------------------- Helpers ----------------------------------
# -------------- Django ORM Helpers ---------------
@sync_to_async
def get_guild_projects(guild_id: int):
    return list(
        DiscordGuild.objects
        .filter(id=guild_id)
        .values_list('bot_integrations__project_id', 'bot_integrations__project__name')
    )


@sync_to_async
def get_project_by_id(project_id: int):
    from projects.models import Project
    return Project.objects.get(id=project_id)


@sync_to_async
@transaction.atomic
def save_setup(guild_id: int, project_id: int, channel_id: int):
    guild, _ = DiscordGuild.objects.get_or_create(id=guild_id)

    integration = guild.bot_integrations.select_for_update().filter(
        project_id=project_id
    ).first()

    if not integration:
        integration = guild.bot_integrations.create(project_id=project_id)

    integration.channel_id = channel_id
    integration.save()


@sync_to_async
def get_projects_for_autocomplete(guild_id: int, current: str):
    return list(
        DiscordGuild.objects
        .filter(id=guild_id)
        .filter(
            Q(bot_integrations__project__name__icontains=current)
        )
        .values_list(
            'bot_integrations__project__name',
            'bot_integrations__project_id'
        )
        .distinct()[:25]
    )


@sync_to_async
def get_pending_notifications():
    return list(
        Notification.objects.filter(
            is_sent=False,
            bot_integration__channel_id__isnull=False
        )
        .order_by('timestamp')[:30]
        .values('message', 'bot_integration__channel_id', 'id')
    )


@sync_to_async
def mark_notifications_as_sent(notification_ids: list[int]):
    Notification.objects.filter(id__in=notification_ids).update(is_sent=True)


@sync_to_async
def create_installation_state(guild_id: int):
    guild = DiscordGuild.objects.get_or_create(id=guild_id)[0]
    state = InstallationState.objects.create(guild=guild)
    return state.id

# -------------- Autocomplete Helper ---------------
async def project_autocomplete(interaction: Interaction, current: str):
    projects = await get_projects_for_autocomplete(interaction.guild_id, current)

    return [
        app_commands.Choice(name=name, value=str(project_id))
        for name, project_id in projects
    ][:25]


# ------------- UI Helper -------------------------
def setup_button_view(state_id: UUID):
    button = Button(label="Link Guild", url=f"https://www.scrumb.in/discord-connect/{state_id}")
    view = View()
    view.add_item(button)
    return view


# ----------------------- Check Notifications ----------------------
@tasks.loop(seconds=5)
async def send_pending_notifications():
    sent_notification_ids = []
    notifications = await get_pending_notifications()
    for notification in notifications:
        try:
            await send_message(notification["bot_integration__channel_id"], notification["message"])
            sent_notification_ids.append(notification["id"])
        except Exception as e:
            print(f"Failed to send notification: {e}")

    await mark_notifications_as_sent(sent_notification_ids)


# ----------------------- Commands ----------------------------------
@tree.command(name="setup", description="Setup the bot")
@app_commands.autocomplete(project=project_autocomplete)
async def setup(interaction: Interaction, channel: TextChannel, project: str | None = None):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True
        )
        return

    temp_projects = await get_projects_for_autocomplete(interaction.guild_id, "")
    if not temp_projects:
        await interaction.response.send_message(
            "⚠️ This server is not linked to any project yet.\nClick below to connect it.", ephemeral=True, view=setup_button_view(await create_installation_state(interaction.guild_id))
        )
        return

    me = interaction.guild.me or interaction.client.user
    if not channel.permissions_for(me).send_messages:
        await interaction.response.send_message(
            "I don't have permission to send messages in that channel.",
            ephemeral=True
        )
        return

    projects = await get_guild_projects(interaction.guild_id)

    if not projects:
        await interaction.response.send_message(
            "You don't have any projects.", ephemeral=True
        )
        return

    if len(projects) == 1:
        project_id, project_name = projects[0]

    else:
        if project is None:
            await interaction.response.send_message(
                "Select a project using autocomplete.",
                ephemeral=True
            )
            return

        project_id = int(project)

        match = next((p for p in projects if p[0] == project_id), None)
        if not match:
            await interaction.response.send_message(
                "Invalid project selected.",
                ephemeral=True
            )
            return

        project_id, project_name = match

    await save_setup(interaction.guild_id, project_id, channel.id)

    await interaction.response.send_message(
        f"Setup complete for **{project_name}** in {channel.mention}.",
        ephemeral=True
    )


# ----------------------- Logs ----------------------------------
@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")

    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Sync failed: {e}")

    if not send_pending_notifications.is_running():
        send_pending_notifications.start()


@client.event
async def on_guild_join(guild: Guild):
    print(f"Joined guild: {guild.name} (ID: {guild.id})")
    try:
        send_channel = guild.system_channel
        if not send_channel:
            print("No system channel found, fetching channels...")
            channels = await guild.fetch_channels()
            send_channel = None
            for channel in channels:
                if channel.permissions_for(guild.me).send_messages:
                    send_channel = channel
                    break
        if send_channel:
            state_id = await create_installation_state(guild.id)
            view = setup_button_view(state_id)
            await send_message(send_channel.id, "Thanks for adding me! Click the link below to link this server to your Scrumb projects.", view=view)
    except Exception as e:
        print(f"Failed to fetch channels: {e} {str(e.__traceback__.tb_lineno)}")


client.run(settings.DISCORD_BOT_TOKEN)
