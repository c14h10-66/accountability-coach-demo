"""LLM-level dialogue orchestrator for the accountability coach."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from accountability_coach.core.coordinator import CentralCoordinator
from accountability_coach.core.models import RISK_NONE, UserState
from accountability_coach.dialogue.access_control import AccessControl
from accountability_coach.dialogue.input_signals import EmojiEmotionInterpreter, InputSignal
from accountability_coach.dialogue.language_guard import PublicLanguageGuard
from accountability_coach.dialogue.llm import LLMClient, LLMError, build_llm_from_env
from accountability_coach.dialogue.memory import DialogueMemory
from accountability_coach.dialogue.models import DialogueTurn
from accountability_coach.dialogue.policy import DialoguePolicy, DialoguePolicyContext
from accountability_coach.dialogue.stickers import StickerLibrary
from accountability_coach.dialogue.user_preferences import UserPreferenceManager
from accountability_coach.modules.icbt_playbook import ICBTDialoguePlaybook
from accountability_coach.modules.reminder_scheduler import ReminderScheduler


ALLOWED_INTENTS = {
    "help",
    "status",
    "add_task",
    "plan",
    "checkin",
    "emotion",
    "resources",
    "review",
    "commitment",
    "copresence",
    "schedule_reminder",
    "schedule_break_reminders",
    "clarify",
    "chat",
}


class DialogueAgent:
    """Natural-language layer above CentralCoordinator.

    The paper's CentralCoordinator remains the executive brain for state and
    sub-agent orchestration.  This class adds the missing conversational layer:
    trust-building, human-coach style accountability dialogue, ICBT-informed
    emotional scaffolding, and LLM-based intent/response generation.
    """

    def __init__(
        self,
        coordinator: CentralCoordinator,
        llm: LLMClient | None = None,
        icbt: ICBTDialoguePlaybook | None = None,
        reminders: ReminderScheduler | None = None,
        memory: DialogueMemory | None = None,
        policy: DialoguePolicy | None = None,
        stickers: StickerLibrary | None = None,
        language_guard: PublicLanguageGuard | None = None,
        input_signals: EmojiEmotionInterpreter | None = None,
        access_control: AccessControl | None = None,
        preferences: UserPreferenceManager | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.llm = llm or build_llm_from_env()
        self.icbt = icbt or ICBTDialoguePlaybook()
        self.reminders = reminders or ReminderScheduler()
        self.memory = memory or DialogueMemory()
        self.policy = policy or DialoguePolicy()
        self.stickers = stickers or StickerLibrary()
        self.language_guard = language_guard or PublicLanguageGuard()
        self.input_signals = input_signals or EmojiEmotionInterpreter()
        self.access_control = access_control or AccessControl.from_env()
        self.preferences = preferences or UserPreferenceManager()

    def opening(self, user_id: str) -> str:
        access_turn = self._access_turn(user_id, "")
        if access_turn:
            return access_turn.reply
        status = self.coordinator.query_status(user_id)
        if status["active_task_count"] == 0 and not status["supervision"]["goals"]:
            self.coordinator.start_onboarding(user_id)
            state = self.coordinator.store.load(user_id)
            runtime = self.policy.runtime_context(self._user_timezone(user_id))
            time_text = self._opening_time_text(runtime)
            name = str(state.profile.get("display_name") or "").strip()
            greeting = f"{name}，你好" if name else "你好"
            hint = "" if state.profile.get("onboarding_intro_sent") else self.preferences.onboarding_hint(state)
            reply = (
                f"{greeting}，我是你的学业责任教练。{time_text}\n"
                "我主要做三件事：把学习任务说清楚，定个现实一点的时间，到点提醒你。\n"
                "卡住的时候，我们就把下一步拆小。你可以直接说想处理哪件事，也可以先随便讲两句。"
                + (f"\n{hint}" if hint else "")
            )
            state = self.coordinator.store.load(user_id)
            state.profile["onboarding_intro_sent"] = True
            self.coordinator.store.save(state)
            self._append_dialogue_event(user_id, "assistant", reply, "opening")
            return reply
        return self._render_status(status)

    def respond(self, user_id: str, text: str) -> DialogueTurn:
        text = text.strip()
        if not text:
            access_turn = self._access_turn(user_id, text)
            if access_turn:
                return access_turn
            return DialogueTurn(
                user_id=user_id,
                reply="我在。直接说你现在的任务、进度或卡点就行。",
                intent="empty",
            )
        if text in {"退出", "结束", "quit", "exit"}:
            return DialogueTurn(user_id=user_id, reply="好，今天先停在这里。", intent="exit")
        access_turn = self._access_turn(user_id, text)
        if access_turn:
            return access_turn
        if text in {"重置", "清空", "reset"}:
            previous = self.coordinator.store.load(user_id)
            reset_state = UserState(user_id=user_id)
            for key in ("access", "display_name", "timezone"):
                if key in previous.profile:
                    reset_state.profile[key] = previous.profile[key]
            if previous.profile.get("timezone"):
                reset_state.supervision.constraints["timezone"] = str(previous.profile["timezone"])
            self.coordinator.store.save(reset_state)
            return DialogueTurn(user_id=user_id, reply="好，重新开始。\n" + self.opening(user_id), intent="reset")
        preference_turn = self._preference_turn(user_id, text)
        if preference_turn:
            return preference_turn
        first_use_turn = self._first_use_turn(user_id, text)
        if first_use_turn:
            return first_use_turn

        input_signal = self.input_signals.from_text(text)
        semantic_text = "" if input_signal and input_signal.expression_only else text
        return self._respond_semantic(
            user_id,
            semantic_text,
            original_text=text,
            input_signal=input_signal,
        )

    def respond_signal(self, user_id: str, signal: InputSignal) -> DialogueTurn:
        """Respond to a non-text signal such as a sticker or emoji item."""
        access_turn = self._access_turn(user_id, "")
        if access_turn:
            return access_turn
        return self._respond_semantic(
            user_id,
            "",
            original_text=signal.raw,
            input_signal=signal,
        )

    def _access_turn(self, user_id: str, text: str) -> DialogueTurn | None:
        state = self.coordinator.store.load(user_id)
        decision = self.access_control.evaluate(state, text)
        if decision.should_save:
            self.coordinator.store.save(state)
        if not decision.handled:
            return None
        if decision.allowed:
            self._append_dialogue_event(
                user_id,
                "assistant",
                decision.reply,
                "access_authorized",
                decision.metadata,
            )
        return DialogueTurn(
            user_id=user_id,
            reply=decision.reply,
            intent="access_authorized" if decision.allowed else "access_required",
            metadata=decision.metadata,
        )

    def _preference_turn(self, user_id: str, text: str) -> DialogueTurn | None:
        state = self.coordinator.store.load(user_id)
        result = self.preferences.handle(state, text)
        if not result:
            return None
        self.coordinator.store.save(state)
        self._append_dialogue_event(
            user_id,
            "user",
            text,
            "profile_update",
            {"profile_update": result.changed_fields},
        )
        self._append_dialogue_event(
            user_id,
            "assistant",
            result.reply,
            "profile_update",
            {"profile_update": result.changed_fields},
        )
        return DialogueTurn(
            user_id=user_id,
            reply=result.reply,
            intent="profile_update",
            metadata={"profile_update": result.changed_fields},
        )

    def _first_use_turn(self, user_id: str, text: str) -> DialogueTurn | None:
        state = self.coordinator.store.load(user_id)
        if state.profile.get("onboarding_intro_sent"):
            return None
        if state.tasks or state.supervision.goals:
            return None
        if state.profile.get("display_name") or state.profile.get("timezone"):
            return None
        if text.strip().lower() not in {"你好", "嗨", "hello", "hi", "开始", "/start", "帮助", "help", "?"}:
            return None
        return DialogueTurn(user_id=user_id, reply=self.opening(user_id), intent="opening")

    def _respond_semantic(
        self,
        user_id: str,
        text: str,
        *,
        original_text: str,
        input_signal: InputSignal | None = None,
    ) -> DialogueTurn:
        risk_text = text or (input_signal.description if input_signal else "")
        risk = self.coordinator.assess_risk(user_id, risk_text)
        if risk["risk_assessment"]["level"] != RISK_NONE:
            reply = self._render_risk(risk)
            return DialogueTurn(
                user_id=user_id,
                reply=reply,
                intent="risk_escalation",
                risk_level=risk["risk_assessment"]["level"],
                tool_results={"risk": risk},
            )

        status = self.coordinator.query_status(user_id)
        memory_context = self._dialogue_memory(user_id)
        runtime_context = self.policy.runtime_context(self._user_timezone(user_id))
        action = self._decide_action(user_id, text, status, memory_context, runtime_context, input_signal)
        signal_result: dict[str, Any] | None = None
        if input_signal and input_signal.expression_only:
            signal_result = self.coordinator.record_emotional_signal(
                user_id,
                description=input_signal.description,
                emotion_tags=input_signal.emotion_tags,
            )
        tool_results = self._execute_action(user_id, action, text, input_signal)
        if signal_result:
            tool_results["emotional_signal"] = {
                "emotion_tags": input_signal.emotion_tags,
                "emotional_adjustment": signal_result.get("emotional_adjustment"),
                "role_decision": signal_result.get("role_decision"),
            }
        user_memory_text = (
            input_signal.memory_text()
            if input_signal and input_signal.expression_only
            else original_text
        )
        self._append_dialogue_event(
            user_id,
            "user",
            user_memory_text,
            str(action.get("intent", "chat")),
            {
                "action": action,
                **(
                    {"input_signal": input_signal.to_payload()}
                    if input_signal
                    else {}
                ),
            },
        )
        memory_context = self._dialogue_memory(user_id)
        updated_status = self.coordinator.query_status(user_id)
        formulation = self._build_icbt_formulation(user_id, text, action, input_signal)
        policy_context = self.policy.build_context(
            action=action,
            status=updated_status,
            memory_context=memory_context,
            runtime=runtime_context,
        )
        self._limit_time_context_repetition(user_id, policy_context)
        reply, used_llm = self._compose_reply(
            text,
            action,
            tool_results,
            updated_status,
            formulation,
            memory_context,
            policy_context.to_payload(),
            input_signal,
        )
        reply = self._polish_reply(reply)
        sticker = self._select_sticker(
            user_id,
            intent=str(action.get("intent", "chat")),
            policy_context=policy_context.to_payload(),
            risk_level=RISK_NONE,
            tool_results=tool_results,
        )
        turn = DialogueTurn(
            user_id=user_id,
            reply=reply,
            intent=str(action.get("intent", "chat")),
            role=str(updated_status.get("role", "")),
            used_llm=used_llm,
            sticker=sticker,
            tool_results=tool_results,
            metadata={
                "action": action,
                "icbt": asdict(formulation) if formulation else {},
                "dialogue_policy": policy_context.to_payload(),
                "input_signal": input_signal.to_payload() if input_signal else None,
                "status": updated_status,
            },
        )
        self._append_dialogue_event(
            user_id,
            "assistant",
            reply,
            str(action.get("intent", "chat")),
            {"used_llm": used_llm},
        )
        return turn

    def _decide_action(
        self,
        user_id: str,
        text: str,
        status: dict[str, Any],
        memory_context: dict[str, Any],
        runtime_context: object,
        input_signal: InputSignal | None = None,
    ) -> dict[str, Any]:
        if not self.llm.is_available():
            return {"intent": "llm_unavailable", "payload": {}}
        try:
            raw = self.llm.complete(
                [
                    {"role": "system", "content": self._intent_system_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "user_text": text,
                                "input_signal": input_signal.to_payload() if input_signal else None,
                                "status": self._compact_status(status),
                                "dialogue_memory": memory_context,
                                "runtime_context": asdict(runtime_context),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0.0,
            )
            return self._normalize_action(self._parse_action(raw), status)
        except LLMError as exc:
            return {"intent": "llm_error", "payload": {"error": str(exc)}}

    def _execute_action(
        self,
        user_id: str,
        action: dict[str, Any],
        text: str,
        input_signal: InputSignal | None = None,
    ) -> dict[str, Any]:
        intent = str(action.get("intent", "chat"))
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        if intent == "llm_unavailable":
            return {"error": "LLM is not configured"}
        if intent == "llm_error":
            return {"error": payload.get("error", "LLM request failed")}
        if intent == "help":
            return {"help": self._help_text()}
        if intent == "status":
            return {"status": self.coordinator.query_status(user_id)}
        if intent == "add_task":
            state = self.coordinator.add_or_update_task(user_id, self._task_payload(payload, text))
            return {"state": asdict(state), "task": asdict(state.tasks[-1]) if state.tasks else {}}
        if intent == "plan":
            state = self.coordinator.plan_schedule(user_id, payload)
            return {"state": asdict(state), "schedule": [asdict(item) for item in state.schedule[:5]]}
        if intent == "checkin":
            checkin_payload = self._checkin_payload(user_id, payload, text)
            return {"checkin_result": self.coordinator.record_checkin(user_id, checkin_payload)}
        if intent == "emotion":
            emotion_text = str(payload.get("text") or text or (input_signal.description if input_signal else ""))
            return {
                "emotional_dialogue": self.coordinator.get_emotional_dialogue(
                    user_id,
                    emotion_text,
                )
            }
        if intent == "resources":
            return {
                "resources": self.coordinator.suggest_resources(
                    user_id,
                    payload.get("task_id") or self._latest_task_id(user_id),
                    str(payload.get("query") or text),
                )
            }
        if intent == "review":
            return {"review": self.coordinator.generate_progress_review(user_id, str(payload.get("period", "weekly")))}
        if intent == "commitment":
            return {
                "commitment": self.coordinator.create_commitment(
                    user_id,
                    payload.get("task_id") or self._latest_task_id(user_id),
                    str(payload.get("text") or "我会先做 15 分钟并打卡。"),
                )
            }
        if intent == "copresence":
            return {
                "copresence": self.coordinator.start_copresence_session(
                    user_id,
                    payload.get("task_id") or self._latest_task_id(user_id),
                    {"duration_minutes": self._int_value(payload.get("duration_minutes"), 25)},
                )
            }
        if intent == "schedule_reminder":
            try:
                reminder_payload = self._reminder_payload(payload, text)
            except ValueError as exc:
                return {"clarify": str(exc)}
            push = self.coordinator.schedule_push(
                user_id,
                str(reminder_payload["message"]),
                str(reminder_payload["due_at"]),
                metadata={
                    "source": "dialogue",
                    **(
                        {"delay_seconds": reminder_payload["delay_seconds"]}
                        if reminder_payload.get("delay_seconds") is not None
                        else {}
                    ),
                },
            )
            return {"scheduled_push": push}
        if intent == "schedule_break_reminders":
            result = self.coordinator.schedule_break_reminders(
                user_id,
                interval_minutes=self._int_value(payload.get("interval_minutes"), 45),
                duration_minutes=self._optional_int_value(payload.get("duration_minutes")),
                start_at=str(payload.get("start_at")) if payload.get("start_at") else None,
                message=str(payload.get("message") or "到休息点了，站起来喝口水，活动一下再继续。"),
            )
            return {"break_reminders": result}
        if intent == "clarify":
            return {"clarify": str(payload.get("question") or "你想新增任务、汇报进度，还是处理卡住的状态？")}
        return {"chat": {"text": text}}

    def _compose_reply(
        self,
        text: str,
        action: dict[str, Any],
        tool_results: dict[str, Any],
        status: dict[str, Any],
        formulation: object | None,
        memory_context: dict[str, Any],
        policy_context: dict[str, Any],
        input_signal: InputSignal | None = None,
    ) -> tuple[str, bool]:
        intent = str(action.get("intent", "chat"))
        if intent == "llm_unavailable":
            return (
                "这个对话入口现在需要先配置 LLM 才能使用自然语言能力。\n"
                "请设置 ACCOUNTABILITY_COACH_LLM_BASE_URL、ACCOUNTABILITY_COACH_LLM_API_KEY、"
                "ACCOUNTABILITY_COACH_LLM_MODEL 后重新启动。"
            ), False
        if intent == "llm_error":
            return f"LLM 请求失败：{tool_results.get('error', 'unknown error')}", False
        if not self.llm.is_available():
            return "LLM 未配置，无法进行语义对话。", False
        try:
            reply = self.llm.complete(
                [
                    {"role": "system", "content": self._response_system_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "user_text": text,
                                "action": action,
                                "tool_results": self._compact_tool_results(tool_results),
                                "status": self._compact_status(
                                    status,
                                    include_tasks=str(action.get("intent", "chat")) == "status",
                                ),
                                "dialogue_memory": memory_context,
                                "dialogue_policy": policy_context,
                                "input_signal": input_signal.to_payload() if input_signal else None,
                                "icbt_formulation": asdict(formulation) if formulation else {},
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0.35,
            )
            return reply, True
        except LLMError as exc:
            return f"LLM 回复生成失败：{exc}", False

    def _intent_system_prompt(self) -> str:
        return (
            "You are the intent router for an academic accountability coach based on ACSP. "
            "Return ONLY JSON with keys intent, payload, confidence, and optional conversation_update. No prose. "
            "Allowed intents: help,status,add_task,plan,checkin,emotion,resources,review,commitment,copresence,schedule_reminder,schedule_break_reminders,clarify,chat. "
            "Intent meanings: "
            "status = user asks about the current task, plan, state, or existing task list; "
            "add_task = user states a concrete academic task or deadline to supervise; "
            "plan = user asks you to arrange/start/schedule an existing academic task; "
            "checkin = user reports progress, completion, delay, stuckness, or evidence; "
            "emotion = user expresses avoidance, shame, anxiety, low motivation, overwhelm, or wants emotional support; "
            "resources = user asks how to do something, wants materials, examples, methods, references, or knowledge help; "
            "schedule_reminder = user wants a timer, reminder, wake-up, countdown, or future nudge; "
            "schedule_break_reminders = user agrees to periodic break reminders for a study/work plan; "
            "chat = greeting or casual acknowledgement that does not need a tool; "
            "clarify = only when no safe intent can be inferred even with recent_dialogue and status. "
            "Prefer checkin for progress reports; emotion for distress/avoidance; add_task only for explicit academic study goals. "
            "If input_signal.kind is emoji and input_signal.expression_only is true, treat it as an affective cue rather than text. "
            "Use emotion when tags suggest sadness, fatigue, overwhelm, anxiety, frustration, or embarrassment; use chat when it is only positive or ambiguous. "
            "Never create tasks, plans, check-ins, reminders, or resources solely from an emoji/sticker signal. "
            "For add_task, plan, and emotion payloads, include semantic readiness and timing when inferable: "
            "{readiness: ready|ambivalent|low|opt_out|unknown, planning_permission: true|false|null, start_timing: now|later|unknown}. "
            "Naming a task does not by itself mean the user wants to start now; set planning_permission true only when the user asks to plan/start or clearly agrees. "
            "For greetings, use chat. Route current-task/state questions to status rather than generic clarification. "
            "Resolve elliptical replies using recent_dialogue and status before clarifying. "
            "Use conversation_update only for durable context the coach should preserve across turns: "
            "{temporal_anchor, current_topic, pending_intention, user_constraint, user_preference, next_follow_up}. "
            "Do not fabricate context; preserve a prior context unless the user changes it. "
            "Payload examples: add_task {title, priority, estimated_minutes, tags}; estimated_minutes must be a number. "
            "checkin {status: completed|partial|skipped|delayed, progress_percent, note, evidence_text}; "
            "schedule_reminder {message, delay_seconds} for relative reminders, or {message, due_at} with ISO-8601 timezone for absolute reminders. "
            "schedule_break_reminders {interval_minutes, duration_minutes?, start_at?, message?}; use 45 minutes when the user wants reminders but gives no interval. "
            "Use schedule_reminder for semantic timer/reminder requests, including non-academic reminders. "
            "Do NOT create an academic task for a non-academic timer request. "
            "clarify {question}."
        )

    def _response_system_prompt(self) -> str:
        return (
            "You are a Chinese academic accountability coach following the ACSP paper. "
            "Use CentralCoordinator tool results as facts. Speak like a skilled human supervisor: warm, specific, "
            "not fluffy. Use natural conversational Chinese, with varied sentence shapes and almost no coaching jargon. "
            "Your Chinese should read like a real chat message, not a product notification or therapy worksheet. "
            "Use everyday wording such as '好，记下了', '行，那今晚先这样', '30 秒后叫你刷牙', when it fits the facts. "
            "Avoid customer-service or system wording such as '已为你', '当前', '该任务', '本次', '执行', '进行', '推进', "
            "'策略', '模式', '路径', '我将为你', '根据你的状态'. "
            "Do not explain your response structure, do not summarize the user's sentence as '你这句话...' unless it is truly needed. "
            "Do not use the same validate-explain-question pattern every turn; sometimes a short direct answer is better. "
            "Be concise. Prefer 1-3 short Chinese sentences. If there are two separate points, separate them with one blank line. "
            "Do not over-explain psychology. Do not repeat ideas about pressure, failure, burden, or being judged. Mention pressure at most once, and only if the user raised it. "
            "Avoid words like '信号', '负荷信号', and mechanical reassurance formulas unless the user used those terms first. "
            "Use abstract words like '状态', '节奏', '安排' sparingly; prefer concrete things: sleep, meal, first paragraph, reminder time, next check-in. "
            "Do not mention 打卡 unless the action is a check-in, reminder, or the user explicitly asks about check-ins. "
            "Incorporate ICBT moves when distress or avoidance appears: empathic reflection, validation, "
            "shared responsibility when plans fail repeatedly, cognitive reframing, graded behavioral activation, "
            "and, only when dialogue_policy.task_push_allowed is true, one small next action. Use these moves lightly, not as a worksheet. Do not claim to be a therapist. If risk is present, prioritize professional support. "
            "Do not sound like a fixed script. Avoid repeated stock phrases, diagnostic-sounding labels, and automatic 'first do 10 minutes' endings. "
            "Never say '上下文', '按某某节奏', '按某某方向', '监督策略', or any explanation of what internal plan you are following. "
            "Do not describe the conversation as a state machine or policy; just answer in ordinary human wording. "
            "Avoid system-feedback phrasing such as 'I received your state', 'I caught/held this context', or Chinese variants like "
            "'你这个状态我接住了', '这个上下文我接住了', '我接住你的情绪'. Say it as a person would, without announcing state capture. "
            "Never invent task names, timers, materials, or user intentions that are not present in user_text, tool_results, status, "
            "or an explicit ICBT formulation. Prompt examples are not user facts. "
            "Treat dialogue_memory and dialogue_policy as private guidance, not user-facing text. Never expose tool IDs, push IDs, "
            "queue state, metadata, policy names, task_action_mode, response_register, intervention_modes, or supervision strategy. "
            "Do not quote pending_intention or describe the internal coaching rhythm; simply respond naturally in that direction. "
            "Respect dialogue_memory.working_context. If it contains timing, constraints, or pending intentions, keep the next step aligned "
            "with that context unless the user explicitly changes it. "
            "If input_signal.kind is emoji and expression_only is true, do not treat the raw emoji as words. Infer gently from emotion_tags, "
            "avoid certainty, and respond as if the user gave a mood cue. Do not say '我识别到表情文本'. "
            "Use dialogue_policy.runtime privately. If local_hour is 23-5, do not invite a broad study session on a greeting; suggest sleep, shutdown, or only an emergency minimum. "
            "If it is around meal time and the user seems undecided or tired, mention eating/resting briefly before planning. "
            "When the user asks 'why study so late', answer directly using the local time: late-night study is usually low-return unless there is an urgent deadline. "
            "When dialogue_policy includes sleep_or_shutdown, make rest or tomorrow planning the default. "
            "When dialogue_policy includes meal_or_basic_needs_check, a one-clause reminder to eat or rest is enough; do not turn it into a lecture. "
            "Respect dialogue_policy. For emotion-state turns, do not treat the message as a check-in unless the user reports a concrete task outcome. "
            "If dialogue_policy.task_push_allowed is false, do not assign a micro-action, do not tell the user to open materials, "
            "and do not imply immediate progress is required. "
            "If dialogue_policy.task_action_mode is task_record_only, separate recording the task from starting it; confirm the record and leave planning as optional. "
            "If dialogue_policy.task_action_mode is emotional_first, stay with the emotional content before mentioning tasks, and mention tasks only if it reduces pressure. "
            "When dialogue_policy includes emotional_support or load_assessment, first validate and assess the user's state; then consider task load, "
            "decomposition, recovery, or next-day planning. "
            "When dialogue_policy includes autonomy_respect or pressure_downshift, do not ask for the academic task immediately, "
            "do not push task decomposition, and do not reframe refusal as progress. Offer rest, a brief conversation, or optional tomorrow planning. "
            "When dialogue_policy includes late_day_recovery_or_tomorrow_planning, do not default to immediate execution; offer a softer late-day plan "
            "or tomorrow's first block unless the user explicitly wants to work now. "
            "When dialogue_policy includes offer_break_reminder_cadence, ask once whether periodic break reminders would help; suggest 30 or 45 minutes naturally. "
            "If action is schedule_break_reminders, confirm the cadence and avoid adding another question. "
            "If tool_results.scheduled_push.confirmation_text exists, use it as the core reply. For ordinary life reminders like brushing teeth or drinking water, do not add study advice. "
            "Follow dialogue_policy.closing_style and dialogue_policy.max_questions strictly. "
            "If max_questions is 0, end with a concrete statement or next checkpoint, not a question. "
            "Do not append a generic optional question after the useful answer is already complete. "
            "If the user only greets you and there is no scheduled block in status, answer naturally. Ask what academic task they want to work on only when it is not late night or meal/rest time. "
            "If the user asks what the current learning task is and none exists, say plainly that no learning task is recorded yet, "
            "then ask for one concrete academic task. "
            "Ask at most one question, and often ask none. "
            "Do not use Markdown, bold markers, numbered therapy worksheets, or English labels. "
            "Never output bracketed sticker text such as '[表情包：...]'; stickers are disabled in this adapter. "
            "Use '打卡' instead of 'DaKa'. If a reminder was scheduled, confirm it naturally; do not say you cannot push."
        )

    def _parse_action(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start : end + 1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"intent": "chat", "payload": {"text": raw}}
        if not isinstance(data, dict):
            return {"intent": "chat", "payload": {"text": raw}}
        if "payload" not in data or not isinstance(data["payload"], dict):
            data["payload"] = {}
        return data

    def _normalize_action(self, action: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
        intent = str(action.get("intent") or "chat").strip()
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        confidence = self._float_value(action.get("confidence"), 1.0)
        if intent not in ALLOWED_INTENTS:
            return {
                "intent": "clarify",
                "payload": {"question": "我没能可靠理解这句话。你是想新增任务、查看状态、打卡，还是设置提醒？"},
                "confidence": 0.0,
            }
        if confidence < 0.35:
            return {
                "intent": "clarify",
                "payload": {"question": "我有点拿不准你的意思。你想让我执行哪一步？"},
                "confidence": confidence,
            }
        if intent in {"plan", "checkin", "resources", "commitment", "copresence"}:
            has_task = bool(status.get("active_task_count", 0)) or bool(payload.get("task_id"))
            if not has_task:
                return {
                    "intent": "clarify",
                    "payload": {"question": "我还没有记录到可操作的学习任务。你先告诉我一个具体任务，我再继续。"},
                    "confidence": confidence,
                }
        if intent == "schedule_reminder" and not (payload.get("due_at") or payload.get("delay_seconds")):
            return {
                "intent": "clarify",
                "payload": {"question": "我可以提醒你，但还缺少具体时间。你希望多久后，或什么时间提醒？"},
                "confidence": confidence,
            }
        if intent == "schedule_break_reminders" and not payload.get("interval_minutes"):
            payload["interval_minutes"] = 45
        normalized = {"intent": intent, "payload": payload, "confidence": confidence}
        conversation_update = action.get("conversation_update")
        if isinstance(conversation_update, dict):
            normalized["conversation_update"] = {
                str(key): value
                for key, value in conversation_update.items()
                if value not in (None, "", [], {})
            }
        return normalized

    def _task_payload(self, payload: dict[str, Any], text: str) -> dict[str, Any]:
        cleaned = {key: value for key, value in payload.items() if value not in (None, "", [])}
        priority = str(cleaned.get("priority") or "medium")
        raw_tags = cleaned.get("tags") or []
        tags = raw_tags if isinstance(raw_tags, list) else [str(raw_tags)]
        return {
            "title": str(cleaned.get("title") or text),
            "priority": priority,
            "importance": self._int_value(cleaned.get("importance"), 5 if priority in {"urgent", "high"} else 3),
            "estimated_minutes": self._int_value(cleaned.get("estimated_minutes"), 50),
            "tags": tags,
            **{key: value for key, value in cleaned.items() if key not in {"title", "priority", "importance", "estimated_minutes", "tags"}},
        }

    def _checkin_payload(self, user_id: str, payload: dict[str, Any], text: str) -> dict[str, Any]:
        inferred = {key: value for key, value in payload.items() if value not in (None, "", [])}
        inferred["task_id"] = inferred.get("task_id") or self._latest_task_id(user_id)
        inferred["status"] = inferred.get("status") or "partial"
        inferred["progress_percent"] = max(0, min(100, self._int_value(inferred.get("progress_percent"), 0)))
        inferred["note"] = inferred.get("note") or text
        return inferred

    def _reminder_payload(self, payload: dict[str, Any], text: str) -> dict[str, Any]:
        delay_raw = payload.get("delay_seconds")
        delay_seconds = self._optional_int_value(delay_raw)
        request = self.reminders.build_request(
            str(payload.get("message") or text),
            due_at=str(payload.get("due_at")) if payload.get("due_at") else None,
            delay_seconds=delay_seconds,
        )
        return {"message": request.message, "due_at": request.due_at, "delay_seconds": delay_seconds}

    def _int_value(self, value: object, default: int) -> int:
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default

    def _optional_int_value(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError) as exc:
            raise ValueError("提醒时间需要是结构化秒数 delay_seconds，或 ISO 时间 due_at。") from exc

    def _float_value(self, value: object, default: float) -> float:
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, parsed))

    def _latest_task_id(self, user_id: str) -> str:
        state = self.coordinator.store.load(user_id)
        for task in reversed(state.tasks):
            if task.status != "completed":
                return task.task_id
        return state.tasks[-1].task_id if state.tasks else ""

    def _build_icbt_formulation(
        self,
        user_id: str,
        text: str,
        action: dict[str, Any],
        input_signal: InputSignal | None = None,
    ) -> object | None:
        intent = str(action.get("intent", "chat"))
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        if intent in {"checkin", "emotion"} or bool(payload.get("needs_emotional_support")):
            formulation_text = text or (input_signal.description if input_signal else "")
            return self.icbt.formulate(self.coordinator.store.load(user_id), formulation_text)
        return None

    def _compact_status(self, status: dict[str, Any], include_tasks: bool = False) -> dict[str, Any]:
        compacted = {
            "role": status.get("role"),
            "active_task_count": status.get("active_task_count"),
            "planned_block_count": status.get("planned_block_count"),
            "proactive_suggestions": status.get("proactive_suggestions"),
            "emotion": status.get("emotion"),
            "next_blocks": status.get("next_blocks", [])[:2],
            "tracking_insights": status.get("tracking_insights"),
        }
        if include_tasks:
            compacted["active_tasks"] = self._compact_tasks(status.get("active_tasks", []))
        return compacted

    def _compact_tasks(self, tasks: object) -> list[dict[str, Any]]:
        if not isinstance(tasks, list):
            return []
        compacted: list[dict[str, Any]] = []
        for item in tasks[:3]:
            if not isinstance(item, dict):
                continue
            compacted.append(
                {
                    "task_id": item.get("task_id"),
                    "title": item.get("title"),
                    "priority": item.get("priority"),
                    "status": item.get("status"),
                    "remaining_minutes": item.get("remaining_minutes"),
                    "deadline": item.get("deadline"),
                }
            )
        return compacted

    def _dialogue_memory(self, user_id: str) -> dict[str, Any]:
        state = self.coordinator.store.load(user_id)
        return self.memory.context(state)

    def _user_timezone(self, user_id: str) -> str | None:
        state = self.coordinator.store.load(user_id)
        profile_timezone = state.profile.get("timezone")
        if profile_timezone:
            return str(profile_timezone)
        constraint_timezone = state.supervision.constraints.get("timezone")
        if constraint_timezone:
            return str(constraint_timezone)
        default_timezone = os.getenv("ACCOUNTABILITY_COACH_DEFAULT_TIMEZONE", "").strip()
        if default_timezone:
            return default_timezone
        return None

    def _opening_time_text(self, runtime: object) -> str:
        local_datetime = getattr(runtime, "local_datetime", "")
        timezone_name = getattr(runtime, "timezone", "")
        if not local_datetime:
            return ""
        try:
            hour_minute = local_datetime.split("T", 1)[1][:5]
        except IndexError:
            hour_minute = local_datetime
        if timezone_name:
            return f"现在是你本地时间 {hour_minute}（{timezone_name}）。"
        return f"现在是本地时间 {hour_minute}。"

    def _append_dialogue_event(
        self,
        user_id: str,
        speaker: str,
        text: str,
        intent: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        state = self.coordinator.store.load(user_id)
        self.memory.record_event(
            state,
            speaker=speaker,
            text=text,
            intent=intent,
            metadata=metadata,
        )
        self.coordinator.store.save(state)

    def _compact_tool_results(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        public_results = self._public_tool_results(tool_results)
        text = json.dumps(public_results, ensure_ascii=False)
        if len(text) > 5000:
            return {"summary": text[:5000] + "..."}
        return public_results

    def _public_tool_results(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        if "scheduled_push" in tool_results and isinstance(tool_results["scheduled_push"], dict):
            return {"scheduled_push": self._public_push(tool_results["scheduled_push"])}
        if "break_reminders" in tool_results and isinstance(tool_results["break_reminders"], dict):
            pushes = tool_results["break_reminders"].get("pushes", [])
            public_pushes = [self._public_push(push) for push in pushes if isinstance(push, dict)]
            return {
                "break_reminders": {
                    "scheduled": bool(public_pushes),
                    "count": len(public_pushes),
                    "first_due_at": public_pushes[0].get("due_at") if public_pushes else None,
                    "interval_minutes": self._first_push_metadata_value(pushes, "interval_minutes"),
                }
            }
        return tool_results

    def _public_push(self, push: dict[str, Any]) -> dict[str, Any]:
        public_push = {
            "scheduled": True,
            "message": push.get("message"),
            "due_at": push.get("due_at"),
        }
        metadata = push.get("metadata") if isinstance(push.get("metadata"), dict) else {}
        delay_seconds = self._optional_delay_from_metadata(metadata)
        if delay_seconds is not None:
            public_push["confirmation_text"] = self._reminder_confirmation_text(
                str(push.get("message") or ""),
                delay_seconds,
            )
        return public_push

    def _optional_delay_from_metadata(self, metadata: dict[str, Any]) -> int | None:
        value = metadata.get("delay_seconds")
        if value in (None, ""):
            return None
        try:
            return max(0, int(float(str(value).strip())))
        except (TypeError, ValueError):
            return None

    def _reminder_confirmation_text(self, message: str, delay_seconds: int) -> str:
        cleaned = message.strip(" 。，.!！")
        if not cleaned:
            cleaned = "这件事"
        return f"好，{self._relative_delay_text(delay_seconds)}叫你{cleaned}。"

    def _relative_delay_text(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} 秒后"
        if seconds < 3600:
            minutes = max(1, round(seconds / 60))
            return f"{minutes} 分钟后"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours} 小时 {minutes} 分钟后"
        return f"{hours} 小时后"

    def _first_push_metadata_value(self, pushes: object, key: str) -> object | None:
        if not isinstance(pushes, list):
            return None
        for push in pushes:
            if not isinstance(push, dict):
                continue
            metadata = push.get("metadata") if isinstance(push.get("metadata"), dict) else {}
            value = metadata.get(key)
            if value not in (None, ""):
                return value
        return None

    def _select_sticker(
        self,
        user_id: str,
        *,
        intent: str,
        policy_context: dict[str, Any],
        risk_level: str,
        tool_results: dict[str, Any],
    ) -> dict[str, Any] | None:
        state = self.coordinator.store.load(user_id)
        sticker = self.stickers.choose(
            state,
            intent=intent,
            policy_context=policy_context,
            risk_level=risk_level,
            tool_results=tool_results,
        )
        self.coordinator.store.save(state)
        return sticker

    def _limit_time_context_repetition(
        self,
        user_id: str,
        policy_context: DialoguePolicyContext,
    ) -> None:
        """Keep meal/night nudges useful by not repeating them every turn."""
        mode_to_kind = {
            "meal_or_basic_needs_check": "meal",
            "sleep_or_shutdown": "night",
            "late_day_recovery_or_tomorrow_planning": "night",
        }
        active_kinds = {
            kind
            for mode, kind in mode_to_kind.items()
            if mode in policy_context.intervention_modes
        }
        if not active_kinds:
            return

        state = self.coordinator.store.load(user_id)
        local_date = policy_context.runtime.local_datetime[:10] or "unknown"
        raw_counts = state.tracking_state.get("time_context_counts")
        counts = raw_counts if isinstance(raw_counts, dict) else {}
        if counts.get("date") != local_date:
            counts = {"date": local_date, "meal": 0, "night": 0}

        blocked_kinds: set[str] = set()
        for kind in sorted(active_kinds):
            current = int(counts.get(kind, 0) or 0)
            if current >= 2:
                blocked_kinds.add(kind)
            else:
                counts[kind] = current + 1
        state.tracking_state["time_context_counts"] = counts
        self.coordinator.store.save(state)
        if not blocked_kinds:
            return

        blocked_modes = {
            mode
            for mode, kind in mode_to_kind.items()
            if kind in blocked_kinds
        }
        policy_context.intervention_modes = [
            mode for mode in policy_context.intervention_modes if mode not in blocked_modes
        ]
        if "meal" in blocked_kinds:
            policy_context.planning_options = [
                item
                for item in policy_context.planning_options
                if "eating" not in item and "meal" not in item and "basic-needs" not in item
            ]
            policy_context.rationale = [
                item for item in policy_context.rationale if "meal" not in item.lower()
            ]
        if "night" in blocked_kinds:
            policy_context.planning_options = [
                item
                for item in policy_context.planning_options
                if "sleep" not in item
                and "shutdown" not in item
                and "recovery" not in item
                and "tomorrow" not in item
            ]
            policy_context.rationale = [
                item
                for item in policy_context.rationale
                if "sleep" not in item.lower() and "late" not in item.lower()
            ]
        if (
            policy_context.closing_style == "recovery_or_next_checkpoint"
            and not any(mode in policy_context.intervention_modes for mode in mode_to_kind)
        ):
            policy_context.closing_style = "contextual_next_step"
            policy_context.max_questions = min(policy_context.max_questions or 1, 1)

    def _render_status(self, status: dict[str, Any]) -> str:
        next_blocks = status.get("next_blocks") or []
        if not next_blocks:
            return "现在还没有安排中的学习块。你可以说一件想处理的学业任务，也可以先说现在的状态。"
        first = next_blocks[0]
        return f"当前下一块是「{first.get('title')}」，{first.get('focus_minutes')} 分钟。你可以先做这一块，结束后回来打卡。"

    def _render_risk(self, risk: dict[str, Any]) -> str:
        assessment = risk["risk_assessment"]
        actions = "\n".join(f"- {item}" for item in assessment.get("recommended_actions", []))
        return (
            f"我先暂停普通学习监督，因为这里出现了需要优先处理的风险：{assessment.get('level')}。\n"
            "请把安全放在第一位，联系身边可信的人或当地专业支持。\n"
            f"{actions}"
        )

    def _help_text(self) -> str:
        return (
            "你可以直接自然语言说：\n"
            "我今晚要写论文提纲\n"
            "排一下\n"
            "我只做了 40%，卡在资料整理\n"
            "我不想写了\n"
            "30秒后提醒我交作业\n"
            "也可以说：状态、周报、重置、退出。"
        )

    def _polish_reply(self, reply: str) -> str:
        polished = reply.replace("DaKa", "打卡").replace("daka", "打卡")
        polished = polished.replace("**", "")
        return self.language_guard.polish(polished)
