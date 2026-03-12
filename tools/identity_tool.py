"""
Mock Identity Verification Tool — simulates Jumio/Onfido-style API.
Verifies documents against government registries.
"""
from datetime import datetime
import random


# Simulated verification outcomes
_VERIFICATION_RESULTS = {
    "A123456(7)": {
        "status": "VERIFIED",
        "id_type": "HKID",
        "id_number": "A123456(7)",
        "name_match": True,
        "dob_match": True,
        "document_authentic": True,
        "registry_source": "HKSAR Immigration Department",
        "verification_confidence": 0.98,
    },
    "PH987654321": {
        "status": "VERIFIED",
        "id_type": "PASSPORT",
        "id_number": "PH987654321",
        "name_match": True,
        "dob_match": True,
        "document_authentic": True,
        "registry_source": "Philippine Bureau of Immigration",
        "verification_confidence": 0.95,
    },
    "RU20190045678": {
        "status": "VERIFIED",
        "id_type": "PASSPORT",
        "id_number": "RU20190045678",
        "name_match": True,
        "dob_match": True,
        "document_authentic": True,
        "registry_source": "Russian Federal Migration Service",
        "verification_confidence": 0.91,
        "notes": "Document verified but jurisdiction flagged",
    },
    "B654321(2)": {
        "status": "VERIFIED",
        "id_type": "HKID",
        "id_number": "B654321(2)",
        "name_match": True,
        "dob_match": True,
        "document_authentic": True,
        "registry_source": "HKSAR Immigration Department",
        "verification_confidence": 0.97,
    },
}


class IdentityVerificationTool:
    """Mock identity verification against government registries."""

    def verify_identity(self, id_number: str, full_name: str, dob: str) -> dict:
        if id_number in _VERIFICATION_RESULTS:
            result = dict(_VERIFICATION_RESULTS[id_number])
        elif id_number.upper().startswith("DEMO-") or not id_number:
            # Demo / user-entered customer — simulate a standard verification pass
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
            # Unknown real-world ID — simulate a generic verification
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
        """For corporate entities — check ownership structure."""
        return {
            "entity": entity_name,
            "registry_checked": "HK Companies Registry",
            "ownership_verified": True,
            "beneficial_owners_above_10pct": [],
            "verified_at": datetime.utcnow().isoformat() + "Z",
        }
