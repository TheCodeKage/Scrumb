from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Project, Task
from .serializers import TaskSerializer, ProjectSerializer
from api_caller import generate_tasks

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


def healthz(request):
    return JsonResponse({
        "status": "healthy",
        "service": "scrumb-backend"
    })
