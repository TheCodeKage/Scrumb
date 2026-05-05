import json
import logging
from typing import Dict, Optional
from Knowledge_graph_functions import ScrumbEngine, COLLECTION_NAME
logger = logging.getLogger("ScrumbReasoning")
class ScrumbBrain:
    def __init__(self, user_id: str):
        self.engine = ScrumbEngine(user_id)
    async def get_aware_response(self, idea_id: str, message: str) -> Dict:
        query_vector = self.engine.encoder.encode(message).tolist()
        try:
            matches = self.engine.client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                query_filter={"must": [{"key": "idea_id", "match": {"value": idea_id}}]},
                limit=5
            ).points
        except Exception as e:
            logger.error(f"KG Retrieval Failed: {e}")
            matches = []
        context_blocks = []
        for m in matches:
            node_type = m.payload.get('node_type', 'unknown')
            symbol = m.payload.get('symbol_name', 'Task/Root')
            content = m.payload.get('content', '')
            context_blocks.append(f"[{node_type.upper()}] {symbol}: {content}")
        context_str = "\n---\n".join(context_blocks)
        system_prompt = f"""
                You are 'Scrumb-Brain', an expert coding assistant.
                Use the following code context to answer the user.

                CONTEXT:
                {context_str}

                USER QUESTION: {message}

                ANSWER GUIDELINES:
                1. If the answer is in the context, be specific.
                2. If not, say you don't have that information yet.
                3. Do not make up code.
                """

        result = await self.engine._reason_with_ollama(system_prompt)

        # Now result.get("response") will contain the actual text
        answer_text = result.get("response") or "The brain returned an empty thought."

        return {
            "answer": answer_text,
            "source_nodes": [m.payload.get('symbol_name', 'N/A') for m in matches],
            "context_found": len(matches) > 0
        }