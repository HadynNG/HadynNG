"""
Recruitment Pattern Assessment Agent — Checkpoint 4  ★ (Key LLM reasoning step)
- Assess whether the account holder was recruited as a money mule
- Classify mule type: WITTING / UNWITTING / PROFESSIONAL / UNKNOWN
- Match against known recruitment tactics and scam typologies
- Provide recruitment likelihood score
"""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from .base_agent import BaseAgent
from tools.fraud_intelligence_tool import FraudIntelligenceTool
from tools.transaction_tool import TransactionTool

console = Console()

MULE_TYPES = ("WITTING", "UNWITTING", "PROFESSIONAL", "UNKNOWN")


class RecruitmentPatternAgent(BaseAgent):
    name = "RecruitmentPatternAgent"
    step_label = "Checkpoint 4"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fraud_intel = FraudIntelligenceTool()
        self.tx = TransactionTool()

    # ------------------------------------------------------------------ #
    # CP 4 — Recruitment Pattern Assessment                                #
    # ------------------------------------------------------------------ #

    def _cp4(self, context: dict) -> dict:
        self._print_step_header(
            "Recruitment Pattern Assessment",
            "LLM-powered analysis of mule recruitment indicators and mule type classification.",
        )
        account_id = context.get("account_id")
        account_profile = context.get("account_profile", {})

        # Gather indicators from prior checkpoints
        self._print_action("Collecting observable recruitment indicators")
        indicators = []
        if context.get("layering_detected"):
            indicators.append("high pass-through")
        if context.get("structuring_result", {}).get("structuring_detected"):
            indicators.append("structuring")
        if context.get("alert_type") in ("new_account_high_volume", "pass_through"):
            indicators.append("new account high volume")
        if account_profile.get("account_opened"):
            indicators.append("recently opened account")
        if context.get("known_network_member"):
            indicators.append("known mule network member")
        if context.get("network_risk") == "HIGH":
            indicators.append("high-risk network links")
        if any(p.get("flags") for p in context.get("counterparty_data", [])):
            indicators.append("suspicious counterparties")

        self._print_action("Querying fraud intelligence database")
        intel = self.fraud_intel.get_adverse_intelligence(account_id)
        mule_info = self.fraud_intel.check_account(account_id)
        recruitment = self.fraud_intel.get_recruitment_indicators(account_id)

        if intel["records"]:
            for rec in intel["records"]:
                indicators.append(f"adverse intel: {rec.get('intel_type', 'unknown')}")

        self._print_action("Matching typology against observed indicators")
        typo_match = self.fraud_intel.match_typology(indicators)

        # Core LLM reasoning — key reasoning step (★)
        thinking, response = self._llm_reason(
            system_prompt=(
                "You are a senior AML investigator specialising in money mule detection. "
                "Based on all available evidence, determine:\n"
                "1. Mule recruitment likelihood: HIGH / MEDIUM / LOW\n"
                "2. Mule type: WITTING (knowingly participating) / UNWITTING (deceived) / "
                "PROFESSIONAL (active criminal) / UNKNOWN\n"
                "3. Key recruitment indicators that support your assessment\n"
                "4. Recommended next steps\n\n"
                "Mule type guidance:\n"
                "- PROFESSIONAL: multiple accounts, structured splits, crypto conversion, network coordinator links\n"
                "- WITTING: clearly knew account was for illegal use, direct coordination with criminals\n"
                "- UNWITTING: deceived via job scam / romance scam; typical victim profile (young, low income)\n"
                "- UNKNOWN: insufficient evidence\n\n"
                "Respond ONLY in JSON:\n"
                '{"recruitment_likelihood": "HIGH|MEDIUM|LOW", '
                '"mule_type": "WITTING|UNWITTING|PROFESSIONAL|UNKNOWN", '
                '"recruitment_indicators": ["..."], '
                '"recruitment_narrative": "...", '
                '"recommended_next_steps": "..."}'
            ),
            user_prompt=(
                f"Account: {account_id}\n"
                f"Name: {account_profile.get('full_name', 'N/A')}\n"
                f"Occupation: {account_profile.get('occupation', 'N/A')}\n"
                f"Account opened: {account_profile.get('account_opened', 'N/A')}\n"
                f"Existing risk rating: {account_profile.get('existing_risk_rating', 'N/A')}\n"
                f"Alert type: {context.get('alert_type', 'N/A')}\n"
                f"Layering detected: {context.get('layering_detected', False)}\n"
                f"Layering patterns: {context.get('layering_patterns', [])}\n"
                f"Known mule network member: {context.get('known_network_member', False)}\n"
                f"Known networks: {context.get('known_networks', [])}\n"
                f"Adverse intel records: {intel['records']}\n"
                f"Known mule account check: {mule_info}\n"
                f"Recruitment tactics detected: {recruitment['tactics_detected']}\n"
                f"Observable indicators: {indicators}\n"
                f"Top typology match: {typo_match.get('top_typology')}\n\n"
                "Assess the recruitment pattern and classify this mule account."
            ),
        )

        parsed = self._extract_json(response)

        # Fallback: if in known mule register, trust that
        if mule_info.get("known_mule"):
            parsed.setdefault("recruitment_likelihood", "HIGH")
            parsed.setdefault("mule_type", mule_info.get("mule_type", "UNKNOWN"))

        recruitment_likelihood = parsed.get("recruitment_likelihood", "MEDIUM")
        mule_type = parsed.get("mule_type", "UNKNOWN")
        if mule_type not in MULE_TYPES:
            mule_type = "UNKNOWN"

        recruitment_narrative = parsed.get(
            "recruitment_narrative",
            f"Recruitment likelihood: {recruitment_likelihood}. Mule type: {mule_type}.",
        )

        color = "red" if recruitment_likelihood == "HIGH" else "yellow" if recruitment_likelihood == "MEDIUM" else "green"
        console.print(
            Panel(
                f"[bold]Mule type:[/bold] {mule_type}\n"
                f"[bold]Recruitment likelihood:[/bold] {recruitment_likelihood}\n\n"
                + recruitment_narrative,
                title="[bold]Recruitment Pattern Assessment[/bold]",
                border_style=color,
            )
        )

        context["recruitment_likelihood"] = recruitment_likelihood
        context["mule_type"] = mule_type
        context["recruitment_indicators"] = parsed.get("recruitment_indicators", indicators)
        context["recruitment_narrative"] = recruitment_narrative
        context["typology_match"] = typo_match
        context["cp4"] = {
            "recruitment_likelihood": recruitment_likelihood,
            "mule_type": mule_type,
            "typology_matched": typo_match.get("typology_matched", False),
            "top_typology": typo_match.get("top_typology", {}).get("name") if typo_match.get("top_typology") else None,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(
            context,
            f"CP4 complete — mule type: {mule_type}, likelihood: {recruitment_likelihood}",
        )
        # Store insight for future recall
        self._store_insight(
            context,
            f"Mule type {mule_type} detected for {account_profile.get('occupation', 'unknown')} "
            f"via {context.get('alert_type', 'unknown')} alert",
        )
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  RECRUITMENT PATTERN AGENT (CP4 ★)  ━━━[/bold magenta]")
        context = self._cp4(context)
        return context
