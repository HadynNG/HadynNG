"""
Centralised configuration — single source of truth for all services.

Uses pydantic-settings to load from environment variables (or .env file).
Every service, agent, and MCP server imports `settings` from here.
"""
from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Platform-wide configuration loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Paths ────────────────────────────────────────────────────────────────
    root_dir: Path = _ROOT
    storage_dir: Path = _ROOT / "storage"
    documents_dir: Path = _ROOT / "storage" / "documents"
    sop_dir: Path = _ROOT / "storage" / "documents" / "sop"
    rag_dir: Path = _ROOT / "storage" / "documents" / "rag"
    skills_dir: Path = _ROOT / "storage" / "documents" / "skills"
    seeds_dir: Path = _ROOT / "storage" / "seeds"

    # ── LLM / Ollama ─────────────────────────────────────────────────────────
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    llm_temperature: float = 0.05
    llm_max_tokens: int = 2048
    llm_seed: int = 42

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "hadynng"
    postgres_user: str = "hadynng"
    postgres_password: str = "changeme_in_production"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # ── MinIO ────────────────────────────────────────────────────────────────
    minio_host: str = "localhost"
    minio_port: int = 9000
    minio_console_port: int = 9001
    minio_root_user: str = "hadynng"
    minio_root_password: str = "changeme_in_production"
    minio_bucket_documents: str = "documents"
    minio_bucket_audit: str = "audit-logs"
    minio_bucket_timelines: str = "timelines"

    @property
    def minio_endpoint(self) -> str:
        return f"{self.minio_host}:{self.minio_port}"

    # ── Milvus ───────────────────────────────────────────────────────────────
    milvus_host: str = "localhost"
    milvus_port: int = 19530      # gRPC / MilvusClient port
    milvus_http_port: int = 9091  # metrics / health port
    milvus_collection_memory: str = "agent_memory"
    milvus_collection_rag: str = "rag_documents"

    # ── Mission Broker ───────────────────────────────────────────────────────
    broker_host: str = "0.0.0.0"
    broker_port: int = 8000

    # ── MCP Servers ──────────────────────────────────────────────────────────
    agent_zero_mcp_host: str = "0.0.0.0"
    agent_zero_mcp_port: int = 8100
    tools_mcp_host: str = "0.0.0.0"
    tools_mcp_port: int = 8101

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
