"""CentralCoordinator for the ACSP accountability coach."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from accountability_coach.core.interfaces import UserStateStore
from accountability_coach.core.json_store import JsonUserStateStore
from accountability_coach.core.models import (
    CHECKIN_DELAYED,
    CHECKIN_SKIPPED,
    EVIDENCE_SUSPICIOUS,
    EVIDENCE_UNCERTAIN,
    RISK_NONE,
    ROLE_PARTNER,
    TASK_COMPLETED,
    TASK_DEFERRED,
    CheckInRecord,
    GuidancePlan,
    RiskAssessment,
    RoleDecision,
    Task,
    UserState,
    normalize_checkin,
    normalize_task,
    iso_from_datetime,
    now_iso,
    parse_datetime,
)
from accountability_coach.modules.commitments import CommitmentContractManager
from accountability_coach.modules.copresence import CoPresenceAgent
from accountability_coach.modules.emotional_dialogue import EmotionalDialoguePlaybook
from accountability_coach.modules.emotional_support import EmotionalSupportAgent
from accountability_coach.modules.evidence_verification import DaKaEvidenceVerifier
from accountability_coach.modules.knowledge_support import KnowledgeSupportAgent
from accountability_coach.modules.onboarding import TrustOnboardingFlow
from accountability_coach.modules.progress_review import ProgressReviewAgent
from accountability_coach.modules.proactive import (
    ProactiveConversationAgent,
    ProactivePrompt,
)
from accountability_coach.modules.resource_pool import ResourcePoolAgent
from accountability_coach.modules.risk_detection import RiskDetector
from accountability_coach.modules.role_arbiter import RoleArbiter
from accountability_coach.modules.schedule_planning import SchedulePlanningAgent
from accountability_coach.modules.supervision_customization import (
    SupervisionCustomization,
)
from accountability_coach.modules.task_guidance import TaskGuidanceAgent
from accountability_coach.modules.task_tracking import TaskTrackingAgent


@dataclass(slots=True)
class CoachModules:
    """Bundle of ACSP sub-agents owned by the coordinator."""

    supervision: SupervisionCustomization = field(default_factory=SupervisionCustomization)
    schedule: SchedulePlanningAgent = field(default_factory=SchedulePlanningAgent)
    tracking: TaskTrackingAgent = field(default_factory=TaskTrackingAgent)
    guidance: TaskGuidanceAgent = field(default_factory=TaskGuidanceAgent)
    knowledge: KnowledgeSupportAgent = field(default_factory=KnowledgeSupportAgent)
    emotional: EmotionalSupportAgent = field(default_factory=EmotionalSupportAgent)
    onboarding: TrustOnboardingFlow = field(default_factory=TrustOnboardingFlow)
    role_arbiter: RoleArbiter = field(default_factory=RoleArbiter)
    risk: RiskDetector = field(default_factory=RiskDetector)
    evidence: DaKaEvidenceVerifier = field(default_factory=DaKaEvidenceVerifier)
    copresence: CoPresenceAgent = field(default_factory=CoPresenceAgent)
    emotional_dialogue: EmotionalDialoguePlaybook = field(default_factory=EmotionalDialoguePlaybook)
    resources: ResourcePoolAgent = field(default_factory=ResourcePoolAgent)
    reviews: ProgressReviewAgent = field(default_factory=ProgressReviewAgent)
    commitments: CommitmentContractManager = field(default_factory=CommitmentContractManager)
    proactive: ProactiveConversationAgent = field(default_factory=ProactiveConversationAgent)


class CentralCoordinator:
    """Executive brain for the accountability coach architecture.

    It performs the three functions named in Section 4.1: intent routing,
    global state management, and response aggregation.
    """

    def __init__(
        self,
        store: UserStateStore | None = None,
        memory_dir: str | Path | None = None,
        modules: CoachModules | None = None,
    ) -> None:
        base_dir = Path(memory_dir or ".accountability_coach_memory")
        self.store = store or JsonUserStateStore(base_dir)
        self.modules = modules or CoachModules()

    def handle_intent(
        self,
        user_id: str,
        intent: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Route a simple backend intent to the appropriate sub-agent flow."""
        payload = payload or {}
        if intent == "configure":
            return self.configure_supervision(user_id, payload)
        if intent == "add_task":
            return self.add_or_update_task(user_id, payload)
        if intent == "plan":
            return self.plan_schedule(user_id, payload)
        if intent == "checkin":
            return self.record_checkin(user_id, payload)
        if intent == "status":
            return self.query_status(user_id)
        if intent == "knowledge":
            return self.request_knowledge_support(
                user_id,
                task_id=str(payload.get("task_id", "")),
                query=str(payload.get("query", "")),
            )
        if intent == "emotion":
            return self.get_emotional_adjustment(user_id)
        if intent == "onboarding_start":
            return self.start_onboarding(user_id)
        if intent == "onboarding_response":
            return self.record_onboarding_response(user_id, payload)
        if intent == "risk":
            return self.assess_risk(user_id, str(payload.get("text", "")))
        if intent == "emotional_dialogue":
            return self.get_emotional_dialogue(user_id, str(payload.get("text", "")))
        if intent == "resources":
            return self.suggest_resources(user_id, payload.get("task_id"), str(payload.get("query", "")))
        if intent == "review":
            return self.generate_progress_review(user_id, str(payload.get("period", "weekly")))
        if intent == "proactive_suggestions":
            return self.get_proactive_suggestions(user_id)
        if intent == "break_reminders":
            return self.schedule_break_reminders(
                user_id,
                interval_minutes=int(payload.get("interval_minutes", 45) or 45),
                duration_minutes=payload.get("duration_minutes"),
                start_at=payload.get("start_at"),
                message=str(payload.get("message") or "到休息点了，站起来喝口水，活动一下再继续。"),
            )
        raise ValueError(f"Unknown intent: {intent}")

    def start_onboarding(self, user_id: str) -> dict[str, Any]:
        """Return the next trust-building onboarding script."""
        state = self.store.load(user_id)
        script = self.modules.onboarding.build_opening_script(state)
        self._set_role(state, latest_text="onboarding trust building")
        self.store.save(state)
        return {"state": asdict(state), "onboarding_script": asdict(script)}

    def record_onboarding_response(
        self,
        user_id: str,
        response_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist onboarding answers and return the next trust-building step."""
        state = self.store.load(user_id)
        next_script = self.modules.onboarding.record_response(state, response_data)
        self._set_role(state, latest_text=str(response_data))
        self.store.save(state)
        return {"state": asdict(state), "onboarding_script": asdict(next_script)}

    def configure_supervision(
        self,
        user_id: str,
        config_data: dict[str, Any],
    ) -> UserState:
        """Pre-intervention setup: persona, intensity, goals, background."""
        state = self.store.load(user_id)
        state = self.modules.supervision.configure(state, config_data)
        self._set_role(state, latest_text=str(config_data))
        self.store.save(state)
        return state

    def add_or_update_task(
        self,
        user_id: str,
        task_data: dict[str, Any],
    ) -> UserState:
        """Add or update a task in shared memory."""
        state = self.store.load(user_id)
        task = normalize_task(task_data)
        existing = self._find_task(state, task.task_id)
        if existing:
            self._copy_task(existing, task)
        else:
            state.tasks.append(task)
        state.acsp_layer = "operational"
        self._set_role(state, latest_text=task.notes or task.title)
        state.updated_at = now_iso()
        self.store.save(state)
        return state

    def plan_schedule(
        self,
        user_id: str,
        options: dict[str, Any] | None = None,
    ) -> UserState:
        """Generate or regenerate schedule planning scaffolding."""
        state = self.store.load(user_id)
        role_decision = self._set_role(state)
        adjustment = self.modules.emotional.derive_adjustment(state.emotion)
        adjustment = self.modules.role_arbiter.apply_to_adjustment(
            role_decision,
            adjustment,
        )
        state.tracking_state["emotional_adjustment"] = adjustment
        now = self._option_datetime(options or {}, "current_datetime")
        self.modules.schedule.build_initial_schedule(
            state,
            current_datetime=now,
            options=options or {},
            adjustment=adjustment,
        )
        if (options or {}).get("enable_proactive_prompts", True):
            self._append_proactive_prompts(
                state,
                self.modules.proactive.plan_checkpoints(state),
            )
        state.updated_at = now_iso()
        self.store.save(state)
        return state

    def record_checkin(
        self,
        user_id: str,
        checkin_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Closed-loop DaKa processing: tracking, emotion, guidance, replanning."""
        state = self.store.load(user_id)
        checkin = normalize_checkin(checkin_data)
        state = self.modules.tracking.update_from_checkin(state, checkin)
        evidence_assessment = self.modules.evidence.assess(state, checkin)
        state.evidence_assessments.append(evidence_assessment)
        state.emotion = self.modules.emotional.update_from_checkin(
            state.emotion,
            checkin,
        )
        tracking_insights = self.modules.tracking.derive_tracking_insights(state)
        role_decision = self._set_role(
            state,
            latest_text=checkin.note,
            tracking_insights=tracking_insights,
        )
        emotional_adjustment = self.modules.emotional.derive_adjustment(state.emotion)
        emotional_adjustment = self.modules.role_arbiter.apply_to_adjustment(
            role_decision,
            emotional_adjustment,
        )
        state.tracking_state["emotional_adjustment"] = emotional_adjustment
        risk = self.modules.risk.assess(state, latest_text=checkin.note)
        if risk.level != RISK_NONE:
            state.risk_assessments.append(risk)
        state.intervention_paused = risk.pause_regular_intervention

        if risk.pause_regular_intervention:
            guidance = self._risk_guidance(risk)
            replan_triggered = False
        else:
            guidance = self.modules.guidance.generate_guidance(
                state,
                checkin=checkin,
                tracking_insights=tracking_insights,
                emotional_adjustment=emotional_adjustment,
            )
            guidance.role = role_decision.role
            guidance.tone = str(emotional_adjustment.get("guidance_tone", guidance.tone))
            if evidence_assessment.consistency_level in {EVIDENCE_SUSPICIOUS, EVIDENCE_UNCERTAIN}:
                guidance.reflection_questions.append(evidence_assessment.ritual_prompt)
                guidance.emotional_support_flags.append("daka_consistency_dialogue")
            if guidance.commitments:
                state.commitments.extend(guidance.commitments)
                self.modules.commitments.activate_suggestions(state)
            changed_commitments = self.modules.commitments.evaluate_from_latest_checkin(state)

            replan_triggered = self._should_replan(checkin, guidance, emotional_adjustment)
            if replan_triggered:
                self.modules.schedule.adapt_schedule_after_feedback(
                    state,
                    feedback={
                        "reason": "checkin_feedback",
                        "emotional_adjustment": emotional_adjustment,
                    },
                )

        state.current_role = role_decision.role
        state.acsp_layer = (
            "regulatory"
            if emotional_adjustment.get("distress_detected") or risk.level != RISK_NONE
            else "operational"
        )
        state.updated_at = now_iso()
        self.store.save(state)

        return {
            "state": asdict(state),
            "guidance_plan": asdict(guidance),
            "tracking_insights": asdict(tracking_insights),
            "emotional_adjustment": emotional_adjustment,
            "role_decision": asdict(role_decision),
            "risk_assessment": asdict(risk),
            "evidence_assessment": asdict(evidence_assessment),
            "changed_commitments": [asdict(item) for item in changed_commitments]
            if not risk.pause_regular_intervention
            else [],
            "replan_triggered": replan_triggered,
        }

    def query_status(self, user_id: str) -> dict[str, Any]:
        """Return a compact overview for dialogue or API layers."""
        state = self.store.load(user_id)
        insights = self.modules.tracking.derive_tracking_insights(state)
        role_decision = self._set_role(state, tracking_insights=insights)
        adjustment = self.modules.emotional.derive_adjustment(state.emotion)
        adjustment = self.modules.role_arbiter.apply_to_adjustment(
            role_decision,
            adjustment,
        )
        state.tracking_state["emotional_adjustment"] = adjustment
        self.store.save(state)
        due_reminders = self.modules.tracking.get_due_reminders(state)
        active_tasks = [
            task for task in state.tasks if task.status not in {TASK_COMPLETED, TASK_DEFERRED}
        ]
        return {
            "user_id": state.user_id,
            "role": role_decision.role,
            "role_decision": asdict(role_decision),
            "acsp_layer": state.acsp_layer,
            "supervision": asdict(state.supervision),
            "intervention_paused": state.intervention_paused,
            "latest_risk_assessment": asdict(state.risk_assessments[-1])
            if state.risk_assessments
            else None,
            "latest_evidence_assessment": asdict(state.evidence_assessments[-1])
            if state.evidence_assessments
            else None,
            "active_task_count": len(active_tasks),
            "active_tasks": [asdict(item) for item in active_tasks[:5]],
            "planned_block_count": len(state.schedule),
            "tracking_insights": asdict(insights),
            "emotion": asdict(state.emotion),
            "emotional_adjustment": adjustment,
            "due_reminders": [asdict(item) for item in due_reminders],
            "next_blocks": [asdict(item) for item in state.schedule[:3]],
            "recent_dialogue": list(state.tracking_state.get("recent_dialogue", []) or [])[-6:],
            "proactive_suggestions": self.modules.proactive.break_reminder_offer(state),
        }

    def request_knowledge_support(
        self,
        user_id: str,
        task_id: str,
        query: str = "",
    ) -> dict[str, Any]:
        """Explicit KnowledgeSupport activation for capability bottlenecks."""
        state = self.store.load(user_id)
        task = self._find_task(state, task_id)
        if not task:
            return {"error": f"Task not found: {task_id}", "sources": []}
        sources = self.modules.knowledge.suggest_relevant_sources(
            state,
            task,
            query=query,
        )
        methods = self.modules.knowledge.methodological_guidance(task)
        state.tracking_state["knowledge_request_count"] = (
            int(state.tracking_state.get("knowledge_request_count", 0) or 0) + 1
        )
        role_decision = self._set_role(
            state,
            latest_text=f"knowledge support {query} resource method",
        )
        state.updated_at = now_iso()
        self.store.save(state)
        return {
            "task": asdict(task),
            "sources": [asdict(source) for source in sources],
            "methodological_guidance": methods,
            "role": role_decision.role,
            "role_decision": asdict(role_decision),
        }

    def register_knowledge_source(
        self,
        user_id: str,
        source_data: dict[str, Any],
    ) -> UserState:
        state = self.store.load(user_id)
        self.modules.knowledge.register_source(state, source_data)
        state.updated_at = now_iso()
        self.store.save(state)
        return state

    def get_emotional_adjustment(self, user_id: str) -> dict[str, object]:
        state = self.store.load(user_id)
        role_decision = self._set_role(state)
        adjustment = self.modules.emotional.derive_adjustment(state.emotion)
        adjustment = self.modules.role_arbiter.apply_to_adjustment(
            role_decision,
            adjustment,
        )
        state.tracking_state["emotional_adjustment"] = adjustment
        self.store.save(state)
        return adjustment

    def record_emotional_signal(
        self,
        user_id: str,
        *,
        description: str,
        emotion_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update the emotional baseline from non-check-in affective cues."""
        state = self.store.load(user_id)
        synthetic = CheckInRecord(
            status="emotion_signal",
            note=description,
            emotion_tags=emotion_tags or [],
        )
        state.emotion = self.modules.emotional.update_from_checkin(state.emotion, synthetic)
        role_decision = self._set_role(state, latest_text=description)
        adjustment = self.modules.emotional.derive_adjustment(state.emotion)
        adjustment = self.modules.role_arbiter.apply_to_adjustment(role_decision, adjustment)
        state.tracking_state["emotional_adjustment"] = adjustment
        state.acsp_layer = "regulatory" if adjustment.get("distress_detected") else state.acsp_layer
        state.updated_at = now_iso()
        self.store.save(state)
        return {
            "state": asdict(state),
            "emotional_adjustment": adjustment,
            "role_decision": asdict(role_decision),
        }

    def assess_risk(self, user_id: str, text: str = "") -> dict[str, Any]:
        """Run risk escalation detection without changing task progress."""
        state = self.store.load(user_id)
        risk = self.modules.risk.assess(state, latest_text=text)
        if risk.level != RISK_NONE:
            state.risk_assessments.append(risk)
        state.intervention_paused = risk.pause_regular_intervention
        if state.intervention_paused:
            self._set_role(state, latest_text=text)
        state.updated_at = now_iso()
        self.store.save(state)
        return {"state": asdict(state), "risk_assessment": asdict(risk)}

    def start_copresence_session(
        self,
        user_id: str,
        task_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.store.load(user_id)
        options = options or {}
        session = self.modules.copresence.start_pomodoro_session(
            state,
            task_id=task_id,
            block_id=options.get("block_id"),
            duration_minutes=int(options.get("duration_minutes", 25)),
            ping_interval_minutes=int(options.get("ping_interval_minutes", 5)),
            authorized_screen_activity=bool(options.get("authorized_screen_activity", False)),
        )
        self.store.save(state)
        return {"state": asdict(state), "copresence_session": asdict(session)}

    def record_screen_activity(
        self,
        user_id: str,
        session_id: str,
        activity_app: str,
        window_title: str,
    ) -> dict[str, Any]:
        state = self.store.load(user_id)
        session = self.modules.copresence.record_activity_sample(
            state,
            session_id,
            activity_app,
            window_title,
        )
        self.store.save(state)
        return {"state": asdict(state), "copresence_session": asdict(session) if session else None}

    def get_emotional_dialogue(self, user_id: str, text: str = "") -> dict[str, Any]:
        state = self.store.load(user_id)
        plan = self.modules.emotional_dialogue.build_plan(state, text)
        self.store.save(state)
        return {"state": asdict(state), "emotional_dialogue": asdict(plan)}

    def suggest_resources(
        self,
        user_id: str,
        task_id: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        state = self.store.load(user_id)
        task = self._find_task(state, task_id) if task_id else None
        resources = self.modules.resources.suggest_resources(state, task, query)
        self.store.save(state)
        return {"resources": [asdict(item) for item in resources]}

    def generate_progress_review(
        self,
        user_id: str,
        period: str = "weekly",
    ) -> dict[str, Any]:
        state = self.store.load(user_id)
        review = self.modules.reviews.generate_review(state, period=period)
        self.store.save(state)
        return {"state": asdict(state), "progress_review": asdict(review)}

    def create_commitment(
        self,
        user_id: str,
        task_id: str,
        text: str,
        due_at: str | None = None,
        penalty: str = "",
    ) -> dict[str, Any]:
        state = self.store.load(user_id)
        commitment = self.modules.commitments.create_contract(
            state,
            task_id,
            text,
            due_at=due_at,
            penalty=penalty,
        )
        self.store.save(state)
        return {"state": asdict(state), "commitment": asdict(commitment)}

    def schedule_push(
        self,
        user_id: str,
        message: str,
        due_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a future push reminder for an adapter to deliver."""
        state = self.store.load(user_id)
        pushes = list(state.tracking_state.get("scheduled_pushes", []) or [])
        push = {
            "push_id": f"push_{len(pushes) + 1}_{int(datetime.now(timezone.utc).timestamp())}",
            "user_id": user_id,
            "message": message,
            "due_at": due_at,
            "status": "scheduled",
            "created_at": now_iso(),
            "metadata": metadata or {},
        }
        pushes.append(push)
        state.tracking_state["scheduled_pushes"] = pushes
        state.updated_at = now_iso()
        self.store.save(state)
        return push

    def schedule_break_reminders(
        self,
        user_id: str,
        interval_minutes: int,
        duration_minutes: int | None = None,
        start_at: str | None = None,
        message: str = "到休息点了，站起来喝口水，活动一下再继续。",
    ) -> dict[str, Any]:
        """Schedule opt-in periodic break reminders for a long plan."""
        state = self.store.load(user_id)
        start_dt = parse_datetime(start_at) if start_at else None
        prompts = self.modules.proactive.break_reminders(
            state,
            interval_minutes=interval_minutes,
            start_at=start_dt,
            duration_minutes=duration_minutes,
            message=message,
        )
        pushes = self._append_proactive_prompts(state, prompts)
        state.updated_at = now_iso()
        self.store.save(state)
        return {"state": asdict(state), "pushes": pushes}

    def get_proactive_suggestions(self, user_id: str) -> dict[str, Any]:
        """Return proactive opportunities an adapter/dialogue layer can offer."""
        state = self.store.load(user_id)
        return {
            "break_reminder_offer": self.modules.proactive.break_reminder_offer(state),
            "scheduled_push_count": len(state.tracking_state.get("scheduled_pushes", []) or []),
        }

    def pop_due_pushes(
        self,
        user_id: str,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return due push reminders and mark them delivered."""
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        state = self.store.load(user_id)
        pushes = list(state.tracking_state.get("scheduled_pushes", []) or [])
        due: list[dict[str, Any]] = []
        followups: list[dict[str, Any]] = []
        changed = False
        for push in pushes:
            if push.get("status") != "scheduled":
                continue
            due_at = parse_datetime(str(push.get("due_at") or ""))
            if due_at and due_at <= now:
                if self._should_cancel_silence_followup(state, push):
                    push["status"] = "cancelled"
                    push["cancelled_at"] = iso_from_datetime(now)
                    push["cancel_reason"] = "user_replied_after_parent_push"
                    changed = True
                    continue
                push["status"] = "delivered"
                push["delivered_at"] = iso_from_datetime(now)
                due.append(dict(push))
                followup = self._build_silence_followup(state, pushes, followups, push, now)
                if followup:
                    followups.append(followup)
                changed = True
        if followups:
            pushes.extend(followups)
            changed = True
        if changed:
            state.tracking_state["scheduled_pushes"] = pushes
            state.updated_at = now_iso()
            self.store.save(state)
        return due

    def _append_proactive_prompts(
        self,
        state: UserState,
        prompts: list[ProactivePrompt],
    ) -> list[dict[str, Any]]:
        pushes = list(state.tracking_state.get("scheduled_pushes", []) or [])
        existing_keys = {
            str(item.get("metadata", {}).get("dedupe_key"))
            for item in pushes
            if isinstance(item.get("metadata"), dict)
        }
        created: list[dict[str, Any]] = []
        for prompt in prompts:
            dedupe_key = self._proactive_dedupe_key(prompt)
            if dedupe_key in existing_keys:
                continue
            push_id = f"push_{len(pushes) + len(created) + 1}_{int(datetime.now(timezone.utc).timestamp())}"
            push = prompt.to_push(state.user_id, push_id)
            push["created_at"] = now_iso()
            push["metadata"]["dedupe_key"] = dedupe_key
            created.append(push)
            existing_keys.add(dedupe_key)
        if created:
            pushes.extend(created)
            state.tracking_state["scheduled_pushes"] = pushes
        return created

    def _build_silence_followup(
        self,
        state: UserState,
        pushes: list[dict[str, Any]],
        pending_followups: list[dict[str, Any]],
        delivered_push: dict[str, Any],
        delivered_at: datetime,
    ) -> dict[str, Any] | None:
        prompt = self.modules.proactive.silence_follow_up(delivered_push, delivered_at)
        if prompt is None:
            return None
        dedupe_key = self._proactive_dedupe_key(prompt)
        for item in [*pushes, *pending_followups]:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if metadata.get("dedupe_key") == dedupe_key and item.get("status") != "cancelled":
                return None
        existing_count = len(pushes) + len(pending_followups)
        push_id = f"push_{existing_count + 1}_{int(datetime.now(timezone.utc).timestamp())}"
        push = prompt.to_push(state.user_id, push_id)
        push["created_at"] = now_iso()
        push["metadata"]["dedupe_key"] = dedupe_key
        return push

    def _should_cancel_silence_followup(self, state: UserState, push: dict[str, Any]) -> bool:
        metadata = push.get("metadata") if isinstance(push.get("metadata"), dict) else {}
        if metadata.get("reason") != "silence_followup":
            return False
        parent_delivered_at = parse_datetime(str(metadata.get("parent_delivered_at") or ""))
        if parent_delivered_at is None:
            return False
        return self._has_user_dialogue_after(state, parent_delivered_at)

    def _has_user_dialogue_after(self, state: UserState, moment: datetime) -> bool:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        memory = state.tracking_state.get("dialogue_memory")
        archive = memory.get("archive", []) if isinstance(memory, dict) else []
        for event in archive:
            if not isinstance(event, dict) or event.get("speaker") != "user":
                continue
            created_at = parse_datetime(str(event.get("created_at") or ""))
            if created_at is None:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at > moment:
                return True
        return False

    def _proactive_dedupe_key(self, prompt: ProactivePrompt) -> str:
        metadata = prompt.metadata or {}
        return "|".join(
            [
                str(prompt.reason),
                str(prompt.due_at),
                str(metadata.get("block_id", "")),
                str(metadata.get("task_id", "")),
                str(metadata.get("interval_minutes", "")),
                str(metadata.get("elapsed_minutes", "")),
                str(metadata.get("parent_push_id", "")),
                str(metadata.get("follow_up_stage", "")),
            ]
        )

    def query_state(self, user_id: str) -> UserState:
        """Return the full aggregate state for internal callers and tests."""
        return self.store.load(user_id)

    def _should_replan(
        self,
        checkin,
        guidance: GuidancePlan,
        emotional_adjustment: dict[str, object],
    ) -> bool:
        low_schedule = float(
            emotional_adjustment.get("schedule_intensity_multiplier", 1.0)
        ) < 0.9
        return (
            guidance.needs_replan
            or low_schedule
            or checkin.status in {CHECKIN_SKIPPED, CHECKIN_DELAYED}
        )

    def _set_role(
        self,
        state: UserState,
        latest_text: str = "",
        tracking_insights: Any | None = None,
    ) -> RoleDecision:
        decision = self.modules.role_arbiter.decide(
            state,
            latest_text=latest_text,
            tracking_insights=tracking_insights,
        )
        state.role_decision = decision
        state.current_role = decision.role
        return decision

    def _risk_guidance(self, risk: RiskAssessment) -> GuidancePlan:
        return GuidancePlan(
            reflection_questions=[
                "Are you in immediate danger right now, or can you contact a trusted person?"
            ],
            reinforcement_messages=list(risk.recommended_actions),
            plan_adjustments=[],
            commitments=[],
            environment_suggestions=[
                "Move away from academic performance pressure until safety and support are addressed."
            ],
            role=ROLE_PARTNER,
            tone="lenient",
            needs_replan=False,
            emotional_support_flags=["risk_escalation"],
        )

    def _find_task(self, state: UserState, task_id: str) -> Task | None:
        for task in state.tasks:
            if task.task_id == task_id:
                return task
        return None

    def _copy_task(self, target: Task, source: Task) -> None:
        for key, value in asdict(source).items():
            setattr(target, key, value)
        target.updated_at = now_iso()

    def _option_datetime(
        self,
        options: dict[str, Any],
        key: str,
    ) -> datetime | None:
        value = options.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None
