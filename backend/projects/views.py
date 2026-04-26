import logging

from django.db import transaction
from django.http import JsonResponse
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from services.AI.api_caller import generate_tasks, get_panic_recommendations, check_description
from services.api_responses import success_response, error_response
from users.models import Team, Membership
from . import analytics
from .logic import save_tasks, cut_tasks, calculate_target_cut, add_questions, \
    select_option_for_question
from .models import Project, Task, ArchitectQuestion, ProjectSettings
from .permissions import IsTeamLeader
from .serializers import TaskSerializer, ProjectSerializer, QuestionSerializer, ProjectSettingsSerializer

logger = logging.getLogger(__name__)


# Create your views here.


class ProjectBaseViewSet(viewsets.GenericViewSet):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        if self.request.query_params.get('is_leader', 'false').lower() == 'true':
            return (Project.objects.filter(team__members=self.request.user.developer,
                                           team__memberships__role=Membership.Role.LEADER)
                    .select_related('team')
                    .prefetch_related('tasks__depends_on', 'tasks__subtasks'))
        return (Project.objects.filter(team__members=self.request.user.developer)
                .select_related('team')
                .prefetch_related('tasks__depends_on', 'tasks__subtasks'))


class ProjectViewSet(ProjectBaseViewSet, viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action == 'destroy':
            return [IsTeamLeader()]
        return super().get_permissions()

    def perform_create(self, serializer):
        team_id = self.request.data.get('team_id')

        if not team_id:
            raise serializers.ValidationError({"team_id": "This field is required."})

        team = Team.objects.filter(
            id=team_id,
            members=self.request.user.developer,
            members__memberships__role=Membership.Role.LEADER
        ).first()

        if not team:
            raise serializers.ValidationError({"team_id": "Invalid team ID."})

        # 1. Save the project first
        project = serializer.save(team=team)
        audit_data = check_description(project)

        if audit_data.get("is_detailed"):
            project.is_detailed = True
            project.save(update_fields=["is_detailed"])
        else:
            add_questions(project, audit_data.get("questions", []))

    @action(detail=True, methods=["get", "patch"], url_path="settings", url_name="settings")
    def project_settings(self, request, pk=None):
        project = self.get_object()

        obj, _ = ProjectSettings.objects.get_or_create(project=project)

        if request.method == "GET":
            serializer = ProjectSettingsSerializer(obj)
            return Response(serializer.data)

        serializer = ProjectSettingsSerializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProjectPlanningViewSet(ProjectBaseViewSet):
    permission_classes = [IsTeamLeader]

    @action(detail=True, methods=['post'])
    def generate_plan(self, request, pk=None):
        project = self.get_object()

        if project.tasks.exists():
            return error_response(
                message="Plan has already been generated",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # Ensure every question has exactly one 'is_selected=True' option
        if project.questions.filter(options__is_selected=True).distinct().count() < project.questions.count():
            return error_response(
                message="You have not answered all architect questions yet",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tasks_data = generate_tasks(project)
            save_tasks(tasks_data, project)
        except Exception:
            logger.exception("Failed to generate plan for project_id=%s", project.id)
            return error_response(
                message="Task plan generation is temporarily unavailable.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Mark the project detailed only after the plan has been generated and saved.
        project.is_detailed = True
        project.save(update_fields=['is_detailed'])
        return success_response(message="Plan generated")

    @action(detail=True, methods=['post'])
    def answer_all(self, request, pk=None):
        project = self.get_object()

        if project.is_detailed:
            return error_response(
                message="Plan has already been generated",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        questions = project.questions.all()

        if not questions.exists():
            return error_response(
                message="No questions found for this project",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        answers = request.data.get("answers", [])

        if not isinstance(answers, list):
            raise ValidationError("Answers must be a list.")

        question_map = {q.id: q for q in questions}

        with transaction.atomic():
            for item in answers:
                q_id = item.get("question_id")
                opt_id = item.get("selected_option_id")

                if q_id not in question_map:
                    raise ValidationError(f"Invalid question_id: {q_id}")

                select_option_for_question(question_map[q_id], opt_id)

        return success_response(message="All answers submitted successfully", status_code=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def interview(self, request, pk=None):
        project = self.get_object()

        # If Gemini is still thinking (Audit phase), tell the IDE to wait
        if not project.is_detailed and not project.questions.exists():
            return success_response(
                message="Architect is reviewing",
                data={"phase": "AUDITING"},
            )

        # Return the questions so Sohal can render the MCQs
        serializer = QuestionSerializer(project.questions.all(), many=True)
        return success_response(
            message="Architect questions fetched",
            data={
                "phase": "INTERVIEWING",
                "questions": serializer.data,
            },
        )


class ProjectAnalyticsViewSet(ProjectBaseViewSet):
    @action(detail=True, methods=['get'])
    def health(self, request, pk=None):
        project = self.get_object()
        health = analytics.health(project)
        if health is None:
            return success_response(message="No history yet", data={'daily_velocity': 'N/A'})
        return success_response(message="Project health fetched", data=health)

    @action(detail=True, methods=['get'])
    def stalled_tasks(self, request, pk=None):
        project = self.get_object()
        stalled_data = analytics.stalled_tasks(project)
        return success_response(message="Stalled tasks fetched", data=stalled_data)

    @action(detail=True, methods=['get'])
    def roast(self, request, pk=None):
        project = self.get_object()
        roast_data = analytics.roast(project)
        return success_response(message="Roast sent", data=roast_data)


class ProjectPanicViewSet(ProjectBaseViewSet):
    permission_classes = [IsTeamLeader]

    @action(detail=True, methods=['post'])
    def panic_previews(self, request, pk=None):
        project = self.get_object()
        return success_response(
            message="Panic previews generated",
            data=get_panic_recommendations(project, calculate_target_cut(project)),
        )

    @action(detail=True, methods=['post'])
    def panic_mode(self, request, pk=None):
        project = self.get_object()
        count_old, count_new, imp_old, imp_new = (
            cut_tasks(
                get_panic_recommendations(project, calculate_target_cut(project)),
                project
            )
        )

        return success_response(
            message="Panic mode applied",
            data={
                "no_of_tasks_before": count_old,
                "no_of_tasks_after": count_new,
                "total_importance_before": imp_old,
                "total_importance_after": imp_new,
            },
        )


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return Task.objects.filter(project__team__members=self.request.user.developer).prefetch_related('subtasks',
                                                                                                        'depends_on')

    def perform_update(self, serializer):
        instance = self.get_object()

        developer = self.request.user.developer
        if developer != instance.owner:
            raise serializers.ValidationError({"error": "You are not the owner of this task."})
        new_status = serializer.validated_data.get('status')

        # The Cheating Detector
        if new_status == 'done':
            # Check if any child tasks are NOT done
            has_unfinished_children = instance.subtasks.exclude(status='done').exists()

            if has_unfinished_children:
                # We stop the process here and send a 400 error
                raise serializers.ValidationError({
                    "shame_message": f"Execution Integrity Violation: '{instance.title}' cannot be finished while its sub-tasks are still pending."
                })

        serializer.save()


class QuestionViewSet(viewsets.GenericViewSet,
                      viewsets.mixins.ListModelMixin,
                      viewsets.mixins.RetrieveModelMixin):

    serializer_class = QuestionSerializer

    def get_queryset(self):
        queryset = ArchitectQuestion.objects.filter(
            project__team__members=self.request.user.developer
        ).prefetch_related('options')

        project_id = self.request.query_params.get("project")

        if project_id:
            try:
                project_id = int(project_id)
                queryset = queryset.filter(project_id=project_id)
            except (ValueError, TypeError):
                raise ValidationError("Invalid project ID.")

        return queryset

    @action(detail=True, methods=["post"])
    def select(self, request, pk=None):
        question = self.get_object()

        if not question.project.team.is_leader(request.user.developer):
            raise PermissionDenied("Only the team leader can answer the Architect's questions.")

        with transaction.atomic():
            select_option_for_question(question, request.data.get("selected_option_id"))

        question.refresh_from_db()
        return success_response(
            message="Option selected",
            data=self.get_serializer(question).data,
        )


@api_view(["GET", "HEAD"])
@permission_classes([AllowAny])
def healthz(request):
    return JsonResponse({
        "status": "healthy",
        "service": "scrumb-backend"
    })
