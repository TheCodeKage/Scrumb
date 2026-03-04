from collections.abc import Iterable
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from projects.models import TaskHistory, Task, Project


def calculate_target_cut(project: Project):
    # 1. Calculate Time Remaining
    days_left = (project.guarantee_date - timezone.now().date()).days
    if days_left <= 0: return 100  # Absolute Panic: Deadline passed.

    # 2. Calculate Work Remaining (Importance Weighted)
    unfinished_tasks = project.tasks.exclude(status='archived').exclude(status='done')
    work_remaining = unfinished_tasks.aggregate(Sum('importance'))['importance__sum'] or 0

    # 3. Get Velocity (Average importance finished per day in the last 3 days)
    # If no history exists, we assume a "Standard" velocity of 5 units/day
    recent_done = TaskHistory.objects.filter(
        task__project=project,
        to_status='done',
        timestamp__gte=timezone.now() - timedelta(days=3)
    ).count()

    velocity = max(recent_done * 5, 5)  # Default to 5 so we don't divide by zero

    # 4. The "Reality" Check
    estimated_days_needed = work_remaining / velocity

    if estimated_days_needed <= days_left:
        return 0  # We are on track. No cuts needed.

    # 5. The Cut Percentage
    # (Days we don't have / Days we need) * 100
    cut_percent = ((estimated_days_needed - days_left) / estimated_days_needed) * 100
    return min(round(cut_percent, 2), 90)  # Cap at 90% so we don't delete the whole project


def save_tasks(data: Iterable, project: Project, parent=None):
    for task in data:
        t = Task.objects.create(
            project=project,
            parent_task=parent,
            title=task['title'],
            importance=task['importance'],
            phase_label=task['phase_label'],
            status='to-do',
        )
        t.save()
        if (((name := 'subtasks') in task) and task['subtasks']) or (
                ((name := 'sub_tasks') in task) and task['sub_tasks']):
            save_tasks(task[name], parent=t, project=project)


def cut_tasks(tasks_to_cut: Iterable, project: Project):
    old = project.tasks.filter(status__in=['to-do', 'doing', 'done'])
    count_old = old.count()
    importance_old = old.aggregate(Sum('importance'))['importance__sum'] or 0

    for task_id in tasks_to_cut:
        try:
            task = project.tasks.get(id=task_id)
            task.archive_recursive(reason="Panic Mode: Automated scope reduction.")
        except Task.DoesNotExist:
            continue

    new = project.tasks.filter(status__in=['to-do', 'doing', 'done'])
    count_new = new.count()
    importance_new = new.aggregate(Sum('importance'))['importance__sum'] or 0

    return count_old, count_new, importance_old, importance_new


def calculate_health(project: Project):
    completion = project.completion_percentage
    target_cut = calculate_target_cut(project)

    # 2. Velocity Math (Points per day)
    # We look at history for the last 7 days
    recent_done = TaskHistory.objects.filter(
        task__project=project,
        to_status='done',
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).aggregate(total=Sum('task__importance'))['total'] or 0

    velocity = round(recent_done / 7, 2)

    # 3. Categorization
    status = "HEALTHY"
    if target_cut > 0: status = "STRESSED"
    if target_cut > 50: status = "TERMINAL"

    total_importance = project.tasks.exclude(status__in=('archived', 'done')).aggregate(importance=Sum('importance'))[
                           'importance'] or 0
    distance = ((1 - (completion / 100)) * total_importance)

    return status, velocity, distance, target_cut
