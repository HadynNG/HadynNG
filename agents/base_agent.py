"""
Base Agent — provides LLM integration and rich console output.
All KYC step agents inherit from this class.

Supports two LLM modes:
  1. Direct Ollama (default, backward-compatible with demo)
  2. LLM Gateway (production mode — centralised Ollama proxy with caching)

The mode is selected automatically: if an LLMGateway instance is passed,
it is used; otherwise a direct Ollama client is created.
"""
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import ollama
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

console = Console()


def _parse_thinking_and_content(full_text: str) -> tuple[str, str]:
    """
    Split <think>...</think> blocks from the main response.
    Returns (thinking, content).
    """
    thinking_blocks = re.findall(r"<think>(.*?)</think>", full_text, re.DOTALL)
    content = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()
    thinking = "\n".join(b.strip() for b in thinking_blocks)
    return thinking, content


class BaseAgent(ABC):
    """Base class for all KYC pipeline agents."""

    name: str = "BaseAgent"
    step_label: str = "Step ?"

    def __init__(
        self,
        model: str = "qwen3.5:9b",
        ollama_host: str = "http://localhost:11434",
        llm_gateway: Optional[object] = None,
        memory: Optional[object] = None,
    ):
        self.model = model
        self.ollama_host = ollama_host
        self._llm_gateway = llm_gateway
        self._memory = memory
        # Direct client — used when no gateway is provided
        self.client = ollama.Client(host=ollama_host)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _print_step_header(self, title: str, description: str = ""):
        console.print()
        console.print(Rule(f"[bold cyan]{self.step_label}: {title}[/bold cyan]", style="cyan"))
        if description:
            console.print(f"[dim]{description}[/dim]")

    def _print_thinking(self, thinking: str):
        if thinking.strip():
            console.print(
                Panel(
                    Text(thinking.strip(), style="italic dim yellow"),
                    title="[bold yellow]Chain-of-Thought[/bold yellow]",
                    border_style="yellow",
                    expand=False,
                )
            )

    def _print_llm_response(self, content: str):
        console.print(
            Panel(
                content.strip(),
                title="[bold green]LLM Analysis[/bold green]",
                border_style="green",
                expand=False,
            )
        )

    def _print_action(self, action: str, result: str = ""):
        console.print(f"  [bold blue]▶[/bold blue] {action}")
        if result:
            console.print(f"    [dim]{result}[/dim]")

    def _print_decision(self, decision: str, color: str = "white"):
        console.print(
            Panel(
                f"[bold {color}]{decision}[/bold {color}]",
                title="[bold]Decision[/bold]",
                border_style=color,
                expand=False,
            )
        )

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    def _llm_reason(
        self,
        system_prompt: str,
        user_prompt: str,
        show_thinking: bool = True,
        temperature: float = 0.05,
        max_tokens: int = 2048,
    ) -> tuple[str, str]:
        """
        Call the LLM, stream output, and return (thinking, content).
        Displays the chain-of-thought in real time.

        Routes through LLM Gateway if available, otherwise uses direct
        Ollama streaming (backward-compatible demo mode).
        """
        # ── Gateway mode (production) ────────────────────────────────────
        if self._llm_gateway is not None:
            return self._llm_reason_via_gateway(
                system_prompt, user_prompt, show_thinking, temperature, max_tokens
            )

        # ── Direct Ollama mode (demo/backward-compatible) ────────────────
        return self._llm_reason_direct(
            system_prompt, user_prompt, show_thinking, temperature, max_tokens
        )

    def _llm_reason_via_gateway(
        self,
        system_prompt: str,
        user_prompt: str,
        show_thinking: bool,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, str]:
        """Route LLM call through the centralised LLM Gateway."""
        console.print(f"\n[dim italic]  Querying {self.model} via LLM Gateway...[/dim italic]")

        thinking_text = ""
        content_text = ""

        try:
            console.print("[dim]  ┌─ Thinking ────────────────────────────────[/dim]")
            for chunk in self._llm_gateway.stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if chunk["type"] == "thinking":
                    thinking_text += chunk["text"]
                    if show_thinking:
                        print(f"\033[33m{chunk['text']}\033[0m", end="", flush=True)
                elif chunk["type"] == "content":
                    if not content_text and thinking_text:
                        print()
                        console.print("[dim]  └────────────────────────────────────────[/dim]")
                        console.print("[dim]  ┌─ Response ────────────────────────────────[/dim]")
                    content_text += chunk["text"]
                    print(chunk["text"], end="", flush=True)
                elif chunk["type"] == "truncated":
                    console.print(f"\n[yellow]  {chunk['text']}[/yellow]")
                    break

            print()
            console.print("[dim]  └────────────────────────────────────────[/dim]")

            if not thinking_text and "<think>" in content_text:
                thinking_text, content_text = _parse_thinking_and_content(content_text)

        except Exception as e:
            console.print(f"[red]  LLM Gateway error: {e}[/red]")
            content_text = f"[LLM unavailable: {e}]"

        return thinking_text.strip(), content_text.strip()

    def _llm_reason_direct(
        self,
        system_prompt: str,
        user_prompt: str,
        show_thinking: bool,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, str]:
        """Direct Ollama streaming — original demo behavior."""
        MAX_THINKING_CHARS = max_tokens * 6
        MAX_CONTENT_CHARS = max_tokens * 4

        console.print(f"\n[dim italic]  Querying {self.model}...[/dim italic]")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        thinking_text = ""
        content_text = ""

        try:
            stream = self.client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                think=True,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "repeat_penalty": 1.1,
                    "seed": 42,
                },
            )

            thinking_buffer = ""
            content_buffer = ""

            console.print("[dim]  ┌─ Thinking ────────────────────────────────[/dim]")
            for chunk in stream:
                msg = chunk.message
                if hasattr(msg, "thinking") and msg.thinking:
                    thinking_buffer += msg.thinking
                    if show_thinking:
                        print(f"\033[33m{msg.thinking}\033[0m", end="", flush=True)
                    if len(thinking_buffer) > MAX_THINKING_CHARS:
                        print()
                        console.print("\n[yellow]  [thinking truncated — generation cap reached][/yellow]")
                        break
                if msg.content:
                    if not content_buffer and thinking_buffer:
                        print()
                        console.print("[dim]  └────────────────────────────────────────[/dim]")
                        console.print("[dim]  ┌─ Response ────────────────────────────────[/dim]")
                    if "<|endoftext|>" in msg.content or "<|im_end|>" in msg.content:
                        stop_at = min(
                            (msg.content.find(t) for t in ("<|endoftext|>", "<|im_end|>") if t in msg.content)
                        )
                        tail = msg.content[:stop_at]
                        if tail:
                            content_buffer += tail
                            print(tail, end="", flush=True)
                        break
                    content_buffer += msg.content
                    print(msg.content, end="", flush=True)
                    if len(content_buffer) > MAX_CONTENT_CHARS:
                        console.print("\n[yellow]  [response truncated — generation cap reached][/yellow]")
                        break

            print()
            console.print("[dim]  └────────────────────────────────────────[/dim]")

            thinking_text = thinking_buffer
            content_text = content_buffer

            if not thinking_text and "<think>" in content_text:
                thinking_text, content_text = _parse_thinking_and_content(content_text)

        except Exception as e:
            console.print(f"[red]  LLM error: {e}[/red]")
            content_text = f"[LLM unavailable: {e}]"

        return thinking_text.strip(), content_text.strip()

    def _extract_json(self, text: str) -> dict:
        """
        Extract the first valid balanced JSON object from text.
        Strips model special tokens before parsing.
        """
        text = re.sub(r"<\|[^|]+\|>.*", "", text, flags=re.DOTALL).strip()

        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass

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
                            break
            i += 1
        return {}

    # ------------------------------------------------------------------
    # Memory helpers (available when memory service is connected)
    # ------------------------------------------------------------------

    def _recall_insights(self, query: str, top_k: int = 3) -> list[dict]:
        """Recall past insights from vector memory for this agent."""
        if self._memory is None:
            return []
        try:
            return self._memory.recall_agent_insights(self.name, query, top_k=top_k)
        except Exception:
            return []

    def _store_insight(self, context: dict, insight: str):
        """Store a learning insight from this mission."""
        if self._memory is None:
            return
        mission_id = context.get("mission_id", "unknown")
        try:
            self._memory.store_agent_insight(
                self.name, mission_id, insight,
                metadata={
                    "customer_id": context.get("customer_id"),
                    "risk_level": context.get("risk_level"),
                },
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, context: dict) -> dict:
        """
        Execute this agent's steps.

        Args:
            context: Shared mission context dict (read + write).

        Returns:
            Updated context dict.
        """
        ...

    def _log(self, context: dict, message: str, level: str = "INFO"):
        audit = context.setdefault("audit_log", [])
        audit.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent": self.name,
            "level": level,
            "message": message,
        })
