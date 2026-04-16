# Agent Skills Reference

## DataCollectionAgent
- Classify trigger events (onboarding, transaction_alert, periodic_review, customer_update)
- Retrieve customer profiles from CRM
- Verify identity documents (HKID, passport) against government registries
- Assess jurisdiction risk using FATF classifications

## RiskAssessmentAgent
- Calculate risk scores using rule-based factors
- Generate professional risk narratives via LLM
- Identify high-risk occupations and jurisdictions
- Apply risk thresholds: HIGH (>=50), MEDIUM (>=20), LOW (<20)

## AereveScreeningAgent
- Generate name variants (accent normalisation, reversals, initials)
- Screen against sanctions lists (UN, OFAC, EU, HKMA)
- Screen against PEP databases
- Search adverse media for matching articles
- Apply confidence boosting (DOB +0.25, nationality +0.15)

## AlertReviewAgent
- Triage alerts with auto-dismiss for low-confidence hits (<0.55)
- Investigate matches using LLM analysis (TRUE_POSITIVE vs FALSE_POSITIVE)
- Generate Enhanced Due Diligence (EDD) reports
- Assess source of wealth, business relationships, ongoing monitoring needs

## DecisionAgent
- Make final compliance decisions (APPROVE, APPROVE_WITH_CONDITIONS, ESCALATE_TO_MLRO, REJECT)
- Apply rule-based anchoring with LLM reasoning overlay
- Generate MLRO escalation dossiers
- Prepare STR templates for JFIU submission

## DocumentationAgent
- Write AMLO-compliant audit trails (5-year retention)
- Generate customer notifications tailored to decision outcome
- Generate internal team notifications
- Create structured audit log JSON files
