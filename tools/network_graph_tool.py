"""
Network Graph Tool — linked account discovery via graph traversal.

Loads account relationship data from storage/seeds/network_graph.md.
Performs BFS traversal to find all accounts reachable within a given depth,
and returns network summaries for mule investigation.
"""

from collections import defaultdict, deque
from typing import Any

from tools.md_loader import load, parse_sections

# ── Module-level cache ────────────────────────────────────────────────────────

def _load_graph_data() -> tuple[list[dict], list[dict]]:
    sections = parse_sections(load("network_graph.md"))
    links = sections.get("Account Links", [])
    networks = sections.get("Known Mule Networks", [])
    return links, networks


_LINKS, _KNOWN_NETWORKS = _load_graph_data()

# Strength weights for risk scoring
_STRENGTH_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

# Build adjacency index at import time
def _build_adjacency(links: list[dict]) -> dict[str, list[dict]]:
    adj: dict[str, list[dict]] = defaultdict(list)
    for lnk in links:
        src = lnk.get("source_account", "")
        tgt = lnk.get("target_account", "")
        if src and tgt:
            adj[src].append({"account": tgt, **lnk})
            adj[tgt].append({"account": src, **lnk})  # undirected
    return adj


_ADJ = _build_adjacency(_LINKS)


class NetworkGraphTool:
    """Traverses the account relationship graph for linked account discovery."""

    def get_linked_accounts(
        self, account_id: str, max_depth: int = 2
    ) -> dict[str, Any]:
        """
        BFS traversal starting from account_id up to max_depth hops.
        Returns all reachable accounts with their relationship paths.
        """
        visited: dict[str, dict] = {}   # account → discovery info
        queue: deque[tuple[str, int, list]] = deque()
        queue.append((account_id, 0, []))

        while queue:
            current, depth, path = queue.popleft()
            if current in visited or depth > max_depth:
                continue
            if current != account_id:
                visited[current] = {
                    "account_id": current,
                    "depth": depth,
                    "path": path,
                }
            if depth < max_depth:
                for neighbour in _ADJ.get(current, []):
                    nb_id = neighbour["account"]
                    if nb_id not in visited and nb_id != account_id:
                        new_path = path + [{
                            "from": current,
                            "to": nb_id,
                            "relationship": neighbour.get("relationship_type"),
                            "strength": neighbour.get("strength"),
                        }]
                        queue.append((nb_id, depth + 1, new_path))

        # Risk score: sum of strength weights across all direct neighbours
        direct_links = _ADJ.get(account_id, [])
        risk_score = sum(
            _STRENGTH_WEIGHT.get(lnk.get("strength", "LOW"), 1)
            for lnk in direct_links
        )

        return {
            "account_id": account_id,
            "linked_account_count": len(visited),
            "linked_accounts": list(visited.values()),
            "direct_link_count": len(direct_links),
            "network_risk_score": risk_score,
            "high_risk_links": [
                lnk for lnk in direct_links if lnk.get("strength") == "HIGH"
            ],
        }

    def get_direct_links(self, account_id: str) -> list[dict]:
        """Return all direct (depth-1) links from an account."""
        return _ADJ.get(account_id, [])

    def check_known_networks(self, account_id: str) -> dict[str, Any]:
        """
        Check whether this account appears in any known mule network records.
        Matches against both coordinator and member account lists.
        """
        matches = []
        for net in _KNOWN_NETWORKS:
            members_str = net.get("member_accounts", "")
            members = [m.strip() for m in members_str.split(";")]
            coordinator = net.get("coordinator_account", "")
            if account_id in members or account_id == coordinator:
                matches.append({
                    "network_id": net.get("network_id"),
                    "network_type": net.get("network_type"),
                    "status": net.get("status"),
                    "role": "coordinator" if account_id == coordinator else "member",
                    "estimated_total_hkd": net.get("estimated_total_hkd"),
                    "first_detected": net.get("first_detected"),
                })
        return {
            "account_id": account_id,
            "in_known_network": bool(matches),
            "networks": matches,
        }

    def get_network_summary(self, account_id: str) -> dict[str, Any]:
        """
        Combined summary: linked accounts + known network membership.
        """
        linked = self.get_linked_accounts(account_id)
        known = self.check_known_networks(account_id)

        # Classify overall network risk
        if known["in_known_network"] or linked["network_risk_score"] >= 6:
            network_risk = "HIGH"
        elif linked["network_risk_score"] >= 3:
            network_risk = "MEDIUM"
        else:
            network_risk = "LOW"

        return {
            "account_id": account_id,
            "network_risk": network_risk,
            "linked_account_count": linked["linked_account_count"],
            "direct_link_count": linked["direct_link_count"],
            "network_risk_score": linked["network_risk_score"],
            "known_network_member": known["in_known_network"],
            "known_networks": known["networks"],
            "linked_accounts": linked["linked_accounts"],
            "high_risk_links": linked["high_risk_links"],
        }
