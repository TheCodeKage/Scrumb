from rest_framework import serializers

from .logic import calculate_health
from .models import Project, Task


class TaskSerializer(serializers.ModelSerializer):
    sub_tasks = serializers.SerializerMethodField()
    blocking_tasks = serializers.SerializerMethodField()
    is_blocked = serializers.ReadOnlyField()

    class Meta:
        model = Task
        fields = [
            'id', 'parent_task', 'title', 'status', 'importance',
            'phase_label', 'sub_tasks', 'owner',
            'is_blocked', 'blocking_tasks'
        ]


    def get_sub_tasks(self, task):
        # Optimization: Use the related_name 'subtasks' defined in your model
        return TaskSerializer(task.subtasks.all(), many=True).data

    def get_blocking_tasks(self, task):
        # Return a simple list of titles/IDs that are stopping this task
        return task.depends_on.exclude(status='done').values('id', 'title')

    def validate_status(self, value):
        if value == 'done' and self.instance:
            # 1. Vertical Check: Sub-tasks
            if self.instance.subtasks.exclude(status='done').exists():
                raise serializers.ValidationError(
                    "Cannot mark as done: sub-tasks are incomplete."
                )

            # 2. Horizontal Check: Dependencies (depends_on)
            if self.instance.is_blocked:
                raise serializers.ValidationError(
                    "Cannot mark as done: horizontal dependencies are incomplete."
                )

        return value


class ProjectSerializer(serializers.ModelSerializer):
    tasks = serializers.SerializerMethodField()
    health = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'guarantee_date', "team", 'tasks', 'completion_percentage', 'health']

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