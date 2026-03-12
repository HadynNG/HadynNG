# Agentic KYC Platform

A demonstrable agentic AI platform for **KYC (Know Your Customer) Name Screening**, built with:

- **Orchestrator** — powered by [Ollama](https://ollama.com) running `qwen3.5:9b`
- **Intent Parser** — maps free-form natural language to a structured KYC request, validated against an external SOP document
- **6 specialised agents** mapped to the full KYC SOP (HKMA / AMLO / SFC compliant)
- **Rich chain-of-thought output** — every LLM reasoning step is streamed to the terminal in real time
- **Mock tools** — simulated CRM, identity verification, and sanctions screening APIs

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│              Free-form User Prompt (natural language)       │
└───────────────────────┬────────────────────────────────────┘
                        │
              ┌─────────▼──────────┐
              │   IntentParser      │  ← orchestrator/intent_parser.py
              │  Reads: kyc_sop.md  │    Validates prompt against SOP
              │  Extracts: name,    │    Classifies event type
              │  event_type, notes  │
              └─────────┬──────────┘
                        │  Structured intent
              ┌─────────▼──────────┐
              │  MissionExecutor   │  ← orchestrator/mission_executor.py
              │  (orchestrator)    │    Drives the full pipeline
              └─────────┬──────────┘
                        │  Uses LLM to plan
              ┌─────────▼──────────┐
              │    TaskPlanner     │  ← orchestrator/task_planner.py
              │   (qwen3.5:9b)    │    Shows chain-of-thought
              └─────────┬──────────┘
                        │  Execution plan
        ┌───────────────▼───────────────────────────┐
        │              Agent Pipeline                │
        │                                           │
        │  1. DataCollectionAgent   (Steps 1.1–1.3) │
        │  2. RiskAssessmentAgent   (Step  2.1)     │
        │  3. ScreeningAgent        (Steps 3.1–3.2) │
        │  4. AlertReviewAgent      (Steps 4.1–4.3) │  ← LLM reasoning
        │  5. DecisionAgent         (Steps 5.1–5.3) │  ← LLM reasoning
        │  6. DocumentationAgent    (Steps 6.1–6.2) │
        └───────────────┬───────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   CRM Tool      Identity Tool    Screening Tool
   (crm_tool)   (identity_tool)  (screening_tool)
```

---

## File Layout

```
HadynNG/
│
├── orchestrator/                   # Core platform components
│   ├── __init__.py
│   ├── intent_parser.py            # Free-form prompt → structured KYC intent (SOP-validated)
│   ├── mission_executor.py         # Central coordinator — runs the full pipeline
│   ├── mission_timeline.py         # Per-run timeline state tracker (JSON)
│   └── task_planner.py             # LLM-based mission analysis and planning
│
├── agents/                         # One agent per KYC phase
│   ├── __init__.py
│   ├── base_agent.py               # Base class: Ollama integration + CoT display
│   ├── data_collection_agent.py    # Phase 1: Trigger → CRM → Identity verify
│   ├── risk_assessment_agent.py    # Phase 2: Risk score + LLM narrative
│   ├── screening_agent.py          # Phase 3: Name variants → Sanctions/PEP screen
│   ├── alert_review_agent.py       # Phase 4: Triage → LLM investigation → EDD
│   ├── decision_agent.py           # Phase 5: LLM decision → MLRO escalation → STR
│   └── documentation_agent.py      # Phase 6: Audit log → Notifications
│
├── tools/                          # Mock external API integrations
│   ├── __init__.py
│   ├── crm_tool.py                 # Simulated CRM / customer database
│   ├── identity_tool.py            # Simulated Jumio/Onfido identity verification
│   └── screening_tool.py           # Simulated Dow Jones / World-Check screening
│
├── demo/
│   ├── run_demo.py                 # ← ENTRY POINT — run this
│   ├── kyc_sop.md                  # External SOP reference (HKMA/AMLO/SFC aligned)
│   └── cases/                      # Pre-built test scenarios
│       ├── case_clean.json         # Low-risk HK individual → expected: APPROVE
│       ├── case_pep.json           # Philippine senator (PEP) → expected: ESCALATE_TO_MLRO
│       └── case_sanctioned.json    # Russian exec on UN/OFAC lists → expected: REJECT
│
├── audit_logs/                     # Auto-created — JSON audit trails per run
│
├── requirements.txt
└── README.md
```

---

## Prerequisites

### 1. Python 3.11+
```bash
python --version   # must be 3.11 or higher
```

### 2. Ollama running locally with the required model
```bash
# Install Ollama if not already installed
# https://ollama.com/download

# Pull the model
ollama pull qwen3.5:9b

# Verify it's available
ollama list
```

### 3. Install Python dependencies
```bash
# From the repo root (HadynNG/)
pip install -r requirements.txt
```

---

## Running the Demo

All commands are run from the **repo root** (`HadynNG/`).

### Interactive mode — free-form prompt
```bash
python demo/run_demo.py
```

You will be prompted to describe the customer in plain language. The **IntentParser** reads the KYC SOP (`demo/kyc_sop.md`) and determines whether your input is a valid KYC screening request. If yes, it extracts the customer name and event type automatically and looks them up in the CRM.

```
Your request: Screen Valeria Petrov — flagged suspicious wire transfer
  ✓ KYC request recognised — Subject: Valeria Petrov  Event: transaction_alert
```

If the input is not a KYC request (e.g. a general enquiry), the system explains why and re-prompts.

### Quick preset — skip the prompt
```bash
# Case 1 — Clean customer (expected: APPROVE)
python demo/run_demo.py --demo clean

# Case 2 — Politically Exposed Person (expected: ESCALATE_TO_MLRO)
python demo/run_demo.py --demo pep

# Case 3 — Sanctioned individual (expected: REJECT)
python demo/run_demo.py --demo sanctioned
```

---

## What You'll See

Each run produces a **full terminal walkthrough** with colour-coded panels:

| Colour | Panel | Description |
|--------|-------|-------------|
| Yellow | `Chain-of-Thought` | LLM's internal reasoning (streamed live) |
| Green  | `LLM Analysis`     | LLM's final structured response |
| Cyan   | Step headers       | Current KYC phase being executed |
| Red    | Alerts / Decisions | True positive hits, escalations, STRs |
| Dim    | Tool calls         | CRM, identity, screening API calls |

Audit log files are written to `audit_logs/` and timeline state to `timelines/` after each run.

---

## Demo Cases

### Case 1 — `clean` (James Wong Wai-Man, HKG)
- HK ID verified ✓
- Low-risk jurisdiction ✓
- No sanctions / PEP hits ✓
- **Expected outcome: APPROVE**

### Case 2 — `pep` (Senator Marcus Delgado, PHL)
- Self-declared PEP ✓
- Found in PEP database ✓
- Adverse media (corruption allegation) ✓
- EDD triggered ✓
- **Expected outcome: ESCALATE_TO_MLRO**

### Case 3 — `sanctioned` (Valeria Petrov, RUS)
- Russian national (FATF high-risk jurisdiction)
- Confirmed TRUE_POSITIVE on UN Security Council + OFAC SDN lists ✓
- Adverse media (sanctions evasion) ✓
- STR preparation triggered ✓
- **Expected outcome: REJECT**

---

## Decision Logic

The `DecisionAgent` enforces a clear, policy-grounded boundary between outcomes:

| Outcome | Trigger condition |
|---------|-------------------|
| `APPROVE` | No hits, LOW risk, identity clean |
| `APPROVE_WITH_CONDITIONS` | No hits, MEDIUM risk or PEP cleared — enhanced monitoring required |
| `ESCALATE_TO_MLRO` | PEP TRUE_POSITIVE, adverse media, HIGH risk without confirmed sanctions — human judgement required |
| `REJECT` | Confirmed TRUE_POSITIVE on a **government sanctions list** (UN, OFAC SDN, EU Consolidated, HKMA) — factual finding only |

> **Key principle:** `REJECT` is reserved for confirmed sanctions matches only — not for high risk scores or adverse media alone. Adverse media and PEP concerns route to `ESCALATE_TO_MLRO` for human review.

---

## KYC SOP Reference

The `IntentParser` validates all user inputs against `demo/kyc_sop.md` before triggering the pipeline. The SOP defines:
- **Trigger conditions** — onboarding, transaction alerts, periodic review, customer updates
- **Intent keywords** — phrases that indicate a KYC request
- **Out-of-scope requests** — general enquiries, IT support, complaints
- **Decision thresholds** — aligned with the decision logic table above

To update compliance rules or trigger conditions, edit `demo/kyc_sop.md` — no code changes needed.

---

## KYC SOP Phase Coverage

| SOP Step | Agent | Description | LLM Used |
|----------|-------|-------------|----------|
| —        | IntentParser | Free-form intent classification + SOP validation | ✓ |
| 1.1 | DataCollectionAgent | Event classification | ✓ |
| 1.2 | DataCollectionAgent | CRM data retrieval | — |
| 1.3 | DataCollectionAgent | Identity verification | — |
| 2.1 | RiskAssessmentAgent | Risk scoring + narrative | ✓ |
| 3.1 | ScreeningAgent | Name variant generation | — |
| 3.2 | ScreeningAgent | Sanctions/PEP screening | — |
| 4.1 | AlertReviewAgent | Alert triage | — |
| 4.2 | AlertReviewAgent | Match investigation | ✓ |
| 4.3 | AlertReviewAgent | Enhanced Due Diligence | ✓ |
| 5.1 | DecisionAgent | Final decision | ✓ |
| 5.2 | DecisionAgent | MLRO escalation | ✓ |
| 5.3 | DecisionAgent | STR preparation | ✓ |
| 6.1 | DocumentationAgent | Audit logging | — |
| 6.2 | DocumentationAgent | Stakeholder notifications | — |

> **Out of scope for this demo:** Step 3.3 (periodic/scheduled re-screening)

---

## Configuring Ollama

In `demo/run_demo.py`, edit these two constants:
```python
OLLAMA_HOST = "http://localhost:11434"   # Change if Ollama runs elsewhere
MODEL = "qwen3.5:9b"                    # Change to any supported model
```

To use a faster/smaller model for testing:
```bash
ollama pull qwen3:4b
# then set MODEL = "qwen3:4b" in run_demo.py
```

---

## Compliance Framework
- **AMLO** — Anti-Money Laundering and Counter-Terrorist Financing Ordinance (HK, Cap. 615)
- **HKMA** — Hong Kong Monetary Authority AML/CFT Guidelines
- **SFC** — Securities and Futures Commission AML Circular
- **FATF** — High-risk and monitored jurisdiction lists
