# View to link discord guild object with projects, check login user is leader for projects selected
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from bot_integrations.logic import process_cron_jobs, add_cron_job
from bot_integrations.models import DiscordGuild, InstallationState, DiscordBotIntegration, Notification, CronSchedule
from projects.models import Project
from users.models import Membership
from services.api_responses import success_response, error_response


class HasAPIKeyHeader(BasePermission):
    def has_permission(self, request, view):
        api_key = request.headers.get("X-API-KEY")  # or whatever header name

        return api_key == settings.DISCORD_API_KEY


class HasCronJobAPIKeyHeader(BasePermission):
    def has_permission(self, request, view):
        api_key = request.headers.get("X-CRON-API-KEY")

        return api_key == settings.CRON_JOB_API_KEY


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


class DiscordBotViews(ViewSet):
    permission_classes = (HasAPIKeyHeader,)
    http_method_names = ["get", "post"]

    @action(detail=False, methods=['get'])
    def get_guild_projects(self, request, *args, **kwargs):
        guild_id = request.query_params.get('guild_id')
        if not guild_id:
            return error_response("Guild ID is required")

        try:
            projects = list(
                DiscordGuild.objects
                .filter(id=guild_id)
                .values_list('bot_integrations__project_id', 'bot_integrations__project__name')
            )
        except DiscordGuild.DoesNotExist:
            return error_response("Guild not found")
        except Exception as e:
            print(e)
            return error_response("An unknown error occurred while fetching projects")

        return success_response("Projects Fetched Successfully", data=projects)

    @action(detail=False, methods=['post'])
    def save_setup(self, request, *args, **kwargs):
        guild_id = request.data.get('guild_id')
        project_id = request.data.get('project_id')
        channel_id = request.data.get('channel_id')

        if not guild_id:
            return error_response("Guild ID is required")
        if not project_id:
            return error_response("Project ID is required")
        if not channel_id:
            return error_response("Channel ID is required")

        guild, _ = DiscordGuild.objects.get_or_create(id=guild_id)

        with transaction.atomic():
            integration = guild.bot_integrations.select_for_update().filter(
                project_id=project_id
            ).select_related('project').first()

            if not integration:
                integration = guild.bot_integrations.create(project_id=project_id)

            integration.channel_id = channel_id
            integration.save()

        try:
            add_cron_job(integration.project)
            msg = "Setup saved successfully"
        except Exception as e:
            msg = "Setup saved successfully, However, an error occurred while adding automatic project updates. Please contact support."
            print(e)

        return success_response(msg)

    @action(detail=False, methods=['get'])
    def get_projects_for_autocomplete(self, request, *args, **kwargs):
        guild_id = request.query_params.get('guild_id')
        current = request.query_params.get('current')

        if not guild_id:
            return error_response("Guild ID is required")

        projects = list(
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

        return success_response("Projects fetched successfully", data=projects)

    @action(detail=False, methods=['get'])
    def get_pending_notifications(self, request, *args, **kwargs):
        notifications = list(
            Notification.objects.filter(
                is_sent=False,
                bot_integration__channel_id__isnull=False
            )
            .order_by('timestamp')[:30]
            .values('message', 'bot_integration__channel_id', 'id')
        )
        return success_response("Notifications fetched successfully", data=notifications)

    @action(detail=False, methods=['post'])
    def mark_notifications_as_sent(self, request, *args, **kwargs):
        notification_ids = request.data.get('notification_ids')
        if not notification_ids:
            return success_response("No notification IDs provided")

        with transaction.atomic():
            Notification.objects.filter(id__in=notification_ids).update(is_sent=True)
        return success_response("Notifications marked as sent successfully")

    @action(detail=False, methods=['post'])
    def create_installation_state(self, request, *args, **kwargs):
        guild_id = request.data.get('guild_id')
        if not guild_id:
            return error_response("Guild ID is required")

        guild, _ = DiscordGuild.objects.get_or_create(id=guild_id)
        state = InstallationState.objects.create(guild=guild)
        return success_response("Installation state created successfully", data={"state_id": state.id})


class CronJobViews(ViewSet):
    permission_classes = (HasCronJobAPIKeyHeader,)
    http_method_names = ["get", "post"]

    # method to calculate time for sending message, getting and compiling all analytics, and sending messages of current batch
    @action(detail=False, methods=['get'])
    def cron_job(self, request, *args, **kwargs):
        process_cron_jobs()
        return success_response("Cron jobs processed successfully")

    @action(detail=False, methods=['get'])
    def reset_weekly_cron_schedule(self, request, *args, **kwargs):
        CronSchedule.reset_weekly_schedules()
        return success_response("Weekly cron schedules reset successfully")

    @action(detail=False, methods=['get'])
    def reset_daily_cron_schedule(self, request, *args, **kwargs):
        CronSchedule.reset_daily_schedules()
        return success_response("Daily cron schedules reset successfully")
