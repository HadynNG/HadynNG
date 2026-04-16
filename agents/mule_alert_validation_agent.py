"""
Mule Alert Validation Agent — Checkpoint 1
- Receive and validate a mule account alert
- Classify alert type and priority
- Retrieve account profile from CRM
- Determine whether alert warrants investigation
"""

from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent
from tools.crm_tool import CRMTool
from tools.transaction_tool import TransactionTool

console = Console()

ALERT_TYPES = {
    "transaction_velocity",   # Unusually high number or volume of transactions
    "pass_through",           # Credits immediately followed by debits
    "unusual_counterparty",   # Transfers to/from unknown or high-risk parties
    "structuring",            # Transactions just below reporting threshold
    "new_account_high_volume",# New account with immediate high-volume activity
    "network_flag",           # Flagged due to link to known mule network
    "victim_complaint",       # Victim complaint identifies account as recipient
    "police_referral",        # Referral from law enforcement
}


class MuleAlertValidationAgent(BaseAgent):
    name = "MuleAlertValidationAgent"
    step_label = "Checkpoint 1"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.crm = CRMTool()
        self.tx = TransactionTool()

    # ------------------------------------------------------------------ #
    # CP 1.1 — Validate Alert                                              #
    # ------------------------------------------------------------------ #

    def _cp1_1(self, context: dict) -> dict:
        self._print_step_header(
            "Mule Alert Validation",
            "Verify alert metadata, classify type, and confirm investigation threshold.",
        )
        alert = context.get("alert", {})
        self._print_action("Validating incoming mule alert payload")

        thinking, response = self._llm_reason(
            system_prompt=(
                "You are an AML analyst validating a mule account alert. "
                "Your task is to:\n"
                "1. Confirm the alert type is a known mule indicator.\n"
                "2. Assign an investigation priority (HIGH / MEDIUM / LOW).\n"
                "3. Write a brief alert narrative explaining why this warrants investigation.\n\n"
                f"Known mule alert types: {sorted(ALERT_TYPES)}\n\n"
                "Respond ONLY in JSON:\n"
                '{"alert_type_valid": true/false, "normalised_alert_type": "...", '
                '"priority": "HIGH|MEDIUM|LOW", "alert_narrative": "...", '
                '"proceed": true/false}'
            ),
            user_prompt=(
                f"Mule alert payload:\n{alert}\n\n"
                f"Account ID: {context.get('account_id')}\n"
                f"Notes: {context.get('notes', '')}\n\n"
                "Validate and classify this alert."
            ),
        )

        parsed = self._extract_json(response)

        # Defensive: any non-empty alert with a known account warrants investigation
        alert_type_raw = alert.get("alert_type", context.get("alert_type", "transaction_velocity"))
        normalised = parsed.get("normalised_alert_type", alert_type_raw)
        priority = parsed.get("priority", "MEDIUM")
        proceed = parsed.get("proceed", True)

        self._print_action(
            f"Alert type: [bold]{normalised}[/bold] | Priority: [bold]{priority}[/bold]",
            f"Proceed with investigation: {proceed}",
        )

        if not proceed:
            self._print_decision("ALERT CLOSED — insufficient basis for investigation", color="yellow")
            context["mule_status"] = "ALERT_CLOSED"
            self._log(context, "CP1.1 — alert closed: insufficient grounds", "WARN")
            return context

        context["alert_validated"] = True
        context["alert_priority"] = priority
        context["alert_type"] = normalised
        context["alert_narrative"] = parsed.get("alert_narrative", "")
        context["cp1_1"] = {
            "validated": True,
            "priority": priority,
            "alert_type": normalised,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"CP1.1 complete — alert type: {normalised}, priority: {priority}")
        return context

    # ------------------------------------------------------------------ #
    # CP 1.2 — Retrieve Account Profile                                    #
    # ------------------------------------------------------------------ #

    def _cp1_2(self, context: dict) -> dict:
        self._print_step_header(
            "Retrieve Account Profile",
            "Pull CRM profile and initial transaction velocity for the flagged account.",
        )
        account_id = context.get("account_id")

        self._print_action(f"Querying CRM for account_id={account_id}")
        customer = self.crm.get_customer(account_id)

        if not customer.get("found"):
            self._print_decision(f"Account {account_id} not found in CRM", color="red")
            context["mule_status"] = "ACCOUNT_NOT_FOUND"
            self._log(context, "CP1.2 — account not found in CRM", "ERROR")
            return context

        self._print_action(
            "Account profile retrieved",
            f"Name: {customer['full_name']} | Risk rating: {customer.get('existing_risk_rating', 'UNKNOWN')}",
        )

        # Quick transaction velocity snapshot
        self._print_action(f"Pulling transaction velocity for {account_id}")
        velocity = self.tx.get_velocity(account_id)

        # Build display table
        table = Table(title="Account Profile", show_header=True, header_style="bold cyan")
        table.add_column("Field", style="dim", width=25)
        table.add_column("Value")
        for k, v in customer.items():
            if k not in ("found", "retrieved_at"):
                table.add_row(str(k), str(v))
        table.add_row("tx_count", str(velocity.get("tx_count", 0)))
        table.add_row("total_credit_hkd", str(velocity.get("total_credit_hkd", 0)))
        table.add_row("high_passthrough", str(velocity.get("high_passthrough", False)))
        console.print(table)

        context["account_profile"] = customer
        context["alert_velocity"] = velocity
        context["cp1_2"] = {
            "account_retrieved": True,
            "existing_risk_rating": customer.get("existing_risk_rating", "UNKNOWN"),
            "tx_count": velocity.get("tx_count", 0),
            "high_passthrough": velocity.get("high_passthrough", False),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"CP1.2 complete — profile for {customer['full_name']}")
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  MULE ALERT VALIDATION AGENT (CP1)  ━━━[/bold magenta]")
        context = self._cp1_1(context)
        if context.get("mule_status") in ("ALERT_CLOSED", "ACCOUNT_NOT_FOUND"):
            return context
        context = self._cp1_2(context)
        return context
