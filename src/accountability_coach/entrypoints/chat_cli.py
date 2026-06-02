"""Interactive terminal entrypoint for the accountability coach."""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from accountability_coach import CentralCoordinator
from accountability_coach.dialogue import DialogueAgent
from accountability_coach.dialogue.llm import LLMClient


class LocalPushLoop:
    """Poll persisted reminders and print due pushes in the terminal."""

    def __init__(self, coach: CentralCoordinator, user_id: str, interval_seconds: float = 1.0) -> None:
        self.coach = coach
        self.user_id = user_id
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            for push in self.coach.pop_due_pushes(self.user_id):
                message = push.get("message", "回来打卡")
                metadata = push.get("metadata") if isinstance(push.get("metadata"), dict) else {}
                is_followup = metadata.get("reason") == "silence_followup"
                text = str(message).strip()
                if not is_followup and not any(
                    marker in text for marker in ("该", "记得", "别忘", "提醒", "到了", "啦", "吧", "。", "！", "？")
                ):
                    text = f"该{text}啦"
                print(f"\n教练 > {text}\n你 > ", end="", flush=True)


class ChatHarness:
    """Thin terminal adapter around the LLM-powered dialogue agent."""

    EXIT_WORDS = {"exit", "quit", "q", "退出", "结束", "拜拜"}

    def __init__(
        self,
        coach: CentralCoordinator,
        user_id: str,
        llm: LLMClient | None = None,
        timezone_name: str | None = None,
    ) -> None:
        if timezone_name:
            state = coach.store.load(user_id)
            state.profile["timezone"] = timezone_name
            coach.store.save(state)
        self.user_id = user_id
        self.dialogue = DialogueAgent(coach, llm=llm)

    def opening(self) -> str:
        return self.dialogue.opening(self.user_id)

    def respond(self, text: str) -> str:
        turn = self.dialogue.respond(self.user_id, text)
        return turn.reply


def main() -> int:
    parser = argparse.ArgumentParser(prog="accountability-coach-chat")
    parser.add_argument("--user-id", default="chat_test")
    parser.add_argument("--memory-dir", default=".accountability_coach_memory")
    parser.add_argument("--timezone", default=None, help="User IANA timezone, e.g. Europe/Stockholm")
    args = parser.parse_args()

    coach = CentralCoordinator(memory_dir=Path(args.memory_dir))
    harness = ChatHarness(coach, args.user_id, timezone_name=args.timezone)
    push_loop = LocalPushLoop(coach, args.user_id)
    push_loop.start()

    print("Accountability Coach 测试对话已启动。输入「退出」结束。")
    if not harness.dialogue.llm.is_available():
        print(
            "注意：当前没有配置 LLM，自然语言对话不会启用。\n"
            "请设置 ACCOUNTABILITY_COACH_LLM_BASE_URL、ACCOUNTABILITY_COACH_LLM_API_KEY、"
            "ACCOUNTABILITY_COACH_LLM_MODEL 后重新启动。"
        )
    print(harness.opening())
    try:
        while True:
            try:
                text = input("\n你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已结束。")
                return 0
            if text in ChatHarness.EXIT_WORDS:
                print("教练 > 好，今天先停在这里。")
                return 0
            print("教练 > " + harness.respond(text))
    finally:
        push_loop.stop()


if __name__ == "__main__":
    raise SystemExit(main())
