"""
Vector Store — Milvus-backed semantic memory for RAG and agent recall.

Uses pymilvus MilvusClient (2.4+ simplified API) for collection management,
upsert, and semantic search.  Uses Ollama embeddings (nomic-embed-text).
Gracefully degrades to no-op if Milvus or Ollama is unavailable.

Collections:
  agent_memory   — per-agent insight embeddings for cross-mission recall
  rag_documents  — chunked SOP / corpus for RAG retrieval
"""
import hashlib
import uuid
from typing import Optional

try:
    from pymilvus import MilvusClient, DataType
    _MILVUS_AVAILABLE = True
except ImportError:
    _MILVUS_AVAILABLE = False

try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False


# Default embedding model
_EMBED_MODEL = "nomic-embed-text"
_EMBED_DIM   = 768


class VectorStore:
    """
    Milvus vector store with Ollama embeddings.

    All public methods are no-ops when Milvus or the embedding model is
    unavailable, so the platform degrades gracefully in demo mode.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        ollama_host: str = "http://localhost:11434",
        embed_model: str = _EMBED_MODEL,
    ):
        self._ollama_host  = ollama_host
        self._embed_model  = embed_model
        self._client: Optional[object] = None

        if _MILVUS_AVAILABLE:
            try:
                uri = f"http://{host}:{port}"
                self._client = MilvusClient(uri=uri)
                # Verify connection by listing collections
                self._client.list_collections()
            except Exception:
                self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    # ── Collection management ──────────────────────────────────────────────

    def ensure_collection(self, name: str, dim: int = _EMBED_DIM):
        """Create a Milvus collection if it does not already exist."""
        if not self._client:
            return
        try:
            existing = self._client.list_collections()
            if name not in existing:
                self._client.create_collection(
                    collection_name=name,
                    dimension=dim,
                    metric_type="COSINE",
                    auto_id=False,
                )
        except Exception:
            pass

    # ── Embedding ──────────────────────────────────────────────────────────

    def _embed(self, text: str) -> Optional[list[float]]:
        """Generate a vector embedding via Ollama."""
        if not _OLLAMA_AVAILABLE:
            return None
        try:
            client   = _ollama.Client(host=self._ollama_host)
            response = client.embed(model=self._embed_model, input=text)
            if hasattr(response, "embeddings") and response.embeddings:
                return response.embeddings[0]
            return None
        except Exception:
            return None

    # ── Write ──────────────────────────────────────────────────────────────

    def upsert(
        self,
        collection: str,
        text: str,
        metadata: Optional[dict] = None,
        point_id: Optional[str] = None,
    ):
        """Embed *text* and upsert into a Milvus collection."""
        if not self._client:
            return

        self.ensure_collection(collection)
        vector = self._embed(text)
        if vector is None:
            return

        pid = point_id or str(uuid.uuid4())
        try:
            uid = str(uuid.UUID(pid))
        except ValueError:
            uid = str(uuid.UUID(hashlib.md5(pid.encode()).hexdigest()))

        payload = dict(metadata or {})
        payload["text"] = text

        try:
            self._client.upsert(
                collection_name=collection,
                data=[{"id": uid, "vector": vector, **payload}],
            )
        except Exception:
            pass

    # ── Read ───────────────────────────────────────────────────────────────

    def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search in a Milvus collection."""
        if not self._client:
            return []

        self.ensure_collection(collection)
        vector = self._embed(query)
        if vector is None:
            return []

        # Build Milvus filter expression
        expr = None
        if filters:
            parts = [f'{k} == "{v}"' if isinstance(v, str) else f"{k} == {v}"
                     for k, v in filters.items()]
            expr = " && ".join(parts)

        try:
            results = self._client.search(
                collection_name=collection,
                data=[vector],
                limit=top_k,
                filter=expr,
                output_fields=["text", *list((filters or {}).keys())],
                search_params={"metric_type": "COSINE"},
            )
            hits = results[0] if results else []
            return [
                {
                    "id":     h["id"],
                    "score":  h["distance"],
                    **h["entity"],
                }
                for h in hits
                if h["distance"] >= score_threshold
            ]
        except Exception:
            return []

    # ── Health ─────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        if self._client:
            try:
                collections = self._client.list_collections()
                return {"status": "ok", "collections": collections}
            except Exception as e:
                return {"status": "error", "error": str(e)}
        return {"status": "unavailable", "note": "Milvus not connected"}
