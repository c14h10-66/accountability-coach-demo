"""Run the direct OpenClaw personal-WeChat adapter."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from accountability_coach import CentralCoordinator
from accountability_coach.dialogue import AccessControl, DialogueAgent
from accountability_coach.wechat.openclaw_adapter import OpenClawWeChatAdapter
from accountability_coach.wechat.openclaw_client import OpenClawConfig


async def _run(args: argparse.Namespace) -> None:
    config = OpenClawConfig(
        base_url=args.base_url,
        bot_type=args.bot_type,
        qr_poll_interval_seconds=args.qr_poll_interval,
        long_poll_timeout_ms=args.long_poll_timeout_ms,
        api_timeout_ms=args.api_timeout_ms,
        push_poll_seconds=args.push_poll_seconds,
    )
    coordinator = CentralCoordinator(memory_dir=Path(args.memory_dir))
    access_control = AccessControl.from_env(
        invite_codes=args.invite_code,
        allowed_users=args.allowed_user,
        require_invite=args.require_invite,
    )
    dialogue = DialogueAgent(coordinator, access_control=access_control)
    adapter = OpenClawWeChatAdapter(
        coordinator,
        config=config,
        state_dir=Path(args.memory_dir) / "wechat_openclaw",
        dialogue=dialogue,
    )
    await adapter.start()


def main() -> int:
    parser = argparse.ArgumentParser(prog="accountability-coach-wechat-openclaw")
    parser.add_argument("--memory-dir", default=".accountability_coach_memory")
    parser.add_argument("--base-url", default="https://ilinkai.weixin.qq.com")
    parser.add_argument("--bot-type", default="3")
    parser.add_argument("--qr-poll-interval", type=int, default=1)
    parser.add_argument("--long-poll-timeout-ms", type=int, default=35_000)
    parser.add_argument("--api-timeout-ms", type=int, default=15_000)
    parser.add_argument("--push-poll-seconds", type=int, default=5)
    parser.add_argument("--invite-code", action="append", default=[], help="Invite code accepted by the coach")
    parser.add_argument("--allowed-user", action="append", default=[], help="Wechat user id allowed without an invite")
    parser.add_argument("--require-invite", action="store_true", help="Require an invite even if no env invite code is set")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
