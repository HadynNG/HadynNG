"""
Linked Account Discovery Agent — Checkpoint 2
- Traverse account relationship graph to find all linked accounts
- Classify each link by relationship type and strength
- Produce network risk assessment
"""

from datetime import datetime

from rich.console import Console
from rich.table import Table

from .base_agent import BaseAgent
from tools.network_graph_tool import NetworkGraphTool
from tools.crm_tool import CRMTool

console = Console()


class LinkedAccountDiscoveryAgent(BaseAgent):
    name = "LinkedAccountDiscoveryAgent"
    step_label = "Checkpoint 2"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.graph = NetworkGraphTool()
        self.crm = CRMTool()

    # ------------------------------------------------------------------ #
    # CP 2 — Discover Linked Accounts                                      #
    # ------------------------------------------------------------------ #

    def _cp2(self, context: dict) -> dict:
        self._print_step_header(
            "Linked Account Discovery",
            "Graph traversal to identify all accounts connected to the subject (depth ≤ 2).",
        )
        account_id = context.get("account_id")

        self._print_action(f"Running BFS network traversal from {account_id} (max depth 2)")
        summary = self.graph.get_network_summary(account_id)

        linked_accounts = summary.get("linked_accounts", [])
        linked_ids = [la["account_id"] for la in linked_accounts]

        # Show network table
        if linked_accounts:
            table = Table(
                title=f"Linked Accounts (depth ≤ 2) for {account_id}",
                show_header=True,
                header_style="bold yellow",
            )
            table.add_column("Account ID", width=20)
            table.add_column("Depth", width=6)
            table.add_column("Relationship Path")
            for la in linked_accounts:
                path_str = " → ".join(
                    f"{p['relationship']}({p['strength']})" for p in la.get("path", [])
                )
                table.add_row(la["account_id"], str(la["depth"]), path_str or "direct")
            console.print(table)
        else:
            console.print("  [dim]No linked accounts found within depth 2.[/dim]")

        # Check known networks
        known_nets = summary.get("known_networks", [])
        if summary.get("known_network_member"):
            self._print_decision(
                f"Account is a member of {len(known_nets)} known mule network(s) — HIGH network risk",
                color="red",
            )
        else:
            net_risk = summary.get("network_risk", "LOW")
            color = "red" if net_risk == "HIGH" else "yellow" if net_risk == "MEDIUM" else "green"
            self._print_decision(
                f"Network risk: {net_risk} | Linked accounts: {len(linked_accounts)}",
                color=color,
            )

        # Build summary text
        network_summary = (
            f"Found {len(linked_accounts)} linked account(s) within 2 hops. "
            f"Network risk score: {summary['network_risk_score']}. "
            f"Known mule network member: {summary['known_network_member']}. "
            f"High-risk direct links: {len(summary.get('high_risk_links', []))}."
        )

        context["linked_accounts"] = linked_ids
        context["linked_account_details"] = linked_accounts
        context["network_summary"] = network_summary
        context["network_risk_score"] = summary["network_risk_score"]
        context["known_network_member"] = summary["known_network_member"]
        context["known_networks"] = known_nets
        context["network_risk"] = summary["network_risk"]
        context["cp2"] = {
            "linked_account_count": len(linked_accounts),
            "network_risk": summary["network_risk"],
            "network_risk_score": summary["network_risk_score"],
            "known_network_member": summary["known_network_member"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._log(
            context,
            f"CP2 complete — {len(linked_accounts)} linked accounts, network risk: {summary['network_risk']}",
        )
        return context

    # ------------------------------------------------------------------ #
    # Main entry point                                                      #
    # ------------------------------------------------------------------ #

    def run(self, context: dict) -> dict:
        console.print("\n[bold magenta]━━━  LINKED ACCOUNT DISCOVERY AGENT (CP2)  ━━━[/bold magenta]")
        context = self._cp2(context)
        return context
