"""
Fund Flow & Layering Analysis Agent — Checkpoint 3
- Analyse transaction patterns across primary + linked accounts
- Detect structuring, rapid pass-through, and layering patterns
- Estimate total financial exposure
"""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from .base_agent import BaseAgent
from tools.transaction_tool import TransactionTool

console = Console()

# Passthrough ratio threshold — above this level is considered layering
_PASSTHROUGH_THRESHOLD = 0.90


class FundFlowLayeringAgent(BaseAgent):
    name = "FundFlowLayeringAgent"
    step_label = "Checkpoint 3"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tx = TransactionTool()

    # ------------------------------------------------------------------ #
    # CP 3 — Fund Flow & Layering Analysis                                 #
    # ------------------------------------------------------------------ #

    def _cp3(self, context: dict) -> dict:
        self._print_step_header(
            "Fund Flow & Layering Analysis",
            "Examine transaction patterns for structuring, pass-through, and layering.",
        )
        account_id = context.get("account_id")
        linked_ids = context.get("linked_accounts", [])
        all_ids = [account_id] + linked_ids

        self._print_action(f"Analysing fund flow across {len(all_ids)} account(s)")
        flow = self.tx.get_fund_flow_summary(all_ids)

        self._print_action("Checking for structuring patterns")
        structuring = self.tx.detect_structuring(account_id)

        self._print_action("Computing transaction velocity")
        velocity = context.get("alert_velocity") or self.tx.get_velocity(account_id)

        self._print_action("Retrieving top counterparties")
        counterparties = self.tx.get_counterparties(account_id)

        # Determine layering indicators
        layering_patterns = []
        if velocity.get("high_passthrough"):
            layering_patterns.append(
                f"High pass-through ratio ({velocity.get('passthrough_ratio', 0):.0%}) — "
                "credits almost entirely forwarded"
            )
        if velocity.get("same_day_credit_debit_days", 0) >= 3:
            layering_patterns.append(
                f"Same-day credit→debit on {velocity['same_day_credit_debit_days']} days — "
                "funds not retained"
            )
        if structuring.get("structuring_detected"):
            layering_patterns.append(
                f"Structuring detected — {structuring['suspected_structured_count']} "
                "transactions just below HKD 50,000 threshold"
            )
        if len(flow.get("external_fund_destinations", [])) >= 3:
            layering_patterns.append(
                f"Funds dispersed to {len(flow['external_fund_destinations'])} distinct "
                "external destinations — dispersion pattern"
            )
        if flow.get("suspicious_tx_count", 0) >= 5:
            layering_patterns.append(
                f"{flow['suspicious_tx_count']} transactions flagged as suspicious"
            )

        layering_detected = len(layering_patterns) >= 2

        # LLM interpretation of patterns
        thinking, response = self._llm_reason(
            system_prompt=(
                "You are an AML analyst specialising in financial crime. "
                "Given transaction analysis data, write a concise fund flow and layering summary. "
                "Focus on: (1) how funds enter the account, (2) how funds are moved out, "
                "(3) whether layering is evident, (4) estimated exposure and money laundering risk. "
                "Keep it under 150 words. End with a one-line layering verdict."
            ),
            user_prompt=(
                f"Account: {account_id}\n"
                f"Total credit (HKD): {flow['total_credit_hkd']:,.0f}\n"
                f"Total debit (HKD): {flow['total_debit_hkd']:,.0f}\n"
                f"Passthrough ratio: {velocity.get('passthrough_ratio', 0):.0%}\n"
                f"Same-day credit/debit days: {velocity.get('same_day_credit_debit_days', 0)}\n"
                f"Structuring detected: {structuring.get('structuring_detected', False)}\n"
                f"External sources: {flow.get('external_fund_sources', [])}\n"
                f"External destinations: {flow.get('external_fund_destinations', [])}\n"
                f"Suspicious tx count: {flow.get('suspicious_tx_count', 0)}\n"
                f"Layering patterns identified: {layering_patterns}\n"
                "Write the fund flow and layering analysis."
            ),
        )

        fund_flow_summary = response if response and "[LLM unavailable" not in response else (
            f"Total exposure: HKD {flow['total_credit_hkd']:,.0f}. "
            f"Pass-through ratio: {velocity.get('passthrough_ratio', 0):.0%}. "
            f"Layering detected: {layering_detected}."
        )

        console.print(
            Panel(
                fund_flow_summary,
                title=f"[bold cyan]Fund Flow Summary — {account_id}[/bold cyan]",
                border_style="cyan",
            )
        )

        context["fund_flow_summary"] = fund_flow_summary
        context["layering_detected"] = layering_detected
        context["layering_patterns"] = layering_patterns
        context["total_exposure_hkd"] = flow.get("total_credit_hkd", 0.0)
        context["suspicious_tx_count"] = flow.get("suspicious_tx_count", 0)
        context["counterparty_data"] = counterparties.get("counterparties", [])
        context["structuring_result"] = structuring
        context["cp3"] = {
            "layering_detected": layering_detected,
            "layering_pattern_count": len(layering_patterns),
            "total_exposure_hkd": flow.get("total_credit_hkd", 0.0),
            "structuring_detected": structuring.get("structuring_detected", False),
            "passthrough_ratio": velocity.get("passthrough_ratio", 0),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(
            context,
            f"CP3 complete — layering: {layering_detected}, exposure HKD {flow.get('total_credit_hkd', 0):,.0f}",
        )
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  FUND FLOW & LAYERING AGENT (CP3)  ━━━[/bold magenta]")
        context = self._cp3(context)
        return context
