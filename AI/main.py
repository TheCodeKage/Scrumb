import os
import hmac
import hashlib
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()
from Knowledge_graph_functions import ScrumbEngine, get_encoder

app = FastAPI(title="Scrumb AI Context Engine")


# --- Models ---
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


class AuditRequest(BaseModel):
    user_id: str
    active_task_id: str
    current_file: str
    current_symbol: ASTSymbol


class ManualCrawlRequest(BaseModel):
    user_id: str
    idea_id: str
    task_id: str
    repo_full_name: str
    commit_hash: str
    file_paths: List[str]


# --- Security ---
def verify_github_signature(body: bytes, signature: str):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not signature:
        raise HTTPException(status_code=401, detail="Signature missing")
    hash_object = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + hash_object.hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")


# --- Endpoints ---

@app.post("/seed")
async def seed_project(data: SeedRequest):
    engine = ScrumbEngine(data.user_id, get_encoder())
    task_list = [{"id": t.id, "title": t.title} for t in data.tasks]
    return engine.seed_project(data.idea_id, data.project_name, task_list)


def verify_github_signature(body: bytes, signature: str):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    hash_object = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256)
    expected = "sha256=" + hash_object.hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")


@app.post("/audit")
async def complex_audit_endpoint(
        request: Request,
        user_id: str,
        idea_id: str,
        task_id: str
):
    """
    PRE-INGESTION AUDITOR
    Receives GitHub Diff + Context.
    Returns deep 4-point analysis.
    """
    body = await request.body()
    #signature = request.headers.get("X-Hub-Signature-256")
    #verify_github_signature(body, signature)

    payload = await request.json()
    engine = ScrumbEngine(user_id, get_encoder())

    # Trigger the Judge for a deep classification
    audit_results = await engine.judge_and_audit(user_id, idea_id, task_id, payload)

    return audit_results


@app.post("/webhook/github")
async def github_webhook_ingestor(
        request: Request,
        bg_tasks: BackgroundTasks,
        user_id: str,
        idea_id: str,
        task_id: str
):
    """
    INGESTOR: Only called if Audit is satisfied.
    """
    payload = await request.json()
    engine = ScrumbEngine(user_id, get_encoder())

    bg_tasks.add_task(engine.ingest_from_webhook, payload, user_id, idea_id, task_id)

    return {"status": "INGESTION_QUEUED", "msg": "Context is being mapped to Qdrant Cloud."}


@app.post("/ingest/manual")
async def ingest_manual(data: ManualCrawlRequest, bg_tasks: BackgroundTasks):
    """Fallback for manual triggers without Webhooks."""
    # Note: This still requires a valid token from .env for manual crawling
    engine = ScrumbEngine(data.user_id, get_encoder())
    token = os.getenv("GITHUB_TOKEN")  # Or use App token logic

    for path in data.file_paths:
        bg_tasks.add_task(
            engine.fast_crawl_and_ingest,
            data.repo_full_name, path, data.commit_hash,
            data.task_id, data.idea_id, token
        )
    return {"status": "crawling_manual_files"}




@app.get("/inspect/{user_id}")
async def inspect_vectors(user_id: str):
    engine = ScrumbEngine(user_id, get_encoder())
    return engine.client.scroll(
        collection_name="scrumb_symbols",
        scroll_filter={"must": [{"key": "user_id", "match": {"value": user_id}}]},
        limit=5
    )


@app.get("/health")
def health():
    return {"status": "online", "engine": "Scrumb-v1-Full"}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)