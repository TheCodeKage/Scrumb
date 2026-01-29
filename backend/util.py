from dotenv import load_dotenv
from google import genai
import json
import re
from django.conf import settings

GEMINI_FEATURE_PROMPT = """
You are a senior product manager helping define an MVP for a software project.

Given the project title and description, generate a list of MVP features.

Rules:
- Only suggest features required for an MVP
- Avoid advanced or scaling features
- Assign importance on a scale of 1–5
  5 = absolutely required for MVP
  1 = nice to have

Return ONLY valid JSON in the following format:
{
  "features": [
    { "feature": "Feature name", "importance": 5 }
  ]
}
"""


def call_gemini(title: str, description: str, api_key=None):
    """
    Calls Gemini API and returns a list of features with importance scores.
    Output format:
    [
        {"feature": "User authentication", "importance": 5},
        ...
    ]
    """

    if api_key is None:
        api_key=settings.GEMINI_KEY

    client = genai.Client(api_key=api_key)

    prompt = f"""
{GEMINI_FEATURE_PROMPT}

Project Title:
{title}

Project Description:
{description}
"""

    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
    )

    raw_text = response.text.strip()

    # 🧼 Clean possible markdown/code fences
    cleaned = re.sub(r"```json|```", "", raw_text).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed.get("features", [])

    except json.JSONDecodeError:
        # 🔥 Fail gracefully (very important for MVP)
        return [
            {
                "feature": "Define core functionality",
                "importance": 5
            }
        ]

if __name__ == "__main__":
    print(call_gemini("Udaan", "A tracking app for all kinds of public transport", "AIzaSyDcY9eyzF2mL7z31m19Xu92u0tKgAYmLKY"))