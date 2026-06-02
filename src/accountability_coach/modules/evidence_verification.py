"""DaKa evidence consistency ritual from ACSP Section 3.3.3."""

from __future__ import annotations

from pathlib import Path

from accountability_coach.core.models import (
    EVIDENCE_CONSISTENT,
    EVIDENCE_MISSING,
    EVIDENCE_SUSPICIOUS,
    EVIDENCE_UNCERTAIN,
    CheckInRecord,
    EvidenceAssessment,
    Task,
    UserState,
    make_id,
)


class DaKaEvidenceVerifier:
    """Multidimensional consistency checks without treating the user as a liar."""

    DISTRACTION_TERMS = {
        "weibo",
        "微博",
        "douyin",
        "抖音",
        "tiktok",
        "bilibili",
        "youtube",
        "netflix",
        "steam",
        "game",
        "游戏",
        "instagram",
        "twitter",
        "x.com",
    }
    PRODUCTIVE_TERMS = {
        "paper",
        "论文",
        "draft",
        "outline",
        "word",
        "docs",
        "pdf",
        "latex",
        "notion",
        "zotero",
        "problem",
        "题",
        "anki",
        "vscode",
        "pycharm",
        "excel",
    }

    def assess(self, state: UserState, checkin: CheckInRecord) -> EvidenceAssessment:
        task = self._find_task(state, checkin.task_id)
        evidence_text = self._extract_evidence_text(checkin)
        activity = self._extract_activity(checkin)
        checks: list[str] = []
        flags: list[str] = []

        if not evidence_text and not activity and not checkin.evidence_ref:
            return EvidenceAssessment(
                assessment_id=make_id("evidence"),
                checkin_id=checkin.checkin_id,
                task_id=checkin.task_id,
                consistency_level=EVIDENCE_MISSING,
                checks=["no_evidence_submitted"],
                flags=["ask_for_lightweight_evidence_next_time"],
                ritual_prompt="I will trust this DaKa, and next time please attach one small artifact so the ritual feels concrete.",
                confidence=0.1,
            )

        task_terms = self._task_terms(task)
        evidence_terms = self._tokens(f"{evidence_text} {activity}")
        matching_terms = sorted(task_terms & evidence_terms)
        distracting = sorted(
            term for term in self.DISTRACTION_TERMS if term in f"{evidence_text} {activity}".lower()
        )

        if evidence_text:
            checks.append("ocr_or_text_evidence_present")
        if activity:
            checks.append("screen_activity_present")
        if matching_terms:
            checks.append(f"matched_task_terms:{','.join(matching_terms[:5])}")
        if distracting:
            flags.append(f"possible_distraction_activity:{','.join(distracting[:3])}")

        if distracting and not matching_terms:
            level = EVIDENCE_SUSPICIOUS
            confidence = 0.75
            prompt = (
                "The evidence does not seem aligned with the pledged task. "
                "I may be misreading it, so please explain what part of this artifact shows progress."
            )
        elif matching_terms or self._productive_signal(evidence_text, activity):
            level = EVIDENCE_CONSISTENT
            confidence = 0.8
            prompt = "Evidence and task look aligned. Treat this as a serious completed ritual, not just a self-report."
        else:
            level = EVIDENCE_UNCERTAIN
            confidence = 0.45
            prompt = (
                "I cannot clearly connect the artifact to the task yet. "
                "Please add one sentence naming the concrete output."
            )

        return EvidenceAssessment(
            assessment_id=make_id("evidence"),
            checkin_id=checkin.checkin_id,
            task_id=checkin.task_id,
            consistency_level=level,
            evidence_text=evidence_text,
            detected_activity=activity,
            checks=checks,
            flags=flags,
            ritual_prompt=prompt,
            confidence=confidence,
        )

    def _extract_evidence_text(self, checkin: CheckInRecord) -> str:
        metadata = checkin.metadata or {}
        for key in ("ocr_text", "screenshot_ocr_text", "evidence_text"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if checkin.evidence_ref and checkin.evidence_ref.endswith(".txt"):
            path = Path(checkin.evidence_ref)
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore")[:4000]
        return ""

    def _extract_activity(self, checkin: CheckInRecord) -> str:
        metadata = checkin.metadata or {}
        parts = [
            str(metadata.get(key, ""))
            for key in ("activity_app", "activity_title", "screen_activity", "window_title")
        ]
        return " ".join(part for part in parts if part).strip()

    def _task_terms(self, task: Task | None) -> set[str]:
        if not task:
            return set()
        raw = " ".join([task.title, task.notes, *task.tags, *task.knowledge_tags])
        return self._tokens(raw)

    def _tokens(self, text: str) -> set[str]:
        return {
            token.strip(".,;:!?()[]{}'\"").lower()
            for token in text.split()
            if len(token.strip(".,;:!?()[]{}'\"")) >= 2
        }

    def _productive_signal(self, evidence_text: str, activity: str) -> bool:
        haystack = f"{evidence_text} {activity}".lower()
        return any(term in haystack for term in self.PRODUCTIVE_TERMS)

    def _find_task(self, state: UserState, task_id: str) -> Task | None:
        for task in state.tasks:
            if task.task_id == task_id:
                return task
        return None
