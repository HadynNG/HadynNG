"""
Mock Sanctions Screening Tool — simulates Dow Jones / World-Check style API.
Screens against UN, OFAC, EU, HKMA sanctions lists and PEP databases.
"""
from datetime import datetime


# Simulated sanctions / PEP database
_SANCTIONS_DB = [
    {
        "list": "UN Security Council",
        "entry_id": "UN-2024-RUS-00847",
        "full_name": "Valeria Mikhailovna Petrov",
        "aliases": ["V. Petrov", "Валерия Петров"],
        "date_of_birth": "1978-11-03",
        "nationality": "RUS",
        "designation_reason": "Involved in sanctions-evading energy transactions",
        "designation_date": "2024-01-15",
        "type": "SANCTIONS",
    },
    {
        "list": "OFAC SDN",
        "entry_id": "OFAC-SDN-2023-009312",
        "full_name": "Valeria Petrov",
        "aliases": ["Valeria M. Petrov"],
        "date_of_birth": "1978-11-03",
        "nationality": "RUS",
        "designation_reason": "Energy sector sanctions — E.O. 14024",
        "designation_date": "2023-09-10",
        "type": "SANCTIONS",
    },
]

_PEP_DB = [
    {
        "list": "Global PEP Database",
        "entry_id": "PEP-PHL-2021-0553",
        "full_name": "Senator Marcus Delgado",
        "aliases": ["Marcus Delgado", "M. Delgado"],
        "date_of_birth": "1965-07-22",
        "nationality": "PHL",
        "role": "Philippine Senate — Senator, Committee on Finance",
        "pep_tier": 1,
        "active": True,
        "type": "PEP",
    },
]

_ADVERSE_MEDIA_DB = [
    {
        "subject": "Valeria Petrov",
        "headline": "Russian energy exec Valeria Petrov linked to sanction-busting network",
        "source": "Reuters",
        "date": "2024-02-01",
        "url": "https://reuters.com/mock/2024-petrov",
        "category": "SANCTIONS_EVASION",
    },
    {
        "subject": "Marcus Delgado",
        "headline": "Philippine senator Delgado under scrutiny for undisclosed assets",
        "source": "Philippine Inquirer",
        "date": "2023-12-15",
        "url": "https://inquirer.net/mock/delgado-2023",
        "category": "CORRUPTION",
    },
]


def _name_similarity(query: str, target: str) -> float:
    """Simple token overlap similarity."""
    q_tokens = set(query.lower().split())
    t_tokens = set(target.lower().split())
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = q_tokens & t_tokens
    return len(overlap) / max(len(q_tokens), len(t_tokens))


class SanctionsScreeningTool:
    """Mock sanctions & PEP screening tool."""

    def screen(self, queries: list[str], customer_data: dict) -> dict:
        """
        Run screening against all lists.

        Args:
            queries: List of name variants to screen.
            customer_data: Full customer record for additional matching.

        Returns:
            dict with hits, confidence scores, and raw alerts.
        """
        hits = []
        dob = customer_data.get("date_of_birth", "")
        nationality = customer_data.get("nationality", "")

        for entry in _SANCTIONS_DB + _PEP_DB:
            for query in queries:
                score = _name_similarity(query, entry["full_name"])
                # Also check aliases
                for alias in entry.get("aliases", []):
                    alias_score = _name_similarity(query, alias)
                    score = max(score, alias_score)

                if score >= 0.5:
                    # Boost confidence if DOB or nationality also match
                    confidence = score
                    identifiers_matched = []
                    if dob and entry.get("date_of_birth") == dob:
                        confidence = min(1.0, confidence + 0.25)
                        identifiers_matched.append("DOB")
                    if nationality and entry.get("nationality") == nationality:
                        confidence = min(1.0, confidence + 0.15)
                        identifiers_matched.append("Nationality")

                    hits.append({
                        "matched_query": query,
                        "list": entry["list"],
                        "entry_id": entry["entry_id"],
                        "matched_name": entry["full_name"],
                        "match_type": entry["type"],
                        "name_similarity": round(score, 3),
                        "overall_confidence": round(confidence, 3),
                        "identifiers_matched": identifiers_matched,
                        "entry_details": entry,
                    })

        # Deduplicate by entry_id, keeping highest confidence
        seen = {}
        for h in hits:
            eid = h["entry_id"]
            if eid not in seen or h["overall_confidence"] > seen[eid]["overall_confidence"]:
                seen[eid] = h
        deduped_hits = list(seen.values())

        return {
            "screened_at": datetime.utcnow().isoformat() + "Z",
            "queries_used": queries,
            "total_hits": len(deduped_hits),
            "hits": sorted(deduped_hits, key=lambda x: x["overall_confidence"], reverse=True),
            "lists_checked": ["UN Security Council", "OFAC SDN", "EU Consolidated", "HKMA", "Global PEP Database"],
            "database_last_updated": "2024-03-01T00:00:00Z",
        }

    def search_adverse_media(self, name: str) -> list[dict]:
        """Search adverse media for a given name."""
        results = []
        for article in _ADVERSE_MEDIA_DB:
            if _name_similarity(name, article["subject"]) >= 0.5:
                results.append(article)
        return results
