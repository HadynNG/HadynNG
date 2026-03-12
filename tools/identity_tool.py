"""
Identity Verification Tool — document verification against government registries.

Static data is loaded from:
  data/identity_registry.md  — pre-configured verification outcomes

Simulates Jumio / Onfido-style API.
Unknown IDs receive a simulated fallback result so the pipeline never halts
on a demo customer that was entered at runtime.
"""

from datetime import datetime

from tools.md_loader import load, parse_table


# ── Loader ────────────────────────────────────────────────────────────────────

def _load_verification_results() -> dict:
    rows = parse_table(load("identity_registry.md"))
    db = {}
    for row in rows:
        for bool_field in ("name_match", "dob_match", "document_authentic"):
            row[bool_field] = row.get(bool_field, "true").lower() == "true"
        row["verification_confidence"] = float(row.get("verification_confidence", "0.80"))
        # Drop empty notes so callers can use .get("notes") cleanly
        if not row.get("notes"):
            row.pop("notes", None)
        db[row["id_number"]] = row
    return db


# Load once at import time
_VERIFICATION_RESULTS = _load_verification_results()


# ── Tool class ────────────────────────────────────────────────────────────────

class IdentityVerificationTool:
    """Identity verification tool — reads from data/identity_registry.md."""

    def verify_identity(self, id_number: str, full_name: str, dob: str) -> dict:
        if id_number in _VERIFICATION_RESULTS:
            result = dict(_VERIFICATION_RESULTS[id_number])
        elif id_number.upper().startswith("DEMO-") or not id_number:
            # User-entered demo customer — simulate a standard pass
            result = {
                "status": "VERIFIED",
                "id_type": "DEMO",
                "id_number": id_number,
                "name_match": True,
                "dob_match": True,
                "document_authentic": True,
                "registry_source": "Demo Verification Service (simulated)",
                "verification_confidence": 0.85,
                "notes": "Simulated verification for demo customer",
            }
        else:
            # Unrecognised real-world ID — generic simulated pass
            result = {
                "status": "VERIFIED",
                "id_type": "UNKNOWN",
                "id_number": id_number,
                "name_match": True,
                "dob_match": True,
                "document_authentic": True,
                "registry_source": "International Document Registry (simulated)",
                "verification_confidence": 0.80,
                "notes": "Document accepted — manual review recommended for unrecognised ID format",
            }

        result["verified_name"] = full_name
        result["verified_dob"] = dob
        result["verified_at"] = datetime.utcnow().isoformat() + "Z"
        return result

    def verify_beneficial_owner_structure(self, entity_name: str) -> dict:
        """For corporate entities — check UBO structure."""
        return {
            "entity": entity_name,
            "registry_checked": "HK Companies Registry",
            "ownership_verified": True,
            "beneficial_owners_above_10pct": [],
            "verified_at": datetime.utcnow().isoformat() + "Z",
        }
