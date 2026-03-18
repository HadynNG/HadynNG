# HadynNG KYC Screening Platform — User Tutorial

This tutorial walks you through using the HadynNG KYC Name Screening platform step by step. Two modes are available: **Demo Mode** (quick start, no infrastructure required) and **Production Mode** (full Docker stack).

---

## Prerequisites

### For Demo Mode
- Python 3.11+
- [Ollama](https://ollama.com) installed and running

### For Production Mode
- Docker 24+
- Docker Compose 2.0+
- A machine with at least 8 GB RAM (16 GB recommended for GPU inference)

---

## Part 1 — Demo Mode (Quickstart)

Demo mode runs entirely on your local machine with no databases or containers required. It is the fastest way to see the system in action.

### Step 1: Install the LLM

```bash
ollama pull qwen3.5:9b
```

This downloads the default reasoning model (~5 GB). Wait until the download completes.

### Step 2: Install Python dependencies

```bash
cd HadynNG
pip install -r requirements.txt
```

### Step 3: Run the interactive chatbot

```bash
python demo/run_demo.py
```

You will be greeted with a conversational prompt. Type a screening request in plain English, for example:

```
> Screen James Wong, transaction alert from HSBC, no notes
```

The system will:
1. Parse your intent
2. Pull mock CRM and identity data
3. Run sanctions and PEP screening
4. Apply risk assessment
5. Output a final decision with a full audit trail

Type `quit` or `exit` to leave.

### Step 4: Run preset test cases

Four pre-built cases cover every possible outcome. Run them individually:

| Command | Customer | Expected Decision |
|---------|----------|--------------------|
| `python demo/run_demo.py --demo clean` | James Wong (HK) | `APPROVE` |
| `python demo/run_demo.py --demo medium` | Li Wei Chen (HK) | `APPROVE_WITH_CONDITIONS` |
| `python demo/run_demo.py --demo pep` | Senator Marcus Delgado (PHL) | `ESCALATE_TO_MLRO` |
| `python demo/run_demo.py --demo sanctioned` | Valeria Petrov (RUS) | `REJECT` |

Each case prints the full 6-phase agent pipeline with timing, reasoning, and final disposition.

---

## Part 2 — Production Mode (Docker Stack)

Production mode runs the full platform with PostgreSQL, Redis, MinIO, Qdrant, and Ollama all containerised.

### Step 1: Configure environment

Copy the environment template and fill in your values:

```bash
cp .env.example .env
```

The defaults in `.env.example` work out of the box for a local deployment. Key variables to review:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `qwen3.5:9b` | LLM model to use |
| `POSTGRES_PASSWORD` | `kyc_password` | Database password |
| `MINIO_ROOT_PASSWORD` | `kyc_minio_password` | Object store password |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Step 2: Start all services

```bash
docker compose up -d
```

This starts 9 services. Wait ~60 seconds for all health checks to pass, then verify:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "healthy", "service": "mission-broker"}
```

### Step 3: Check service status

```bash
docker compose ps
```

All services should show `healthy` or `running`.

---

## Part 3 — Using the API (Production Mode)

All interactions go through the Mission Broker API at `http://localhost:8000`.

### 3.1 Parse a free-form screening request

Convert a plain-English prompt into a structured mission intent:

```bash
curl -X POST http://localhost:8000/parse \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Screen Valeria Petrov — suspicious wire transfer from Moscow"}'
```

Response:

```json
{
  "customer_name": "Valeria Petrov",
  "event_type": "transaction_alert",
  "notes": "suspicious wire transfer from Moscow",
  "confidence": 0.97
}
```

### 3.2 Create a screening mission

Submit a mission for a customer. The platform runs the full 6-phase KYC pipeline asynchronously:

```bash
curl -X POST http://localhost:8000/missions \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "C003",
    "customer_name": "Valeria Petrov",
    "event_type": "transaction_alert",
    "notes": "Suspicious wire transfer flagged by compliance team"
  }'
```

Response:

```json
{
  "mission_id": "m-abc123",
  "status": "pending",
  "customer_name": "Valeria Petrov"
}
```

### 3.3 Poll mission status

```bash
curl http://localhost:8000/missions/m-abc123
```

The `status` field progresses through:

```
pending → running → completed
```

When completed, the response includes the `final_decision` and a full phase-by-phase timeline.

### 3.4 Use the compliance chatbot

Ask questions about AMLO, HKMA guidelines, or system decisions:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What triggers Enhanced Due Diligence under HKMA guidelines?"}'
```

### 3.5 Real-time WebSocket updates

Connect to the WebSocket endpoint to receive live phase updates as a mission runs:

```
ws://localhost:8000/ws/missions/{mission_id}
```

Events are emitted at the completion of each agent phase with timing and summary.

---

## Part 4 — Understanding the Output

### Decision Outcomes

| Decision | Meaning | Next Action |
|----------|---------|-------------|
| `APPROVE` | No risk indicators found | Onboard / proceed |
| `APPROVE_WITH_CONDITIONS` | Elevated risk; no confirmed hits | Enhanced monitoring required |
| `ESCALATE_TO_MLRO` | PEP match or HIGH risk without confirmed sanctions | Human review by MLRO |
| `REJECT` | Confirmed TRUE_POSITIVE on government sanctions list | Decline and file if required |

### The 6-Phase Pipeline

| Phase | Agent | What It Does |
|-------|-------|-------------|
| 1 | DataCollectionAgent | Classifies event, retrieves CRM record, verifies identity |
| 2 | RiskAssessmentAgent | Scores risk (LOW / MEDIUM / HIGH) with LLM narrative |
| 3 | ScreeningAgent | Generates name variants, runs sanctions and PEP checks |
| 4 | AlertReviewAgent | Triages alerts, investigates matches, applies EDD if needed |
| 5 | DecisionAgent | Issues final decision, prepares MLRO dossier or STR if required |
| 6 | DocumentationAgent | Writes AMLO-compliant audit log, sends notifications |

---

## Part 5 — Monitoring & Infrastructure UIs

| Service | URL | Credentials |
|---------|-----|-------------|
| MinIO Console (documents) | http://localhost:9001 | `kyc_admin` / `kyc_minio_password` |
| Qdrant Dashboard (vectors) | http://localhost:6333/dashboard | — |

---

## Part 6 — Stopping the Platform

```bash
docker compose down          # Stop services, keep data volumes
docker compose down -v       # Stop services AND delete all data
```

---

## Common Issues

| Problem | Solution |
|---------|---------|
| `ollama: command not found` | Install Ollama from https://ollama.com |
| Model not found error | Run `ollama pull qwen3.5:9b` first |
| Port already in use | Change the port in `.env` and `docker-compose.yml` |
| Mission stuck in `running` | Check Ollama is reachable: `curl http://localhost:11434` |
| `pip install` fails | Upgrade pip first: `pip install --upgrade pip` |
