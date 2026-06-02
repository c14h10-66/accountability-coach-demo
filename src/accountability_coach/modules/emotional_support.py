"""Emotional scaffolding and global control signal."""

from __future__ import annotations

from accountability_coach.core.models import (
    CHECKIN_COMPLETED,
    CHECKIN_PARTIAL,
    CHECKIN_SKIPPED,
    CheckInRecord,
    EmotionState,
    UserState,
    clamp,
    now_iso,
)


class EmotionalSupportAgent:
    """Daemon-like emotional support agent from Section 4.7.

    It updates emotional baseline from DaKa notes and emits a global control
    signal used by scheduling, tracking, and guidance.
    """

    NEGATIVE_TAGS = {"anxious", "sad", "tired", "overwhelmed", "helpless", "frustrated"}
    POSITIVE_TAGS = {"motivated", "calm", "proud", "relieved", "focused", "confident"}
    LOW_ENERGY_TAGS = {"tired", "sleepy", "burned_out", "exhausted"}
    HARSH_PATTERNS = (
        "never",
        "always",
        "useless",
        "failure",
        "worthless",
        "can't do anything",
        "nothing works",
        "all my fault",
    )

    def update_from_checkin(
        self,
        current: EmotionState | None,
        checkin: CheckInRecord,
    ) -> EmotionState:
        emotion = current or EmotionState()
        tags = {tag.lower() for tag in checkin.emotion_tags}
        note = checkin.note.lower()
        inferred = self._infer_tags_from_note(note)
        tags.update(inferred)

        negative_count = len(tags & self.NEGATIVE_TAGS)
        positive_count = len(tags & self.POSITIVE_TAGS)
        low_energy = bool(tags & self.LOW_ENERGY_TAGS)

        if checkin.status == CHECKIN_COMPLETED:
            emotion.valence += 0.12
            emotion.morale += 0.10
            emotion.self_efficacy += 0.10
            emotion.stress -= 0.04
        elif checkin.status == CHECKIN_PARTIAL:
            emotion.valence -= 0.03
            emotion.morale -= 0.03
            emotion.self_efficacy -= 0.02
        elif checkin.status == CHECKIN_SKIPPED:
            emotion.valence -= 0.12
            emotion.morale -= 0.12
            emotion.self_efficacy -= 0.10
            emotion.stress += 0.10

        emotion.valence += 0.10 * positive_count - 0.12 * negative_count
        emotion.morale += 0.08 * positive_count - 0.10 * negative_count
        emotion.self_efficacy += 0.06 * positive_count - 0.08 * negative_count
        emotion.stress += 0.10 * negative_count - 0.05 * positive_count
        emotion.energy += (-0.12 if low_energy else 0.02 * positive_count)
        emotion.arousal += 0.06 if {"anxious", "frustrated"} & tags else 0.0

        emotion.valence = clamp(emotion.valence, -1.0, 1.0)
        emotion.arousal = clamp(emotion.arousal, 0.0, 1.0)
        emotion.morale = clamp(emotion.morale, 0.0, 1.0)
        emotion.stress = clamp(emotion.stress, 0.0, 1.0)
        emotion.energy = clamp(emotion.energy, 0.0, 1.0)
        emotion.self_efficacy = clamp(emotion.self_efficacy, 0.0, 1.0)
        emotion.tag_history = (emotion.tag_history + sorted(tags))[-50:]
        emotion.dominant_tags = self._dominant_recent_tags(emotion.tag_history)
        emotion.distress_detected = (
            emotion.stress >= 0.7
            or emotion.morale <= 0.35
            or bool(tags & {"helpless", "overwhelmed", "sad"})
        )
        emotion.support_flags = self._support_flags(emotion, note)
        emotion.updated_at = now_iso()
        return emotion

    def update_from_dialogue_summary(
        self,
        current: EmotionState | None,
        summary: str,
    ) -> EmotionState:
        synthetic = CheckInRecord(
            status=CHECKIN_PARTIAL,
            note=summary,
            emotion_tags=list(self._infer_tags_from_note(summary.lower())),
        )
        return self.update_from_checkin(current, synthetic)

    def derive_adjustment(self, emotion: EmotionState | None) -> dict[str, object]:
        """Return the global control signal described in Section 4.1/4.7."""
        emotion = emotion or EmotionState()
        schedule_multiplier = 1.0
        reminder_multiplier = 1.0
        tone = "neutral"

        if emotion.distress_detected or emotion.morale < 0.35:
            schedule_multiplier = 0.6
            reminder_multiplier = 0.5
            tone = "lenient"
        elif emotion.stress > 0.6 or emotion.energy < 0.4:
            schedule_multiplier = 0.75
            reminder_multiplier = 0.7
            tone = "lenient"
        elif emotion.self_efficacy > 0.75 and emotion.morale > 0.75:
            schedule_multiplier = 1.1
            reminder_multiplier = 1.0
            tone = "firm"

        return {
            "schedule_intensity_multiplier": schedule_multiplier,
            "reminder_frequency_multiplier": reminder_multiplier,
            "guidance_tone": tone,
            "distress_detected": emotion.distress_detected,
            "support_flags": list(emotion.support_flags),
        }

    def analyze_state(self, state: UserState) -> dict[str, object]:
        recent = state.checkins[-5:]
        skipped = sum(1 for item in recent if item.status == CHECKIN_SKIPPED)
        harsh_notes = [
            item.note
            for item in recent
            if any(pattern in item.note.lower() for pattern in self.HARSH_PATTERNS)
        ]
        return {
            "persistent_failure": skipped >= 2,
            "harsh_self_criticism": bool(harsh_notes),
            "needs_empathic_listening": state.emotion.distress_detected,
            "needs_shared_responsibility": skipped >= 2 and state.emotion.stress >= 0.55,
            "needs_cognitive_reframing": bool(harsh_notes),
        }

    def _infer_tags_from_note(self, note: str) -> set[str]:
        tags: set[str] = set()
        mapping = {
            "anxious": ("anxious", "panic", "worried", "scared"),
            "sad": ("sad", "down", "depressed", "cry"),
            "tired": ("tired", "sleepy", "exhausted", "no energy"),
            "overwhelmed": ("overwhelmed", "too much", "can't finish"),
            "helpless": ("helpless", "stuck", "no way"),
            "frustrated": ("frustrated", "annoyed", "angry"),
            "motivated": ("motivated", "ready", "energized"),
            "proud": ("proud", "happy", "finished"),
            "focused": ("focused", "flow", "concentrated"),
            "calm": ("calm", "okay", "better"),
        }
        for tag, needles in mapping.items():
            if any(needle in note for needle in needles):
                tags.add(tag)
        return tags

    def _support_flags(self, emotion: EmotionState, note: str) -> list[str]:
        flags: list[str] = []
        if emotion.distress_detected:
            flags.append("empathic_listening")
        if emotion.stress >= 0.55 and emotion.self_efficacy <= 0.45:
            flags.append("shared_responsibility")
        if any(pattern in note for pattern in self.HARSH_PATTERNS):
            flags.append("cognitive_reframing")
        return flags

    def _dominant_recent_tags(self, history: list[str]) -> list[str]:
        counts: dict[str, int] = {}
        for tag in history[-20:]:
            counts[tag] = counts.get(tag, 0) + 1
        return [
            tag
            for tag, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ]


EmotionalSupport = EmotionalSupportAgent
