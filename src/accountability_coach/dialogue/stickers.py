"""Optional sticker selection for dialogue adapters.

The sticker layer is deliberately presentation-only.  It reads structured
dialogue state and returns an optional attachment description that adapters can
render as an image, a platform sticker, or a text fallback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from accountability_coach.core.models import RISK_NONE, UserState, now_iso


@dataclass(slots=True)
class Sticker:
    """A sticker asset or fallback expression pack entry."""

    sticker_id: str
    label: str
    alt_text: str
    tags: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    asset_path: str = ""
    platform_key: str = ""
    fallback_text: str = ""
    weight: int = 1

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class StickerLibrary:
    """Select low-frequency contextual stickers without owning conversation logic."""

    DEFAULT_STICKERS: tuple[Sticker, ...] = (
        Sticker(
            sticker_id="coach_nod",
            label="小教练点头",
            alt_text="小教练点头表示收到",
            tags=["ack", "steady"],
            intents=["add_task", "plan", "chat"],
            fallback_text="小教练点头",
        ),
        Sticker(
            sticker_id="coach_blanket",
            label="先给你降压",
            alt_text="小教练递来一条毯子，表示先缓一缓",
            tags=["support", "low_pressure", "companionate"],
            intents=["emotion"],
            fallback_text="先给你降压",
        ),
        Sticker(
            sticker_id="coach_confetti",
            label="小小庆祝",
            alt_text="小教练撒了一点彩花庆祝完成",
            tags=["celebrate", "completion"],
            intents=["checkin"],
            fallback_text="小小庆祝",
        ),
        Sticker(
            sticker_id="coach_timer",
            label="计时器就位",
            alt_text="小教练抱着计时器准备提醒",
            tags=["reminder", "timer"],
            intents=["schedule_reminder", "schedule_break_reminders", "copresence"],
            fallback_text="计时器就位",
        ),
        Sticker(
            sticker_id="coach_steady",
            label="稳住不急",
            alt_text="小教练做了一个稳住的手势",
            tags=["steady", "reframe"],
            intents=["review", "commitment", "chat"],
            fallback_text="稳住不急",
        ),
    )

    def __init__(
        self,
        stickers: list[Sticker] | None = None,
        min_turn_gap: int = 3,
        max_daily: int = 8,
        enabled: bool = False,
    ) -> None:
        self.stickers = stickers or list(self.DEFAULT_STICKERS)
        self.min_turn_gap = max(0, int(min_turn_gap))
        self.max_daily = max(0, int(max_daily))
        self.enabled = enabled

    def choose(
        self,
        state: UserState,
        *,
        intent: str,
        policy_context: dict[str, Any],
        risk_level: str = RISK_NONE,
        tool_results: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return one sticker payload when the turn is eligible.

        The cadence state is stored in ``tracking_state`` so adapters remain
        stateless and the feature works across long-running sessions.
        """
        sticker_state = self._sticker_state(state)
        self._reset_daily_count(sticker_state)
        if not self._enabled(state, risk_level):
            sticker_state["turns_since_last"] = int(sticker_state.get("turns_since_last", 0) or 0) + 1
            return None

        candidate_tags = self._candidate_tags(intent, policy_context, tool_results or {})
        candidate = self._best_candidate(intent, candidate_tags)
        if candidate is None:
            sticker_state["turns_since_last"] = int(sticker_state.get("turns_since_last", 0) or 0) + 1
            return None

        if not self._cadence_allows(sticker_state, candidate_tags):
            sticker_state["turns_since_last"] = int(sticker_state.get("turns_since_last", 0) or 0) + 1
            return None

        payload = candidate.to_payload()
        payload["reason_tags"] = sorted(candidate_tags)
        payload["selected_at"] = now_iso()
        sticker_state["turns_since_last"] = 0
        sticker_state["sent_today"] = int(sticker_state.get("sent_today", 0) or 0) + 1
        sticker_state["last_sticker_id"] = candidate.sticker_id
        sticker_state["last_sent_at"] = payload["selected_at"]
        sticker_state["history"] = (list(sticker_state.get("history", []) or []) + [payload])[-50:]
        state.tracking_state["sticker_state"] = sticker_state
        return payload

    def render_for_text_adapter(self, sticker: dict[str, Any] | None) -> str:
        """Render a sticker payload for terminals that cannot show images."""
        if not sticker:
            return ""
        label = str(sticker.get("fallback_text") or sticker.get("label") or "表情包").strip()
        return f"[表情包：{label}]"

    def _enabled(self, state: UserState, risk_level: str) -> bool:
        if not self.enabled:
            return False
        if risk_level != RISK_NONE or state.intervention_paused:
            return False
        value = state.profile.get("stickers_enabled", True)
        return bool(value)

    def _sticker_state(self, state: UserState) -> dict[str, Any]:
        sticker_state = state.tracking_state.get("sticker_state")
        if isinstance(sticker_state, dict):
            return sticker_state
        sticker_state = {
            "turns_since_last": self.min_turn_gap,
            "sent_today": 0,
            "sent_date": now_iso()[:10],
            "history": [],
        }
        state.tracking_state["sticker_state"] = sticker_state
        return sticker_state

    def _reset_daily_count(self, sticker_state: dict[str, Any]) -> None:
        today = now_iso()[:10]
        if sticker_state.get("sent_date") != today:
            sticker_state["sent_date"] = today
            sticker_state["sent_today"] = 0

    def _candidate_tags(
        self,
        intent: str,
        policy_context: dict[str, Any],
        tool_results: dict[str, Any],
    ) -> set[str]:
        tags = {intent}
        response_register = str(policy_context.get("response_register") or "")
        if response_register:
            tags.add(response_register)
        if response_register in {"low_pressure", "companionate_support"}:
            tags.add("support")
        payload_status = ""
        checkin_result = tool_results.get("checkin_result") if isinstance(tool_results, dict) else {}
        if isinstance(checkin_result, dict):
            checkin = checkin_result.get("checkin")
            if isinstance(checkin, dict):
                payload_status = str(checkin.get("status") or "")
        if payload_status == "completed":
            tags.add("completion")
            tags.add("celebrate")
        if intent in {"schedule_reminder", "schedule_break_reminders"}:
            tags.add("reminder")
        return tags

    def _best_candidate(self, intent: str, tags: set[str]) -> Sticker | None:
        scored: list[tuple[int, Sticker]] = []
        for sticker in self.stickers:
            score = 0
            if intent in sticker.intents:
                score += 3
            score += len(tags & set(sticker.tags))
            if score:
                scored.append((score + sticker.weight, sticker))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1].sticker_id))
        return scored[0][1]

    def _cadence_allows(self, sticker_state: dict[str, Any], tags: set[str]) -> bool:
        if self.max_daily and int(sticker_state.get("sent_today", 0) or 0) >= self.max_daily:
            return False
        gap = int(sticker_state.get("turns_since_last", self.min_turn_gap) or 0)
        urgent_social_feedback = bool({"completion", "support"} & tags)
        required_gap = 1 if urgent_social_feedback else self.min_turn_gap
        return gap >= required_gap
