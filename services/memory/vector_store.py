"""
Vector Store — Qdrant-backed semantic memory for RAG and agent memory.

Uses Ollama embeddings (nomic-embed-text) for vectorisation.
Gracefully degrades to no-op if Qdrant is unavailable.
"""
import hashlib
import uuid
from typing import Optional

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False


# Default embedding model — small, fast, good for retrieval
_EMBED_MODEL = "nomic-embed-text"
_EMBED_DIM = 768


class VectorStore:
    """
    Qdrant vector store with Ollama embeddings.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        ollama_host: str = "http://localhost:11434",
        embed_model: str = _EMBED_MODEL,
    ):
        self._client: Optional[object] = None
        self._ollama_host = ollama_host
        self._embed_model = embed_model

        if _QDRANT_AVAILABLE:
            try:
                self._client = QdrantClient(host=host, port=port, timeout=5)
                # Verify connection
                self._client.get_collections()
            except Exception:
                self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    def ensure_collection(self, name: str, dim: int = _EMBED_DIM):
        """Create collection if it doesn't exist."""
        if not self._client:
            return
        try:
            collections = [c.name for c in self._client.get_collections().collections]
            if name not in collections:
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
        except Exception:
            pass

    def _embed(self, text: str) -> Optional[list[float]]:
        """Generate embedding vector using Ollama."""
        if not _OLLAMA_AVAILABLE:
            return None
        try:
            client = _ollama.Client(host=self._ollama_host)
            response = client.embed(model=self._embed_model, input=text)
            if hasattr(response, "embeddings") and response.embeddings:
                return response.embeddings[0]
            return None
        except Exception:
            return None

    def upsert(
        self,
        collection: str,
        text: str,
        metadata: Optional[dict] = None,
        point_id: Optional[str] = None,
    ):
        """Embed text and upsert into Qdrant collection."""
        if not self._client:
            return

        self.ensure_collection(collection)
        vector = self._embed(text)
        if vector is None:
            return

        pid = point_id or str(uuid.uuid4())
        # Qdrant needs UUID or int ids
        try:
            uid = uuid.UUID(pid)
        except ValueError:
            uid = uuid.UUID(hashlib.md5(pid.encode()).hexdigest())

        payload = metadata or {}
        payload["text"] = text

        try:
            self._client.upsert(
                collection_name=collection,
                points=[PointStruct(id=str(uid), vector=vector, payload=payload)],
            )
        except Exception:
            pass

    def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search in a Qdrant collection."""
        if not self._client:
            return []

        self.ensure_collection(collection)
        vector = self._embed(query)
        if vector is None:
            return []

        # Build filter
        qdrant_filter = None
        if filters and _QDRANT_AVAILABLE:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
            qdrant_filter = Filter(must=conditions)

        try:
            results = self._client.query_points(
                collection_name=collection,
                query=vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=qdrant_filter,
            )
            return [
                {"id": str(r.id), "score": r.score, **r.payload}
                for r in results.points
            ]
        except Exception:
            return []

    def health_check(self) -> dict:
        if self._client:
            try:
                collections = self._client.get_collections()
                return {
                    "status": "ok",
                    "collections": [c.name for c in collections.collections],
                }
            except Exception as e:
                return {"status": "error", "error": str(e)}
        return {"status": "unavailable", "note": "Qdrant not connected"}
