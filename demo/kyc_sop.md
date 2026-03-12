# KYC / AML Name Screening — Standard Operating Procedure (SOP)
## Reference: HKMA AML/CFT Guideline, AMLO (Cap. 615), SFC AML Circular

---

## 1. When to Trigger KYC Screening

KYC name screening **must** be initiated under any of the following conditions:

| Trigger | Event Type | Examples |
|---|---|---|
| New customer onboarding | `onboarding` | Opening an account, applying for a loan, establishing a business relationship |
| Suspicious transaction flagged | `transaction_alert` | Large cash deposits, cross-border wires, structuring patterns |
| Scheduled periodic re-review | `periodic_review` | Annual (LOW risk), semi-annual (MEDIUM), quarterly (HIGH) |
| Customer record update | `customer_update` | Change of name, nationality, address, occupation, UBO change |
| Ad-hoc compliance request | `onboarding` | Compliance officer or RM requests a fresh check based on new information |

---

## 2. Intent Recognition Guidelines

A request **should** trigger the KYC pipeline if it contains any of the following:
- Explicit intent: *screen*, *check*, *verify*, *KYC*, *AML*, *sanctions*, *PEP*, *due diligence*, *onboard*
- Risk-related language: *risk assessment*, *background check*, *identity check*, *compliance review*
- Customer-related action: *new client*, *new customer*, *review [name]*, *approve [name]*, *open account for*

A request **should NOT** trigger the pipeline if it is:
- A general enquiry (e.g. product information, branch hours)
- An IT or operational support request
- An internal policy question with no named subject
- A complaint or grievance unrelated to customer screening

---

## 3. Information to Extract from Request

When a KYC request is identified, extract:
- **Customer name** — the individual or entity to be screened (required)
- **Event type** — one of: `onboarding`, `transaction_alert`, `periodic_review`, `customer_update`
- **Additional context** — any notes about risk concerns, transaction details, or special circumstances

---

## 4. Escalation Thresholds

| Condition | Action |
|---|---|
| Confirmed sanctions list match (TRUE_POSITIVE, SANCTIONS list) | REJECT — terminate relationship |
| PEP match or adverse media with unresolved risk | ESCALATE_TO_MLRO — human review |
| No hits, risk LOW, identity verified | APPROVE |
| No hits, risk MEDIUM, needs monitoring | APPROVE_WITH_CONDITIONS |

---

## 5. Out of Scope

This pipeline handles name screening only. It does NOT:
- Execute financial transactions
- Provide legal advice
- Handle general customer service enquiries
- Perform corporate restructuring analysis
