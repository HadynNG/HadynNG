#!/usr/bin/env python3
"""
KYC Agentic Platform — Demo Runner

The chatbot runs as a general-purpose compliance assistant.
It responds to any question or message conversationally.
When the user's intent is to screen a customer (KYC / AML / sanctions check),
the full SOP pipeline is triggered automatically.

Usage:
    python demo/run_demo.py                    # conversational mode
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

import ollama
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

from orchestrator import IntentParser, MissionExecutor, MuleExecutor
from tools.crm_tool import CRMTool

console = Console()

# ── Ollama configuration ──────────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"
MODEL = "qwen3.5:9b"

# ── Conversational assistant persona ─────────────────────────────────────────
_CHAT_SYSTEM_PROMPT = """You are a knowledgeable compliance operations assistant embedded in an \
AML/KYC screening platform. You help compliance officers, relationship managers, and operations \
staff with questions about:
- KYC (Know Your Customer) procedures and requirements
- AML (Anti-Money Laundering) regulations and red flags
- Sanctions screening (UN Security Council, OFAC SDN, EU Consolidated, HKMA)
- PEP (Politically Exposed Persons) identification and handling
- Risk assessment methodologies (LOW / MEDIUM / HIGH)
- Regulatory frameworks: HKMA guidelines, AMLO (Cap. 615), SFC AML Circular, FATF
- EDD (Enhanced Due Diligence) triggers and procedures
- STR (Suspicious Transaction Report) filing obligations

To screen a customer, the user can say something like:
  "Screen John Smith for new account onboarding"
  "Run KYC on Valeria Petrov — suspicious wire transfer"
  "Periodic review for Senator Marcus Delgado"

Keep your answers concise, accurate, and professional.
If you are unsure about something, say so clearly."""


# ── KYC Screening preset demo cases ──────────────────────────────────────────
_PRESETS = {
    "clean":      ROOT / "demo" / "cases" / "case_clean.json",
    "medium":     ROOT / "demo" / "cases" / "case_medium_risk.json",
    "pep":        ROOT / "demo" / "cases" / "case_pep.json",
    "sanctioned": ROOT / "demo" / "cases" / "case_sanctioned.json",
}
_PRESET_EXPECTED = {
    "clean":      "APPROVE",
    "medium":     "APPROVE_WITH_CONDITIONS",
    "pep":        "ESCALATE_TO_MLRO",
    "sanctioned": "REJECT",
}

# ── Mule Account Hunting preset demo cases ────────────────────────────────────
_MULE_PRESETS = {
    "mule-unwitting":    ROOT / "demo" / "cases" / "case_mule_unwitting.json",
    "mule-professional": ROOT / "demo" / "cases" / "case_mule_professional.json",
    "mule-clean":        ROOT / "demo" / "cases" / "case_mule_clean.json",
}
_MULE_PRESET_EXPECTED = {
    "mule-unwitting":    "FILE_SAR or ESCALATE_TO_MLRO",
    "mule-professional": "FILE_SAR",
    "mule-clean":        "CLOSE_NO_ACTION or MONITOR",
}


# ── Welcome banner ────────────────────────────────────────────────────────────
def _print_welcome():
    console.print()
    console.print(
        Panel(
            "[bold cyan]KYC Compliance Assistant — Agentic AI Platform[/bold cyan]\n\n"
            f"Powered by [bold]Ollama[/bold] / [bold]{MODEL}[/bold]\n\n"
            "I can help you with compliance questions, AML/KYC regulations,\n"
            "sanctions screening, and PEP identification.\n\n"
            "[bold]To trigger a KYC screening[/bold], just describe it naturally:\n"
            "  [dim]• Screen James Wong for new account onboarding[/dim]\n"
            "  [dim]• Run KYC on Valeria Petrov — suspicious wire transfer[/dim]\n"
            "  [dim]• Periodic review needed for Senator Marcus Delgado[/dim]\n\n"
            "Or ask me anything about compliance.\n"
            "[dim]Type 'quit' or press Ctrl+C to exit.[/dim]",
            title="[bold magenta]AGENTIC KYC PLATFORM[/bold magenta]",
            border_style="magenta",
            padding=(1, 4),
        )
    )


# ── General conversational reply ──────────────────────────────────────────────
def _chat_reply(user_input: str) -> None:
    """Call the LLM as a conversational compliance assistant and print the response."""
    try:
        client = ollama.Client(host=OLLAMA_HOST)
        response = client.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            stream=False,
            think=False,          # No CoT needed for chat — keep it fast
            options={
                "temperature": 0.3,
                "num_predict": 512,
                "seed": 0,
            },
        )
        content = (response.message.content or "").strip()
        console.print(f"\n[bold green]Assistant:[/bold green] {content}\n")
    except Exception as e:
        console.print(f"\n[red]Assistant unavailable: {e}[/red]\n")


# ── KYC sub-flow: CRM lookup + payload builder ────────────────────────────────
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


def _kyc_sub_flow(intent: dict) -> dict | None:
    """
    Given a parsed KYC intent, look up the customer in the CRM, confirm with
    the user, and return a mission payload ready for MissionExecutor.
    Returns None if the user cancels.
    """
    full_name = intent["customer_name"]
    event_type = intent["event_type"]
    notes = intent["notes"]

    console.print(
        f"\n  [green]✓ KYC screening triggered[/green] — "
        f"Subject: [bold]{full_name}[/bold]  "
        f"Event: [dim]{event_type}[/dim]"
    )
    if notes:
        console.print(f"  [dim]Context: {notes}[/dim]")

    # ── Search CRM ───────────────────────────────────────────────────────────
    matches = CRMTool.search_by_name(full_name)

    customer_id: str
    customer_record: dict

    if matches:
        best = matches[0]
        console.print()
        if len(matches) == 1 or best["_match_score"] >= 0.80:
            console.print(
                f"  [green]Found matching record "
                f"(confidence: {best['_match_score']:.0%})[/green]"
            )
            _show_customer_table(best, "Matched Customer Record")
            confirmed = Confirm.ask(
                "[bold]Is this the correct customer?[/bold]", default=True
            )
            if confirmed:
                customer_id = best["customer_id"]
                customer_record = best
            else:
                console.print(
                    "[yellow]No matching record used — proceeding with name only.[/yellow]"
                )
                matches = []
        else:
            console.print(f"  [yellow]Found {len(matches)} possible matches:[/yellow]\n")
            for idx, m in enumerate(matches[:4], start=1):
                console.print(
                    f"  [{idx}] {m['full_name']}  "
                    f"({m.get('nationality','?')}, DOB: {m.get('date_of_birth','?')})  "
                    f"[dim]— {m['_match_score']:.0%} match[/dim]"
                )
            console.print("  [0] None of these — screen by name only")
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
        console.print(
            "\n  [dim]No existing CRM record — screening by name only.[/dim]\n"
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
        console.print("[yellow]Screening cancelled.[/yellow]\n")
        return None

    # ── Build mission payload ─────────────────────────────────────────────────
    nat = customer_record.get("nationality", "UNKNOWN")
    is_pep = customer_record.get("pep_self_declared", False)
    pep_note = " The customer is a self-declared PEP." if is_pep else ""
    notes_part = f" Additional context: {notes}" if notes else ""

    mission_description = (
        f"Perform full KYC name screening for individual customer "
        f"{customer_id} ({full_name}, {nat} national), "
        f"triggered by a {event_type} event.{pep_note}"
        f"{notes_part}"
        f" Verify identity, assess risk, screen against all applicable sanctions and PEP "
        f"lists, and make an approval decision per HKMA and AMLO requirements."
    )

    return {
        "customer_id": customer_id,
        "event": {
            "event_type": event_type,
            "trigger_source": "chat_user_input",
            "triggered_at": datetime.utcnow().isoformat() + "Z",
            "notes": notes or f"User-initiated {event_type} screening",
        },
        "mission_description": mission_description,
        "_expected": "Depends on customer profile",
    }


# ── Mule pipeline runner ──────────────────────────────────────────────────────
def _run_mule_pipeline(executor: MuleExecutor, payload: dict) -> None:
    """Execute the mule hunting pipeline and print the final result panel."""
    expected = payload.pop("_expected", "N/A")
    try:
        result = executor.execute(payload)
    except KeyboardInterrupt:
        console.print("\n[yellow]Investigation interrupted.[/yellow]\n")
        return
    except Exception as e:
        console.print(f"\n[red]Investigation error: {e}[/red]\n")
        return

    disposition = result.get("final_disposition", "N/A")
    color = {
        "FILE_SAR": "red",
        "ESCALATE_TO_MLRO": "red",
        "MONITOR": "yellow",
        "CLOSE_NO_ACTION": "green",
    }.get(disposition, "white")

    console.print(
        Panel(
            f"Final Disposition : [bold {color}]{disposition}[/bold {color}]\n"
            f"Expected          : {expected}\n"
            f"Mule Type         : {result.get('mule_type', 'N/A')}\n"
            f"Typology          : {result.get('fraud_typology', 'N/A')}\n"
            f"SAR Reference     : {result.get('sar_reference') or 'None'}",
            title="[bold]Mule Investigation Complete[/bold]",
            border_style="red",
        )
    )
    console.print()


# ── KYC Pipeline runner ───────────────────────────────────────────────────────
def _run_pipeline(executor: MissionExecutor, payload: dict) -> None:
    """Execute the KYC pipeline and print the final result panel."""
    expected = payload.pop("_expected", "N/A")
    try:
        result = executor.execute(payload)
    except KeyboardInterrupt:
        console.print("\n[yellow]Screening interrupted.[/yellow]\n")
        return
    except Exception as e:
        console.print(f"\n[red]Screening error: {e}[/red]\n")
        return

    decision = result.get("final_decision", "N/A")
    color = {"APPROVE": "green", "APPROVE_WITH_CONDITIONS": "yellow"}.get(decision, "red")

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
    console.print()


# ── Preset loader ─────────────────────────────────────────────────────────────
def _load_preset(name: str) -> dict:
    with open(_PRESETS[name], encoding="utf-8") as f:
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


def _load_mule_preset(name: str) -> dict:
    with open(_MULE_PRESETS[name], encoding="utf-8") as f:
        payload = json.load(f)
    console.print(
        Panel(
            f"[bold]Preset:[/bold]   {name}\n"
            f"[bold]Expected:[/bold] {_MULE_PRESET_EXPECTED[name]}",
            title="[bold]Mule Hunting Demo Preset[/bold]",
            border_style="red",
        )
    )
    return {**payload, "_expected": _MULE_PRESET_EXPECTED[name]}


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    _print_welcome()

    # ── Parse --demo flag ─────────────────────────────────────────────────────
    all_presets = {**_PRESETS, **_MULE_PRESETS}
    demo_flag = None
    args = sys.argv[1:]
    if "--demo" in args:
        idx = args.index("--demo")
        if idx + 1 < len(args) and args[idx + 1] in all_presets:
            demo_flag = args[idx + 1]
        else:
            console.print(
                f"[red]Unknown --demo value. Choose from: {list(all_presets)}[/red]"
            )
            sys.exit(1)

    # Components created once — reused across all turns
    intent_parser = IntentParser(model=MODEL, ollama_host=OLLAMA_HOST)
    executor = MissionExecutor(model=MODEL, ollama_host=OLLAMA_HOST)
    mule_executor = MuleExecutor(model=MODEL, ollama_host=OLLAMA_HOST)

    # Run preset pipeline first if --demo was given
    if demo_flag:
        if demo_flag in _MULE_PRESETS:
            _run_mule_pipeline(mule_executor, _load_mule_preset(demo_flag))
        else:
            _run_pipeline(executor, _load_preset(demo_flag))

    # ── Main conversational loop ──────────────────────────────────────────────
    while True:
        try:
            raw = Prompt.ask("\n[bold cyan]You[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended. Goodbye.[/dim]")
            return

        text = raw.strip()

        if not text:
            continue

        if text.lower() in ("quit", "exit", "q", "bye"):
            console.print("[dim]Goodbye.[/dim]")
            return

        # ── Classify intent ───────────────────────────────────────────────────
        intent = intent_parser.parse(text)

        if intent["is_kyc_request"]:
            # KYC path: collect customer info → run pipeline
            payload = _kyc_sub_flow(intent)
            if payload:
                _run_pipeline(executor, payload)
        else:
            # General chat path: respond as compliance assistant
            _chat_reply(text)


if __name__ == "__main__":
    main()
