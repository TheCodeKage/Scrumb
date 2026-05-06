import random
from collections.abc import Iterable
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from users.models import Developer
from projects.models import TaskHistory, Task, Project, ArchitectQuestion, Option


def get_selected_constraints(project: Project):
    """
    Gathers all the choices made by the team.
    """
    selections = []
    # Using your model structure
    for question in project.questions.all():
        selected_texts = question.selected_option_text  # Your property
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
                is_recommended=opt_text == q_data["architect_recommendation"]
            ) for opt_text in q_data["options"]
        ]

        # 3. Bulk create options per question
        Option.objects.bulk_create(option_objects)


def answer_question(project: Project, question_id: int, answer_id: int):
    answer = Option.objects.get(id=answer_id, question_id=question_id, question__project=project)
    answer.is_selected = True
    answer.save()


def get_daily_velocity(project: Project, days=7):
    cutoff = timezone.now() - timedelta(days=days)

    # On-task velocity: importance points completed
    recent_done_importance = TaskHistory.objects.filter(
        task__project=project,
        to_status='done',
        timestamp__gte=cutoff
    ).aggregate(total=Sum('task__importance'))['total'] or 0

    raw_velocity = round(recent_done_importance / days, 2) or 0.1

    return raw_velocity

    """# Distraction penalty: proportion of commits that were off-task
    total_commits = CommitEvent.objects.filter(
        task__project=project,
        timestamp__gte=cutoff
    ).count()

    unrelated_commits = UnrelatedCommit.objects.filter(
        project=project,
        timestamp__gte=cutoff
    ).count()

    all_commits = total_commits + unrelated_commits
    if all_commits > 0:
        distraction_ratio = unrelated_commits / all_commits
        # Penalty: up to 30% velocity reduction at 100% off-task
        penalty = min(distraction_ratio * 0.3, 0.3)
        effective_velocity = round(raw_velocity * (1 - penalty), 2)
    else:
        effective_velocity = raw_velocity

    return max(effective_velocity, 0.1)   # floor to avoid division by zero"""


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
            task_data['slug'] = task_data['slug'][:100]
            t = Task.objects.create(
                project=project,
                parent_task=parent,
                title=task_data['title'],
                importance=task_data['importance'],
                phase_label=task_data.get('phase_label', 'Development'),
                status='to-do',
                owner=Developer.objects.get(user__username=task_data['owner'], teams=project.team),
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
            print(f"Archiving task with ID: {task_id}")
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
    if target_cut > 40: status = "TERMINAL"

    total_importance = project.tasks.exclude(status__in=('archived', 'done')).aggregate(importance=Sum('importance'))[
                           'importance'] or 0

    return status, velocity, total_importance, target_cut


def get_stalled_tasks(project: Project):
    # 1. Identify the "Stallers"
    stalled_tasks = (
        project.tasks.filter(status='doing')
        .order_by('-blocked_tasks_count', 'updated_on')[:5]
    )

    # 2. Prepare the data for Gemini
    shame_data = []
    for task in stalled_tasks:
        shame_data.append({
            "owner": task.owner.user.username,  # The simple string field
            "task": task.title,
            "tasks_stalled": task.blocked_tasks_count,
            "days_stalled": (timezone.now() - task.updated_on).days
        })

    return shame_data

def update_blocking_counts(project: Project):
    tasks = list(
        Task.objects.filter(project=project)
        .select_related('parent_task')
        .prefetch_related('depends_on', 'subtasks')
    )

    # -------- Build graph --------
    graph = defaultdict(set)

    for task in tasks:
        for dep in task.depends_on.all():
            graph[dep.id].add(task.id)

        if task.parent_task:
            graph[task.parent_task.id].add(task.id)

    # -------- DFS with memo --------
    memo = {}

    def dfs(task_id, visiting=None):
        if visiting is None:
            visiting = set()
        if task_id in memo:
            return memo[task_id]

        if task_id in visiting:
            return set()  # break cycle safely

        visiting.add(task_id)

        blocked = set()
        for neighbor in graph[task_id]:
            blocked.add(neighbor)
            blocked |= dfs(neighbor, visiting)

        visiting.remove(task_id)

        memo[task_id] = blocked
        return blocked

    # -------- Compute + assign --------
    for task in tasks:
        blocked_set = dfs(task.id)
        task.blocked_tasks_count = len(blocked_set)

    # -------- Bulk update (CRITICAL) --------
    with transaction.atomic():
        Task.objects.bulk_update(tasks, ['blocked_tasks_count'])


def select_option_for_question(question, selected_option_id):
    try:
        selected_option_id = int(selected_option_id)
    except (ValueError, TypeError):
        raise ValidationError("Invalid option ID.")

    option = question.options.filter(id=selected_option_id).first()

    if not option:
        raise ValidationError("Option does not belong to this question.")

    # Efficient update
    question.options.exclude(id=selected_option_id).update(is_selected=False)
    option.is_selected = True
    option.save()

    return question
