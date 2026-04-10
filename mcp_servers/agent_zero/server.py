"""
AgentZero MCP Server — central agent dispatcher.

This MCP server wraps all KYC agents and exposes them as callable tools
via the Model Context Protocol.  The Orchestrator connects to this server
as an MCP client and dispatches agent execution through it.

Architecture:
  Prompt → Mission Broker → Orchestrator → AgentZero MCP → Agents → Tool MCP → Tools

Pipeline execution now uses a LangGraph StateGraph (orchestrator/kyc_graph.py)
instead of a manual for-loop.  Each agent is a typed node; conditional edges
handle DataCollection failure and ensure documentation always runs last.

Individual agent tools (run_data_collection, run_risk_assessment, …) still call
agents directly for single-phase invocations.  run_full_pipeline delegates to
graph.invoke() so the full pipeline benefits from LangGraph state management,
typed schema, and optional Redis checkpointing.

Tools exposed:
  - run_data_collection
  - run_risk_assessment
  - run_screening
  - run_alert_review
  - run_decision
  - run_documentation
  - run_full_pipeline  ← uses LangGraph graph.invoke()
  - agent_status
  - get_context
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from config import settings
from services.memory import MemoryManager

logger = logging.getLogger("agent_zero_mcp")

# ── Agent Registry (for individual-phase tools) ───────────────────────────────

PIPELINE_ORDER = [
    "DataCollectionAgent",
    "RiskAssessmentAgent",
    "AereveScreeningAgent",
    "AlertReviewAgent",
    "DecisionAgent",
    "DocumentationAgent",
]


def _build_agents() -> dict:
    """Instantiate all agents with current settings (no llm_gateway/memory in MCP mode)."""
    from agents import (
        AlertReviewAgent,
        AereveScreeningAgent,
        DataCollectionAgent,
        DecisionAgent,
        DocumentationAgent,
        RiskAssessmentAgent,
    )
    return {
        "DataCollectionAgent":  DataCollectionAgent(model=settings.ollama_model, ollama_host=settings.ollama_host),
        "RiskAssessmentAgent":  RiskAssessmentAgent(model=settings.ollama_model, ollama_host=settings.ollama_host),
        "AereveScreeningAgent": AereveScreeningAgent(model=settings.ollama_model, ollama_host=settings.ollama_host),
        "AlertReviewAgent":     AlertReviewAgent(model=settings.ollama_model, ollama_host=settings.ollama_host),
        "DecisionAgent":        DecisionAgent(model=settings.ollama_model, ollama_host=settings.ollama_host),
        "DocumentationAgent":   DocumentationAgent(model=settings.ollama_model, ollama_host=settings.ollama_host),
    }


# ── MCP Server Definition ─────────────────────────────────────────────────────

def create_server() -> Server:
    server = Server("agent-zero")
    memory = MemoryManager(
        redis_url=settings.redis_url,
        milvus_host=settings.milvus_host,
        milvus_port=settings.milvus_port,
    )

    # ── Tool definitions ───────────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="run_data_collection",
                description="Phase 1: Classify trigger event, collect customer data from CRM, verify identity documents.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string", "description": "Mission identifier"},
                        "context":    {"type": "object", "description": "Current mission context dict"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="run_risk_assessment",
                description="Phase 2: Calculate risk score using rule-based factors and generate LLM risk narrative.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "context":    {"type": "object"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="run_screening",
                description="Phase 3: Generate name variants and screen against sanctions/PEP databases. Search adverse media.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "context":    {"type": "object"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="run_alert_review",
                description="Phase 4: Triage alerts, investigate matches with LLM, run Enhanced Due Diligence if required.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "context":    {"type": "object"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="run_decision",
                description="Phase 5: Make final compliance decision, handle MLRO escalation and STR filing.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "context":    {"type": "object"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="run_documentation",
                description="Phase 6: Generate audit trail, write logs, send stakeholder notifications.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "context":    {"type": "object"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="run_full_pipeline",
                description=(
                    "Run all 6 agent phases in sequence via LangGraph StateGraph "
                    "(DataCollection → Risk → Screening → AlertReview → Decision → Documentation). "
                    "Conditional edge: DataCollection failure routes directly to Documentation."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                        "context":    {"type": "object"},
                    },
                    "required": ["mission_id", "context"],
                },
            ),
            Tool(
                name="agent_status",
                description="Check which agents are available and their current state.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_context",
                description="Retrieve current mission context from memory.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mission_id": {"type": "string"},
                    },
                    "required": ["mission_id"],
                },
            ),
        ]

    # ── Tool execution ─────────────────────────────────────────────────────

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "agent_status":
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "agents":       PIPELINE_ORDER,
                        "model":        settings.ollama_model,
                        "ollama_host":  settings.ollama_host,
                        "orchestrator": "LangGraph StateGraph",
                        "status":       "ready",
                    }),
                )]

            if name == "get_context":
                mission_id = arguments["mission_id"]
                ctx = memory.get_context(mission_id)
                return [TextContent(
                    type="text",
                    text=json.dumps(ctx or {"error": "No context found"}, default=str),
                )]

            # All remaining tools need mission_id and context
            mission_id = arguments["mission_id"]
            context    = arguments["context"]

            if name == "run_full_pipeline":
                # ── LangGraph path ────────────────────────────────────────
                from orchestrator.kyc_graph import build_graph

                graph = build_graph(
                    model=settings.ollama_model,
                    ollama_host=settings.ollama_host,
                    redis_url=settings.redis_url,
                )
                # Invoke the full StateGraph; returns final merged state
                result = graph.invoke(
                    context,
                    config={"configurable": {"thread_id": mission_id}},
                )

                memory.update_context(mission_id, result)
                result["status"] = result.get("status", "COMPLETE")

            else:
                # ── Individual-agent path ─────────────────────────────────
                agent_map = {
                    "run_data_collection": "DataCollectionAgent",
                    "run_risk_assessment": "RiskAssessmentAgent",
                    "run_screening":       "AereveScreeningAgent",
                    "run_alert_review":    "AlertReviewAgent",
                    "run_decision":        "DecisionAgent",
                    "run_documentation":   "DocumentationAgent",
                }
                agent_name = agent_map.get(name)
                if not agent_name:
                    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

                agents = _build_agents()
                agent  = agents[agent_name]
                result = agent.run(context)

                memory.update_context(mission_id, result)
                _store_phase_insight(memory, agent_name, mission_id, result)

            return [TextContent(
                type="text",
                text=json.dumps(result, default=str),
            )]

        except Exception as e:
            logger.error("AgentZero tool error (%s): %s", name, e)
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e), "tool": name}),
            )]

    return server


def _store_phase_insight(memory: MemoryManager, agent_name: str, mission_id: str, context: dict):
    """Store a learning insight after a phase for cross-mission recall."""
    insights = {
        "RiskAssessmentAgent": (
            f"Risk assessment: level={context.get('risk_level')}, "
            f"score={context.get('risk_score')}"
        ),
        "AereveScreeningAgent": (
            f"Screening: {context.get('screening_results', {}).get('total_hits', 0)} hits"
        ),
        "DecisionAgent": (
            f"Decision: {context.get('final_decision')} for "
            f"customer {context.get('customer_id')}"
        ),
    }
    insight = insights.get(agent_name)
    if insight:
        memory.store_agent_insight(
            agent_name, mission_id, insight,
            metadata={
                "customer_id": context.get("customer_id"),
                "risk_level":  context.get("risk_level"),
                "decision":    context.get("final_decision"),
            },
        )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
