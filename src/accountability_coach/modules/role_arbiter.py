"""Regulatory-layer role arbitration for ACSP Section 3.4.3."""

from __future__ import annotations

from typing import Any

from accountability_coach.core.models import (
    ROLE_COACH,
    ROLE_EXPERT,
    ROLE_MENTOR,
    ROLE_PARTNER,
    RoleDecision,
    UserState,
)


class RoleArbiter:
    """Select Mentor, Coach, Expert, or Partner from current user state."""

    EXPERT_TERMS = (
        "resource",
        "source",
        "concept",
        "method",
        "how do i",
        "how to",
        "don't know how",
        "not sure how",
        "资料",
        "资源",
        "概念",
        "方法",
        "不会",
        "怎么做",
    )
    MENTOR_TERMS = (
        "should i continue",
        "do i continue",
        "why am i doing",
        "what is the point",
        "goal",
        "meaning",
        "到底要不要",
        "还要继续",
        "有没有意义",
        "目标",
        "方向",
    )

    def decide(
        self,
        state: UserState,
        latest_text: str = "",
        tracking_insights: Any | None = None,
    ) -> RoleDecision:
        text = self._recent_text(state, latest_text)
        scores = {
            ROLE_MENTOR: 0,
            ROLE_COACH: 0,
            ROLE_EXPERT: 0,
            ROLE_PARTNER: 0,
        }
        triggers: dict[str, list[str]] = {role: [] for role in scores}

        if state.emotion.distress_detected or state.emotion.morale < 0.35:
            scores[ROLE_PARTNER] += 4
            triggers[ROLE_PARTNER].append("emotional_distress_or_low_morale")
        if "lonely" in text or "孤独" in text or "没人陪" in text:
            scores[ROLE_PARTNER] += 2
            triggers[ROLE_PARTNER].append("isolation_or_companionship_need")

        recent_skip = int(state.tracking_state.get("recent_skip_streak", 0) or 0)
        under = int(state.tracking_state.get("under_completion_streak", 0) or 0)
        if tracking_insights is not None:
            recent_skip = max(recent_skip, int(getattr(tracking_insights, "recent_skip_streak", 0)))
            under = max(under, int(getattr(tracking_insights, "under_completion_streak", 0)))
        if state.tracking_state.get("needs_escalation") or recent_skip >= 2 or under >= 3:
            scores[ROLE_COACH] += 3
            triggers[ROLE_COACH].append("execution_gap_or_declining_self_control")

        if any(term in text for term in self.EXPERT_TERMS):
            scores[ROLE_EXPERT] += 3
            triggers[ROLE_EXPERT].append("skill_or_methodological_bottleneck")
        if int(state.tracking_state.get("knowledge_request_count", 0) or 0) >= 2:
            scores[ROLE_EXPERT] += 2
            triggers[ROLE_EXPERT].append("repeated_knowledge_support_requests")

        if not state.supervision.goals or any(term in text for term in self.MENTOR_TERMS):
            scores[ROLE_MENTOR] += 3
            triggers[ROLE_MENTOR].append("goal_confusion_or_purpose_reconstruction")
        if state.emotion.stress > 0.7 and ("never" in text or "完不成" in text):
            scores[ROLE_MENTOR] += 2
            triggers[ROLE_MENTOR].append("irrational_anxiety_about_goal")

        role = max(
            scores,
            key=lambda item: (scores[item], self._priority(item)),
        )
        if scores[role] == 0:
            role = ROLE_COACH
            triggers[role].append("default_behavioral_accountability")
        return self._decision_for(role, triggers[role])

    def apply_to_adjustment(
        self,
        decision: RoleDecision,
        adjustment: dict[str, object],
    ) -> dict[str, object]:
        updated = dict(adjustment)
        current_reminder = float(updated.get("reminder_frequency_multiplier", 1.0))
        updated["reminder_frequency_multiplier"] = round(
            current_reminder * decision.reminder_strength_multiplier,
            3,
        )
        updated["guidance_tone"] = self._tone_to_control(decision)
        updated["role"] = decision.role
        updated["role_triggers"] = list(decision.triggers)
        updated["guidance_strategy_weights"] = dict(decision.guidance_strategy_weights)
        return updated

    def _decision_for(self, role: str, triggers: list[str]) -> RoleDecision:
        if role == ROLE_PARTNER:
            return RoleDecision(
                role=role,
                triggers=triggers,
                rationale="User needs affective buffering before accountability pressure.",
                tone_template="warm, validating, non-judgmental, and co-present",
                reminder_strength_multiplier=0.55,
                guidance_strategy_weights={
                    "empathic_listening": 1.0,
                    "shared_responsibility": 0.9,
                    "commitment": 0.25,
                    "knowledge": 0.3,
                },
            )
        if role == ROLE_EXPERT:
            return RoleDecision(
                role=role,
                triggers=triggers,
                rationale="User appears blocked by knowledge, resources, or methods.",
                tone_template="clear, instructive, resource-oriented, and concrete",
                reminder_strength_multiplier=0.85,
                guidance_strategy_weights={
                    "knowledge": 1.0,
                    "methodological_guidance": 0.9,
                    "reflection": 0.45,
                    "commitment": 0.35,
                },
            )
        if role == ROLE_MENTOR:
            return RoleDecision(
                role=role,
                triggers=triggers,
                rationale="User needs purpose clarification or macro-level cognitive reconstruction.",
                tone_template="strategic, reflective, stabilizing, and perspective-building",
                reminder_strength_multiplier=0.75,
                guidance_strategy_weights={
                    "reflection": 1.0,
                    "values_reconnection": 0.9,
                    "schedule": 0.45,
                    "commitment": 0.35,
                },
            )
        return RoleDecision(
            role=ROLE_COACH,
            triggers=triggers,
            rationale="User needs behavioral accountability for execution.",
            tone_template="firm, specific, rhythmic, and behavior-focused",
            reminder_strength_multiplier=1.25,
            guidance_strategy_weights={
                "tracking": 1.0,
                "commitment": 0.9,
                "reflection": 0.75,
                "reward": 0.55,
            },
        )

    def _recent_text(self, state: UserState, latest_text: str) -> str:
        notes = " ".join(checkin.note for checkin in state.checkins[-5:])
        return f"{latest_text} {notes}".lower()

    def _priority(self, role: str) -> int:
        return {
            ROLE_PARTNER: 4,
            ROLE_EXPERT: 3,
            ROLE_COACH: 2,
            ROLE_MENTOR: 1,
        }.get(role, 0)

    def _tone_to_control(self, decision: RoleDecision) -> str:
        if decision.role == ROLE_PARTNER:
            return "lenient"
        if decision.role == ROLE_COACH:
            return "firm"
        return "neutral"
