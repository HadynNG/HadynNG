"""
Risk Assessment Agent — Step 2.1
Calculates an initial risk score using rule-based logic +
LLM-reasoned narrative.
"""
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent

console = Console()

# Risk scoring rules
RISK_FACTORS = {
    "HIGH_RISK_JURISDICTION": 30,
    "MEDIUM_RISK_JURISDICTION": 15,
    "PEP_SELF_DECLARED": 25,
    "HIGH_RISK_OCCUPATION": 20,
    "CORPORATE_ENTITY": 10,
    "PREVIOUS_HIGH_RATING": 20,
    "IDENTITY_NOTES_FLAG": 10,
}

HIGH_RISK_OCCUPATIONS = {
    "government official", "politician", "diplomat", "military officer",
    "energy sector executive", "arms dealer", "casino operator",
}


class RiskAssessmentAgent(BaseAgent):
    name = "RiskAssessmentAgent"
    step_label = "Phase 2"

    def _calculate_score(self, context: dict) -> tuple[int, list]:
        customer = context["customer_data"]
        jur_risk = context["jurisdiction_risk"]["risk_level"]
        id_notes = context["identity_verification"].get("notes", "")

        score = 0
        factors_applied = []

        if jur_risk == "HIGH":
            score += RISK_FACTORS["HIGH_RISK_JURISDICTION"]
            factors_applied.append(f"High-risk jurisdiction (+{RISK_FACTORS['HIGH_RISK_JURISDICTION']}pts)")
        elif jur_risk == "MEDIUM":
            score += RISK_FACTORS["MEDIUM_RISK_JURISDICTION"]
            factors_applied.append(f"Medium-risk jurisdiction (+{RISK_FACTORS['MEDIUM_RISK_JURISDICTION']}pts)")

        if customer.get("pep_self_declared"):
            score += RISK_FACTORS["PEP_SELF_DECLARED"]
            factors_applied.append(f"PEP self-declared (+{RISK_FACTORS['PEP_SELF_DECLARED']}pts)")

        occupation = customer.get("occupation", "").lower()
        if any(h in occupation for h in HIGH_RISK_OCCUPATIONS):
            score += RISK_FACTORS["HIGH_RISK_OCCUPATION"]
            factors_applied.append(f"High-risk occupation '{customer['occupation']}' (+{RISK_FACTORS['HIGH_RISK_OCCUPATION']}pts)")

        if customer.get("customer_type") == "corporate":
            score += RISK_FACTORS["CORPORATE_ENTITY"]
            factors_applied.append(f"Corporate entity (+{RISK_FACTORS['CORPORATE_ENTITY']}pts)")

        if customer.get("existing_risk_rating") == "HIGH":
            score += RISK_FACTORS["PREVIOUS_HIGH_RATING"]
            factors_applied.append(f"Previous HIGH risk rating (+{RISK_FACTORS['PREVIOUS_HIGH_RATING']}pts)")

        if id_notes:
            score += RISK_FACTORS["IDENTITY_NOTES_FLAG"]
            factors_applied.append(f"Identity verification notes flagged (+{RISK_FACTORS['IDENTITY_NOTES_FLAG']}pts)")

        return score, factors_applied

    def _score_to_level(self, score: int) -> tuple[str, str]:
        if score >= 50:
            return "HIGH", "red"
        elif score >= 20:
            return "MEDIUM", "yellow"
        return "LOW", "green"

    def run(self, context: dict) -> dict:
        console.print(
            f"\n[bold magenta]━━━  RISK ASSESSMENT AGENT  ━━━[/bold magenta]"
        )
        self._print_step_header(
            "Calculate Initial Risk Score",
            "Apply rule-based scoring model + LLM risk narrative.",
        )

        score, factors = self._calculate_score(context)
        risk_level, color = self._score_to_level(score)

        # Display scoring table
        table = Table(title="Risk Scoring Breakdown", show_header=True, header_style="bold magenta")
        table.add_column("Factor", style="dim")
        table.add_column("Points", justify="right")
        for f in factors:
            parts = f.rsplit("(", 1)
            pts = parts[1].rstrip(")") if len(parts) == 2 else ""
            table.add_row(parts[0].strip(), pts)
        table.add_row("[bold]TOTAL SCORE[/bold]", f"[bold]{score}[/bold]")
        console.print(table)

        # LLM reasoning for risk narrative
        customer = context["customer_data"]
        thinking, response = self._llm_reason(
            system_prompt=(
                "You are a KYC compliance risk analyst. Given the customer's profile and scoring factors, "
                "provide a concise risk assessment narrative. Highlight key concerns and recommend next steps. "
                "Keep your response under 150 words. Be professional and factual."
            ),
            user_prompt=(
                f"Customer: {customer['full_name']} ({customer['nationality']})\n"
                f"Occupation: {customer.get('occupation', 'N/A')}\n"
                f"Jurisdiction risk: {context['jurisdiction_risk']['risk_level']}\n"
                f"Risk score: {score} / 100+\n"
                f"Risk level: {risk_level}\n"
                f"Factors applied: {factors}\n\n"
                "Write a brief risk assessment narrative and recommend next steps."
            ),
        )

        self._print_decision(
            f"Risk Level: {risk_level}  (Score: {score})",
            color=color,
        )
        if risk_level == "HIGH":
            console.print("  [bold red]→ Proceed to Enhanced Due Diligence (EDD)[/bold red]")
        elif risk_level == "MEDIUM":
            console.print("  [bold yellow]→ Standard screening with heightened attention[/bold yellow]")
        else:
            console.print("  [bold green]→ Basic screening[/bold green]")

        context["risk_score"] = score
        context["risk_level"] = risk_level
        context["risk_factors"] = factors
        context["risk_narrative"] = response
        context["step_2_1"] = {
            "score": score,
            "level": risk_level,
            "factors": factors,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 2.1 complete — risk level: {risk_level}, score: {score}")
        return context
