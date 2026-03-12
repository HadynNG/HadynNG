"""
Mission Timeline — real-time status tracker for UI consumption.

Writes a JSON file to timelines/<mission_id>.json that is updated after
every pipeline phase completes. A UI can poll or watch this file to
display live mission progress without needing to parse terminal output.

File schema:
{
  "mission_id": "...",
  "customer_id": "...",
  "customer_name": "...",
  "model": "...",
  "started_at": "<ISO-8601>",
  "status": "IN_PROGRESS" | "COMPLETE" | "FAILED",
  "current_phase": "AereveScreeningAgent",
  "progress_pct": 50,
  "phases": [
    {
      "sequence": 1,
      "phase_id": "data_collection",
      "label": "Data Collection",
      "agent": "DataCollectionAgent",
      "status": "COMPLETE" | "IN_PROGRESS" | "PENDING" | "FAILED",
      "started_at": "<ISO-8601>",
      "completed_at": "<ISO-8601>",
      "duration_seconds": 4.2,
      "summary": "Customer verified — identity confirmed",
      "key_outputs": { "risk_level": "LOW", ... },
      "substeps": [
        { "id": "1.1", "label": "Event Classification", "status": "COMPLETE" },
        ...
      ]
    }
  ],
  "final_decision": "APPROVE",
  "risk_level": "LOW",
  "risk_score": 10,
  "screening_hits": 0,
  "edd_required": false,
  "str_filed": false,
  "audit_log_file": "...",
  "completed_at": "<ISO-8601>",
  "elapsed_seconds": 87.4,
  "updated_at": "<ISO-8601>"
}
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

TIMELINE_DIR = Path("timelines")

# Phase definitions — fixed sequence with display metadata
_PHASES = [
    {
        "sequence": 0,
        "phase_id": "planning",
        "label": "Mission Planning",
        "agent": "Orchestrator",
        "substeps": [
            {"id": "0.1", "label": "LLM Mission Analysis"},
            {"id": "0.2", "label": "Execution Plan Generation"},
        ],
    },
    {
        "sequence": 1,
        "phase_id": "data_collection",
        "label": "Data Collection & Identity Verification",
        "agent": "DataCollectionAgent",
        "substeps": [
            {"id": "1.1", "label": "Trigger Event Classification"},
            {"id": "1.2", "label": "CRM Customer Data Retrieval"},
            {"id": "1.3", "label": "Identity Document Verification"},
        ],
    },
    {
        "sequence": 2,
        "phase_id": "risk_assessment",
        "label": "Risk Assessment",
        "agent": "RiskAssessmentAgent",
        "substeps": [
            {"id": "2.1", "label": "Risk Score Calculation"},
            {"id": "2.2", "label": "LLM Risk Narrative"},
        ],
    },
    {
        "sequence": 3,
        "phase_id": "screening",
        "label": "Name Screening",
        "agent": "AereveScreeningAgent",
        "substeps": [
            {"id": "3.1", "label": "Query Variant Generation"},
            {"id": "3.2", "label": "Sanctions / PEP Database Screening"},
        ],
    },
    {
        "sequence": 4,
        "phase_id": "alert_review",
        "label": "Alert Review & Investigation",
        "agent": "AlertReviewAgent",
        "substeps": [
            {"id": "4.1", "label": "Alert Triage & Auto-Dismiss"},
            {"id": "4.2", "label": "LLM Match Investigation"},
            {"id": "4.3", "label": "Enhanced Due Diligence (EDD)"},
        ],
    },
    {
        "sequence": 5,
        "phase_id": "decision",
        "label": "Decision & Escalation",
        "agent": "DecisionAgent",
        "substeps": [
            {"id": "5.1", "label": "LLM Compliance Decision"},
            {"id": "5.2", "label": "MLRO Escalation (if required)"},
            {"id": "5.3", "label": "STR Filing (if required)"},
        ],
    },
    {
        "sequence": 6,
        "phase_id": "documentation",
        "label": "Documentation & Closure",
        "agent": "DocumentationAgent",
        "substeps": [
            {"id": "6.1", "label": "Audit Trail Logging"},
            {"id": "6.2", "label": "Stakeholder Notifications"},
        ],
    },
]

_AGENT_TO_PHASE = {p["agent"]: p for p in _PHASES}
_TOTAL_PHASES = len(_PHASES)  # includes planning


class MissionTimeline:
    """
    Tracks and persists mission progress for UI consumption.

    Usage:
        tl = MissionTimeline(mission_id, customer_id, customer_name, model)
        tl.start_phase("Orchestrator")
        tl.complete_phase("Orchestrator", summary="Plan ready", key_outputs={})
        tl.start_phase("DataCollectionAgent")
        ...
        tl.complete_mission(context)
    """

    def __init__(
        self,
        mission_id: str,
        customer_id: str,
        customer_name: str,
        model: str,
    ):
        self.mission_id = mission_id
        self.file = TIMELINE_DIR / f"timeline_{mission_id}.json"
        TIMELINE_DIR.mkdir(exist_ok=True)

        now = self._now()
        self._phase_start_times: dict[str, str] = {}

        # Build initial phase list — all PENDING
        phases = []
        for p in _PHASES:
            phases.append({
                "sequence": p["sequence"],
                "phase_id": p["phase_id"],
                "label": p["label"],
                "agent": p["agent"],
                "status": "PENDING",
                "started_at": None,
                "completed_at": None,
                "duration_seconds": None,
                "summary": None,
                "key_outputs": {},
                "substeps": [
                    {"id": s["id"], "label": s["label"], "status": "PENDING"}
                    for s in p["substeps"]
                ],
            })

        self._data = {
            "mission_id": mission_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "model": model,
            "started_at": now,
            "status": "IN_PROGRESS",
            "current_phase": None,
            "progress_pct": 0,
            "phases": phases,
            "final_decision": None,
            "risk_level": None,
            "risk_score": None,
            "screening_hits": None,
            "edd_required": None,
            "str_filed": None,
            "audit_log_file": None,
            "completed_at": None,
            "elapsed_seconds": None,
            "updated_at": now,
        }
        self._write()

    # ── Public API ────────────────────────────────────────────────────────────

    def start_phase(self, agent_name: str):
        """Mark a phase as IN_PROGRESS."""
        phase = self._get_phase(agent_name)
        if phase is None:
            return
        now = self._now()
        phase["status"] = "IN_PROGRESS"
        phase["started_at"] = now
        # Mark all substeps as PENDING (reset if retried)
        for s in phase["substeps"]:
            s["status"] = "PENDING"
        self._phase_start_times[agent_name] = now
        self._data["current_phase"] = phase["label"]
        self._update_progress()
        self._write()

    def complete_substep(self, agent_name: str, substep_id: str):
        """Mark an individual sub-step as complete."""
        phase = self._get_phase(agent_name)
        if phase is None:
            return
        for s in phase["substeps"]:
            if s["id"] == substep_id:
                s["status"] = "COMPLETE"
                break
        self._write()

    def complete_phase(
        self,
        agent_name: str,
        summary: str,
        key_outputs: Optional[dict] = None,
        status: str = "COMPLETE",
    ):
        """Mark a phase as COMPLETE (or FAILED) with a summary."""
        phase = self._get_phase(agent_name)
        if phase is None:
            return
        now = self._now()
        phase["status"] = status
        phase["completed_at"] = now
        phase["summary"] = summary
        phase["key_outputs"] = key_outputs or {}
        # Mark remaining substeps as COMPLETE if phase succeeded
        if status == "COMPLETE":
            for s in phase["substeps"]:
                if s["status"] == "PENDING":
                    s["status"] = "COMPLETE"
        # Calculate duration
        start = self._phase_start_times.get(agent_name)
        if start:
            delta = datetime.fromisoformat(now.rstrip("Z")) - datetime.fromisoformat(start.rstrip("Z"))
            phase["duration_seconds"] = round(delta.total_seconds(), 1)
        self._update_progress()
        self._write()

    def complete_mission(self, context: dict):
        """Finalise the timeline with mission-level results."""
        now = self._now()
        start = datetime.fromisoformat(self._data["started_at"].rstrip("Z"))
        elapsed = (datetime.fromisoformat(now.rstrip("Z")) - start).total_seconds()

        self._data.update({
            "status": "COMPLETE",
            "current_phase": None,
            "progress_pct": 100,
            "final_decision": context.get("final_decision"),
            "risk_level": context.get("risk_level"),
            "risk_score": context.get("risk_score"),
            "screening_hits": context.get("screening_results", {}).get("total_hits", 0),
            "edd_required": context.get("edd_required", False),
            "str_filed": context.get("step_5_3", {}).get("str_filed", False),
            "audit_log_file": context.get("audit_log_file"),
            "completed_at": now,
            "elapsed_seconds": round(elapsed, 1),
            "updated_at": now,
        })
        self._write()

    def fail_mission(self, reason: str):
        """Mark the entire mission as FAILED."""
        now = self._now()
        self._data.update({
            "status": "FAILED",
            "current_phase": None,
            "updated_at": now,
            "completed_at": now,
            "final_decision": "FAILED",
        })
        # Mark current IN_PROGRESS phase as failed
        for phase in self._data["phases"]:
            if phase["status"] == "IN_PROGRESS":
                phase["status"] = "FAILED"
                phase["summary"] = reason
        self._write()

    @property
    def filepath(self) -> str:
        return str(self.file)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat() + "Z"

    def _get_phase(self, agent_name: str) -> Optional[dict]:
        meta = _AGENT_TO_PHASE.get(agent_name)
        if meta is None:
            return None
        seq = meta["sequence"]
        return next((p for p in self._data["phases"] if p["sequence"] == seq), None)

    def _update_progress(self):
        completed = sum(1 for p in self._data["phases"] if p["status"] == "COMPLETE")
        self._data["progress_pct"] = round((completed / _TOTAL_PHASES) * 100)
        self._data["updated_at"] = self._now()

    def _write(self):
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, default=str)
