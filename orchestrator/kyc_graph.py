"""
KYC Pipeline as a LangGraph StateGraph.

Replaces the manual PIPELINE_ORDER for-loop with a typed, conditional
StateGraph.  Each of the 6 KYC agents becomes a node function; conditional
edges handle DataCollection failure (→ documentation so an audit trail is
still written) and ensure documentation is always the terminal step.

Usage — full pipeline (blocking):
    from orchestrator.kyc_graph import build_graph, KYCState

    graph = build_graph(model="qwen3.5:9b", ollama_host="http://localhost:11434")
    final_state = graph.invoke(initial_state)

Usage — streaming (for WebSocket / timeline updates):
    for chunk in graph.stream(initial_state):
        node_name, updates = next(iter(chunk.items()))
        # node_name: "data_collection" | "risk_assessment" | …
        # updates: dict of state keys changed by that node

State flow:
    data_collection
        ↓  (ok)               ↓  (FAILED/ERROR)
    risk_assessment          documentation ──→ END
        ↓
    aereve_screening
        ↓
    alert_review
        ↓
    decision
        ↓
    documentation ──→ END
"""
from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END


# ── Shared State Schema ────────────────────────────────────────────────────────

class KYCState(TypedDict, total=False):
    """
    Typed state dict threaded through all 6 KYC pipeline nodes.

    Uses total=False so every field is optional — each agent adds its own
    keys and the graph merges them incrementally into the shared state.
    This replaces the untyped `context` dict used in MissionExecutor.
    """

    # ── Mission bootstrap ──────────────────────────────────────────────────
    customer_id: str
    customer_name: str
    event: dict
    event_type: str
    mission_payload: dict
    audit_log: list
    status: str
    mission_id: str
    mission_plan: dict

    # ── Phase 1 — DataCollectionAgent ─────────────────────────────────────
    customer_data: dict
    identity_verification: dict
    jurisdiction_risk: dict
    step_1_1: dict
    step_1_2: dict
    step_1_3: dict

    # ── Phase 2 — RiskAssessmentAgent ─────────────────────────────────────
    risk_score: int
    risk_level: str          # "HIGH" | "MEDIUM" | "LOW"
    risk_narrative: str
    step_2_1: dict

    # ── Phase 3 — AereveScreeningAgent ────────────────────────────────────
    name_variants: list
    screening_results: dict
    pep_screening: dict
    adverse_media: list
    step_3_1: dict
    step_3_2: dict

    # ── Phase 4 — AlertReviewAgent ────────────────────────────────────────
    step_4_1: dict
    step_4_2: dict
    step_4_3: dict
    edd_required: bool
    edd_report: dict

    # ── Phase 5 — DecisionAgent ───────────────────────────────────────────
    final_decision: str      # "APPROVE" | "APPROVE_WITH_CONDITIONS" | "ESCALATE_TO_MLRO" | "REJECT"
    step_5_1: dict
    step_5_2: dict
    step_5_3: dict
    requires_str: bool
    mlro_dossier: dict

    # ── Phase 6 — DocumentationAgent ─────────────────────────────────────
    audit_id: str
    audit_log_file: str
    customer_notification: str
    internal_notification: str


# ── Node name → Agent class name mapping ───────────────────────────────────────

NODE_TO_AGENT: dict[str, str] = {
    "data_collection":  "DataCollectionAgent",
    "risk_assessment":  "RiskAssessmentAgent",
    "aereve_screening": "AereveScreeningAgent",
    "alert_review":     "AlertReviewAgent",
    "decision":         "DecisionAgent",
    "documentation":    "DocumentationAgent",
}


# ── Graph Factory ──────────────────────────────────────────────────────────────

def build_graph(
    model: str = "qwen3.5:9b",
    ollama_host: str = "http://localhost:11434",
    llm_gateway: Optional[object] = None,
    memory: Optional[object] = None,
    redis_url: Optional[str] = None,
):
    """
    Compile and return the KYC StateGraph.

    Each of the 6 KYC agents is wrapped as a node function. The node
    function receives the full current state, calls agent.run(), and returns
    the full updated state dict. LangGraph merges returned keys into the
    shared state before the next node runs.

    Conditional edges:
      - data_collection: if status is FAILED/ERROR → skip to documentation
      - documentation: always → END

    Args:
        model:       Ollama model name, e.g. "qwen3.5:9b".
        ollama_host: Ollama API base URL.
        llm_gateway: Optional LLMGateway instance (production mode).
        memory:      Optional MemoryManager for cross-mission recall.
        redis_url:   If given, attaches a Redis checkpointer so mission
                     state survives broker restarts and can be resumed by
                     thread_id (== mission_id).

    Returns:
        Compiled CompiledGraph.  Call .invoke(state) or .stream(state).
    """
    from agents import (
        AlertReviewAgent,
        AereveScreeningAgent,
        DataCollectionAgent,
        DecisionAgent,
        DocumentationAgent,
        RiskAssessmentAgent,
    )

    _kwargs = dict(
        model=model,
        ollama_host=ollama_host,
        llm_gateway=llm_gateway,
        memory=memory,
    )

    # Instantiate once at graph-build time; shared across all invocations
    # of the compiled graph.
    _agents = {
        "DataCollectionAgent":  DataCollectionAgent(**_kwargs),
        "RiskAssessmentAgent":  RiskAssessmentAgent(**_kwargs),
        "AereveScreeningAgent": AereveScreeningAgent(**_kwargs),
        "AlertReviewAgent":     AlertReviewAgent(**_kwargs),
        "DecisionAgent":        DecisionAgent(**_kwargs),
        "DocumentationAgent":   DocumentationAgent(**_kwargs),
    }

    # ── Node functions ─────────────────────────────────────────────────────
    # Each node receives the full KYCState, calls the agent, and returns the
    # full updated context dict.  LangGraph merges returned keys into state.

    def data_collection_node(state: KYCState) -> dict:
        return _agents["DataCollectionAgent"].run(dict(state))

    def risk_assessment_node(state: KYCState) -> dict:
        return _agents["RiskAssessmentAgent"].run(dict(state))

    def aereve_screening_node(state: KYCState) -> dict:
        return _agents["AereveScreeningAgent"].run(dict(state))

    def alert_review_node(state: KYCState) -> dict:
        return _agents["AlertReviewAgent"].run(dict(state))

    def decision_node(state: KYCState) -> dict:
        return _agents["DecisionAgent"].run(dict(state))

    def documentation_node(state: KYCState) -> dict:
        return _agents["DocumentationAgent"].run(dict(state))

    # ── Routing functions ──────────────────────────────────────────────────

    def _route_after_data_collection(state: KYCState) -> str:
        """
        If DataCollection failed (no customer data) jump straight to
        documentation so a failure audit trail is always written.
        """
        if state.get("status", "").upper() in ("FAILED", "ERROR"):
            return "documentation"
        return "risk_assessment"

    # ── Assemble graph ─────────────────────────────────────────────────────

    builder = StateGraph(KYCState)

    builder.add_node("data_collection",  data_collection_node)
    builder.add_node("risk_assessment",  risk_assessment_node)
    builder.add_node("aereve_screening", aereve_screening_node)
    builder.add_node("alert_review",     alert_review_node)
    builder.add_node("decision",         decision_node)
    builder.add_node("documentation",    documentation_node)

    builder.set_entry_point("data_collection")

    # DataCollection → Risk (normal) or Documentation (failure)
    builder.add_conditional_edges(
        "data_collection",
        _route_after_data_collection,
        {
            "risk_assessment": "risk_assessment",
            "documentation":   "documentation",
        },
    )

    # Happy path
    builder.add_edge("risk_assessment",  "aereve_screening")
    builder.add_edge("aereve_screening", "alert_review")
    builder.add_edge("alert_review",     "decision")
    builder.add_edge("decision",         "documentation")
    builder.add_edge("documentation",    END)

    # ── Optional Redis checkpointer ────────────────────────────────────────

    if redis_url:
        try:
            from langgraph.checkpoint.redis import RedisSaver
            checkpointer = RedisSaver(redis_url=redis_url)
            return builder.compile(checkpointer=checkpointer)
        except ImportError:
            pass  # langgraph-checkpoint-redis not installed; compile without

    return builder.compile()
