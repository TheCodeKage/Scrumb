import os

import django
from google.genai.types import GenerateContentResponse

from projects.logic import get_selected_constraints

# Set the environment variable to your settings file
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# Initialize Django
django.setup()

from django.utils import timezone
from backend.settings import GEMINI_KEY
from google import genai
import json
from projects.models import Project, Task

client = genai.Client(api_key=str(GEMINI_KEY).strip())


def send_prompt(prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt
    )
    return response


def clean_json(response: GenerateContentResponse):
    return response.text.replace('```json', '').replace('```', '').strip()


def get_ai_response(prompt: str, in_json=True):
    if in_json:
        return json.loads(clean_json(send_prompt(prompt)))
    return send_prompt(prompt).text


def check_description(project: Project):
    team_data = {}
    for member in project.team.members.all():
        team_data[member.user.username] = [skill.name for skill in member.skills.all()]

    prompt = f"""
    You are the "Architect Prime". We are starting a project: {project.name}.
    DESCRIPTION: {project.description}
    TEAM: {team_data}

    TASK: We need to build a high-precision Task DAG. To do this, we need to finalize the Technical Blueprint. 

    If the description is too vague (like "a bus app"), generate 3-5 MANDATORY Multiple Choice Questions to lock in the architecture.

    RULES FOR QUESTIONS:
    1. NO META-TALK: Do not ask "Why is this vague?". 
    2. BE TECHNICAL: Ask about Frameworks, Databases, Auth, or specific MVP Features.
    3. KEEP IT SIMPLE: Options should be short (e.g., "Django + React" vs "FastAPI + Next.js").
    4. TEAM AWARE: Look at the TEAM skills. If Gopi knows Python, make Python-based stacks the 'recommended' options.

    STRICT JSON STRUCTURE:
    {{
        "is_detailed": false,
        "questions": [
            {{
                "text": "What is the primary tech stack for the MVP?",
                "options": ["Django (Python) + React", "FastAPI (Python) + Vue", "Node.js + React"],
                "architect_recommendation": "Django (Python) + React"
            }},
            {{
                "text": "How will we handle real-time location tracking?",
                "options": ["WebSockets (Pusher/Socket.io)", "Firebase Realtime DB", "HTTP Polling (Simple)"],
                "architect_recommendation": "Firebase Realtime DB"
            }}
        ]
    }}
    """
    return get_ai_response(prompt)


def generate_tasks(project: Project):
    team_data = {}
    for member in project.team.members.all():
        team_data[member.user.username] = [skill.name for skill in member.skills.all()]
    # --- NEW: Get the MCQ results ---
    user_choices = get_selected_constraints(project)

    prompt = f"""
        You are the "Architect Prime" for {project.name}.
        GOAL: {project.description}
        DEADLINE: {project.guarantee_date} (Current Date: {timezone.now().date()})

        TEAM RESOURCES: {team_data}

        STRICT TECHNICAL CONSTRAINTS (User Selected):
        {json.dumps(user_choices)}

        TASK: Generate a Directed Acyclic Graph (DAG) of tasks for an MVP.

        RULES:
        1. COMPLIANCE: Every task must align with the 'STRICT TECHNICAL CONSTRAINTS'. 
        2. SCOPE: Adjust task complexity to fit the DEADLINE. If the deadline is close, skip polish.
        3. NESTING: Use the 'sub_tasks' field for every high-level phase (3-5 subtasks minimum).
        4. OWNERSHIP: Assign owners based on skills in TEAM RESOURCES.

    STRICT JSON STRUCTURE:
    Return a JSON list of objects. Each object must contain:
    - "slug": A unique, short identifier (e.g., "db-setup").
    - "title": Clear task name.
    - "importance": 1-10.
    - "owner": The name of the team member best suited based on their skills.
    - "depends_on": A list of "slugs" that MUST be 'done' before this task can start. Use [] if none.
    - "sub_tasks": (Optional) A nested list of tasks following this same structure.

    EXECUTION RULES:
    1. WATERFALL LOGIC: Ensure 'depends_on' creates a logical flow (e.g., API cannot start until Database is designed).
    2. DELEGATION: If a task requires 'CSS', assign it to the member with 'CSS' in their skills.
    3. MVP FOCUS: Only generate tasks required to reach a functional prototype.
    4. NO DIALOGUE: Output ONLY the raw JSON list.
    5. MANDATORY NESTING: Every high-level "Phase" must contain at least 3-5 sub_tasks. Do not provide a flat list.
    6. CROSS-HIERARCHY LINKS: Horizontal depends_on can link any task to any other task, regardless of nesting level.
    7. FORMAT ENFORCEMENT: If a task is a "Parent," it should describe the goal; its sub_tasks should describe the actions.
    """

    return get_ai_response(prompt)


def get_panic_recommendations(project: Project, target_cut: float):
    completion_rate = project.completion_percentage

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
    List of task IDs to archive.
    ["1", "2"]
    """

    return get_ai_response(prompt)


def shame_team(shame_data: list[dict[str, str]], team_data: dict[str, str]):
    prompt = f"Based on this data: {shame_data} and data on team: {team_data}, write a brutal but funny 2-sentence summary of why the project is failing. Mention names."

    return get_ai_response(prompt, in_json=False)


if __name__ == '__main__':
    print(f"DEBUG: Key is {GEMINI_KEY}")
    print(get_panic_recommendations(Project.objects.get(id=1), target_cut=2))
