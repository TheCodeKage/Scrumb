from django.http import JsonResponse
from rest_framework import viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Project, Task
from .serializers import TaskSerializer, ProjectSerializer
from api_caller import generate_tasks, get_panic_recommendations


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

        def save_tasks(data, parent=None):
            for task in data:
                t = Task.objects.create(
                    project=project,
                    parent_task=parent,
                    title=task['title'],
                    importance=task['importance'],
                    phase_label=task['phase_label'],
                    status='to-do',
                )
                t.save()
                if (((name:='subtasks') in task) and task['subtasks']) or (((name:='sub_tasks') in task) and task['sub_tasks']):
                    save_tasks(task[name], parent=t)

        save_tasks(tasks_data)
        print(tasks_data)
        return Response({"status": "Plan Generated and Tasks Created"})

    @action(detail=True, methods=['post'])
    def panic_mode(self, request, pk=None):
        project = self.get_object()

        tasks_to_cut = Task.objects.filter(
            id__in=
                get_panic_recommendations(
                    project,
                    project.completion_percentage
                )
        )

        for i in tasks_to_cut:
            i.archive_recursive(reason="Panic Mode: Strategic Scope Cut")

        count = tasks_to_cut.count()
        for task in tasks_to_cut:
            task.status = 'archived'
            task.save()  # This triggers your signal!

            # We manually update the reason for the signal-created history entry
            last_history = task.history.first()
            if last_history:
                last_history.change_reason = "Panic Mode: Automated scope reduction."
                last_history.save()

        return Response({"message": f"Panic Mode Activated. {count} tasks archived."})


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
