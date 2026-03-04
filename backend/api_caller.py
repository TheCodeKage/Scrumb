import os
import django

# Set the environment variable to your settings file
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# Initialize Django
django.setup()

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from backend.settings import GEMINI_KEY

from google import genai
import json

from projects.models import TaskHistory, Project

client = genai.Client(api_key=str(GEMINI_KEY).strip())


def generate_tasks(project_name, project_description):
    prompt = f"""
    You are a Senior Project Architect for {project_name}.
    Description of {project_name}: {project_description}

    Create a comprehensive execution plan. 
    Format: A JSON list of tasks. 
    Each task MUST have: 'title', 'importance' (1-10), 'phase_label', and optional 'sub_tasks' (a list of tasks).

    Constraints:
    1. Focus on MVP.
    2. Output ONLY valid JSON. No conversational text.
    3. Break complex tasks into sub_tasks.
    4. If no technology stack is specified, use abstract, high-level terms (e.g., 'Backend Logic' instead of 'Django'). Do not assume the project uses specific libraries or languages unless explicitly stated.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt
    )
    # Clean the response (sometimes AI adds markdown blocks)
    clean_json = response.text.replace('```json', '').replace('```', '').strip()
    return json.loads(clean_json)


def get_panic_recommendations(project: Project, target_cut: float):
    completion_rate = Project.completion_percentage

    if target_cut == 0:
        return []

    # 2. Format tasks for the AI (Need ID + Title + Importance)
    unfinished_qs = project.tasks.exclude(status__in=('archived', 'done'))
    task_data = list(unfinished_qs.values('id', 'title', 'importance'))

    days_remaining = (project.guarantee_date - timezone.now().date()).days

    prompt = f"""
    SYSTEM: You are a CLI tool designed to output raw JSON only. You have no personality. You do not explain. You only execute.
    
    CONTEXT: Project "{project.name}" ({project.description}) is failing.
    MATH: Days Left: {days_remaining} | Completion: {completion_rate}% | TARGET CUT: {target_cut}% of importance weight.
    
    DATA:
    {json.dumps(task_data)}
    
    STRICT ALGORITHM:
    1. Sort tasks by 'importance' ASC.
    2. Select tasks to archive until the sum of their 'importance' reaches {target_cut}% of the total unfinished importance.
    3. PROTECT: Importance > 8 and their parents.
    4. If a task is protected, skip it and move to the next lowest importance.
    
    OUTPUT FORMAT:
    ["id1", "id2"]
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",  # Or your specific model version
        contents=prompt
    )

    # Strip markdown and load
    raw_text = response.text.strip().replace('```json', '').replace('```', '')
    return json.loads(raw_text)


if __name__ == '__main__':
    print(f"DEBUG: Key is {GEMINI_KEY}")
    print(get_panic_recommendations(Project.objects.get(id=1), target_cut=2))
