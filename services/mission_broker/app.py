"""
Mission Broker — FastAPI gateway for the Agentic KYC Platform.

This is the single HTTP entry point. All external clients (UI, API consumers,
webhooks) interact with the platform through this service.

Responsibilities:
  - Accept mission requests (POST /missions)
  - Parse intent from free-form prompts (POST /parse)
  - Proxy chat completions (POST /chat)
  - Serve mission status and timeline (GET /missions/{id})
  - Health checks for all subsystems (GET /health)
  - WebSocket for real-time timeline updates (WS /ws/missions/{id})
"""
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from config import settings
from services.llm_gateway import LLMGateway
from services.memory import MemoryManager

logger = logging.getLogger("mission_broker")


# ── Request / Response models ────────────────────────────────────────────────

class ParseRequest(BaseModel):
    prompt: str
    sop_path: Optional[str] = None


class ParseResponse(BaseModel):
    is_kyc_request: bool
    customer_name: Optional[str] = None
    event_type: str = "onboarding"
    notes: str = ""
    decline_reason: Optional[str] = None


class MissionRequest(BaseModel):
    customer_id: str
    customer_name: Optional[str] = None
    event_type: str = "onboarding"
    trigger_source: str = "api"
    notes: str = ""
    mission_description: Optional[str] = None


class MissionResponse(BaseModel):
    mission_id: str
    status: str
    customer_id: str
    message: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str


class MuleAlertRequest(BaseModel):
    account_id: str
    account_name: Optional[str] = None
    alert_type: str = "transaction_velocity"
    alert_source: str = "system"
    priority: Optional[str] = None
    notes: str = ""


class MuleMissionResponse(BaseModel):
    mission_id: str
    status: str
    account_id: str
    message: str


class HealthResponse(BaseModel):
    status: str
    services: dict


# ── Application factory ─────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        app.state.llm = LLMGateway(
            model=settings.ollama_model,
            ollama_host=settings.ollama_host,
            redis_url=settings.redis_url,
        )
        app.state.memory = MemoryManager(
            redis_url=settings.redis_url,
            milvus_host=settings.milvus_host,
            milvus_port=settings.milvus_port,
            postgres_dsn=settings.postgres_dsn,
        )
        app.state.active_missions: dict[str, dict] = {}
        logger.info("Mission Broker started — model=%s", settings.ollama_model)
        yield
        # Shutdown
        logger.info("Mission Broker shutting down")

    app = FastAPI(
        title="HadynNG Agentic KYC Platform",
        description="Mission Broker — API gateway for KYC screening missions",
        version="2.0.0",
        lifespan=lifespan,
    )

    _register_routes(app)
    return app


def _register_routes(app: FastAPI):
    """Register all API routes."""

    # ── Health ────────────────────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse)
    async def health():
        llm_health = app.state.llm.health_check()
        memory_health = app.state.memory.health_check()
        all_ok = (
            llm_health.get("status") == "ok"
            and memory_health["redis"].get("status") in ("ok", "degraded")
        )
        return HealthResponse(
            status="ok" if all_ok else "degraded",
            services={
                "llm_gateway": llm_health,
                "memory": memory_health,
                "broker": {"status": "ok"},
            },
        )

    # ── Intent Parsing ────────────────────────────────────────────────────

    @app.post("/parse", response_model=ParseResponse)
    async def parse_intent(req: ParseRequest):
        """Parse a free-form prompt into a structured KYC intent."""
        from orchestrator import IntentParser

        parser = IntentParser(
            model=settings.ollama_model,
            ollama_host=settings.ollama_host,
            sop_path=req.sop_path,
        )
        result = parser.parse(req.prompt)
        return ParseResponse(**result)

    # ── Mission Lifecycle ─────────────────────────────────────────────────

    @app.post("/missions", response_model=MissionResponse)
    async def create_mission(req: MissionRequest):
        """Create and execute a new KYC screening mission."""
        mission_id = f"M-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6].upper()}"

        event = {
            "event_type": req.event_type,
            "trigger_source": req.trigger_source,
            "triggered_at": datetime.utcnow().isoformat() + "Z",
            "notes": req.notes,
        }

        mission_description = req.mission_description or (
            f"KYC name screening for customer {req.customer_id} "
            f"triggered by {req.event_type}."
        )

        payload = {
            "customer_id": req.customer_id,
            "customer_name": req.customer_name or req.customer_id,
            "event": event,
            "mission_description": mission_description,
        }

        # Store mission context in Redis
        app.state.memory.set_context(mission_id, {
            "mission_id": mission_id,
            "payload": payload,
            "status": "QUEUED",
            "created_at": datetime.utcnow().isoformat() + "Z",
        })

        # Execute mission in background
        asyncio.create_task(_run_mission(app, mission_id, payload))

        return MissionResponse(
            mission_id=mission_id,
            status="QUEUED",
            customer_id=req.customer_id,
            message="Mission queued for execution.",
        )

    @app.get("/missions/{mission_id}")
    async def get_mission(mission_id: str):
        """Get mission status and timeline."""
        ctx = app.state.memory.get_context(mission_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail="Mission not found")
        return ctx

    @app.get("/missions")
    async def list_missions(limit: int = 20, status: Optional[str] = None):
        """List recent missions."""
        # In production this queries PostgreSQL; here we return from Redis
        return {"missions": [], "note": "Full listing requires PostgreSQL backend"}

    # ── Chat ──────────────────────────────────────────────────────────────

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        """General-purpose compliance assistant chat."""
        system_prompt = (
            "You are a knowledgeable compliance operations assistant embedded in an "
            "AML/KYC screening platform. You help with KYC procedures, AML regulations, "
            "sanctions screening, PEP identification, and risk assessment. "
            "Keep answers concise, accurate, and professional."
        )
        result = app.state.llm.generate(
            system_prompt=system_prompt,
            user_prompt=req.message,
            think=False,
            temperature=0.3,
            max_tokens=512,
        )
        conv_id = req.conversation_id or str(uuid.uuid4())
        return ChatResponse(reply=result["content"], conversation_id=conv_id)

    # ── Mule Account Hunting ──────────────────────────────────────────────

    @app.post("/mule-missions", response_model=MuleMissionResponse)
    async def create_mule_mission(req: MuleAlertRequest):
        """Create and execute a mule account investigation mission."""
        mission_id = f"MULE-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6].upper()}"

        alert = {
            "alert_type": req.alert_type,
            "alert_source": req.alert_source,
            "priority": req.priority or "MEDIUM",
            "triggered_at": datetime.utcnow().isoformat() + "Z",
            "notes": req.notes,
        }

        payload = {
            "account_id": req.account_id,
            "account_name": req.account_name or req.account_id,
            "alert": alert,
            "notes": req.notes,
        }

        app.state.memory.set_context(mission_id, {
            "mission_id": mission_id,
            "payload": payload,
            "status": "QUEUED",
            "created_at": datetime.utcnow().isoformat() + "Z",
        })

        asyncio.create_task(_run_mule_mission(app, mission_id, payload))

        return MuleMissionResponse(
            mission_id=mission_id,
            status="QUEUED",
            account_id=req.account_id,
            message="Mule investigation mission queued for execution.",
        )

    @app.get("/mule-missions/{mission_id}")
    async def get_mule_mission(mission_id: str):
        """Get mule investigation status and timeline."""
        ctx = app.state.memory.get_context(mission_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail="Mule mission not found")
        return ctx

    # ── WebSocket for real-time updates ───────────────────────────────────

    @app.websocket("/ws/missions/{mission_id}")
    async def mission_ws(websocket: WebSocket, mission_id: str):
        """WebSocket endpoint for real-time mission timeline updates."""
        await websocket.accept()
        try:
            while True:
                ctx = app.state.memory.get_context(mission_id)
                if ctx:
                    await websocket.send_json(ctx)
                    if ctx.get("status") in ("COMPLETE", "FAILED"):
                        break
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            pass


async def _run_mission(app: FastAPI, mission_id: str, payload: dict):
    """Execute mission in background thread (blocking LLM calls)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from orchestrator import MissionExecutor

    try:
        app.state.memory.update_context(mission_id, {"status": "IN_PROGRESS"})

        executor = MissionExecutor(
            model=settings.ollama_model,
            ollama_host=settings.ollama_host,
        )

        # Run in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, executor.execute, payload)

        # Store final result
        app.state.memory.update_context(mission_id, {
            "status": "COMPLETE",
            "final_decision": result.get("final_decision"),
            "risk_level": result.get("risk_level"),
            "risk_score": result.get("risk_score"),
            "screening_hits": result.get("screening_results", {}).get("total_hits", 0),
            "audit_log_file": result.get("audit_log_file"),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        })

        # Publish completion event
        app.state.memory.publish_event(f"mission:{mission_id}", {
            "event": "completed",
            "decision": result.get("final_decision"),
        })

    except Exception as e:
        logger.error("Mission %s failed: %s", mission_id, e)
        app.state.memory.update_context(mission_id, {
            "status": "FAILED",
            "error": str(e),
        })


async def _run_mule_mission(app: FastAPI, mission_id: str, payload: dict):
    """Execute mule investigation in background thread (blocking LLM calls)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from orchestrator import MuleExecutor

    try:
        app.state.memory.update_context(mission_id, {"status": "IN_PROGRESS"})

        executor = MuleExecutor(
            model=settings.ollama_model,
            ollama_host=settings.ollama_host,
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, executor.execute, payload)

        app.state.memory.update_context(mission_id, {
            "status": "COMPLETE",
            "final_disposition": result.get("final_disposition"),
            "mule_type": result.get("mule_type"),
            "sar_reference": result.get("sar_reference"),
            "total_exposure_hkd": result.get("total_exposure_hkd"),
            "completed_at": datetime.utcnow().isoformat() + "Z",
        })

        app.state.memory.publish_event(f"mission:{mission_id}", {
            "event": "completed",
            "disposition": result.get("final_disposition"),
        })

    except Exception as e:
        logger.error("Mule mission %s failed: %s", mission_id, e)
        app.state.memory.update_context(mission_id, {
            "status": "FAILED",
            "error": str(e),
        })


# ── Standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(
        app,
        host=settings.broker_host,
        port=settings.broker_port,
        log_level=settings.log_level.lower(),
    )
