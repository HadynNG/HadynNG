"""
Alert Review Agent — Steps 4.1, 4.2, 4.3
- Triage and prioritise alerts
- Investigate matches using LLM reasoning
- Perform EDD for high-risk / PEPs
"""
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent

console = Console()

# Thresholds for auto-dismissal vs escalation
AUTO_DISMISS_THRESHOLD = 0.55
AUTO_ESCALATE_THRESHOLD = 0.85


class AlertReviewAgent(BaseAgent):
    name = "AlertReviewAgent"
    step_label = "Phase 4"

    # ------------------------------------------------------------------ #
    # Step 4.1 — Triage Alerts                                             #
    # ------------------------------------------------------------------ #

    def _step_4_1(self, context: dict) -> dict:
        self._print_step_header(
            "Triage Alerts",
            "Sort by confidence, auto-dismiss obvious false positives.",
        )
        hits = context["screening_results"]["hits"]

        if not hits:
            console.print("  [green]No alerts to triage — screening was clear.[/green]")
            context["triaged_alerts"] = []
            context["step_4_1"] = {"result": "NO_HITS", "timestamp": datetime.utcnow().isoformat() + "Z"}
            self._log(context, "Step 4.1 — no alerts to triage")
            return context

        triaged = []
        dismissed = []

        for hit in hits:
            conf = hit["overall_confidence"]
            # Auto-dismiss if low confidence AND no additional identifiers matched
            if conf < AUTO_DISMISS_THRESHOLD and not hit["identifiers_matched"]:
                dismissed.append({**hit, "triage_result": "AUTO_DISMISSED", "dismiss_reason": "Low confidence, no identifier match"})
            else:
                priority = "HIGH" if conf >= AUTO_ESCALATE_THRESHOLD else "MEDIUM" if conf >= 0.65 else "LOW"
                triaged.append({**hit, "priority": priority})

        if dismissed:
            console.print(f"\n  [dim]Auto-dismissed {len(dismissed)} low-confidence alert(s):[/dim]")
            for d in dismissed:
                console.print(f"    [dim]• {d['matched_name']} ({d['list']}) — {d['dismiss_reason']}[/dim]")

        if triaged:
            table = Table(title="Triaged Alert Queue", show_header=True, header_style="bold yellow")
            table.add_column("Priority", width=8)
            table.add_column("Type", width=12)
            table.add_column("Matched Name", width=25)
            table.add_column("List", width=20)
            table.add_column("Confidence", justify="right", width=12)
            for t in triaged:
                p = t["priority"]
                color = "red" if p == "HIGH" else "yellow" if p == "MEDIUM" else "white"
                table.add_row(
                    f"[{color}]{p}[/{color}]",
                    t["match_type"],
                    t["matched_name"],
                    t["list"],
                    f"{t['overall_confidence']:.0%}",
                )
            console.print(table)
        else:
            console.print("  [green]All alerts auto-dismissed as false positives.[/green]")

        context["triaged_alerts"] = triaged
        context["dismissed_alerts"] = dismissed
        context["step_4_1"] = {
            "triaged_count": len(triaged),
            "dismissed_count": len(dismissed),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 4.1 — {len(triaged)} alerts triaged, {len(dismissed)} dismissed")
        return context

    # ------------------------------------------------------------------ #
    # Step 4.2 — Investigate Matches                                       #
    # ------------------------------------------------------------------ #

    def _step_4_2(self, context: dict) -> dict:
        self._print_step_header(
            "Investigate Matches",
            "LLM-driven investigation to classify each alert as true/false positive.",
        )
        triaged = context.get("triaged_alerts", [])
        customer = context["customer_data"]
        adverse = context.get("adverse_media", [])

        if not triaged:
            console.print("  [green]No triaged alerts — skipping investigation.[/green]")
            context["investigation_results"] = []
            context["step_4_2"] = {"result": "SKIPPED", "timestamp": datetime.utcnow().isoformat() + "Z"}
            self._log(context, "Step 4.2 skipped — no alerts to investigate")
            return context

        investigations = []

        for alert in triaged:
            console.print(
                f"\n  [bold]Investigating alert:[/bold] {alert['matched_name']} "
                f"([{alert['list']}], confidence: {alert['overall_confidence']:.0%})"
            )

            entry = alert.get("entry_details", {})
            adverse_for_customer = [a for a in adverse if customer["full_name"].split()[0] in a["subject"]]

            thinking, response = self._llm_reason(
                system_prompt=(
                    "You are a senior KYC compliance investigator. "
                    "You must determine whether a screening alert is a TRUE POSITIVE or FALSE POSITIVE. "
                    "Analyse all available evidence systematically:\n"
                    "1. Compare names, dates of birth, nationalities, and other identifiers\n"
                    "2. Assess the plausibility of the match given the context\n"
                    "3. Consider adverse media and known risk factors\n"
                    "4. Make a clear determination with supporting evidence\n\n"
                    "Respond in this JSON format:\n"
                    '{"classification": "TRUE_POSITIVE" or "FALSE_POSITIVE", '
                    '"confidence": 0.0-1.0, '
                    '"evidence_for": ["..."], '
                    '"evidence_against": ["..."], '
                    '"reasoning": "...", '
                    '"recommended_action": "..."}'
                ),
                user_prompt=(
                    f"CUSTOMER UNDER REVIEW:\n"
                    f"Name: {customer['full_name']}\n"
                    f"DOB: {customer['date_of_birth']}\n"
                    f"Nationality: {customer['nationality']}\n"
                    f"Occupation: {customer.get('occupation', 'N/A')}\n"
                    f"Jurisdiction: {customer['jurisdiction']}\n\n"
                    f"SCREENING ALERT:\n"
                    f"List: {alert['list']}\n"
                    f"Matched Name: {alert['matched_name']}\n"
                    f"Match Type: {alert['match_type']}\n"
                    f"Identifiers Matched: {alert['identifiers_matched']}\n"
                    f"Name Similarity: {alert['name_similarity']:.0%}\n"
                    f"Overall Confidence: {alert['overall_confidence']:.0%}\n"
                    f"Entry Details: {entry}\n\n"
                    f"ADVERSE MEDIA:\n"
                    + (
                        "\n".join(f"- [{a['source']}] {a['headline']}" for a in adverse_for_customer)
                        if adverse_for_customer
                        else "None found"
                    )
                    + "\n\nClassify this alert."
                ),
            )

            parsed = self._extract_json(response)
            classification = parsed.get("classification", "REQUIRES_REVIEW")
            inv_confidence = parsed.get("confidence", 0.5)

            color = "red" if classification == "TRUE_POSITIVE" else "green"
            console.print(
                f"\n  [bold {color}]→ Classification: {classification}[/bold {color}] "
                f"(confidence: {inv_confidence:.0%})"
            )

            investigations.append({
                "alert": alert,
                "classification": classification,
                "confidence": inv_confidence,
                "parsed": parsed,
                "raw_reasoning": response,
            })

        context["investigation_results"] = investigations
        context["step_4_2"] = {
            "investigations": len(investigations),
            "true_positives": sum(1 for i in investigations if i["classification"] == "TRUE_POSITIVE"),
            "false_positives": sum(1 for i in investigations if i["classification"] == "FALSE_POSITIVE"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(
            context,
            f"Step 4.2 — {context['step_4_2']['true_positives']} TP, "
            f"{context['step_4_2']['false_positives']} FP",
        )
        return context

    # ------------------------------------------------------------------ #
    # Step 4.3 — Enhanced Due Diligence                                    #
    # ------------------------------------------------------------------ #

    def _step_4_3(self, context: dict) -> dict:
        self._print_step_header(
            "Enhanced Due Diligence (EDD)",
            "Deeper checks for high-risk customers and PEPs.",
        )
        risk_level = context["risk_level"]
        customer = context["customer_data"]

        requires_edd = (
            risk_level == "HIGH"
            or customer.get("pep_self_declared")
            or any(
                i["classification"] == "TRUE_POSITIVE"
                for i in context.get("investigation_results", [])
            )
        )

        if not requires_edd:
            console.print("  [green]EDD not required for this customer.[/green]")
            context["edd_required"] = False
            context["step_4_3"] = {"required": False, "timestamp": datetime.utcnow().isoformat() + "Z"}
            self._log(context, "Step 4.3 — EDD not required")
            return context

        console.print("  [bold red]EDD required.[/bold red]")

        thinking, edd_report = self._llm_reason(
            system_prompt=(
                "You are a senior compliance officer preparing an Enhanced Due Diligence (EDD) report "
                "in accordance with HKMA and AMLO requirements.\n"
                "The EDD report must cover:\n"
                "1. Source of wealth/funds assessment\n"
                "2. Business relationship justification\n"
                "3. Senior management approval requirement\n"
                "4. Additional document checklist\n"
                "5. Ongoing monitoring requirements\n\n"
                "Be specific to the customer's profile and identified risks. "
                "Format as a structured report under 200 words."
            ),
            user_prompt=(
                f"Prepare an EDD report for:\n"
                f"Customer: {customer['full_name']}\n"
                f"Nationality: {customer['nationality']}\n"
                f"Occupation: {customer.get('occupation', 'N/A')}\n"
                f"Risk Level: {risk_level}\n"
                f"PEP: {customer.get('pep_self_declared', False)}\n"
                f"Risk Factors: {context.get('risk_factors', [])}\n"
                f"Investigation Results: {[i['classification'] for i in context.get('investigation_results', [])]}\n"
                f"Adverse Media: {[a['headline'] for a in context.get('adverse_media', [])]}"
            ),
        )

        context["edd_required"] = True
        context["edd_report"] = edd_report
        context["step_4_3"] = {
            "required": True,
            "report_generated": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, "Step 4.3 — EDD report generated")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print(
            f"\n[bold magenta]━━━  ALERT REVIEW AGENT  ━━━[/bold magenta]"
        )
        context = self._step_4_1(context)
        context = self._step_4_2(context)
        context = self._step_4_3(context)
        return context
