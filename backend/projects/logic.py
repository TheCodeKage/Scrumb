import random
from collections.abc import Iterable
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from projects.models import TaskHistory, Task, Project, ArchitectQuestion, Option


def get_selected_constraints(project: Project):
    """
    Gathers all the choices made by the team.
    """
    selections = []
    # Using your model structure
    for question in project.questions.all():
        selected_texts = question.selected_option_text # Your property
        if selected_texts:
            selections.append({
                "context": question.text,
                "choice": ", ".join(selected_texts)
            })
    return selections


@transaction.atomic
def add_questions(project: Project, questions: Iterable[dict]):
    for q_data in questions:
        # 1. Create the Parent Question
        question_obj = ArchitectQuestion.objects.create(
            project=project,
            text=q_data["text"]
        )

        # 2. Prepare the Options for THIS question only
        option_objects = [
            Option(
                question=question_obj,
                text=opt_text,
                is_recommended=opt_text==q_data["architect_recommendation"]
            ) for opt_text in q_data["options"]
        ]

        # 3. Bulk create options per question
        Option.objects.bulk_create(option_objects)


def answer_question(project: Project, question_id: int, answer_id: int):
    answer = Option.objects.get(id=answer_id, question_id=question_id, question__project=project)
    answer.is_selected = True
    answer.save()


def get_daily_velocity(project: Project, days=7):
    recent_done_importance = TaskHistory.objects.filter(
        task__project=project,
        to_status='done',
        timestamp__gte=timezone.now() - timedelta(days=days)
    ).aggregate(total=Sum('task__importance'))['total'] or 0

    # We use max(..., 1) to avoid DivisionByZero or making the AI think we are dead
    return round(recent_done_importance / days, 2) or 0.1


def calculate_target_cut(project: Project):
    # 1. Calculate Time Remaining
    days_left = (project.guarantee_date - timezone.now().date()).days
    if days_left <= 0: return 100  # Absolute Panic: Deadline passed.

    # 2. Calculate Work Remaining (Importance Weighted)
    unfinished_tasks = project.tasks.exclude(status__in=('done', 'archived'))
    work_remaining = unfinished_tasks.aggregate(Sum('importance'))['importance__sum'] or 0

    # 3. Get Velocity (Average importance finished per day in the last 3 days)
    velocity = get_daily_velocity(project, days=7)

    # 4. The "Reality" Check
    estimated_days_needed = work_remaining / velocity

    if estimated_days_needed <= days_left:
        return 0  # We are on track. No cuts needed.

    # 5. The Cut Percentage
    # (Days we don't have / Days we need) * 100
    cut_percent = ((estimated_days_needed - days_left) / estimated_days_needed) * 100
    return min(round(cut_percent, 2), 90)  # Cap at 90% so we don't delete the whole project


@transaction.atomic
def save_tasks(data: Iterable, project: Project):
    # Dictionary to keep track of { "slug": TaskObject }
    slug_to_task_map = {}

    # --- PASS 1: CREATE ALL TASKS ---
    def create_recursive(tasks_list, parent=None):
        for task_data in tasks_list:
            t = Task.objects.create(
                project=project,
                parent_task=parent,
                title=task_data['title'],
                importance=task_data['importance'],
                phase_label=task_data.get('phase_label', 'Development'),
                status='to-do',
                owner=task_data['owner'],
                slug=task_data['slug']  # Ensure you added 'slug' to your Task Model
            )

            # Add to our flat map for linking later
            slug_to_task_map[t.slug] = t

            # Handle sub-tasks (if any)
            sub_key = 'sub_tasks' if 'sub_tasks' in task_data else 'subtasks'
            if sub_key in task_data and task_data[sub_key]:
                create_recursive(task_data[sub_key], parent=t)

    create_recursive(data)

    # --- PASS 2: LINK DEPENDENCIES ---
    def link_recursive(tasks_list):
        for task_data in tasks_list:
            current_task = slug_to_task_map.get(task_data['slug'])

            # Link dependencies using the slug map
            if 'depends_on' in task_data and task_data['depends_on']:
                for dep_slug in task_data['depends_on']:
                    dep_task = slug_to_task_map.get(dep_slug)
                    if dep_task:
                        current_task.depends_on.add(dep_task)

            # Recurse into sub-tasks to link their dependencies too
            sub_key = 'sub_tasks' if 'sub_tasks' in task_data else 'subtasks'
            if sub_key in task_data and task_data[sub_key]:
                link_recursive(task_data[sub_key])

    link_recursive(data)


@transaction.atomic
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
    target_cut = calculate_target_cut(project)

    # 2. Velocity Math (Points per day)
    # We look at history for the last 7 days
    velocity = get_daily_velocity(project, days=7)

    # 3. Categorization
    status = "HEALTHY"
    if target_cut > 0: status = "STRESSED"
    if target_cut > 50: status = "TERMINAL"

    total_importance = project.tasks.exclude(status__in=('archived', 'done')).aggregate(importance=Sum('importance'))[
                           'importance'] or 0

    return status, velocity, total_importance, target_cut


def get_team_shame_data(project: Project):
    # 1. Identify the "Stallers"
    stalled_tasks = project.tasks.filter(status='doing').order_by('updated_on')[:3]

    # 2. Prepare the data for Gemini
    team_data = project.team
    shame_data = []
    for task in stalled_tasks:
        shame_data.append({
            "owner": task.owner,  # The simple string field
            "task": task.title,
            "days_stalled": (timezone.now() - task.updated_on).days
        })

    return shame_data, team_data
