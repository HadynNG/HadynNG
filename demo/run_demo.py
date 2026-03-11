#!/usr/bin/env python3
"""
KYC Agentic Platform — Demo Runner

Usage:
    python demo/run_demo.py                    # interactive: enter customer details
    python demo/run_demo.py --demo clean       # quick preset: low-risk HK individual
    python demo/run_demo.py --demo pep         # quick preset: Philippine senator (PEP)
    python demo/run_demo.py --demo sanctioned  # quick preset: sanctioned Russian exec
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

from orchestrator import MissionExecutor
from tools.crm_tool import CRMTool

console = Console()

# ── Ollama configuration ──────────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"
MODEL = "qwen3.5:9b"

# ── Country name → ISO-3 code helpers ────────────────────────────────────────
_COUNTRY_MAP = {
    "hong kong": "HKG", "hk": "HKG",
    "china": "CHN", "prc": "CHN",
    "usa": "USA", "united states": "USA", "us": "USA", "america": "USA",
    "uk": "GBR", "united kingdom": "GBR", "britain": "GBR",
    "russia": "RUS", "russian federation": "RUS",
    "philippines": "PHL", "ph": "PHL",
    "singapore": "SGP", "sg": "SGP",
    "taiwan": "TWN",
    "japan": "JPN",
    "south korea": "KOR", "korea": "KOR",
    "australia": "AUS",
    "canada": "CAN",
    "germany": "DEU",
    "france": "FRA",
    "iran": "IRN",
    "north korea": "PRK",
    "syria": "SYR",
    "myanmar": "MMR",
    "pakistan": "PAK",
    "ukraine": "UKR",
}

def _resolve_nationality(raw: str) -> str:
    """Convert country name or code to ISO-3. Returns uppercased input if unknown."""
    normalised = raw.strip().lower()
    return _COUNTRY_MAP.get(normalised, raw.strip().upper()[:3])


# ── Preset demo cases ─────────────────────────────────────────────────────────
_PRESETS = {
    "clean": ROOT / "demo" / "cases" / "case_clean.json",
    "pep":   ROOT / "demo" / "cases" / "case_pep.json",
    "sanctioned": ROOT / "demo" / "cases" / "case_sanctioned.json",
}
_PRESET_EXPECTED = {
    "clean":      "APPROVE",
    "pep":        "APPROVE_WITH_CONDITIONS or ESCALATE_TO_MLRO",
    "sanctioned": "REJECT or ESCALATE_TO_MLRO",
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
def collect_customer_input() -> dict:
    """
    Interactively collect customer details from the user and return
    a mission_payload dict ready for MissionExecutor.
    """
    console.print()
    console.print(Rule("[bold cyan]NEW CUSTOMER — KYC SCREENING REQUEST[/bold cyan]", style="cyan"))
    console.print(
        "[dim]Enter the details of the customer you want to screen.\n"
        "Press Enter to accept the default where shown in brackets.[/dim]\n"
    )

    # ── Core identity fields ──────────────────────────────────────────────────
    full_name = Prompt.ask("[bold]Full name[/bold]")

    dob_raw = Prompt.ask(
        "[bold]Date of birth[/bold] [dim](YYYY-MM-DD)[/dim]",
        default="",
    )
    dob = dob_raw.strip() or "1980-01-01"

    nat_raw = Prompt.ask(
        "[bold]Nationality[/bold] [dim](country name or ISO-3 code, e.g. HKG, RUS, USA)[/dim]",
        default="HKG",
    )
    nationality = _resolve_nationality(nat_raw)

    id_type = Prompt.ask(
        "[bold]ID type[/bold]",
        choices=["HKID", "PASSPORT", "NID", "OTHER"],
        default="PASSPORT",
    )
    id_number = Prompt.ask(
        "[bold]ID number[/bold]",
        default=f"DEMO-{uuid.uuid4().hex[:8].upper()}",
    )

    # ── Optional enrichment fields ────────────────────────────────────────────
    occupation = Prompt.ask(
        "[bold]Occupation[/bold] [dim](optional, press Enter to skip)[/dim]",
        default="",
    )

    is_pep = Confirm.ask(
        "[bold]Is this customer a self-declared PEP[/bold] (Politically Exposed Person)?",
        default=False,
    )

    employer = Prompt.ask(
        "[bold]Employer / company[/bold] [dim](optional, press Enter to skip)[/dim]",
        default="",
    )

    address = Prompt.ask(
        "[bold]Address[/bold] [dim](optional, press Enter to skip)[/dim]",
        default="",
    )

    # ── Event metadata ────────────────────────────────────────────────────────
    console.print()
    event_type = Prompt.ask(
        "[bold]Event type[/bold]",
        choices=["onboarding", "transaction_alert", "customer_update", "periodic_review"],
        default="onboarding",
    )

    notes = Prompt.ask(
        "[bold]Additional context / notes[/bold] [dim](optional)[/dim]",
        default="",
    )

    # ── Build and register customer record ────────────────────────────────────
    customer_id = f"DEMO-{uuid.uuid4().hex[:6].upper()}"

    customer_record = {
        "customer_id": customer_id,
        "full_name": full_name,
        "aliases": [],
        "date_of_birth": dob,
        "nationality": nationality,
        "id_type": id_type,
        "id_number": id_number,
        "address": address or "Not provided",
        "email": "",
        "phone": "",
        "customer_type": "individual",
        "occupation": occupation or "Not provided",
        "employer": employer or "Not provided",
        "jurisdiction": nationality,
        "pep_self_declared": is_pep,
        "existing_risk_rating": "UNKNOWN",
    }

    CRMTool.register_customer(customer_record)

    # ── Show confirmation table ───────────────────────────────────────────────
    console.print()
    table = Table(title="Customer Profile to Screen", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim", width=22)
    table.add_column("Value")
    for k, v in customer_record.items():
        if k not in ("customer_id", "aliases", "email", "phone"):
            table.add_row(str(k).replace("_", " ").title(), str(v))
    console.print(table)
    console.print(f"  [dim]Customer ID: {customer_id}[/dim]\n")

    confirmed = Confirm.ask("[bold]Start KYC screening with these details?[/bold]", default=True)
    if not confirmed:
        console.print("[yellow]Screening cancelled.[/yellow]")
        sys.exit(0)

    # ── Build mission description ─────────────────────────────────────────────
    pep_note = " The customer is a self-declared PEP." if is_pep else ""
    notes_part = f" Additional context: {notes}" if notes else ""

    mission_description = (
        f"Perform full KYC name screening for {'new' if event_type == 'onboarding' else ''} "
        f"individual customer {customer_id} ({full_name}, {nationality} national), "
        f"triggered by a {event_type} event.{pep_note}"
        f" Occupation: {occupation or 'not provided'}."
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

    # Parse --demo flag
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

    if demo_flag:
        payload = load_preset(demo_flag)
    else:
        payload = collect_customer_input()

    expected = payload.pop("_expected", "N/A")

    executor = MissionExecutor(model=MODEL, ollama_host=OLLAMA_HOST)

    try:
        result = executor.execute(payload)
    except KeyboardInterrupt:
        console.print("\n[yellow]Demo interrupted by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        raise

    decision = result.get("final_decision", "N/A")
    color = {"APPROVE": "green", "APPROVE_WITH_CONDITIONS": "yellow"}.get(decision, "red")

    console.print(
        Panel(
            f"Final Decision : [bold {color}]{decision}[/bold {color}]\n"
            f"Expected       : {expected}\n"
            f"Audit Log      : {result.get('audit_log_file', 'N/A')}\n"
            f"Timeline       : {result.get('timeline_file', 'N/A')}",
            title="[bold]Demo Complete[/bold]",
            border_style="magenta",
        )
    )


if __name__ == "__main__":
    main()
