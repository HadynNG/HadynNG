"""
Transaction Tool — transaction history and fund-flow analysis.

Loads transaction data from storage/seeds/transaction_history.md.
Provides structuring detection, velocity analysis, and fund-flow summaries
for mule account investigation.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from tools.md_loader import load, parse_sections, parse_table

# ── Module-level cache ────────────────────────────────────────────────────────

def _load_transactions() -> list[dict]:
    sections = parse_sections(load("transaction_history.md"))
    return sections.get("Transactions", [])


_TX_DATA: list[dict] = _load_transactions()

# Reporting threshold (HKD) — transactions just below this trigger structuring check
_STRUCTURING_THRESHOLD = 50_000


class TransactionTool:
    """Queries transaction history for mule investigation checkpoints."""

    def get_transactions(self, account_id: str, limit: int = 50) -> dict[str, Any]:
        """Return recent transactions for an account, most recent first."""
        rows = [r for r in _TX_DATA if r.get("account_id") == account_id]
        rows.sort(key=lambda r: r.get("tx_date", ""), reverse=True)
        rows = rows[:limit]
        return {
            "account_id": account_id,
            "found": bool(rows),
            "count": len(rows),
            "transactions": rows,
        }

    def get_counterparties(self, account_id: str) -> dict[str, Any]:
        """Return all unique counterparties and their transaction counts."""
        rows = [r for r in _TX_DATA if r.get("account_id") == account_id]
        parties: dict[str, dict] = {}
        for r in rows:
            cp_id = r.get("counterparty_id", "UNKNOWN")
            cp_name = r.get("counterparty_name", "UNKNOWN")
            if cp_id not in parties:
                parties[cp_id] = {
                    "counterparty_id": cp_id,
                    "counterparty_name": cp_name,
                    "tx_count": 0,
                    "total_credit": 0.0,
                    "total_debit": 0.0,
                    "flags": set(),
                }
            entry = parties[cp_id]
            entry["tx_count"] += 1
            amt = float(r.get("amount", 0))
            if r.get("tx_type") == "credit":
                entry["total_credit"] += amt
            else:
                entry["total_debit"] += amt
            flag = r.get("flag", "NORMAL")
            if flag != "NORMAL":
                entry["flags"].add(flag)

        # Convert sets to sorted lists for JSON serialisability
        result = []
        for p in parties.values():
            p["flags"] = sorted(p["flags"])
            result.append(p)
        result.sort(key=lambda x: x["tx_count"], reverse=True)
        return {"account_id": account_id, "counterparties": result}

    def detect_structuring(self, account_id: str) -> dict[str, Any]:
        """
        Detect structuring: transactions deliberately kept just below
        the HKD 50,000 reporting threshold.
        """
        rows = [r for r in _TX_DATA if r.get("account_id") == account_id]
        threshold_low = _STRUCTURING_THRESHOLD * 0.85  # 85–99% of threshold
        structured = [
            r for r in rows
            if threshold_low <= float(r.get("amount", 0)) < _STRUCTURING_THRESHOLD
        ]
        return {
            "account_id": account_id,
            "structuring_threshold": _STRUCTURING_THRESHOLD,
            "suspected_structured_count": len(structured),
            "structuring_detected": len(structured) >= 3,
            "suspected_transactions": structured,
        }

    def get_velocity(self, account_id: str) -> dict[str, Any]:
        """
        Compute transaction velocity stats: total credits, debits, net flow,
        suspicious flag ratio, and credit-to-debit turnaround speed indicators.
        """
        rows = [r for r in _TX_DATA if r.get("account_id") == account_id]
        if not rows:
            return {"account_id": account_id, "found": False}

        total_credit = sum(float(r["amount"]) for r in rows if r.get("tx_type") == "credit")
        total_debit = sum(float(r["amount"]) for r in rows if r.get("tx_type") == "debit")
        suspicious_count = sum(1 for r in rows if r.get("flag") not in ("NORMAL", ""))
        tx_count = len(rows)

        # Group by date to find same-day credit→debit pairs (rapid turnaround)
        by_date: dict[str, list] = defaultdict(list)
        for r in rows:
            by_date[r.get("tx_date", "")].append(r)

        same_day_pairs = 0
        for date_rows in by_date.values():
            has_credit = any(r["tx_type"] == "credit" for r in date_rows)
            has_debit = any(r["tx_type"] == "debit" for r in date_rows)
            if has_credit and has_debit:
                same_day_pairs += 1

        passthrough_ratio = round(min(total_debit, total_credit) / max(total_credit, 1), 4)

        return {
            "account_id": account_id,
            "found": True,
            "tx_count": tx_count,
            "total_credit_hkd": round(total_credit, 2),
            "total_debit_hkd": round(total_debit, 2),
            "net_flow_hkd": round(total_credit - total_debit, 2),
            "suspicious_flag_ratio": round(suspicious_count / max(tx_count, 1), 4),
            "same_day_credit_debit_days": same_day_pairs,
            "passthrough_ratio": passthrough_ratio,
            "high_passthrough": passthrough_ratio >= 0.90,
        }

    def get_fund_flow_summary(self, account_ids: list[str]) -> dict[str, Any]:
        """
        Summarise fund flow across a set of accounts (primary + linked).
        Identifies common counterparties and total exposure.
        """
        all_rows = [r for r in _TX_DATA if r.get("account_id") in account_ids]
        total_credit = sum(float(r["amount"]) for r in all_rows if r.get("tx_type") == "credit")
        total_debit = sum(float(r["amount"]) for r in all_rows if r.get("tx_type") == "debit")

        # External counterparties (not in the account set)
        external_in: set[str] = set()
        external_out: set[str] = set()
        for r in all_rows:
            cp = r.get("counterparty_id", "")
            if cp not in account_ids:
                if r["tx_type"] == "credit":
                    external_in.add(cp)
                else:
                    external_out.add(cp)

        return {
            "accounts_analysed": account_ids,
            "total_tx_count": len(all_rows),
            "total_credit_hkd": round(total_credit, 2),
            "total_debit_hkd": round(total_debit, 2),
            "net_exposure_hkd": round(total_credit, 2),
            "external_fund_sources": sorted(external_in),
            "external_fund_destinations": sorted(external_out),
            "suspicious_tx_count": sum(1 for r in all_rows if r.get("flag") not in ("NORMAL", "")),
        }
