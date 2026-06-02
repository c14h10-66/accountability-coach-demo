"""Periodic reflection reports over accountability coaching state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from accountability_coach.core.models import (
    CHECKIN_COMPLETED,
    ProgressReview,
    UserState,
    iso_from_datetime,
    make_id,
    now_iso,
    parse_datetime,
)


class ProgressReviewAgent:
    """Generate weekly/monthly reflection reports and repeated-blocker insights."""

    BLOCKER_TERMS = {
        "tired": ("tired", "sleepy", "exhausted", "累", "困"),
        "anxious": ("anxious", "worried", "panic", "焦虑", "慌"),
        "unclear_next_step": ("don't know", "not sure", "unclear", "不会", "不清楚"),
        "distraction": ("phone", "video", "game", "weibo", "bilibili", "手机", "视频", "游戏"),
        "too_large": ("too much", "too big", "overwhelmed", "太多", "太大", "完不成"),
    }

    def generate_review(
        self,
        state: UserState,
        period: str = "weekly",
        now: datetime | None = None,
    ) -> ProgressReview:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        days = 30 if period == "monthly" else 7
        start = now - timedelta(days=days)
        checkins = [
            item
            for item in state.checkins
            if (created := parse_datetime(item.created_at)) is not None and created >= start
        ]
        total = len(checkins)
        completed = sum(1 for item in checkins if item.status == CHECKIN_COMPLETED)
        avg_progress = sum(item.progress_percent for item in checkins) / total if total else 0.0
        blockers = self._blockers(checkins)
        tag_counts = self._task_tag_patterns(state, checkins)
        review = ProgressReview(
            review_id=make_id("review"),
            period=period,
            period_start=iso_from_datetime(start),
            period_end=iso_from_datetime(now),
            total_checkins=total,
            completion_rate=round(completed / total, 3) if total else 0.0,
            average_progress=round(avg_progress, 2),
            emotion_summary={
                "current_morale": state.emotion.morale,
                "current_stress": state.emotion.stress,
                "dominant_tags": list(state.emotion.dominant_tags),
            },
            recurring_blockers=blockers,
            task_type_patterns=tag_counts,
            narrative=self._narrative(total, completed, avg_progress, blockers),
            self_efficacy_message=self._self_efficacy_message(state, total, completed),
        )
        state.progress_reviews.append(review)
        state.updated_at = now_iso()
        return review

    def _blockers(self, checkins) -> list[str]:
        counts: dict[str, int] = {}
        text = " ".join(item.note.lower() for item in checkins)
        for label, terms in self.BLOCKER_TERMS.items():
            counts[label] = sum(1 for term in terms if term in text)
        return [label for label, count in sorted(counts.items(), key=lambda item: -item[1]) if count > 0]

    def _task_tag_patterns(self, state: UserState, checkins) -> dict[str, int]:
        tasks = {task.task_id: task for task in state.tasks}
        counts: dict[str, int] = {}
        for checkin in checkins:
            task = tasks.get(checkin.task_id)
            if not task:
                continue
            for tag in task.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    def _narrative(self, total: int, completed: int, avg_progress: float, blockers: list[str]) -> str:
        if not total:
            return "这个周期还没有打卡数据；第一目标是先让进展可见。"
        blocker_text = ", ".join(blockers[:3]) if blockers else "no single repeated blocker"
        return (
            f"This period had {total} check-ins, {completed} full completions, and {avg_progress:.1f}% average progress. "
            f"The main repeated blocker pattern was: {blocker_text}."
        )

    def _self_efficacy_message(self, state: UserState, total: int, completed: int) -> str:
        if total and completed:
            return "You have concrete proof that starting is possible; we can reuse the conditions around those wins."
        if state.progress_reviews:
            previous = state.progress_reviews[0]
            return (
                f"Compared with the earlier {previous.period} review, the useful signal is clearer now: we know what blocks you and can plan around it."
            )
        return "The first review is about visibility, not judgment."
