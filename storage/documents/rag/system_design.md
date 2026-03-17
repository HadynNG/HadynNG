# Agentic KYC Platform — System Design Document

**Version:** 1.0
**Status:** Demo Phase
**Author:** Platform Team
**Compliance Frameworks:** HKMA AML/CFT Manual · AMLO (Cap. 615) · SFC AML Guidelines

---

## 1. Executive Summary

This document describes the architecture and design decisions behind the Agentic KYC Platform — a custom-built AI orchestration system that automates the Know Your Customer (KYC) Name Screening process in compliance with Hong Kong regulatory requirements.

The platform replaces manual, sequential screening workflows with a pipeline of specialised AI agents, each responsible for a discrete phase of the KYC SOP. A Large Language Model (LLM) provides reasoning capability at critical decision points, while deterministic rule-based logic governs mechanical steps. Every action is fully logged for regulatory audit.

**Key outcomes:**
- End-to-end KYC screening in under 3 minutes (vs. 2–4 hours manually)
- Full chain-of-thought transparency — every AI decision is traceable
- Audit-ready output meeting AMLO Section 20 five-year retention requirements
- Zero framework dependencies — fully auditable, no vendor lock-in

---

## 2. Design Philosophy

### 2.1 Why No LangChain or LangGraph?

Frameworks like LangChain are valuable for rapid prototyping, but introduce risks that are unacceptable in a regulated compliance context:

| Concern | LangChain / LangGraph | This Platform |
|---|---|---|
| Auditability | Hidden abstraction layers | Every line explicit and auditable |
| Vendor lock-in | Framework version drift | Pure Python, no dependency risk |
| Regulatory approval | Framework internals are black boxes | All logic is reviewable by compliance |
| Failure transparency | Hard to trace errors through chains | Every error has a clear origin |
| Control | Framework decides routing | We decide routing, always |

The platform is built on three primitives only: **Python**, **Ollama HTTP API**, and **JSON**. This is deliberate.

### 2.2 The Two-Role Model

The system separates AI responsibilities into two distinct roles:

- **Planner (LLM):** Analyses the mission and generates a plan. Does not execute.
- **Executor (code):** Executes the plan step by step. Does not improvise.

This mirrors how a well-run compliance team works: a senior analyst designs the approach, junior analysts execute defined procedures.

### 2.3 LLM Used Surgically, Not Universally

Not every step needs AI reasoning. The LLM is called only where genuine judgment is required:

| Step | Reasoning needed? | Uses LLM? |
|---|---|---|
| CRM data retrieval | No — deterministic lookup | ❌ |
| Identity verification | No — API call | ❌ |
| Risk score calculation | No — rule-based formula | ❌ |
| Name variant generation | No — string algorithm | ❌ |
| Sanctions database match | No — fuzzy string match | ❌ |
| **Event classification** | Yes — ambiguous types | ✅ |
| **Risk narrative** | Yes — professional text | ✅ |
| **Alert investigation** | Yes — evidence weighing | ✅ |
| **EDD report** | Yes — regulatory document | ✅ |
| **Compliance decision** | Yes — multi-factor ruling | ✅ |
| **MLRO dossier / STR** | Yes — professional communication | ✅ |

This keeps LLM calls fast and targeted, and ensures the pipeline does not fail due to AI errors on trivial operations.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      run_demo.py / API Gateway                       │
│   User enters customer details → mission_payload dict created        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │  mission_payload
                    ┌───────────▼────────────┐
                    │    MissionExecutor      │
                    │  (orchestrator core)    │
                    └────┬──────────┬────────┘
                         │          │
              ┌──────────▼──┐  ┌───▼──────────────┐
              │ TaskPlanner  │  │ MissionTimeline   │
              │ (LLM brain)  │  │ (UI status file)  │
              └──────────────┘  └──────────────────┘
                         │
              ┌──────────▼──────────────────────────────────────┐
              │               Agent Pipeline                     │
              │                                                  │
              │  ┌─────────────────────────────────────────┐    │
              │  │  1. DataCollectionAgent   (Steps 1.1–3)  │    │
              │  │  2. RiskAssessmentAgent   (Step  2.1)    │    │
              │  │  3. AereveScreeningAgent        (Steps 3.1–2)  │    │
              │  │  4. AlertReviewAgent      (Steps 4.1–3)  │◄── LLM
              │  │  5. DecisionAgent         (Steps 5.1–3)  │◄── LLM
              │  │  6. DocumentationAgent    (Steps 6.1–2)  │    │
              │  └─────────────────────────────────────────┘    │
              └─────────────────────┬───────────────────────────┘
                                    │
              ┌─────────────────────▼──────────────────────┐
              │                  Tools Layer                 │
              │  CRMTool · IdentityTool · ScreeningTool      │
              └────────────────────────────────────────────┘
```

### 3.1 Shared Context Dictionary

All components communicate through a single Python dictionary (`context`) that passes through the pipeline. This replaces message queues, databases, and vector stores for the demo:

```
context = {
  # Input
  "customer_id": "C001",
  "event": { "event_type": "onboarding", ... },

  # Written by DataCollectionAgent
  "customer_data": { "full_name": "James Wong", ... },
  "identity_verification": { "status": "VERIFIED", ... },
  "jurisdiction_risk": { "risk_level": "LOW", ... },

  # Written by RiskAssessmentAgent
  "risk_score": 10,
  "risk_level": "LOW",
  "risk_narrative": "Customer presents low inherent risk...",

  # Written by AereveScreeningAgent
  "screening_results": { "total_hits": 0, "hits": [] },
  "adverse_media": [],

  # Written by AlertReviewAgent
  "triaged_alerts": [],
  "investigation_results": [],
  "edd_required": false,

  # Written by DecisionAgent
  "final_decision": "APPROVE",
  "requires_str": false,
  "decision_details": { ... },

  # Written by DocumentationAgent
  "audit_id": "AUD-C001-20240304T...",
  "audit_log_file": "audit_logs/audit_C001_...json",

  # Cross-cutting
  "audit_log": [ ... ],      # every agent appends here
  "timeline": <MissionTimeline>,
  "timeline_file": "timelines/timeline_....json",
  "status": "COMPLETE"
}
```

In the production architecture (see Section 8), this context would be stored in Redis with a mission_id key, allowing distributed agents to read/write it.

---

## 4. Component Design

### 4.1 MissionExecutor (`orchestrator/mission_executor.py`)

The central coordinator. Responsibilities:
1. Receive the mission payload
2. Initialise the `MissionTimeline` for UI tracking
3. Call `TaskPlanner` to generate an LLM execution plan
4. Run agents in the fixed `PIPELINE_ORDER` (safety guarantee — the LLM plan informs but never overrides the sequence)
5. Pass the shared context through each agent
6. Catch and log agent errors without crashing the pipeline
7. Write the final report

**Key design decision:** The execution order is hardcoded in `PIPELINE_ORDER`. Even if the LLM suggests a different sequence, the code ignores it. This ensures the compliance pipeline cannot be manipulated or accidentally reordered by the model.

### 4.2 TaskPlanner (`orchestrator/task_planner.py`)

Uses Ollama to analyse the mission description and return a structured JSON execution plan with:
- Mission summary and scope
- Compliance framework applicability
- Per-agent purpose and expected inputs/outputs
- Risk flags identified upfront
- Estimated decision outcomes

The plan is used for the opening summary display and the timeline, not for routing.

**Consistency settings:** `temperature=0.05`, `seed=42`, `repeat_penalty=1.1` — these ensure the planning output is near-deterministic for the same input while avoiding full rigidity.

### 4.3 BaseAgent (`agents/base_agent.py`)

The parent class for all six KYC agents. Provides:

**`_llm_reason(system_prompt, user_prompt, max_tokens)`**
- Calls Ollama with streaming enabled
- Separates thinking tokens (`<think>`) from the response in real time
- Hard char-count safety breaks at `max_tokens × 6` (thinking) and `max_tokens × 4` (content) to prevent infinite generation loops
- `num_predict`, `repeat_penalty=1.1`, `seed=42` in every call

**`_extract_json(text)`**
- Strips model special tokens (`<|endoftext|>`, `<|im_end|>`)
- Finds the first syntactically balanced `{}` block by walking brace depth
- Falls back to `{}` if no valid JSON is found — all call sites have safe defaults

### 4.4 MissionTimeline (`orchestrator/mission_timeline.py`)

Writes `timelines/timeline_<mission_id>.json` and updates it after every phase transition. The file is designed to be polled by a UI:

```json
{
  "mission_id": "C001-20240304T120000Z",
  "status": "IN_PROGRESS",
  "current_phase": "Alert Review & Investigation",
  "progress_pct": 57,
  "phases": [
    { "sequence": 1, "label": "Data Collection", "status": "COMPLETE",
      "duration_seconds": 4.1, "summary": "James Wong verified — VERIFIED" },
    { "sequence": 4, "label": "Alert Review", "status": "IN_PROGRESS",
      "substeps": [
        { "id": "4.1", "label": "Alert Triage", "status": "COMPLETE" },
        { "id": "4.2", "label": "LLM Investigation", "status": "PENDING" }
      ]
    }
  ],
  "final_decision": null,
  "updated_at": "2024-03-04T12:01:32Z"
}
```

See Section 7 for UI integration guidance.

---

## 5. KYC SOP Mapping

| SOP Step | Agent | Sub-step | LLM? | Tool Called |
|---|---|---|---|---|
| 1.1 Trigger event | DataCollectionAgent | Event classification | ✅ | — |
| 1.2 Collect data | DataCollectionAgent | CRM query | ❌ | CRMTool |
| 1.3 Verify identity | DataCollectionAgent | Registry check | ❌ | IdentityTool |
| 2.1 Risk score | RiskAssessmentAgent | Rules engine | ❌ | — |
| 2.1 Risk narrative | RiskAssessmentAgent | LLM narrative | ✅ | — |
| 3.1 Query prep | AereveScreeningAgent | Name variants | ❌ | — |
| 3.2 Screening | AereveScreeningAgent | Database search | ❌ | ScreeningTool |
| 4.1 Triage | AlertReviewAgent | Rule-based sort | ❌ | — |
| 4.2 Investigate | AlertReviewAgent | Evidence analysis | ✅ | — |
| 4.3 EDD | AlertReviewAgent | Report generation | ✅ | — |
| 5.1 Decide | DecisionAgent | Compliance ruling | ✅ | — |
| 5.2 Escalate | DecisionAgent | MLRO dossier | ✅ | — |
| 5.3 STR | DecisionAgent | JFIU report | ✅ | — |
| 6.1 Audit log | DocumentationAgent | File write | ❌ | — |
| 6.2 Notify | DocumentationAgent | Notification gen | ❌ | — |

> **Out of scope (Phase 1):** Step 3.3 — periodic/scheduled rescreening

---

## 6. LLM Integration Strategy

### 6.1 Model

| Setting | Value | Rationale |
|---|---|---|
| Model | `qwen3.5:9b` | Strong reasoning, runs locally on consumer hardware |
| Temperature | `0.05` | Near-deterministic for consistent compliance outputs |
| Seed | `42` | Reproducible outputs for the same input |
| Repeat penalty | `1.1` | Prevents generation loops on complex prompts |
| num_predict | `2048` (agents) / `4096` (planner) | Hard cap prevents infinite generation |

### 6.2 Thinking Mode

The `think=True` parameter activates the model's internal chain-of-thought reasoning, which streams as `<think>` tokens. These are:
- Displayed live in the terminal (yellow text) for demonstration
- Captured in `thinking_text` but not stored in the audit log
- Subject to the same generation cap as regular content

### 6.3 Prompt Engineering Principles

1. **Role assignment first:** Every system prompt begins with a clear professional role ("You are a senior KYC compliance investigator...")
2. **Explicit output format:** JSON schema is included in every system prompt that requires structured output
3. **Scope constraints:** System prompts explicitly state what the model should NOT do (e.g., "do not flag missing customer fields — they come from CRM")
4. **Conservative defaults:** If JSON parsing fails, all agents default to the safest possible outcome (e.g., `ESCALATE_TO_MLRO` rather than `APPROVE`)

---

## 7. UI Integration — Timeline File

The `MissionTimeline` is designed to be consumed by any UI without coupling. The timeline file at `timelines/timeline_<mission_id>.json` is:

- **Created** when `MissionExecutor.execute()` is called
- **Updated** after every phase start and completion (~every 30–120 seconds depending on LLM speed)
- **Finalised** with `progress_pct: 100`, `status: "COMPLETE"`, and `final_decision` when the pipeline ends

### 7.1 Polling Pattern (simple)

```javascript
// Frontend: poll every 2 seconds
const TIMELINE_PATH = `/timelines/timeline_${missionId}.json`;

async function pollTimeline() {
  const res = await fetch(TIMELINE_PATH);
  const data = await res.json();
  updateProgressBar(data.progress_pct);
  updatePhaseList(data.phases);
  if (data.status === 'COMPLETE' || data.status === 'FAILED') {
    clearInterval(poller);
    showFinalDecision(data.final_decision);
  }
}
const poller = setInterval(pollTimeline, 2000);
```

### 7.2 File-Watch Pattern (reactive)

On Linux/macOS, use `inotify`/`FSEvents` to trigger UI updates immediately when the file changes:

```python
# Backend: serve timeline over WebSocket on file change
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class TimelineWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.json'):
            websocket.send(open(event.src_path).read())
```

### 7.3 REST API Pattern (production)

In production, wrap the executor in a FastAPI service:

```python
# POST /missions  → start a new KYC mission, returns mission_id
# GET /missions/{id}/timeline  → return current timeline JSON
# GET /missions/{id}/result    → return final context (after COMPLETE)
```

### 7.4 Timeline Data Contract

Your UI can rely on these fields always being present:

| Field | Type | Notes |
|---|---|---|
| `mission_id` | string | Unique per run |
| `status` | string | `IN_PROGRESS`, `COMPLETE`, `FAILED` |
| `current_phase` | string \| null | Display name of running phase |
| `progress_pct` | int 0–100 | Suitable for a progress bar |
| `phases[].status` | string | `PENDING`, `IN_PROGRESS`, `COMPLETE`, `FAILED` |
| `phases[].substeps[].status` | string | Granular step tracking |
| `final_decision` | string \| null | Only set when `status == COMPLETE` |
| `risk_level` | string \| null | `LOW`, `MEDIUM`, `HIGH` |
| `updated_at` | ISO-8601 | Last write timestamp for stale-check |

---

## 8. Production Architecture

The demo uses in-process agents with a shared Python dict. The production architecture maps directly to your original diagram:

```
┌───────────────┐   REST API   ┌──────────────────────────────┐
│  221b Gateway │◄────────────►│  Mission Controller           │
│  (your client)│              │  + Input Guardrail            │
└───────────────┘              │  (FastAPI + prompt validation) │
                               └──────────────┬───────────────┘
                                              │ Redis LPUSH
                               ┌──────────────▼───────────────┐
                               │  Mission Executor             │
                               │  (Redis BLPOP consumer)       │
                               │  + TaskPlanner (Ollama)       │
                               └──────────────┬───────────────┘
                                              │ JSON-RPC
                      ┌───────────────────────┼───────────────────────┐
              ┌───────▼──────┐  ┌─────────────▼──┐  ┌───────────────▼──┐
              │ Agent 1      │  │ Agent 2         │  │ Agent N          │
              │ (container)  │  │ (container)     │  │ (container)      │
              └──────────────┘  └────────────────┘  └──────────────────┘
                                              │ JSON-RPC
                               ┌──────────────▼───────────────┐
                               │  Output Guardrail             │
                               │  + MCP Server                 │
                               └──────────────┬───────────────┘
                                              │ REST API
                               ┌──────────────▼───────────────┐
                               │  Tools & API Pool             │
                               │  (real CRM, Dow Jones, etc.)  │
                               └──────────────────────────────┘
```

### Migration Path: Demo → Production

| Demo component | Production replacement |
|---|---|
| Shared `context` dict | Redis hash keyed by `mission_id` |
| In-process agent calls | JSON-RPC over HTTP between containerised agents |
| Mock `CRMTool` | Real CRM API (Oracle, Salesforce, etc.) |
| Mock `ScreeningTool` | Dow Jones Risk & Compliance / Refinitiv World-Check API |
| Mock `IdentityTool` | Jumio / Onfido / Veriff API |
| File-based audit log | Immutable append-only database (PostgreSQL + WORM) |
| File-based timeline | Redis Pub/Sub → WebSocket |
| Single process | Docker/K8s with per-agent containers |

---

## 9. Security & Compliance Considerations

### 9.1 Data Handling
- Customer PII never leaves the local environment in the demo
- In production: all data encrypted in transit (TLS 1.3) and at rest (AES-256)
- Audit logs are append-only; deletion requires MLRO + IT approval

### 9.2 LLM Safety
- All LLM calls use a local model (Ollama) — no data sent to external APIs
- System prompts include explicit scope constraints to prevent prompt injection
- LLM outputs are always parsed and validated before being acted upon
- Conservative defaults: if LLM output is ambiguous, escalate rather than approve

### 9.3 Human-in-the-Loop
The system is designed as decision-support, not decision-replacement:
- All TRUE_POSITIVE alerts require human review before account action
- ESCALATE_TO_MLRO decisions await human approval before proceeding
- STR filing requires MLRO sign-off before JFIU submission

### 9.4 Regulatory Compliance
| Requirement | Implementation |
|---|---|
| AMLO S.20 — 5-year record retention | `audit_logs/` JSON files + `retention_policy` field |
| HKMA — risk-based approach | Risk scoring in Phase 2 calibrates screening depth |
| HKMA — CDD for PEPs | `pep_self_declared` triggers EDD path automatically |
| SFC — AML controls | Decision audit trail captures rationale for every ruling |
| FATF — high-risk jurisdictions | Hardcoded jurisdiction risk list in `CRMTool` |

---

## 10. Technology Stack

| Layer | Technology | Why |
|---|---|---|
| LLM runtime | Ollama | Local, no data egress, privacy-safe |
| LLM model | qwen3.5:9b | Strong reasoning, efficient on local hardware |
| Language | Python 3.11+ | Mature ecosystem, async support, type hints |
| Terminal UI | Rich | Professional output with no web dependency |
| Data format | JSON | Universal, human-readable, auditable |
| Orchestration | Custom Python | Full control, no framework risk |
| Timeline output | JSON file | UI-agnostic, no additional infrastructure |

---

## 11. Known Limitations (Demo Phase)

| Limitation | Impact | Production fix |
|---|---|---|
| Mock tools | No real sanctions data | Replace with vendor APIs |
| Single-process pipeline | No parallelism | Containerised agents via JSON-RPC |
| Local LLM only | Slower than cloud models | Optional cloud LLM endpoint |
| File-based timeline | Requires polling | Redis Pub/Sub + WebSocket |
| English-only | Cannot screen non-Latin scripts natively | Multilingual model or translation preprocessing |
| No retry logic in agents | Failed LLM call = empty result | Add retry with exponential backoff |
