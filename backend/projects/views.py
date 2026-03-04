from django.http import JsonResponse
from django.utils import timezone
from rest_framework import viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from api_caller import generate_tasks, get_panic_recommendations
from .logic import save_tasks, cut_tasks, calculate_health, calculate_target_cut
from .models import Project, Task
from .serializers import TaskSerializer, ProjectSerializer


# Create your views here.
class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    @action(detail=True, methods=['post'])
    def generate_plan(self, request, pk=None):
        project = self.get_object()

        if Task.objects.filter(project=project).exists():
            return Response({"error": "Plan already exists!"}, status=400)

        tasks_data = generate_tasks(project.name, project.description)

        save_tasks(tasks_data, project)
        return Response({"status": "Plan Generated and Tasks Created"})

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

        return Response({
            "project_name": project.name,
            "status": status,
            "completion_percentage": project.completion_percentage,
            "daily_velocity": velocity,
            "current_panic_requirement": f"{target_cut}% scope cut needed",
            "days_until_guarantee": (project.guarantee_date - timezone.now().date()).days,
            "expected_complete_by": f"{round(distance/velocity)} days",
        })


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def perform_update(self, serializer):
        instance = self.get_object()
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


def healthz(request):
    return JsonResponse({
        "status": "healthy",
        "service": "scrumb-backend"
    })
