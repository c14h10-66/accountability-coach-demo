"""Risk detection and escalation from ACSP Section 3.3.6."""

from __future__ import annotations

from accountability_coach.core.models import (
    CHECKIN_COMPLETED,
    RISK_CRITICAL,
    RISK_ESCALATE,
    RISK_MONITOR,
    RISK_NONE,
    RiskAssessment,
    UserState,
    make_id,
    parse_datetime,
)


class RiskDetector:
    """Detect clinical risk, relationship rupture, and goal-capacity mismatch."""

    SELF_HARM_TERMS = (
        "suicide",
        "kill myself",
        "end my life",
        "self harm",
        "hurt myself",
        "don't want to live",
        "不想活",
        "自杀",
        "自残",
        "伤害自己",
        "活着没意思",
    )
    SEVERE_DEPRESSION_TERMS = (
        "hopeless",
        "can't go on",
        "cannot go on",
        "nothing matters",
        "绝望",
        "撑不下去",
        "没有希望",
    )
    HOSTILITY_TERMS = (
        "i don't trust you",
        "do not trust you",
        "useless ai",
        "you are useless",
        "shut up",
        "不相信你",
        "你没用",
        "闭嘴",
        "讨厌你",
    )

    def assess(self, state: UserState, latest_text: str = "") -> RiskAssessment:
        text = self._recent_text(state, latest_text)
        categories: list[str] = []
        evidence: list[str] = []
        actions: list[str] = []
        level = RISK_NONE
        pause = False

        if self._contains(text, self.SELF_HARM_TERMS):
            level = RISK_CRITICAL
            pause = True
            categories.append("clinical_risk_self_harm")
            evidence.append("self-harm or immediate safety language detected")
            actions.extend(
                [
                    "Pause routine accountability, reminders, penalties, and performance pressure.",
                    "Encourage the user to contact local emergency services, a crisis hotline, or a trusted person immediately if there is any immediate danger.",
                    "State that this AI coach cannot provide crisis care or replace professional support.",
                ]
            )
        elif self._contains(text, self.SEVERE_DEPRESSION_TERMS):
            level = RISK_ESCALATE
            categories.append("clinical_risk_severe_distress")
            evidence.append("severe hopelessness or impairment language detected")
            actions.extend(
                [
                    "Recommend professional mental-health support before intensifying academic accountability.",
                    "Use only low-pressure emotional support until the user confirms safety and capacity.",
                ]
            )

        if self._sustained_low_completion_with_negative_emotion(state):
            if level == RISK_NONE:
                level = RISK_ESCALATE
            categories.append("goal_capacity_mismatch")
            evidence.append("sustained low completion plus high negative emotion")
            actions.append(
                "Suggest a human accountability coach, academic advisor, or counselor to reassess load and goals."
            )

        if self._contains(text, self.HOSTILITY_TERMS):
            if level == RISK_NONE:
                level = RISK_ESCALATE
            categories.append("relationship_rupture")
            evidence.append("persistent distrust or hostility toward AI coach detected")
            actions.append(
                "Offer a soft reset or soft exit: reduce interaction, change style, or move to a human coach."
            )

        if level == RISK_NONE and state.emotion.distress_detected:
            level = RISK_MONITOR
            categories.append("distress_monitoring")
            evidence.append("distress detected but no escalation threshold met")
            actions.append("Use partner role and monitor for worsening risk.")

        return RiskAssessment(
            risk_id=make_id("risk"),
            level=level,
            categories=categories,
            evidence=evidence,
            recommended_actions=actions,
            pause_regular_intervention=pause,
        )

    def _sustained_low_completion_with_negative_emotion(self, state: UserState) -> bool:
        recent = state.checkins[-10:]
        if len(recent) < 5:
            return False
        completed = sum(1 for item in recent if item.status == CHECKIN_COMPLETED)
        completion_rate = completed / len(recent)
        avg_progress = sum(item.progress_percent for item in recent) / len(recent)
        dates = [parse_datetime(item.created_at) for item in recent]
        valid_dates = [item for item in dates if item is not None]
        spans_week = False
        if len(valid_dates) >= 2:
            spans_week = (max(valid_dates) - min(valid_dates)).days >= 7
        negative = state.emotion.morale <= 0.35 or state.emotion.stress >= 0.65
        return negative and completion_rate <= 0.25 and avg_progress < 35 and (
            spans_week or len(recent) >= 8
        )

    def _recent_text(self, state: UserState, latest_text: str) -> str:
        notes = " ".join(checkin.note for checkin in state.checkins[-8:])
        return f"{latest_text} {notes}".lower()

    def _contains(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)
