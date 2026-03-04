"""
Mission Executor — the central coordinator of the agentic platform.

Responsibilities:
1. Accept a mission payload (customer_id + event + description).
2. Use TaskPlanner (LLM) to build an execution plan.
3. Dispatch agents in sequence according to the plan.
4. Track progress, handle failures, and produce a final report.
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
from agents import (
    AlertReviewAgent,
    DataCollectionAgent,
    DecisionAgent,
    DocumentationAgent,
    RiskAssessmentAgent,
    ScreeningAgent,
)

console = Console()

# Registry mapping agent names → classes
AGENT_REGISTRY = {
    "DataCollectionAgent": DataCollectionAgent,
    "RiskAssessmentAgent": RiskAssessmentAgent,
    "ScreeningAgent": ScreeningAgent,
    "AlertReviewAgent": AlertReviewAgent,
    "DecisionAgent": DecisionAgent,
    "DocumentationAgent": DocumentationAgent,
}

# Canonical execution order (always enforced)
PIPELINE_ORDER = [
    "DataCollectionAgent",
    "RiskAssessmentAgent",
    "ScreeningAgent",
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
        model: str = "qwen3-coder-next:latest",
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
        context = {
            "customer_id": mission_payload["customer_id"],
            "event": mission_payload.get("event", {}),
            "mission_payload": mission_payload,
            "audit_log": [],
            "status": "IN_PROGRESS",
        }

        # --- Step B: Plan the mission using LLM ---
        mission_description = mission_payload.get(
            "mission_description",
            f"KYC name screening for customer {mission_payload['customer_id']} "
            f"triggered by {mission_payload.get('event', {}).get('event_type', 'unknown event')}.",
        )

        try:
            plan = self.planner.plan(mission_description)
        except Exception as e:
            console.print(f"[red]Task planner error: {e}[/red]")
            plan = {"execution_plan": [{"agent": a} for a in PIPELINE_ORDER]}

        context["mission_plan"] = plan

        # --- Step C: Build agents ---
        agents = self._build_agents()

        # --- Step D: Execute pipeline in canonical order ---
        console.print()
        console.print(Rule("[bold cyan]PIPELINE EXECUTION STARTING[/bold cyan]", style="cyan"))

        for agent_name in PIPELINE_ORDER:
            agent = agents.get(agent_name)
            if not agent:
                console.print(f"[red]Agent not found: {agent_name}[/red]")
                continue

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
                # Continue pipeline unless it's a fatal error
                if agent_name in ("DataCollectionAgent",):
                    context["status"] = "FAILED"
                    break

            # Stop pipeline early on hard escalations
            if context.get("status", "").startswith("ESCALATED_") and agent_name == "DataCollectionAgent":
                console.print(
                    f"[red]Pipeline halted at {agent_name}: {context['status']}[/red]"
                )
                break

        # --- Step E: Final report ---
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        context["status"] = "COMPLETE"
        context["elapsed_seconds"] = elapsed
        self._print_final_report(context, elapsed)

        return context
