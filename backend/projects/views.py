from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from Users.models import Team, Membership
from AI.api_caller import generate_tasks, get_panic_recommendations, shame_team, check_description
from mixins import ActionPermissionMixin
from .logic import save_tasks, cut_tasks, calculate_health, calculate_target_cut, get_team_shame_data, add_questions
from .models import Project, Task, ArchitectQuestion
from .permissions import IsTeamLeader
from .serializers import TaskSerializer, ProjectSerializer, QuestionSerializer


# Create your views here.
class ProjectViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    serializer_class = ProjectSerializer

    permission_map = {
        'generate_plan': [IsTeamLeader],
        'panic_mode': [IsTeamLeader],
        'destroy': [IsTeamLeader],
    }

    def get_queryset(self):
        return Project.objects.filter(team__members=self.request.user.developer).prefetch_related('tasks__subtasks', 'tasks__depends_on')

    def perform_create(self, serializer):
        team_id = self.request.data.get('team_id')

        if not team_id:
            raise serializers.ValidationError({"team_id": "This field is required."})
        if not Team.objects.filter(id=team_id, members=self.request.user.developer, members__memberships__role=Membership.Role.LEADER).exists():
            raise serializers.ValidationError({"team_id": "Invalid team ID."})

        team = Team.objects.get(id=team_id)

        # 1. Save the project first
        project = serializer.save(team=team)
        audit_data = check_description(project)


        if audit_data.get("is_detailed"):
            project.is_detailed = True
            project.save(update_fields=["is_detailed"])
        else:
            add_questions(project, audit_data.get("questions", []))

        project.save()




    @action(detail=True, methods=['post'])
    def generate_plan(self, request, pk=None):
        project = self.get_object()

        if project.tasks.exists(): return Response({"error": "Plan has already been generated"}, status=400)

        # Ensure every question has exactly one 'is_selected=True' option
        if project.questions.filter(options__is_selected=True).distinct().count() < project.questions.count():
            return Response({"error": "You haven't answered all the Architect's questions yet."}, status=400)

        # Flip the switch: The project is now detailed enough because the user chose the MCQs
        project.is_detailed = True
        project.save(update_fields=['is_detailed'])

        tasks_data = generate_tasks(project)
        save_tasks(tasks_data, project)
        return Response({"status": "Plan Generated"})

    @action(detail=True, methods=['post'])
    def panic_mode(self, request, pk=None):
        project = self.get_object()
        count_old, count_new, imp_old, imp_new = (
            cut_tasks(
                get_panic_recommendations(project, calculate_target_cut(project)),
                project
            )
        )

        return Response({
            "no_of_tasks_before": count_old,
            "no_of_tasks_after": count_new,
            "total_importance_before": imp_old,
            "total_importance_after": imp_new,
        })

    @action(detail=True, methods=['get'])
    def health(self, request, pk=None):
        project = self.get_object()

        status, velocity, distance, target_cut = calculate_health(project)

        if not velocity: return "N/A (no history yet)"

        return Response({
            "project_name": project.name,
            "status": status,
            "completion_percentage": project.completion_percentage,
            "daily_velocity": velocity,
            "current_panic_requirement": f"{target_cut}% scope cut needed",
            "days_until_guarantee": (project.guarantee_date - timezone.now().date()).days,
            "expected_complete_by": f"{round(distance/velocity)} days",
        })

    @action(detail=True, methods=['get'])
    def team_shame(self, request, pk=None):
        project = self.get_object()
        shame_data, team_data = get_team_shame_data(project)
        return Response(
            shame_team(shame_data, team_data)
        )

    @action(detail=True, methods=['get'])
    def interview(self, request, pk=None):
        project = self.get_object()

        # If Gemini is still thinking (Audit phase), tell the IDE to wait
        if not project.is_detailed and not project.questions.exists():
            return Response({"status": "AUDITING", "message": "Architect is reviewing..."})

        # Return the questions so Sohal can render the MCQs
        serializer = QuestionSerializer(project.questions.all(), many=True)
        return Response({
            "status": "INTERVIEWING",
            "questions": serializer.data
        })


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return Task.objects.filter(project__team__members=self.request.user.developer).prefetch_related('subtasks', 'depends_on')

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


class QuestionViewSet(viewsets.GenericViewSet, viewsets.mixins.ListModelMixin, viewsets.mixins.UpdateModelMixin):
    serializer_class = QuestionSerializer

    def get_queryset(self):
        return ArchitectQuestion.objects.filter(project__team__members=self.request.user.developer).prefetch_related('options')

    def perform_update(self, serializer):
        selected_option_id = self.request.data.get('selected_option_id')
        question: ArchitectQuestion = self.get_object()

        if not question.project.team.is_leader(self.request.user.developer):
            return Response({"error": "Only the team leader can answer the Architect's questions."}, status=403)

        try:
            selected_option_id = int(selected_option_id)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Invalid Option ID for this question.")

        if selected_option_id:
            with transaction.atomic():
                # 1. Ensure the option actually belongs to this question (Security)
                option_to_select = question.options.filter(id=selected_option_id)

                if not option_to_select.exists():
                    raise serializers.ValidationError("Invalid Option ID for this question.")

                # 2. Reset all and select the new one
                question.options.all().update(is_selected=False)
                option_to_select.update(is_selected=True)

        # 3. Save the serializer to trigger any other signals/logic
        serializer.save()

        # 4. CRITICAL: Refresh the object from DB so the response shows the new state
        question.refresh_from_db()

def healthz(request):
    return JsonResponse({
        "status": "healthy",
        "service": "scrumb-backend"
    })
