"""Dialogue data structures kept separate from core ACSP state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DialogueTurn:
    """One user-facing dialogue result.

    The dialogue layer is intentionally not persisted as raw chat transcript yet;
    it returns enough metadata for tests, adapters, and future memory policies.
    """

    user_id: str
    reply: str
    intent: str
    role: str = ""
    risk_level: str = "none"
    used_llm: bool = False
    sticker: dict[str, Any] | None = None
    tool_results: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
