"""
Scam/Fraud Intelligence Correlation Agent — Checkpoint 5
- Correlate account against known scam cases and fraud intelligence
- Match to recognised typologies from the fraud intelligence database
- Check linked accounts for confirmed mule activity
- Produce a fraud correlation score and typology classification
"""

from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent
from tools.fraud_intelligence_tool import FraudIntelligenceTool
from tools.screening_tool import SanctionsScreeningTool as ScreeningTool

console = Console()


class ScamFraudCorrelationAgent(BaseAgent):
    name = "ScamFraudCorrelationAgent"
    step_label = "Checkpoint 5"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fraud_intel = FraudIntelligenceTool()
        self.screening = ScreeningTool()

    # ------------------------------------------------------------------ #
    # CP 5 — Scam / Fraud Intelligence Correlation                         #
    # ------------------------------------------------------------------ #

    def _cp5(self, context: dict) -> dict:
        self._print_step_header(
            "Scam/Fraud Intelligence Correlation",
            "Cross-reference account and network against known scam cases and fraud databases.",
        )
        account_id = context.get("account_id")
        account_profile = context.get("account_profile", {})
        account_name = account_profile.get("full_name", account_id)
        linked_ids = context.get("linked_accounts", [])

        # Check primary account
        self._print_action(f"Checking {account_id} against known mule register")
        mule_info = self.fraud_intel.check_account(account_id)
        self._print_action(f"Checking {account_id} for adverse intelligence records")
        intel = self.fraud_intel.get_adverse_intelligence(account_id)

        # Check all linked accounts
        self._print_action(f"Checking {len(linked_ids)} linked account(s) for known activity")
        linked_mule_hits = []
        for lid in linked_ids:
            lm = self.fraud_intel.check_account(lid)
            if lm.get("known_mule"):
                linked_mule_hits.append(lm)
            li = self.fraud_intel.get_adverse_intelligence(lid)
            if li.get("has_high_severity"):
                intel["records"].extend(li["records"])

        # Screen account name for adverse media
        self._print_action(f"Screening name '{account_name}' for adverse media")
        adverse = self.screening.search_adverse_media(account_name)

        # Consolidate indicators
        all_indicators = context.get("recruitment_indicators", []).copy()
        if mule_info.get("known_mule"):
            all_indicators.append(f"confirmed mule: {mule_info.get('mule_type', '')}")
        if intel.get("has_high_severity"):
            all_indicators.append("high-severity adverse intelligence")
        if linked_mule_hits:
            all_indicators.append(f"linked to {len(linked_mule_hits)} confirmed mule account(s)")

        # Typology matching
        self._print_action("Matching to known scam typologies")
        typology_result = self.fraud_intel.match_typology(all_indicators)

        # Compute correlation confidence
        base_score = 0.0
        if mule_info.get("known_mule"):
            base_score += 0.4
        if intel.get("has_high_severity"):
            base_score += 0.25
        if linked_mule_hits:
            base_score += min(0.2 * len(linked_mule_hits), 0.2)
        if typology_result.get("typology_matched"):
            base_score += typology_result["top_typology"].get("confidence", 0) * 0.15
        correlation_confidence = round(min(base_score, 1.0), 3)

        # Determine primary typology
        top_typo = typology_result.get("top_typology", {})
        fraud_typology = (
            top_typo.get("name", "Unknown")
            if top_typo else "No typology match"
        )

        # Build summary table
        table = Table(title="Fraud Correlation Summary", show_header=True, header_style="bold red")
        table.add_column("Check", style="dim", width=30)
        table.add_column("Result")
        table.add_row("Known mule register", str(mule_info.get("known_mule", False)))
        table.add_row("Mule type (register)", str(mule_info.get("mule_type", "N/A")))
        table.add_row("Adverse intel records", str(intel.get("intel_count", 0)))
        table.add_row("High-severity intel", str(intel.get("has_high_severity", False)))
        table.add_row("Linked mule accounts", str(len(linked_mule_hits)))
        table.add_row("Typology match", fraud_typology)
        table.add_row("Correlation confidence", f"{correlation_confidence:.0%}")
        table.add_row("Adverse media hits", str(len(adverse)))
        console.print(table)

        # Resolve correlated cases
        correlated_cases = []
        for rec in intel["records"]:
            correlated_cases.append({
                "case_ref": rec.get("intel_id"),
                "type": rec.get("intel_type"),
                "description": rec.get("description"),
                "severity": rec.get("severity"),
                "source": rec.get("source"),
            })

        fraud_narrative = (
            f"Account {account_id} correlated to typology '{fraud_typology}' "
            f"with {correlation_confidence:.0%} confidence. "
            f"Intel records: {intel.get('intel_count', 0)}. "
            f"Linked confirmed mule accounts: {len(linked_mule_hits)}."
        )

        context["correlated_cases"] = correlated_cases
        context["fraud_typology"] = fraud_typology
        context["correlation_confidence"] = correlation_confidence
        context["fraud_narrative"] = fraud_narrative
        context["linked_mule_hit_count"] = len(linked_mule_hits)
        context["adverse_media_mule"] = adverse
        context["cp5"] = {
            "known_mule_register": mule_info.get("known_mule", False),
            "adverse_intel_count": intel.get("intel_count", 0),
            "linked_mule_hits": len(linked_mule_hits),
            "fraud_typology": fraud_typology,
            "correlation_confidence": correlation_confidence,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(
            context,
            f"CP5 complete — typology: {fraud_typology}, confidence: {correlation_confidence:.0%}",
        )
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  SCAM/FRAUD CORRELATION AGENT (CP5)  ━━━[/bold magenta]")
        context = self._cp5(context)
        return context
