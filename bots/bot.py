from __future__ import annotations

import atexit

from typing import TYPE_CHECKING
import httpx
from discord import Client, app_commands
from discord import Interaction, TextChannel
from discord.client import Intents
from discord.ext import tasks
from discord.ui import Button, View
from dotenv import load_dotenv
import os

if TYPE_CHECKING:
    from discord import Guild
    from uuid import UUID

load_dotenv()

client = Client(intents=Intents.default())
tree = app_commands.CommandTree(client)
api_key = os.getenv("API_KEY")
BASE_URL = "https://apiv2.scrumb.in"

headers = {"X-API-KEY": api_key}
client_http = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5, read=10, write=10))


def build_action_view(actions):
    if not actions:
        return None

    view = View(timeout=None)

    for action in actions:
        label = (
            "✂️ Cut Tasks" if action["action_type"] == "cut_tasks"
            else "⏳ Delay Deadline"
        )

        button = Button(
            label=label,
            style=1,  # primary
            custom_id=str(action["id"])  # IMPORTANT
        )

        view.add_item(button)

    return view


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
# -------------- HTTP Helpers ---------------
async def async_get(url: str, params=None):
    try:
        response = await client_http.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"GET request failed: {e}")
        return None


async def async_post(url: str, json=None):
    try:
        response = await client_http.post(url, headers=headers, json=json)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"POST request failed: {e}")
        return None


@atexit.register
def close_http():
    import asyncio
    try:
        asyncio.run(client_http.aclose())
    except:
        pass


# -------------- Django ORM Helpers ---------------
async def get_guild_projects(guild_id: int):
    data = await async_get(
        f"{BASE_URL}/discord/get_guild_projects/",
        params={"guild_id": guild_id}
    )
    return data["data"] if data else []


async def save_setup(guild_id: int, project_id: int, channel_id: int):
    await async_post(
        f"{BASE_URL}/discord/save_setup/",
        json={
            "guild_id": guild_id,
            "project_id": project_id,
            "channel_id": channel_id
        }
    )


async def get_projects_for_autocomplete(guild_id: int, current: str):
    data = await async_get(
        f"{BASE_URL}/discord/get_projects_for_autocomplete/",
        params={"guild_id": guild_id, "current": current}
    )
    return data["data"] if data else []


async def get_pending_notifications():
    data = await async_get(
        f"{BASE_URL}/discord/get_pending_notifications/"
    )
    return data["data"] if data else []


async def mark_notifications_as_sent(notification_ids: list[int]):
    await async_post(
        f"{BASE_URL}/discord/mark_notifications_as_sent/",
        json={"notification_ids": notification_ids}
    )


async def create_installation_state(guild_id: int):
    data = await async_post(
        f"{BASE_URL}/discord/create_installation_state/",
        json={"guild_id": guild_id}
    )
    return data["data"]["state_id"] if data else None


# -------------- Autocomplete Helper ---------------
async def project_autocomplete(interaction: Interaction, current: str):
    projects = await get_projects_for_autocomplete(interaction.guild_id, current)

    return [
        app_commands.Choice(name=name, value=str(project_id))
        for name, project_id in projects
    ][:25]


# ------------- UI Helper -------------------------
def setup_button_view(state_id: UUID):
    button = Button(label="Link Guild", url=f"https://www.scrumb.in/discord-connect?guild_id={state_id}")
    view = View()
    view.add_item(button)
    return view


# ----------------------- Check Notifications ----------------------
@tasks.loop(minutes=10.0)
async def send_pending_notifications():
    sent_notification_ids = []
    notifications = await get_pending_notifications()
    for notification in notifications:
        try:
            view = build_action_view(notification.get("actions"))

            await send_message(
                notification["bot_integration__channel_id"],
                notification["message"],
                view=view
            )
            sent_notification_ids.append(notification["id"])
        except Exception as e:
            print(f"Failed to send notification: {e}")

    await mark_notifications_as_sent(sent_notification_ids)


# ----------------------- Commands ----------------------------------
@tree.command(name="setup", description="Setup the bot")
@app_commands.autocomplete(project=project_autocomplete)
async def setup(interaction: Interaction, channel: TextChannel, project: str | None = None):
    await interaction.response.defer(ephemeral=True)

    if interaction.guild_id is None:
        await interaction.followup.send(
            "This command can only be used in a server.",
            ephemeral=True
        )
        return

    temp_projects = await get_projects_for_autocomplete(interaction.guild_id, "")
    if not temp_projects:
        await interaction.followup.send(
            "⚠️ This server is not linked to any project yet.",
            ephemeral=True
        )
        return

    me = interaction.guild.me or interaction.client.user
    if not channel.permissions_for(me).send_messages:
        await interaction.followup.send(
            "I don't have permission to send messages in that channel.",
            ephemeral=True
        )
        return

    projects = await get_guild_projects(interaction.guild_id)

    if not projects:
        await interaction.followup.send(
            "You don't have any projects.", ephemeral=True
        )
        return

    if len(projects) == 1:
        project_id, project_name = projects[0]

    else:
        if project is None:
            await interaction.followup.send(
                "Select a project using autocomplete.",
                ephemeral=True
            )
            return

        project_id = int(project)

        match = next((p for p in projects if p[0] == project_id), None)
        if not match:
            await interaction.followup.send(
                "Invalid project selected.",
                ephemeral=True
            )
            return

        project_id, project_name = match

    await save_setup(interaction.guild_id, project_id, channel.id)

    await interaction.followup.send(
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
            await send_message(send_channel.id,
                               "Thanks for adding me! Click the link below to link this server to your Scrumb projects.",
                               view=view)
    except Exception as e:
        print(f"Failed to fetch channels: {e} {str(e.__traceback__.tb_lineno)}")


@client.event
async def on_interaction(interaction: Interaction):
    if not interaction.type.name == "component":
        return

    button_id = interaction.data.get("custom_id")

    if not button_id:
        return

    # Call backend
    res = await async_post(
        f"{BASE_URL}/discord/process_button_click/",
        json={"id": button_id}
    )

    if res and res.get("success"):
        await interaction.response.send_message(
            "✅ Action executed successfully.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ Failed or already processed.",
            ephemeral=True
        )


client.run(os.getenv("DISCORD_BOT_TOKEN"))
