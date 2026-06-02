import asyncio
import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from accountability_coach import CentralCoordinator
from accountability_coach.core.json_store import JsonUserStateStore
from accountability_coach.core.models import (
    CHECKIN_SKIPPED,
    COMMITMENT_FULFILLED,
    EVIDENCE_SUSPICIOUS,
    INTENSITY_STRICT,
    ROLE_COACH,
    ROLE_EXPERT,
    ROLE_MENTOR,
    ROLE_PARTNER,
    RISK_CRITICAL,
    STYLE_SERIOUS,
    Task,
    UserState,
    iso_from_datetime,
    parse_datetime,
)
from accountability_coach.dialogue import AccessControl, DialogueAgent, DialoguePolicy, StickerLibrary
from accountability_coach.dialogue.language_guard import PublicLanguageGuard
from accountability_coach.entrypoints.chat_cli import ChatHarness
from accountability_coach.wechat.official_account import (
    WeChatOfficialAccountHandler,
    verify_wechat_signature,
)
from accountability_coach.wechat.openclaw_adapter import OpenClawWeChatAdapter
from accountability_coach.wechat.openclaw_client import OpenClawConfig
from accountability_coach.wechat.openclaw_multi import HostedOpenClawAccount
from accountability_coach.modules.role_arbiter import RoleArbiter
from accountability_coach.modules.schedule_planning import SchedulePlanningAgent


class FakeLLM:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
        self.calls.append(messages)
        if not self.outputs:
            raise AssertionError("FakeLLM has no queued output")
        return self.outputs.pop(0)

    def is_available(self) -> bool:
        return True


class FakeOpenClawClient:
    def __init__(self, updates: list[dict]) -> None:
        self.config = OpenClawConfig()
        self.token = "token"
        self.updates = updates
        self.sent: list[dict[str, str]] = []

    def get_updates(self, sync_buf: str) -> dict:
        if not self.updates:
            return {"ret": 0, "errcode": 0, "get_updates_buf": sync_buf, "msgs": []}
        return self.updates.pop(0)

    def send_text(self, user_id: str, context_token: str, text: str) -> dict:
        self.sent.append(
            {
                "user_id": user_id,
                "context_token": context_token,
                "text": text,
            }
        )
        return {"ret": 0, "errcode": 0}

    def is_success(self, payload: dict) -> bool:
        return int(payload.get("ret") or 0) == 0 and int(payload.get("errcode") or 0) == 0

    def error_text(self, payload: dict) -> str:
        return str(payload)


class ACSPCoreTests(unittest.TestCase):
    def test_json_store_round_trips_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonUserStateStore(Path(tmp))
            state = UserState(user_id="u1")
            state.supervision.goals = ["finish thesis"]
            state.tasks.append(Task(task_id="task_1", title="Read paper"))

            store.save(state)
            loaded = store.load("u1")

            self.assertEqual(loaded.user_id, "u1")
            self.assertEqual(loaded.supervision.goals, ["finish thesis"])
            self.assertEqual(loaded.tasks[0].title, "Read paper")
            self.assertEqual(store.list_users(), ["u1"])

    def test_schedule_prioritizes_urgent_important_and_uses_pomodoro(self) -> None:
        now = datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc)
        state = UserState(user_id="u1")
        state.tasks = [
            Task(
                task_id="low",
                title="Optional reading",
                priority="low",
                importance=2,
                estimated_minutes=50,
                deadline=iso_from_datetime(now + timedelta(days=10)),
            ),
            Task(
                task_id="urgent",
                title="Submit thesis outline",
                priority="urgent",
                importance=5,
                estimated_minutes=60,
                deadline=iso_from_datetime(now + timedelta(hours=20)),
            ),
        ]

        blocks = SchedulePlanningAgent().build_initial_schedule(state, now)

        self.assertGreaterEqual(len(blocks), 1)
        self.assertEqual(blocks[0].task_id, "urgent")
        self.assertEqual(blocks[0].focus_minutes, 25)
        self.assertEqual(blocks[0].break_minutes, 5)
        self.assertEqual(blocks[0].quadrant, "urgent_important")

    def test_low_morale_schedule_downgrades_load(self) -> None:
        now = datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc)
        state = UserState(user_id="u1")
        state.emotion.morale = 0.2
        state.emotion.energy = 0.3
        state.tasks = [
            Task(
                task_id="hard",
                title="Write difficult chapter",
                priority="high",
                importance=5,
                estimated_minutes=180,
            )
        ]

        blocks = SchedulePlanningAgent().build_initial_schedule(state, now)

        self.assertLessEqual(len(blocks), 3)
        self.assertEqual(blocks[0].focus_minutes, 15)
        self.assertEqual(blocks[0].break_minutes, 10)
        self.assertTrue(blocks[0].is_essential)

    def test_coordinator_checkin_closes_tracking_emotion_guidance_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.configure_supervision(
                "u1",
                {
                    "style": STYLE_SERIOUS,
                    "intensity": INTENSITY_STRICT,
                    "goals": ["pass the exam"],
                },
            )
            state = coach.add_or_update_task(
                "u1",
                {
                    "task_id": "task_exam",
                    "title": "Finish calculus problem set",
                    "priority": "urgent",
                    "importance": 5,
                    "estimated_minutes": 90,
                },
            )
            self.assertEqual(len(state.tasks), 1)
            planned = coach.plan_schedule("u1")
            self.assertGreater(len(planned.schedule), 0)

            result = coach.record_checkin(
                "u1",
                {
                    "task_id": "task_exam",
                    "block_id": planned.schedule[0].block_id,
                    "status": CHECKIN_SKIPPED,
                    "progress_percent": 0,
                    "note": "I am anxious and overwhelmed. I feel like a failure.",
                    "emotion_tags": ["anxious", "overwhelmed"],
                },
            )

            self.assertTrue(result["replan_triggered"])
            self.assertLess(
                result["emotional_adjustment"]["schedule_intensity_multiplier"],
                1.0,
            )
            self.assertGreater(len(result["guidance_plan"]["commitments"]), 0)
            self.assertIn(
                "empathic_listening",
                result["emotional_adjustment"]["support_flags"],
            )

    def test_onboarding_uses_contract_alignment_and_transparency_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))

            first = coach.start_onboarding("u1")
            self.assertEqual(
                first["onboarding_script"]["stage"],
                "contractual_parameters",
            )
            self.assertTrue(first["onboarding_script"]["service_boundaries"])

            coach.configure_supervision(
                "u1",
                {"goals": ["finish dissertation"], "intensity": "moderate"},
            )
            second = coach.start_onboarding("u1")
            self.assertEqual(
                second["onboarding_script"]["stage"],
                "multidimensional_alignment",
            )
            self.assertTrue(
                any(
                    "procrastination history" in question.lower()
                    for question in second["onboarding_script"]["questions"]
                )
            )

            third = coach.record_onboarding_response(
                "u1",
                {
                    "procrastination_history": "I freeze before writing tasks.",
                    "past_attempts": ["timer apps", "study rooms"],
                    "hard_start_task_types": ["writing"],
                },
            )
            self.assertEqual(
                third["onboarding_script"]["stage"],
                "bidirectional_transparency",
            )
            self.assertTrue(third["onboarding_script"]["self_disclosure"])

    def test_role_arbiter_selects_all_regulatory_roles(self) -> None:
        arbiter = RoleArbiter()

        mentor_state = UserState(user_id="mentor")
        self.assertEqual(arbiter.decide(mentor_state).role, ROLE_MENTOR)

        expert_state = UserState(user_id="expert")
        expert_state.supervision.goals = ["pass exam"]
        expert_state.tasks.append(Task(task_id="t", title="Essay"))
        self.assertEqual(
            arbiter.decide(
                expert_state,
                latest_text="I don't know how to find resources for this concept.",
            ).role,
            ROLE_EXPERT,
        )

        coach_state = UserState(user_id="coach")
        coach_state.supervision.goals = ["finish assignment"]
        coach_state.tasks.append(Task(task_id="t", title="Assignment"))
        coach_state.tracking_state["recent_skip_streak"] = 2
        self.assertEqual(arbiter.decide(coach_state).role, ROLE_COACH)

        partner_state = UserState(user_id="partner")
        partner_state.supervision.goals = ["finish assignment"]
        partner_state.tasks.append(Task(task_id="t", title="Assignment"))
        partner_state.emotion.distress_detected = True
        partner_state.emotion.morale = 0.2
        self.assertEqual(arbiter.decide(partner_state).role, ROLE_PARTNER)

    def test_critical_risk_pauses_regular_intervention_and_escalates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.configure_supervision("u1", {"goals": ["pass exam"]})
            planned = coach.add_or_update_task(
                "u1",
                {
                    "task_id": "task_exam",
                    "title": "Study",
                    "priority": "high",
                    "estimated_minutes": 30,
                },
            )
            self.assertEqual(len(planned.tasks), 1)
            coach.plan_schedule("u1")

            result = coach.record_checkin(
                "u1",
                {
                    "task_id": "task_exam",
                    "status": CHECKIN_SKIPPED,
                    "progress_percent": 0,
                    "note": "I don't want to live and I might hurt myself.",
                    "emotion_tags": ["sad"],
                },
            )

            self.assertEqual(result["risk_assessment"]["level"], RISK_CRITICAL)
            self.assertTrue(result["state"]["intervention_paused"])
            self.assertFalse(result["replan_triggered"])
            self.assertIn(
                "risk_escalation",
                result["guidance_plan"]["emotional_support_flags"],
            )

    def test_daka_evidence_marks_inconsistent_activity_as_ritual_suspicious(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.configure_supervision("u1", {"goals": ["finish thesis"]})
            coach.add_or_update_task(
                "u1",
                {
                    "task_id": "paper",
                    "title": "Write thesis literature review",
                    "priority": "high",
                    "tags": ["writing", "thesis"],
                    "estimated_minutes": 50,
                },
            )

            result = coach.record_checkin(
                "u1",
                {
                    "task_id": "paper",
                    "status": "completed",
                    "progress_percent": 100,
                    "note": "I finished the writing block.",
                    "metadata": {
                        "ocr_text": "Weibo trending topics and entertainment feed",
                        "activity_app": "Weibo",
                    },
                },
            )

            self.assertEqual(
                result["evidence_assessment"]["consistency_level"],
                EVIDENCE_SUSPICIOUS,
            )
            self.assertIn(
                "daka_consistency_dialogue",
                result["guidance_plan"]["emotional_support_flags"],
            )

    def test_copresence_records_redirect_ping_for_authorized_distraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.configure_supervision("u1", {"goals": ["finish homework"]})
            coach.add_or_update_task(
                "u1",
                {"task_id": "hw", "title": "Math homework", "estimated_minutes": 25},
            )
            started = coach.start_copresence_session(
                "u1",
                "hw",
                {"authorized_screen_activity": True, "duration_minutes": 25},
            )
            session_id = started["copresence_session"]["session_id"]

            updated = coach.record_screen_activity(
                "u1",
                session_id,
                "Steam",
                "Game Library",
            )

            pings = updated["copresence_session"]["pings"]
            self.assertTrue(any("possible_distraction" in ping["flags"] for ping in pings))

    def test_emotional_dialogue_playbook_outputs_reframing_and_shared_responsibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.configure_supervision("u1", {"goals": ["write paper"]})
            coach.add_or_update_task(
                "u1",
                {"task_id": "paper", "title": "Write paper", "estimated_minutes": 30},
            )
            for _ in range(2):
                coach.record_checkin(
                    "u1",
                    {
                        "task_id": "paper",
                        "status": CHECKIN_SKIPPED,
                        "progress_percent": 0,
                        "note": "I never finish anything. Everything is ruined.",
                        "emotion_tags": ["sad"],
                    },
                )

            result = coach.get_emotional_dialogue(
                "u1",
                "I never finish anything. Everything is ruined.",
            )

            dialogue = result["emotional_dialogue"]
            self.assertIn("cognitive_reframing", dialogue["strategy_tags"])
            self.assertIn("companionate_shared_responsibility", dialogue["strategy_tags"])
            self.assertIn("all_or_nothing", dialogue["distortion_labels"])

    def test_resources_review_and_executable_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.configure_supervision(
                "u1",
                {"goals": ["finish essay"], "major": "writing"},
            )
            coach.add_or_update_task(
                "u1",
                {
                    "task_id": "essay",
                    "title": "Write essay draft",
                    "estimated_minutes": 30,
                    "tags": ["writing"],
                },
            )
            resources = coach.suggest_resources("u1", "essay", "citation writing")
            self.assertTrue(any("Purdue" in item["title"] for item in resources["resources"]))

            commitment = coach.create_commitment(
                "u1",
                "essay",
                "I will write for 25 minutes and submit DaKa.",
            )
            self.assertEqual(commitment["commitment"]["status"], "active")

            result = coach.record_checkin(
                "u1",
                {
                    "task_id": "essay",
                    "status": "completed",
                    "progress_percent": 100,
                    "note": "Drafted the intro.",
                    "metadata": {"ocr_text": "Essay draft introduction paragraph"},
                },
            )
            self.assertTrue(
                any(
                    item["status"] == COMMITMENT_FULFILLED
                    for item in result["changed_commitments"]
                )
            )

            review = coach.generate_progress_review("u1", "weekly")
            self.assertGreaterEqual(review["progress_review"]["total_checkins"], 1)
            self.assertIn("check-ins", review["progress_review"]["narrative"])

    def test_chat_harness_requires_llm_and_delegates_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            offline_chat = ChatHarness(coach, "offline_user")

            self.assertIn("到点提醒", offline_chat.opening())
            self.assertNotIn("不填表", offline_chat.opening())
            self.assertIn("需要先配置 LLM", offline_chat.respond("我要煮鸡蛋，半分钟后叫我"))

        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"help","payload":{}}',
                    "你可以直接说任务、进度、情绪，或者让我在某个时间提醒你。",
                    '{"intent":"schedule_reminder","payload":{"message":"煮鸡蛋","delay_seconds":30}}',
                    "可以，30 秒后我会提醒你煮鸡蛋。这个不会被记成学习任务。",
                ]
            )
            chat = ChatHarness(coach, "chat_user", llm=llm)

            self.assertIn("到点提醒", chat.opening())
            self.assertIn("直接说任务", chat.respond("?"))
            timer_reply = chat.respond("我要煮鸡蛋，半分钟后叫我")
            state = coach.store.load("chat_user")

            self.assertIn("30 秒后", timer_reply)
            self.assertEqual(state.tasks, [])
            self.assertEqual(state.tracking_state["scheduled_pushes"][0]["message"], "煮鸡蛋")

    def test_dialogue_invite_gate_and_user_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            access = AccessControl(invite_codes={"friend-code"}, require_invite=True)
            llm = FakeLLM(
                [
                    '{"intent":"chat","payload":{},"confidence":0.9}',
                    "你好，之后我按你的时区来陪你安排。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm, access_control=access)

            blocked = dialogue.respond("friend", "你好")
            invalid = dialogue.respond("friend", "邀请码 wrong")
            accepted = dialogue.respond("friend", "邀请码 friend-code")
            nickname = dialogue.respond("friend", "设置昵称 小周")
            timezone_reply = dialogue.respond("friend", "设置时区 Asia/Shanghai")
            state = coach.store.load("friend")
            turn = dialogue.respond("friend", "我想聊聊")
            router_payload = json.loads(llm.calls[0][1]["content"])

            self.assertEqual(blocked.intent, "access_required")
            self.assertIn("邀请制", blocked.reply)
            self.assertEqual(invalid.intent, "access_required")
            self.assertIn("不对", invalid.reply)
            self.assertEqual(accepted.intent, "access_authorized")
            self.assertTrue(coach.store.load("friend").profile["access"]["authorized"])
            self.assertEqual(nickname.intent, "profile_update")
            self.assertEqual(timezone_reply.intent, "profile_update")
            self.assertEqual(state.profile["display_name"], "小周")
            self.assertEqual(state.profile["timezone"], "Asia/Shanghai")
            self.assertEqual(router_payload["runtime_context"]["timezone"], "Asia/Shanghai")
            self.assertEqual(turn.intent, "chat")

    def test_first_use_opening_is_shown_once_and_reset_preserves_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            access = AccessControl(invite_codes={"code"}, require_invite=True)
            dialogue = DialogueAgent(coach, llm=FakeLLM([]), access_control=access)

            dialogue.respond("friend", "邀请码 code")
            opening = dialogue.respond("friend", "你好")
            repeated = dialogue.opening("friend")
            reset = dialogue.respond("friend", "重置")
            state = coach.store.load("friend")

            self.assertEqual(opening.intent, "opening")
            self.assertIn("设置昵称", opening.reply)
            self.assertNotIn("设置昵称", repeated)
            self.assertNotIn("邀请制", reset.reply)
            self.assertTrue(state.profile["access"]["authorized"])

    def test_dialogue_agent_uses_llm_for_intent_and_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    (
                        '{"intent":"add_task","payload":{"title":"整理第二章","priority":"high",'
                        '"estimated_minutes":45,"tags":["thesis"],"readiness":"ambivalent",'
                        '"planning_permission":false,"start_timing":"later"}}'
                    ),
                    "好，我先把第二章记录下来。今晚你要安排它的时候，直接说排一下或开始就行。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "今晚把第二章整理出来")
            state = coach.store.load("u1")
            response_payload = json.loads(llm.calls[1][1]["content"])

            self.assertTrue(turn.used_llm)
            self.assertEqual(turn.intent, "add_task")
            self.assertIn("第二章", state.tasks[0].title)
            self.assertFalse(response_payload["dialogue_policy"]["task_push_allowed"])
            self.assertEqual(response_payload["dialogue_policy"]["task_action_mode"], "task_record_only")
            self.assertEqual(response_payload["dialogue_policy"]["closing_style"], "record_and_wait")
            self.assertEqual(response_payload["dialogue_policy"]["max_questions"], 0)
            self.assertIn("assuming_task_mention_means_start_now", response_payload["dialogue_policy"]["avoid_moves"])
            self.assertNotIn("25 分钟", turn.reply)
            self.assertNotIn("打卡", turn.reply)
            self.assertNotIn("DaKa", turn.reply)
            self.assertNotIn("**", turn.reply)
            self.assertEqual(len(llm.calls), 2)

    def test_dialogue_schedules_and_pops_due_pushes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"交作业","delay_seconds":30}}',
                    (
                        "可以，30 秒后我会提醒你交作业。\n"
                        "提醒任务已进入排程（push_7_1779534684）。\n"
                        "监督策略：继续按当前节奏推进。"
                    ),
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "30秒之后提醒我 交作业")
            state = coach.store.load("u1")
            pushes = state.tracking_state["scheduled_pushes"]
            response_payload = json.loads(llm.calls[1][1]["content"])
            public_push = response_payload["tool_results"]["scheduled_push"]

            self.assertEqual(turn.intent, "schedule_reminder")
            self.assertTrue(turn.used_llm)
            self.assertEqual(pushes[0]["message"], "交作业")
            self.assertNotIn("push_id", public_push)
            self.assertNotIn("status", public_push)
            self.assertNotIn("metadata", public_push)
            self.assertEqual(public_push["confirmation_text"], "好，30 秒后叫你交作业。")
            self.assertNotIn("push_", turn.reply)
            self.assertNotIn("进入排程", turn.reply)
            self.assertNotIn("监督策略", turn.reply)
            self.assertNotIn("我会提醒你", turn.reply)
            self.assertEqual(coach.pop_due_pushes("u1"), [])

            pushes[0]["due_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).replace(microsecond=0).isoformat()
            state.tracking_state["scheduled_pushes"] = pushes
            coach.store.save(state)

            due = coach.pop_due_pushes("u1")
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["message"], "交作业")
            self.assertEqual(coach.store.load("u1").tracking_state["scheduled_pushes"][0]["status"], "delivered")

    def test_planned_push_creates_silence_followup_and_cancels_after_user_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            first_due = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
            coach.schedule_push(
                "u1",
                "这一段轮到「写论文」。先看一下状态：能开始就开始；不合适就回我一句，我帮你改节奏。",
                iso_from_datetime(first_due),
                metadata={
                    "reason": "planned_block_start",
                    "proactive": True,
                    "follow_up_enabled": True,
                    "title": "写论文",
                    "block_id": "block_1",
                    "task_id": "task_1",
                },
            )

            due = coach.pop_due_pushes("u1", first_due)
            state = coach.store.load("u1")
            pushes = state.tracking_state["scheduled_pushes"]
            followups = [item for item in pushes if item["metadata"].get("reason") == "silence_followup"]

            self.assertEqual(len(due), 1)
            self.assertEqual(len(followups), 1)
            self.assertIn("没收到", followups[0]["message"])
            self.assertEqual(followups[0]["metadata"]["follow_up_stage"], 1)

            parent_delivered_at = parse_datetime(pushes[0]["delivered_at"])
            self.assertIsNotNone(parent_delivered_at)
            assert parent_delivered_at is not None
            state.tracking_state["dialogue_memory"] = {
                "archive": [
                    {
                        "speaker": "user",
                        "created_at": iso_from_datetime(parent_delivered_at + timedelta(minutes=2)),
                        "text": "我开始了",
                        "intent": "checkin",
                    }
                ]
            }
            coach.store.save(state)

            followup_due = parse_datetime(followups[0]["due_at"])
            self.assertIsNotNone(followup_due)
            assert followup_due is not None
            self.assertEqual(coach.pop_due_pushes("u1", followup_due), [])
            cancelled = coach.store.load("u1").tracking_state["scheduled_pushes"][1]
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(cancelled["cancel_reason"], "user_replied_after_parent_push")

    def test_silence_followup_deescalates_and_stops_after_second_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            first_due = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
            coach.schedule_push(
                "u1",
                "这段「写论文」先收一下。回我完成、部分完成、卡住，或者要改计划。",
                iso_from_datetime(first_due),
                metadata={
                    "reason": "planned_block_checkin",
                    "proactive": True,
                    "follow_up_enabled": True,
                    "title": "写论文",
                    "block_id": "block_1",
                    "task_id": "task_1",
                },
            )

            coach.pop_due_pushes("u1", first_due)
            first_followup = coach.store.load("u1").tracking_state["scheduled_pushes"][1]
            first_followup_due = parse_datetime(first_followup["due_at"])
            self.assertIsNotNone(first_followup_due)
            assert first_followup_due is not None

            due = coach.pop_due_pushes("u1", first_followup_due)
            state = coach.store.load("u1")
            pushes = state.tracking_state["scheduled_pushes"]
            second_followups = [
                item
                for item in pushes
                if item["metadata"].get("reason") == "silence_followup"
                and item["metadata"].get("follow_up_stage") == 2
            ]

            self.assertEqual(len(due), 1)
            self.assertIn("一个词", due[0]["message"])
            self.assertEqual(len(second_followups), 1)
            second_due = parse_datetime(second_followups[0]["due_at"])
            self.assertIsNotNone(second_due)
            assert second_due is not None

            due = coach.pop_due_pushes("u1", second_due)
            self.assertEqual(len(due), 1)
            self.assertIn("不继续催", due[0]["message"])
            self.assertEqual(
                len(
                    [
                        item
                        for item in coach.store.load("u1").tracking_state["scheduled_pushes"]
                        if item["metadata"].get("reason") == "silence_followup"
                    ]
                ),
                2,
            )

    def test_timer_request_is_not_planned_as_study_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"煮鸡蛋","delay_seconds":30}}',
                    "可以，30 秒后我提醒你煮鸡蛋；这不是学习任务。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "我要煮鸡蛋，定时30秒")
            state = coach.store.load("u1")
            pushes = state.tracking_state["scheduled_pushes"]

            self.assertEqual(turn.intent, "schedule_reminder")
            self.assertEqual(pushes[0]["message"], "煮鸡蛋")
            self.assertEqual(state.tasks, [])
            self.assertNotIn("25 分钟", turn.reply)
            self.assertNotIn("番茄钟", turn.reply)

    def test_llm_semantic_timer_routes_to_reminder_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"煮鸡蛋","delay_seconds":30}}',
                    "可以，半分钟后我提醒你煮鸡蛋。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "我要煮鸡蛋，半分钟后叫我")
            state = coach.store.load("u1")

            self.assertEqual(turn.intent, "schedule_reminder")
            self.assertEqual(state.tracking_state["scheduled_pushes"][0]["message"], "煮鸡蛋")
            self.assertEqual(state.tasks, [])
            self.assertEqual(len(llm.calls), 2)

    def test_dialogue_prompt_does_not_seed_example_tasks_or_reuse_stale_task_on_greeting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            state = coach.store.load("u1")
            state.tasks.append(Task(task_id="stale", title="煮鸡蛋，定时30秒"))
            coach.store.save(state)
            llm = FakeLLM(
                [
                    '{"intent":"chat","payload":{}}',
                    "哈喽，我在。你今天想推进哪件学业任务？",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "哈喽")
            response_prompt_payload = llm.calls[1][1]["content"]

            self.assertEqual(turn.intent, "chat")
            self.assertNotIn("cooking", dialogue._intent_system_prompt())
            self.assertNotIn("egg", dialogue._intent_system_prompt())
            self.assertNotIn("煮鸡蛋", response_prompt_payload)
            self.assertEqual(turn.metadata["icbt"], {})

    def test_dialogue_memory_keeps_long_archive_but_sends_bounded_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            outputs: list[str] = []
            for index in range(25):
                outputs.extend(
                    [
                        '{"intent":"chat","payload":{},"confidence":0.86}',
                        f"第 {index} 轮收到，我们继续保持节奏。",
                    ]
                )
            llm = FakeLLM(outputs)
            dialogue = DialogueAgent(coach, llm=llm)
            dialogue.opening("u1")

            for index in range(25):
                dialogue.respond("u1", f"第 {index} 轮随便聊一句")

            state = coach.store.load("u1")
            memory = state.tracking_state["dialogue_memory"]
            first_router_payload = json.loads(llm.calls[0][1]["content"])

            self.assertGreaterEqual(len(memory["archive"]), 50)
            self.assertLessEqual(len(memory["recent_events"]), 16)
            self.assertIn("累计对话事件", memory["long_term_summary"])
            self.assertIn("dialogue_memory", first_router_payload)
            self.assertTrue(
                any(
                    "到点提醒" in item["text"]
                    for item in first_router_payload["dialogue_memory"]["recent_events"]
                )
            )

    def test_opening_and_runtime_context_use_user_timezone_without_low_energy_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            state = coach.store.load("u1")
            state.profile["timezone"] = "Europe/Stockholm"
            coach.store.save(state)
            llm = FakeLLM(
                [
                    '{"intent":"chat","payload":{},"confidence":0.9}',
                    "你好，我们先看看今天适合怎么安排。",
                ]
            )
            policy = DialoguePolicy(
                now_provider=lambda: datetime(2026, 5, 22, 20, 30, tzinfo=timezone.utc),
            )
            dialogue = DialogueAgent(coach, llm=llm, policy=policy)

            opening = dialogue.opening("u1")
            turn = dialogue.respond("u1", "你好")
            router_payload = json.loads(llm.calls[0][1]["content"])

            self.assertIn("Europe/Stockholm", opening)
            self.assertIn("22:30", opening)
            self.assertIn("到点提醒", opening)
            self.assertNotIn("没力气", opening)
            self.assertNotIn("填表", opening)
            self.assertNotIn("背命令", opening)
            self.assertEqual(router_payload["runtime_context"]["timezone"], "Europe/Stockholm")
            self.assertEqual(router_payload["runtime_context"]["local_hour"], 22)
            self.assertEqual(turn.intent, "chat")

    def test_dialogue_preserves_temporal_working_context_without_phrase_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    (
                        '{"intent":"chat","payload":{},"confidence":0.88,'
                        '"conversation_update":{"temporal_anchor":"after meal",'
                        '"pending_intention":"study later"}}'
                    ),
                    "可以，先处理好吃饭。后面学习我们接着安排。",
                    (
                        '{"intent":"add_task","payload":{"title":"看书","priority":"medium",'
                        '"estimated_minutes":30,"tags":["reading"]},"confidence":0.86,'
                        '"conversation_update":{"current_topic":"reading",'
                        '"temporal_anchor":"after meal"}}'
                    ),
                    "那就把晚饭后的学习先定成看书 30 分钟，吃完后我们再启动。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            dialogue.respond("u1", "我先去处理一下吃饭，之后再学习")
            turn = dialogue.respond("u1", "可能看会书")
            state = coach.store.load("u1")
            response_payload = json.loads(llm.calls[3][1]["content"])

            self.assertEqual(turn.intent, "add_task")
            self.assertEqual(
                state.tracking_state["dialogue_memory"]["working_context"]["temporal_anchor"],
                "after meal",
            )
            self.assertEqual(
                response_payload["dialogue_memory"]["working_context"]["temporal_anchor"],
                "after meal",
            )
            self.assertNotIn("晚饭", dialogue._intent_system_prompt())
            self.assertNotIn("after meal", dialogue._intent_system_prompt())

    def test_late_emotion_turn_uses_policy_for_support_and_tomorrow_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    (
                        '{"intent":"emotion","payload":{"text":"我现在精力很低",'
                        '"readiness":"low","planning_permission":false},"confidence":0.91}'
                    ),
                    "听起来你现在真的需要先缓一缓。今晚不急着拆任务；你可以先休息，或者我们只聊聊是什么让你这么累，明天再排第一小步。",
                ]
            )
            late_policy = DialoguePolicy(
                now_provider=lambda: datetime(2026, 5, 21, 22, 15, tzinfo=timezone.utc),
            )
            dialogue = DialogueAgent(coach, llm=llm, policy=late_policy)

            turn = dialogue.respond("u1", "嗯，我累了")
            router_payload = json.loads(llm.calls[0][1]["content"])
            response_payload = json.loads(llm.calls[1][1]["content"])
            policy_payload = response_payload["dialogue_policy"]

            self.assertEqual(turn.intent, "emotion")
            self.assertEqual(router_payload["runtime_context"]["local_hour"], 22)
            self.assertEqual(policy_payload["user_readiness"], "low")
            self.assertFalse(policy_payload["task_push_allowed"])
            self.assertEqual(policy_payload["task_action_mode"], "support_before_planning")
            self.assertEqual(policy_payload["response_register"], "low_pressure")
            self.assertIn("emotional_support", policy_payload["intervention_modes"])
            self.assertIn("load_assessment", policy_payload["intervention_modes"])
            self.assertIn("late_day_recovery_or_tomorrow_planning", policy_payload["intervention_modes"])
            self.assertIn("autonomy_respect", policy_payload["intervention_modes"])
            self.assertEqual(policy_payload["closing_style"], "supportive_pause")
            self.assertEqual(policy_payload["max_questions"], 0)
            self.assertIn("treating_emotion_as_checkin", policy_payload["avoid_moves"])
            self.assertIn("returning_to_task_before_emotional_response", policy_payload["avoid_moves"])
            self.assertIn("asking_for_academic_task_immediately", policy_payload["avoid_moves"])
            self.assertIn("ending_with_task_pressure_question", policy_payload["avoid_moves"])
            self.assertNotIn("信号", turn.reply)
            self.assertNotIn("打卡", turn.reply)
            self.assertNotIn("最想推进的", turn.reply)

    def test_emoji_only_input_becomes_emotional_signal_not_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    (
                        '{"intent":"emotion","payload":{"text":"用户发了一个哭的表情",'
                        '"readiness":"low","planning_permission":false},"confidence":0.87}'
                    ),
                    "看起来有点撑不住了，先缓一下就行。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "😭")
            router_payload = json.loads(llm.calls[0][1]["content"])
            response_payload = json.loads(llm.calls[1][1]["content"])
            state = coach.store.load("u1")
            memory = state.tracking_state["dialogue_memory"]
            user_events = [item for item in memory["recent_events"] if item["speaker"] == "user"]

            self.assertEqual(turn.intent, "emotion")
            self.assertEqual(router_payload["user_text"], "")
            self.assertEqual(router_payload["input_signal"]["kind"], "emoji")
            self.assertTrue(router_payload["input_signal"]["expression_only"])
            self.assertIn("sad", router_payload["input_signal"]["emotion_tags"])
            self.assertIn("emotional_signal", turn.tool_results)
            self.assertIn("sad", state.emotion.tag_history)
            self.assertEqual(state.tasks, [])
            self.assertNotIn("😭", user_events[-1]["text"])
            self.assertIn("表情", user_events[-1]["text"])
            self.assertEqual(response_payload["user_text"], "")
            self.assertIn("input_signal", response_payload)

    def test_midnight_greeting_uses_sleep_policy_not_task_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            state = coach.store.load("u1")
            state.profile["timezone"] = "Europe/Stockholm"
            coach.store.save(state)
            llm = FakeLLM(
                [
                    '{"intent":"chat","payload":{},"confidence":0.9}',
                    "已经很晚了，今晚先收尾休息吧。论文可以明天再定第一步。",
                ]
            )
            night_policy = DialoguePolicy(
                now_provider=lambda: datetime(2026, 5, 24, 22, 3, tzinfo=timezone.utc),
            )
            dialogue = DialogueAgent(coach, llm=llm, policy=night_policy)

            turn = dialogue.respond("u1", "你好")
            response_payload = json.loads(llm.calls[1][1]["content"])
            policy_payload = response_payload["dialogue_policy"]

            self.assertEqual(policy_payload["runtime"]["local_hour"], 0)
            self.assertIn("sleep_or_shutdown", policy_payload["intervention_modes"])
            self.assertIn("recovery", policy_payload["closing_style"])
            self.assertIn("休息", turn.reply)
            self.assertNotIn("最想先做哪", turn.reply)

    def test_meal_time_policy_surfaces_basic_needs_check(self) -> None:
        policy = DialoguePolicy(
            now_provider=lambda: datetime(2026, 5, 24, 16, 30, tzinfo=timezone.utc),
        )
        runtime = policy.runtime_context("Europe/Stockholm")
        context = policy.build_context(
            action={"intent": "chat", "payload": {}},
            status={"active_task_count": 0, "planned_block_count": 0},
            memory_context={},
            runtime=runtime,
        )

        self.assertEqual(runtime.local_hour, 18)
        self.assertIn("meal_or_basic_needs_check", context.intervention_modes)
        self.assertTrue(any("eating" in item for item in context.planning_options))

    def test_time_context_mentions_are_capped_per_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            state = coach.store.load("u1")
            state.profile["timezone"] = "Europe/Stockholm"
            coach.store.save(state)
            outputs: list[str] = []
            for _ in range(3):
                outputs.extend(
                    [
                        '{"intent":"chat","payload":{},"confidence":0.9}',
                        "已经很晚了，今晚先休息。",
                    ]
                )
            llm = FakeLLM(outputs)
            night_policy = DialoguePolicy(
                now_provider=lambda: datetime(2026, 5, 24, 22, 25, tzinfo=timezone.utc),
            )
            dialogue = DialogueAgent(coach, llm=llm, policy=night_policy)

            dialogue.respond("u1", "你好")
            dialogue.respond("u1", "还在吗")
            dialogue.respond("u1", "嗯")
            second_payload = json.loads(llm.calls[3][1]["content"])
            third_payload = json.loads(llm.calls[5][1]["content"])
            counts = coach.store.load("u1").tracking_state["time_context_counts"]

            self.assertIn("sleep_or_shutdown", second_payload["dialogue_policy"]["intervention_modes"])
            self.assertNotIn("sleep_or_shutdown", third_payload["dialogue_policy"]["intervention_modes"])
            self.assertEqual(counts["night"], 2)

    def test_contextual_plan_confirmation_uses_no_question_closing_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    (
                        '{"intent":"chat","payload":{},"confidence":0.9,'
                        '"conversation_update":{"temporal_anchor":"tomorrow noon",'
                        '"pending_intention":"start writing"}}'
                    ),
                    "好，今晚就休息，明天中午再开始。",
                    '{"intent":"chat","payload":{},"confidence":0.9}',
                    "好，那就按刚才定的来。明天中午先打开文档，写第一句就算启动。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            dialogue.respond("u1", "今晚不写了，明天中午开始")
            turn = dialogue.respond("u1", "好啊")
            response_payload = json.loads(llm.calls[3][1]["content"])
            policy_payload = response_payload["dialogue_policy"]

            self.assertEqual(turn.intent, "chat")
            self.assertEqual(policy_payload["closing_style"], "confirm_context_and_stop")
            self.assertEqual(policy_payload["max_questions"], 0)
            self.assertIn("asking_again_after_context_is_set", policy_payload["avoid_moves"])
            self.assertNotIn("？", turn.reply)
            self.assertNotIn("?", turn.reply)

    def test_plan_creates_proactive_prompts_and_break_offer_for_long_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.add_or_update_task(
                "u1",
                {
                    "task_id": "long",
                    "title": "写论文初稿",
                    "estimated_minutes": 150,
                    "priority": "high",
                    "importance": 5,
                },
            )
            coach.plan_schedule(
                "u1",
                {"current_datetime": "2026-05-22T09:00:00+00:00"},
            )
            state = coach.store.load("u1")
            pushes = state.tracking_state["scheduled_pushes"]
            reasons = {item["metadata"]["reason"] for item in pushes}
            suggestions = coach.get_proactive_suggestions("u1")

            self.assertIn("planned_block_start", reasons)
            self.assertIn("planned_block_checkin", reasons)
            self.assertEqual(suggestions["break_reminder_offer"]["type"], "break_reminder_offer")
            self.assertIn(45, suggestions["break_reminder_offer"]["suggested_intervals"])

    def test_dialogue_schedules_opt_in_break_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            coach.add_or_update_task(
                "u1",
                {
                    "task_id": "long",
                    "title": "写论文初稿",
                    "estimated_minutes": 150,
                    "priority": "high",
                    "importance": 5,
                },
            )
            coach.plan_schedule(
                "u1",
                {
                    "current_datetime": "2026-05-22T09:00:00+00:00",
                    "enable_proactive_prompts": False,
                },
            )
            llm = FakeLLM(
                [
                    '{"intent":"schedule_break_reminders","payload":{"interval_minutes":45},"confidence":0.94}',
                    "好，我会按 45 分钟一轮提醒你休息。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "需要，每45分钟提醒我休息")
            state = coach.store.load("u1")
            break_pushes = [
                item
                for item in state.tracking_state["scheduled_pushes"]
                if item["metadata"].get("reason") == "break_reminder"
            ]
            response_payload = json.loads(llm.calls[1][1]["content"])

            self.assertEqual(turn.intent, "schedule_break_reminders")
            self.assertGreaterEqual(len(break_pushes), 1)
            self.assertEqual(break_pushes[0]["metadata"]["interval_minutes"], 45)
            self.assertEqual(response_payload["dialogue_policy"]["max_questions"], 0)

    def test_dialogue_stickers_are_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"喝水","delay_seconds":30},"confidence":0.94}',
                    "可以，30 秒后我提醒你喝水。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm)

            turn = dialogue.respond("u1", "30秒后提醒我喝水")

            self.assertEqual(turn.intent, "schedule_reminder")
            self.assertIsNone(turn.sticker)
            self.assertNotIn("表情包", turn.reply)

    def test_sticker_library_respects_cadence_and_risk_suppression(self) -> None:
        state = UserState(user_id="u1")
        library = StickerLibrary(min_turn_gap=2, enabled=True)

        first = library.choose(
            state,
            intent="chat",
            policy_context={"response_register": "natural_companion"},
        )
        self.assertIsNotNone(first)

        second = library.choose(
            state,
            intent="chat",
            policy_context={"response_register": "natural_companion"},
        )
        self.assertIsNone(second)

        state.tracking_state["sticker_state"]["turns_since_last"] = 3
        risky = library.choose(
            state,
            intent="emotion",
            policy_context={"response_register": "companionate_support"},
            risk_level=RISK_CRITICAL,
        )
        self.assertIsNone(risky)

    def test_reply_polish_removes_system_feedback_phrasing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"chat","payload":{},"confidence":0.9}',
                    (
                        "你这个状态我接住了：先不推学习。\n"
                        "你说的区别确实重要，我会按这个方向回答。\n"
                        "我们就继续按你前面定的节奏：先稳住状态，不急着把学习顶上去。\n"
                        "这件事可以说得更直白一点。"
                    ),
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm, stickers=StickerLibrary(min_turn_gap=99))

            turn = dialogue.respond("u1", "你觉得你和真人最大的区别是啥")

            self.assertNotIn("接住", turn.reply)
            self.assertNotIn("状态我", turn.reply)
            self.assertNotIn("上下文", turn.reply)
            self.assertNotIn("节奏", turn.reply)
            self.assertNotIn("按这个方向", turn.reply)
            self.assertNotIn("先稳住状态", turn.reply)
            self.assertIn("直白", turn.reply)

    def test_public_language_guard_removes_internal_operations_language(self) -> None:
        guard = PublicLanguageGuard()

        polished = guard.polish(
            "\n".join(
                [
                    "你现在这个上下文我接住了：先不推学习。",
                    "我们就继续按你前面定的节奏：先稳住状态，不急着把学习顶上去。",
                    "如果现在不太合适，就先喝水。",
                    "之后可以换个安排。",
                    "已给你设好提醒了。30 秒后我会提醒你：喝水。[表情包：计时器就位]",
                ]
            )
        )

        self.assertNotIn("上下文", polished)
        self.assertNotIn("接住", polished)
        self.assertNotIn("节奏", polished)
        self.assertNotIn("先稳住状态", polished)
        self.assertNotIn("表情包", polished)
        self.assertNotIn("已给你", polished)
        self.assertNotIn("我会提醒你", polished)
        self.assertIn("先喝水", polished)
        self.assertIn("30 秒后叫你喝水", polished)
        self.assertIn("换个安排", polished)

    def test_chat_harness_does_not_render_sticker_text_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"喝水","delay_seconds":30},"confidence":0.94}',
                    "可以，30 秒后我提醒你喝水。",
                ]
            )
            chat = ChatHarness(coach, "u1", llm=llm)
            chat.dialogue.stickers = StickerLibrary(min_turn_gap=0, enabled=True)

            reply = chat.respond("30秒后提醒我喝水")

            self.assertIn("30 秒后", reply)
            self.assertNotIn("表情包", reply)

    def test_wechat_signature_verification(self) -> None:
        token = "coach-token"
        timestamp = "1779534684"
        nonce = "abc123"
        signature = hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode("utf-8")).hexdigest()

        self.assertTrue(verify_wechat_signature(token, signature, timestamp, nonce))
        self.assertFalse(verify_wechat_signature(token, "bad-signature", timestamp, nonce))

    def test_wechat_official_handler_uses_dialogue_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coach = CentralCoordinator(memory_dir=Path(tmp))
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"喝水","delay_seconds":30},"confidence":0.94}',
                    "可以，30 秒后我提醒你喝水。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm, stickers=StickerLibrary(min_turn_gap=0, enabled=True))
            handler = WeChatOfficialAccountHandler(coach, dialogue)
            xml = (
                "<xml>"
                "<ToUserName><![CDATA[coach_bot]]></ToUserName>"
                "<FromUserName><![CDATA[wechat_user]]></FromUserName>"
                "<MsgType><![CDATA[text]]></MsgType>"
                "<Content><![CDATA[30秒后提醒我喝水]]></Content>"
                "<MsgId>1</MsgId>"
                "</xml>"
            ).encode("utf-8")

            response = handler.handle_xml(xml).decode("utf-8")
            state = coach.store.load("wechat_user")

            self.assertIn("<MsgType><![CDATA[text]]></MsgType>", response)
            self.assertIn("30 秒后", response)
            self.assertNotIn("表情包", response)
            self.assertEqual(state.tracking_state["scheduled_pushes"][0]["message"], "喝水")

    def test_openclaw_adapter_routes_text_message_without_astrbot_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "transport"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(
                json.dumps({"token": "token", "context_tokens": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            updates = [
                {
                    "ret": 0,
                    "errcode": 0,
                    "get_updates_buf": "next-buf",
                    "msgs": [
                        {
                            "from_user_id": "wx_user",
                            "context_token": "ctx_1",
                            "item_list": [
                                {"type": 1, "text_item": {"text": "30秒后提醒我喝水"}}
                            ],
                        }
                    ],
                }
            ]
            client = FakeOpenClawClient(updates)
            coach = CentralCoordinator(memory_dir=Path(tmp) / "coach")
            llm = FakeLLM(
                [
                    '{"intent":"schedule_reminder","payload":{"message":"喝水","delay_seconds":30},"confidence":0.94}',
                    "可以，30 秒后我提醒你喝水。\n\n先把杯子放手边。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm, stickers=StickerLibrary(min_turn_gap=0, enabled=True))
            adapter = OpenClawWeChatAdapter(
                coach,
                state_dir=state_dir,
                dialogue=dialogue,
                client=client,
            )

            asyncio.run(adapter.poll_once())

            coach_state = coach.store.load("wx_user")
            self.assertEqual(adapter.state.sync_buf, "next-buf")
            self.assertEqual(adapter.state.context_tokens["wx_user"], "ctx_1")
            self.assertEqual(coach_state.tracking_state["scheduled_pushes"][0]["message"], "喝水")
            self.assertEqual(client.sent[0]["user_id"], "wx_user")
            self.assertIn("30 秒后", client.sent[0]["text"])
            self.assertEqual(client.sent[1]["text"], "先把杯子放手边。")
            self.assertNotIn("表情包", "\n".join(item["text"] for item in client.sent))

    def test_openclaw_adapter_routes_sticker_as_emotion_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "transport"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(
                json.dumps({"token": "token", "context_tokens": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            updates = [
                {
                    "ret": 0,
                    "errcode": 0,
                    "get_updates_buf": "next-buf",
                    "msgs": [
                        {
                            "from_user_id": "wx_user",
                            "context_token": "ctx_1",
                            "item_list": [
                                {"type": 47, "emoji_item": {"name": "[流泪]"}}
                            ],
                        }
                    ],
                }
            ]
            client = FakeOpenClawClient(updates)
            coach = CentralCoordinator(memory_dir=Path(tmp) / "coach")
            llm = FakeLLM(
                [
                    (
                        '{"intent":"emotion","payload":{"text":"用户发了一个流泪表情",'
                        '"readiness":"low","planning_permission":false},"confidence":0.86}'
                    ),
                    "看起来不太开心。先缓一下，我在。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm, stickers=StickerLibrary(min_turn_gap=0, enabled=True))
            adapter = OpenClawWeChatAdapter(
                coach,
                state_dir=state_dir,
                dialogue=dialogue,
                client=client,
            )

            asyncio.run(adapter.poll_once())

            router_payload = json.loads(llm.calls[0][1]["content"])
            coach_state = coach.store.load("wx_user")
            user_events = [
                item
                for item in coach_state.tracking_state["dialogue_memory"]["recent_events"]
                if item["speaker"] == "user"
            ]

            self.assertEqual(router_payload["user_text"], "")
            self.assertEqual(router_payload["input_signal"]["source"], "wechat_emoji")
            self.assertIn("sad", router_payload["input_signal"]["emotion_tags"])
            self.assertEqual(coach_state.tasks, [])
            self.assertIn("sad", coach_state.emotion.tag_history)
            self.assertIn("表情", user_events[-1]["text"])
            self.assertNotIn("[流泪]", user_events[-1]["text"])
            self.assertEqual(client.sent[0]["text"], "看起来不太开心。先缓一下，我在。")

    def test_hosted_openclaw_account_namespaces_coach_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "account"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(
                json.dumps({"token": "token", "context_tokens": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            updates = [
                {
                    "ret": 0,
                    "errcode": 0,
                    "get_updates_buf": "next-buf",
                    "msgs": [
                        {
                            "from_user_id": "wx_user",
                            "context_token": "ctx_1",
                            "item_list": [
                                {"type": 1, "text_item": {"text": "我想聊聊"}}
                            ],
                        }
                    ],
                }
            ]
            client = FakeOpenClawClient(updates)
            coach = CentralCoordinator(memory_dir=Path(tmp) / "coach")
            llm = FakeLLM(
                [
                    '{"intent":"chat","payload":{},"confidence":0.92}',
                    "你好，我在。",
                ]
            )
            dialogue = DialogueAgent(coach, llm=llm, access_control=AccessControl())
            account = HostedOpenClawAccount(
                "acct_a",
                coordinator=coach,
                dialogue=dialogue,
                config=OpenClawConfig(),
                state_dir=state_dir,
                client_factory=lambda _config, _token: client,
            )

            asyncio.run(account.poll_once())

            namespaced_state = coach.store.load("wechat:acct_a:wx_user")
            router_payload = json.loads(llm.calls[0][1]["content"])

            self.assertEqual(account.state.sync_buf, "next-buf")
            self.assertEqual(account.state.context_tokens["wx_user"], "ctx_1")
            self.assertEqual(namespaced_state.user_id, "wechat:acct_a:wx_user")
            self.assertEqual(router_payload["user_text"], "我想聊聊")
            self.assertEqual(client.sent[0]["user_id"], "wx_user")
            self.assertEqual(client.sent[0]["text"], "你好，我在。")

    def test_openclaw_adapter_delivers_due_pushes_to_known_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "transport"
            state_dir.mkdir()
            (state_dir / "state.json").write_text(
                json.dumps(
                    {
                        "token": "token",
                        "context_tokens": {"wx_user": "ctx_1"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            client = FakeOpenClawClient([])
            coach = CentralCoordinator(memory_dir=Path(tmp) / "coach")
            coach.schedule_push(
                "wx_user",
                "喝水",
                iso_from_datetime(datetime.now(timezone.utc) - timedelta(seconds=1)),
            )
            adapter = OpenClawWeChatAdapter(coach, state_dir=state_dir, client=client)

            asyncio.run(adapter.poll_once())

            self.assertEqual(client.sent[0]["context_token"], "ctx_1")
            self.assertEqual(client.sent[0]["text"], "该喝水啦")


if __name__ == "__main__":
    unittest.main()
