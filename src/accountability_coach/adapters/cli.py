"""Interactive CLI adapter for the message event bus."""

from __future__ import annotations

from datetime import datetime, timezone

from accountability_coach.messaging.event_bus import EventBus
from accountability_coach.messaging.message import MessageEnvelope, MessageResponse


class CLIAdapter:
    """Minimal terminal adapter for future message-entry integrations."""

    def __init__(self, event_bus: EventBus, user_id: str = "cli_user") -> None:
        self.event_bus = event_bus
        self.user_id = user_id
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            text = input("> ").strip()
            if text in {"/quit", "/exit"}:
                await self.stop()
                break
            await self.event_bus.publish(
                MessageEnvelope(
                    platform="cli",
                    user_id=self.user_id,
                    conversation_id=self.user_id,
                    text=text,
                    received_at=datetime.now(timezone.utc),
                )
            )
            response = await self.event_bus.dispatch_once()
            await self.send(response)

    async def stop(self) -> None:
        self._running = False

    async def send(self, response: MessageResponse) -> None:
        print(response.text)
