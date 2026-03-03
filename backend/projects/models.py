from django.db import models
from django.db.models import Sum


# Create your models here.
class Project(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    is_active = models.BooleanField(default=True)
    guarantee_date = models.DateField(auto_now=True)

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
