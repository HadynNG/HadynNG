# Agentic KYC Platform

A production-ready agentic AI platform for **KYC (Know Your Customer) Name Screening**, built for Hong Kong's AMLO/HKMA/SFC compliance frameworks.

**Architecture:** Mission Broker → Orchestrator → AgentZero MCP → Agent Pipeline → Tool MCP → Tools

**Stack:** Ollama + qwen3.5:9b | FastAPI | MCP | PostgreSQL | Redis | MinIO | Qdrant

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    User / External Client                            │
└────────────────────────────┬─────────────────────────────────────────┘
                             │  HTTP / WebSocket
                 ┌───────────▼───────────┐
                 │    Mission Broker      │  ← FastAPI gateway (port 8000)
                 │    POST /missions      │    Intent parsing, mission dispatch
                 │    POST /parse         │    Chat, WebSocket timeline
                 │    POST /chat          │
                 │    WS /ws/missions/{id}│
                 └───────────┬───────────┘
                             │
           ┌─────────────────┼──────────────────────┐
           │                 │                      │
  ┌────────▼──────┐  ┌──────▼──────┐  ┌────────────▼────────────┐
  │ IntentParser   │  │ Orchestrator│  │   Memory Service        │
  │ (SOP-based     │  │ + Planner   │  │   Redis   → short-term  │
  │  classifier)   │  │ (LLM plan)  │  │   Qdrant  → vectors     │
  └────────────────┘  └──────┬──────┘  │   Postgres → long-term  │
                             │         └─────────────────────────┘
                ┌────────────▼──────────────┐
                │   AgentZero MCP Server    │  ← Central agent dispatcher
                │   (wraps all 6 agents)    │    (port 8100)
                └────────────┬──────────────┘
                             │
         ┌───────────────────▼─────────────────────────────┐
         │                Agent Pipeline                    │
         │                                                 │
         │  1. DataCollectionAgent   (Steps 1.1–1.3)       │
         │  2. RiskAssessmentAgent   (Step  2.1)           │
         │  3. AereveScreeningAgent  (Steps 3.1–3.2)       │
         │  4. AlertReviewAgent      (Steps 4.1–4.3)  ← LLM│
         │  5. DecisionAgent         (Steps 5.1–5.3)  ← LLM│
         │  6. DocumentationAgent    (Steps 6.1–6.2)       │
         └───────────────────┬─────────────────────────────┘
                             │
                ┌────────────▼──────────────┐
                │   Tools MCP Server        │  ← External integrations
                │   CRM, Identity, Screening│    (port 8101)
                └────────────┬──────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
    CRM Tool          Identity Tool       Screening Tool
```

---

## File Layout

```
HadynNG/
│
├── config/                          # Centralised configuration
│   ├── __init__.py
│   └── settings.py                  # pydantic-settings (loads from .env)
│
├── services/                        # Production services
│   ├── llm_gateway/                 # Centralised LLM proxy
│   │   └── gateway.py               # Ollama wrapper with caching + streaming
│   ├── memory/                      # Memory service
│   │   ├── manager.py               # Unified short/long/semantic memory
│   │   ├── redis_store.py           # Redis (context, cache, pub/sub)
│   │   └── vector_store.py          # Qdrant (RAG, agent memory)
│   └── mission_broker/              # FastAPI HTTP gateway
│       └── app.py                   # REST + WebSocket endpoints
│
├── mcp_servers/                     # MCP protocol servers
│   ├── agent_zero/                  # Central agent dispatcher
│   │   └── server.py                # Wraps all 6 agents as MCP tools
│   └── tools/                       # External tool integrations
│       └── server.py                # CRM, identity, screening as MCP tools
│
├── orchestrator/                    # Core pipeline coordination
│   ├── intent_parser.py             # Free-form prompt → structured KYC intent
│   ├── mission_executor.py          # Central coordinator (demo + production)
│   ├── mission_timeline.py          # Real-time status tracker (JSON)
│   └── task_planner.py              # LLM-based mission planning
│
├── agents/                          # KYC pipeline agents
│   ├── base_agent.py                # Base: LLM Gateway + direct Ollama + memory
│   ├── data_collection_agent.py     # Phase 1: Event → CRM → Identity
│   ├── risk_assessment_agent.py     # Phase 2: Risk score + narrative
│   ├── screening_agent.py           # Phase 3: Name variants → Screening
│   ├── alert_review_agent.py        # Phase 4: Triage → Investigation → EDD
│   ├── decision_agent.py            # Phase 5: Decision → MLRO → STR
│   └── documentation_agent.py       # Phase 6: Audit → Notifications
│
├── tools/                           # Tool implementations
│   ├── crm_tool.py                  # CRM database (mock → production)
│   ├── identity_tool.py             # Identity verification
│   ├── screening_tool.py            # Sanctions/PEP screening
│   └── md_loader.py                 # Markdown data parser
│
├── storage/                         # Organised document storage
│   ├── documents/
│   │   ├── sop/                     # Standard Operating Procedures
│   │   │   └── kyc_sop.md
│   │   ├── rag/                     # RAG corpus
│   │   │   └── system_design.md
│   │   └── skills/                  # Agent skill definitions
│   │       └── agent_skills.md
│   └── seeds/                       # Seed data for dev/test
│       ├── crm_customers.md
│       ├── identity_registry.md
│       ├── sanctions_pep_list.md
│       ├── jurisdiction_risk.md
│       └── adverse_media.md
│
├── data/                            # Original data (backward-compatible)
├── demo/                            # CLI demo runner + test cases
│   ├── run_demo.py                  # ← ENTRY POINT (demo mode)
│   ├── kyc_sop.md                   # SOP reference (also in storage/)
│   └── cases/                       # Preset test scenarios
│
├── infra/                           # Infrastructure
│   └── init.sql                     # PostgreSQL schema (WORM audit logs)
│
├── docker-compose.yml               # Full stack: PG + Redis + MinIO + Qdrant + Ollama
├── Dockerfile                       # Application container
├── .env.example                     # Environment template
├── requirements.txt                 # Python dependencies
└── README.md
```

---

## Prerequisites

### Demo Mode (CLI only)
```bash
python --version   # 3.11+
ollama pull qwen3.5:9b
pip install -r requirements.txt
```

### Production Mode (full stack)
```bash
docker --version   # Docker 24+
docker compose version
cp .env.example .env   # Edit with your values
```

---

## Running

### Demo Mode (backward-compatible CLI)
```bash
# Interactive conversational mode
python demo/run_demo.py

# Preset test cases
python demo/run_demo.py --demo clean       # → APPROVE
python demo/run_demo.py --demo medium      # → APPROVE_WITH_CONDITIONS
python demo/run_demo.py --demo pep         # → ESCALATE_TO_MLRO
python demo/run_demo.py --demo sanctioned  # → REJECT
```

### Production Mode (Docker Compose)
```bash
# Start all infrastructure + application services
docker compose up -d

# Check health
curl http://localhost:8000/health

# Parse intent
curl -X POST http://localhost:8000/parse \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Screen Valeria Petrov — suspicious wire transfer"}'

# Create mission
curl -X POST http://localhost:8000/missions \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "C003",
    "customer_name": "Valeria Petrov",
    "event_type": "transaction_alert",
    "notes": "Suspicious wire transfer flagged"
  }'

# Check mission status
curl http://localhost:8000/missions/{mission_id}

# Chat with compliance assistant
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What triggers EDD under HKMA guidelines?"}'
```

### Infrastructure Services

| Service | URL | Purpose |
|---------|-----|---------|
| Mission Broker | http://localhost:8000 | API gateway |
| MinIO Console | http://localhost:9001 | Document storage UI |
| PostgreSQL | localhost:5432 | Database |
| Redis | localhost:6379 | Cache + pub/sub |
| Qdrant | http://localhost:6333 | Vector DB dashboard |
| Ollama | http://localhost:11434 | LLM API |

---

## Demo Cases

| Case | Customer | Expected | Key Factors |
|------|----------|----------|-------------|
| `clean` | James Wong (HKG) | APPROVE | HK ID verified, LOW risk, no hits |
| `medium` | Li Wei Chen (HKG) | APPROVE_WITH_CONDITIONS | MEDIUM risk, enhanced monitoring |
| `pep` | Senator Marcus Delgado (PHL) | ESCALATE_TO_MLRO | Self-declared PEP, adverse media |
| `sanctioned` | Valeria Petrov (RUS) | REJECT | UN + OFAC TRUE_POSITIVE sanctions |

---

## Decision Logic

| Outcome | Trigger condition |
|---------|-------------------|
| `APPROVE` | No hits, LOW risk, identity clean |
| `APPROVE_WITH_CONDITIONS` | No hits, MEDIUM risk or PEP cleared — enhanced monitoring |
| `ESCALATE_TO_MLRO` | PEP TRUE_POSITIVE, adverse media, HIGH risk without sanctions |
| `REJECT` | Confirmed TRUE_POSITIVE on government sanctions list (UN, OFAC, EU, HKMA) |

> **Key principle:** `REJECT` is reserved for confirmed sanctions matches only.

---

## Memory Architecture

| Tier | Store | Purpose |
|------|-------|---------|
| Short-term | Redis | Mission context, session state (24h TTL) |
| Long-term | PostgreSQL | Audit logs, mission records, user preferences |
| Semantic | Qdrant | RAG document embeddings, agent memory (cross-mission learning) |

Agents store insights after each phase. Future missions recall relevant past decisions via vector similarity search.

---

## MCP Tools Reference

### AgentZero MCP (port 8100)
| Tool | Description |
|------|-------------|
| `run_data_collection` | Phase 1: Event classification, CRM lookup, identity verification |
| `run_risk_assessment` | Phase 2: Risk scoring and LLM narrative |
| `run_screening` | Phase 3: Name variants, sanctions/PEP screening |
| `run_alert_review` | Phase 4: Triage, investigation, EDD |
| `run_decision` | Phase 5: Final decision, MLRO escalation, STR |
| `run_documentation` | Phase 6: Audit trail, notifications |
| `run_full_pipeline` | All 6 phases in sequence |
| `agent_status` | Check available agents |
| `get_context` | Retrieve mission context |

### Tools MCP (port 8101)
| Tool | Description |
|------|-------------|
| `crm_search` | Fuzzy name search in CRM |
| `crm_get` | Get customer by ID |
| `crm_register` | Register new customer |
| `identity_verify` | Verify identity documents |
| `screening_screen` | Screen against sanctions/PEP lists |
| `screening_adverse_media` | Search adverse media |
| `jurisdiction_risk` | FATF jurisdiction risk lookup |

---

## KYC SOP Phase Coverage

| Step | Agent | Description | LLM |
|------|-------|-------------|-----|
| — | IntentParser | Intent classification + SOP validation | Yes |
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

## Configuration

All configuration is centralised in `config/settings.py` and loaded from `.env`:

```bash
cp .env.example .env
# Edit .env with your values
```

Key environment variables:
- `OLLAMA_HOST` — LLM server URL
- `OLLAMA_MODEL` — Model name (default: `qwen3.5:9b`)
- `POSTGRES_*` — Database connection
- `REDIS_*` — Cache connection
- `MINIO_*` — Object storage
- `QDRANT_*` — Vector database

For demo mode, no `.env` is needed — all defaults work with local Ollama.

---

## Compliance Framework
- **AMLO** — Anti-Money Laundering and Counter-Terrorist Financing Ordinance (HK, Cap. 615)
- **HKMA** — Hong Kong Monetary Authority AML/CFT Guidelines
- **SFC** — Securities and Futures Commission AML Circular
- **FATF** — High-risk and monitored jurisdiction lists
