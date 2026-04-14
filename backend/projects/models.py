from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum

from Users.models import Team, Developer


# Create your models here.
class Project(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    github_installation_id = models.BigIntegerField(null=True, blank=True)
    github_link = models.URLField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now=True)

    guarantee_date = models.DateField()
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, related_name='projects')

    is_detailed = models.BooleanField(default=False)

    def __str__(self):
        return self.name + self.guarantee_date.strftime("%m/%d/%Y")

    @property
    def completion_percentage(self):
        stats = self.tasks.aggregate(
            total_importance=Sum('importance'),
            done_importance=Sum('importance', filter=models.Q(status='done'))
        )

        total = stats['total_importance'] or 0
        done = stats['done_importance'] or 0

        if total == 0:
            return 0

        return round((done / total) * 100, 2)


class Task(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')

    title = models.CharField(max_length=100)
    slug = models.SlugField(unique=False)
    status = models.CharField(max_length=20, choices=[("to-do", "To-Do"), ("doing", "Doing"), ("done", "Done"),
                                                      ("archived", "Archived")])
    importance = models.IntegerField(default=0)
    phase_label = models.CharField(max_length=100)

    parent_task = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True, related_name='subtasks')
    depends_on = models.ManyToManyField("self", blank=True, related_name='blocked_tasks', symmetrical=False)
    owner = models.ForeignKey(Developer, on_delete=models.SET_NULL, blank=True, null=True, related_name='owned_tasks')
    blocked_tasks_count = models.PositiveIntegerField(default=0)

    updated_on = models.DateTimeField(auto_now=True)
    ai_suggested = models.BooleanField(default=False)

    class Meta:
        unique_together = ('project', 'slug')

    @property
    def is_parent(self):
        return self.subtasks.exists()

    @property
    def is_blocked(self):
        # 1. Check horizontal (Direct dependencies)
        if self.depends_on.exclude(status='done').exists():
            return True

        # 2. Check vertical (If parent is blocked, you are too)
        if self.parent_task and self.parent_task.is_blocked:
            return True

        return False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # take a snapshot the moment the object is loaded
        self._original_status = self.status

    def archive_recursive(self, reason="Automated cascade"):
        """
        Kills this task and every task beneath it.
        """
        # 1. Update self
        if self.status != 'archived':
            self.status = 'archived'
            self._change_reason = reason
            # We pass a custom reason so TaskHistory knows why it died
            self.save(update_fields=['status'])

            # 2. Update children
            for child in self.subtasks.all():
                child.archive_recursive(reason=reason)


class TaskHistory(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='history')
    from_status = models.CharField(max_length=20, choices=[('to-do', 'To-Do'), ('doing', 'Doing'), ('done', 'Done')])
    to_status = models.CharField(max_length=20, choices=[('to-do', 'To-Do'), ('doing', 'Doing'), ('done', 'Done'),
                                                         ('archived', 'Archived')])
    change_reason = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']


class ArchitectQuestion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()  # The question from Gemini

    @property
    def is_answered(self):
        return self.options.filter(is_selected=True).exists()

    @property
    def selected_options(self):
        return self.options.filter(is_selected=True)

    @property
    def selected_option_text(self):
        return [q.text for q in self.selected_options]


class Option(models.Model):
    question = models.ForeignKey("ArchitectQuestion", on_delete=models.CASCADE, related_name='options')
    text = models.TextField()
    is_selected = models.BooleanField(default=False)
    is_recommended = models.BooleanField(default=False)


class ProjectSettings(models.Model):

    class CompletionPolicy(models.TextChoices):
        HARD_BLOCK  = 'hard_block',  'Hard block — revert silently'
        SOFT_WARN   = 'soft_warn',   'Soft warn — revert with warning notification'
        SHAME_BLOCK = 'shame_block', 'Shame block — revert and post to webhook'

    class SuggestionPolicy(models.TextChoices):
        AUTO      = 'auto',    'Auto-mark done immediately'
        SUGGEST   = 'suggest', 'Notify developer to confirm'
        REVIEW    = 'review',  'Move to done, flag for leader review'

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name='settings'
    )
    completion_policy   = models.CharField(
        max_length=20, choices=CompletionPolicy.choices,
        default=CompletionPolicy.HARD_BLOCK,
    )
    suggestion_policy   = models.CharField(
        max_length=20, choices=SuggestionPolicy.choices,
        default=SuggestionPolicy.SUGGEST,
    )
    skip_ai_completion_check = models.BooleanField(default=False)
    max_commits_for_review   = models.PositiveIntegerField(default=10)

    def __str__(self):
        return f"Settings({self.project.name})"
