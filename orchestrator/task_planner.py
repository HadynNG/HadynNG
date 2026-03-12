"""
Task Planner — Uses Ollama (qwen3-coder-next:latest) to analyse an incoming
mission and produce a structured, step-by-step execution plan.

This is the "brain" of the orchestrator: it converts a free-form mission
description into a concrete JSON execution plan that the MissionExecutor
can follow.
"""
import json
import re
from datetime import datetime

import ollama
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()

# Canonical agent names available in the platform
AVAILABLE_AGENTS = [
    "DataCollectionAgent",    # Steps 1.1–1.3
    "RiskAssessmentAgent",    # Step  2.1
    "AereveScreeningAgent",         # Steps 3.1–3.2
    "AlertReviewAgent",       # Steps 4.1–4.3
    "DecisionAgent",          # Steps 5.1–5.3
    "DocumentationAgent",     # Steps 6.1–6.2
]

_SYSTEM_PROMPT = """
You are the orchestration engine for a KYC (Know Your Customer) Agentic AI platform
that operates under Hong Kong's AMLO, HKMA, and SFC compliance frameworks.

Your role:
1. Analyse the incoming mission description.
2. Break it down into a concrete, sequenced execution plan.
3. Map each step to one of the available agents.
4. Highlight any compliance considerations or risk flags.

Available agents and their responsibilities:
- DataCollectionAgent   : Receive event, collect customer data, verify identity (Steps 1.1–1.3)
- RiskAssessmentAgent   : Calculate initial risk score and categorise (Step 2.1)
- AereveScreeningAgent        : Generate name variants, run sanctions/PEP screening (Steps 3.1–3.2)
- AlertReviewAgent      : Triage alerts, investigate matches (LLM), run EDD (Steps 4.1–4.3)
- DecisionAgent         : Final compliance decision, MLRO escalation, STR filing (Steps 5.1–5.3)
- DocumentationAgent    : Audit logging, stakeholder notifications (Steps 6.1–6.2)

IMPORTANT RULES:
- All six agent phases must be included for a complete KYC screening.
- Agents must run in the order listed above (sequential pipeline).
- Flag if any step may require human intervention.
- Periodic/scheduled rescreening is OUT OF SCOPE for this demo.

Respond ONLY with a valid JSON object in this exact schema (no markdown, no extra text):
{
  "mission_id": "unique identifier",
  "mission_summary": "one-sentence summary",
  "scope": "what is in scope",
  "out_of_scope": "what is excluded",
  "compliance_framework": ["AMLO", "HKMA", ...],
  "execution_plan": [
    {
      "sequence": 1,
      "agent": "AgentName",
      "purpose": "what this agent does in this mission",
      "key_inputs": ["list of required inputs"],
      "expected_outputs": ["list of outputs"],
      "human_intervention_possible": true/false,
      "notes": "any special considerations"
    }
  ],
  "risk_flags": ["any upfront risk considerations"],
  "estimated_decision_outcomes": ["APPROVE", "APPROVE_WITH_CONDITIONS", "ESCALATE_TO_MLRO", "REJECT"],
  "compliance_notes": "overall compliance notes"
}
""".strip()


class TaskPlanner:
    """LLM-powered task planner using Ollama."""

    def __init__(
        self,
        model: str = "qwen3.5:9b",
        ollama_host: str = "http://localhost:11434",
    ):
        self.model = model
        self.client = ollama.Client(host=ollama_host)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_json(self, text: str) -> dict:
        """
        Extract the first valid balanced JSON object from text.
        Strips model special tokens before parsing.
        """
        # Remove special tokens (<|endoftext|>, <|im_end|>, etc.) and everything after
        text = re.sub(r"<\|[^|]+\|>.*", "", text, flags=re.DOTALL).strip()

        # Try fenced code block first
        code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code:
            try:
                return json.loads(code.group(1))
            except json.JSONDecodeError:
                pass

        # Walk the text to find the first syntactically balanced {} block
        i = 0
        while i < len(text):
            if text[i] != "{":
                i += 1
                continue
            depth = 0
            start = i
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : j + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break  # malformed block — skip to next {
            i += 1
        return {}

    def _default_plan(self, mission_description: str) -> dict:
        """Fallback plan if LLM is unavailable."""
        return {
            "mission_id": f"MISSION-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            "mission_summary": mission_description[:100],
            "scope": "KYC Name Screening",
            "out_of_scope": "Periodic rescreening",
            "compliance_framework": ["AMLO", "HKMA", "SFC"],
            "execution_plan": [
                {"sequence": i + 1, "agent": a, "purpose": f"Execute {a} phase",
                 "key_inputs": [], "expected_outputs": [], "human_intervention_possible": False, "notes": ""}
                for i, a in enumerate(AVAILABLE_AGENTS)
            ],
            "risk_flags": [],
            "estimated_decision_outcomes": ["APPROVE", "ESCALATE_TO_MLRO", "REJECT"],
            "compliance_notes": "Default plan — LLM unavailable",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def plan(self, mission_description: str) -> dict:
        """
        Use the LLM to analyse the mission and return a structured execution plan.

        Args:
            mission_description: Free-form description of the KYC screening mission.

        Returns:
            Structured execution plan dict.
        """
        console.print()
        console.print(Rule("[bold blue]ORCHESTRATOR — TASK PLANNING[/bold blue]", style="blue"))
        console.print(
            Panel(
                f"[bold]Mission:[/bold] {mission_description}",
                title="[bold blue]Incoming Mission[/bold blue]",
                border_style="blue",
            )
        )
        console.print(f"\n[dim italic]  Routing to {self.model} for mission analysis...[/dim italic]")

        full_text = ""
        thinking_text = ""
        content_text = ""

        # Character-level safety caps to prevent infinite generation loops
        MAX_THINKING_CHARS = 24_000   # planning needs more thinking room
        MAX_CONTENT_CHARS  = 8_000    # JSON plan can be verbose

        try:
            console.print("[dim]  ┌─ Orchestrator Thinking ───────────────────[/dim]")
            stream = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Analyse and plan this KYC mission:\n\n{mission_description}\n\n"
                            f"Available agents: {AVAILABLE_AGENTS}"
                        ),
                    },
                ],
                stream=True,
                think=True,
                options={
                    "temperature": 0.05,
                    "num_predict": 4096,
                    "repeat_penalty": 1.1,
                    "seed": 42,
                },
            )

            for chunk in stream:
                msg = chunk.message
                if hasattr(msg, "thinking") and msg.thinking:
                    thinking_text += msg.thinking
                    print(f"\033[33m{msg.thinking}\033[0m", end="", flush=True)
                    # Safety: break if thinking loops indefinitely
                    if len(thinking_text) > MAX_THINKING_CHARS:
                        print()
                        console.print("\n[yellow]  [thinking truncated — generation cap reached][/yellow]")
                        break
                if msg.content:
                    if not content_text and thinking_text:
                        print()
                        console.print("[dim]  └────────────────────────────────────────[/dim]")
                        console.print("[dim]  ┌─ Execution Plan (JSON) ───────────────[/dim]")
                    # Stop at end-of-sequence special tokens emitted by some models
                    if "<|endoftext|>" in msg.content or "<|im_end|>" in msg.content:
                        stop_at = min(
                            (msg.content.find(t) for t in ("<|endoftext|>", "<|im_end|>") if t in msg.content)
                        )
                        tail = msg.content[:stop_at]
                        if tail:
                            content_text += tail
                            print(tail, end="", flush=True)
                        break
                    content_text += msg.content
                    print(msg.content, end="", flush=True)
                    # Safety: break if content loops indefinitely
                    if len(content_text) > MAX_CONTENT_CHARS:
                        console.print("\n[yellow]  [response truncated — generation cap reached][/yellow]")
                        break

            print()
            console.print("[dim]  └────────────────────────────────────────[/dim]")

        except Exception as e:
            console.print(f"\n[red]  LLM unavailable: {e}[/red]")
            console.print("  [yellow]  Using default execution plan.[/yellow]")
            return self._default_plan(mission_description)

        plan = self._extract_json(content_text)
        if not plan:
            console.print("  [yellow]  Could not parse plan JSON — using default plan.[/yellow]")
            plan = self._default_plan(mission_description)

        # Ensure mission_id
        if "mission_id" not in plan:
            plan["mission_id"] = f"MISSION-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"

        # Print plan summary
        console.print()
        console.print(
            Panel(
                f"[bold]Mission ID:[/bold]  {plan.get('mission_id')}\n"
                f"[bold]Summary:[/bold]     {plan.get('mission_summary', 'N/A')}\n"
                f"[bold]Scope:[/bold]       {plan.get('scope', 'N/A')}\n"
                f"[bold]Out of Scope:[/bold] {plan.get('out_of_scope', 'N/A')}\n"
                f"[bold]Framework:[/bold]   {', '.join(plan.get('compliance_framework', []))}\n"
                f"[bold]Agents:[/bold]      {len(plan.get('execution_plan', []))} phases planned\n"
                f"[bold]Risk Flags:[/bold]  {', '.join(plan.get('risk_flags', [])) or 'None'}",
                title="[bold blue]EXECUTION PLAN SUMMARY[/bold blue]",
                border_style="blue",
            )
        )

        return plan
