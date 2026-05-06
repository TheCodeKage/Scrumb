from django.db.models.signals import post_save
from django.dispatch import receiver

from github.logic import set_github_installation
from projects.logic import update_blocking_counts
from projects.models import Task, TaskHistory, ProjectSettings, Project


@receiver(post_save, sender=Task)
def update_task_status(sender, instance, created, **kwargs):
    if not created:
        if instance._original_status != instance.status:
            project = instance.project

            project._unaccounted_importance += instance.importance

            if project._unaccounted_importance > 10:
                update_blocking_counts(project)
                project._unaccounted_importance = 0

            project.save()


@receiver(post_save, sender=Task)
def log_task_status_change(sender, instance, created, **kwargs):
    # We only care about updates, not initial creation
    if not created:
        reason = getattr(instance, '_change_reason', "Execution Sync Update")
        if instance._original_status != instance.status:
            TaskHistory.objects.create(
                task=instance,
                from_status=instance._original_status,
                to_status=instance.status,
                change_reason=reason,
            )
            # Update the snapshot so multiple saves in one request don't double-log
            instance._original_status = instance.status


@receiver(post_save, sender=Project)
def create_project_settings(sender, instance, created, **kwargs):
    if created:
        ProjectSettings.objects.get_or_create(project=instance)


@receiver(post_save, sender=Project)
def check_existing_installation(sender, instance, created, **kwargs):
    if created:
        if instance.github_repo_slug and instance.github_installation_id is None:
            set_github_installation(instance)
