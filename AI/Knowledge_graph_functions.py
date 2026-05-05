import os
import uuid
import logging
import ast
import httpx
import json
from datetime import datetime
from typing import List, Dict, Optional

# Core Dependencies
from github import Auth, GithubIntegration
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType
from sentence_transformers import SentenceTransformer

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ScrumbEngine")

COLLECTION_NAME = "scrumb_knowledge_graph"
_encoder = None

def get_encoder():
    """
    Singleton provider for the SentenceTransformer model.
    Prevents redundant memory usage on your LOQ laptop.
    """
    global _encoder
    if _encoder is None:
        # This loads the 384-dimensional vector model
        _encoder = SentenceTransformer('all-MiniLM-L6-v2')
    return _encoder

class ScrumbEngine:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
        self.ollama_url = "http://127.0.0.1:11434/api/generate"
        self.model_name = "llama3"  # High reasoning capability for code
        self._setup_db()

    def _setup_db(self):
        """Initializes the vector store with precise indexing for hierarchical traversal."""
        try:
            collections = self.client.get_collections().collections
            if not any(c.name == COLLECTION_NAME for c in collections):
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
            # Create Keyword Indexes for all hierarchical levels to ensure fast retrieval
            fields = ["user_id", "idea_id", "task_id", "node_type", "file_path", "parent_node"]
            for field in fields:
                self.client.create_payload_index(COLLECTION_NAME, field, PayloadSchemaType.KEYWORD)
        except Exception as e:
            logger.error(f"Database Initialization Error: {e}")

    # --- AGENTIC REASONING (OLLAMA) ---

    async def _reason_with_ollama(self, prompt: str) -> Dict:
        """The 'Brain' of Scrumb: Local LLM processing for semantic analysis."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.ollama_url, json=payload, timeout=60.0)
                return json.loads(resp.json()['response'])
        except Exception as e:
            logger.error(f"Ollama Reasoning Failure: {e}")
            return {}

    # --- 1. SEED FUNCTION ---

    async def seed_idea(self, idea_id: str, idea_description: str, tasks: List[Dict]):
        """Creates the root and task nodes. The foundation of the Knowledge Graph."""
        points = []

        # Root Node: The Idea
        points.append(PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.user_id}_{idea_id}")),
            vector=self.encoder.encode(idea_description).tolist(),
            payload={
                "user_id": self.user_id, "idea_id": idea_id, "node_type": "idea_root",
                "content": idea_description, "created_at": datetime.now().isoformat()
            }
        ))

        # Task Nodes
        for task in tasks:
            t_id = task['task_id']
            ctx = f"Task: {task['name']}. Description: {task.get('description', '')}"
            points.append(PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{idea_id}_{t_id}")),
                vector=self.encoder.encode(ctx).tolist(),
                payload={
                    "user_id": self.user_id, "idea_id": idea_id, "task_id": t_id,
                    "node_type": "task_node", "name": task['name'],
                    "status": "initialized", "content": ctx
                }
            ))

        self.client.upsert(COLLECTION_NAME, points)
        return {"status": "SUCCESS", "message": f"Graph initialized for {idea_id} with {len(tasks)} tasks."}

    # --- 2. AUDITOR FUNCTION ---

    async def audit_payload(self, idea_id: str, github_payload: Dict, tasks: List[Dict], user_id: str):
        """Deep analysis of incoming code vs existing Knowledge Graph."""
        # Extract files from payload (Added/Modified)
        files_to_check = []
        for commit in github_payload.get("commits", []):
            files_to_check.extend(
                [f for f in commit.get("added", []) + commit.get("modified", []) if f.endswith(".py")])

        if not files_to_check:
            return {"status": "SKIPPED", "reason": "No Python files detected."}

        # Analyze the semantic context of the push
        push_message = github_payload.get("head_commit", {}).get("message", "")

        # Cross-reference existing KG to find drift
        audit_results = []
        for file_path in set(files_to_check):
            # 1. Similarity Check (Vector)
            file_vector = self.encoder.encode(file_path + " " + push_message).tolist()
            matches = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=file_vector,
                query_filter={"must": [{"key": "idea_id", "match": {"value": idea_id}}]},
                limit=3
            ).points

            # 2. Agentic Reasoning for Path Alignment
            prompt = f"""
            Analyze this GitHub change for the project '{idea_id}'.
            File: {file_path} | Push Message: {push_message}
            Available Tasks: {json.dumps(tasks)}
            Previous Matches in KG: {[m.payload.get('content') for m in matches]}

            Determine:
            1. 'alignment_score': 0-100 (Is this on the right path?).
            2. 'task_id': Which task does this relate to?
            3. 'semantic_meaning': What is the intent of this change?
            4. 'impact': How does this change affect other modules?
            5. 'redundancy': Is this code already implemented elsewhere?
            6. 'verdict': Should we INGEST or REJECT?
            """
            analysis = await self._reason_with_ollama(prompt)
            audit_results.append({"file": file_path, "analysis": analysis})

        return {"status": "AUDIT_COMPLETE", "results": audit_results}

    # --- 3. INGESTION FUNCTION ---

    def _parse_ast(self, code: str):
        """Structural precision using Abstract Syntax Trees."""
        try:
            tree = ast.parse(code)
            nodes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    nodes.append({"type": "class", "name": node.name, "content": ast.unparse(node)})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nodes.append({"type": "function", "name": node.name, "content": ast.unparse(node)})
            return nodes
        except:
            return []

    async def ingest_from_github(self, idea_id: str, github_payload: Dict, tasks: List[Dict], user_id: str):
        """Full-resolution ingestion. Builds vertical and horizontal dependencies."""
        token = self._get_github_token(github_payload.get("installation", {}).get("id"))
        repo_name = github_payload.get("repository", {}).get("full_name")
        sha = github_payload.get("after")

        # 1. Identify New Tasks and Create Nodes
        existing_tasks = [t['task_id'] for t in tasks]
        # (Logic to check if list 'tasks' contains IDs not in KG... then seed them)

        python_files = list(
            {f for c in github_payload.get("commits", []) for f in (c.get("added", []) + c.get("modified", [])) if
             f.endswith(".py")})

        all_points = []
        async with httpx.AsyncClient() as client:
            for file_path in python_files:
                # Fetch Code Content
                raw_url = f"https://raw.githubusercontent.com/{repo_name}/{sha}/{file_path}"
                resp = await client.get(raw_url, headers={"Authorization": f"token {token}"})
                code_text = resp.text

                # 2. Extract Structure via AST
                logic_blocks = self._parse_ast(code_text)

                # 3. Agentic Classification (Determine Task and Intent)
                for block in logic_blocks:
                    prompt = f"""
                    Classify this {block['type']} '{block['name']}' into one of these tasks: {json.dumps(tasks)}
                    Project Goal: {idea_id}
                    Code: {block['content'][:500]}
                    Return JSON: {{"task_id": "ID", "intent": "purpose", "dependencies": ["file1", "file2"]}}
                    """
                    meta = await self._reason_with_ollama(prompt)

                    # 4. Vertical and Horizontal Dependency Node
                    node_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{idea_id}_{file_path}_{block['name']}"))
                    all_points.append(PointStruct(
                        id=node_id,
                        vector=self.encoder.encode(block['content']).tolist(),
                        payload={
                            "user_id": user_id, "idea_id": idea_id,
                            "task_id": meta.get("task_id"), "node_type": block['type'],
                            "file_path": file_path, "symbol_name": block['name'],
                            "intent": meta.get("intent"),
                            "vertical_deps": {"file": file_path, "task": meta.get("task_id")},
                            "horizontal_deps": meta.get("dependencies", []),
                            "content": block['content'],
                            "ingested_at": datetime.now().isoformat()
                        }
                    ))

        if all_points:
            self.client.upsert(COLLECTION_NAME, all_points)
        return {"status": "INGESTED", "count": len(all_points)}

    # --- 4. TASK COMPLETION FUNCTION ---

    async def is_task_completed(self, idea_id: str, task_id: str):
        """Analyzes the KG nodes under a task to verify objective fulfillment."""
        # Search for all logic nodes under this task
        task_data = self.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter={"must": [
                {"key": "idea_id", "match": {"value": idea_id}},
                {"key": "task_id", "match": {"value": task_id}}
            ]},
            limit=100
        )[0]

        if not task_data:
            return {"status": "NOT_STARTED", "completion": 0}

        aggregated_logic = "\n".join([f"[{p.payload['symbol_name']}]: {p.payload['intent']}" for p in task_data])

        prompt = f"""
        Analyze the progress of Task '{task_id}' for Project '{idea_id}'.
        Logic Implemented:
        {aggregated_logic}

        Return JSON:
        {{
            "is_completed": true/false,
            "completion_percentage": 0-100,
            "how_it_is_done": "summary of implementation",
            "missing_measures": ["list of steps to finish"],
            "critical_risks": ["dependencies or logic gaps"]
        }}
        """
        return await self._reason_with_ollama(prompt)

    def _get_github_token(self, installation_id):
        # Implementation of JWT/Auth as provided in previous logic
        with open(os.getenv("GITHUB_PRIVATE_KEY_PATH"), 'r') as f:

            private_key = f.read()

            auth = Auth.AppAuth(os.getenv("GITHUB_APP_ID"), private_key)

            integration = GithubIntegration(auth=auth)

            return integration.get_access_token(installation_id).token