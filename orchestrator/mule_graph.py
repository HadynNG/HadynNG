"""
Mule Account Hunting Pipeline as a LangGraph StateGraph.

7-checkpoint workflow for detecting and investigating money mule accounts,
modelled after the compliance workflow:

  CP1: Mule Alert Validation
  CP2: Linked Account Discovery
  CP3: Fund Flow & Layering Analysis
  CP4: Recruitment Pattern Assessment  ← key LLM reasoning step (★)
  CP5: Scam/Fraud Intelligence Correlation
  CP6: Outreach & Source of Funds Review
  CP7: SAR Drafting & Analyst Review

State flow:

    mule_alert_validation
           ↓ (ALERT_CLOSED / ACCOUNT_NOT_FOUND)       ↓ (valid)
       [END — alert closed]               linked_account_discovery
                                                  ↓
                                        fund_flow_layering
                                                  ↓
                                        recruitment_pattern       ★
                                                  ↓
                                        scam_fraud_correlation
                                                  ↓
                                        outreach_source_of_funds
                                                  ↓
                                        sar_drafting  ──→ END

Usage — streaming (WebSocket / timeline updates):
    from orchestrator.mule_graph import build_mule_graph, MuleState

    graph = build_mule_graph(model="qwen3.5:9b", ollama_host="http://localhost:11434")
    for chunk in graph.stream(initial_state):
        node_name, updates = next(iter(chunk.items()))
"""
from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END


# ── Shared State Schema ────────────────────────────────────────────────────────

class MuleState(TypedDict, total=False):
    """
    Typed state dict threaded through all 7 mule investigation checkpoints.

    Uses total=False so every field is optional — each agent adds its own
    keys and LangGraph merges them into the shared state.
    """

    # ── Mission bootstrap ──────────────────────────────────────────────────
    account_id: str            # Primary account under investigation
    account_name: str          # Account holder name
    alert: dict                # Incoming alert payload
    alert_type: str            # Normalised alert type
    notes: str                 # Analyst notes
    mission_id: str
    audit_log: list
    mule_status: str           # ALERT_CLOSED | ACCOUNT_NOT_FOUND | IN_PROGRESS | COMPLETE

    # ── CP1 — MuleAlertValidationAgent ────────────────────────────────────
    alert_validated: bool
    alert_priority: str        # HIGH | MEDIUM | LOW
    alert_narrative: str
    account_profile: dict
    alert_velocity: dict
    cp1_1: dict
    cp1_2: dict

    # ── CP2 — LinkedAccountDiscoveryAgent ─────────────────────────────────
    linked_accounts: list          # List of linked account IDs
    linked_account_details: list   # Full link details with paths
    network_summary: str
    network_risk_score: int
    known_network_member: bool
    known_networks: list
    network_risk: str              # HIGH | MEDIUM | LOW
    cp2: dict

    # ── CP3 — FundFlowLayeringAgent ───────────────────────────────────────
    fund_flow_summary: str
    layering_detected: bool
    layering_patterns: list
    total_exposure_hkd: float
    suspicious_tx_count: int
    counterparty_data: list
    structuring_result: dict
    cp3: dict

    # ── CP4 — RecruitmentPatternAgent (★) ────────────────────────────────
    recruitment_likelihood: str   # HIGH | MEDIUM | LOW
    mule_type: str                # WITTING | UNWITTING | PROFESSIONAL | UNKNOWN
    recruitment_indicators: list
    recruitment_narrative: str
    typology_match: dict
    cp4: dict

    # ── CP5 — ScamFraudCorrelationAgent ───────────────────────────────────
    correlated_cases: list
    fraud_typology: str
    correlation_confidence: float
    fraud_narrative: str
    linked_mule_hit_count: int
    adverse_media_mule: list
    cp5: dict

    # ── CP6 — OutreachSourceOfFundsAgent ──────────────────────────────────
    outreach_conducted: bool
    source_of_funds_explanation: str
    explanation_credibility: str   # CREDIBLE | PARTIAL | IMPLAUSIBLE
    edd_findings: str
    cp6: dict

    # ── CP7 — SARDraftingAgent ────────────────────────────────────────────
    final_disposition: str         # FILE_SAR | ESCALATE_TO_MLRO | MONITOR | CLOSE_NO_ACTION
    sar_required: bool
    sar_reference: str
    sar_draft: dict
    analyst_notes: str
    mule_key_findings: list
    cp7: dict


# ── Node name → Agent class name mapping ───────────────────────────────────────

MULE_NODE_TO_AGENT: dict[str, str] = {
    "mule_alert_validation":    "MuleAlertValidationAgent",
    "linked_account_discovery": "LinkedAccountDiscoveryAgent",
    "fund_flow_layering":       "FundFlowLayeringAgent",
    "recruitment_pattern":      "RecruitmentPatternAgent",
    "scam_fraud_correlation":   "ScamFraudCorrelationAgent",
    "outreach_source_of_funds": "OutreachSourceOfFundsAgent",
    "sar_drafting":             "SARDraftingAgent",
}


# ── Graph Factory ──────────────────────────────────────────────────────────────

def build_mule_graph(
    model: str = "qwen3.5:9b",
    ollama_host: str = "http://localhost:11434",
    llm_gateway: Optional[object] = None,
    memory: Optional[object] = None,
    redis_url: Optional[str] = None,
):
    """
    Compile and return the Mule Hunting StateGraph.

    7 agents are wrapped as node functions. Conditional edge after CP1 closes
    the investigation immediately if the alert is invalid or the account
    cannot be found, avoiding unnecessary downstream LLM calls.

    Args:
        model:       Ollama model name, e.g. "qwen3.5:9b".
        ollama_host: Ollama API base URL.
        llm_gateway: Optional LLMGateway instance (production mode).
        memory:      Optional MemoryManager for cross-mission recall.
        redis_url:   If given, attaches a Redis checkpointer keyed by mission_id.

    Returns:
        Compiled CompiledGraph.  Call .invoke(state) or .stream(state).
    """
    from agents import (
        MuleAlertValidationAgent,
        LinkedAccountDiscoveryAgent,
        FundFlowLayeringAgent,
        RecruitmentPatternAgent,
        ScamFraudCorrelationAgent,
        OutreachSourceOfFundsAgent,
        SARDraftingAgent,
    )

    _kwargs = dict(
        model=model,
        ollama_host=ollama_host,
        llm_gateway=llm_gateway,
        memory=memory,
    )

    # Instantiate once at graph-build time; shared across all invocations.
    _agents = {
        "MuleAlertValidationAgent":    MuleAlertValidationAgent(**_kwargs),
        "LinkedAccountDiscoveryAgent": LinkedAccountDiscoveryAgent(**_kwargs),
        "FundFlowLayeringAgent":       FundFlowLayeringAgent(**_kwargs),
        "RecruitmentPatternAgent":     RecruitmentPatternAgent(**_kwargs),
        "ScamFraudCorrelationAgent":   ScamFraudCorrelationAgent(**_kwargs),
        "OutreachSourceOfFundsAgent":  OutreachSourceOfFundsAgent(**_kwargs),
        "SARDraftingAgent":            SARDraftingAgent(**_kwargs),
    }

    # ── Node functions ─────────────────────────────────────────────────────

    def mule_alert_validation_node(state: MuleState) -> dict:
        return _agents["MuleAlertValidationAgent"].run(dict(state))

    def linked_account_discovery_node(state: MuleState) -> dict:
        return _agents["LinkedAccountDiscoveryAgent"].run(dict(state))

    def fund_flow_layering_node(state: MuleState) -> dict:
        return _agents["FundFlowLayeringAgent"].run(dict(state))

    def recruitment_pattern_node(state: MuleState) -> dict:
        return _agents["RecruitmentPatternAgent"].run(dict(state))

    def scam_fraud_correlation_node(state: MuleState) -> dict:
        return _agents["ScamFraudCorrelationAgent"].run(dict(state))

    def outreach_source_of_funds_node(state: MuleState) -> dict:
        return _agents["OutreachSourceOfFundsAgent"].run(dict(state))

    def sar_drafting_node(state: MuleState) -> dict:
        return _agents["SARDraftingAgent"].run(dict(state))

    # ── Routing functions ──────────────────────────────────────────────────

    def _route_after_alert_validation(state: MuleState) -> str:
        """
        If the alert is closed or the account is not found, end the
        investigation immediately — no further agents need to run.
        """
        terminal = {"ALERT_CLOSED", "ACCOUNT_NOT_FOUND"}
        if state.get("mule_status", "").upper() in terminal:
            return END
        return "linked_account_discovery"

    # ── Assemble graph ─────────────────────────────────────────────────────

    builder = StateGraph(MuleState)

    builder.add_node("mule_alert_validation",    mule_alert_validation_node)
    builder.add_node("linked_account_discovery", linked_account_discovery_node)
    builder.add_node("fund_flow_layering",       fund_flow_layering_node)
    builder.add_node("recruitment_pattern",      recruitment_pattern_node)
    builder.add_node("scam_fraud_correlation",   scam_fraud_correlation_node)
    builder.add_node("outreach_source_of_funds", outreach_source_of_funds_node)
    builder.add_node("sar_drafting",             sar_drafting_node)

    builder.set_entry_point("mule_alert_validation")

    # CP1 → CP2 (valid alert) or END (closed/not found)
    builder.add_conditional_edges(
        "mule_alert_validation",
        _route_after_alert_validation,
        {
            "linked_account_discovery": "linked_account_discovery",
            END: END,
        },
    )

    # Linear happy path: CP2 → CP3 → CP4 → CP5 → CP6 → CP7 → END
    builder.add_edge("linked_account_discovery", "fund_flow_layering")
    builder.add_edge("fund_flow_layering",       "recruitment_pattern")
    builder.add_edge("recruitment_pattern",      "scam_fraud_correlation")
    builder.add_edge("scam_fraud_correlation",   "outreach_source_of_funds")
    builder.add_edge("outreach_source_of_funds", "sar_drafting")
    builder.add_edge("sar_drafting",             END)

    # ── Optional Redis checkpointer ────────────────────────────────────────

    if redis_url:
        try:
            from langgraph.checkpoint.redis import RedisSaver
            checkpointer = RedisSaver(redis_url=redis_url)
            return builder.compile(checkpointer=checkpointer)
        except ImportError:
            pass  # langgraph-checkpoint-redis not installed; compile without

    return builder.compile()
