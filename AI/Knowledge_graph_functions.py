import os
import uuid
import logging
import ast
import httpx
import networkx as nx
from datetime import datetime
from github import GithubIntegration  # pip install PyGithub
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType
from sentence_transformers import SentenceTransformer

# Configuration
COLLECTION_NAME = "scrumb_symbols"

_encoder = None


def get_encoder():
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer('all-MiniLM-L6-v2')
    return _encoder


class ScrumbEngine:
    def __init__(self, user_id, encoder):
        self.user_id = user_id
        self.encoder = encoder

        # GitHub App Config
        self.app_id = os.getenv("GITHUB_APP_ID")
        self.private_key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH")

        # Qdrant Config
        qdrant_url = os.getenv("QDRANT_URL")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")

        if not qdrant_url or "cloud.qdrant.io" not in qdrant_url:
            print("⚠️ WARNING: QDRANT_URL is missing or local.")

        self.client = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key,
            timeout=60,
            https=True if qdrant_url and "https" in qdrant_url else False
        )

        self.G = nx.DiGraph()
        self.G.add_node(self.user_id, type="user_root")
        self._setup_db()

    def _setup_db(self):
        try:
            collections = self.client.get_collections().collections
            if not any(c.name == COLLECTION_NAME for c in collections):
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
            self.client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="user_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            logging.error(f"Database Initialization Failed: {e}")

    def _get_token(self, installation_id):
        """Authenticates as a GitHub App to get a temporary token."""
        with open(self.private_key_path, 'r') as f:
            private_key = f.read()
        integration = GithubIntegration(self.app_id, private_key)
        access_token = integration.get_access_token(installation_id)
        return access_token.token

    def seed_project(self, idea_id, project_name, tasks):
        """APPROACH 1: Builds the logical project hierarchy."""
        self.G.add_node(idea_id, type="idea", name=project_name)
        self.G.add_edge(self.user_id, idea_id, relation="OWNS")
        for task in tasks:
            self.G.add_node(task['id'], type="task", title=task['title'])
            self.G.add_edge(idea_id, task['id'], relation="HAS_TASK")
        return {"status": "seeded", "idea_id": idea_id}

    async def ingest_from_webhook(self, payload: dict, user_id: str, idea_id: str,task_id :str):
        """The Manager: Processes the full GitHub Webhook JSON."""
        repo_name = payload.get("repository", {}).get("full_name")
        installation_id = payload.get("installation", {}).get("id")

        if not installation_id:
            logging.error("❌ Installation ID missing from webhook.")
            return

        token = self._get_token(installation_id)

        for commit in payload.get("commits", []):
            commit_hash = commit.get("id")
            message = commit.get("message", "").lower()

            # Task Detection Logic
            task_id = "general_dev"
            if "task-" in message:
                task_id = message.split("task-")[-1].split()[0]

            files_to_crawl = commit.get("added", []) + commit.get("modified", [])

            for file_path in files_to_crawl:
                if file_path.endswith(".py"):
                    await self.fast_crawl_and_ingest(
                        repo_full_name=repo_name,
                        file_path=file_path,
                        commit_hash=commit_hash,
                        task_id=task_id,
                        idea_id=idea_id,
                        token=token
                    )

    async def fast_crawl_and_ingest(self, repo_full_name, file_path, commit_hash, task_id, idea_id, token):
        """The Scout: Fetches code into RAM and extracts AST."""
        raw_url = f"https://raw.githubusercontent.com/{repo_full_name}/{commit_hash}/{file_path}"
        headers = {"Authorization": f"token {token}"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(raw_url, headers=headers)
                if response.status_code != 200:
                    return None

                code_text = response.text
                tree = ast.parse(code_text)

                ast_json = {
                    "functions": [
                        {"name": n.name, "docstring": ast.get_docstring(n) or ""}
                        for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                    ],
                    "classes": [
                        {"name": n.name, "docstring": ast.get_docstring(n) or ""}
                        for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                    ]
                }

                github_payload = {"commit_hash": commit_hash, "file_path": file_path}
                return self.ingest_code_context(task_id, idea_id, github_payload, ast_json)

            except Exception as e:
                logging.error(f"❌ Crawl Error in {file_path}: {str(e)}")
        return None

    def ingest_code_context(self, task_id, idea_id, github_payload, ast_json):
        """The Worker: Maps symbols to Files, Commits, and Tasks in Qdrant."""
        commit_hash = github_payload.get('commit_hash', 'local')
        file_path = github_payload.get('file_path', 'unknown')

        # Update Structural Graph
        commit_node = f"commit_{commit_hash}"
        file_node = f"file_{file_path}"
        self.G.add_node(commit_node, type="commit", hash=commit_hash)
        self.G.add_node(file_node, type="file", path=file_path)
        self.G.add_edge(task_id, commit_node, relation="PRODUCED")
        self.G.add_edge(commit_node, file_node, relation="MODIFIED")

        points = []
        symbols = ast_json.get('functions', []) + ast_json.get('classes', [])

        for sym in symbols:
            if not isinstance(sym, dict):
                sym = sym.model_dump()

            symbol_name = sym['name']
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.user_id}_{file_path}_{symbol_name}"))

            context_string = f"File: {file_path} | Symbol: {symbol_name} | Logic: {sym.get('docstring', '')}"
            vector = self.encoder.encode(context_string).tolist()

            points.append(PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "user_id": self.user_id,
                    "idea_id": idea_id,
                    "task_id": task_id,
                    "file_path": file_path,
                    "symbol_name": symbol_name,
                    "commit": commit_hash,
                    "timestamp": datetime.now().isoformat()
                }
            ))

        if points:
            self.client.upsert(collection_name=COLLECTION_NAME, points=points)
        return len(points)

    async def judge_and_audit(self, user_id, idea_id, task_id, github_payload):
        """
        THE JUDGE: Full 4-point precision audit.
        Processes the GitHub diff before ingestion.
        """
        # 1. Setup Data for Analysis
        repo_name = github_payload.get("repository", {}).get("full_name")
        installation_id = github_payload.get("installation", {}).get("id")
        token = self._get_token(installation_id)

        # We grab the most significant changed file from the latest commit for auditing
        latest_commit = github_payload.get("commits", [])[-1]
        target_file = (latest_commit.get("modified") or latest_commit.get("added") or [""])[0]

        if not target_file:
            return {"error": "No code changes detected to audit."}

        # 2. In-Memory Crawl for Auditing
        sha = latest_commit.get("id")
        raw_url = f"https://raw.githubusercontent.com/{repo_name}/{sha}/{target_file}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(raw_url, headers={"Authorization": f"token {token}"})
            incoming_code = resp.text

        # 3. Vectorize Incoming Logic
        incoming_vector = self.encoder.encode(incoming_code).tolist()

        # 4. PERFORM AUDIT SCORING
        # Search Qdrant for similar logic in this specific Task vs Project
        search_results = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=incoming_vector,
            query_filter={"must": [{"key": "user_id", "match": {"value": user_id}}]},
            limit=5
        ).points

        # --- AUDIT POINT 1 & 2: INTENT (GOAL) CLASSIFICATION ---
        # Comparing incoming code against the "Task ID" context
        intent_match = [p for p in search_results if p.payload.get("task_id") == task_id]
        intent_score = intent_match[0].score if intent_match else 0.0

        goal_classification = "DEVIATED"
        if intent_score > 0.85:
            goal_classification = "PERFECT_ALIGNMENT"
        elif intent_score > 0.65:
            goal_classification = "SUBSTANTIALLY_ON_TRACK"
        elif intent_score > 0.40:
            goal_classification = "VAGUELY_RELATED"

        # --- AUDIT POINT 3 & 4: CODE EVOLUTION CLASSIFICATION ---
        # Comparing incoming code against ANY existing logic (Drift Check)
        top_overall_score = search_results[0].score if search_results else 0.0
        code_classification = "RE-ARCHITECTURE / NEW LOGIC"

        if top_overall_score > 0.98:
            code_classification = "IDENTICAL_REPLICATION"
        elif top_overall_score > 0.90:
            code_classification = "MINOR_SYNTAX_REFACTORING"
        elif top_overall_score > 0.75:
            # Check if Task IDs match to see if it's a "Same logic, different place" drift
            if search_results[0].payload.get("task_id") != task_id:
                code_classification = "LOGIC_DRIFT_DETECTION (Existing logic applied to wrong task)"
            else:
                code_classification = "LOGIC_EVOLUTION (Same intent, improved method)"
        elif top_overall_score > 0.50:
            code_classification = "SKELETON_SIMILARITY (Same domain, different purpose)"

        return {
            "intent_audit": {
                "goal_classification": goal_classification,
                "accuracy_score": round(intent_score, 4),
                "context": f"Alignment with target task '{task_id}'."
            },
            "structural_audit": {
                "code_classification": code_classification,
                "similarity_score": round(top_overall_score, 4),
                "context": f"Comparison against total repository history for Idea '{idea_id}'."
            },
            "verdict": "PROCEED_TO_INGEST" if intent_score > 0.5 else "WARNING_LOGICAL_MISMATCH"
        }