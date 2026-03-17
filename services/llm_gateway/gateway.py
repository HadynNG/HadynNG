"""
LLM Gateway — centralised LLM proxy for all agents and services.

Every component that needs LLM inference calls this gateway instead of
creating its own Ollama client. This provides:
  - Single connection pool to the Ollama server
  - Consistent generation parameters
  - Token usage tracking and request logging
  - Model routing (future: multiple models for different tasks)
  - Caching for repeated identical prompts (via Redis when available)
"""
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Generator, Optional

import ollama
from rich.console import Console

console = Console()

# Try Redis for caching; graceful fallback to in-memory LRU
try:
    import redis as _redis_mod
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class LLMGateway:
    """
    Centralised LLM inference gateway.

    All agents and services should use this instead of direct Ollama calls.
    """

    def __init__(
        self,
        model: str = "qwen3.5:9b",
        ollama_host: str = "http://localhost:11434",
        redis_url: Optional[str] = None,
        cache_ttl: int = 3600,
    ):
        self.model = model
        self.ollama_host = ollama_host
        self.client = ollama.Client(host=ollama_host)
        self.cache_ttl = cache_ttl
        self._stats = {"requests": 0, "cached_hits": 0, "errors": 0}
        self._memory_cache: dict[str, str] = {}

        # Redis cache (optional)
        self._redis: Optional[object] = None
        if redis_url and _REDIS_AVAILABLE:
            try:
                self._redis = _redis_mod.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        max_tokens: int = 2048,
        seed: int = 42,
        think: bool = True,
        use_cache: bool = False,
        model_override: Optional[str] = None,
    ) -> dict:
        """
        Non-streaming LLM call. Returns dict with thinking + content.

        Args:
            system_prompt: System message.
            user_prompt: User message.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            seed: Random seed for reproducibility.
            think: Enable chain-of-thought mode.
            use_cache: Cache this response (for deterministic queries).
            model_override: Use a different model for this call.

        Returns:
            {"thinking": str, "content": str, "model": str, "cached": bool}
        """
        self._stats["requests"] += 1
        model = model_override or self.model

        # Check cache
        if use_cache:
            cache_key = self._cache_key(model, system_prompt, user_prompt, temperature, seed)
            cached = self._get_cache(cache_key)
            if cached is not None:
                self._stats["cached_hits"] += 1
                return {"thinking": "", "content": cached, "model": model, "cached": True}

        try:
            response = self.client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                think=think,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "repeat_penalty": 1.1,
                    "seed": seed,
                },
            )

            thinking = ""
            if hasattr(response.message, "thinking") and response.message.thinking:
                thinking = response.message.thinking
            content = response.message.content or ""

            # Clean special tokens
            content = re.sub(r"<\|[^|]+\|>.*", "", content, flags=re.DOTALL).strip()

            if use_cache:
                self._set_cache(cache_key, content)

            return {"thinking": thinking, "content": content, "model": model, "cached": False}

        except Exception as e:
            self._stats["errors"] += 1
            raise LLMGatewayError(f"LLM call failed: {e}") from e

    def stream(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.05,
        max_tokens: int = 2048,
        seed: int = 42,
        think: bool = True,
        model_override: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        """
        Streaming LLM call. Yields chunks with type "thinking" or "content".

        Yields:
            {"type": "thinking"|"content", "text": str}
        """
        self._stats["requests"] += 1
        model = model_override or self.model

        # Character-level safety caps
        max_thinking_chars = max_tokens * 6
        max_content_chars = max_tokens * 4
        thinking_len = 0
        content_len = 0

        try:
            stream = self.client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
                think=think,
                options={
                    "temperature": temperature,
                    "num_predict": max_tokens,
                    "repeat_penalty": 1.1,
                    "seed": seed,
                },
            )

            for chunk in stream:
                msg = chunk.message

                if hasattr(msg, "thinking") and msg.thinking:
                    thinking_len += len(msg.thinking)
                    if thinking_len > max_thinking_chars:
                        yield {"type": "truncated", "text": "[thinking truncated]"}
                        break
                    yield {"type": "thinking", "text": msg.thinking}

                if msg.content:
                    # Stop at special tokens
                    if "<|endoftext|>" in msg.content or "<|im_end|>" in msg.content:
                        stop_at = min(
                            (msg.content.find(t) for t in ("<|endoftext|>", "<|im_end|>") if t in msg.content)
                        )
                        tail = msg.content[:stop_at]
                        if tail:
                            yield {"type": "content", "text": tail}
                        break

                    content_len += len(msg.content)
                    if content_len > max_content_chars:
                        yield {"type": "truncated", "text": "[content truncated]"}
                        break
                    yield {"type": "content", "text": msg.content}

        except Exception as e:
            self._stats["errors"] += 1
            raise LLMGatewayError(f"LLM stream failed: {e}") from e

    def extract_json(self, text: str) -> dict:
        """Extract first valid JSON object from LLM output."""
        text = re.sub(r"<\|[^|]+\|>.*", "", text, flags=re.DOTALL).strip()

        # Try fenced code block
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

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def health_check(self) -> dict:
        """Check Ollama connectivity and model availability."""
        try:
            models = self.client.list()
            model_names = [m.model for m in models.models]
            available = self.model in model_names
            return {"status": "ok", "model": self.model, "model_available": available,
                    "models_loaded": model_names}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Cache helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(model: str, system: str, user: str, temp: float, seed: int) -> str:
        raw = f"{model}:{temp}:{seed}:{system}:{user}"
        return f"llm_cache:{hashlib.sha256(raw.encode()).hexdigest()}"

    def _get_cache(self, key: str) -> Optional[str]:
        if self._redis:
            try:
                return self._redis.get(key)
            except Exception:
                pass
        return self._memory_cache.get(key)

    def _set_cache(self, key: str, value: str):
        if self._redis:
            try:
                self._redis.setex(key, self.cache_ttl, value)
                return
            except Exception:
                pass
        self._memory_cache[key] = value


class LLMGatewayError(Exception):
    """Raised when LLM inference fails."""
