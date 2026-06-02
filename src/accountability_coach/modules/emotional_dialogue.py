"""Structured emotional dialogue playbook, inspired by CBT/ICBT patterns."""

from __future__ import annotations

from accountability_coach.core.models import (
    CHECKIN_SKIPPED,
    EmotionalDialoguePlan,
    UserState,
    now_iso,
)


class EmotionalDialoguePlaybook:
    """Select talk-level emotional scaffolding, not just numeric multipliers."""

    DISTORTIONS = {
        "all_or_nothing": ("always", "never", "nothing", "everything", "全都", "从来", "永远", "完全"),
        "catastrophizing": ("ruined", "disaster", "can't finish", "over", "完了", "毁了", "完不成"),
        "personalization": ("my fault", "i am useless", "failure", "都怪我", "我太差", "废物"),
        "should_statement": ("should have", "must", "应该", "必须", "早该"),
    }

    def build_plan(
        self,
        state: UserState,
        latest_text: str = "",
    ) -> EmotionalDialoguePlan:
        text = self._recent_text(state, latest_text)
        labels = self._detect_distortions(text)
        persistent_skips = sum(1 for item in state.checkins[-5:] if item.status == CHECKIN_SKIPPED) >= 2
        distress = state.emotion.distress_detected or state.emotion.morale <= 0.35
        tags: list[str] = []
        if distress:
            tags.append("empathic_listening")
        if persistent_skips or "shared_responsibility" in state.emotion.support_flags:
            tags.append("companionate_shared_responsibility")
        if labels:
            tags.append("cognitive_reframing")
        if not tags:
            tags.append("steady_encouragement")

        plan = EmotionalDialoguePlan(
            strategy_tags=tags,
            reflective_response=self._reflective_response(distress, latest_text),
            validation=self._validation(distress),
            responsibility_sharing=self._responsibility_sharing(persistent_skips),
            distortion_labels=labels,
            reframing_prompt=self._reframing_prompt(labels),
            next_micro_action="Choose one action that can be started in two minutes, then send a small DaKa.",
            tone="peer-like" if distress or persistent_skips else "warm-practical",
        )
        state.emotional_dialogue_history.append(plan)
        state.updated_at = now_iso()
        return plan

    def _reflective_response(self, distress: bool, latest_text: str) -> str:
        if distress:
            return (
                "I hear that this feels heavy and discouraging. I am going to slow the pressure down first, then we will choose one small next move."
            )
        if latest_text:
            return "I am taking this as useful signal about what the task feels like, not as a verdict on you."
        return "Let's keep this concrete and gentle: what happened, what helped, and what is the next small action?"

    def _validation(self, distress: bool) -> str:
        if distress:
            return "Feeling stuck under academic pressure is understandable; we can protect safety and rhythm at the same time."
        return "A check-in is valuable because it makes the pattern visible."

    def _responsibility_sharing(self, persistent_skips: bool) -> str:
        if persistent_skips:
            return (
                "If this plan kept producing skips, part of the responsibility is mine too: the task may have been too large, too vague, or timed poorly."
            )
        return ""

    def _reframing_prompt(self, labels: list[str]) -> str:
        if not labels:
            return ""
        return (
            "Use a thought-record reset: situation, automatic thought, evidence for it, evidence against it, a balanced thought, and one tiny behavior."
        )

    def _detect_distortions(self, text: str) -> list[str]:
        return [
            label
            for label, terms in self.DISTORTIONS.items()
            if any(term in text for term in terms)
        ]

    def _recent_text(self, state: UserState, latest_text: str) -> str:
        notes = " ".join(checkin.note for checkin in state.checkins[-5:])
        return f"{latest_text} {notes}".lower()
