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

    def __init__(self, model: str = "qwen3.5:9b", ollama_host: str = "http://localhost:11434"):
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
        temperature: float = 0.05,
        max_tokens: int = 2048,
    ) -> tuple[str, str]:
        """
        Call the LLM, stream output, and return (thinking, content).
        Displays the chain-of-thought in real time.

        Args:
            max_tokens: Hard cap on tokens generated (thinking + content).
                        Prevents infinite loops from model repetition cycles.
        """
        # Character-level safety caps (rough proxy for tokens; prevents runaway generation)
        MAX_THINKING_CHARS = max_tokens * 6   # thinking is verbose; allow ~6 chars/token
        MAX_CONTENT_CHARS  = max_tokens * 4

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
                # Handle native thinking tokens (ollama >= 0.4)
                if hasattr(msg, "thinking") and msg.thinking:
                    thinking_buffer += msg.thinking
                    if show_thinking:
                        print(f"\033[33m{msg.thinking}\033[0m", end="", flush=True)
                    # Safety: break if thinking exceeds character cap
                    if len(thinking_buffer) > MAX_THINKING_CHARS:
                        print()
                        console.print("\n[yellow]  [thinking truncated — generation cap reached][/yellow]")
                        break
                if msg.content:
                    if not content_buffer and thinking_buffer:
                        # Transition from thinking to content
                        print()
                        console.print("[dim]  └────────────────────────────────────────[/dim]")
                        console.print("[dim]  ┌─ Response ────────────────────────────────[/dim]")
                    # Stop at end-of-sequence special tokens emitted by some models
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
                    # Safety: break if content exceeds character cap
                    if len(content_buffer) > MAX_CONTENT_CHARS:
                        console.print("\n[yellow]  [response truncated — generation cap reached][/yellow]")
                        break

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
        """
        Extract the first valid balanced JSON object from text.
        Strips model special tokens before parsing.
        """
        # Remove special tokens (<|endoftext|>, <|im_end|>, etc.) and everything after
        text = re.sub(r"<\|[^|]+\|>.*", "", text, flags=re.DOTALL).strip()

        # Try fenced code block first
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
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
