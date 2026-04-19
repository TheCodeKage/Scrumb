from django.conf import settings
from rest_framework import viewsets
from rest_framework.decorators import action

from Github.logic import safe_sync
from api_responses import success_response, error_response
from projects.models import Project


def _build_github_app_installation_link(project_id=None):
    if project_id is not None:
        return f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={project_id}"
    else:
        return f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new"


# Create your views here.


class InstallationViewSet(viewsets.ViewSet):
    permission_classes = []

    @action(detail=False, methods=['get'])
    def install(self, request, pk=None):
        return success_response(
            message="Installation link created successfully.",
            data={"install_url": _build_github_app_installation_link(request.query_params.get('project_id'))},
        )

    @action(detail=False, methods=['get'])
    def setup(self, request):
        installation_id = request.GET.get('installation_id')
        project_id = request.GET.get('state')  # optional but recommended

        if not installation_id:
            return error_response("Missing installation_id")

        try:
            installation_id = int(installation_id)
        except ValueError:
            return error_response("Invalid installation_id")

        if project_id is not None:
            project = Project.objects.filter(id=project_id).first()
            if project:
                project.installation_id = installation_id
                project.save()

        # prevent duplicate sync spam
        safe_sync(installation_id)

        return success_response(
            message="GitHub installation connected successfully.",
            data={
                "installation_id": installation_id,
                "project_id": project_id
            }
        )


class EventsViewSet(viewsets.ViewSet):
    permission_classes = []

    @action(detail=False, methods=['post'])
    def push(self, request):
        print(request.data)
        return success_response("hi")
