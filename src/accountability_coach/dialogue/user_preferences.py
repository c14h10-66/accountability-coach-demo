"""Explicit user profile commands for chat deployments."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from accountability_coach.core.models import UserState, now_iso


@dataclass(slots=True)
class PreferenceCommandResult:
    """A handled profile command."""

    reply: str
    changed_fields: dict[str, str] = field(default_factory=dict)


class UserPreferenceManager:
    """Handle explicit profile setup without involving the LLM router."""

    NICKNAME_PATTERNS = (
        re.compile(r"^(?:设置)?昵称\s*[:：]?\s*(?P<value>.{1,24})$"),
        re.compile(r"^我叫\s*(?P<value>[^，。！？\s]{1,24})$"),
    )
    TIMEZONE_PATTERNS = (
        re.compile(r"^(?:设置)?时区\s*[:：]?\s*(?P<value>[A-Za-z_]+/[A-Za-z0-9_+\-/]+)$"),
        re.compile(r"^我的时区是\s*(?P<value>[A-Za-z_]+/[A-Za-z0-9_+\-/]+)$"),
    )
    GOAL_PATTERNS = (
        re.compile(r"^(?:设置)?(?:学习)?目标\s*[:：]?\s*(?P<value>.{1,80})$"),
        re.compile(r"^我主要想(?:监督|推进|完成)\s*(?P<value>.{1,80})$"),
    )

    def handle(self, state: UserState, text: str) -> PreferenceCommandResult | None:
        command = text.strip()
        if not command:
            return None
        nickname = self._match(command, self.NICKNAME_PATTERNS)
        if nickname:
            return self._set_nickname(state, nickname)
        timezone = self._match(command, self.TIMEZONE_PATTERNS)
        if timezone:
            return self._set_timezone(state, timezone)
        goal = self._match(command, self.GOAL_PATTERNS)
        if goal:
            return self._set_goal(state, goal)
        return None

    def onboarding_hint(self, state: UserState) -> str:
        missing: list[str] = []
        if not state.profile.get("display_name"):
            missing.append("设置昵称 小周")
        if not state.profile.get("timezone") and not state.supervision.constraints.get("timezone"):
            missing.append("设置时区 Asia/Shanghai")
        if not state.supervision.goals:
            missing.append("设置目标 期末复习")
        if not missing:
            return ""
        examples = "、".join(f"“{item}”" for item in missing[:3])
        return f"第一次用的话，可以先发 {examples}。不设置也可以，直接说任务就行。"

    def _set_nickname(self, state: UserState, value: str) -> PreferenceCommandResult:
        nickname = self._clean_value(value, max_len=24)
        if not nickname:
            return PreferenceCommandResult("昵称我没看清。可以发：设置昵称 小周。")
        state.profile["display_name"] = nickname
        state.updated_at = now_iso()
        return PreferenceCommandResult(
            reply=f"好，以后我叫你{nickname}。",
            changed_fields={"display_name": nickname},
        )

    def _set_timezone(self, state: UserState, value: str) -> PreferenceCommandResult:
        timezone_name = value.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return PreferenceCommandResult(
                "这个时区我没认出来。可以用 IANA 名称，比如 Asia/Shanghai、Europe/Stockholm。"
            )
        state.profile["timezone"] = timezone_name
        state.supervision.constraints["timezone"] = timezone_name
        state.updated_at = now_iso()
        return PreferenceCommandResult(
            reply=f"好，之后按 {timezone_name} 的时间提醒你。",
            changed_fields={"timezone": timezone_name},
        )

    def _set_goal(self, state: UserState, value: str) -> PreferenceCommandResult:
        goal = self._clean_value(value, max_len=80)
        if not goal:
            return PreferenceCommandResult("目标我没看清。可以发：设置目标 期末复习。")
        if goal not in state.supervision.goals:
            state.supervision.goals.append(goal)
        state.updated_at = now_iso()
        return PreferenceCommandResult(
            reply=f"记下了，主要目标：{goal}。",
            changed_fields={"goal": goal},
        )

    def _match(self, text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
        for pattern in patterns:
            match = pattern.match(text)
            if match:
                return match.group("value").strip()
        return ""

    def _clean_value(self, value: str, *, max_len: int) -> str:
        return value.strip().strip("“”\"'，。！？ ").replace("\n", " ")[:max_len].strip()
