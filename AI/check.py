from qdrant_client import QdrantClient

import dotenv
dotenv.load_dotenv()
import os
url = os.getenv("QDRANT_URL")
api_key = os.getenv("QDRANT_API_KEY")

# Use 'url' instead of 'host' and 'port'
client = QdrantClient(
    url=url,
    api_key=api_key,
    timeout=30
)

try:
    # This forces a network request to the server
    collections = client.get_collections()
    print(f"✅ Connection successful! Total collections: {len(collections.collections)}")
except Exception as e:
    print(f"❌ Connection failed: {e}")