"""
Fraud Intelligence Tool — scam typology matching and mule account intelligence.

Loads data from storage/seeds/fraud_intelligence.md.
Provides account-level intelligence lookups, typology matching, and
recruitment tactic pattern analysis for mule investigation.
"""

from typing import Any

from tools.md_loader import load, parse_sections

# ── Module-level cache ────────────────────────────────────────────────────────

def _load_all() -> dict[str, list[dict]]:
    return parse_sections(load("fraud_intelligence.md"))


_DATA = _load_all()
_KNOWN_MULE_ACCOUNTS: list[dict] = _DATA.get("Known Mule Accounts", [])
_TYPOLOGIES: list[dict] = _DATA.get("Scam Typologies", [])
_TACTICS: list[dict] = _DATA.get("Recruitment Tactics", [])
_ADVERSE_INTEL: list[dict] = _DATA.get("Adverse Intelligence", [])


class FraudIntelligenceTool:
    """Queries fraud intelligence database for mule investigation."""

    def check_account(self, account_id: str) -> dict[str, Any]:
        """
        Check if an account appears in the known mule accounts register.
        Returns status, mule_type, and associated network.
        """
        matches = [
            r for r in _KNOWN_MULE_ACCOUNTS
            if r.get("account_id") == account_id
        ]
        if not matches:
            return {
                "account_id": account_id,
                "known_mule": False,
            }
        m = matches[0]
        return {
            "account_id": account_id,
            "known_mule": True,
            "mule_type": m.get("mule_type"),
            "status": m.get("status"),
            "network_id": m.get("network_id"),
            "confirmed_date": m.get("confirmed_date"),
            "total_laundered_hkd": m.get("total_laundered_hkd"),
            "source": m.get("source"),
        }

    def get_adverse_intelligence(self, account_id: str) -> dict[str, Any]:
        """Return all adverse intelligence records for an account."""
        matches = [
            r for r in _ADVERSE_INTEL
            if r.get("account_id") == account_id
        ]
        high_severity = [r for r in matches if r.get("severity") == "HIGH"]
        return {
            "account_id": account_id,
            "intel_count": len(matches),
            "has_high_severity": bool(high_severity),
            "records": matches,
        }

    def match_typology(self, indicators: list[str]) -> dict[str, Any]:
        """
        Match a list of observed indicators against known scam typologies.
        Returns ranked matches with confidence scores.
        """
        indicators_lower = {ind.lower() for ind in indicators}
        scored: list[dict] = []

        for typo in _TYPOLOGIES:
            red_flags_raw = typo.get("red_flags", "")
            red_flags = [f.strip().lower() for f in red_flags_raw.split(";") if f.strip()]
            if not red_flags:
                continue
            # Simple token-overlap confidence
            matches = sum(
                1 for flag in red_flags
                if any(token in flag for token in indicators_lower)
                   or any(token in ind for ind in indicators_lower for token in flag.split())
            )
            if matches > 0:
                confidence = round(matches / len(red_flags), 3)
                scored.append({
                    "typology_id": typo.get("typology_id"),
                    "name": typo.get("name"),
                    "description": typo.get("description"),
                    "mule_role": typo.get("mule_role"),
                    "match_count": matches,
                    "confidence": confidence,
                })

        scored.sort(key=lambda x: x["confidence"], reverse=True)
        top_match = scored[0] if scored else None
        return {
            "indicators_checked": indicators,
            "matches": scored[:3],
            "top_typology": top_match,
            "typology_matched": top_match is not None and top_match["confidence"] >= 0.3,
        }

    def get_recruitment_indicators(self, account_id: str) -> dict[str, Any]:
        """
        Return known recruitment tactics relevant to this account.
        Matches tactics based on adverse intelligence records.
        """
        intel = self.get_adverse_intelligence(account_id)
        mule_info = self.check_account(account_id)

        detected_tactics: list[dict] = []

        # Use intel records to infer tactic
        for rec in intel["records"]:
            desc = rec.get("description", "").lower()
            for tactic in _TACTICS:
                tact_name = tactic.get("name", "").lower()
                if any(word in desc for word in tact_name.split()):
                    detected_tactics.append({
                        "tactic_id": tactic.get("tactic_id"),
                        "name": tactic.get("name"),
                        "platform": tactic.get("platform"),
                        "red_flags": tactic.get("red_flags"),
                        "source_intel": rec.get("intel_id"),
                    })

        # For known mule accounts add default professional tactic
        if mule_info.get("known_mule") and mule_info.get("mule_type") == "PROFESSIONAL":
            detected_tactics.append({
                "tactic_id": "TACT-003",
                "name": "Dark Web Account Purchase / Active Participation",
                "platform": "Criminal network",
                "red_flags": "Deliberate account management; multiple accounts; structured splits",
                "source_intel": "mule_register",
            })

        return {
            "account_id": account_id,
            "tactic_count": len(detected_tactics),
            "tactics_detected": detected_tactics,
            "recruitment_confirmed": bool(detected_tactics),
        }

    def get_all_typologies(self) -> list[dict]:
        """Return all scam typologies for reference."""
        return _TYPOLOGIES

    def get_all_tactics(self) -> list[dict]:
        """Return all known recruitment tactics."""
        return _TACTICS
