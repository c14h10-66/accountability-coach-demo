"""Proactive conversation prompts and opt-in break reminders."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from accountability_coach.core.models import UserState, iso_from_datetime, parse_datetime


@dataclass(slots=True)
class ProactivePrompt:
    """A future message for an adapter to deliver proactively."""

    message: str
    due_at: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_push(self, user_id: str, push_id: str) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "push_id": push_id,
            "user_id": user_id,
            "message": payload["message"],
            "due_at": payload["due_at"],
            "status": "scheduled",
            "metadata": {
                **payload["metadata"],
                "reason": payload["reason"],
                "proactive": True,
            },
        }


class ProactiveConversationAgent:
    """Generate proactive touchpoints without owning delivery adapters."""

    def __init__(
        self,
        long_plan_minutes: int = 90,
        default_break_intervals: tuple[int, ...] = (30, 45),
        silence_followup_minutes: tuple[int, ...] = (8, 15),
    ) -> None:
        self.long_plan_minutes = long_plan_minutes
        self.default_break_intervals = default_break_intervals
        self.silence_followup_minutes = silence_followup_minutes

    def plan_checkpoints(self, state: UserState) -> list[ProactivePrompt]:
        prompts: list[ProactivePrompt] = []
        for index, block in enumerate(state.schedule, start=1):
            if block.start_at:
                prompts.append(
                    ProactivePrompt(
                        message=self._block_start_message(block.title, index),
                        due_at=block.start_at,
                        reason="planned_block_start",
                        metadata={
                            "block_id": block.block_id,
                            "task_id": block.task_id,
                            "title": block.title,
                            "sequence_index": index,
                            "follow_up_enabled": True,
                        },
                    )
                )
            if block.checkin_due_at:
                prompts.append(
                    ProactivePrompt(
                        message=self._block_checkin_message(block.title),
                        due_at=block.checkin_due_at,
                        reason="planned_block_checkin",
                        metadata={
                            "block_id": block.block_id,
                            "task_id": block.task_id,
                            "title": block.title,
                            "sequence_index": index,
                            "follow_up_enabled": True,
                        },
                    )
                )
        return prompts

    def silence_follow_up(
        self,
        delivered_push: dict[str, Any],
        delivered_at: datetime,
    ) -> ProactivePrompt | None:
        """Create a graduated follow-up when a planned touchpoint gets no reply."""
        metadata = delivered_push.get("metadata") if isinstance(delivered_push.get("metadata"), dict) else {}
        reason = str(metadata.get("reason") or "")
        source_reason = str(metadata.get("source_reason") or reason)
        if source_reason not in {"planned_block_start", "planned_block_checkin"}:
            return None
        if metadata.get("follow_up_enabled") is False:
            return None
        stage = int(metadata.get("follow_up_stage", 0) or 0) + 1
        if stage > len(self.silence_followup_minutes):
            return None
        delay = self.silence_followup_minutes[stage - 1]
        title = str(metadata.get("title") or self._title_from_message(str(delivered_push.get("message") or "")) or "这一段")
        due_at = delivered_at + timedelta(minutes=delay)
        return ProactivePrompt(
            message=self._silence_message(title, source_reason, stage),
            due_at=iso_from_datetime(due_at),
            reason="silence_followup",
            metadata={
                "parent_push_id": delivered_push.get("push_id"),
                "parent_delivered_at": iso_from_datetime(delivered_at),
                "follow_up_stage": stage,
                "source_reason": source_reason,
                "block_id": metadata.get("block_id"),
                "task_id": metadata.get("task_id"),
                "title": title,
                "follow_up_enabled": stage < len(self.silence_followup_minutes),
            },
        )

    def break_reminder_offer(self, state: UserState) -> dict[str, Any] | None:
        total_minutes = self._scheduled_focus_minutes(state)
        if total_minutes < self.long_plan_minutes:
            total_minutes = max(total_minutes, self._active_task_minutes(state))
        if total_minutes < self.long_plan_minutes:
            return None
        return {
            "type": "break_reminder_offer",
            "total_minutes": total_minutes,
            "suggested_intervals": list(self.default_break_intervals),
            "message": "这个计划时间比较长，可以询问用户是否需要周期性休息提醒。",
        }

    def break_reminders(
        self,
        state: UserState,
        *,
        interval_minutes: int,
        start_at: datetime | None = None,
        duration_minutes: int | None = None,
        message: str = "到休息点了，站起来喝口水，活动一下再继续。",
    ) -> list[ProactivePrompt]:
        interval = max(5, int(interval_minutes))
        window_start = start_at or self._schedule_start(state) or datetime.now(timezone.utc)
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        duration = duration_minutes or self._scheduled_focus_minutes(state) or interval
        duration = max(interval, int(duration))
        prompts: list[ProactivePrompt] = []
        elapsed = interval
        while elapsed < duration:
            due_at = window_start + timedelta(minutes=elapsed)
            prompts.append(
                ProactivePrompt(
                    message=message,
                    due_at=iso_from_datetime(due_at),
                    reason="break_reminder",
                    metadata={
                        "interval_minutes": interval,
                        "elapsed_minutes": elapsed,
                    },
                )
            )
            elapsed += interval
        return prompts

    def _scheduled_focus_minutes(self, state: UserState) -> int:
        return sum(max(0, int(block.focus_minutes or 0)) for block in state.schedule)

    def _active_task_minutes(self, state: UserState) -> int:
        total = 0
        for task in state.tasks:
            if task.status == "completed":
                continue
            total += int(task.remaining_minutes if task.remaining_minutes is not None else task.estimated_minutes)
        return total

    def _schedule_start(self, state: UserState) -> datetime | None:
        starts = [parse_datetime(block.start_at) for block in state.schedule if block.start_at]
        starts = [item for item in starts if item is not None]
        return min(starts) if starts else None

    def _block_start_message(self, title: str, index: int) -> str:
        if index <= 1:
            return f"这一段轮到「{title}」。先看一下自己现在能不能开始；不合适就回我一句，我帮你换个安排。"
        return f"下一段是「{title}」。先停半分钟看看自己；适合继续就接上，不适合就回我调整。"

    def _block_checkin_message(self, title: str) -> str:
        return f"这段「{title}」先收一下。回我完成、部分完成、卡住，或者要改计划。"

    def _silence_message(self, title: str, source_reason: str, stage: int) -> str:
        if stage <= 1 and source_reason == "planned_block_checkin":
            return f"刚才那段「{title}」没有收到结果。我先把压力放低，你只回一个词也行：完成、部分、卡住、跳过。"
        if stage <= 1:
            return f"我没收到你的回应，先不默认你在拖延。可能是在忙、累了，或者这段不合适。回我一个词就行：开始了、卡住、改小、休息。"
        return f"我先不继续催「{title}」了。等你回来，直接说现状；我会按新的状态重排，不按刚才那一版硬推。"

    def _title_from_message(self, message: str) -> str:
        if "「" in message and "」" in message:
            return message.split("「", 1)[1].split("」", 1)[0]
        return ""
