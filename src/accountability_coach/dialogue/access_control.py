"""Invitation and allow-list control for shared chat deployments."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass, field

from accountability_coach.core.models import UserState, now_iso


@dataclass(slots=True)
class AccessDecision:
    """Result of checking whether a user may use the coach dialogue."""

    allowed: bool
    handled: bool = False
    reply: str = ""
    should_save: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class AccessControl:
    """Small invitation layer for personal-WeChat sharing.

    If no invite codes, allow-list, or explicit requirement is configured, the
    coach remains open.  Once enabled, users must either be allow-listed or send
    a valid invite code before the LLM dialogue is called.
    """

    INVITE_RE = re.compile(
        r"^(?:/invite|invite|邀请码|邀请码是|我的邀请码是|code)\s*[:：]?\s*(?P<code>\S+)\s*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        invite_codes: set[str] | None = None,
        allowed_users: set[str] | None = None,
        require_invite: bool = False,
    ) -> None:
        self.invite_codes = {code.strip() for code in (invite_codes or set()) if code.strip()}
        self.allowed_users = {user.strip() for user in (allowed_users or set()) if user.strip()}
        self.require_invite = require_invite or bool(self.invite_codes or self.allowed_users)

    @classmethod
    def from_env(
        cls,
        *,
        invite_codes: list[str] | None = None,
        allowed_users: list[str] | None = None,
        require_invite: bool | None = None,
    ) -> "AccessControl":
        env_codes = cls._split_env(os.getenv("ACCOUNTABILITY_COACH_INVITE_CODES", ""))
        env_users = cls._split_env(os.getenv("ACCOUNTABILITY_COACH_ALLOWED_USERS", ""))
        env_required = cls._truthy(os.getenv("ACCOUNTABILITY_COACH_REQUIRE_INVITE", ""))
        return cls(
            invite_codes=set(env_codes + list(invite_codes or [])),
            allowed_users=set(env_users + list(allowed_users or [])),
            require_invite=env_required if require_invite is None else require_invite,
        )

    def evaluate(self, state: UserState, text: str = "") -> AccessDecision:
        if not self.require_invite:
            return AccessDecision(allowed=True)
        if self._is_authorized(state):
            return AccessDecision(allowed=True)
        if state.user_id in self.allowed_users:
            self._authorize(state, source="allow_list", code="")
            return AccessDecision(allowed=True, should_save=True)

        invite_code = self._extract_invite_code(text)
        if invite_code:
            if self._valid_code(invite_code):
                self._authorize(state, source="invite_code", code=invite_code)
                return AccessDecision(
                    allowed=True,
                    handled=True,
                    should_save=True,
                    reply=(
                        "通过了，欢迎来用。\n"
                        "你可以先发“设置昵称 小周”或“设置时区 Asia/Shanghai”，也可以直接说现在想处理的学习任务。"
                    ),
                    metadata={"authorized": True, "source": "invite_code"},
                )
            return AccessDecision(
                allowed=False,
                handled=True,
                reply="邀请码不对。你再确认一下，格式可以发：邀请码 xxxx。",
                metadata={"authorized": False, "reason": "invalid_invite_code"},
            )

        return AccessDecision(
            allowed=False,
            handled=True,
            reply="这个教练现在是邀请制。让主人给你一个邀请码，然后直接发：邀请码 xxxx。",
            metadata={"authorized": False, "reason": "invite_required"},
        )

    def _is_authorized(self, state: UserState) -> bool:
        access = state.profile.get("access")
        return isinstance(access, dict) and bool(access.get("authorized"))

    def _authorize(self, state: UserState, *, source: str, code: str) -> None:
        state.profile["access"] = {
            "authorized": True,
            "source": source,
            "authorized_at": now_iso(),
            **({"invite_code_hash": self._hash_code(code)} if code else {}),
        }
        state.updated_at = now_iso()

    def _extract_invite_code(self, text: str) -> str:
        match = self.INVITE_RE.match(text.strip())
        return match.group("code").strip() if match else ""

    def _valid_code(self, code: str) -> bool:
        return any(hmac.compare_digest(code, expected) for expected in self.invite_codes)

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @staticmethod
    def _split_env(value: str) -> list[str]:
        return [item for item in re.split(r"[,;\s]+", value.strip()) if item]

    @staticmethod
    def _truthy(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}
