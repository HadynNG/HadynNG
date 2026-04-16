"""
CRM Tool — customer data and jurisdiction risk.

Static data is loaded from:
  data/crm_customers.md      — customer records
  data/jurisdiction_risk.md  — FATF jurisdiction risk classifications

In production this would call a real CRM / database API.
Supports dynamic customer registration for user-entered demo cases.
"""

from datetime import datetime

from tools.md_loader import load, parse_table


# ── Runtime customers (populated by run_demo.py for user-entered names) ───────
_RUNTIME_CUSTOMERS: dict = {}


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_crm_db() -> dict:
    rows = parse_table(load("crm_customers.md"))
    db = {}
    for row in rows:
        # Aliases: semicolon-separated → list
        row["aliases"] = [a.strip() for a in row.get("aliases", "").split(";") if a.strip()]
        # Boolean field
        row["pep_self_declared"] = row.get("pep_self_declared", "false").lower() == "true"
        db[row["customer_id"]] = row
    return db


def _load_jurisdiction_risk() -> tuple[set, set]:
    high: set[str] = set()
    medium: set[str] = set()
    current = None
    for line in load("jurisdiction_risk.md").splitlines():
        line = line.strip()
        if line == "## HIGH_RISK":
            current = "high"
        elif line == "## MEDIUM_RISK":
            current = "medium"
        elif current and line and not line.startswith("#"):
            codes = [c.strip() for c in line.split(",") if c.strip()]
            (high if current == "high" else medium).update(codes)
    return high, medium


# Load once at import time
_CRM_DB = _load_crm_db()
HIGH_RISK_JURISDICTIONS, MEDIUM_RISK_JURISDICTIONS = _load_jurisdiction_risk()


# ── Tool class ────────────────────────────────────────────────────────────────

class CRMTool:
    """CRM tool — reads from data/crm_customers.md and data/jurisdiction_risk.md."""

    @staticmethod
    def register_customer(customer_data: dict) -> str:
        """Register a runtime customer (user-entered demo cases)."""
        customer_id = customer_data.get("customer_id") or f"DEMO-{len(_RUNTIME_CUSTOMERS) + 1:03d}"
        _RUNTIME_CUSTOMERS[customer_id] = {
            **customer_data,
            "customer_id": customer_id,
            "account_opened": datetime.utcnow().strftime("%Y-%m-%d"),
            "last_reviewed": datetime.utcnow().strftime("%Y-%m-%d"),
            "existing_risk_rating": "UNKNOWN",
        }
        return customer_id

    def get_customer(self, customer_id: str) -> dict:
        # Runtime customers (user-entered) take priority
        if customer_id in _RUNTIME_CUSTOMERS:
            record = dict(_RUNTIME_CUSTOMERS[customer_id])
            record["found"] = True
            record["retrieved_at"] = datetime.utcnow().isoformat() + "Z"
            return record
        if customer_id not in _CRM_DB:
            return {"error": f"Customer {customer_id} not found", "found": False}
        record = dict(_CRM_DB[customer_id])
        record["found"] = True
        record["retrieved_at"] = datetime.utcnow().isoformat() + "Z"
        return record

    def get_jurisdiction_risk(self, jurisdiction_code: str) -> dict:
        if jurisdiction_code in HIGH_RISK_JURISDICTIONS:
            return {
                "jurisdiction": jurisdiction_code,
                "risk_level": "HIGH",
                "reason": "FATF high-risk or sanctioned jurisdiction",
            }
        if jurisdiction_code in MEDIUM_RISK_JURISDICTIONS:
            return {
                "jurisdiction": jurisdiction_code,
                "risk_level": "MEDIUM",
                "reason": "FATF monitored or elevated-risk jurisdiction",
            }
        return {
            "jurisdiction": jurisdiction_code,
            "risk_level": "LOW",
            "reason": "Standard jurisdiction",
        }

    @staticmethod
    def search_by_name(name: str) -> list[dict]:
        """Search all customers by name similarity (fuzzy + token overlap)."""
        from difflib import SequenceMatcher

        name_lower = name.strip().lower()
        results = []
        all_customers = {**_CRM_DB, **_RUNTIME_CUSTOMERS}

        for customer_id, record in all_customers.items():
            full_name = record.get("full_name", "").lower()
            aliases = [a.lower() for a in record.get("aliases", [])]

            seq_score = SequenceMatcher(None, name_lower, full_name).ratio()
            alias_score = max(
                (SequenceMatcher(None, name_lower, a).ratio() for a in aliases),
                default=0,
            )
            best_score = max(seq_score, alias_score)

            # Token-overlap boost for partial name matches
            query_tokens = set(name_lower.split())
            name_tokens = set(full_name.split())
            if query_tokens and name_tokens:
                token_overlap = len(query_tokens & name_tokens) / len(query_tokens | name_tokens)
                best_score = max(best_score, token_overlap)

            if best_score >= 0.45:
                results.append({**record, "_match_score": round(best_score, 3)})

        results.sort(key=lambda x: x["_match_score"], reverse=True)
        return results

    def check_existing_records(self, customer_id: str) -> dict:
        customer = self.get_customer(customer_id)
        if not customer.get("found"):
            return customer
        return {
            "found": True,
            "customer_id": customer_id,
            "has_existing_record": True,
            "previous_risk_rating": customer.get("existing_risk_rating"),
            "last_reviewed": customer.get("last_reviewed"),
        }
