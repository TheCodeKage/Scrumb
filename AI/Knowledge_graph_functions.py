import os
import uuid
import ast_creater
import logging

import networkx as nx
from datetime import datetime
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType

# Configuration
COLLECTION_NAME = "scrumb_symbols"

from sentence_transformers import SentenceTransformer

_encoder = None

def get_encoder():
    global _encoder
    if _encoder is None:
        # MiniLM is ideal for the LOQ's CPU/RAM balance
        _encoder = SentenceTransformer('all-MiniLM-L6-v2')
    return _encoder
class ScrumbEngine:
    def __init__(self, user_id, encoder):
        self.user_id = user_id
        self.encoder = encoder
        qdrant_url = os.getenv("QDRANT_URL")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")


        if not qdrant_url or "cloud.qdrant.io" not in qdrant_url:
            print("⚠️ WARNING: QDRANT_URL is missing or local. Attempting local connection...")

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
        """Ensures Qdrant is indexed for high-speed keyword filtering."""
        try:
            collections = self.client.get_collections().collections
            if not any(c.name == COLLECTION_NAME for c in collections):
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
            # Critical for 'audit_intent' performance and stability
            self.client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="user_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as e:
            logging.error(f"Database Initialization Failed: {e}")

    # --- APPROACH 1: THE SEED (Skeleton) ---
    def seed_project(self, idea_id, project_name, tasks):
        """Builds the logical hierarchy."""
        self.G.add_node(idea_id, type="idea", name=project_name)
        self.G.add_edge(self.user_id, idea_id, relation="OWNS")
        for task in tasks:
            self.G.add_node(task['id'], type="task", title=task['title'])
            self.G.add_edge(idea_id, task['id'], relation="HAS_TASK")
        return {"status": "seeded", "idea_id": idea_id}

    # --- APPROACH 2 & 3: THE INGESTION (Flesh) ---
    def ingest_code_context(self, task_id, idea_id, github_payload, ast_json):
        """
        Maps symbols to Files, Commits, and Tasks with high precision.
        github_payload: { commit_hash, file_path, branch }
        """
        commit_hash = github_payload.get('commit_hash', 'local')
        file_path = github_payload.get('file_path', 'unknown')

        # 1. Update Structural Graph
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
            # Unique ID prevents duplicate symbols if re-ingested
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{self.user_id}_{file_path}_{symbol_name}"))

            # 3. Update the context string and payload to use symbol_name
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
                    "symbol_name": sym['name'],
                    "commit": commit_hash
                }
            ))

        if points:
            self.client.upsert(collection_name=COLLECTION_NAME, points=points)
        return len(points)

    def audit_intent(self, active_task_id, current_file, current_symbol):
        """
        High-precision auditor.
        Checks if current development aligns with the intended task.
        """
        # 1. Prepare search string
        search_text = f"File: {current_file} | Symbol: {current_symbol['name']} | Logic: {current_symbol.get('docstring', '')}"
        query_vector = self.encoder.encode(search_text).tolist()

        # 2. Query Cloud Vector DB
        results = self.client.query_points(
            collection_name="scrumb_symbols",
            query=query_vector,
            query_filter={"must": [{"key": "user_id", "match": {"value": self.user_id}}]},
            limit=3
        ).points

        if not results:
            return {"status": "NEW_CODE", "message": "First time seeing this logic."}

        top = results[0]
        score = round(top.score, 3)

        # --- LOGIC GATES ---

        # GATE 1: Low Confidence (New territory)
        if score < 0.45:
            return {
                "status": "NEW_CODE",
                "confidence": score,
                "message": "Logic is significantly different from existing context."
            }

        # GATE 2: High Confidence + Correct Task
        if top.payload.get('task_id') == active_task_id:
            return {
                "status": "ON_TRACK",
                "confidence": score,
                "message": f"Verified: Logic aligns with {active_task_id}."
            }

        # GATE 3: High Confidence + Wrong Task (The "Drift")
        return {
            "status": "DRIFT_DETECTED",
            "confidence": score,
            "suggested_task": top.payload.get('task_id'),
            "message": f"Intent matches '{top.payload.get('task_id')}' better than your current task."
        }