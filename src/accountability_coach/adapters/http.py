"""HTTP adapter configuration boundary.

The runnable HTTP server lives in `accountability_coach.entrypoints.http_api`.
This adapter object keeps a platform-adapter slot available for future event
bus based integrations.
"""

from __future__ import annotations

from accountability_coach.messaging.event_bus import EventBus
from accountability_coach.messaging.message import MessageResponse


class HTTPAdapter:
    """Minimal HTTP adapter descriptor."""

    def __init__(self, event_bus: EventBus, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.event_bus = event_bus
        self.host = host
        self.port = port
        self.running = False

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False

    async def send(self, response: MessageResponse) -> None:
        await self.event_bus.responses.put(response)
