"""
SAR Tool — Suspicious Activity Report drafting and reference management.

Generates SAR reference numbers, logs draft SARs to the audit trail,
and provides structure for the SAR Drafting Agent (Checkpoint 7).
"""

from datetime import datetime
from typing import Any


class SARTool:
    """Manages SAR reference generation and draft logging."""

    @staticmethod
    def generate_sar_reference(account_id: str) -> str:
        """Generate a unique SAR reference number."""
        date_part = datetime.utcnow().strftime("%Y%m%d")
        time_part = datetime.utcnow().strftime("%H%M%S")
        return f"SAR-MULE-{date_part}-{account_id}-{time_part}"

    @staticmethod
    def build_sar_structure(
        account_id: str,
        account_name: str,
        alert_type: str,
        mule_type: str,
        fraud_typology: str,
        total_exposure_hkd: float,
        linked_accounts: list[str],
        key_findings: list[str],
        analyst_recommendation: str,
        sar_narrative: str,
    ) -> dict[str, Any]:
        """
        Build a structured SAR dict ready for JFIU submission.
        Follows AMLO Cap. 615 and JFIU SAR form requirements.
        """
        sar_ref = SARTool.generate_sar_reference(account_id)
        return {
            "sar_reference": sar_ref,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "status": "DRAFT",
            "reporter": {
                "institution": "[INSTITUTION NAME — complete before submission]",
                "department": "AML Compliance",
                "contact": "[COMPLIANCE OFFICER NAME]",
            },
            "subject": {
                "account_id": account_id,
                "account_name": account_name,
                "mule_type": mule_type,
                "alert_type": alert_type,
            },
            "financial_summary": {
                "total_exposure_hkd": round(total_exposure_hkd, 2),
                "linked_accounts": linked_accounts,
            },
            "suspicion": {
                "fraud_typology": fraud_typology,
                "key_findings": key_findings,
                "narrative": sar_narrative,
            },
            "recommendation": analyst_recommendation,
            "filing_obligations": (
                "Under AMLO Cap. 615 s.25A, this report must be filed with JFIU within "
                "a reasonable time of forming the suspicion. Do not tip off the subject."
            ),
        }

    @staticmethod
    def get_filing_checklist() -> list[str]:
        """Return the pre-filing checklist items for analyst review."""
        return [
            "Verify all account details match CRM records",
            "Confirm total exposure figure against transaction analysis",
            "Ensure all linked accounts are listed",
            "Review mule type classification (witting / unwitting / professional)",
            "Confirm typology matches transaction pattern evidence",
            "Legal sign-off from MLRO obtained",
            "Do NOT disclose SAR filing to subject account holder (tipping-off prohibition)",
            "Retain all supporting evidence in case file",
            "Submit to JFIU via STR online portal",
        ]
