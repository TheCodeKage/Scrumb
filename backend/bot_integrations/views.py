# View to link discord guild object with projects, check login user is leader for projects selected
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from bot_integrations.models import DiscordGuild, InstallationState, DiscordBotIntegration
from projects.models import Project
from users.models import Membership
from services.api_responses import success_response, error_response


class LinkDiscordView(APIView):
    permission_classes = (IsAuthenticated,)
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        developer = request.user.developer

        projects = request.data.get("project_ids") or []
        if not isinstance(projects, list):
            projects = [projects]

        try:
            projects = list(set(int(p) for p in projects))
        except (TypeError, ValueError) as e:
            print(e)
            return error_response("project_ids must be a list of integers")

        if not projects:
            return error_response("project_ids cannot be empty")

        installation_id = request.data.get("guild_id")
        if not installation_id:
            return error_response("Guild ID is required")

        installation_state = InstallationState.objects.select_related("guild").filter(id=installation_id).first()
        if not installation_state:
            print("InstallationState not found for ID: ", installation_id, "")
            return error_response("Guild not found")

        guild = installation_state.guild

        qs = Project.objects.filter(
            id__in=projects,
            team__memberships__developer=developer,
            team__memberships__role=Membership.Role.LEADER
        )

        valid_project_ids = set(qs.values_list("id", flat=True))

        if valid_project_ids != set(projects):
            print("Invalid project IDs: ", set(projects) - valid_project_ids)
            return error_response("Some projects were invalid or unauthorized")

        # 🔥 1. Update existing integrations
        DiscordBotIntegration.objects.filter(
            project_id__in=valid_project_ids
        ).update(discord_guild=guild)

        # 🔥 2. Find missing ones
        existing_ids = set(
            DiscordBotIntegration.objects.filter(project_id__in=valid_project_ids)
            .values_list("project_id", flat=True)
        )

        missing_ids = valid_project_ids - existing_ids

        # 🔥 3. Bulk create missing
        new_integrations = [
            DiscordBotIntegration(project_id=pid, discord_guild=guild)
            for pid in missing_ids
        ]

        DiscordBotIntegration.objects.bulk_create(new_integrations)

        return success_response("Projects linked successfully")