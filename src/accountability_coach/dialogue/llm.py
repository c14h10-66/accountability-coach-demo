"""Small dependency-free LLM client abstraction.

The coach core remains framework-free.  When environment variables are present,
this module can call an OpenAI-compatible chat-completions endpoint via the
standard library.  Without a configured model, the natural-language dialogue
entrypoint reports that LLM routing is unavailable instead of pretending to
understand free text with brittle keyword rules.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Raised when an LLM provider fails or returns an invalid response."""


class LLMClient(Protocol):
    """Minimal chat interface used by DialogueAgent."""

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        """Return assistant text for the given chat messages."""

    def is_available(self) -> bool:
        """Return whether this client can make real model calls."""


@dataclass(slots=True)
class NullLLMClient:
    """Explicit no-op LLM used in tests and offline local development."""

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        raise LLMError("No LLM client configured")

    def is_available(self) -> bool:
        return False


@dataclass(slots=True)
class OpenAICompatibleLLMClient:
    """Call an OpenAI-compatible `/chat/completions` endpoint.

    Expected environment variables:
    - ACCOUNTABILITY_COACH_LLM_BASE_URL, e.g. https://api.openai.com/v1
    - ACCOUNTABILITY_COACH_LLM_API_KEY
    - ACCOUNTABILITY_COACH_LLM_MODEL
    """

    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 40

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response did not include choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM response content was empty")
        return content.strip()

    def is_available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def build_llm_from_env() -> LLMClient:
    """Create a configured LLM client, or NullLLMClient when offline."""
    base_url = os.getenv("ACCOUNTABILITY_COACH_LLM_BASE_URL", "").strip()
    api_key = os.getenv("ACCOUNTABILITY_COACH_LLM_API_KEY", "").strip()
    model = os.getenv("ACCOUNTABILITY_COACH_LLM_MODEL", "").strip()
    if base_url and api_key and model:
        return OpenAICompatibleLLMClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=int(os.getenv("ACCOUNTABILITY_COACH_LLM_TIMEOUT", "40")),
        )
    return NullLLMClient()
