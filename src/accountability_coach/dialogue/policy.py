"""Dialogue intervention policy derived from state, not keyword triggers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(slots=True)
class RuntimeContext:
    """Runtime facts that help the coach adapt without parsing user wording."""

    local_datetime: str
    local_hour: int
    day_phase: str
    timezone: str


@dataclass(slots=True)
class DialoguePolicyContext:
    """High-level response guidance for the LLM dialogue layer."""

    runtime: RuntimeContext
    user_readiness: str = "unknown"
    start_timing: str = "unknown"
    task_push_allowed: bool = False
    task_action_mode: str = "none"
    response_register: str = "natural_companion"
    closing_style: str = "contextual_next_step"
    max_questions: int = 1
    intervention_modes: list[str] = field(default_factory=list)
    avoid_moves: list[str] = field(default_factory=list)
    assessment_questions: list[str] = field(default_factory=list)
    planning_options: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class DialoguePolicy:
    """Build response policy from intent, local time, and workload state."""

    def __init__(
        self,
        now_provider: Callable[[], datetime] | None = None,
        late_day_start_hour: int = 21,
        heavy_task_threshold: int = 3,
        heavy_block_threshold: int = 4,
    ) -> None:
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())
        self.late_day_start_hour = late_day_start_hour
        self.heavy_task_threshold = heavy_task_threshold
        self.heavy_block_threshold = heavy_block_threshold

    def runtime_context(self, timezone_name: str | None = None) -> RuntimeContext:
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.astimezone()
        zone_name = ""
        if timezone_name:
            try:
                zone = ZoneInfo(timezone_name)
                now = now.astimezone(zone)
                zone_name = timezone_name
            except ZoneInfoNotFoundError:
                zone_name = str(now.tzinfo or "")
        else:
            zone_name = str(now.tzinfo or "")
        return RuntimeContext(
            local_datetime=now.isoformat(timespec="seconds"),
            local_hour=now.hour,
            day_phase=self._day_phase(now.hour),
            timezone=zone_name,
        )

    def build_context(
        self,
        *,
        action: dict[str, Any],
        status: dict[str, Any],
        memory_context: dict[str, Any],
        runtime: RuntimeContext | None = None,
    ) -> DialoguePolicyContext:
        runtime = runtime or self.runtime_context()
        context = DialoguePolicyContext(runtime=runtime)
        intent = str(action.get("intent", "chat"))
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        readiness = self._readiness(payload)
        planning_permission = self._planning_permission(payload)
        start_timing = self._start_timing(payload)
        active_count = int(status.get("active_task_count", 0) or 0)
        block_count = int(status.get("planned_block_count", 0) or 0)
        has_pending_context = bool((memory_context.get("working_context") or {}).get("pending_intention"))
        proactive_suggestions = status.get("proactive_suggestions") if isinstance(status, dict) else None
        context.user_readiness = readiness
        context.start_timing = start_timing

        if self._allows_immediate_task_push(intent, readiness, planning_permission, start_timing):
            context.task_push_allowed = True
            context.task_action_mode = "permissioned_next_step"
        elif intent == "add_task":
            context.task_action_mode = "task_record_only"
            context.intervention_modes.append("task_record_only")
            context.avoid_moves.extend(
                [
                    "assuming_task_mention_means_start_now",
                    "conflating_task_recording_with_task_start",
                    "assigning_micro_action_without_permission",
                ]
            )
            context.planning_options.append("record the task and leave scheduling or starting as a separate opt-in step")
            context.rationale.append("Naming a task is not the same as agreeing to start immediately.")

        if intent == "emotion":
            context.task_action_mode = "emotional_first"
            context.response_register = "companionate_support"
            context.intervention_modes.extend(["emotional_support", "load_assessment"])
            context.avoid_moves.extend(
                [
                    "treating_emotion_as_checkin",
                    "pushing_immediate_execution",
                    "returning_to_task_before_emotional_response",
                ]
            )
            context.assessment_questions.extend(
                [
                    "distinguish physical fatigue, emotional overload, and task overload",
                    "check whether the current workload is too broad or poorly timed",
                ]
            )
            context.planning_options.extend(
                [
                    "offer task decomposition only after emotional validation",
                    "offer a next-day first block when immediate work is not suitable",
                ]
            )
            context.rationale.append("The user expressed a state, not a task outcome.")

        if readiness in {"low", "opt_out"} or planning_permission is False:
            context.task_push_allowed = False
            if intent != "add_task":
                context.task_action_mode = "support_before_planning"
            context.response_register = "low_pressure"
            context.intervention_modes.extend(["autonomy_respect", "pressure_downshift"])
            context.avoid_moves.extend(
                [
                    "asking_for_academic_task_immediately",
                    "task_decomposition_without_permission",
                    "turning_refusal_into_checkin",
                    "implying_immediate_progress_required",
                ]
            )
            context.planning_options.extend(
                [
                    "offer rest or a brief conversation without planning",
                    "ask permission before any schedule or task decomposition",
                    "offer tomorrow planning only as an option, not a demand",
                ]
            )
            context.rationale.append("User readiness is low, so accountability should reduce pressure before planning.")

        if runtime.local_hour >= self.late_day_start_hour and intent in {"emotion", "plan", "add_task", "chat"}:
            if start_timing != "now":
                context.task_push_allowed = False
            context.intervention_modes.append("late_day_recovery_or_tomorrow_planning")
            context.avoid_moves.append("assuming_now_is_the_best_start_time")
            context.planning_options.append("consider recovery, a shutdown ritual, or tomorrow's first study block")
            context.rationale.append("Local time is late enough that recovery may be more useful than escalation.")

        if self._is_sleep_time(runtime.local_hour) and intent in {"chat", "emotion", "plan", "add_task"}:
            if start_timing != "now":
                context.task_push_allowed = False
            context.intervention_modes.append("sleep_or_shutdown")
            context.avoid_moves.extend(["inviting_broad_late_night_study", "asking_for_task_on_late_greeting"])
            context.planning_options.append("suggest sleep, shutdown, or only an emergency minimum if a deadline is urgent")
            context.rationale.append("The user's local time is in a sleep window.")

        if self._is_meal_time(runtime.local_hour) and intent in {"chat", "emotion", "plan", "add_task"}:
            context.intervention_modes.append("meal_or_basic_needs_check")
            context.planning_options.append("briefly mention eating or a basic-needs break before planning when relevant")
            context.rationale.append("The user's local time is near a normal meal window.")

        if active_count >= self.heavy_task_threshold or block_count >= self.heavy_block_threshold:
            context.intervention_modes.append("workload_review")
            context.assessment_questions.append("check whether too many open tasks are creating avoidance")
            context.rationale.append("The current workload may be contributing to avoidance.")

        if intent in {"add_task", "plan"} and isinstance(proactive_suggestions, dict):
            if proactive_suggestions.get("type") == "break_reminder_offer":
                context.intervention_modes.append("offer_break_reminder_cadence")
                context.planning_options.append("offer optional 30 or 45 minute break reminders for the long plan")
                context.closing_style = "one_relevant_offer"
                context.max_questions = max(context.max_questions, 1)
                context.rationale.append("The planned workload is long enough that opt-in break reminders may help.")

        if has_pending_context:
            context.intervention_modes.append("context_continuity")
            context.rationale.append("A prior working context is active and should be preserved.")

        context.intervention_modes = self._unique(context.intervention_modes)
        context.avoid_moves = self._unique(context.avoid_moves)
        context.assessment_questions = self._unique(context.assessment_questions)
        context.planning_options = self._unique(context.planning_options)
        context.rationale = self._unique(context.rationale)
        self._apply_closing_policy(context, intent, memory_context)
        return context

    def _day_phase(self, hour: int) -> str:
        if hour < 6:
            return "night"
        if hour < 12:
            return "morning"
        if hour < 18:
            return "afternoon"
        if hour < self.late_day_start_hour:
            return "evening"
        return "late_day"

    def _is_sleep_time(self, hour: int) -> bool:
        return hour >= 23 or hour < 6

    def _is_meal_time(self, hour: int) -> bool:
        return 11 <= hour <= 13 or 17 <= hour <= 20

    def _readiness(self, payload: dict[str, Any]) -> str:
        value = str(payload.get("readiness") or "unknown").strip().lower()
        return value if value in {"ready", "ambivalent", "low", "opt_out", "unknown"} else "unknown"

    def _planning_permission(self, payload: dict[str, Any]) -> bool | None:
        value = payload.get("planning_permission")
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0"}:
            return False
        return None

    def _start_timing(self, payload: dict[str, Any]) -> str:
        value = str(payload.get("start_timing") or "unknown").strip().lower()
        return value if value in {"now", "later", "unknown"} else "unknown"

    def _allows_immediate_task_push(
        self,
        intent: str,
        readiness: str,
        planning_permission: bool | None,
        start_timing: str,
    ) -> bool:
        if intent in {"copresence", "schedule_reminder", "schedule_break_reminders"}:
            return True
        if readiness in {"low", "opt_out"}:
            return False
        if start_timing == "now":
            return True
        return planning_permission is True and readiness == "ready"

    def _unique(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _apply_closing_policy(
        self,
        context: DialoguePolicyContext,
        intent: str,
        memory_context: dict[str, Any],
    ) -> None:
        working_context = memory_context.get("working_context") or {}
        has_anchor = bool(
            working_context.get("temporal_anchor")
            or working_context.get("pending_intention")
            or working_context.get("next_follow_up")
        )
        if context.user_readiness in {"low", "opt_out"}:
            context.closing_style = "supportive_pause"
            context.max_questions = 0
            context.avoid_moves.append("ending_with_task_pressure_question")
            return
        if context.task_action_mode == "task_record_only":
            context.closing_style = "record_and_wait"
            context.max_questions = 0
            context.avoid_moves.append("adding_start_question_after_recording_task")
            return
        if has_anchor:
            context.closing_style = "confirm_context_and_stop"
            context.max_questions = 0
            context.avoid_moves.append("asking_again_after_context_is_set")
            return
        if "sleep_or_shutdown" in context.intervention_modes:
            context.closing_style = "recovery_or_next_checkpoint"
            context.max_questions = 0
            context.avoid_moves.append("adding_optional_question_after_plan")
            return
        if "late_day_recovery_or_tomorrow_planning" in context.intervention_modes:
            context.closing_style = "recovery_or_next_checkpoint"
            context.max_questions = 0
            context.avoid_moves.append("adding_optional_question_after_plan")
            return
        if intent in {"schedule_reminder", "schedule_break_reminders", "checkin", "status"}:
            context.closing_style = "confirm_and_stop"
            context.max_questions = 0
            context.avoid_moves.append("adding_followup_question_by_default")
