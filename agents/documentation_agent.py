"""
Documentation Agent — Steps 6.1, 6.2
- Log all actions to audit trail (retained 5+ years per AMLO)
- Notify stakeholders of outcome
"""
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .base_agent import BaseAgent

console = Console()

AUDIT_LOG_DIR = Path("audit_logs")


class DocumentationAgent(BaseAgent):
    name = "DocumentationAgent"
    step_label = "Phase 6"

    # ------------------------------------------------------------------ #
    # Step 6.1 — Log All Actions                                           #
    # ------------------------------------------------------------------ #

    def _step_6_1(self, context: dict) -> dict:
        self._print_step_header(
            "Log All Actions",
            "Write complete audit trail to persistent storage (AMLO 5-year retention).",
        )

        AUDIT_LOG_DIR.mkdir(exist_ok=True)
        customer_id = context.get("customer_id", "UNKNOWN")
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        log_file = AUDIT_LOG_DIR / f"audit_{customer_id}_{timestamp}.json"

        audit_payload = {
            "audit_id": f"AUD-{customer_id}-{timestamp}",
            "customer_id": customer_id,
            "customer_name": context.get("customer_data", {}).get("full_name", "N/A"),
            "process_started": context.get("audit_log", [{}])[0].get("timestamp", timestamp),
            "process_completed": datetime.utcnow().isoformat() + "Z",
            "final_decision": context.get("final_decision", "N/A"),
            "risk_level": context.get("risk_level", "N/A"),
            "risk_score": context.get("risk_score", 0),
            "screening_hits": context.get("screening_results", {}).get("total_hits", 0),
            "edd_required": context.get("edd_required", False),
            "str_filed": context.get("step_5_3", {}).get("str_filed", False),
            "str_id": context.get("str_id"),
            "step_summary": {
                "step_1_1": context.get("step_1_1"),
                "step_1_2": context.get("step_1_2"),
                "step_1_3": context.get("step_1_3"),
                "step_2_1": context.get("step_2_1"),
                "step_3_1": context.get("step_3_1"),
                "step_3_2": context.get("step_3_2"),
                "step_4_1": context.get("step_4_1"),
                "step_4_2": context.get("step_4_2"),
                "step_4_3": context.get("step_4_3"),
                "step_5_1": context.get("step_5_1"),
                "step_5_2": context.get("step_5_2"),
                "step_5_3": context.get("step_5_3"),
            },
            "action_log": context.get("audit_log", []),
            "retention_policy": "5 years — AMLO Section 20",
        }

        with open(log_file, "w") as f:
            json.dump(audit_payload, f, indent=2, default=str)

        self._print_action(
            f"Audit trail written to [bold]{log_file}[/bold]",
            f"Audit ID: {audit_payload['audit_id']} | "
            f"{len(audit_payload['action_log'])} action entries",
        )

        context["audit_id"] = audit_payload["audit_id"]
        context["audit_log_file"] = str(log_file)
        context["step_6_1"] = {
            "audit_id": audit_payload["audit_id"],
            "log_file": str(log_file),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 6.1 — audit trail saved: {log_file}")
        return context

    # ------------------------------------------------------------------ #
    # Step 6.2 — Notify Stakeholders                                       #
    # ------------------------------------------------------------------ #

    def _step_6_2(self, context: dict) -> dict:
        self._print_step_header(
            "Notify Stakeholders",
            "Generate closure notifications for customer and internal team.",
        )
        decision = context.get("final_decision", "N/A")
        customer = context.get("customer_data", {})

        decision_messages = {
            "APPROVE": (
                f"Dear {customer.get('full_name', 'Customer')},\n\n"
                "Your KYC verification has been successfully completed. Your account has been approved "
                "and is now active. We look forward to serving you.\n\n"
                "Regards,\nCompliance Team"
            ),
            "APPROVE_WITH_CONDITIONS": (
                f"Dear {customer.get('full_name', 'Customer')},\n\n"
                "Your KYC verification is complete. Your account has been approved with enhanced "
                "monitoring. A compliance representative may contact you periodically.\n\n"
                "Regards,\nCompliance Team"
            ),
            "ESCALATE_TO_MLRO": (
                f"Dear {customer.get('full_name', 'Customer')},\n\n"
                "Your KYC application is currently under further review. Our compliance team "
                "will contact you within 2 business days. No action is required from you at this time.\n\n"
                "Regards,\nCompliance Team"
            ),
            "REJECT": (
                f"Dear {customer.get('full_name', 'Customer')},\n\n"
                "We regret to inform you that we are unable to establish a business relationship "
                "at this time. If you believe this is in error, please contact our compliance team.\n\n"
                "Regards,\nCompliance Team"
            ),
        }

        customer_notification = decision_messages.get(
            decision,
            f"Dear {customer.get('full_name', 'Customer')},\n\nYour application is under review.\n\nRegards,\nCompliance Team",
        )

        internal_notification = (
            f"[INTERNAL — KYC CLOSURE NOTICE]\n"
            f"Customer ID : {context.get('customer_id')}\n"
            f"Name        : {customer.get('full_name', 'N/A')}\n"
            f"Decision    : {decision}\n"
            f"Risk Level  : {context.get('risk_level', 'N/A')}\n"
            f"Audit ID    : {context.get('audit_id', 'N/A')}\n"
            f"EDD Required: {context.get('edd_required', False)}\n"
            f"STR Filed   : {context.get('step_5_3', {}).get('str_filed', False)}\n"
            f"Completed   : {datetime.utcnow().isoformat()}Z"
        )

        console.print(
            Panel(customer_notification, title="[bold]Customer Notification (Email)[/bold]", border_style="blue")
        )
        console.print(
            Panel(internal_notification, title="[bold]Internal Team Notification[/bold]", border_style="dim")
        )

        context["customer_notification"] = customer_notification
        context["internal_notification"] = internal_notification
        context["step_6_2"] = {
            "notifications_sent": ["customer_email", "internal_team"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, "Step 6.2 — stakeholder notifications generated")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print(
            f"\n[bold magenta]━━━  DOCUMENTATION AGENT  ━━━[/bold magenta]"
        )
        context = self._step_6_1(context)
        context = self._step_6_2(context)
        return context
