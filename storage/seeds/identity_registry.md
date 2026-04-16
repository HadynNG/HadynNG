# Identity Verification Registry

Simulates Jumio / Onfido document verification outcomes.
Used by the Data Collection Agent (Step 1.3).
Leave the `notes` cell empty if not applicable.

| id_number | status | id_type | name_match | dob_match | document_authentic | registry_source | verification_confidence | notes |
|-----------|--------|---------|------------|-----------|-------------------|-----------------|------------------------|-------|
| A123456(7) | VERIFIED | HKID | true | true | true | HKSAR Immigration Department | 0.98 | |
| PH987654321 | VERIFIED | PASSPORT | true | true | true | Philippine Bureau of Immigration | 0.95 | |
| RU20190045678 | VERIFIED | PASSPORT | true | true | true | Russian Federal Migration Service | 0.91 | Document verified but jurisdiction flagged |
| B654321(2) | VERIFIED | HKID | true | true | true | HKSAR Immigration Department | 0.97 | |
