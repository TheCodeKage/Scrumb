from rest_framework import serializers

from .models import Project, Task


class TaskSerializer(serializers.ModelSerializer):
    sub_tasks = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id',
            'parent_task', # The ID of the parent
            'title',
            'status',
            'importance',
            'phase_label',
            'sub_tasks'
        ]


    def get_sub_tasks(self, task):
        child_tasks = Task.objects.filter(parent_task=task)
        return TaskSerializer(child_tasks, many=True).data


class ProjectSerializer(serializers.ModelSerializer):
    tasks = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'tasks']

    def get_tasks(self, project):
        root_tasks = project.tasks.filter(parent_task__isnull=True)
        return TaskSerializer(root_tasks, many=True).data