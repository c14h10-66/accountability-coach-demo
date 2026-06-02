"""Trust-building onboarding flow from ACSP Section 3.3.1."""

from __future__ import annotations

from typing import Any

from accountability_coach.core.models import (
    ONBOARDING_ALIGNMENT,
    ONBOARDING_CONTRACT,
    ONBOARDING_TRANSPARENCY,
    OnboardingScript,
    UserState,
    now_iso,
)


class TrustOnboardingFlow:
    """Three-stage onboarding: contract, alignment, and transparency."""

    def build_opening_script(self, state: UserState) -> OnboardingScript:
        stage = self._next_stage(state)
        if stage == ONBOARDING_CONTRACT:
            script = OnboardingScript(
                stage=stage,
                questions=[
                    "What academic goal or deadline do you want supervision for first?",
                    "How long do you want this supervision relationship to run?",
                    "How strict should I be when you miss a planned block: lenient, moderate, or strict?",
                ],
                self_disclosure=[
                    "I am a software coach, not a judge. I keep state so we can see patterns, not to shame a single failure.",
                    "I can be consistent about reminders and reflection, but I cannot verify every claim the way a human beside you could.",
                ],
                service_boundaries=[
                    "I can help with planning, DaKa check-ins, reminders, reflection, knowledge-source organization, and emotional scaffolding.",
                    "I cannot provide clinical care, crisis support, or guarantee academic outcomes.",
                ],
                next_action="Collect goals, supervision duration, and preferred intensity.",
            )
        elif stage == ONBOARDING_ALIGNMENT:
            script = OnboardingScript(
                stage=stage,
                questions=[
                    "What is your procrastination history: when did it start, and what does it usually look like?",
                    "What have you already tried, and why did those attempts stop working?",
                    "Which task types are hardest to start: reading, writing, problem sets, memorization, admin, or something else?",
                    "What usually happens right before you avoid a task?",
                ],
                self_disclosure=[
                    "My strongest use is pattern tracking: I can remember repeated blockers and adapt plans without treating one bad day as your identity.",
                ],
                service_boundaries=[
                    "If a blocker is mainly a knowledge gap, I will switch into expert support; if it is emotional overload, I will reduce pressure first.",
                ],
                next_action="Map task types, failed attempts, and supervision preferences into the user's profile.",
            )
        else:
            script = OnboardingScript(
                stage=stage,
                questions=[
                    "What would make you feel safe enough to report an honest miss instead of hiding it?",
                    "What kind of reminder feels helpful, and what kind feels humiliating or counterproductive?",
                    "When should I suggest a human supervisor, counselor, or trusted person instead of continuing routine coaching?",
                ],
                self_disclosure=[
                    "I will not moralize a missed check-in. A miss becomes planning data unless there is a safety risk.",
                    "I can forget the emotional charge of a single failure while preserving useful patterns for future planning.",
                ],
                service_boundaries=[
                    "If you mention self-harm, immediate danger, severe impairment, or sustained hopelessness, I will pause routine accountability and point you to real-world support.",
                    "If you stop trusting this system or feel harmed by it, the right move may be a human coach or a different support style.",
                ],
                next_action="Confirm transparency, safety boundaries, and honest DaKa expectations.",
            )
        state.onboarding_scripts.append(script)
        state.updated_at = now_iso()
        return script

    def record_response(
        self,
        state: UserState,
        response_data: dict[str, Any],
    ) -> OnboardingScript:
        """Store onboarding answers and return the next script."""
        profile_updates = {
            "procrastination_history": response_data.get("procrastination_history"),
            "past_attempts": response_data.get("past_attempts"),
            "hard_start_task_types": response_data.get("hard_start_task_types"),
            "avoidance_precursors": response_data.get("avoidance_precursors"),
            "helpful_reminder_style": response_data.get("helpful_reminder_style"),
            "harmful_reminder_style": response_data.get("harmful_reminder_style"),
            "honesty_conditions": response_data.get("honesty_conditions"),
        }
        for key, value in profile_updates.items():
            if value not in (None, "", []):
                state.profile[key] = value

        if response_data.get("boundary_acknowledged") is True:
            state.profile["boundary_acknowledged"] = True
        if response_data.get("transparency_acknowledged") is True:
            state.profile["transparency_acknowledged"] = True

        if state.profile.get("boundary_acknowledged") and state.profile.get(
            "procrastination_history"
        ):
            state.supervision.alignment_status = "trust_building_complete"
            state.supervision.trust_level = max(state.supervision.trust_level, 0.72)
            state.acsp_layer = "operational"
        else:
            state.supervision.alignment_status = "onboarding"
            state.acsp_layer = "foundational"
        state.updated_at = now_iso()
        return self.build_opening_script(state)

    def _next_stage(self, state: UserState) -> str:
        if not state.supervision.goals:
            return ONBOARDING_CONTRACT
        if not state.profile.get("procrastination_history"):
            return ONBOARDING_ALIGNMENT
        if not state.profile.get("boundary_acknowledged"):
            return ONBOARDING_TRANSPARENCY
        return ONBOARDING_TRANSPARENCY
