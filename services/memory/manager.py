"""
Memory Manager — coordinates short-term and long-term memory for agents.

Memory tiers:
  1. Short-term (Redis): Mission context, session state, ephemeral cache.
     TTL-based eviction. Keyed by mission_id.
  2. Long-term (PostgreSQL): User preferences, historical decisions,
     structured records. Persistent, queryable.
  3. Semantic (Milvus): Vector embeddings for RAG document retrieval
     and agent memory recall. Similarity search.
"""
from datetime import datetime
from typing import Any, Optional

from .redis_store import RedisStore
from .vector_store import VectorStore


class MemoryManager:
    """
    Unified memory interface for all agents and services.

    Usage:
        memory = MemoryManager(redis_url=..., milvus_host=...)
        # Short-term
        memory.set_context("mission-123", {"status": "IN_PROGRESS", ...})
        ctx = memory.get_context("mission-123")
        # Long-term preferences
        memory.set_preference("user-1", "default_model", "qwen3.5:9b")
        model = memory.get_preference("user-1", "default_model")
        # Semantic search
        memory.store_memory("agent_memory", text, metadata)
        results = memory.recall("sanctions screening procedure", top_k=5)
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        milvus_host: str = "localhost",
        milvus_port: int = 19530,
        postgres_dsn: Optional[str] = None,
    ):
        self.redis = RedisStore(redis_url)
        self.vector = VectorStore(host=milvus_host, port=milvus_port)
        self._postgres_dsn = postgres_dsn

    # ── Short-term Memory (Redis) ────────────────────────────────────────────

    def set_context(self, mission_id: str, context: dict, ttl: int = 86400):
        """Store mission context in Redis. Default TTL: 24 hours."""
        self.redis.set_json(f"mission:{mission_id}:context", context, ttl=ttl)

    def get_context(self, mission_id: str) -> Optional[dict]:
        """Retrieve mission context from Redis."""
        return self.redis.get_json(f"mission:{mission_id}:context")

    def update_context(self, mission_id: str, updates: dict, ttl: int = 86400):
        """Merge updates into existing mission context."""
        ctx = self.get_context(mission_id) or {}
        ctx.update(updates)
        self.set_context(mission_id, ctx, ttl=ttl)

    def delete_context(self, mission_id: str):
        """Remove mission context from Redis."""
        self.redis.delete(f"mission:{mission_id}:context")

    # ── Session & Cache (Redis) ──────────────────────────────────────────────

    def cache_set(self, key: str, value: Any, ttl: int = 3600):
        """Generic cache set with TTL."""
        self.redis.set_json(f"cache:{key}", value, ttl=ttl)

    def cache_get(self, key: str) -> Optional[Any]:
        """Generic cache get."""
        return self.redis.get_json(f"cache:{key}")

    def publish_event(self, channel: str, event: dict):
        """Publish event via Redis pub/sub (for real-time UI updates)."""
        self.redis.publish(channel, event)

    # ── User Preferences (Redis + PostgreSQL) ────────────────────────────────

    def set_preference(self, user_id: str, key: str, value: Any):
        """Store a user preference. Cached in Redis, persisted in PostgreSQL."""
        # Redis (fast reads)
        self.redis.set_json(f"pref:{user_id}:{key}", value, ttl=0)
        # PostgreSQL persistence would happen via the broker service

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        """Retrieve a user preference."""
        result = self.redis.get_json(f"pref:{user_id}:{key}")
        return result if result is not None else default

    def get_all_preferences(self, user_id: str) -> dict:
        """Retrieve all preferences for a user from Redis."""
        return self.redis.get_by_prefix(f"pref:{user_id}:")

    # ── Semantic Memory (Qdrant) ─────────────────────────────────────────────

    def store_memory(
        self,
        collection: str,
        text: str,
        metadata: Optional[dict] = None,
        memory_id: Optional[str] = None,
    ):
        """Store a text memory with vector embedding in Qdrant."""
        meta = metadata or {}
        meta["stored_at"] = datetime.utcnow().isoformat() + "Z"
        self.vector.upsert(collection, text, metadata=meta, point_id=memory_id)

    def recall(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Recall memories similar to the query from Qdrant."""
        return self.vector.search(
            collection, query, top_k=top_k,
            score_threshold=score_threshold, filters=filters,
        )

    def store_rag_document(self, text: str, source: str, metadata: Optional[dict] = None):
        """Store a RAG document chunk in the rag_documents collection."""
        meta = metadata or {}
        meta["source"] = source
        self.store_memory("rag_documents", text, metadata=meta)

    def search_rag(self, query: str, top_k: int = 5) -> list[dict]:
        """Search RAG document store."""
        return self.recall("rag_documents", query, top_k=top_k)

    # ── Agent Memory (cross-mission learning) ────────────────────────────────

    def store_agent_insight(
        self,
        agent_name: str,
        mission_id: str,
        insight: str,
        metadata: Optional[dict] = None,
    ):
        """Store an agent's insight/learning for future recall."""
        meta = metadata or {}
        meta.update({"agent": agent_name, "mission_id": mission_id})
        self.store_memory("agent_memory", insight, metadata=meta)

    def recall_agent_insights(
        self,
        agent_name: str,
        query: str,
        top_k: int = 3,
    ) -> list[dict]:
        """Recall relevant past insights for an agent."""
        return self.recall(
            "agent_memory", query, top_k=top_k,
            filters={"agent": agent_name},
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        return {
            "redis":  self.redis.health_check(),
            "milvus": self.vector.health_check(),
        }
