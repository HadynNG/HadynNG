"""
Mock CRM Tool — simulates internal customer database queries.
In production this would call a real CRM/database API.

Supports dynamic customer registration for user-entered demo customers.
"""
from datetime import datetime


# Runtime-registered customers (populated by run_demo.py for user-entered cases)
_RUNTIME_CUSTOMERS: dict = {}

# Simulated CRM database
_CRM_DB = {
    "C001": {
        "customer_id": "C001",
        "full_name": "James Wong Wai-Man",
        "aliases": ["James Wong", "Wong Wai Man"],
        "date_of_birth": "1985-03-12",
        "nationality": "HKG",
        "id_type": "HKID",
        "id_number": "A123456(7)",
        "address": "Flat 12B, Tower 3, The Arch, 1 Austin Road West, Kowloon",
        "email": "james.wong@example.com",
        "phone": "+852 9123 4567",
        "customer_type": "individual",
        "occupation": "Software Engineer",
        "employer": "TechCorp HK Ltd",
        "account_opened": "2022-06-15",
        "jurisdiction": "HKG",
        "pep_self_declared": False,
        "existing_risk_rating": "LOW",
        "last_reviewed": "2024-01-10",
    },
    "C002": {
        "customer_id": "C002",
        "full_name": "Senator Marcus Delgado",
        "aliases": ["Marcus Delgado", "M. Delgado"],
        "date_of_birth": "1965-07-22",
        "nationality": "PHL",
        "id_type": "PASSPORT",
        "id_number": "PH987654321",
        "address": "88 Orchard Boulevard, Manila, Philippines",
        "email": "m.delgado@gov.ph",
        "phone": "+63 917 555 0199",
        "customer_type": "individual",
        "occupation": "Government Official",
        "employer": "Philippine Senate",
        "account_opened": "2023-11-01",
        "jurisdiction": "PHL",
        "pep_self_declared": True,
        "existing_risk_rating": "MEDIUM",
        "last_reviewed": "2023-11-15",
    },
    "C003": {
        "customer_id": "C003",
        "full_name": "Valeria Petrov",
        "aliases": ["V. Petrov", "Валерия Петров", "Valeria Mikhailovna Petrov"],
        "date_of_birth": "1978-11-03",
        "nationality": "RUS",
        "id_type": "PASSPORT",
        "id_number": "RU20190045678",
        "address": "Tverskaya Street 14, Moscow, Russia",
        "email": "v.petrov@energycorp.ru",
        "phone": "+7 495 123 4567",
        "customer_type": "individual",
        "occupation": "Energy Sector Executive",
        "employer": "Energotek PJSC",
        "account_opened": "2024-02-20",
        "jurisdiction": "RUS",
        "pep_self_declared": False,
        "existing_risk_rating": "HIGH",
        "last_reviewed": "2024-02-20",
    },
}

# High-risk jurisdictions per FATF
HIGH_RISK_JURISDICTIONS = {
    "RUS", "IRN", "PRK", "SYR", "MMR", "YEM", "SDN", "LBY", "SOM", "AFG"
}
MEDIUM_RISK_JURISDICTIONS = {
    "PHL", "PAK", "TUN", "MAR", "UKR", "KAZ", "VNM"
}


class CRMTool:
    """Mock CRM tool for customer data retrieval."""

    @staticmethod
    def register_customer(customer_data: dict) -> str:
        """
        Register a new customer at runtime (for user-entered demo cases).
        Returns the assigned customer_id.
        """
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
        # Runtime customers take priority (user-entered demo cases)
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
            level = "HIGH"
            reason = "FATF high-risk or sanctioned jurisdiction"
        elif jurisdiction_code in MEDIUM_RISK_JURISDICTIONS:
            level = "MEDIUM"
            reason = "FATF monitored or elevated-risk jurisdiction"
        else:
            level = "LOW"
            reason = "Standard jurisdiction"
        return {
            "jurisdiction": jurisdiction_code,
            "risk_level": level,
            "reason": reason,
        }

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
