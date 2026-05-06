import hashlib
import hmac

from django.conf import settings
from rest_framework import viewsets
from rest_framework.decorators import action

from projects.models import Project
from services.AI.api_caller import process_github_push
from services.api_responses import success_response, error_response


class InstallationViewSet(viewsets.ViewSet):
    permission_classes = []

    @action(detail=False, methods=['get'])
    def setup(self, request):
        installation_id = request.GET.get('installation_id')

        if not installation_id:
            return error_response("Missing installation_id")

        try:
            installation_id = int(installation_id)
        except ValueError:
            return error_response("Invalid installation_id")

        return success_response(
            message="GitHub installation connected successfully.",
            data={
                "installation_id": installation_id,
            }
        )


def _verify_github_signature(request) -> bool:
    """
    Verify GitHub webhook signature using X-Hub-Signature-256.

    GitHub sends:
        X-Hub-Signature-256: sha256=<hexdigest>

    We compute the HMAC using the raw body and compare securely.
    """
    secret = getattr(settings, "GITHUB_WEBHOOK_SECRET", None)
    if not secret:
        return False

    signature = request.headers.get("X-Hub-Signature-256")
    if not signature or not signature.startswith("sha256="):
        return False

    raw_body = request.body  # must be raw bytes, not request.data
    expected_signature = "sha256=" + hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)


def _verify_github_event(request, expected_event: str = "push") -> bool:
    """
    Verify the GitHub event type sent in the X-GitHub-Event header.

    Example:
        X-GitHub-Event: push
    """
    event = request.headers.get("X-GitHub-Event")
    return event == expected_event



class EventsViewSet(viewsets.ViewSet):
    permission_classes = []

    @action(detail=False, methods=['post'])
    def push(self, request):
        if not _verify_github_signature(request):
            return error_response("Invalid GitHub signature")

        if not _verify_github_event(request, "push"):
            return error_response("Unsupported GitHub event")

        print(request.data)
        process_github_push(Project.objects.filter(github_installation_id=request.data["installation_id"]).first(), request.data)
        return success_response("hi")
