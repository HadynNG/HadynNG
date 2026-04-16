"""
Outreach & Source of Funds Review Agent — Checkpoint 6
- Evaluate whether customer outreach has been or should be conducted
- Assess credibility of source-of-funds explanations
- Determine if Enhanced Due Diligence findings change risk profile
- Produce EDD findings summary for SAR drafting
"""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from .base_agent import BaseAgent
from tools.crm_tool import CRMTool

console = Console()

CREDIBILITY_LEVELS = ("CREDIBLE", "PARTIAL", "IMPLAUSIBLE")


class OutreachSourceOfFundsAgent(BaseAgent):
    name = "OutreachSourceOfFundsAgent"
    step_label = "Checkpoint 6"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.crm = CRMTool()

    # ------------------------------------------------------------------ #
    # CP 6 — Outreach & Source of Funds                                    #
    # ------------------------------------------------------------------ #

    def _cp6(self, context: dict) -> dict:
        self._print_step_header(
            "Outreach & Source of Funds Review",
            "Evaluate source-of-funds explanations and EDD findings.",
        )
        account_id = context.get("account_id")
        account_profile = context.get("account_profile", {})
        account_name = account_profile.get("full_name", account_id)
        mule_type = context.get("mule_type", "UNKNOWN")
        recruitment_likelihood = context.get("recruitment_likelihood", "MEDIUM")
        total_exposure = context.get("total_exposure_hkd", 0.0)
        occupation = account_profile.get("occupation", "Unknown")

        self._print_action(f"Reviewing source-of-funds plausibility for {account_name}")

        # Simulate existing outreach record lookup via CRM
        # In production this queries a CRM case management system
        existing_record = self.crm.check_existing_records(account_id)

        # Construct context-appropriate source-of-funds explanation
        # For unwitting mules: "I was told it was a work-from-home job"
        # For professional mules: no coherent explanation available
        # For unknown/clean: legitimate employment income
        sof_explanations = {
            "PROFESSIONAL": "No credible source-of-funds explanation available. Subject has not responded to outreach attempts.",
            "WITTING": "Subject claims funds are from 'business dealings' but cannot name the business or provide documentation.",
            "UNWITTING": f"Subject states they were hired as a 'work-from-home financial transfer agent' via social media. Believed the role was legitimate. Occupation recorded as '{occupation}'.",
            "UNKNOWN": f"Source of funds declared as income from '{occupation}'. Explanation partially consistent with transaction volumes.",
        }
        sof_explanation = sof_explanations.get(mule_type, sof_explanations["UNKNOWN"])

        # LLM assessment of source-of-funds credibility
        thinking, response = self._llm_reason(
            system_prompt=(
                "You are an AML compliance officer conducting an Enhanced Due Diligence review. "
                "Assess the credibility of the subject's source-of-funds explanation in light of "
                "the transaction evidence and investigation findings.\n\n"
                "Credibility levels:\n"
                "- CREDIBLE: Explanation fully consistent with occupation, transaction volumes, and counterparties\n"
                "- PARTIAL: Some elements credible but key gaps remain unexplained\n"
                "- IMPLAUSIBLE: Explanation contradicted by evidence or absent\n\n"
                "Respond ONLY in JSON:\n"
                '{"source_of_funds_explanation": "...", '
                '"explanation_credibility": "CREDIBLE|PARTIAL|IMPLAUSIBLE", '
                '"edd_findings": "...", '
                '"outreach_conducted": true/false, '
                '"outreach_notes": "..."}'
            ),
            user_prompt=(
                f"Account: {account_id} — {account_name}\n"
                f"Occupation: {occupation}\n"
                f"Mule type assessed: {mule_type}\n"
                f"Recruitment likelihood: {recruitment_likelihood}\n"
                f"Total exposure HKD: {total_exposure:,.0f}\n"
                f"Layering detected: {context.get('layering_detected', False)}\n"
                f"Fraud typology: {context.get('fraud_typology', 'Unknown')}\n"
                f"Correlation confidence: {context.get('correlation_confidence', 0):.0%}\n"
                f"Source-of-funds stated: {sof_explanation}\n"
                f"Known mule network member: {context.get('known_network_member', False)}\n\n"
                "Assess credibility and summarise EDD findings."
            ),
        )

        parsed = self._extract_json(response)

        # Fallback credibility based on mule type
        fallback_credibility = {
            "PROFESSIONAL": "IMPLAUSIBLE",
            "WITTING": "IMPLAUSIBLE",
            "UNWITTING": "PARTIAL",
            "UNKNOWN": "PARTIAL",
        }
        credibility = parsed.get("explanation_credibility", fallback_credibility.get(mule_type, "PARTIAL"))
        if credibility not in CREDIBILITY_LEVELS:
            credibility = fallback_credibility.get(mule_type, "PARTIAL")

        edd_findings = parsed.get(
            "edd_findings",
            f"EDD findings: {credibility} source-of-funds explanation. "
            f"Mule type {mule_type}. Total exposure HKD {total_exposure:,.0f}.",
        )

        color = "green" if credibility == "CREDIBLE" else "yellow" if credibility == "PARTIAL" else "red"
        console.print(
            Panel(
                f"[bold]Source of funds credibility:[/bold] [{color}]{credibility}[/{color}]\n\n"
                + edd_findings,
                title="[bold]EDD Findings[/bold]",
                border_style=color,
            )
        )

        outreach_conducted = parsed.get("outreach_conducted", mule_type in ("UNWITTING", "UNKNOWN"))
        context["outreach_conducted"] = outreach_conducted
        context["source_of_funds_explanation"] = parsed.get("source_of_funds_explanation", sof_explanation)
        context["explanation_credibility"] = credibility
        context["edd_findings"] = edd_findings
        context["cp6"] = {
            "outreach_conducted": outreach_conducted,
            "explanation_credibility": credibility,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"CP6 complete — SOF credibility: {credibility}")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  OUTREACH & SOURCE OF FUNDS AGENT (CP6)  ━━━[/bold magenta]")
        context = self._cp6(context)
        return context
