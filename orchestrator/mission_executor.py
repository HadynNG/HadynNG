"""
Mission Executor — the central coordinator of the agentic platform.

Responsibilities:
1. Accept a mission payload (customer_id + event + description).
2. Use TaskPlanner (LLM) to build an execution plan.
3. Dispatch agents in sequence according to the plan.
4. Track progress via MissionTimeline (for UI consumption).
5. Display rich chain-of-thought output throughout.
"""
import sys
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

from .task_planner import TaskPlanner
from .mission_timeline import MissionTimeline
from agents import (
    AlertReviewAgent,
    DataCollectionAgent,
    DecisionAgent,
    DocumentationAgent,
    RiskAssessmentAgent,
    AereveScreeningAgent,
)

console = Console()

# Registry mapping agent names → classes
AGENT_REGISTRY = {
    "DataCollectionAgent": DataCollectionAgent,
    "RiskAssessmentAgent": RiskAssessmentAgent,
    "AereveScreeningAgent": AereveScreeningAgent,
    "AlertReviewAgent": AlertReviewAgent,
    "DecisionAgent": DecisionAgent,
    "DocumentationAgent": DocumentationAgent,
}

# Canonical execution order (always enforced)
PIPELINE_ORDER = [
    "DataCollectionAgent",
    "RiskAssessmentAgent",
    "AereveScreeningAgent",
    "AlertReviewAgent",
    "DecisionAgent",
    "DocumentationAgent",
]


class MissionExecutor:
    """
    Central mission coordinator.

    Usage:
        executor = MissionExecutor()
        result = executor.execute(mission_payload)
    """

    def __init__(
        self,
        model: str = "qwen3.5:9b",
        ollama_host: str = "http://localhost:11434",
    ):
        self.model = model
        self.ollama_host = ollama_host
        self.planner = TaskPlanner(model=model, ollama_host=ollama_host)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_agents(self) -> dict:
        return {
            name: cls(model=self.model, ollama_host=self.ollama_host)
            for name, cls in AGENT_REGISTRY.items()
        }

    def _print_banner(self, mission_payload: dict):
        console.print()
        console.print(Rule("[bold magenta]AGENTIC KYC PLATFORM[/bold magenta]", style="magenta"))
        console.print(
            Panel(
                f"[bold]Customer ID:[/bold]  {mission_payload.get('customer_id', 'N/A')}\n"
                f"[bold]Event Type:[/bold]   {mission_payload.get('event', {}).get('event_type', 'N/A')}\n"
                f"[bold]Initiated:[/bold]    {datetime.utcnow().isoformat()}Z\n"
                f"[bold]Model:[/bold]        {self.model}\n"
                f"[bold]Host:[/bold]         {self.ollama_host}",
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
            ("Customer", context.get("customer_data", {}).get("full_name", "N/A")),
            ("Customer ID", context.get("customer_id", "N/A")),
            ("Event Type", context.get("event_type", "N/A")),
            ("Identity Verified", context.get("identity_verification", {}).get("status", "N/A")),
            ("Risk Level", context.get("risk_level", "N/A")),
            ("Risk Score", str(context.get("risk_score", "N/A"))),
            ("Screening Hits", str(context.get("screening_results", {}).get("total_hits", 0))),
            ("True Positives", str(context.get("step_4_2", {}).get("true_positives", 0))),
            ("EDD Required", str(context.get("edd_required", False))),
            ("STR Filed", str(context.get("step_5_3", {}).get("str_filed", False))),
            ("MLRO Escalated", str(context.get("step_5_2", {}).get("escalated", False))),
            ("Final Decision", f"[bold {color}]{decision}[/bold {color}]"),
            ("Audit ID", context.get("audit_id", "N/A")),
            ("Audit Log", context.get("audit_log_file", "N/A")),
            ("Total Time", f"{elapsed:.1f}s"),
        ]

        for field, value in rows:
            table.add_row(field, value)

        console.print(table)
        console.print()

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    def execute(self, mission_payload: dict) -> dict:
        """
        Execute a complete KYC screening mission.

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

        # --- Step A: Build execution context ---
        customer_id = mission_payload["customer_id"]
        context = {
            "customer_id": customer_id,
            "event": mission_payload.get("event", {}),
            "mission_payload": mission_payload,
            "audit_log": [],
            "status": "IN_PROGRESS",
        }

        # --- Step B: Initialise timeline ---
        # mission_id: use plan's ID later; for now derive from customer_id + timestamp
        mission_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        timeline = MissionTimeline(
            mission_id=f"{customer_id}-{mission_ts}",
            customer_id=customer_id,
            customer_name=mission_payload.get("customer_name", customer_id),
            model=self.model,
        )
        context["timeline"] = timeline
        context["timeline_file"] = timeline.filepath

        # --- Step C: Plan the mission using LLM ---
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

        # Backfill mission_id into timeline if available
        if plan.get("mission_id"):
            timeline._data["mission_id"] = plan["mission_id"]
            timeline._write()

        # --- Step D: Build agents ---
        agents = self._build_agents()

        # --- Step E: Execute pipeline in canonical order ---
        console.print()
        console.print(Rule("[bold cyan]PIPELINE EXECUTION STARTING[/bold cyan]", style="cyan"))

        for agent_name in PIPELINE_ORDER:
            agent = agents.get(agent_name)
            if not agent:
                console.print(f"[red]Agent not found: {agent_name}[/red]")
                continue

            timeline.start_phase(agent_name)
            try:
                context = agent.run(context)
            except Exception as e:
                console.print(f"\n[red]Agent {agent_name} raised an error: {e}[/red]")
                context["audit_log"].append({
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "agent": agent_name,
                    "level": "ERROR",
                    "message": str(e),
                })
                timeline.complete_phase(agent_name, summary=f"Agent error: {e}", status="FAILED")
                if agent_name == "DataCollectionAgent":
                    context["status"] = "FAILED"
                    timeline.fail_mission(f"Fatal error in {agent_name}: {e}")
                    break
                continue

            # Build a compact summary for the timeline from context
            phase_summary = self._phase_summary(agent_name, context)
            phase_outputs = self._phase_outputs(agent_name, context)
            timeline.complete_phase(agent_name, summary=phase_summary, key_outputs=phase_outputs)

            # Stop pipeline early on hard escalations
            if context.get("status", "").startswith("ESCALATED_") and agent_name == "DataCollectionAgent":
                console.print(f"[red]Pipeline halted at {agent_name}: {context['status']}[/red]")
                timeline.fail_mission(f"Escalated: {context['status']}")
                break

        # --- Step F: Final report ---
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        context["status"] = "COMPLETE"
        context["elapsed_seconds"] = elapsed
        timeline.complete_mission(context)

        self._print_final_report(context, elapsed)
        console.print(f"  [dim]Timeline written to: {timeline.filepath}[/dim]")
        return context

    # ------------------------------------------------------------------
    # Timeline summary helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _phase_summary(agent_name: str, context: dict) -> str:
        """Return a one-line human-readable summary for the timeline."""
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
        """Return key structured outputs for the timeline phase."""
        outputs = {
            "DataCollectionAgent": {
                "identity_status": context.get("identity_verification", {}).get("status"),
                "jurisdiction_risk": context.get("jurisdiction_risk", {}).get("risk_level"),
            },
            "RiskAssessmentAgent": {
                "risk_level": context.get("risk_level"),
                "risk_score": context.get("risk_score"),
            },
            "AereveScreeningAgent": {
                "total_hits": context.get("screening_results", {}).get("total_hits", 0),
                "adverse_media_count": len(context.get("adverse_media", [])),
                "lists_checked": context.get("screening_results", {}).get("lists_checked", []),
            },
            "AlertReviewAgent": {
                "triaged": context.get("step_4_1", {}).get("triaged_count", 0),
                "true_positives": context.get("step_4_2", {}).get("true_positives", 0),
                "false_positives": context.get("step_4_2", {}).get("false_positives", 0),
                "edd_required": context.get("edd_required", False),
            },
            "DecisionAgent": {
                "decision": context.get("final_decision"),
                "requires_str": context.get("requires_str", False),
                "escalated": context.get("step_5_2", {}).get("escalated", False),
            },
            "DocumentationAgent": {
                "audit_id": context.get("audit_id"),
                "audit_log_file": context.get("audit_log_file"),
            },
        }
        return outputs.get(agent_name, {})
