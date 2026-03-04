# Agentic KYC Platform

A demonstrable agentic AI platform for **KYC (Know Your Customer) Name Screening**, built with:

- **Orchestrator** — powered by [Ollama](https://ollama.com) running `qwen3-coder-next:latest`
- **6 specialised agents** mapped to the full KYC SOP (HKMA / AMLO / SFC compliant)
- **Rich chain-of-thought output** — every LLM reasoning step is streamed to the terminal in real time
- **Mock tools** — simulated CRM, identity verification, and sanctions screening APIs

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Mission Payload (JSON)                  │
└────────────────────────┬────────────────────────────────┘
                         │
               ┌─────────▼──────────┐
               │   MissionExecutor   │  ← orchestrator/mission_executor.py
               │  (orchestrator)     │
               └─────────┬──────────┘
                         │  Uses LLM to plan
               ┌─────────▼──────────┐
               │    TaskPlanner      │  ← orchestrator/task_planner.py
               │ (qwen3-coder-next)  │  Shows chain-of-thought
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
               ┌─────────▼──────────┐
               │   Tools (Mocked)    │
               │  CRM / Identity /   │
               │  Sanctions DB       │
               └────────────────────┘
```

---

## File Layout

```
HadynNG/
│
├── orchestrator/                   # Core platform components
│   ├── __init__.py
│   ├── mission_executor.py         # Central coordinator — runs the full pipeline
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
│   └── cases/                      # Pre-built test scenarios
│       ├── case_clean.json         # Low-risk HK individual → expected: APPROVE
│       ├── case_pep.json           # Philippine senator (PEP) → expected: APPROVE_WITH_CONDITIONS
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

# Pull the model (large download — be patient)
ollama pull qwen3-coder-next:latest

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

### Quick run — choose a case interactively
```bash
python demo/run_demo.py
```

### Run a specific case directly
```bash
# Case 1 — Clean customer (expected: APPROVE)
python demo/run_demo.py clean

# Case 2 — Politically Exposed Person (expected: APPROVE_WITH_CONDITIONS or ESCALATE)
python demo/run_demo.py pep

# Case 3 — Sanctioned individual (expected: REJECT or ESCALATE_TO_MLRO)
python demo/run_demo.py sanctioned
```

---

## What You'll See

Each run produces a **full terminal walkthrough** with colour-coded panels:

| Output type | Colour | Description |
|-------------|--------|-------------|
| 🟡 Yellow   | `Chain-of-Thought` | LLM's internal reasoning (streamed live) |
| 🟢 Green    | `LLM Analysis`     | LLM's final structured response |
| 🔵 Blue     | `Step headers`     | Current KYC phase being executed |
| 🔴 Red      | `Alerts / Decisions` | True positive hits, escalations, STRs |
| ⚪ Dim      | `Tool calls`       | CRM, identity, screening API calls |

**Audit log** files are written to `audit_logs/` after each run.

---

## Demo Cases

### Case 1 — `clean` (James Wong Wai-Man, HKG)
- HK ID verified ✓
- Low risk jurisdiction ✓
- No sanctions / PEP hits ✓
- **Expected outcome: APPROVE**

### Case 2 — `pep` (Senator Marcus Delgado, PHL)
- Self-declared PEP ✓
- Found in PEP database ✓
- Adverse media (corruption allegation) ✓
- EDD required ✓
- **Expected outcome: APPROVE_WITH_CONDITIONS or ESCALATE_TO_MLRO**

### Case 3 — `sanctioned` (Valeria Petrov, RUS)
- Russian national (FATF high-risk jurisdiction)
- Matched on UN Security Council + OFAC SDN lists ✓
- Adverse media (sanctions evasion) ✓
- STR preparation triggered ✓
- **Expected outcome: REJECT or ESCALATE_TO_MLRO + STR**

---

## Customising Ollama Settings

In `demo/run_demo.py`, edit these two lines:
```python
OLLAMA_HOST = "http://localhost:11434"   # Change if Ollama runs elsewhere
MODEL = "qwen3-coder-next:latest"        # Change to any supported model
```

To use a faster/smaller model for testing:
```bash
ollama pull qwen3:8b
# then set MODEL = "qwen3:8b" in run_demo.py
```

---

## KYC SOP Coverage

| SOP Step | Agent | Description | LLM Used |
|----------|-------|-------------|----------|
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

> **Out of scope for this demo:** Step 3.3 (periodic/scheduled rescreening)

---

## Compliance Framework
- **AMLO** — Anti-Money Laundering and Counter-Terrorist Financing Ordinance (HK)
- **HKMA** — Hong Kong Monetary Authority guidelines
- **SFC** — Securities and Futures Commission requirements
- **FATF** — High-risk jurisdiction lists
