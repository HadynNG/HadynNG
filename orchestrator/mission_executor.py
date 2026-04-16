"""
Mission Executor — the central coordinator of the agentic platform.

Responsibilities:
1. Accept a mission payload (customer_id + event + description).
2. Use TaskPlanner (LLM) to build an execution plan.
3. Drive agents via a LangGraph StateGraph (graph.stream()), replacing the
   previous manual for-loop over PIPELINE_ORDER.
4. Track progress via MissionTimeline (external to the graph — managed here).
5. Persist context in Redis/memory service when available.
6. Display rich chain-of-thought output throughout.

Architecture paths:
  Demo mode:   Orchestrator → LangGraph graph (direct agent calls)
  Production:  Orchestrator → LangGraph graph (agents → Tool MCP → Tools)
               + Redis checkpointing for mission resumability

How LangGraph replaces the for-loop:
  - graph.stream() yields {node_name: updated_state_keys} after each node.
  - MissionExecutor intercepts each chunk: completes the timeline phase,
    publishes to memory, then pre-starts the next expected phase.
  - Conditional edge: DataCollection FAILED → documentation (skips phases 2-5).
"""
import sys
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .task_planner import TaskPlanner
from .mission_timeline import MissionTimeline
from .kyc_graph import build_graph, NODE_TO_AGENT

console = Console()

# Canonical pipeline order — used to pre-start timeline phases
PIPELINE_ORDER = [
    "DataCollectionAgent",
    "RiskAssessmentAgent",
    "AereveScreeningAgent",
    "AlertReviewAgent",
    "DecisionAgent",
    "DocumentationAgent",
]

# Next expected agent after each one (for timeline pre-start)
_NEXT_AGENT: dict[str, Optional[str]] = {
    "DataCollectionAgent":  "RiskAssessmentAgent",
    "RiskAssessmentAgent":  "AereveScreeningAgent",
    "AereveScreeningAgent": "AlertReviewAgent",
    "AlertReviewAgent":     "DecisionAgent",
    "DecisionAgent":        "DocumentationAgent",
    "DocumentationAgent":   None,
}


class MissionExecutor:
    """
    Central mission coordinator.

    Usage:
        # Demo mode (backward-compatible)
        executor = MissionExecutor()
        result = executor.execute(mission_payload)

        # Production mode (with services)
        executor = MissionExecutor(
            llm_gateway=llm_gateway,
            memory=memory_manager,
        )
        result = executor.execute(mission_payload)
    """

    def __init__(
        self,
        model: str = "qwen3.5:9b",
        ollama_host: str = "http://localhost:11434",
        llm_gateway: Optional[object] = None,
        memory: Optional[object] = None,
    ):
        self.model = model
        self.ollama_host = ollama_host
        self._llm_gateway = llm_gateway
        self._memory = memory
        self.planner = TaskPlanner(model=model, ollama_host=ollama_host)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _print_banner(self, mission_payload: dict):
        mode = "Production (LLM Gateway + LangGraph)" if self._llm_gateway else "Demo (Direct Ollama + LangGraph)"
        console.print()
        console.print(Rule("[bold magenta]AGENTIC KYC PLATFORM[/bold magenta]", style="magenta"))
        console.print(
            Panel(
                f"[bold]Customer ID:[/bold]  {mission_payload.get('customer_id', 'N/A')}\n"
                f"[bold]Event Type:[/bold]   {mission_payload.get('event', {}).get('event_type', 'N/A')}\n"
                f"[bold]Initiated:[/bold]    {datetime.utcnow().isoformat()}Z\n"
                f"[bold]Model:[/bold]        {self.model}\n"
                f"[bold]Host:[/bold]         {self.ollama_host}\n"
                f"[bold]Mode:[/bold]         {mode}",
                title="[bold magenta]MISSION INITIATED[/bold magenta]",
                border_style="magenta",
            )
        )

    def _print_final_report(self, context: dict, elapsed: float):
        decision = context.get("final_decision", "UNKNOWN")
        decision_colors = {
            "APPROVE": "green",
            "APPROVE_WITH_CONDITIONS": "yellow",
            "ESCALATE_TO_MLRO": "red",
            "REJECT": "red",
        }
        color = decision_colors.get(decision, "white")

        console.print()
        console.print(Rule("[bold magenta]MISSION COMPLETE[/bold magenta]", style="magenta"))

        table = Table(title="Final KYC Screening Summary", show_header=True, header_style="bold magenta")
        table.add_column("Field", style="dim", width=30)
        table.add_column("Value")

        rows = [
            ("Customer",         context.get("customer_data", {}).get("full_name", "N/A")),
            ("Customer ID",      context.get("customer_id", "N/A")),
            ("Event Type",       context.get("event_type", "N/A")),
            ("Identity Verified",context.get("identity_verification", {}).get("status", "N/A")),
            ("Risk Level",       context.get("risk_level", "N/A")),
            ("Risk Score",       str(context.get("risk_score", "N/A"))),
            ("Screening Hits",   str(context.get("screening_results", {}).get("total_hits", 0))),
            ("True Positives",   str(context.get("step_4_2", {}).get("true_positives", 0))),
            ("EDD Required",     str(context.get("edd_required", False))),
            ("STR Filed",        str(context.get("step_5_3", {}).get("str_filed", False))),
            ("MLRO Escalated",   str(context.get("step_5_2", {}).get("escalated", False))),
            ("Final Decision",   f"[bold {color}]{decision}[/bold {color}]"),
            ("Audit ID",         context.get("audit_id", "N/A")),
            ("Audit Log",        context.get("audit_log_file", "N/A")),
            ("Total Time",       f"{elapsed:.1f}s"),
        ]

        for field, value in rows:
            table.add_row(field, value)

        console.print(table)
        console.print()

    # ── Main execution loop ────────────────────────────────────────────────

    def execute(self, mission_payload: dict) -> dict:
        """
        Execute a complete KYC screening mission via LangGraph StateGraph.

        The StateGraph streams one chunk per completed node.  For each chunk:
          1. The timeline phase is completed.
          2. Memory is updated (Redis).
          3. A real-time pub/sub event is published for WebSocket consumers.
          4. The next timeline phase is pre-started.

        Args:
            mission_payload: Dict with keys:
                - customer_id (str)
                - event (dict)
                - mission_description (str, optional)

        Returns:
            Final context dict with all results.
        """
        start_time = datetime.utcnow()
        self._print_banner(mission_payload)

        # ── Step A: Build initial context ──────────────────────────────────
        customer_id = mission_payload["customer_id"]
        context: dict = {
            "customer_id":    customer_id,
            "event":          mission_payload.get("event", {}),
            "mission_payload":mission_payload,
            "audit_log":      [],
            "status":         "IN_PROGRESS",
        }

        # ── Step B: Initialise timeline ────────────────────────────────────
        mission_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        mission_id = f"{customer_id}-{mission_ts}"
        timeline = MissionTimeline(
            mission_id=mission_id,
            customer_id=customer_id,
            customer_name=mission_payload.get("customer_name", customer_id),
            model=self.model,
        )
        context["timeline_file"] = timeline.filepath
        context["mission_id"]    = mission_id

        if self._memory:
            self._memory.set_context(mission_id, context)

        # ── Step C: Plan the mission ───────────────────────────────────────
        mission_description = mission_payload.get(
            "mission_description",
            f"KYC name screening for customer {customer_id} "
            f"triggered by {mission_payload.get('event', {}).get('event_type', 'unknown event')}.",
        )

        timeline.start_phase("Orchestrator")
        try:
            plan = self.planner.plan(mission_description)
            timeline.complete_phase(
                "Orchestrator",
                summary=plan.get("mission_summary", "Execution plan ready"),
                key_outputs={"mission_id": plan.get("mission_id"), "risk_flags": plan.get("risk_flags", [])},
            )
        except Exception as e:
            console.print(f"[red]Task planner error: {e}[/red]")
            plan = {"execution_plan": [{"agent": a} for a in PIPELINE_ORDER]}
            timeline.complete_phase("Orchestrator", summary=f"Planner error — using default plan: {e}", status="FAILED")

        context["mission_plan"] = plan

        if plan.get("mission_id"):
            timeline._data["mission_id"] = plan["mission_id"]
            timeline._write()

        # ── Step D: Build LangGraph and stream pipeline ────────────────────
        redis_url = None
        if self._memory:
            try:
                from config import settings
                redis_url = settings.redis_url
            except Exception:
                pass

        graph = build_graph(
            model=self.model,
            ollama_host=self.ollama_host,
            llm_gateway=self._llm_gateway,
            memory=self._memory,
            redis_url=redis_url,
        )

        console.print()
        console.print(Rule("[bold cyan]PIPELINE EXECUTION STARTING (LangGraph)[/bold cyan]", style="cyan"))

        # Pre-start the first timeline phase
        timeline.start_phase("DataCollectionAgent")

        # Stream config — only attach thread_id when a checkpointer is present
        stream_config = {}
        if redis_url:
            stream_config = {"configurable": {"thread_id": mission_id}}

        # ── Step E: Stream graph, one chunk per completed node ─────────────
        for chunk in graph.stream(context, config=stream_config):
            node_name, updates = next(iter(chunk.items()))
            agent_name = NODE_TO_AGENT.get(node_name, node_name)

            # Merge node output into local context
            context.update(updates)

            # Build timeline summary from updated context
            phase_summary = self._phase_summary(agent_name, context)
            phase_outputs = self._phase_outputs(agent_name, context)
            timeline.complete_phase(agent_name, summary=phase_summary, key_outputs=phase_outputs)

            # Persist to memory after each phase
            if self._memory:
                self._memory.update_context(mission_id, {
                    "status":         context.get("status"),
                    "current_phase":  agent_name,
                    "risk_level":     context.get("risk_level"),
                    "risk_score":     context.get("risk_score"),
                    "final_decision": context.get("final_decision"),
                })
                self._memory.publish_event(f"mission:{mission_id}", {
                    "event":   "phase_complete",
                    "phase":   agent_name,
                    "summary": phase_summary,
                })

            # Pre-start next phase for timeline continuity
            # Handle DataCollection failure: jump straight to Documentation
            if agent_name == "DataCollectionAgent" and context.get("status", "").upper() in ("FAILED", "ERROR"):
                timeline.start_phase("DocumentationAgent")
            else:
                next_agent = _NEXT_AGENT.get(agent_name)
                if next_agent:
                    timeline.start_phase(next_agent)

        # ── Step F: Final report ───────────────────────────────────────────
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        context["status"]          = "COMPLETE"
        context["elapsed_seconds"] = elapsed
        timeline.complete_mission(context)

        if self._memory:
            self._memory.update_context(mission_id, {
                "status":           "COMPLETE",
                "final_decision":   context.get("final_decision"),
                "elapsed_seconds":  elapsed,
            })
            self._memory.publish_event(f"mission:{mission_id}", {
                "event":    "completed",
                "decision": context.get("final_decision"),
            })

        self._print_final_report(context, elapsed)
        console.print(f"  [dim]Timeline written to: {timeline.filepath}[/dim]")
        return context

    # ── Timeline summary helpers ───────────────────────────────────────────

    @staticmethod
    def _phase_summary(agent_name: str, context: dict) -> str:
        summaries = {
            "DataCollectionAgent": (
                f"Customer {context.get('customer_data', {}).get('full_name', '?')} verified — "
                f"identity {context.get('identity_verification', {}).get('status', '?')}"
            ),
            "RiskAssessmentAgent": (
                f"Risk level: {context.get('risk_level', '?')} "
                f"(score: {context.get('risk_score', '?')})"
            ),
            "AereveScreeningAgent": (
                f"{context.get('screening_results', {}).get('total_hits', 0)} hit(s) found — "
                f"{len(context.get('adverse_media', []))} adverse media item(s)"
            ),
            "AlertReviewAgent": (
                f"Triaged {context.get('step_4_1', {}).get('triaged_count', 0)} alert(s) — "
                f"TP: {context.get('step_4_2', {}).get('true_positives', 0)}, "
                f"FP: {context.get('step_4_2', {}).get('false_positives', 0)}"
            ),
            "DecisionAgent": (
                f"Decision: {context.get('final_decision', '?')} — "
                f"STR: {context.get('step_5_3', {}).get('str_filed', False)}"
            ),
            "DocumentationAgent": (
                f"Audit trail saved — {len(context.get('audit_log', []))} log entries"
            ),
        }
        return summaries.get(agent_name, f"{agent_name} completed")

    @staticmethod
    def _phase_outputs(agent_name: str, context: dict) -> dict:
        outputs = {
            "DataCollectionAgent": {
                "identity_status":   context.get("identity_verification", {}).get("status"),
                "jurisdiction_risk": context.get("jurisdiction_risk", {}).get("risk_level"),
            },
            "RiskAssessmentAgent": {
                "risk_level": context.get("risk_level"),
                "risk_score": context.get("risk_score"),
            },
            "AereveScreeningAgent": {
                "total_hits":          context.get("screening_results", {}).get("total_hits", 0),
                "adverse_media_count": len(context.get("adverse_media", [])),
                "lists_checked":       context.get("screening_results", {}).get("lists_checked", []),
            },
            "AlertReviewAgent": {
                "triaged":        context.get("step_4_1", {}).get("triaged_count", 0),
                "true_positives": context.get("step_4_2", {}).get("true_positives", 0),
                "false_positives":context.get("step_4_2", {}).get("false_positives", 0),
                "edd_required":   context.get("edd_required", False),
            },
            "DecisionAgent": {
                "decision":     context.get("final_decision"),
                "requires_str": context.get("requires_str", False),
                "escalated":    context.get("step_5_2", {}).get("escalated", False),
            },
            "DocumentationAgent": {
                "audit_id":       context.get("audit_id"),
                "audit_log_file": context.get("audit_log_file"),
            },
        }
        return outputs.get(agent_name, {})
