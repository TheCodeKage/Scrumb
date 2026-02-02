from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth.models import User


# Create your models here.
class Idea(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ideas')
    idea = models.TextField()
    added_on = models.DateTimeField(auto_now_add=True)
    archived_on = models.DateTimeField(null=True, blank=True)

    @property
    def is_hidden(self):
        return self.archived_on is not None

    def __str__(self):
        return f"{self.author}-{self.idea[:50]}"


class Project(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="projects")
    title = models.CharField(max_length=100)
    description = models.TextField()

    source_idea = models.ForeignKey(Idea, null=True, blank=True, on_delete=models.SET_NULL)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_ready(self):
        return self.features.exists()

    def __str__(self):
        return f"{self.author}-{self.title[:50]}"

    class Meta:
        ordering = ['-created_at']


class Feature(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="features")
    feature = models.TextField()
    importance_score = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.project}-{self.feature[:50]}"

    class Meta:
        ordering = ['-importance_score', 'id']
        unique_together = ('project', 'feature')


class Task(models.Model):
    STATUS_CHOICES = [("todo", "To-Do"), ("ongoing", "Ongoing"),("done", "Completed"),]
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    feature = models.ForeignKey(Feature, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="todo")
    assignee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    order = models.PositiveIntegerField()
    estimate_hours = models.PositiveIntegerField(null=True, blank=True)
    auto_generated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.project}-{self.title[:50]}"

    class Meta:
        ordering = ["order"]
