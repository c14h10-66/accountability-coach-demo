"""Supervision customization from ACSP foundational layer."""

from __future__ import annotations

from typing import Any

from accountability_coach.core.models import (
    INTENSITY_LENIENT,
    INTENSITY_MODERATE,
    INTENSITY_STRICT,
    STYLE_CUSTOM,
    STYLE_GENTLE,
    STYLE_PLAYFUL,
    STYLE_SERIOUS,
    SupervisionProfile,
    UserState,
    now_iso,
)


class SupervisionCustomization:
    """Configure persona, supervision intensity, goals, and trust alignment.

    This operationalizes Section 4.2: preset personas and supervision
    intensity become global parameters that later modulate tone, reminder
    strength, and escalation thresholds.
    """

    _STYLE_TONES = {
        STYLE_GENTLE: "warm, patient, and non-judgmental",
        STYLE_SERIOUS: "direct, orderly, and accountability-focused",
        STYLE_PLAYFUL: "light, encouraging, and momentum-oriented",
        STYLE_CUSTOM: "custom",
    }
    _INTENSITY_PARAMS = {
        INTENSITY_STRICT: (1.35, 1),
        INTENSITY_MODERATE: (1.0, 2),
        INTENSITY_LENIENT: (0.7, 3),
    }

    def configure(self, state: UserState, config_data: dict[str, Any]) -> UserState:
        profile = state.supervision or SupervisionProfile()
        style = str(config_data.get("style", profile.style or STYLE_GENTLE)).lower()
        intensity = str(
            config_data.get("intensity", profile.intensity or INTENSITY_MODERATE)
        ).lower()
        if style not in self._STYLE_TONES:
            style = STYLE_CUSTOM
        if intensity not in self._INTENSITY_PARAMS:
            intensity = INTENSITY_MODERATE

        reminder_strength, escalation_threshold = self._INTENSITY_PARAMS[intensity]
        persona = str(
            config_data.get("persona_description")
            or config_data.get("persona")
            or self._default_persona(style, intensity)
        )
        profile.style = style
        profile.intensity = intensity
        profile.persona_description = persona
        profile.tone = str(config_data.get("tone") or self._STYLE_TONES[style])
        profile.reminder_strength = reminder_strength
        profile.escalation_threshold = escalation_threshold
        profile.academic_background = str(
            config_data.get("academic_background", profile.academic_background)
        )
        profile.major = str(config_data.get("major", profile.major))
        profile.goals = list(config_data.get("goals", profile.goals))
        profile.exam_target_dates = dict(
            config_data.get("exam_target_dates", profile.exam_target_dates)
        )
        profile.constraints = dict(config_data.get("constraints", profile.constraints))
        profile.service_boundaries = list(
            config_data.get("service_boundaries", profile.service_boundaries)
            or [
                "The coach supports study planning, accountability, and reflection.",
                "Clinical or crisis needs should be escalated to qualified support.",
            ]
        )

        profile.alignment_status = "aligned" if profile.goals else "needs_goals"
        profile.trust_level = min(1.0, max(profile.trust_level, 0.6))
        state.supervision = profile
        state.profile.update(dict(config_data.get("profile", {})))
        state.acsp_layer = "operational" if profile.goals else "foundational"
        state.updated_at = now_iso()
        return state

    def _default_persona(self, style: str, intensity: str) -> str:
        if style == STYLE_SERIOUS:
            return (
                "A structured accountability coach who names deviations clearly, "
                "keeps commitments visible, and still avoids moral judgment."
            )
        if style == STYLE_PLAYFUL:
            return (
                "A bright accountability partner who uses lightness to lower "
                "avoidance while keeping the plan concrete."
            )
        if intensity == INTENSITY_LENIENT:
            return (
                "A gentle coach who protects morale first, then rebuilds study "
                "rhythm through small feasible wins."
            )
        return (
            "A calm accountability coach who balances planning, tracking, "
            "reflection, and emotional safety."
        )
