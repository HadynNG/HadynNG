# HadynNG KYC Screening Platform — Technical Stack

**Document Type:** Technical Reference
**System:** HadynNG Agentic KYC Name Screening Platform
**Date:** 2026-04-10
**Audience:** Engineers, architects, compliance technology teams

---

## 1. Overview

HadynNG is a production-ready, AI-powered KYC (Know Your Customer) name screening platform designed for Hong Kong's regulatory frameworks (AMLO Cap. 615, HKMA AML/CFT Guidelines, SFC AML Circular, FATF). It combines rule-based compliance logic with LLM-powered reasoning across a 6-phase agentic pipeline.

The proposed production upgrade replaces the custom sequential executor with **LangGraph** (typed state graph orchestration) and **AgentField** (infrastructure control plane), while preserving all existing agent logic.

---

## 2. Runtime & Language

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| Primary Language | Python | 3.12 | All backend services, agents, orchestration |
| ASGI Server | Uvicorn | 0.27+ | Serves the FastAPI application |
| Package Manager | pip | Latest | Dependency management |

---

## 3. Application Framework

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| HTTP & WebSocket API | FastAPI | 0.110+ | Mission Broker gateway — REST endpoints + WebSocket live updates |
| Data Validation | Pydantic | 2.5+ | Request/response schema validation, settings models |
| Configuration | pydantic-settings | 2.1+ | Environment-variable-based configuration binding |
| Env Loading | python-dotenv | 1.0+ | `.env` file loading |
| Async HTTP Client | httpx | 0.27+ | Inter-service and Ollama API calls |

---

## 4. Agent Communication Protocol

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| Agent Protocol | MCP (Model Context Protocol) | 1.0+ | Standardised message passing between the orchestrator, agents, and tools |
| Agent Dispatcher | AgentZero MCP Server | Internal | Central dispatcher routing missions to the 6-agent pipeline (port 8100) |
| Tool Server | Tools MCP Server | Internal | Exposes CRM, Identity, and Screening tools over MCP (port 8101) |

MCP decouples tool invocation from agent logic, enabling any MCP-compatible client to call into the platform without code changes.

---

## 5. LLM & Inference

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| LLM Runtime | Ollama | 0.4.0+ | Local LLM inference server; GPU-accelerated if available |
| Default Model | qwen3.5:9b | Latest | Primary reasoning model for all LLM-powered agent steps |
| LLM Gateway | Internal `llm_gateway/gateway.py` | Internal | Caching proxy that wraps Ollama calls with retry logic and response caching |

### LLM Inference Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Temperature | 0.05 | Near-deterministic output for compliance reproducibility |
| Max Tokens (agents) | 2048 | Sufficient for reasoning + structured JSON output |
| Max Tokens (planner) | 4096 | Extended budget for mission planning |
| Seed | 42 | Reproducible outputs across identical inputs |

---

## 6. Data Storage

### 6.1 Relational Database

| Property | Value |
|----------|-------|
| Technology | PostgreSQL |
| Version | 16 (alpine) |
| Port | 5432 |
| ORM/Driver | asyncpg, SQLAlchemy (async) |
| Purpose | Missions, audit logs, screening results, customers, user preferences |

Key design decisions:
- **WORM audit logs**: A PostgreSQL trigger on `audit_logs` prevents `UPDATE` and `DELETE`, enforcing write-once semantics required by AMLO Section 20.
- **JSONB columns**: Used for `plan`, `context`, `metadata` fields to accommodate flexible agent outputs without schema migrations.
- **Full-text search**: GIN index on `customers.name` for fast name lookups.
- **5-year retention**: Audit records are designed for long-term regulatory retention.

#### Core Tables

| Table | Purpose |
|-------|---------|
| `missions` | Master record per screening mission; holds status, plan, final decision |
| `audit_logs` | Immutable AMLO compliance log; one row per significant event |
| `mission_phases` | Per-phase timing and result storage for timeline reconstruction |
| `customers` | CRM data cache with aliases (JSONB) and full-text search index |
| `screening_results` | Historical sanctions/PEP hits with confidence score and disposition |
| `user_preferences` | Key-value settings store (JSONB values) |

### 6.2 In-Memory Cache & Pub/Sub

| Property | Value |
|----------|-------|
| Technology | Redis |
| Version | 7 (alpine) |
| Port | 6379 |
| Purpose | Mission context cache, short-term session data, pub/sub event bus |
| TTL | 24 hours (mission context) |

### 6.3 Object Storage

| Property | Value |
|----------|-------|
| Technology | MinIO |
| Version | Latest (RELEASE.2024+) |
| Ports | 9000 (S3 API), 9001 (Console UI) |
| Client Library | minio 7.2+ |
| Purpose | Documents (SOP, RAG corpus, audit reports, timelines) |
| Interface | S3-compatible API |

Buckets:
- `kyc-documents` — SOP, agent skills, RAG corpus
- `kyc-reports` — Generated audit and decision reports
- `kyc-timelines` — Mission timeline snapshots

> **Note:** Milvus (Section 6.4) also uses MinIO as its internal log and index storage backend. The same MinIO instance is shared via a dedicated bucket (`milvus-storage`), eliminating redundant object store infrastructure.

### 6.4 Vector Database

| Property | Value |
|----------|-------|
| Technology | Milvus |
| Version | 2.4+ (Standalone) |
| Ports | 19530 (gRPC), 9091 (HTTP / metrics) |
| Client Library | pymilvus 2.4+ |
| Purpose | Semantic agent memory, RAG document retrieval, SOP chunked search |
| Internal Dependencies | etcd (metadata), MinIO (index + log storage) |

Collections:

| Collection | Purpose |
|------------|---------|
| `agent_memory` | Per-agent insight embeddings for cross-mission recall |
| `kyc_sop_chunks` | Chunked SOP text for RAG retrieval during intent parsing |
| `system_design_corpus` | Platform documentation embeddings for chatbot context |

**Why Milvus over pgvector:**
- Dedicated vector engine: HNSW and IVF_FLAT index types with GPU acceleration
- Horizontal scaling: Milvus cluster mode scales vector search independently of PostgreSQL
- Collection isolation: each logical store (agent memory, SOP, corpus) is a first-class collection with its own index tuning
- Billion-scale support: future-proof for expanding screening databases without RDBMS coupling

**Milvus Standalone dependencies added to Docker Compose:**

| Service | Image | Purpose |
|---------|-------|---------|
| `etcd` | quay.io/coreos/etcd:v3.5 | Milvus metadata store |
| `milvus` | milvusdb/milvus:v2.4-latest | Vector search engine |

---

## 7. Infrastructure & Containerisation

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| Containerisation | Docker | 24+ | Package each service as an isolated container |
| Orchestration | Docker Compose | 2.0+ | Multi-service startup, networking, health checks, volumes |
| Base Image | python:3.12-slim | — | Minimal production Python container |

### Service Topology

| Service | Image | Port(s) | Health Check |
|---------|-------|---------|-------------|
| `postgres` | postgres:16-alpine | 5432 | `pg_isready` |
| `redis` | redis:7-alpine | 6379 | `redis-cli ping` |
| `minio` | minio:latest | 9000, 9001 | `/minio/health/live` |
| `etcd` | quay.io/coreos/etcd:v3.5 | 2379 | etcd health endpoint |
| `milvus` | milvusdb/milvus:v2.4-latest | 19530, 9091 | `/healthz` |
| `ollama` | ollama/ollama:latest | 11434 | `/api/version` |
| `minio-init` | minio/mc:latest | — | Bucket init job (exits) |
| `mission-broker` | Local Dockerfile | 8000 | `/health` |
| `agent-zero-mcp` | Local Dockerfile | 8100 | MCP handshake |
| `tools-mcp` | Local Dockerfile | 8101 | MCP handshake |

All services share a Docker network (`kyc-network`) and use named volumes for data persistence.

---

## 8. Memory Architecture

The platform uses a three-tier memory model:

| Tier | Store | Persistence | Purpose |
|------|-------|------------|---------|
| Short-term | Redis | 24h TTL | Active mission context, session cache, LLM response cache |
| Long-term | PostgreSQL | Permanent | Audit logs, mission records, screening history, user preferences |
| Semantic | Milvus | Permanent | Agent memory embeddings, RAG retrieval, SOP chunked search |

---

## 9. Proposed Orchestration — LangGraph + AgentField

This section describes the planned upgrade path for the orchestration layer. **No code changes have been made yet.** The current executor (`orchestrator/mission_executor.py`) remains in place.

### 9.1 LangGraph (Orchestration Engine)

| Property | Value |
|----------|-------|
| Technology | LangGraph |
| Version | 0.2+ |
| Role | Replaces the custom `PIPELINE_ORDER` for-loop with a typed `StateGraph` |
| State Schema | `KYCState` TypedDict (typed version of current `context` dict) |
| Persistence | Redis checkpointer (replaces manual `memory.update_context()` calls) |
| Streaming | `graph.stream()` replaces manual `memory.publish_event()` per phase |

**How chaining works:** Each of the 6 agents becomes a node function `(state: KYCState) -> dict`. The node returns only the keys it updated. LangGraph merges those keys into the shared state before calling the next node. `graph.invoke(initial_state)` runs the full pipeline and returns the final merged state.

**Branching:** Conditional edges (e.g. skip EDD for LOW-risk cases, fast-path REJECT on confirmed sanctions) are declared with `add_conditional_edges()`. No agent sees any other agent's internal code — only the shared state.

**Result delivery to caller:**
- Synchronous: `final_state = graph.invoke(initial)` — blocks until `END`, returns complete state dict
- Streaming: `for chunk in graph.stream(initial)` — yields `{node_name: updated_keys}` after each node; FastAPI WebSocket publishes each chunk to the client in real time

### 9.2 AgentField (Infrastructure Control Plane)

| Property | Value |
|----------|-------|
| Technology | AgentField |
| Role | Managed deployment, monitoring, versioning, and visual editing of LangGraph pipelines |
| Deployment | One-click deploy of compiled LangGraph graph to managed endpoint |
| Observability | Built-in run history, per-node latency, token cost per mission |
| Version control | Agent and graph versioning; rollback without infra changes |
| Visual editor | Drag-drop graph builder; non-engineer compliance team can inspect pipeline topology |

### 9.3 Responsibility Split

| Concern | Handled by |
|---------|-----------|
| KYC agent logic (6 agents) | Existing Python agent classes — unchanged |
| State schema and node wiring | LangGraph `StateGraph` |
| Mission persistence / checkpointing | LangGraph Redis checkpointer |
| Real-time updates to WebSocket | `graph.stream()` loop in FastAPI broker |
| Tool invocation (CRM, screening) | Tools MCP server — unchanged |
| Infrastructure deployment and monitoring | AgentField |
| Vector memory (RAG, agent recall) | Milvus — called from inside node functions |
| WORM audit logs | PostgreSQL — called from inside `documentation_node` |

---

## 10. Agent Architecture

Six specialised agents execute sequentially within a mission, each corresponding to a step in the KYC SOP:

| Agent | SOP Steps | LLM-Powered | Primary Responsibility |
|-------|----------|-------------|----------------------|
| `DataCollectionAgent` | 1.1 – 1.3 | Yes (step 1.1) | Event classification, CRM retrieval, identity verification |
| `RiskAssessmentAgent` | 2.1 | Yes | Jurisdiction + PEP risk scoring + narrative |
| `AereveScreeningAgent` | 3.1 – 3.2 | No | Name variant generation, sanctions/PEP database screening |
| `AlertReviewAgent` | 4.1 – 4.3 | Yes (4.2, 4.3) | Alert triage, match investigation, Enhanced Due Diligence |
| `DecisionAgent` | 5.1 – 5.3 | Yes | Final decision, MLRO dossier, STR preparation |
| `DocumentationAgent` | 6.1 – 6.2 | No | AMLO audit logging, stakeholder notifications |

### Orchestration Layer

| Component | File | Role |
|-----------|------|------|
| `IntentParser` | `orchestrator/intent_parser.py` | LLM-based free-form prompt → structured mission intent |
| `TaskPlanner` | `orchestrator/task_planner.py` | LLM-based mission plan generation (which steps to execute) |
| `MissionExecutor` | `orchestrator/mission_executor.py` | Sequentially drives agents, persists phase results, updates status |
| `MissionTimeline` | `orchestrator/mission_timeline.py` | Real-time phase event tracker for WebSocket streaming |

---

## 11. External Tool Integrations (Mock → Production-Ready)

| Tool | File | Data Source | Purpose |
|------|------|-------------|---------|
| CRM Tool | `tools/crm_tool.py` | `storage/seeds/crm_customers.md` | Customer record lookup by name/ID |
| Identity Tool | `tools/identity_tool.py` | `storage/seeds/identity_registry.md` | HKID / passport verification |
| Screening Tool | `tools/screening_tool.py` | `storage/seeds/sanctions_pep_list.md`, `jurisdiction_risk.md`, `adverse_media.md` | UN/OFAC/EU/HKMA sanctions, PEP list, adverse media |

All tools run in mock mode by default (file-backed). Replacing the data source with a live API connection upgrades to production without changing agent code.

---

## 12. Terminal UI (Demo Mode)

| Component | Technology | Version | Role |
|-----------|-----------|---------|------|
| Rich terminal rendering | Rich | 13.7+ | Coloured panels, progress spinners, tables for CLI demo output |

---

## 13. Configuration System

All configuration is managed through environment variables bound to a Pydantic settings model (`config/settings.py`). No hardcoded credentials or endpoints exist in source code.

| Category | Example Variables |
|----------|-----------------|
| LLM | `OLLAMA_HOST`, `OLLAMA_MODEL`, `LLM_TEMPERATURE`, `LLM_SEED` |
| PostgreSQL | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| Redis | `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` |
| MinIO | `MINIO_HOST`, `MINIO_PORT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` |
| Milvus | `MILVUS_HOST`, `MILVUS_PORT`, `MILVUS_GRPC_PORT` |
| Services | `BROKER_HOST`, `BROKER_PORT`, `AGENT_ZERO_MCP_HOST`, `TOOLS_MCP_HOST` |
| Logging | `LOG_LEVEL` |

---

## 14. Regulatory Compliance Framework

| Regulation | Jurisdiction | Coverage |
|-----------|-------------|---------|
| AMLO (Cap. 615) | Hong Kong | Full audit trail, WORM logs, 5-year retention |
| HKMA AML/CFT Guidelines | Hong Kong | EDD triggers, risk-based approach, MLRO escalation |
| SFC AML Circular | Hong Kong | Securities-specific screening requirements |
| FATF High-Risk Jurisdictions | International | Jurisdiction risk scoring, enhanced scrutiny for monitored countries |
| UN Consolidated List | International | Sanctions screening |
| OFAC SDN List | USA | Sanctions screening |
| EU Consolidated List | EU | Sanctions screening |

---

## 15. API Surface

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/parse` | POST | Parse free-form prompt → mission intent |
| `/missions` | POST | Create and start a screening mission |
| `/missions/{id}` | GET | Poll mission status and results |
| `/chat` | POST | Compliance chatbot (RAG-backed) |
| `/ws/missions/{id}` | WebSocket | Real-time phase update stream |

---

## 16. Service Port Reference

| Service | Host Port | Protocol |
|---------|-----------|---------|
| Mission Broker (API Gateway) | 8000 | HTTP / WebSocket |
| AgentZero MCP Server | 8100 | HTTP (MCP) |
| Tools MCP Server | 8101 | HTTP (MCP) |
| Ollama (LLM) | 11434 | HTTP |
| PostgreSQL | 5432 | TCP |
| Redis | 6379 | TCP |
| MinIO S3 API | 9000 | HTTP |
| MinIO Console | 9001 | HTTP |
| etcd | 2379 | HTTP |
| Milvus gRPC | 19530 | gRPC |
| Milvus HTTP / Metrics | 9091 | HTTP |

---

## 17. Python Dependency Summary

```
# Core Framework
fastapi>=0.110.0
uvicorn>=0.27.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.0

# Agent Protocol
mcp>=1.0.0

# LLM
ollama>=0.4.0

# Orchestration (proposed upgrade)
langgraph>=0.2.0

# Storage Clients
asyncpg>=0.29.0
sqlalchemy>=2.0.0
redis>=5.0.0
minio>=7.2.0
pymilvus>=2.4.0

# Async & HTTP
httpx>=0.27.0
aiofiles>=23.0.0

# Terminal UI (demo)
rich>=13.7.0
```

---

## 18. Production Readiness Gap Assessment

Current implementation status versus production requirements, with estimated backend engineering effort.

| Layer | Current State | Production Gap | Backend Effort |
|-------|--------------|----------------|---------------|
| **FastAPI gateway** | Skeleton with routes, no auth, no rate limiting | Auth (JWT/OAuth2), RBAC, rate limiting, request validation, API versioning (`/v1/`), CORS policy | Medium |
| **PostgreSQL** | Schema ready (`infra/init.sql`), no actual DB calls wired | SQLAlchemy async models, CRUD service layer, connection pooling (asyncpg), Alembic migrations | Heavy |
| **Redis** | Client wrapper with fallback, basic get/set/pub | Cluster mode, persistence config (AOF/RDB), password auth, TTL tuning per key type | Light |
| **MinIO** | Bucket creation in docker-compose, no upload/download code | File upload/download service, pre-signed URL generation, lifecycle policies, virus scan hook | Medium |
| **Milvus** | Wrapper with embedding + search, graceful fallback | Collection management, HNSW index tuning, embedding pipeline for SOP/RAG corpus ingestion, etcd HA | Medium |
| **Ollama** | Works end-to-end, LLM Gateway with caching | Model warm-up script, health monitoring, GPU memory management, fallback model routing | Light |
| **AgentZero MCP** | Fully defined tools, agents callable | Production stdio → HTTP/SSE transport, bearer token auth, structured logging, connection pool | Medium |
| **Tools MCP** | Fixed and working | Same transport + auth needs as AgentZero MCP | Medium |
| **Docker Compose** | Complete with health checks | Resource limits (`mem_limit`, `cpus`), log drivers (json-file / fluentd), secrets management, network segmentation | Light |
| **CI/CD** | None | GitHub Actions pipeline, image registry (GHCR/ECR), staging + prod environments, automated rollback | Medium |
| **Observability** | Audit logs + timeline JSON files | Prometheus metrics (FastAPI + Milvus + Redis exporters), structured JSON logging, Grafana dashboards, PagerDuty alerting | Medium |
| **Security** | No auth, no encryption, no secrets management | JWT/OAuth2 on all endpoints, TLS termination (nginx/Traefik), HashiCorp Vault for secrets, input sanitisation, OWASP scan | Heavy |

**Effort legend:** Light = 1–3 days, Medium = 3–7 days, Heavy = 1–2+ weeks.

**Heaviest items** (PostgreSQL + Security) are prerequisites for any production deployment. All others can be phased in post-launch.

---

## 19. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Local LLM (Ollama) instead of cloud API | Data sovereignty; no PII leaves the on-premise environment |
| MCP for agent/tool communication | Vendor-neutral protocol; swap tools or agents without breaking contracts |
| Near-zero LLM temperature (0.05) | Compliance requires reproducible, deterministic reasoning |
| WORM PostgreSQL trigger | Prevents post-hoc tampering with audit logs; satisfies AMLO evidence requirements |
| Rule-based decision anchoring | LLM reasoning overlays rules but cannot override them; sanctions = REJECT always |
| Three-tier memory (Redis / PostgreSQL / Milvus) | Redis for speed, PostgreSQL for durability, Milvus for semantic retrieval at scale |
| Milvus over pgvector | Dedicated vector engine with horizontal scaling, GPU-accelerated HNSW indexing, and collection-level isolation; pgvector couples vector workload to OLTP database |
| Mock-first tool design | All tools work with flat-file seed data, enabling offline development and testing without external API credentials |
| LangGraph for orchestration (proposed) | Formalises the existing `context` dict as a typed `KYCState`; adds conditional branching, built-in checkpointing, and streaming without changing agent class code |
| AgentField as control plane (proposed) | Offloads deployment, run tracing, and pipeline versioning to a managed layer; compliance team can inspect graph topology without reading code |
