from rest_framework import serializers

from .logic import calculate_health
from .models import Project, Task, ArchitectQuestion, Option


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


class QuestionSerializer(serializers.ModelSerializer):
    class OptionSerializer(serializers.ModelSerializer):
        class Meta:
            model = Option
            fields = ['id', 'text', 'is_selected', 'is_recommended']
            read_only_fields = ('id', 'text', 'is_recommended')


    options = OptionSerializer(many=True)
    class Meta:
        model = ArchitectQuestion
        fields = [
            'id',
            'text',
            'options'
        ]
        # Only 'answer' should be writeable by the user/IDE
        read_only_fields = ('id', 'text')


class ProjectSerializer(serializers.ModelSerializer):
    tasks = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()
    health = serializers.SerializerMethodField()

    class Meta:
        model = Project
        read_only_fields = ('is_detailed',)
        fields = ['id', 'name', 'description', 'guarantee_date', "team", 'tasks', 'completion_percentage', 'health', 'is_detailed', 'questions']

    def get_tasks(self, project):
        root_tasks = project.tasks.filter(parent_task__isnull=True)
        return TaskSerializer(root_tasks, many=True).data

    def get_questions(self, project):
        questions = project.questions.all()
        return QuestionSerializer(questions, many=True).data

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