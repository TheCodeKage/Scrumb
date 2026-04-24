from django.utils import timezone

from projects.logic import calculate_health, get_stalled_tasks
from projects.models import Project
from services.AI.api_caller import shame_team


def health(project: Project):
    project_status, velocity, distance, target_cut = calculate_health(project)

    if not velocity:
        return None

    return {
            "project_name": project.name,
            "status": project_status,
            "completion_percentage": project.completion_percentage,
            "daily_velocity": velocity,
            "current_panic_requirement": f"{target_cut}% scope cut needed",
            "days_until_guarantee": (project.guarantee_date - timezone.now().date()).days,
            "expected_complete_by": f"{round(distance / velocity)} days",
        }

def stalled_tasks(project: Project):
    tasks = get_stalled_tasks(project)
    return {"stalled_tasks": tasks}

def roast(project: Project,):
    tasks = stalled_tasks(project)['stalled_tasks']
    AI_roast = shame_team(tasks, project.team.get_team_data())
    return {"roast": AI_roast}
