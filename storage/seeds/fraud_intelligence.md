# Fraud Intelligence Database

Intelligence records on known mule recruitment tactics, scam typologies, and flagged accounts.
Used by the Fraud Intelligence Tool for mule account investigation.

## Known Mule Accounts

| account_id | mule_type | status | network_id | confirmed_date | total_laundered_hkd | source |
|-----------|-----------|--------|-----------|----------------|--------------------|----|
| M002 | PROFESSIONAL | CONFIRMED | NET-001 | 2025-02-10 | 300000 | Internal SAR + Police referral |
| M002-ACC2 | PROFESSIONAL | CONFIRMED | NET-001 | 2025-02-10 | 150000 | Internal investigation |
| EXT-NET-02 | PROFESSIONAL | CONFIRMED | NET-001 | 2024-12-01 | 180000 | Inter-bank intelligence sharing |
| EXT-NET-03 | PROFESSIONAL | CONFIRMED | NET-001 | 2024-12-01 | 160000 | Inter-bank intelligence sharing |
| EXT-NET-06 | WITTING | SUSPECTED | NET-001 | 2025-01-20 | 95000 | Suspicious transaction report |

## Scam Typologies

| typology_id | name | description | victim_profile | mule_role | red_flags |
|------------|------|-------------|----------------|-----------|-----------|
| TYPO-001 | Job Scam Mule Recruitment | Fraudsters pose as employers offering work-from-home "money transfer agent" jobs; mule receives funds into personal account and forwards minus a commission | Young adults aged 18-30; low-income; social media users | Unwitting or witting conduit | Account opened recently; no prior employment in finance; receives from unknown entities then immediately forwards; high credit-debit velocity; references like "salary" or "commission" for suspicious transfers |
| TYPO-002 | Romance Scam Fund Layering | Romance scam proceeds are layered through recruited mule accounts before being sent overseas or converted to crypto | Romantically isolated individuals; excessive trust in online relationships | Semi-witting; deceived into believing funds are legitimate | Claims to be helping a romantic partner; reluctant to explain fund source; high-value inbound followed by near-identical outbound |
| TYPO-003 | Professional Money Mule Network | Organised criminal network operates multiple accounts simultaneously; funds split and recombined across layers of mule accounts to obscure source | N/A — accounts are purpose-opened | Witting; paid commission | Multiple accounts under same individual; shared devices/IPs across accounts; structured splitting below reporting thresholds; crypto conversion at terminal layer |
| TYPO-004 | Investment Scam Throughput | Victims transfer funds believing they are investing; proceeds passed through mule accounts before being aggregated by criminal coordinator | Elderly; retirement savings; high net worth | Witting or coerced | Large single credits from individuals (not businesses); immediate forwarding; victim complaints logged against counterparty |

## Recruitment Tactics

| tactic_id | name | platform | description | red_flags |
|----------|------|----------|-------------|-----------|
| TACT-001 | Social Media Job Ad | Facebook; Instagram; Telegram | Ads promise HKD 3,000-10,000 per week for "part-time bank account management work"; victim provides account credentials or receives/forwards funds | Account holder cannot explain employer identity; no contract; paid in cash commission |
| TACT-002 | WhatsApp Romance | WhatsApp; WeChat | Criminal builds romantic relationship over weeks; eventually asks victim to receive money "temporarily" | Romantic partner never met in person; victim becomes defensive when questioned |
| TACT-003 | Dark Web Account Purchase | Dark web forums | Account holder sells account access directly for one-time payment; account then used by criminal | Account shows sudden behavioural change; holder claims card/phone was stolen; IP geolocation inconsistency |
| TACT-004 | Coercion / Debt Trap | In-person; loan shark networks | Victim coerced into providing account access after defaulting on loan | Account holder shows signs of distress; sudden large transactions after period of inactivity |

## Adverse Intelligence

| intel_id | account_id | intel_type | description | date | source | severity |
|---------|-----------|-----------|-------------|------|--------|---------|
| INT-001 | M002 | Police Referral | HK Police Commercial Crime Bureau referral — account associated with romance scam case HK-2024-CCC-8821 | 2024-11-15 | HKPF CCC | HIGH |
| INT-002 | EXT-NET-01 | Inter-bank STR | STR filed by Bank of East Asia referencing EXT-NET-01 as mule network coordinator | 2024-10-28 | BEA AML | HIGH |
| INT-003 | M001 | Victim Complaint | Victim complaint C-2025-0112: funds transferred to M001 in romance scam — victim unaware account was mule | 2025-01-18 | HKPF | MEDIUM |
| INT-004 | EXT-NET-04 | Exchange Flag | Crypto exchange flagged EXT-NET-04 as high-volume cash-out account linked to scam proceeds | 2024-09-10 | Exchange Intelligence | MEDIUM |
