"""Adapter protocol for platform-specific message entry."""

from __future__ import annotations

from typing import Protocol

from accountability_coach.messaging.message import MessageResponse


class MessageAdapter(Protocol):
    """Bridge between a platform and the internal message bus."""

    async def start(self) -> None:
        """Start receiving messages."""

    async def stop(self) -> None:
        """Stop receiving messages."""

    async def send(self, response: MessageResponse) -> None:
        """Send a response back to the platform."""
