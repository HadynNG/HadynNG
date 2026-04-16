"""
Mule Executor — coordinator for the 7-checkpoint mule account hunting pipeline.

Responsibilities:
1. Accept a mule investigation payload (account_id + alert + notes).
2. Drive agents via the Mule LangGraph StateGraph (graph.stream()).
3. Track progress via MissionTimeline (external to the graph).
4. Persist context in Redis/memory service when available.
5. Display rich chain-of-thought output throughout.

Architecture paths:
  Demo mode:   MuleExecutor → LangGraph mule graph (direct agent calls)
  Production:  MuleExecutor → LangGraph mule graph + Redis checkpointing

Checkpoint pipeline:
  CP1 MuleAlertValidationAgent    → CP2 LinkedAccountDiscoveryAgent
  → CP3 FundFlowLayeringAgent     → CP4 RecruitmentPatternAgent (★)
  → CP5 ScamFraudCorrelationAgent → CP6 OutreachSourceOfFundsAgent
  → CP7 SARDraftingAgent
"""
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from .mission_timeline import MissionTimeline
from .mule_graph import build_mule_graph, MULE_NODE_TO_AGENT

console = Console()

# Canonical checkpoint order for timeline pre-start
MULE_PIPELINE_ORDER = [
    "MuleAlertValidationAgent",
    "LinkedAccountDiscoveryAgent",
    "FundFlowLayeringAgent",
    "RecruitmentPatternAgent",
    "ScamFraudCorrelationAgent",
    "OutreachSourceOfFundsAgent",
    "SARDraftingAgent",
]

# Next expected agent after each (for timeline pre-start)
_NEXT_MULE_AGENT: dict[str, Optional[str]] = {
    "MuleAlertValidationAgent":    "LinkedAccountDiscoveryAgent",
    "LinkedAccountDiscoveryAgent": "FundFlowLayeringAgent",
    "FundFlowLayeringAgent":       "RecruitmentPatternAgent",
    "RecruitmentPatternAgent":     "ScamFraudCorrelationAgent",
    "ScamFraudCorrelationAgent":   "OutreachSourceOfFundsAgent",
    "OutreachSourceOfFundsAgent":  "SARDraftingAgent",
    "SARDraftingAgent":            None,
}


class MuleExecutor:
    """
    Central coordinator for mule account hunting missions.

    Usage:
        # Demo mode (backward-compatible)
        executor = MuleExecutor()
        result = executor.execute(mule_payload)

        # Production mode (with services)
        executor = MuleExecutor(
            llm_gateway=llm_gateway,
            memory=memory_manager,
        )
        result = executor.execute(mule_payload)
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

    # ── Helpers ────────────────────────────────────────────────────────────

    def _print_banner(self, payload: dict):
        mode = "Production (LLM Gateway + LangGraph)" if self._llm_gateway else "Demo (Direct Ollama + LangGraph)"
        console.print()
        console.print(Rule("[bold red]MULE ACCOUNT HUNTING PLATFORM[/bold red]", style="red"))
        console.print(
            Panel(
                f"[bold]Account ID:[/bold]   {payload.get('account_id', 'N/A')}\n"
                f"[bold]Account Name:[/bold] {payload.get('account_name', 'N/A')}\n"
                f"[bold]Alert Type:[/bold]   {payload.get('alert', {}).get('alert_type', 'N/A')}\n"
                f"[bold]Priority:[/bold]     {payload.get('alert', {}).get('priority', 'N/A')}\n"
                f"[bold]Initiated:[/bold]    {datetime.utcnow().isoformat()}Z\n"
                f"[bold]Model:[/bold]        {self.model}\n"
                f"[bold]Mode:[/bold]         {mode}",
                title="[bold red]MULE INVESTIGATION INITIATED[/bold red]",
                border_style="red",
            )
        )

    def _print_final_report(self, context: dict, elapsed: float):
        disposition = context.get("final_disposition", "UNKNOWN")
        colors = {
            "FILE_SAR":         "red",
            "ESCALATE_TO_MLRO": "red",
            "MONITOR":          "yellow",
            "CLOSE_NO_ACTION":  "green",
        }
        color = colors.get(disposition, "white")

        console.print()
        console.print(Rule("[bold red]MULE INVESTIGATION COMPLETE[/bold red]", style="red"))

        table = Table(
            title="Mule Investigation Summary",
            show_header=True,
            header_style="bold red",
        )
        table.add_column("Field", style="dim", width=30)
        table.add_column("Value")

        rows = [
            ("Account ID",             context.get("account_id", "N/A")),
            ("Account Name",           context.get("account_profile", {}).get("full_name", "N/A")),
            ("Alert Type",             context.get("alert_type", "N/A")),
            ("Alert Priority",         context.get("alert_priority", "N/A")),
            ("Mule Type",              context.get("mule_type", "N/A")),
            ("Recruitment Likelihood", context.get("recruitment_likelihood", "N/A")),
            ("Fraud Typology",         context.get("fraud_typology", "N/A")),
            ("Correlation Confidence", f"{context.get('correlation_confidence', 0):.0%}"),
            ("Total Exposure (HKD)",   f"{context.get('total_exposure_hkd', 0):,.0f}"),
            ("Layering Detected",      str(context.get("layering_detected", False))),
            ("Linked Accounts",        str(len(context.get("linked_accounts", [])))),
            ("Known Network Member",   str(context.get("known_network_member", False))),
            ("SOF Credibility",        context.get("explanation_credibility", "N/A")),
            ("SAR Reference",          context.get("sar_reference") or "None"),
            ("Final Disposition",      f"[bold {color}]{disposition}[/bold {color}]"),
            ("Total Time",             f"{elapsed:.1f}s"),
        ]

        for field, value in rows:
            table.add_row(field, value)

        console.print(table)
        console.print()

    # ── Main execution loop ────────────────────────────────────────────────

    def execute(self, payload: dict) -> dict:
        """
        Execute a complete mule investigation via the LangGraph MuleState graph.

        Args:
            payload: Dict with keys:
                - account_id (str)
                - account_name (str, optional)
                - alert (dict): alert_type, priority, source, triggered_at
                - notes (str, optional)

        Returns:
            Final context dict with all 7-checkpoint results.
        """
        start_time = datetime.utcnow()
        self._print_banner(payload)

        # ── Step A: Build initial state ────────────────────────────────────
        account_id = payload["account_id"]
        context: dict = {
            "account_id":   account_id,
            "account_name": payload.get("account_name", account_id),
            "alert":        payload.get("alert", {}),
            "alert_type":   payload.get("alert", {}).get("alert_type", "transaction_velocity"),
            "notes":        payload.get("notes", ""),
            "audit_log":    [],
            "mule_status":  "IN_PROGRESS",
        }

        # ── Step B: Initialise timeline ────────────────────────────────────
        mission_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        mission_id = f"MULE-{account_id}-{mission_ts}"
        timeline = MissionTimeline(
            mission_id=mission_id,
            customer_id=account_id,
            customer_name=payload.get("account_name", account_id),
            model=self.model,
        )
        context["mission_id"] = mission_id

        if self._memory:
            self._memory.set_context(mission_id, context)

        # ── Step C: Build LangGraph and stream pipeline ────────────────────
        redis_url = None
        if self._memory:
            try:
                from config import settings
                redis_url = settings.redis_url
            except Exception:
                pass

        graph = build_mule_graph(
            model=self.model,
            ollama_host=self.ollama_host,
            llm_gateway=self._llm_gateway,
            memory=self._memory,
            redis_url=redis_url,
        )

        console.print()
        console.print(Rule(
            "[bold red]MULE PIPELINE EXECUTION STARTING (LangGraph — 7 Checkpoints)[/bold red]",
            style="red",
        ))

        # Pre-start first timeline phase
        timeline.start_phase("MuleAlertValidationAgent")

        stream_config = {}
        if redis_url:
            stream_config = {"configurable": {"thread_id": mission_id}}

        # ── Step D: Stream graph, one chunk per completed checkpoint ───────
        for chunk in graph.stream(context, config=stream_config):
            node_name, updates = next(iter(chunk.items()))
            agent_name = MULE_NODE_TO_AGENT.get(node_name, node_name)

            # Merge checkpoint output into local context
            context.update(updates)

            # Build timeline summary and complete phase
            phase_summary = self._phase_summary(agent_name, context)
            phase_outputs = self._phase_outputs(agent_name, context)
            timeline.complete_phase(agent_name, summary=phase_summary, key_outputs=phase_outputs)

            # Persist to memory after each checkpoint
            if self._memory:
                self._memory.update_context(mission_id, {
                    "mule_status":       context.get("mule_status"),
                    "current_checkpoint": agent_name,
                    "mule_type":         context.get("mule_type"),
                    "final_disposition": context.get("final_disposition"),
                })
                self._memory.publish_event(f"mission:{mission_id}", {
                    "event":   "checkpoint_complete",
                    "checkpoint": agent_name,
                    "summary": phase_summary,
                })

            # Pre-start next checkpoint for timeline continuity
            # If alert was closed at CP1, no more phases run
            mule_status = context.get("mule_status", "")
            if agent_name == "MuleAlertValidationAgent" and mule_status.upper() in (
                "ALERT_CLOSED", "ACCOUNT_NOT_FOUND"
            ):
                pass  # graph ends — no next agent
            else:
                next_agent = _NEXT_MULE_AGENT.get(agent_name)
                if next_agent:
                    timeline.start_phase(next_agent)

        # ── Step E: Final report ───────────────────────────────────────────
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        context["mule_status"] = "COMPLETE"
        context["elapsed_seconds"] = elapsed
        timeline.complete_mission(context)

        if self._memory:
            self._memory.update_context(mission_id, {
                "mule_status":       "COMPLETE",
                "final_disposition": context.get("final_disposition"),
                "elapsed_seconds":   elapsed,
            })
            self._memory.publish_event(f"mission:{mission_id}", {
                "event":       "completed",
                "disposition": context.get("final_disposition"),
            })

        self._print_final_report(context, elapsed)
        console.print(f"  [dim]Timeline written to: {timeline.filepath}[/dim]")
        return context

    # ── Timeline summary helpers ───────────────────────────────────────────

    @staticmethod
    def _phase_summary(agent_name: str, context: dict) -> str:
        summaries = {
            "MuleAlertValidationAgent": (
                f"Alert {context.get('alert_type', '?')} | "
                f"Priority: {context.get('alert_priority', '?')} | "
                f"Status: {context.get('mule_status', '?')}"
            ),
            "LinkedAccountDiscoveryAgent": (
                f"{len(context.get('linked_accounts', []))} linked account(s) | "
                f"Network risk: {context.get('network_risk', '?')}"
            ),
            "FundFlowLayeringAgent": (
                f"Exposure HKD {context.get('total_exposure_hkd', 0):,.0f} | "
                f"Layering: {context.get('layering_detected', False)} | "
                f"{len(context.get('layering_patterns', []))} pattern(s)"
            ),
            "RecruitmentPatternAgent": (
                f"Mule type: {context.get('mule_type', '?')} | "
                f"Likelihood: {context.get('recruitment_likelihood', '?')}"
            ),
            "ScamFraudCorrelationAgent": (
                f"Typology: {context.get('fraud_typology', '?')} | "
                f"Confidence: {context.get('correlation_confidence', 0):.0%}"
            ),
            "OutreachSourceOfFundsAgent": (
                f"SOF credibility: {context.get('explanation_credibility', '?')} | "
                f"Outreach: {context.get('outreach_conducted', False)}"
            ),
            "SARDraftingAgent": (
                f"Disposition: {context.get('final_disposition', '?')} | "
                f"SAR: {context.get('sar_reference') or 'none'}"
            ),
        }
        return summaries.get(agent_name, f"{agent_name} completed")

    @staticmethod
    def _phase_outputs(agent_name: str, context: dict) -> dict:
        outputs = {
            "MuleAlertValidationAgent": {
                "alert_priority": context.get("alert_priority"),
                "alert_type":     context.get("alert_type"),
            },
            "LinkedAccountDiscoveryAgent": {
                "linked_account_count": len(context.get("linked_accounts", [])),
                "network_risk":         context.get("network_risk"),
                "known_network_member": context.get("known_network_member"),
            },
            "FundFlowLayeringAgent": {
                "total_exposure_hkd": context.get("total_exposure_hkd"),
                "layering_detected":  context.get("layering_detected"),
                "layering_patterns":  len(context.get("layering_patterns", [])),
            },
            "RecruitmentPatternAgent": {
                "mule_type":              context.get("mule_type"),
                "recruitment_likelihood": context.get("recruitment_likelihood"),
                "typology":               context.get("cp4", {}).get("top_typology"),
            },
            "ScamFraudCorrelationAgent": {
                "fraud_typology":         context.get("fraud_typology"),
                "correlation_confidence": context.get("correlation_confidence"),
                "linked_mule_hits":       context.get("linked_mule_hit_count", 0),
            },
            "OutreachSourceOfFundsAgent": {
                "explanation_credibility": context.get("explanation_credibility"),
                "outreach_conducted":      context.get("outreach_conducted"),
            },
            "SARDraftingAgent": {
                "final_disposition": context.get("final_disposition"),
                "sar_required":      context.get("sar_required"),
                "sar_reference":     context.get("sar_reference"),
            },
        }
        return outputs.get(agent_name, {})
