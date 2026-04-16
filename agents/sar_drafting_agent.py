"""
SAR Drafting & Analyst Review Agent — Checkpoint 7
- Make final mule investigation disposition
- Draft Suspicious Activity Report (SAR) if warranted
- Prepare analyst review package
- Write audit trail entry
"""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from .base_agent import BaseAgent
from tools.sar_tool import SARTool

console = Console()

# Final disposition options
DISPOSITIONS = (
    "FILE_SAR",           # Strong evidence — file SAR with JFIU
    "ESCALATE_TO_MLRO",   # Significant risk but needs human review first
    "MONITOR",            # Insufficient for SAR but keep enhanced monitoring
    "CLOSE_NO_ACTION",    # False positive — close alert
)


class SARDraftingAgent(BaseAgent):
    name = "SARDraftingAgent"
    step_label = "Checkpoint 7"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sar = SARTool()

    # ------------------------------------------------------------------ #
    # Rule-based disposition anchor                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based_disposition(context: dict) -> str:
        """Deterministic disposition before LLM overlay."""
        mule_type = context.get("mule_type", "UNKNOWN")
        corr_confidence = context.get("correlation_confidence", 0.0)
        credibility = context.get("explanation_credibility", "PARTIAL")
        known_network = context.get("known_network_member", False)
        recruitment_likelihood = context.get("recruitment_likelihood", "LOW")
        total_exposure = context.get("total_exposure_hkd", 0.0)

        # Strong SAR triggers
        if mule_type == "PROFESSIONAL" and corr_confidence >= 0.6:
            return "FILE_SAR"
        if known_network and credibility == "IMPLAUSIBLE":
            return "FILE_SAR"
        if corr_confidence >= 0.7:
            return "FILE_SAR"

        # Escalate triggers
        if recruitment_likelihood == "HIGH" and credibility != "CREDIBLE":
            return "ESCALATE_TO_MLRO"
        if mule_type == "WITTING":
            return "ESCALATE_TO_MLRO"
        if total_exposure >= 500_000 and credibility in ("PARTIAL", "IMPLAUSIBLE"):
            return "ESCALATE_TO_MLRO"

        # Monitor
        if recruitment_likelihood == "MEDIUM":
            return "MONITOR"

        # Close
        return "CLOSE_NO_ACTION"

    # ------------------------------------------------------------------ #
    # CP 7 — SAR Drafting & Analyst Review                                 #
    # ------------------------------------------------------------------ #

    def _cp7(self, context: dict) -> dict:
        self._print_step_header(
            "SAR Drafting & Analyst Review",
            "Final disposition decision, SAR draft, and analyst review package.",
        )
        account_id = context.get("account_id")
        account_profile = context.get("account_profile", {})
        account_name = account_profile.get("full_name", account_id)
        mule_type = context.get("mule_type", "UNKNOWN")

        rule_disposition = self._rule_based_disposition(context)
        self._print_action(f"Rule-based disposition anchor: [bold]{rule_disposition}[/bold]")

        # LLM final disposition reasoning
        thinking, response = self._llm_reason(
            system_prompt=(
                "You are a senior compliance officer finalising a mule account investigation. "
                "Make the final disposition and draft a concise SAR narrative if warranted.\n\n"
                "Dispositions:\n"
                "- FILE_SAR: File Suspicious Activity Report with JFIU (strong evidence of money laundering)\n"
                "- ESCALATE_TO_MLRO: Refer to MLRO for decision (significant risk, needs human review)\n"
                "- MONITOR: Enhanced monitoring — insufficient evidence for SAR now\n"
                "- CLOSE_NO_ACTION: False positive — close alert\n\n"
                "Respond ONLY in JSON:\n"
                '{"final_disposition": "FILE_SAR|ESCALATE_TO_MLRO|MONITOR|CLOSE_NO_ACTION", '
                '"sar_required": true/false, '
                '"sar_narrative": "...", '
                '"analyst_notes": "...", '
                '"key_findings": ["..."]}'
            ),
            user_prompt=(
                f"Case summary:\n"
                f"Account: {account_id} — {account_name}\n"
                f"Mule type: {mule_type}\n"
                f"Recruitment likelihood: {context.get('recruitment_likelihood', 'N/A')}\n"
                f"Fraud typology: {context.get('fraud_typology', 'N/A')}\n"
                f"Correlation confidence: {context.get('correlation_confidence', 0):.0%}\n"
                f"Total exposure HKD: {context.get('total_exposure_hkd', 0):,.0f}\n"
                f"Layering detected: {context.get('layering_detected', False)}\n"
                f"Known mule network: {context.get('known_network_member', False)}\n"
                f"SOF credibility: {context.get('explanation_credibility', 'N/A')}\n"
                f"Adverse intel count: {context.get('cp5', {}).get('adverse_intel_count', 0)}\n"
                f"EDD findings: {context.get('edd_findings', 'N/A')}\n"
                f"Fund flow summary: {context.get('fund_flow_summary', 'N/A')}\n"
                f"Recruitment narrative: {context.get('recruitment_narrative', 'N/A')}\n"
                f"Rule-based anchor: {rule_disposition}\n\n"
                "Make the final disposition decision and draft the SAR narrative."
            ),
        )

        parsed = self._extract_json(response)

        # Validate disposition
        disposition = parsed.get("final_disposition", rule_disposition)
        if disposition not in DISPOSITIONS:
            disposition = rule_disposition

        sar_required = parsed.get("sar_required", disposition == "FILE_SAR")
        analyst_notes = parsed.get("analyst_notes", f"Final disposition: {disposition}")
        key_findings = parsed.get("key_findings", [
            f"Mule type: {mule_type}",
            f"Typology: {context.get('fraud_typology', 'N/A')}",
            f"Exposure: HKD {context.get('total_exposure_hkd', 0):,.0f}",
        ])

        # Build SAR if required
        sar_data = None
        sar_reference = None
        if sar_required:
            sar_narrative = parsed.get(
                "sar_narrative",
                f"Account {account_id} ({account_name}) identified as a {mule_type} money mule. "
                f"Typology: {context.get('fraud_typology', 'unknown')}. "
                f"Total exposure: HKD {context.get('total_exposure_hkd', 0):,.0f}. "
                f"{context.get('fund_flow_summary', '')}",
            )
            linked_ids = context.get("linked_accounts", [])
            sar_data = self.sar.build_sar_structure(
                account_id=account_id,
                account_name=account_name,
                alert_type=context.get("alert_type", "mule_alert"),
                mule_type=mule_type,
                fraud_typology=context.get("fraud_typology", "Unknown"),
                total_exposure_hkd=context.get("total_exposure_hkd", 0.0),
                linked_accounts=linked_ids,
                key_findings=key_findings,
                analyst_recommendation=analyst_notes,
                sar_narrative=sar_narrative,
            )
            sar_reference = sar_data["sar_reference"]
            self._print_action(f"SAR generated: [bold]{sar_reference}[/bold]")

        # Display final outcome
        disposition_colors = {
            "FILE_SAR":          "red",
            "ESCALATE_TO_MLRO":  "red",
            "MONITOR":           "yellow",
            "CLOSE_NO_ACTION":   "green",
        }
        color = disposition_colors.get(disposition, "white")

        console.print(
            Panel(
                f"[bold {color}]{disposition}[/bold {color}]\n\n"
                + analyst_notes,
                title="[bold]MULE INVESTIGATION — FINAL DISPOSITION[/bold]",
                border_style=color,
            )
        )

        if sar_data:
            checklist = self.sar.get_filing_checklist()
            console.print("\n[dim]Pre-filing checklist:[/dim]")
            for item in checklist[:4]:
                console.print(f"  [dim]  □ {item}[/dim]")
            console.print(f"  [dim]  ... ({len(checklist) - 4} more items)[/dim]")

        context["final_disposition"] = disposition
        context["sar_required"] = sar_required
        context["sar_reference"] = sar_reference
        context["sar_draft"] = sar_data
        context["analyst_notes"] = analyst_notes
        context["mule_key_findings"] = key_findings
        context["cp7"] = {
            "final_disposition": disposition,
            "sar_required": sar_required,
            "sar_reference": sar_reference,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"CP7 complete — disposition: {disposition}, SAR: {sar_reference or 'none'}")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  SAR DRAFTING & ANALYST REVIEW AGENT (CP7)  ━━━[/bold magenta]")
        context = self._cp7(context)
        return context
