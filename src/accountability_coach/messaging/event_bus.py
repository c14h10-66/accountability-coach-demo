"""Async event bus for normalized adapter messages."""

from __future__ import annotations

import asyncio

from accountability_coach.messaging.message import MessageEnvelope, MessageResponse
from accountability_coach.messaging.pipeline import MessagePipeline


class EventBus:
    """Receives adapter events and dispatches them to the message pipeline."""

    def __init__(self, pipeline: MessagePipeline) -> None:
        self.pipeline = pipeline
        self.queue: asyncio.Queue[MessageEnvelope] = asyncio.Queue()
        self.responses: asyncio.Queue[MessageResponse] = asyncio.Queue()
        self._running = False

    async def publish(self, message: MessageEnvelope) -> None:
        await self.queue.put(message)

    async def dispatch_once(self) -> MessageResponse:
        message = await self.queue.get()
        response = await self.pipeline.execute(message)
        await self.responses.put(response)
        return response

    async def dispatch_forever(self) -> None:
        self._running = True
        while self._running:
            await self.dispatch_once()

    def stop(self) -> None:
        self._running = False
