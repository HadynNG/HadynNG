# Agentic KYC Platform — System Design Document

**Version:** 3.0
**Status:** Production-Ready Architecture
**Author:** Platform Team

---

## Executive Summary

An end-to-end KYC screening platform built on an agentic AI architecture for Hong Kong's AMLO/HKMA/SFC compliance frameworks. The platform uses a **Mission Broker → MissionExecutor → LangGraph StateGraph → Agent Pipeline → Tools** architecture to provide:

- Full KYC name screening in under 3 minutes (vs 2–4 hours manual)
- LLM-powered reasoning at critical judgment points
- Complete audit trail for AMLO Section 20 compliance
- Production-ready infrastructure with PostgreSQL, Redis, MinIO, and Milvus

---

## Design Philosophy

### Orchestration with LangGraph

The pipeline uses **LangGraph** (`orchestrator/kyc_graph.py`) as the typed state graph engine:

1. **Full auditability** — every LLM call, input, and output is visible and logged; LangGraph state is serializable and checkpointed in Redis
2. **No vendor lock-in** — agents call Ollama directly; LangGraph is a thin graph runner, not a framework that owns the LLM calls
3. **Typed state** — `KYCState` TypedDict enforces what each agent reads and writes, replacing an untyped `context` dict
4. **Conditional routing** — DataCollection failure routes to documentation without running phases 2–5, ensuring an audit trail is always written
5. **Compliance-first** — rule-based decision anchoring is enforced in agent code, not delegated to the graph engine

### Two-Role Model

- **Planner** (LLM): Analyses context, generates plans, makes judgment calls
- **Executor** (LangGraph + agents): Enforces pipeline order, routes state, calls tools, applies rule-based logic

The LLM is never trusted with mechanical steps (CRM lookup, risk scoring formulas, file I/O). It is only invoked where human-like judgment is genuinely needed.

---

## System Architecture (v3.0)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     User / External Client                              │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │  HTTP / WebSocket
                ┌───────────▼────────────┐
                │    Mission Broker       │  ← FastAPI gateway (port 8000)
                │    (services/broker)    │    POST /missions, /parse, /chat
                │                        │    WS /ws/missions/{id}
                └───────────┬────────────┘
                            │
          ┌─────────────────┼─────────────────────┐
          │                 │                     │
 ┌────────▼───────┐  ┌─────▼──────────┐  ┌───────▼──────────────┐
 │  IntentParser   │  │ MissionExecutor│  │   Memory Service     │
 │  (SOP-based     │  │ + TaskPlanner  │  │   Redis (short-term)  │
 │   classifier)   │  │                │  │   Milvus (vectors)    │
 └─────────────────┘  └─────┬──────────┘  │   PostgreSQL (long)   │
                            │             └──────────────────────┘
               ┌────────────▼──────────────┐
               │  LangGraph StateGraph      │  ← orchestrator/kyc_graph.py
               │  KYCState TypedDict        │    Typed state • conditional edges
               │  graph.stream()            │    Redis checkpointer (optional)
               └────────────┬──────────────┘
                            │
        ┌───────────────────▼────────────────────────────┐
        │                Agent Pipeline                   │
        │                                                │
        │  1. DataCollectionAgent    (Steps 1.1–1.3)     │
        │  2. RiskAssessmentAgent    (Step  2.1)         │
        │  3. AereveScreeningAgent   (Steps 3.1–3.2)     │
        │  4. AlertReviewAgent       (Steps 4.1–4.3)     │  ← LLM
        │  5. DecisionAgent          (Steps 5.1–5.3)     │  ← LLM
        │  6. DocumentationAgent     (Steps 6.1–6.2)     │
        └───────────────────┬────────────────────────────┘
                            │  direct Python calls
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   CRM Tool          Identity Tool       Screening Tool

   (Tools MCP Server exposes same tools for external MCP clients — port 8101)
```

---

## Infrastructure Stack

| Component | Purpose | Port |
|-----------|---------|------|
| **PostgreSQL 16** | Audit logs (WORM), missions, customers, screening results | 5432 |
| **Redis 7** | Mission context, session cache, pub/sub, LangGraph checkpointer | 6379 |
| **MinIO** | Document storage (SOP, RAG corpus, audit reports); shared with Milvus | 9000/9001 |
| **etcd** | Milvus internal metadata store | 2379 |
| **Milvus 2.4** | Vector DB for agent memory and RAG document retrieval | 19530/9091 |
| **Ollama** | LLM inference engine (GPU-accelerated) | 11434 |

### Application Services

| Service | Purpose | Port |
|---------|---------|------|
| **Mission Broker** | FastAPI HTTP/WS gateway | 8000 |
| **Tools MCP** | External tool integrations (CRM, Identity, Screening) | 8101 |

---

## Data Flow

### Production Path
```
User Prompt
  → POST /missions (Mission Broker)
    → IntentParser (classify: KYC or chat?)
    → TaskPlanner (LLM: generate execution plan)
    → MissionExecutor (build LangGraph, drive graph.stream())
      → LangGraph StateGraph (node-by-node execution)
        → Agent.run(KYCState)
          → Tool classes (CRM, Identity, Screening — direct Python)
        → Memory Service (persist context per phase, store insights)
      → Timeline (write progress JSON after each chunk)
    → Response (mission_id, status)
```

### LangGraph State Flow
```
data_collection
    │  (ok)                │  (FAILED/ERROR)
    ▼                      ▼
risk_assessment        documentation ──▶ END
    ▼
aereve_screening
    ▼
alert_review
    ▼
decision
    ▼
documentation ──▶ END
```

### Demo Path (backward-compatible)
```
User Prompt
  → run_demo.py (CLI)
    → IntentParser (SOP-validated)
    → MissionExecutor (LangGraph graph.stream(), no infrastructure)
      → Agent Pipeline (KYCState dict)
        → Tool modules (direct Python calls)
    → Terminal output (Rich panels)
```

---

## Memory Architecture

### Three-Tier Memory Model

| Tier | Store | TTL | Purpose |
|------|-------|-----|---------|
| **Short-term** | Redis | 24h | Mission context, session state, ephemeral cache, LangGraph checkpointer |
| **Long-term** | PostgreSQL | Permanent | Audit logs, mission records, user preferences |
| **Semantic** | Milvus | Permanent | RAG document embeddings, agent memory recall |

### Agent Memory (Cross-Mission Learning)

After each phase, key insights are stored as vector embeddings in Milvus:
- Risk assessment outcomes
- Screening hit patterns
- Decision rationale

Future missions can recall relevant past insights via the MemoryManager.

### User Preferences

Stored in Redis (fast reads) and PostgreSQL (persistence):
- Default model preferences
- Risk threshold overrides
- Notification settings

---

## LangGraph Integration

### StateGraph Structure (`orchestrator/kyc_graph.py`)

```python
KYCState (TypedDict, total=False)
  customer_id, event, mission_payload, audit_log, status
  ↓ DataCollectionAgent
  customer_data, identity_verification, jurisdiction_risk
  ↓ RiskAssessmentAgent
  risk_score, risk_level, risk_narrative
  ↓ AereveScreeningAgent
  name_variants, screening_results, pep_screening, adverse_media
  ↓ AlertReviewAgent
  step_4_1, step_4_2, edd_required, edd_report
  ↓ DecisionAgent
  final_decision, step_5_1/5_2/5_3, requires_str
  ↓ DocumentationAgent
  audit_id, audit_log_file, customer_notification
```

### Streaming to WebSocket

`graph.stream()` yields `{node_name: updated_keys}` after each node completes. MissionExecutor intercepts each chunk to:
1. Complete the timeline phase with summary and key outputs
2. Persist updated context to Redis
3. Publish a real-time event for the WebSocket endpoint (`/ws/missions/{id}`)

### Checkpointing

When `redis_url` is provided at graph-build time, a `RedisSaver` checkpointer is attached. Each node's state is snapshotted by `thread_id=mission_id`. A failed mission can be resumed from its last successful node by invoking the graph with the same `thread_id`.

---

## LLM Integration

### Centralised LLM Gateway

All LLM calls route through a single `LLMGateway` service:

- **Connection pooling** — single Ollama client shared across agents
- **Request caching** — Redis-backed cache for deterministic queries
- **Token tracking** — request counts, cache hit rates, error rates
- **Safety caps** — character-level truncation prevents runaway generation

### Model Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Model | `qwen3.5:9b` | Good reasoning, fits consumer GPU |
| Temperature | 0.05 | Near-deterministic for compliance |
| Seed | 42 | Reproducible outputs |
| Repeat penalty | 1.1 | Prevents generation loops |
| Max tokens | 2048 (agents) / 4096 (planner) | Safety cap |

---

## Tools MCP Server (port 8101)

The Tools MCP Server exposes CRM, identity, and screening integrations over the Model Context Protocol for any external MCP-compatible client. Agents invoke the same underlying tool classes directly via Python during pipeline execution.

| Tool | Integration |
|------|------------|
| `crm_search`, `crm_get`, `crm_register` | CRM database |
| `identity_verify`, `identity_verify_ubo` | Government identity registry |
| `screening_screen`, `screening_adverse_media` | Sanctions / PEP / adverse media |
| `jurisdiction_risk` | FATF jurisdiction risk lookup |

---

## Document Organisation

```
storage/
├── documents/
│   ├── sop/             # Standard Operating Procedures
│   │   └── kyc_sop.md
│   ├── rag/             # RAG corpus
│   │   └── system_design.md
│   └── skills/          # Agent skill definitions
│       └── agent_skills.md
└── seeds/               # Seed data for development/testing
    ├── crm_customers.md
    ├── identity_registry.md
    ├── sanctions_pep_list.md
    ├── jurisdiction_risk.md
    └── adverse_media.md
```

---

## Database Schema

### Core Tables

- **missions** — mission records with status, plan, context, final decision
- **audit_logs** — append-only WORM table (AMLO compliance)
- **mission_phases** — per-phase timing for timeline reconstruction
- **customers** — production CRM cache with full-text search
- **screening_results** — historical hits with disposition tracking
- **user_preferences** — key-value store for user settings

See `infra/init.sql` for complete schema.

---

## Security & Compliance

### Audit Trail (AMLO Section 20)
- PostgreSQL `audit_logs` table is WORM (Write Once, Read Many)
- Database trigger prevents UPDATE/DELETE on audit records
- 5-year retention policy recorded in metadata
- LangGraph state snapshots provide additional per-phase evidence trail

### LLM Safety
- Temperature 0.05 — near-deterministic outputs
- Rule-based anchoring — LLM decisions validated against policy rules
- Conservative defaults — escalate rather than approve when uncertain
- REJECT reserved exclusively for confirmed sanctions matches

### Human-in-the-Loop
- ESCALATE_TO_MLRO decisions require human review
- STR filing requires compliance officer approval
- EDD procedures flag for senior management sign-off

---

## KYC SOP Phase Coverage

| SOP Step | Agent | Description | LLM Used |
|----------|-------|-------------|----------|
| — | IntentParser | Free-form intent classification + SOP validation | Yes |
| 1.1 | DataCollectionAgent | Event classification | Yes |
| 1.2 | DataCollectionAgent | CRM data retrieval | — |
| 1.3 | DataCollectionAgent | Identity verification | — |
| 2.1 | RiskAssessmentAgent | Risk scoring + narrative | Yes |
| 3.1 | AereveScreeningAgent | Name variant generation | — |
| 3.2 | AereveScreeningAgent | Sanctions/PEP screening | — |
| 4.1 | AlertReviewAgent | Alert triage | — |
| 4.2 | AlertReviewAgent | Match investigation | Yes |
| 4.3 | AlertReviewAgent | Enhanced Due Diligence | Yes |
| 5.1 | DecisionAgent | Final decision | Yes |
| 5.2 | DecisionAgent | MLRO escalation | Yes |
| 5.3 | DecisionAgent | STR preparation | Yes |
| 6.1 | DocumentationAgent | Audit logging | — |
| 6.2 | DocumentationAgent | Stakeholder notifications | — |

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| LLM | Ollama + qwen3.5:9b | Local inference engine |
| Orchestration | LangGraph 0.2+ | Typed StateGraph pipeline with conditional edges |
| API | FastAPI + Uvicorn | HTTP/WebSocket gateway |
| Protocol | MCP (Tools MCP Server) | External tool integrations |
| DB | PostgreSQL 16 | Structured data + audit logs (WORM) |
| Cache | Redis 7 | Context store + pub/sub + LangGraph checkpointer |
| Objects | MinIO | Document/file storage (shared with Milvus) |
| Vectors | Milvus 2.4 | Semantic memory + RAG |
| Config | pydantic-settings | Centralised configuration |
| UI | Rich | Terminal output (demo) |
| Container | Docker Compose | Multi-service orchestration |
