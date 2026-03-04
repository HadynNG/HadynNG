"""
Screening Agent — Steps 3.1, 3.2
- Prepare query variants (name permutations, transliterations)
- Run automated screening against sanctions/PEP lists
"""
import unicodedata
from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent
from tools.screening_tool import SanctionsScreeningTool

console = Console()


def _remove_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _generate_name_variants(full_name: str, aliases: list[str]) -> list[str]:
    """Generate screening query variants from name and aliases."""
    variants = set()
    all_names = [full_name] + aliases

    for name in all_names:
        name = name.strip()
        variants.add(name)
        # Normalised (no accents)
        variants.add(_remove_accents(name))
        # Reverse order (surname, given)
        parts = name.split()
        if len(parts) >= 2:
            # Last name first
            variants.add(f"{parts[-1]} {' '.join(parts[:-1])}")
            # Initials
            variants.add(f"{parts[0]} {parts[-1]}")
        # Upper/lower normalised
        variants.add(name.upper())

    return [v for v in variants if v]


class ScreeningAgent(BaseAgent):
    name = "ScreeningAgent"
    step_label = "Phase 3"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.screener = SanctionsScreeningTool()

    # ------------------------------------------------------------------ #
    # Step 3.1 — Prepare Screening Queries                                 #
    # ------------------------------------------------------------------ #

    def _step_3_1(self, context: dict) -> dict:
        self._print_step_header(
            "Prepare Screening Queries",
            "Generate name variants and query strings for screening.",
        )
        customer = context["customer_data"]

        aliases = customer.get("aliases", [])
        queries = _generate_name_variants(customer["full_name"], aliases)

        self._print_action(
            f"Generated {len(queries)} query variants for '{customer['full_name']}'",
        )
        for q in sorted(queries):
            console.print(f"    [dim]• {q}[/dim]")

        context["screening_queries"] = list(queries)
        context["step_3_1"] = {
            "queries": list(queries),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(context, f"Step 3.1 complete — {len(queries)} query variants generated")
        return context

    # ------------------------------------------------------------------ #
    # Step 3.2 — Run Automated Screening                                   #
    # ------------------------------------------------------------------ #

    def _step_3_2(self, context: dict) -> dict:
        self._print_step_header(
            "Run Automated Screening",
            "Query sanctions, PEP, and watchlists. Search adverse media for high-risk.",
        )
        queries = context["screening_queries"]
        customer = context["customer_data"]
        risk_level = context["risk_level"]

        self._print_action("Submitting queries to screening engine", "Lists: UN, OFAC, EU, HKMA, PEP")
        results = self.screener.screen(queries, customer)

        hits = results["hits"]
        console.print(
            f"\n  [bold]Screening complete[/bold]: {results['total_hits']} hit(s) found "
            f"across {len(results['lists_checked'])} lists"
        )

        if hits:
            table = Table(title="Raw Screening Hits", show_header=True, header_style="bold red")
            table.add_column("List", style="dim", width=20)
            table.add_column("Matched Name", width=25)
            table.add_column("Type", width=12)
            table.add_column("Confidence", justify="right", width=12)
            table.add_column("Identifiers Matched")
            for h in hits:
                conf = h["overall_confidence"]
                color = "red" if conf >= 0.8 else "yellow" if conf >= 0.6 else "white"
                table.add_row(
                    h["list"],
                    h["matched_name"],
                    h["match_type"],
                    f"[{color}]{conf:.0%}[/{color}]",
                    ", ".join(h["identifiers_matched"]) or "name only",
                )
            console.print(table)
        else:
            console.print("  [bold green]✓ No matches found in screening databases[/bold green]")

        # Adverse media for high-risk customers
        adverse = []
        if risk_level in ("HIGH", "MEDIUM"):
            self._print_action("Running adverse media search (elevated risk customer)")
            adverse = self.screener.search_adverse_media(customer["full_name"])
            if adverse:
                console.print(f"\n  [bold yellow]Adverse media: {len(adverse)} article(s) found[/bold yellow]")
                for a in adverse:
                    console.print(f"    [yellow]• [{a['source']}] {a['headline']}[/yellow]")
            else:
                console.print("  [green]  No adverse media found[/green]")

        context["screening_results"] = results
        context["adverse_media"] = adverse
        context["step_3_2"] = {
            "total_hits": results["total_hits"],
            "adverse_media_count": len(adverse),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(
            context,
            f"Step 3.2 complete — {results['total_hits']} screening hits, {len(adverse)} adverse media",
        )
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print(
            f"\n[bold magenta]━━━  SCREENING AGENT  ━━━[/bold magenta]"
        )
        context = self._step_3_1(context)
        context = self._step_3_2(context)
        return context
