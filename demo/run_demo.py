#!/usr/bin/env python3
"""
KYC Agentic Platform — Demo Runner

Usage:
    python demo/run_demo.py [case]

Cases:
    clean       — Low-risk HK individual (expected: APPROVE)
    pep         — Philippine senator, self-declared PEP (expected: APPROVE_WITH_CONDITIONS or ESCALATE)
    sanctioned  — Russian energy exec on UN/OFAC lists (expected: REJECT or ESCALATE_TO_MLRO)

Examples:
    python demo/run_demo.py clean
    python demo/run_demo.py pep
    python demo/run_demo.py sanctioned
"""

import json
import sys
from pathlib import Path

# Make sure the project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule

from orchestrator import MissionExecutor

console = Console()

CASES = {
    "clean": ROOT / "demo" / "cases" / "case_clean.json",
    "pep": ROOT / "demo" / "cases" / "case_pep.json",
    "sanctioned": ROOT / "demo" / "cases" / "case_sanctioned.json",
}

EXPECTED = {
    "clean": "APPROVE",
    "pep": "APPROVE_WITH_CONDITIONS or ESCALATE_TO_MLRO",
    "sanctioned": "REJECT or ESCALATE_TO_MLRO",
}


def print_welcome():
    console.print()
    console.print(
        Panel(
            "[bold cyan]KYC Name Screening — Agentic AI Platform[/bold cyan]\n\n"
            "This demo showcases a fully agentic KYC pipeline powered by\n"
            f"[bold]Ollama[/bold] with [bold]qwen3-coder-next:latest[/bold].\n\n"
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


def select_case(arg: str | None) -> tuple[str, dict]:
    if arg and arg.lower() in CASES:
        case_name = arg.lower()
    else:
        console.print("\nAvailable demo cases:\n")
        for name, path in CASES.items():
            console.print(f"  [bold]{name:12s}[/bold] — Expected: {EXPECTED[name]}")
        console.print()
        case_name = Prompt.ask(
            "Select a case",
            choices=list(CASES.keys()),
            default="clean",
        )

    case_file = CASES[case_name]
    with open(case_file, encoding="utf-8") as f:
        payload = json.load(f)

    console.print(
        Panel(
            f"[bold]Case:[/bold]     {case_name}\n"
            f"[bold]File:[/bold]     {case_file.name}\n"
            f"[bold]Expected:[/bold] {EXPECTED[case_name]}",
            title="[bold]Selected Demo Case[/bold]",
            border_style="cyan",
        )
    )
    return case_name, payload


def main():
    print_welcome()

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    case_name, payload = select_case(arg)

    # Configurable — point to your Ollama instance
    OLLAMA_HOST = "http://localhost:11434"
    MODEL = "qwen3-coder-next:latest"

    executor = MissionExecutor(model=MODEL, ollama_host=OLLAMA_HOST)

    try:
        result = executor.execute(payload)
    except KeyboardInterrupt:
        console.print("\n[yellow]Demo interrupted by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        raise

    console.print(
        Panel(
            f"Case [bold]{case_name}[/bold] completed.\n"
            f"Final Decision: [bold]{result.get('final_decision', 'N/A')}[/bold]\n"
            f"Expected:       {EXPECTED[case_name]}",
            title="[bold]Demo Summary[/bold]",
            border_style="magenta",
        )
    )


if __name__ == "__main__":
    main()
