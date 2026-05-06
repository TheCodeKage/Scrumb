import os
import hmac
import hashlib
import uvicorn
import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Optional
from dotenv import load_dotenv
from llm import ScrumbBrain
load_dotenv()

from Knowledge_graph_functions import ScrumbEngine, get_encoder

app = FastAPI(title="Scrumb AI Knowledge Graph - Matured v3")


# --- Models ---
class TaskData(BaseModel):
    id: str
    title: str
    description: str

class ChatMessage(BaseModel):
    user_id: str
    idea_id: str
    prompt: str

class SeedRequest(BaseModel):
    user_id: str
    idea_id: str
    idea_description: str
    tasks: List[TaskData]
async def fetch_project_context(engine: ScrumbEngine, idea_id: str):
    """Retrieves existing tasks and project goal from the Knowledge Graph."""
    try:
        res = engine.client.scroll(
            collection_name="scrumb_knowledge_graph",
            scroll_filter={"must": [
                {"key": "idea_id", "match": {"value": idea_id}},
                {"key": "node_type", "match": {"value": "task_node"}}
            ]},
            limit=100
        )[0]

        tasks = [{"task_id": p.payload['task_id'], "name": p.payload['name']} for p in res]

        # Also fetch the idea root for the description
        root = engine.client.scroll(
            collection_name="scrumb_knowledge_graph",
            scroll_filter={"must": [
                {"key": "idea_id", "match": {"value": idea_id}},
                {"key": "node_type", "match": {"value": "idea_root"}}
            ]},
            limit=1
        )[0]

        goal = root[0].payload['content'] if root else "General Software Development"
        return tasks, goal
    except Exception as e:
        logging.error(f"Context Fetch Error: {e}")
        return [], "General Software Development"


# --- Endpoints ---

@app.post("/seed")
async def seed_project(data: SeedRequest):
    """
    1. SEED FUNCTION
    FIXED: Now correctly maps Pydantic 'id' to Engine 'task_id'.
    """
    engine = ScrumbEngine(data.user_id)
    # Map incoming model fields to the keys expected by seed_idea()
    task_list = [
        {
            "task_id": t.id,
            "name": t.title,
            "description": t.description
        } for t in data.tasks
    ]
    return await engine.seed_idea(data.idea_id, data.idea_description, task_list)


@app.post("/audit")
async def complex_audit_endpoint(request: Request, user_id: str, idea_id: str):
    """
    2. AUDITOR FUNCTION
    FIXED: Fetches current task context so the Auditor can map changes correctly.
    """
    payload = await request.json()
    engine = ScrumbEngine(user_id)

    tasks, _ = await fetch_project_context(engine, idea_id)
    return await engine.audit_payload(idea_id, payload, tasks, user_id)


@app.post("/webhook/github")
async def github_webhook_ingestor(
        request: Request,
        bg_tasks: BackgroundTasks,
        user_id: str,
        idea_id: str
):
    """
    3. INGEST FROM GITHUB
    FIXED: Background task now receives full project context for Agentic Classification.
    """
    payload = await request.json()
    engine = ScrumbEngine(user_id)

    # Fetch context to pass to the background ingestion process
    tasks, project_goal = await fetch_project_context(engine, idea_id)

    bg_tasks.add_task(engine.ingest_from_github, idea_id, payload, tasks, user_id)

    return {
        "status": "INGESTION_INITIATED",
        "msg": "Hierarchical logic extraction and agentic classification started."
    }


@app.get("/task-status/{idea_id}/{task_id}")
async def check_task_completion(idea_id: str, task_id: str, user_id: str):
    """
    4. IS TASK COMPLETED
    """
    engine = ScrumbEngine(user_id)
    return await engine.is_task_completed(idea_id, task_id)


@app.get("/inspect/{user_id}/{idea_id}")
async def inspect_knowledge_graph(user_id: str, idea_id: str):
    engine = ScrumbEngine(user_id)
    return engine.client.scroll(
        collection_name="scrumb_knowledge_graph",
        scroll_filter={"must": [
            {"key": "user_id", "match": {"value": user_id}},
            {"key": "idea_id", "match": {"value": idea_id}}
        ]},
        limit=20
    )

@app.get("/project-health/{user_id}/{idea_id}")
async def fetch_global_project_status(user_id: str, idea_id: str):
    """
    PROJECT HEALTH CHECK:
    Fetches the Knowledge Graph and audits completion for all tasks in a project.
    """
    engine = ScrumbEngine(user_id)
    return await engine.get_full_project_status(idea_id)
@app.get("/health")
def health():
    return {
        "status": "online",
        "version": "v3-Agentic-KG",
        "reasoning_engine": "Ollama/Llama3"
    }
@app.post("/chat")
async def chat_with_scrumb(data: ChatMessage):
    """
    KNOWLEDGE-AWARE CHET ENDPOINT:
    Connects the user to their specific project Knowledge Graph.
    """
    brain = ScrumbBrain(data.user_id)
    response = await brain.get_aware_response(data.idea_id, data.prompt)
    return response

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)