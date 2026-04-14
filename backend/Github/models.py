from django.db import models

from projects.models import Task, Project


# Create your models here.
class CommitEvent(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='commits', blank=True, null=True)
    sha = models.CharField(max_length=40)
    author = models.CharField(max_length=100)
    message = models.TextField(blank=True)
    timestamp = models.DateTimeField()

    class Meta:
        ordering = ['-timestamp']
        unique_together = ('task', 'sha')


class UnrelatedCommit(models.Model):
    """Commits that couldn't be matched to any task."""
    project   = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='unrelated_commits')
    developer = models.ForeignKey('Users.Developer', on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name='unrelated_commits')
    sha       = models.CharField(max_length=40)
    branch    = models.CharField(max_length=255)
    message   = models.TextField(blank=True)
    author    = models.CharField(max_length=100)
    timestamp = models.DateTimeField()

    # Files changed — stored as JSON list of {"filename": ..., "additions": ..., "deletions": ...}
    files_changed  = models.JSONField(default=list)
    lines_added    = models.IntegerField(default=0)
    lines_deleted  = models.IntegerField(default=0)

    class Meta:
        unique_together = ('project', 'sha')
        ordering = ['-timestamp']