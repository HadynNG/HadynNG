#!/usr/bin/env python3
"""
KYC Agentic Platform — Demo Runner

Usage:
    python demo/run_demo.py                    # interactive: enter customer name → CRM lookup
    python demo/run_demo.py --demo clean       # APPROVE      : low-risk HK individual
    python demo/run_demo.py --demo medium      # APPROVE_WITH_CONDITIONS : medium-risk customer
    python demo/run_demo.py --demo pep         # ESCALATE_TO_MLRO : Philippine PEP senator
    python demo/run_demo.py --demo sanctioned  # REJECT       : sanctioned Russian executive
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

from orchestrator import IntentParser, MissionExecutor
from tools.crm_tool import CRMTool

console = Console()

# ── Ollama configuration ──────────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"
MODEL = "qwen3.5:9b"


# ── Preset demo cases ─────────────────────────────────────────────────────────
_PRESETS = {
    "clean":       ROOT / "demo" / "cases" / "case_clean.json",
    "medium":      ROOT / "demo" / "cases" / "case_medium_risk.json",
    "pep":         ROOT / "demo" / "cases" / "case_pep.json",
    "sanctioned":  ROOT / "demo" / "cases" / "case_sanctioned.json",
}
_PRESET_EXPECTED = {
    "clean":      "APPROVE",
    "medium":     "APPROVE_WITH_CONDITIONS",
    "pep":        "ESCALATE_TO_MLRO",
    "sanctioned": "REJECT",
}


# ── Welcome banner ────────────────────────────────────────────────────────────
def print_welcome():
    console.print()
    console.print(
        Panel(
            "[bold cyan]KYC Name Screening — Agentic AI Platform[/bold cyan]\n\n"
            "This demo showcases a fully agentic KYC pipeline powered by\n"
            f"[bold]Ollama[/bold] with [bold]{MODEL}[/bold].\n\n"
            "The orchestrator uses LLM chain-of-thought to:\n"
            "  • Plan the mission execution\n"
            "  • Classify events and collect customer data\n"
            "  • Score risk using rule-based and LLM reasoning\n"
            "  • Screen against sanctions / PEP databases\n"
            "  • Investigate alerts with LLM analysis\n"
            "  • Make final compliance decisions\n"
            "  • Generate audit trails and notifications\n\n"
            "[dim]All chain-of-thought output is shown in real time.[/dim]",
            title="[bold magenta]AGENTIC KYC PLATFORM[/bold magenta]",
            border_style="magenta",
            padding=(1, 4),
        )
    )


# ── Interactive customer input ────────────────────────────────────────────────
def _show_customer_table(record: dict, title: str = "Customer Profile to Screen"):
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim", width=24)
    table.add_column("Value")
    skip = {"customer_id", "aliases", "email", "phone", "_match_score"}
    for k, v in record.items():
        if k not in skip:
            table.add_row(str(k).replace("_", " ").title(), str(v))
    console.print(table)
    console.print(f"  [dim]Customer ID: {record['customer_id']}[/dim]\n")


def collect_customer_input() -> dict:
    """
    Accept a free-form user prompt, parse intent against the KYC SOP,
    look up the customer in the CRM, and build the mission payload.
    """
    parser = IntentParser(model=MODEL, ollama_host=OLLAMA_HOST)

    # ── Free-form prompt loop ─────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold cyan]KYC SCREENING REQUEST[/bold cyan]", style="cyan"))
    console.print(
        "[dim]Describe the customer you want to screen in plain language.\n"
        "Examples:\n"
        "  • 'Screen James Wong for new account onboarding'\n"
        "  • 'Run KYC on Valeria Petrov — suspicious wire transfer'\n"
        "  • 'Periodic review needed for Senator Marcus Delgado'[/dim]\n"
    )

    intent = None
    while True:
        raw = Prompt.ask("[bold]Your request[/bold]")

        # Allow graceful exit from the prompt
        if raw.strip().lower() in ("quit", "exit", "q", "bye"):
            console.print("[dim]Goodbye.[/dim]")
            sys.exit(0)

        intent = parser.parse(raw)

        if intent["is_kyc_request"]:
            console.print(
                f"\n  [green]✓ KYC request recognised[/green] — "
                f"Subject: [bold]{intent['customer_name']}[/bold]  "
                f"Event: [dim]{intent['event_type']}[/dim]"
            )
            if intent["notes"]:
                console.print(f"  [dim]Context: {intent['notes']}[/dim]")
            break
        else:
            console.print(
                f"\n  [yellow]⚠  This does not appear to be a KYC screening request.[/yellow]"
            )
            if intent["decline_reason"]:
                console.print(f"  [dim]{intent['decline_reason']}[/dim]")
            console.print(
                "  [dim]Please describe a customer to screen "
                "(e.g. 'Screen John Smith for onboarding'), or type 'quit' to exit.[/dim]\n"
            )

    full_name = intent["customer_name"]
    event_type = intent["event_type"]
    notes = intent["notes"]

    # ── Search CRM ───────────────────────────────────────────────────────────
    matches = CRMTool.search_by_name(full_name)

    customer_id: str
    customer_record: dict

    if matches:
        best = matches[0]
        console.print()
        if len(matches) == 1 or best["_match_score"] >= 0.80:
            # Confident single match — confirm with user
            console.print(
                f"  [green]Found matching record (confidence: {best['_match_score']:.0%})[/green]"
            )
            _show_customer_table(best, "Matched Customer Record")
            confirmed = Confirm.ask(
                "[bold]Is this the correct customer?[/bold]", default=True
            )
            if confirmed:
                customer_id = best["customer_id"]
                customer_record = best
            else:
                console.print("[yellow]No matching record used — proceeding with name only.[/yellow]")
                matches = []  # fall through to new-customer path
        else:
            # Multiple plausible matches — let user pick
            console.print(f"  [yellow]Found {len(matches)} possible matches:[/yellow]\n")
            for idx, m in enumerate(matches[:4], start=1):
                console.print(
                    f"  [{idx}] {m['full_name']}  "
                    f"({m.get('nationality','?')}, DOB: {m.get('date_of_birth','?')})  "
                    f"[dim]— {m['_match_score']:.0%} match[/dim]"
                )
            console.print(f"  [0] None of these — screen by name only")
            choice_str = Prompt.ask(
                "\n  [bold]Select customer[/bold]",
                choices=[str(i) for i in range(len(matches[:4]) + 1)],
                default="1",
            )
            choice = int(choice_str)
            if choice == 0:
                matches = []
            else:
                selected = matches[choice - 1]
                _show_customer_table(selected, "Selected Customer Record")
                customer_id = selected["customer_id"]
                customer_record = selected

    if not matches:
        # No CRM record found — screen by name with minimal profile
        console.print(
            "\n  [dim]No existing record found. Customer will be screened by name only.[/dim]\n"
        )
        customer_id = f"DEMO-{uuid.uuid4().hex[:6].upper()}"
        customer_record = {
            "customer_id": customer_id,
            "full_name": full_name,
            "aliases": [],
            "date_of_birth": "UNKNOWN",
            "nationality": "UNKNOWN",
            "id_type": "UNKNOWN",
            "id_number": f"DEMO-{uuid.uuid4().hex[:8].upper()}",
            "address": "Not provided",
            "email": "",
            "phone": "",
            "customer_type": "individual",
            "occupation": "Not provided",
            "employer": "Not provided",
            "jurisdiction": "UNKNOWN",
            "pep_self_declared": False,
            "existing_risk_rating": "UNKNOWN",
        }
        CRMTool.register_customer(customer_record)

    # ── Final confirmation ────────────────────────────────────────────────────
    confirmed = Confirm.ask("\n[bold]Start KYC screening?[/bold]", default=True)
    if not confirmed:
        console.print("[yellow]Screening cancelled — returning to main prompt.[/yellow]")
        return None

    # ── Build mission description ─────────────────────────────────────────────
    nat = customer_record.get("nationality", "UNKNOWN")
    is_pep = customer_record.get("pep_self_declared", False)
    pep_note = " The customer is a self-declared PEP." if is_pep else ""
    notes_part = f" Additional context: {notes}" if notes else ""

    mission_description = (
        f"Perform full KYC name screening for individual customer "
        f"{customer_id} ({full_name}, {nat} national), "
        f"triggered by a {event_type} event.{pep_note}"
        f"{notes_part}"
        f" Verify identity, assess risk, screen against all applicable sanctions and PEP lists, "
        f"and make an approval decision per HKMA and AMLO requirements."
    )

    return {
        "customer_id": customer_id,
        "event": {
            "event_type": event_type,
            "trigger_source": "demo_user_input",
            "triggered_at": datetime.utcnow().isoformat() + "Z",
            "notes": notes or f"User-initiated {event_type} screening",
        },
        "mission_description": mission_description,
        "_expected": "Depends on customer profile",
    }


# ── Preset loader ─────────────────────────────────────────────────────────────
def load_preset(name: str) -> dict:
    case_file = _PRESETS[name]
    with open(case_file, encoding="utf-8") as f:
        payload = json.load(f)
    console.print(
        Panel(
            f"[bold]Preset:[/bold]   {name}\n"
            f"[bold]Expected:[/bold] {_PRESET_EXPECTED[name]}",
            title="[bold]Quick Demo Preset[/bold]",
            border_style="cyan",
        )
    )
    return {**payload, "_expected": _PRESET_EXPECTED[name]}


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    print_welcome()

    # Parse --demo flag (only affects the first iteration)
    demo_flag = None
    args = sys.argv[1:]
    if "--demo" in args:
        idx = args.index("--demo")
        if idx + 1 < len(args) and args[idx + 1] in _PRESETS:
            demo_flag = args[idx + 1]
        else:
            console.print(
                f"[red]Unknown --demo value. Choose from: {list(_PRESETS)}[/red]"
            )
            sys.exit(1)

    # Create executor once — reused across all screening runs
    executor = MissionExecutor(model=MODEL, ollama_host=OLLAMA_HOST)

    first_run = True

    # ── Persistent chat loop ──────────────────────────────────────────────────
    while True:
        try:
            # On first iteration use the --demo preset if given, then switch to interactive
            if first_run and demo_flag:
                payload = load_preset(demo_flag)
                first_run = False
            else:
                first_run = False
                payload = collect_customer_input()
        except (KeyboardInterrupt, SystemExit):
            console.print("\n[dim]Session ended. Goodbye.[/dim]")
            return

        # collect_customer_input returns None when the user cancels — loop back
        if payload is None:
            console.print()
            console.print(Rule("[dim]Ready for next screening request[/dim]", style="dim"))
            continue

        expected = payload.pop("_expected", "N/A")

        # ── Execute KYC pipeline ──────────────────────────────────────────────
        try:
            result = executor.execute(payload)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Screening interrupted. Returning to main prompt.[/yellow]"
            )
            console.print(Rule("[dim]Ready for next screening request[/dim]", style="dim"))
            continue
        except Exception as e:
            console.print(f"\n[red]Screening error: {e}[/red]")
            console.print(Rule("[dim]Ready for next screening request[/dim]", style="dim"))
            continue

        # ── Show result ───────────────────────────────────────────────────────
        decision = result.get("final_decision", "N/A")
        color = {"APPROVE": "green", "APPROVE_WITH_CONDITIONS": "yellow"}.get(
            decision, "red"
        )

        console.print(
            Panel(
                f"Final Decision : [bold {color}]{decision}[/bold {color}]\n"
                f"Expected       : {expected}\n"
                f"Audit Log      : {result.get('audit_log_file', 'N/A')}\n"
                f"Timeline       : {result.get('timeline_file', 'N/A')}",
                title="[bold]Screening Complete[/bold]",
                border_style="magenta",
            )
        )

        # ── Loop back — ready for next request ────────────────────────────────
        console.print()
        console.print(
            Rule("[dim]Ready for next screening request  •  type 'quit' to exit[/dim]", style="dim")
        )


if __name__ == "__main__":
    main()
