"""
Decision Agent — Steps 5.1, 5.2, 5.3
- Classify outcome and make final decision
- Escalate to human (Compliance Officer / MLRO)
- Prepare STR if suspicious activity suspected
"""
from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from .base_agent import BaseAgent

console = Console()


class DecisionAgent(BaseAgent):
    name = "DecisionAgent"
    step_label = "Phase 5"

    # ------------------------------------------------------------------ #
    # Step 5.1 — Classify and Decide                                       #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Rule-based decision fallback (used when LLM output cannot be parsed) #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rule_based_decision(context: dict) -> tuple[str, bool]:
        """
        Returns (decision, requires_str) based on hard rules.
        Used as primary anchor when LLM JSON is unparseable.
        """
        risk_level = context.get("risk_level", "LOW")
        investigations = context.get("investigation_results", [])
        true_positives = [i for i in investigations if i["classification"] == "TRUE_POSITIVE"]
        customer = context.get("customer_data", {})
        is_pep = customer.get("pep_self_declared", False)
        total_hits = context.get("screening_results", {}).get("total_hits", 0)
        adverse_count = len(context.get("adverse_media", []))

        if true_positives and risk_level == "HIGH":
            return "REJECT", True
        if true_positives:
            return "ESCALATE_TO_MLRO", False
        if total_hits == 0 and risk_level == "LOW" and not is_pep:
            return "APPROVE", False
        if total_hits == 0 and risk_level == "MEDIUM" and not is_pep:
            return "APPROVE_WITH_CONDITIONS", False
        if is_pep or risk_level == "HIGH" or adverse_count > 0:
            return "ESCALATE_TO_MLRO", False
        return "APPROVE_WITH_CONDITIONS", False

    # ------------------------------------------------------------------ #

    def _step_5_1(self, context: dict) -> dict:
        self._print_step_header(
            "Classify & Decide",
            "Make final compliance decision based on all gathered evidence.",
        )
        investigations = context.get("investigation_results", [])
        risk_level = context["risk_level"]
        customer = context["customer_data"]
        edd_required = context.get("edd_required", False)

        true_positives = [i for i in investigations if i["classification"] == "TRUE_POSITIVE"]
        false_positives = [i for i in investigations if i["classification"] == "FALSE_POSITIVE"]
        no_hits = not investigations and not context["screening_results"]["hits"]

        # Compute rule-based anchor first
        rule_decision, rule_requires_str = self._rule_based_decision(context)

        thinking, response = self._llm_reason(
            system_prompt=(
                "You are a Chief Compliance Officer making the final AML/KYC decision "
                "for a customer under review. You must consider all available evidence and "
                "provide a definitive ruling compliant with HKMA, AMLO, and SFC guidelines.\n\n"
                "Decision criteria (apply strictly):\n"
                "- APPROVE: No sanctions hits, no TRUE_POSITIVE alerts, risk LOW, identity verified.\n"
                "- APPROVE_WITH_CONDITIONS: No sanctions hits, risk MEDIUM or PEP cleared, "
                "needs enhanced monitoring but no suspicion of ML/TF.\n"
                "- ESCALATE_TO_MLRO: PEP with adverse media, unresolved HIGH risk, "
                "ambiguous alert requiring human judgement.\n"
                "- REJECT: Confirmed TRUE_POSITIVE sanctions match, very high ML/TF suspicion.\n\n"
                "Important: do NOT escalate a cleared low-risk customer. "
                "Use APPROVE for clean, low-risk cases with no hits.\n\n"
                "Respond ONLY in JSON (no commentary outside JSON):\n"
                '{"decision": "APPROVE|APPROVE_WITH_CONDITIONS|ESCALATE_TO_MLRO|REJECT", '
                '"rationale": "...", "requires_str": true/false, '
                '"monitoring_requirements": "...", "confidence": 0.0-1.0}'
            ),
            user_prompt=(
                f"FULL CASE SUMMARY:\n"
                f"Customer: {customer['full_name']} ({customer['nationality']})\n"
                f"Risk Level: {risk_level} (Score: {context['risk_score']})\n"
                f"Identity Verified: {context['identity_verification']['status']}\n"
                f"Screening Hits: {context['screening_results']['total_hits']}\n"
                f"True Positives: {len(true_positives)}\n"
                f"False Positives: {len(false_positives)}\n"
                f"No Hits: {no_hits}\n"
                f"EDD Required: {edd_required}\n"
                f"PEP: {customer.get('pep_self_declared', False)}\n"
                f"Adverse Media Items: {len(context.get('adverse_media', []))}\n"
                f"Risk Narrative: {context.get('risk_narrative', 'N/A')}\n"
                + (
                    f"EDD Report Summary: {context.get('edd_report', 'N/A')[:300]}"
                    if edd_required else ""
                )
                + f"\n\nRule-based recommendation: {rule_decision}"
                + "\n\nMake the final compliance decision."
            ),
        )

        parsed = self._extract_json(response)
        llm_decision = parsed.get("decision", "")

        # Validate LLM decision — fall back to rule-based if invalid or absent
        valid_decisions = {"APPROVE", "APPROVE_WITH_CONDITIONS", "ESCALATE_TO_MLRO", "REJECT"}
        if llm_decision not in valid_decisions:
            parsed["decision"] = rule_decision
            parsed.setdefault("requires_str", rule_requires_str)
            parsed.setdefault("rationale", f"Rule-based decision: {rule_decision}")

        decision = parsed["decision"]
        requires_str = parsed.get("requires_str", False)

        decision_colors = {
            "APPROVE": "green",
            "APPROVE_WITH_CONDITIONS": "yellow",
            "ESCALATE_TO_MLRO": "red",
            "REJECT": "red",
        }
        color = decision_colors.get(decision, "white")

        console.print(
            Panel(
                f"[bold {color}]{decision}[/bold {color}]\n\n"
                + parsed.get("rationale", response)[:400],
                title="[bold]FINAL COMPLIANCE DECISION[/bold]",
                border_style=color,
            )
        )

        if parsed.get("monitoring_requirements"):
            console.print(
                f"  [dim]Monitoring: {parsed['monitoring_requirements']}[/dim]"
            )

        context["final_decision"] = decision
        context["requires_str"] = requires_str
        context["decision_details"] = parsed
        context["step_5_1"] = {
            "decision": decision,
            "requires_str": requires_str,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 5.1 — decision: {decision}, STR required: {requires_str}")
        return context

    # ------------------------------------------------------------------ #
    # Step 5.2 — Escalate to Human (MLRO / Compliance Officer)             #
    # ------------------------------------------------------------------ #

    def _step_5_2(self, context: dict) -> dict:
        decision = context.get("final_decision", "")
        needs_escalation = decision in ("ESCALATE_TO_MLRO", "REJECT")

        if not needs_escalation:
            context["step_5_2"] = {"escalated": False, "timestamp": datetime.utcnow().isoformat() + "Z"}
            return context

        self._print_step_header(
            "Escalate to Human (MLRO/Compliance Officer)",
            "Preparing escalation dossier for human review.",
        )
        customer = context["customer_data"]

        thinking, dossier = self._llm_reason(
            system_prompt=(
                "You are a compliance system preparing a case dossier for the MLRO "
                "(Money Laundering Reporting Officer). Write a concise, professional escalation "
                "notification that summarises the case, reasons for escalation, and next steps required. "
                "Keep it under 200 words."
            ),
            user_prompt=(
                f"Prepare escalation notification for:\n"
                f"Customer: {customer['full_name']} ({customer['nationality']})\n"
                f"Decision: {decision}\n"
                f"Risk Level: {context['risk_level']}\n"
                f"True Positive Alerts: {context['step_4_2'].get('true_positives', 0)}\n"
                f"EDD Required: {context.get('edd_required', False)}\n"
                f"STR Required: {context.get('requires_str', False)}"
            ),
        )

        console.print(
            Panel(
                dossier,
                title="[bold red]MLRO ESCALATION NOTIFICATION[/bold red]",
                border_style="red",
            )
        )
        console.print("  [dim]→ Notification dispatched to MLRO queue (awaiting human decision)[/dim]")

        context["escalation_dossier"] = dossier
        context["step_5_2"] = {
            "escalated": True,
            "notified_role": "MLRO",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, "Step 5.2 — escalated to MLRO")
        return context

    # ------------------------------------------------------------------ #
    # Step 5.3 — File STR                                                  #
    # ------------------------------------------------------------------ #

    def _step_5_3(self, context: dict) -> dict:
        if not context.get("requires_str"):
            context["step_5_3"] = {"str_filed": False, "timestamp": datetime.utcnow().isoformat() + "Z"}
            return context

        self._print_step_header(
            "File Suspicious Transaction Report (STR)",
            "Generate STR template for MLRO submission to JFIU.",
        )
        customer = context["customer_data"]

        thinking, str_template = self._llm_reason(
            system_prompt=(
                "You are a compliance system generating a Suspicious Transaction Report (STR) "
                "template for submission to the JFIU (Joint Financial Intelligence Unit) in Hong Kong. "
                "Follow AMLO reporting requirements. Structure the STR with:\n"
                "1. Reporter details (redacted for demo)\n"
                "2. Subject details\n"
                "3. Nature of suspicion\n"
                "4. Transaction details (if available)\n"
                "5. Supporting evidence summary\n"
                "Keep it professional and factual. Under 250 words."
            ),
            user_prompt=(
                f"Generate STR template for:\n"
                f"Subject: {customer['full_name']}\n"
                f"Nationality: {customer['nationality']}\n"
                f"Occupation: {customer.get('occupation', 'N/A')}\n"
                f"Reason: {context['decision_details'].get('rationale', 'Multiple sanctions hits')}\n"
                f"Adverse Media: {[a['headline'] for a in context.get('adverse_media', [])]}"
            ),
        )

        str_id = f"STR-{datetime.utcnow().strftime('%Y%m%d')}-{customer['customer_id']}"
        console.print(
            Panel(
                str_template,
                title=f"[bold red]STR TEMPLATE — {str_id}[/bold red]",
                border_style="red",
            )
        )
        console.print(f"  [dim]STR ID {str_id} queued for MLRO approval before JFIU submission.[/dim]")

        context["str_id"] = str_id
        context["str_template"] = str_template
        context["step_5_3"] = {
            "str_filed": True,
            "str_id": str_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 5.3 — STR {str_id} generated")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print(
            f"\n[bold magenta]━━━  DECISION AGENT  ━━━[/bold magenta]"
        )
        context = self._step_5_1(context)
        context = self._step_5_2(context)
        context = self._step_5_3(context)
        return context
