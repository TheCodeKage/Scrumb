from backend.settings import GEMINI_KEY

from google import genai
import json


client = genai.Client(api_key=str(GEMINI_KEY).strip())


def generate_tasks(project_name, project_description):
    prompt = f"""
    You are a Senior Project Architect for Scrumb.
    Project Name: {project_name}
    Description: {project_description}

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

if __name__ == '__main__':
    print(f"DEBUG: Key is {GEMINI_KEY}")
    print(generate_tasks("PDFSummary", "An app that allows user to upload pdf, uses gemini api to summarize it and returns summary"))