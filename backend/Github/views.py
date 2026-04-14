from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from projects.models import Project
from .logic import verify_github_signature, process_push_event


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def github_setup(request, project_id: int):
    project = Project.objects.filter(
        id=project_id,
        team__members=request.user.developer,
        team__memberships__role='leader',
        team__memberships__developer=request.user.developer,
    ).first()

    if not project:
        return Response(
            {"error": "Project not found or you are not the team leader."},
            status=404
        )

    install_url = (
        f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new"
        f"?state={project_id}"
    )

    # 🔥 Better: redirect instead of returning URL
    return HttpResponseRedirect(install_url)


@api_view(['GET'])
@permission_classes([AllowAny])  # GitHub calls this
def github_callback(request):
    installation_id = request.query_params.get("installation_id")
    project_id = request.query_params.get("state")

    if not installation_id or not project_id:
        return Response(
            {"error": "Missing installation_id or state"},
            status=400
        )

    try:
        project = Project.objects.get(id=int(project_id))
    except (Project.DoesNotExist, ValueError):
        return Response({"error": "Project not found"}, status=404)

    try:
        project.github_installation_id = int(installation_id)
    except ValueError:
        return Response({"error": "Invalid installation_id"}, status=400)

    project.save(update_fields=["github_installation_id"])

    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://www.scrumb.in')

    return HttpResponseRedirect(
        f"{frontend_url}/github-connected?project={project_id}"
    )


@api_view(['POST'])
@permission_classes([AllowAny])  # MUST be public
def github_webhook(request):
    # 1. Verify signature
    if not verify_github_signature(request):
        return Response({"error": "Invalid signature"}, status=401)

    event_type = request.headers.get("X-GitHub-Event", "")

    # 2. Ignore non-push events
    if event_type != "push":
        return Response({"status": "ignored", "event": event_type})

    payload = request.data  # DRF handles JSON parsing

    result = process_push_event(payload)

    return Response({"status": "processed", "result": result})
