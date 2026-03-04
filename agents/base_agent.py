"""
Base Agent — provides Ollama LLM integration and rich console output.
All KYC step agents inherit from this class.
"""
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime

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

    def __init__(self, model: str = "qwen3-coder-next:latest", ollama_host: str = "http://localhost:11434"):
        self.model = model
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
        temperature: float = 0.1,
    ) -> tuple[str, str]:
        """
        Call the LLM, stream output, and return (thinking, content).
        Displays the chain-of-thought in real time.
        """
        console.print(f"\n[dim italic]  Querying {self.model}...[/dim italic]")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        full_text = ""
        thinking_text = ""
        content_text = ""

        try:
            stream = self.client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                think=True,
                options={"temperature": temperature},
            )

            # Collect streaming output
            thinking_buffer = ""
            content_buffer = ""
            in_thinking = False

            console.print("[dim]  ┌─ Thinking ────────────────────────────────[/dim]")
            for chunk in stream:
                msg = chunk.message
                # Handle native thinking tokens (ollama >= 0.4)
                if hasattr(msg, "thinking") and msg.thinking:
                    chunk_thinking = msg.thinking
                    thinking_buffer += chunk_thinking
                    if show_thinking:
                        print(f"\033[33m{chunk_thinking}\033[0m", end="", flush=True)
                if msg.content:
                    if not content_buffer and thinking_buffer:
                        # Transition from thinking to content
                        print()  # newline after thinking
                        console.print("[dim]  └────────────────────────────────────────[/dim]")
                        console.print("[dim]  ┌─ Response ────────────────────────────────[/dim]")
                    content_buffer += msg.content
                    print(msg.content, end="", flush=True)

            print()  # final newline
            console.print("[dim]  └────────────────────────────────────────[/dim]")

            thinking_text = thinking_buffer
            content_text = content_buffer

            # Fallback: if the model embedded <think> tags in content
            if not thinking_text and "<think>" in content_text:
                thinking_text, content_text = _parse_thinking_and_content(content_text)

        except Exception as e:
            console.print(f"[red]  LLM error: {e}[/red]")
            content_text = f"[LLM unavailable: {e}]"

        return thinking_text.strip(), content_text.strip()

    def _extract_json(self, text: str) -> dict:
        """Try to extract JSON from LLM response text."""
        # Try code block first
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        # Try raw JSON
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            try:
                return json.loads(text[first_brace : last_brace + 1])
            except json.JSONDecodeError:
                pass
        return {}

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
