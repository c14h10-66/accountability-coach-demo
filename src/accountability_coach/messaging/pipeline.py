"""Async message pipeline for future platform adapters."""

from __future__ import annotations

import json
from typing import Protocol

from accountability_coach.core.coordinator import CentralCoordinator
from accountability_coach.messaging.message import MessageEnvelope, MessageResponse


class PipelineStage(Protocol):
    """A stage that can process or decorate a message."""

    async def process(self, message: MessageEnvelope) -> MessageEnvelope:
        """Process an inbound message."""


class MessagePipeline:
    """Sequential pipeline inspired by adapter plus event-bus bot runtimes."""

    def __init__(
        self,
        coordinator: CentralCoordinator | None = None,
        stages: list[PipelineStage] | None = None,
    ) -> None:
        self.coordinator = coordinator or CentralCoordinator()
        self.stages = stages or []

    async def execute(self, message: MessageEnvelope) -> MessageResponse:
        current = message
        for stage in self.stages:
            current = await stage.process(current)
        payload = self._route_text(current)
        return MessageResponse(
            conversation_id=current.conversation_id,
            text=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )

    def _route_text(self, message: MessageEnvelope) -> dict:
        text = message.text.strip()
        if text == "/status":
            return self.coordinator.query_status(message.user_id)
        if text == "/plan":
            state = self.coordinator.plan_schedule(message.user_id)
            return {"planned_blocks": len(state.schedule), "state": "planned"}
        return {
            "message": "Unsupported message command. Use /status or /plan for this lightweight adapter.",
            "user_id": message.user_id,
        }
