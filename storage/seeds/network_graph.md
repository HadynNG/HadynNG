# Account Network Graph

Account relationship data used by the Network Graph Tool for linked account discovery.
Relationship types: shared_device / shared_ip / same_beneficiary / co_signatory / referral / same_address / common_counterparty

## Account Links

| link_id | source_account | target_account | relationship_type | strength | discovered_date | notes |
|---------|---------------|----------------|------------------|----------|----------------|-------|
| LNK001 | M001 | M002 | shared_device | HIGH | 2025-01-05 | Same mobile device fingerprint used to access both accounts |
| LNK002 | M001 | EXT-NET-06 | same_beneficiary | HIGH | 2025-01-17 | M001 repeatedly sends to same overseas beneficiary as EXT-NET-06 |
| LNK003 | M001 | EXT-VICTIM-01 | common_counterparty | MEDIUM | 2025-01-10 | Funds originate from same scam victim pool |
| LNK004 | M001 | EXT-VICTIM-02 | common_counterparty | MEDIUM | 2025-02-03 | Funds originate from same scam victim pool |
| LNK005 | M002 | M002-ACC2 | co_signatory | HIGH | 2024-07-20 | Linda Wong is sole signatory on both accounts |
| LNK006 | M002 | EXT-NET-02 | shared_ip | HIGH | 2024-08-05 | Same IP address during same session as ACCOMPLICE WONG |
| LNK007 | M002 | EXT-NET-03 | shared_ip | HIGH | 2024-08-05 | Same IP address cluster as ACCOMPLICE CHAN |
| LNK008 | M002 | EXT-NET-04 | same_beneficiary | HIGH | 2024-08-05 | Repeated transfers to CRYPTO EXCHANGE X |
| LNK009 | M002 | EXT-NET-01 | same_beneficiary | HIGH | 2024-08-19 | MULE NETWORK COORDINATOR is primary funder |
| LNK010 | M002 | M001 | shared_device | HIGH | 2025-01-05 | Bidirectional — same device as M001 |
| LNK011 | EXT-NET-01 | EXT-NET-02 | referral | MEDIUM | 2024-06-01 | EXT-NET-02 recruited via EXT-NET-01 according to intelligence |
| LNK012 | EXT-NET-01 | EXT-NET-03 | referral | MEDIUM | 2024-06-01 | EXT-NET-03 recruited via EXT-NET-01 according to intelligence |
| LNK013 | M003 | CLIENT-A | same_beneficiary | LOW | 2024-10-01 | Legitimate repeat client relationship |
| LNK014 | M003 | CLIENT-B | same_beneficiary | LOW | 2024-10-15 | Legitimate client — registered company |

## Known Mule Networks

| network_id | coordinator_account | member_accounts | network_type | estimated_total_hkd | status | first_detected |
|-----------|--------------------|-----------------|--------------|--------------------|--------|----------------|
| NET-001 | EXT-NET-01 | M001; M002; EXT-NET-02; EXT-NET-03; EXT-NET-06 | Romance Scam / Job Scam Layering | 2800000 | ACTIVE | 2024-06-15 |
| NET-002 | EXT-NET-05 | M002 | Investment Scam Layering | 850000 | UNDER_INVESTIGATION | 2024-09-02 |
