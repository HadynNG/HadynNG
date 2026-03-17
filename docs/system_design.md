# Agentic KYC Platform — System Design Document

**Version:** 2.0
**Status:** Production-Ready Architecture
**Author:** Platform Team

---

## Executive Summary

An end-to-end KYC screening platform built on an agentic AI architecture for Hong Kong's AMLO/HKMA/SFC compliance frameworks. The platform uses a **Mission Broker → Orchestrator → AgentZero MCP → Agent Pipeline → Tool MCP** architecture to provide:

- Full KYC name screening in under 3 minutes (vs 2–4 hours manual)
- LLM-powered reasoning at critical judgment points
- Complete audit trail for AMLO Section 20 compliance
- Production-ready infrastructure with PostgreSQL, Redis, MinIO, and Qdrant

---

## Design Philosophy

### Why No LangChain / LangGraph

1. **Full auditability** — every LLM call, input, and output is visible and logged
2. **No vendor lock-in** — swap Ollama for any OpenAI-compatible endpoint
3. **Minimal abstraction** — the code IS the documentation
4. **Compliance-first** — framework magic is unacceptable in regulated environments

### Two-Role Model

- **Planner** (LLM): Analyses context, generates plans, makes judgment calls
- **Executor** (code): Enforces pipeline order, calls tools, applies rule-based logic

The LLM is never trusted with mechanical steps (CRM lookup, risk scoring formulas, file I/O). It is only invoked where human-like judgment is genuinely needed.

---

## System Architecture (v2.0)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     User / External Client                              │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │  HTTP / WebSocket
                ┌───────────▼────────────┐
                │    Mission Broker       │  ← FastAPI gateway
                │    (services/broker)    │    POST /missions, /parse, /chat
                │                        │    WS /ws/missions/{id}
                └───────────┬────────────┘
                            │
          ┌─────────────────┼─────────────────────┐
          │                 │                     │
 ┌────────▼───────┐  ┌─────▼──────┐  ┌───────────▼──────────┐
 │  IntentParser   │  │ Orchestrator│  │   Memory Service     │
 │  (SOP-based     │  │ + Planner  │  │   Redis (short-term)  │
 │   classifier)   │  │            │  │   Qdrant (vectors)    │
 └─────────────────┘  └─────┬──────┘  │   PostgreSQL (long)   │
                            │         └──────────────────────┘
               ┌────────────▼──────────────┐
               │    AgentZero MCP Server    │  ← Central agent dispatcher
               │  (mcp_servers/agent_zero)  │    Wraps all 6 agents
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
                            │
               ┌────────────▼──────────────┐
               │    Tools MCP Server        │  ← External tool integrations
               │  (mcp_servers/tools)       │
               └────────────┬──────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   CRM Tool          Identity Tool       Screening Tool
```

---

## Infrastructure Stack

| Component | Purpose | Port |
|-----------|---------|------|
| **PostgreSQL 16** | Audit logs (WORM), missions, customers, screening results | 5432 |
| **Redis 7** | Mission context, session cache, pub/sub for real-time updates | 6379 |
| **MinIO** | Document storage (SOP, RAG corpus, audit report archives) | 9000/9001 |
| **Qdrant** | Vector DB for agent memory and RAG document retrieval | 6333/6334 |
| **Ollama** | LLM inference engine (GPU-accelerated) | 11434 |

### Application Services

| Service | Purpose | Port |
|---------|---------|------|
| **Mission Broker** | FastAPI HTTP/WS gateway | 8000 |
| **AgentZero MCP** | Central agent dispatcher (MCP protocol) | 8100 |
| **Tools MCP** | External tool integrations (MCP protocol) | 8101 |

---

## Data Flow

### Production Path
```
User Prompt
  → POST /missions (Mission Broker)
    → IntentParser (classify: KYC or chat?)
    → TaskPlanner (LLM: generate execution plan)
    → MissionExecutor (coordinate pipeline)
      → AgentZero MCP (dispatch agents)
        → Agent.run(context)
          → Tools MCP (CRM, screening, identity)
        → Memory Service (persist context, store insights)
      → Timeline (write progress JSON)
    → Response (mission_id, status)
```

### Demo Path (backward-compatible)
```
User Prompt
  → run_demo.py (CLI)
    → IntentParser (SOP-validated)
    → MissionExecutor (direct agent calls)
      → Agent Pipeline (shared context dict)
        → Tool modules (direct Python calls)
    → Terminal output (Rich panels)
```

---

## Memory Architecture

### Three-Tier Memory Model

| Tier | Store | TTL | Purpose |
|------|-------|-----|---------|
| **Short-term** | Redis | 24h | Mission context, session state, ephemeral cache |
| **Long-term** | PostgreSQL | Permanent | Audit logs, mission records, user preferences |
| **Semantic** | Qdrant | Permanent | RAG document embeddings, agent memory recall |

### Agent Memory (Cross-Mission Learning)

After each phase, key insights are stored as vector embeddings in Qdrant:
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

## LLM Integration

### Centralised LLM Gateway

All LLM calls route through a single `LLMGateway` service:

- **Connection pooling** — single Ollama client shared across agents
- **Request caching** — Redis-backed cache for deterministic queries
- **Token tracking** — request counts, cache hit rates, error rates
- **Model routing** — support for multiple models per task type
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

## MCP Architecture

### Model Context Protocol (MCP)

The platform uses MCP to decouple agent logic from tool execution:

**AgentZero MCP Server** — wraps all 6 agents as callable MCP tools:
- `run_data_collection`, `run_risk_assessment`, `run_screening`
- `run_alert_review`, `run_decision`, `run_documentation`
- `run_full_pipeline` (convenience)
- `agent_status`, `get_context`

**Tools MCP Server** — wraps external integrations:
- `crm_search`, `crm_get`, `crm_register`
- `identity_verify`, `identity_verify_ubo`
- `screening_screen`, `screening_adverse_media`
- `jurisdiction_risk`

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
| API | FastAPI + Uvicorn | HTTP/WebSocket gateway |
| Protocol | MCP (Model Context Protocol) | Agent/tool communication |
| DB | PostgreSQL 16 | Structured data + audit logs |
| Cache | Redis 7 | Context store + pub/sub |
| Objects | MinIO | Document/file storage |
| Vectors | Qdrant | Semantic memory + RAG |
| Config | pydantic-settings | Centralised configuration |
| UI | Rich | Terminal output (demo) |
| Container | Docker Compose | Orchestration |
