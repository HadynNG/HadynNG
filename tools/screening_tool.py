"""
Sanctions Screening Tool — screens against sanctions lists, PEP databases,
and adverse media.

Static data is loaded from:
  data/sanctions_pep_list.md  — sanctions entries (## Sanctions) and PEP entries (## PEP)
  data/adverse_media.md       — adverse media articles

Simulates Dow Jones Factiva / LSEG World-Check style API.
"""

from datetime import datetime

from tools.md_loader import load, parse_table, parse_sections


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_sanctions_pep() -> tuple[list, list]:
    sections = parse_sections(load("sanctions_pep_list.md"))

    sanctions = []
    for row in sections.get("Sanctions", []):
        row["aliases"] = [a.strip() for a in row.get("aliases", "").split(";") if a.strip()]
        sanctions.append(row)

    pep = []
    for row in sections.get("PEP", []):
        row["aliases"] = [a.strip() for a in row.get("aliases", "").split(";") if a.strip()]
        row["pep_tier"] = int(row.get("pep_tier", "1"))
        row["active"] = row.get("active", "true").lower() == "true"
        pep.append(row)

    return sanctions, pep


def _load_adverse_media() -> list:
    return parse_table(load("adverse_media.md"))


# Load once at import time
_SANCTIONS_DB, _PEP_DB = _load_sanctions_pep()
_ADVERSE_MEDIA_DB = _load_adverse_media()


# ── Similarity helper ─────────────────────────────────────────────────────────

def _name_similarity(query: str, target: str) -> float:
    """Token overlap similarity (Jaccard on word tokens)."""
    q_tokens = set(query.lower().split())
    t_tokens = set(target.lower().split())
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = q_tokens & t_tokens
    return len(overlap) / max(len(q_tokens), len(t_tokens))


# ── Tool class ────────────────────────────────────────────────────────────────

class SanctionsScreeningTool:
    """Sanctions and PEP screening tool — reads from data/sanctions_pep_list.md
    and data/adverse_media.md."""

    def screen(self, queries: list[str], customer_data: dict) -> dict:
        """
        Screen name variants against all sanctions and PEP lists.

        Confidence is boosted when DOB (+0.25) or nationality (+0.15) also match.
        Hits are deduplicated by entry_id, keeping the highest-confidence match.
        """
        hits = []
        dob = customer_data.get("date_of_birth", "")
        nationality = customer_data.get("nationality", "")

        for entry in _SANCTIONS_DB + _PEP_DB:
            for query in queries:
                score = _name_similarity(query, entry["full_name"])
                for alias in entry.get("aliases", []):
                    score = max(score, _name_similarity(query, alias))

                if score >= 0.5:
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

        # Deduplicate by entry_id, keep highest confidence
        seen: dict = {}
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
            "lists_checked": [
                "UN Security Council", "OFAC SDN", "EU Consolidated",
                "HKMA", "Global PEP Database",
            ],
            "database_last_updated": "2024-03-01T00:00:00Z",
        }

    def search_adverse_media(self, name: str) -> list[dict]:
        """Return adverse media articles whose subject matches *name*."""
        return [
            article for article in _ADVERSE_MEDIA_DB
            if _name_similarity(name, article["subject"]) >= 0.5
        ]
