"""Long-horizon dialogue memory for companionship-style coaching."""

from __future__ import annotations

from typing import Any

from accountability_coach.core.models import UserState, now_iso


class DialogueMemory:
    """Persist dialogue events while exposing a bounded LLM context window.

    The full archive supports long-term accountability supervision.  The
    context method deliberately returns only recent events plus salient moments
    so the model can stay grounded without receiving an ever-growing transcript.
    """

    SALIENT_INTENTS = {
        "add_task",
        "plan",
        "checkin",
        "emotion",
        "commitment",
        "copresence",
        "schedule_reminder",
        "risk_escalation",
    }

    CONTEXT_KEYS = {
        "temporal_anchor",
        "current_topic",
        "pending_intention",
        "user_constraint",
        "user_preference",
        "next_follow_up",
    }

    def __init__(
        self,
        max_archive_events: int = 5000,
        max_context_events: int = 16,
        max_salient_events: int = 200,
    ) -> None:
        self.max_archive_events = max_archive_events
        self.max_context_events = max_context_events
        self.max_salient_events = max_salient_events

    def record_event(
        self,
        state: UserState,
        *,
        speaker: str,
        text: str,
        intent: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        memory = self._memory(state)
        archive = list(memory.get("archive", []) or [])
        event = {
            "event_id": int(memory.get("event_count", 0) or 0) + 1,
            "created_at": now_iso(),
            "speaker": speaker,
            "intent": intent,
            "text": text[:1000],
            "metadata": metadata or {},
        }
        archive.append(event)
        if len(archive) > self.max_archive_events:
            archive = archive[-self.max_archive_events :]
        memory["archive"] = archive
        memory["event_count"] = int(event["event_id"])
        memory["recent_events"] = self._compact_events(archive[-self.max_context_events :])
        if intent in self.SALIENT_INTENTS:
            salient = list(memory.get("salient_events", []) or [])
            salient.append(self._compact_event(event))
            memory["salient_events"] = salient[-self.max_salient_events :]
        self._merge_working_context(memory, metadata or {})
        memory["long_term_summary"] = self._summary(memory)
        state.tracking_state["dialogue_memory"] = memory
        state.tracking_state["recent_dialogue"] = memory["recent_events"]

    def context(self, state: UserState) -> dict[str, Any]:
        memory = self._memory(state)
        archive = list(memory.get("archive", []) or [])
        recent = memory.get("recent_events") or self._compact_events(archive[-self.max_context_events :])
        return {
            "long_term_summary": str(memory.get("long_term_summary") or self._summary(memory)),
            "working_context": dict(memory.get("working_context", {}) or {}),
            "recent_events": recent,
            "salient_events": list(memory.get("salient_events", []) or [])[-12:],
        }

    def _memory(self, state: UserState) -> dict[str, Any]:
        memory = state.tracking_state.get("dialogue_memory")
        if isinstance(memory, dict):
            return memory
        legacy_recent = state.tracking_state.get("recent_dialogue")
        recent = legacy_recent if isinstance(legacy_recent, list) else []
        return {
            "archive": list(recent),
            "event_count": len(recent),
            "recent_events": self._compact_events(recent[-self.max_context_events :]),
            "salient_events": [],
            "working_context": {},
            "long_term_summary": "",
        }

    def _merge_working_context(self, memory: dict[str, Any], metadata: dict[str, Any]) -> None:
        update = metadata.get("conversation_update")
        if not isinstance(update, dict):
            action = metadata.get("action")
            update = action.get("conversation_update") if isinstance(action, dict) else {}
        if not isinstance(update, dict):
            return
        working = dict(memory.get("working_context", {}) or {})
        for key in self.CONTEXT_KEYS:
            value = update.get(key)
            if value in (None, "", [], {}):
                continue
            working[key] = str(value)[:300]
        clear_keys = update.get("clear")
        if isinstance(clear_keys, list):
            for key in clear_keys:
                working.pop(str(key), None)
        memory["working_context"] = working

    def _compact_events(self, events: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [self._compact_event(event) for event in events if isinstance(event, dict)]

    def _compact_event(self, event: dict[str, Any]) -> dict[str, str]:
        return {
            "speaker": str(event.get("speaker", "")),
            "intent": str(event.get("intent", "")),
            "text": str(event.get("text", ""))[:260],
            "created_at": str(event.get("created_at", "")),
        }

    def _summary(self, memory: dict[str, Any]) -> str:
        event_count = int(memory.get("event_count", 0) or 0)
        salient_count = len(memory.get("salient_events", []) or [])
        return f"累计对话事件 {event_count} 条，其中关键监督事件 {salient_count} 条。"
