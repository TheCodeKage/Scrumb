from django.db.models.signals import post_save
from django.dispatch import receiver

from projects.models import Task, TaskHistory


@receiver(post_save, sender=Task)
def log_task_status_change(sender, instance, created, **kwargs):
    # We only care about updates, not initial creation
    if not created:
        if instance._original_status != instance.status:
            TaskHistory.objects.create(
                task=instance,
                from_status=instance._original_status,
                to_status=instance.status,
                change_reason="Execution Sync Update"
            )
            # Update the snapshot so multiple saves in one request don't double-log
            instance._original_status = instance.status