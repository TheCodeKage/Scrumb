from django.db import models

# Create your models here.
class Project(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    is_active = models.BooleanField(default=True)
    guarantee_date = models.DateField(auto_now=True)

    def __str__(self):
        return self.name + self.guarantee_date.strftime("%m/%d/%Y")


class Task(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')

    title = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=[("to-do", "To-Do"), ("doing", "Doing"), ("done", "Done"), ("Archived", "Archived")])
    importance = models.IntegerField(default=0)
    phase_label = models.CharField(max_length=100)

    parent_task = models.ForeignKey("self", on_delete=models.CASCADE, blank=True, null=True)

    @property
    def is_parent(self):
        return self.parent_task is not None
