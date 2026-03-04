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
}


class IdentityVerificationTool:
    """Mock identity verification against government registries."""

    def verify_identity(self, id_number: str, full_name: str, dob: str) -> dict:
        if id_number in _VERIFICATION_RESULTS:
            result = dict(_VERIFICATION_RESULTS[id_number])
        else:
            # Unknown ID — simulate a generic verification
            result = {
                "status": "UNVERIFIED",
                "id_number": id_number,
                "name_match": False,
                "dob_match": False,
                "document_authentic": False,
                "registry_source": "Unknown",
                "verification_confidence": 0.0,
                "notes": "ID not found in any connected registry",
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
