from rest_framework import serializers

from .logic import calculate_health
from .models import Project, Task


class TaskSerializer(serializers.ModelSerializer):
    sub_tasks = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id',
            'parent_task',
            'title',
            'status',
            'importance',
            'phase_label',
            'sub_tasks'
        ]


    def get_sub_tasks(self, task):
        child_tasks = Task.objects.filter(parent_task=task)
        return TaskSerializer(child_tasks, many=True).data

    def validate_status(self, value):
        if value == 'done' and self.instance:
            has_incomplete = Task.objects.filter(
                parent_task=self.instance
            ).exclude(status='done').exists()

            if has_incomplete:
                raise serializers.ValidationError(
                    "Cannot mark as done: some sub-tasks are still incomplete."
                )

        return value


class ProjectSerializer(serializers.ModelSerializer):
    tasks = serializers.SerializerMethodField()
    health = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'guarantee_date','tasks', 'completion_percentage', 'health']

    def get_tasks(self, project):
        root_tasks = project.tasks.filter(parent_task__isnull=True)
        return TaskSerializer(root_tasks, many=True).data

    def get_health(self, project):
        status, velocity, distance, target_cut = calculate_health(project)
        time = velocity and round(distance/velocity)
        health = {
            "status": status,
            "daily_velocity": velocity,
            "current_panic_requirement": f"{target_cut}% scope cut needed",
            "expected_complete_in": f"{time} days",
        }
        return health