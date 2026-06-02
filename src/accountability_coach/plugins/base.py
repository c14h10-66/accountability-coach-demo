"""Plugin protocols for extending the coach."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from accountability_coach.core.coordinator import CentralCoordinator
from accountability_coach.messaging.message import MessageEnvelope, MessageResponse


@dataclass(slots=True)
class PluginContext:
    """Stable context exposed to plugins."""

    coordinator: CentralCoordinator


class CoachPlugin(Protocol):
    """Lifecycle-aware plugin boundary."""

    name: str

    async def initialize(self, context: PluginContext) -> None:
        """Called when a plugin is activated."""

    async def before_message(self, message: MessageEnvelope) -> MessageEnvelope:
        """Hook before the message reaches the coordinator."""

    async def after_message(
        self,
        message: MessageEnvelope,
        response: MessageResponse,
    ) -> MessageResponse:
        """Hook after the coordinator produces a response."""

    async def terminate(self) -> None:
        """Called when a plugin is deactivated."""
