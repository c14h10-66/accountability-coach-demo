"""Normalized message shapes for all adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MessageEnvelope:
    """Platform-neutral inbound message."""

    platform: str
    user_id: str
    conversation_id: str
    text: str
    received_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageResponse:
    """Platform-neutral outbound message."""

    conversation_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
