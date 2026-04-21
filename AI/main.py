import os
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from Knowledge_graph_functions import ScrumbEngine, get_encoder
from dotenv import load_dotenv
load_dotenv()
app = FastAPI(title="Scrumb AI Context Engine")


# --- Request Models ---

class TaskData(BaseModel):
    id: str
    title: str


class SeedRequest(BaseModel):
    user_id: str
    idea_id: str
    project_name: str
    tasks: List[TaskData]


class ASTSymbol(BaseModel):
    name: str
    docstring: Optional[str] = ""


class IngestRequest(BaseModel):
    user_id: str
    idea_id: str
    task_id: str
    github_payload: Dict[str, str]  # commit_hash, file_path, branch
    ast_json: Dict[str, List[ASTSymbol]]


class AuditRequest(BaseModel):
    user_id: str
    active_task_id: str
    current_file: str
    current_symbol: ASTSymbol


# --- API Routes ---

@app.post("/seed")
async def seed_project(data: SeedRequest):
    """Initializes the project skeleton."""
    engine = ScrumbEngine(data.user_id, get_encoder())
    task_list = [{"id": t.id, "title": t.title} for t in data.tasks]
    return engine.seed_project(data.idea_id, data.project_name, task_list)


@app.post("/ingest")
async def ingest_webhook(data: IngestRequest, bg_tasks: BackgroundTasks):
    """Background ingestion for GitHub Webhooks/Bulk files."""
    engine = ScrumbEngine(data.user_id, get_encoder())
    bg_tasks.add_task(
        engine.ingest_code_context,
        data.task_id,
        data.idea_id,
        data.github_payload,
        data.ast_json
    )
    return {"status": "accepted", "queued": True}


@app.post("/audit")
async def audit_code(data: AuditRequest):
    """
    Synchronous Audit:
    Returns an immediate verdict to the IDE or Developer.
    """
    try:
        engine = ScrumbEngine(data.user_id, get_encoder())
        # Convert Pydantic ASTSymbol to dict for the engine
        symbol_dict = data.current_symbol.model_dump()

        verdict = engine.audit_intent(
            active_task_id=data.active_task_id,
            current_file=data.current_file,
            current_symbol=symbol_dict
        )
        return verdict
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/inspect/{user_id}")
async def inspect_vectors(user_id: str):
    engine = ScrumbEngine(user_id, get_encoder())
    # Retrieve the last 5 points stored for this user
    points = engine.client.scroll(
        collection_name="scrumb_symbols",
        scroll_filter={"must": [{"key": "user_id", "match": {"value": user_id}}]},
        limit=5
    )
    return points
@app.get("/health")
def health():
    return {"status": "online", "engine": "Scrumb-Context-v1"}