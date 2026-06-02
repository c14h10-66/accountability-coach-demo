"""Schedule Planning Agent: priority, efficiency, and state adaptation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from accountability_coach.core.models import (
    TASK_COMPLETED,
    TASK_DEFERRED,
    TASK_PENDING,
    TASK_PLANNED,
    ScheduleBlock,
    Task,
    UserState,
    iso_from_datetime,
    make_id,
    now_iso,
    parse_datetime,
)


class SchedulePlanningAgent:
    """Planning scaffolding from Sections 3.3.2 and 4.3."""

    PRIORITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0, "urgent": 4.0}

    def build_initial_schedule(
        self,
        user_state: UserState,
        current_datetime: datetime | None = None,
        options: dict[str, Any] | None = None,
        adjustment: dict[str, object] | None = None,
    ) -> list[ScheduleBlock]:
        """Build a Pomodoro-style schedule using ACSP planning strategies."""
        options = options or {}
        start = current_datetime or datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        adjustment = adjustment or user_state.tracking_state.get("emotional_adjustment", {})
        intensity = float(adjustment.get("schedule_intensity_multiplier", 1.0))
        adaptation = self._state_adaptation(user_state, intensity)
        focus_minutes = adaptation["focus_minutes"]
        break_minutes = adaptation["break_minutes"]
        max_blocks = int(options.get("max_blocks") or adaptation["max_blocks"])
        daily_minutes = int(options.get("available_minutes") or adaptation["daily_minutes"])

        tasks = [
            task
            for task in user_state.tasks
            if task.status not in {TASK_COMPLETED, TASK_DEFERRED}
            and (task.remaining_minutes if task.remaining_minutes is not None else task.estimated_minutes) > 0
        ]
        ranked = sorted(
            tasks,
            key=lambda task: self._priority_score(task, start),
            reverse=True,
        )
        if adaptation["essential_only"]:
            essential = [
                task
                for task in ranked
                if self._quadrant(task, start) in {"urgent_important", "not_urgent_important"}
            ]
            ranked = essential or ranked[:1]

        schedule: list[ScheduleBlock] = []
        cursor = start + timedelta(minutes=int(options.get("start_delay_minutes", 5)))
        minutes_budget = max(15, daily_minutes)
        used_minutes = 0

        for task in ranked:
            remaining = task.remaining_minutes if task.remaining_minutes is not None else task.estimated_minutes
            remaining = max(0, int(remaining))
            if remaining <= 0:
                continue
            cycles = max(1, (remaining + focus_minutes - 1) // focus_minutes)
            cycles = min(cycles, adaptation["max_cycles_per_task"])
            for cycle in range(1, cycles + 1):
                if len(schedule) >= max_blocks or used_minutes + focus_minutes > minutes_budget:
                    break
                actual_focus = min(focus_minutes, remaining)
                block_start = cursor
                block_end = block_start + timedelta(minutes=actual_focus)
                quadrant = self._quadrant(task, start)
                is_essential = (
                    quadrant in {"urgent_important", "not_urgent_important"}
                    or task.priority == "urgent"
                )
                schedule.append(
                    ScheduleBlock(
                        block_id=make_id("block"),
                        task_id=task.task_id,
                        title=task.title,
                        start_at=iso_from_datetime(block_start),
                        end_at=iso_from_datetime(block_end),
                        focus_minutes=actual_focus,
                        break_minutes=break_minutes,
                        status=TASK_PLANNED,
                        pomodoro_index=cycle,
                        quadrant=quadrant,
                        priority_score=round(self._priority_score(task, start), 3),
                        cognitive_load=self._cognitive_load(task, actual_focus),
                        energy_alignment=adaptation["energy_alignment"],
                        is_essential=is_essential,
                        checkin_due_at=iso_from_datetime(block_end + timedelta(minutes=5)),
                        strategy_tags=[
                            "eisenhower",
                            "pomodoro",
                            "state_adaptive",
                        ],
                    )
                )
                cursor = block_end + timedelta(minutes=break_minutes)
                used_minutes += actual_focus
                remaining -= actual_focus
            if len(schedule) >= max_blocks or used_minutes >= minutes_budget:
                break

        for task in tasks:
            if any(block.task_id == task.task_id for block in schedule):
                task.status = TASK_PLANNED
                task.updated_at = now_iso()
        user_state.schedule = schedule
        user_state.tracking_state["last_schedule_generated_at"] = now_iso()
        user_state.tracking_state["planning_strategy"] = adaptation
        user_state.acsp_layer = "operational"
        user_state.updated_at = now_iso()
        return schedule

    def adapt_schedule_after_feedback(
        self,
        user_state: UserState,
        feedback: dict[str, Any] | None = None,
        current_datetime: datetime | None = None,
    ) -> list[ScheduleBlock]:
        """Recalibrate future load after DaKa feedback or emotional downgrade."""
        feedback = feedback or {}
        completed_or_past = [
            block
            for block in user_state.schedule
            if block.status == TASK_COMPLETED
        ]
        options = {
            "available_minutes": feedback.get("available_minutes"),
            "max_blocks": feedback.get("max_blocks"),
            "start_delay_minutes": feedback.get("start_delay_minutes", 10),
        }
        updated = self.build_initial_schedule(
            user_state,
            current_datetime=current_datetime,
            options={key: value for key, value in options.items() if value is not None},
            adjustment=feedback.get("emotional_adjustment"),
        )
        user_state.schedule = completed_or_past + updated
        user_state.tracking_state["last_replan_reason"] = str(
            feedback.get("reason") or "feedback"
        )
        user_state.updated_at = now_iso()
        return user_state.schedule

    def classify_task(self, task: Task, now: datetime | None = None) -> str:
        return self._quadrant(task, now or datetime.now(timezone.utc))

    def _state_adaptation(
        self,
        user_state: UserState,
        schedule_multiplier: float,
    ) -> dict[str, Any]:
        skip_streak = int(user_state.tracking_state.get("recent_skip_streak", 0) or 0)
        under_streak = int(user_state.tracking_state.get("under_completion_streak", 0) or 0)
        low_morale = user_state.emotion.morale < 0.4 or user_state.emotion.energy < 0.4
        procrastination = skip_streak >= 2 or under_streak >= 2

        if low_morale or schedule_multiplier <= 0.65:
            return {
                "focus_minutes": 15,
                "break_minutes": 10,
                "max_blocks": 3,
                "max_cycles_per_task": 2,
                "daily_minutes": int(90 * schedule_multiplier),
                "essential_only": True,
                "energy_alignment": "low_load",
            }
        if procrastination or schedule_multiplier < 0.9:
            return {
                "focus_minutes": 20,
                "break_minutes": 8,
                "max_blocks": 4,
                "max_cycles_per_task": 2,
                "daily_minutes": int(120 * schedule_multiplier),
                "essential_only": True,
                "energy_alignment": "recovery",
            }
        if schedule_multiplier > 1.05:
            return {
                "focus_minutes": 25,
                "break_minutes": 5,
                "max_blocks": 8,
                "max_cycles_per_task": 4,
                "daily_minutes": int(220 * schedule_multiplier),
                "essential_only": False,
                "energy_alignment": "high_capacity",
            }
        return {
            "focus_minutes": 25,
            "break_minutes": 5,
            "max_blocks": 6,
            "max_cycles_per_task": 3,
            "daily_minutes": int(180 * schedule_multiplier),
            "essential_only": False,
            "energy_alignment": "normal",
        }

    def _priority_score(self, task: Task, now: datetime) -> float:
        priority = self.PRIORITY_WEIGHT.get(task.priority, 2.0)
        importance = max(1, min(5, task.importance)) / 5.0
        deadline = parse_datetime(task.deadline)
        urgency = 0.0
        if deadline:
            hours = (deadline - now).total_seconds() / 3600
            if hours <= 0:
                urgency = 5.0
            elif hours <= 24:
                urgency = 4.0
            elif hours <= 72:
                urgency = 3.0
            elif hours <= 168:
                urgency = 2.0
            else:
                urgency = 1.0
        difficulty_penalty = max(0, task.difficulty - 3) * 0.15
        return priority + urgency + (importance * 2.0) - difficulty_penalty

    def _quadrant(self, task: Task, now: datetime) -> str:
        important = task.importance >= 4 or task.priority in {"high", "urgent"}
        deadline = parse_datetime(task.deadline)
        urgent = task.priority == "urgent"
        if deadline:
            urgent = urgent or (deadline - now).total_seconds() <= 72 * 3600
        if urgent and important:
            return "urgent_important"
        if urgent and not important:
            return "urgent_not_important"
        if important:
            return "not_urgent_important"
        return "not_urgent_not_important"

    def _cognitive_load(self, task: Task, focus_minutes: int) -> str:
        if task.difficulty >= 4 or focus_minutes >= 25:
            return "high"
        if task.difficulty <= 2 or focus_minutes <= 15:
            return "low"
        return "medium"


SchedulePlanning = SchedulePlanningAgent
