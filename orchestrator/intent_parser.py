"""
Intent Parser — interprets a free-form user prompt against the KYC SOP.

Reads the SOP document and uses LLM reasoning to determine:
  - Whether the request is a KYC screening request
  - Which customer to screen
  - What event type triggered the request
  - Any additional context to pass downstream

Returns a structured ParsedIntent dict.
"""
import json
import re
from pathlib import Path

import ollama
from rich.console import Console

console = Console()

# SOP search paths (new storage location first, then original demo location)
_ROOT = Path(__file__).resolve().parent.parent
_SOP_CANDIDATES = [
    _ROOT / "storage" / "documents" / "sop" / "kyc_sop.md",
    _ROOT / "demo" / "kyc_sop.md",
]
_DEFAULT_SOP = next((p for p in _SOP_CANDIDATES if p.exists()), _SOP_CANDIDATES[-1])

_VALID_EVENT_TYPES = {"onboarding", "transaction_alert", "periodic_review", "customer_update"}


class IntentParser:
    """
    LLM-powered classifier that maps a free-form user prompt to a
    structured KYC intent, validated against the KYC SOP.
    """

    def __init__(
        self,
        model: str = "qwen3.5:9b",
        ollama_host: str = "http://localhost:11434",
        sop_path: str | Path | None = None,
    ):
        self.model = model
        self.client = ollama.Client(host=ollama_host)
        self._sop_text = self._load_sop(Path(sop_path) if sop_path else _DEFAULT_SOP)

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, user_prompt: str) -> dict:
        """
        Parse a free-form user prompt and return a structured intent.

        Returns:
            {
                "is_kyc_request": bool,
                "customer_name": str | None,
                "event_type": "onboarding" | "transaction_alert" |
                              "periodic_review" | "customer_update",
                "notes": str,
                "decline_reason": str | None,  # set when is_kyc_request=False
            }
        """
        console.print("\n[dim italic]  Parsing intent against KYC SOP...[/dim italic]")

        system_prompt = (
            "You are a compliance operations router. Your job is to determine whether a user "
            "request should trigger a KYC name screening workflow, based on the KYC SOP below.\n\n"
            "=== KYC SOP (excerpt) ===\n"
            + self._sop_text
            + "\n=== END SOP ===\n\n"
            "Analyse the user's message and respond ONLY with a JSON object:\n"
            '{\n'
            '  "is_kyc_request": true or false,\n'
            '  "customer_name": "<full name of the subject to screen, or null if not a KYC request>",\n'
            '  "event_type": "onboarding" | "transaction_alert" | "periodic_review" | "customer_update",\n'
            '  "notes": "<any additional context extracted from the message, or empty string>",\n'
            '  "decline_reason": "<brief reason if is_kyc_request is false, else null>"\n'
            "}\n\n"
            "Rules:\n"
            "- is_kyc_request must be true only if the message clearly asks to screen/check/review a named person or entity\n"
            "- customer_name must be the name of the SUBJECT being screened, not the requester\n"
            "- event_type should be inferred from context; default to 'onboarding' if unclear\n"
            "- Respond ONLY with the JSON object. No preamble, no explanation."
        )

        response_text = self._llm_call(system_prompt, user_prompt)
        parsed = self._extract_json(response_text)

        # Normalise and validate
        is_kyc = bool(parsed.get("is_kyc_request", False))
        customer_name = (parsed.get("customer_name") or "").strip() or None
        event_type = parsed.get("event_type", "onboarding")
        if event_type not in _VALID_EVENT_TYPES:
            event_type = "onboarding"
        notes = (parsed.get("notes") or "").strip()
        decline_reason = (parsed.get("decline_reason") or "").strip() or None

        # Safety: if LLM says it's a KYC request but gave no name, not parseable
        if is_kyc and not customer_name:
            is_kyc = False
            decline_reason = "Could not identify a customer name in the request."

        return {
            "is_kyc_request": is_kyc,
            "customer_name": customer_name,
            "event_type": event_type,
            "notes": notes,
            "decline_reason": decline_reason,
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_sop(path: Path) -> str:
        if path.exists():
            return path.read_text(encoding="utf-8")
        # Graceful fallback — minimal inline SOP
        return (
            "KYC screening triggers: new customer onboarding, transaction alerts, "
            "periodic review, customer updates. Extract customer name and event type."
        )

    def _llm_call(self, system_prompt: str, user_prompt: str) -> str:
        """Lightweight non-streaming LLM call for intent parsing."""
        try:
            response = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                think=False,  # No need for chain-of-thought here — fast classification
                options={
                    "temperature": 0.0,   # Deterministic classification
                    "num_predict": 256,
                    "seed": 42,
                },
            )
            return response.message.content or ""
        except Exception as e:
            console.print(f"[red]  Intent parser LLM error: {e}[/red]")
            return "{}"

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract first balanced JSON object from text."""
        # Strip special tokens
        text = re.sub(r"<\|[^|]+\|>.*", "", text, flags=re.DOTALL).strip()
        # Try fenced block
        block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if block:
            try:
                return json.loads(block.group(1))
            except json.JSONDecodeError:
                pass
        # Walk for balanced {}
        i = 0
        while i < len(text):
            if text[i] != "{":
                i += 1
                continue
            depth, start = 0, i
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start: j + 1])
                        except json.JSONDecodeError:
                            break
            i += 1
        return {}
