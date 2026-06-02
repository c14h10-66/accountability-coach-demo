"""Lightweight note memory helper built on UserState tracking memory."""

from __future__ import annotations

from accountability_coach.core.interfaces import UserStateStore
from accountability_coach.core.models import make_id, now_iso


class MemoryManager:
    """Stores small JSON-serializable notes in a user's shared state."""

    def __init__(self, storage: UserStateStore) -> None:
        self.storage = storage

    def remember(self, user_id: str, kind: str, content: str) -> dict:
        state = self.storage.load(user_id)
        memory = {
            "memory_id": make_id("memory"),
            "kind": kind,
            "content": content,
            "created_at": now_iso(),
        }
        state.tracking_state.setdefault("memories", []).append(memory)
        state.updated_at = now_iso()
        self.storage.save(state)
        return memory

    def recall(self, user_id: str, query: str = "", limit: int = 5) -> list[dict]:
        state = self.storage.load(user_id)
        memories = list(state.tracking_state.get("memories", []))
        if not query:
            return memories[-limit:]
        terms = {term.lower() for term in query.split() if term}
        scored: list[tuple[int, dict]] = []
        for memory in memories:
            content = str(memory.get("content", "")).lower()
            score = sum(1 for term in terms if term in content)
            if score:
                scored.append((score, memory))
        scored.sort(key=lambda item: -item[0])
        return [memory for _, memory in scored[:limit]]
