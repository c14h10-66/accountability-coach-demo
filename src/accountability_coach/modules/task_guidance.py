"""Task Guidance Agent: reflection, reward, restructuring, commitment."""

from __future__ import annotations

from accountability_coach.core.models import (
    CHECKIN_COMPLETED,
    CHECKIN_DELAYED,
    CHECKIN_PARTIAL,
    CHECKIN_SKIPPED,
    ROLE_COACH,
    ROLE_MENTOR,
    ROLE_PARTNER,
    AdjustmentAction,
    CheckInRecord,
    CommitmentSuggestion,
    GuidancePlan,
    Task,
    UserState,
    make_id,
)


class TaskGuidanceAgent:
    """Execution scaffolding from Sections 3.3.3 and 4.5."""

    def generate_guidance(
        self,
        user_state: UserState,
        checkin: CheckInRecord | None = None,
        tracking_insights: object | None = None,
        emotional_adjustment: dict[str, object] | None = None,
    ) -> GuidancePlan:
        """Create structured interventions from DaKa outcomes."""
        checkin = checkin or (user_state.checkins[-1] if user_state.checkins else None)
        emotional_adjustment = emotional_adjustment or user_state.tracking_state.get(
            "emotional_adjustment",
            {},
        )
        tone = str(emotional_adjustment.get("guidance_tone", "neutral"))
        task = self._find_task(user_state, checkin.task_id) if checkin else None
        support_flags = list(emotional_adjustment.get("support_flags", []))

        plan = GuidancePlan(
            role=ROLE_PARTNER if tone == "lenient" else ROLE_COACH,
            tone=tone,
            emotional_support_flags=support_flags,
        )
        if not checkin:
            plan.reflection_questions.append(
                "What is the smallest study action that would make today count?"
            )
            return plan

        if checkin.status == CHECKIN_COMPLETED and checkin.progress_percent >= 80:
            self._completion_guidance(plan, checkin, task)
        elif checkin.status == CHECKIN_DELAYED and checkin.justified_delay:
            self._justified_delay_guidance(plan, checkin, task)
        elif checkin.status == CHECKIN_PARTIAL:
            self._partial_guidance(plan, checkin, task)
        else:
            self._procrastination_guidance(plan, checkin, task, user_state)

        if "cognitive_reframing" in support_flags:
            plan.reflection_questions.append(
                "What is a more balanced explanation than 'I failed completely'?"
            )
        if "shared_responsibility" in support_flags:
            plan.reinforcement_messages.append(
                "This setback is a planning signal we handle together, not proof that you are incapable."
            )
        return plan

    def _completion_guidance(
        self,
        plan: GuidancePlan,
        checkin: CheckInRecord,
        task: Task | None,
    ) -> None:
        title = task.title if task else "this task"
        plan.reflection_questions.extend(
            [
                f"What helped you complete {title} this time?",
                "How would you rate the quality of the output, and what evidence supports that rating?",
                "What was your physical or mental state during the most productive part?",
            ]
        )
        plan.reinforcement_messages.extend(
            [
                "You converted intention into visible progress. Mark the behavior clearly so it can repeat.",
                "Take a small immediate reward that does not make the next block harder to start.",
            ]
        )
        plan.environment_suggestions.append(
            "Keep the current workspace setup if it supported focus; change only one friction point."
        )

    def _justified_delay_guidance(
        self,
        plan: GuidancePlan,
        checkin: CheckInRecord,
        task: Task | None,
    ) -> None:
        title = task.title if task else "the delayed task"
        plan.role = ROLE_PARTNER
        plan.needs_replan = True
        plan.reinforcement_messages.append(
            "A justified delay is handled by recovery planning, not self-blame."
        )
        plan.reflection_questions.extend(
            [
                f"What condition needs to be true before {title} is feasible again?",
                "What is the smallest re-entry step you can do in the next block?",
            ]
        )
        plan.plan_adjustments.append(
            AdjustmentAction(
                action_type="replan_with_lower_load",
                target_id=task.task_id if task else checkin.task_id,
                description="Reduce the next block to a smaller re-entry action and preserve essential work.",
                payload={"focus_minutes": 15, "break_minutes": 10},
            )
        )

    def _partial_guidance(
        self,
        plan: GuidancePlan,
        checkin: CheckInRecord,
        task: Task | None,
    ) -> None:
        title = task.title if task else "this task"
        plan.needs_replan = checkin.progress_percent < 50
        plan.reflection_questions.extend(
            [
                f"Which part of {title} moved forward, even slightly?",
                "What blocked the remaining progress: unclear next step, low energy, or external interruption?",
                "What would make the next 15 minutes easier to begin?",
            ]
        )
        plan.reinforcement_messages.append(
            "Partial progress is usable evidence. We will convert it into the next concrete step."
        )
        plan.environment_suggestions.append(
            "Clear the desk or digital workspace so only the next action is visible."
        )
        if plan.needs_replan:
            plan.plan_adjustments.append(
                AdjustmentAction(
                    action_type="split_task",
                    target_id=task.task_id if task else checkin.task_id,
                    description="Split the task into a smaller next block because progress stayed below half.",
                    payload={"target_focus_minutes": 15},
                )
            )

    def _procrastination_guidance(
        self,
        plan: GuidancePlan,
        checkin: CheckInRecord,
        task: Task | None,
        user_state: UserState,
    ) -> None:
        title = task.title if task else "the planned task"
        plan.role = ROLE_COACH
        plan.needs_replan = True
        if user_state.emotion.distress_detected:
            plan.role = ROLE_PARTNER
        elif user_state.tracking_state.get("recent_skip_streak", 0) >= 2:
            plan.role = ROLE_MENTOR
        plan.reflection_questions.extend(
            [
                f"What exactly happened before you avoided {title}?",
                "Was the task too vague, too large, emotionally aversive, or blocked by missing knowledge?",
                "What is one action small enough that avoidance has less room to start?",
            ]
        )
        plan.reinforcement_messages.append(
            "We are naming the gap so it can be managed. The next step is a behavioral reset, not a character judgment."
        )
        plan.environment_suggestions.extend(
            [
                "Remove one distraction before the next block.",
                "Prepare the exact file, page, or problem set before starting the timer.",
            ]
        )
        plan.plan_adjustments.append(
            AdjustmentAction(
                action_type="reduce_cognitive_load",
                target_id=task.task_id if task else checkin.task_id,
                description="Lower the next block threshold and prioritize essential work.",
                payload={"essential_only": True, "focus_minutes": 15},
            )
        )
        plan.commitments.append(
            CommitmentSuggestion(
                commitment_id=make_id("commitment"),
                task_id=task.task_id if task else checkin.task_id,
                text=f"I will start {title} for 15 minutes and submit a DaKa immediately after.",
                penalty="If I skip without a concrete reason, I will do a small agreed penalty or remove one leisure app until the next check-in.",
            )
        )

    def _find_task(self, user_state: UserState, task_id: str) -> Task | None:
        for task in user_state.tasks:
            if task.task_id == task_id:
                return task
        return None


TaskGuidance = TaskGuidanceAgent
