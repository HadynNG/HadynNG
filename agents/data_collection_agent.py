"""
Data Collection Agent — Steps 1.1, 1.2, 1.3
- Receive trigger event
- Collect customer details from CRM
- Verify identity against registries
"""
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent
from tools.crm_tool import CRMTool
from tools.identity_tool import IdentityVerificationTool

console = Console()

# Supported event types
EVENT_TYPES = {"onboarding", "periodic_review", "transaction_alert", "customer_update"}


class DataCollectionAgent(BaseAgent):
    name = "DataCollectionAgent"
    step_label = "Phase 1"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.crm = CRMTool()
        self.identity = IdentityVerificationTool()

    # ------------------------------------------------------------------ #
    # Step 1.1 — Receive and Classify Trigger Event                        #
    # ------------------------------------------------------------------ #

    def _step_1_1(self, context: dict) -> dict:
        self._print_step_header(
            "Receive & Classify Trigger Event",
            "Detect event type and validate initiation data.",
        )
        event = context.get("event", {})

        self._print_action("Reading incoming event payload")

        thinking, response = self._llm_reason(
            system_prompt=(
                "You are an AI agent in a KYC compliance platform. "
                "Your task is to classify the incoming event and determine if the data is sufficient "
                "to proceed or needs escalation. Be concise and structured.\n"
                "Respond in this JSON format:\n"
                '{"event_type": "...", "is_complete": true/false, '
                '"missing_fields": [], "reasoning": "...", "proceed": true/false}'
            ),
            user_prompt=(
                f"Classify this event and check completeness:\n{event}\n\n"
                f"Valid event types: {list(EVENT_TYPES)}"
            ),
        )

        parsed = self._extract_json(response)
        event_type = parsed.get("event_type", event.get("event_type", "onboarding"))
        proceed = parsed.get("proceed", True)

        self._print_action(
            f"Event classified as: [bold]{event_type}[/bold]",
            f"Proceed={proceed} | Missing fields: {parsed.get('missing_fields', [])}",
        )

        if not proceed:
            self._print_decision("ESCALATE — incomplete event data", color="red")
            context["status"] = "ESCALATED_MISSING_DATA"
            self._log(context, "Escalated at Step 1.1 — incomplete event data", "WARN")
            return context

        context["event_type"] = event_type
        context["step_1_1"] = {
            "classification": parsed,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 1.1 complete — event type: {event_type}")
        return context

    # ------------------------------------------------------------------ #
    # Step 1.2 — Collect Customer Details                                  #
    # ------------------------------------------------------------------ #

    def _step_1_2(self, context: dict) -> dict:
        self._print_step_header(
            "Collect Customer Details",
            "Retrieve full customer profile from CRM and flag high-risk indicators.",
        )
        customer_id = context.get("customer_id")

        self._print_action(f"Querying CRM for customer_id={customer_id}")
        customer = self.crm.get_customer(customer_id)

        if not customer.get("found"):
            self._print_decision(f"Customer {customer_id} not found in CRM", color="red")
            context["status"] = "ESCALATED_CUSTOMER_NOT_FOUND"
            self._log(context, "Customer not found in CRM at Step 1.2", "ERROR")
            return context

        self._print_action("Customer record retrieved", f"Name: {customer['full_name']}")

        # Jurisdiction risk lookup
        jur = self.crm.get_jurisdiction_risk(customer["jurisdiction"])
        self._print_action(
            f"Jurisdiction check for [{customer['jurisdiction']}]",
            f"Risk: {jur['risk_level']} — {jur['reason']}",
        )

        # Build structured output table
        table = Table(title="Customer Profile", show_header=True, header_style="bold cyan")
        table.add_column("Field", style="dim", width=25)
        table.add_column("Value")
        for k, v in customer.items():
            if k not in ("found", "retrieved_at"):
                table.add_row(str(k), str(v))
        console.print(table)

        context["customer_data"] = customer
        context["jurisdiction_risk"] = jur
        context["step_1_2"] = {
            "customer_retrieved": True,
            "jurisdiction_risk_level": jur["risk_level"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 1.2 complete — customer data collected for {customer['full_name']}")
        return context

    # ------------------------------------------------------------------ #
    # Step 1.3 — Verify Identity                                           #
    # ------------------------------------------------------------------ #

    def _step_1_3(self, context: dict) -> dict:
        self._print_step_header(
            "Verify Identity",
            "Cross-verify customer identity against government registries.",
        )
        customer = context["customer_data"]

        self._print_action(
            f"Calling identity verification API for {customer['id_type']} {customer['id_number']}"
        )
        result = self.identity.verify_identity(
            customer["id_number"],
            customer["full_name"],
            customer["date_of_birth"],
        )

        status = result["status"]
        confidence = result.get("verification_confidence", 0)
        color = "green" if status == "VERIFIED" else "red"

        console.print(
            f"\n  [bold {color}]Identity verification: {status}[/bold {color}] "
            f"(confidence: {confidence:.0%})"
        )
        if result.get("notes"):
            console.print(f"  [yellow]  Note: {result['notes']}[/yellow]")

        if status != "VERIFIED":
            self._print_decision("ESCALATE — identity verification failed → EDD path", color="red")
            context["status"] = "ESCALATED_IDENTITY_FAIL"
            self._log(context, "Identity verification failed at Step 1.3", "WARN")
        else:
            self._print_decision("Identity VERIFIED — proceed to Risk Assessment", color="green")

        context["identity_verification"] = result
        context["step_1_3"] = {
            "verification_status": status,
            "confidence": confidence,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 1.3 complete — verification status: {status}")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print(
            f"\n[bold magenta]━━━  DATA COLLECTION AGENT  ━━━[/bold magenta]"
        )
        context = self._step_1_1(context)
        if context.get("status", "").startswith("ESCALATED"):
            return context
        context = self._step_1_2(context)
        if context.get("status", "").startswith("ESCALATED"):
            return context
        context = self._step_1_3(context)
        return context
