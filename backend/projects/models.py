from django.db import models
from django.db.models import Sum


# Create your models here.
class Project(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    is_active = models.BooleanField(default=True)
    created_on = models.DateField(auto_now=True)

    guarantee_date = models.DateField(null=True, blank=True)

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
    status = models.CharField(max_length=20, choices=[("to-do", "To-Do"), ("doing", "Doing"), ("done", "Done"), ("Archived", "Archived")])
    importance = models.IntegerField(default=0)
    phase_label = models.CharField(max_length=100)

    parent_task = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True, related_name='subtasks')

    @property
    def is_parent(self):
        return self.subtasks.exists()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #take a snapshot the moment the object is loaded
        self._original_status = self.status

    def archive_recursive(self, reason="Automated cascade"):
        """
        Kills this task and every task beneath it.
        """
        # 1. Update self
        if self.status != 'archived':
            self.status = 'archived'
            # We pass a custom reason so TaskHistory knows why it died
            self.save(update_fields=['status'])

            # 2. Update children
            for child in self.subtasks.all():
                child.archive_recursive(reason=reason)


class TaskHistory(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='history')
    from_status = models.CharField(max_length=20, choices=[('to-do', 'To-Do'), ('doing', 'Doing'),('done', 'Done')])
    to_status = models.CharField(max_length=20, choices=[('to-do', 'To-Do'), ('doing', 'Doing'),('done', 'Done'), ('archived', 'Archived')])
    change_reason = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']