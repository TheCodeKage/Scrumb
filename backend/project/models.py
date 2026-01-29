from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Idea(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ideas')
    idea = models.TextField()
    added_on = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.idea


class Project(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    title = models.TextField()
    description = models.TextField()


class Feature(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="features")
    feature = models.TextField()
    importance_score = models.PositiveIntegerField(blank=True, null=True)
