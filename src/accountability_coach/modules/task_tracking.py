"""Task Tracking Agent: reminders, DaKa updates, and execution metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from accountability_coach.core.models import (
    CHECKIN_COMPLETED,
    CHECKIN_DELAYED,
    CHECKIN_PARTIAL,
    CHECKIN_SKIPPED,
    REMINDER_ADAPTIVE,
    REMINDER_SCHEDULED,
    REMINDER_SPOT_CHECK,
    TASK_COMPLETED,
    TASK_DEFERRED,
    TASK_IN_PROGRESS,
    TASK_PLANNED,
    TASK_SKIPPED,
    CheckInRecord,
    ReminderEvent,
    ScheduleBlock,
    Task,
    TrackingInsights,
    UserState,
    iso_from_datetime,
    make_id,
    now_iso,
    parse_datetime,
)


class TaskTrackingAgent:
    """Accountability scaffolding from Sections 3.3.3 and 4.4."""

    JUSTIFIED_DELAY_TERMS = {
        "sick",
        "ill",
        "hospital",
        "emergency",
        "family",
        "network",
        "power",
        "teacher",
        "class",
        "exam changed",
        "deadline changed",
    }

    def get_due_reminders(
        self,
        user_state: UserState,
        now: datetime | None = None,
    ) -> list[ReminderEvent]:
        """Return scheduled, adaptive, and spot-check reminder decisions."""
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        adjustment = user_state.tracking_state.get("emotional_adjustment", {})
        frequency_multiplier = float(
            adjustment.get("reminder_frequency_multiplier", 1.0)
        )
        insights = self.derive_tracking_insights(user_state)
        reminders: list[ReminderEvent] = []

        for block in user_state.schedule:
            if block.status in {TASK_COMPLETED, TASK_SKIPPED, TASK_DEFERRED}:
                continue
            start = parse_datetime(block.start_at)
            end = parse_datetime(block.end_at)
            due = parse_datetime(block.checkin_due_at)
            if not start or not end:
                continue
            for offset in block.reminder_offsets_minutes:
                reminder_time = start + timedelta(minutes=offset)
                if reminder_time <= now <= reminder_time + timedelta(minutes=5):
                    reminders.append(
                        self._reminder(
                            user_state,
                            block,
                            reminder_time,
                            REMINDER_SCHEDULED,
                            "normal",
                            "baseline schedule prompt",
                        )
                    )

            overdue = bool(due and now > due and block.status != TASK_COMPLETED)
            if overdue or insights.needs_escalation:
                if self._adaptive_due(now, block, frequency_multiplier):
                    strength = "soft" if frequency_multiplier < 0.75 else "firm"
                    reminders.append(
                        self._reminder(
                            user_state,
                            block,
                            now,
                            REMINDER_ADAPTIVE,
                            strength,
                            "performance deviation or missing DaKa",
                        )
                    )

            if self._spot_check_due(user_state, block, now, frequency_multiplier):
                reminders.append(
                    self._reminder(
                        user_state,
                        block,
                        now,
                        REMINDER_SPOT_CHECK,
                        "light",
                        "random spot-check for accountability ritual",
                    )
                )
        return reminders

    def update_from_checkin(
        self,
        user_state: UserState,
        checkin: CheckInRecord,
    ) -> UserState:
        """Apply a DaKa check-in while trusting self-report as the baseline."""
        if checkin.status == CHECKIN_DELAYED and not checkin.justified_delay:
            checkin.justified_delay = self._is_justified_delay(checkin.delay_reason)
        user_state.checkins.append(checkin)

        block = self._find_block(user_state, checkin.block_id, checkin.task_id)
        task = self._find_task(user_state, checkin.task_id)

        if block:
            block.completed_checkin_id = checkin.checkin_id
            if checkin.status == CHECKIN_COMPLETED:
                block.status = TASK_COMPLETED
            elif checkin.status == CHECKIN_PARTIAL:
                block.status = TASK_IN_PROGRESS
            elif checkin.status == CHECKIN_SKIPPED:
                block.status = TASK_SKIPPED
            elif checkin.status == CHECKIN_DELAYED:
                block.status = TASK_DEFERRED if checkin.justified_delay else TASK_SKIPPED

        if task:
            self._update_task_from_checkin(task, checkin, block)

        insights = self.derive_tracking_insights(user_state)
        user_state.tracking_state.update(
            {
                "total_checkins": insights.total_checkins,
                "on_time_rate": insights.on_time_rate,
                "recent_skip_streak": insights.recent_skip_streak,
                "under_completion_streak": insights.under_completion_streak,
                "needs_escalation": insights.needs_escalation,
                "suggested_tracking_mode": insights.suggested_tracking_mode,
            }
        )
        user_state.updated_at = now_iso()
        return user_state

    def derive_tracking_insights(self, user_state: UserState) -> TrackingInsights:
        total = len(user_state.checkins)
        if total == 0:
            return TrackingInsights()

        completed = sum(1 for item in user_state.checkins if item.status == CHECKIN_COMPLETED)
        skipped = sum(1 for item in user_state.checkins if item.status == CHECKIN_SKIPPED)
        partial = sum(1 for item in user_state.checkins if item.status == CHECKIN_PARTIAL)
        avg_progress = sum(item.progress_percent for item in user_state.checkins) / total

        on_time_count = 0
        comparable = 0
        blocks_by_id = {block.block_id: block for block in user_state.schedule}
        for checkin in user_state.checkins:
            if not checkin.block_id or checkin.block_id not in blocks_by_id:
                continue
            due_at = parse_datetime(blocks_by_id[checkin.block_id].checkin_due_at)
            created_at = parse_datetime(checkin.created_at)
            if not due_at or not created_at:
                continue
            comparable += 1
            if created_at <= due_at + timedelta(minutes=5):
                on_time_count += 1
        on_time_rate = on_time_count / comparable if comparable else completed / total

        recent = user_state.checkins[-5:]
        skip_streak = self._streak(
            list(reversed(recent)),
            lambda item: item.status in {CHECKIN_SKIPPED, CHECKIN_DELAYED}
            and not item.justified_delay,
        )
        under_streak = self._streak(
            list(reversed(recent)),
            lambda item: item.status != CHECKIN_COMPLETED or item.progress_percent < 70,
        )
        threshold = user_state.supervision.escalation_threshold
        needs_escalation = skip_streak >= threshold or under_streak >= threshold + 1
        suggested_mode = "asynchronous"
        if needs_escalation and user_state.supervision.intensity == "strict":
            suggested_mode = "synchronous_recommended"
        elif needs_escalation:
            suggested_mode = "high_frequency_asynchronous"

        return TrackingInsights(
            total_checkins=total,
            completed_checkins=completed,
            skipped_checkins=skipped,
            partial_checkins=partial,
            on_time_rate=round(on_time_rate, 3),
            average_progress=round(avg_progress, 2),
            recent_skip_streak=skip_streak,
            under_completion_streak=under_streak,
            needs_escalation=needs_escalation,
            suggested_tracking_mode=suggested_mode,
        )

    def _reminder(
        self,
        user_state: UserState,
        block: ScheduleBlock,
        scheduled_for: datetime,
        reminder_type: str,
        strength: str,
        reason: str,
    ) -> ReminderEvent:
        task = self._find_task(user_state, block.task_id)
        title = task.title if task else block.title
        return ReminderEvent(
            reminder_id=make_id("reminder"),
            user_id=user_state.user_id,
            task_id=block.task_id,
            block_id=block.block_id,
            scheduled_for=iso_from_datetime(scheduled_for),
            reminder_type=reminder_type,
            strength=strength,
            reason=reason,
            message_hint=f"Check progress on: {title}",
        )

    def _adaptive_due(
        self,
        now: datetime,
        block: ScheduleBlock,
        frequency_multiplier: float,
    ) -> bool:
        interval = int(45 / max(0.5, frequency_multiplier))
        interval = max(25, min(90, interval))
        return now.minute % max(1, interval // 5) == 0 or block.status == TASK_SKIPPED

    def _spot_check_due(
        self,
        user_state: UserState,
        block: ScheduleBlock,
        now: datetime,
        frequency_multiplier: float,
    ) -> bool:
        if frequency_multiplier < 0.75 or user_state.emotion.distress_detected:
            return False
        start = parse_datetime(block.start_at)
        end = parse_datetime(block.end_at)
        if not start or not end or not (start <= now <= end):
            return False
        seed = sum(ord(ch) for ch in block.block_id + now.strftime("%Y%m%d%H"))
        return seed % 11 == 0

    def _update_task_from_checkin(
        self,
        task: Task,
        checkin: CheckInRecord,
        block: ScheduleBlock | None,
    ) -> None:
        remaining = task.remaining_minutes if task.remaining_minutes is not None else task.estimated_minutes
        focus_minutes = checkin.focus_minutes or (block.focus_minutes if block else 25)
        if checkin.status == CHECKIN_COMPLETED:
            remaining = max(0, remaining - max(focus_minutes, int(task.estimated_minutes * checkin.progress_percent / 100)))
            if checkin.progress_percent >= 95 or remaining == 0:
                task.status = TASK_COMPLETED
                task.completed_at = checkin.completed_at or checkin.created_at
            else:
                task.status = TASK_IN_PROGRESS
        elif checkin.status == CHECKIN_PARTIAL:
            remaining = max(0, remaining - max(1, int(focus_minutes * checkin.progress_percent / 100)))
            task.status = TASK_IN_PROGRESS
        elif checkin.status == CHECKIN_DELAYED and checkin.justified_delay:
            task.status = TASK_DEFERRED
        elif checkin.status in {CHECKIN_SKIPPED, CHECKIN_DELAYED}:
            task.status = TASK_SKIPPED
        task.remaining_minutes = remaining
        task.updated_at = now_iso()

    def _is_justified_delay(self, reason: str) -> bool:
        lower = reason.lower()
        return any(term in lower for term in self.JUSTIFIED_DELAY_TERMS)

    def _find_block(
        self,
        user_state: UserState,
        block_id: str | None,
        task_id: str,
    ) -> ScheduleBlock | None:
        if block_id:
            for block in user_state.schedule:
                if block.block_id == block_id:
                    return block
        for block in reversed(user_state.schedule):
            if block.task_id == task_id and block.status == TASK_PLANNED:
                return block
        return None

    def _find_task(self, user_state: UserState, task_id: str) -> Task | None:
        for task in user_state.tasks:
            if task.task_id == task_id:
                return task
        return None

    def _streak(self, items: list[CheckInRecord], predicate) -> int:
        count = 0
        for item in items:
            if predicate(item):
                count += 1
            else:
                break
        return count


TaskTracking = TaskTrackingAgent
