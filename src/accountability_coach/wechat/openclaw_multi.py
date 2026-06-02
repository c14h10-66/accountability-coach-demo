"""Hosted multi-account OpenClaw runtime.

This module lets one server host multiple personal-WeChat OpenClaw sessions.
Each scanned account owns its own transport token, sync buffer, context tokens,
and polling tasks.  The coach memory remains centralized but user ids are
namespaced per hosted account to avoid cross-account collisions.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from accountability_coach.core.coordinator import CentralCoordinator
from accountability_coach.dialogue import DialogueAgent
from accountability_coach.messaging.message import MessageResponse
from accountability_coach.wechat.openclaw_adapter import (
    SESSION_TIMEOUT_ERRCODE,
    OpenClawAdapterState,
)
from accountability_coach.wechat.openclaw_client import (
    OpenClawClient,
    OpenClawConfig,
    OpenClawError,
    OpenClawLoginQR,
)
from accountability_coach.wechat.openclaw_codec import OpenClawMessageCodec


ClientFactory = Callable[[OpenClawConfig, str | None], OpenClawClient]


@dataclass(slots=True)
class HostedAccountStatus:
    """Public status for a hosted OpenClaw account, with no token exposure."""

    account_id: str
    logged_in: bool
    login_status: str
    ilink_account_id: str = ""
    base_url: str = ""
    has_qr: bool = False
    qrcode_img_content: str = ""
    context_count: int = 0
    last_error: str = ""
    updated_at: float = field(default_factory=time.time)


class HostedOpenClawAccount:
    """One hosted personal-WeChat account session."""

    def __init__(
        self,
        account_id: str,
        *,
        coordinator: CentralCoordinator,
        dialogue: DialogueAgent,
        config: OpenClawConfig,
        state_dir: Path,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.account_id = account_id
        self.coordinator = coordinator
        self.dialogue = dialogue
        self.config = replace(config)
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"
        self.state = self._load_state()
        if self.state.base_url:
            self.config.base_url = self.state.base_url
        factory = client_factory or (lambda cfg, token: OpenClawClient(cfg, token=token))
        self.client = factory(self.config, self.state.token or None)
        self.client.config = self.config
        self.client.token = self.state.token or None
        self.codec = OpenClawMessageCodec(self.dialogue.input_signals)
        self._login_qr: OpenClawLoginQR | None = None
        self._login_started_at = 0.0
        self._login_status = "confirmed" if self.client.token else "not_started"
        self._last_error = ""
        self._stopping = asyncio.Event()
        self._login_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._push_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._stopping.clear()
        if self.client.token:
            self._ensure_runtime_tasks()

    async def stop(self) -> None:
        self._stopping.set()
        for task in (self._login_task, self._poll_task, self._push_task):
            if task:
                task.cancel()
        for task in (self._login_task, self._poll_task, self._push_task):
            if not task:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def start_login(self) -> HostedAccountStatus:
        self._stopping.clear()
        await self._ensure_login_qr()
        if not self._login_task or self._login_task.done():
            self._login_task = asyncio.create_task(self._login_poll_loop())
        return self.status()

    async def poll_once(self) -> None:
        if self.client.token:
            await self._poll_inbound_once()
            await self._deliver_due_pushes()
        elif self._login_qr:
            await self._poll_login_once()
        else:
            await self.start_login()

    def status(self) -> HostedAccountStatus:
        return HostedAccountStatus(
            account_id=self.account_id,
            logged_in=bool(self.client.token),
            login_status=self._login_status,
            ilink_account_id=self.state.account_id,
            base_url=self.config.base_url,
            has_qr=self._login_qr is not None,
            qrcode_img_content=self._login_qr.qrcode_img_content if self._login_qr else "",
            context_count=len(self.state.context_tokens),
            last_error=self._last_error,
        )

    async def send(self, response: MessageResponse) -> None:
        platform_user_id = response.conversation_id
        context_token = self.state.context_tokens.get(platform_user_id, "")
        if not context_token:
            raise OpenClawError(
                f"Cannot send to {platform_user_id}: no context_token yet. The user must message first."
            )
        payload = await asyncio.to_thread(
            self.client.send_text,
            platform_user_id,
            context_token,
            response.text,
        )
        if not self.client.is_success(payload):
            raise OpenClawError(self.client.error_text(payload))

    async def _login_poll_loop(self) -> None:
        while not self._stopping.is_set() and not self.client.token:
            try:
                await self._poll_login_once()
            except OpenClawError as exc:
                self._login_status = "error"
                self._last_error = str(exc)
            await asyncio.sleep(max(1, self.config.qr_poll_interval_seconds))

    async def _poll_login_once(self) -> None:
        await self._ensure_login_qr()
        assert self._login_qr is not None
        data = await asyncio.to_thread(self.client.poll_login, self._login_qr.qrcode)
        status = str(data.get("status") or "wait")
        self._login_status = status
        if status == "expired":
            self._login_qr = None
            await self._ensure_login_qr()
            return
        if status != "confirmed":
            return
        token = str(data.get("bot_token") or "").strip()
        if not token:
            raise OpenClawError("Login confirmed but bot_token was missing")
        self.state.token = token
        self.state.account_id = str(data.get("ilink_bot_id") or "").strip()
        self.state.base_url = str(data.get("baseurl") or self.config.base_url).strip()
        self.config.base_url = self.state.base_url
        self.client.config = self.config
        self.client.token = token
        self._login_qr = None
        self._login_status = "confirmed"
        self._last_error = ""
        self._save_state()
        self._ensure_runtime_tasks()

    async def _ensure_login_qr(self) -> None:
        if self._login_qr is not None and time.time() - self._login_started_at <= 300:
            return
        self._login_qr = await asyncio.to_thread(self.client.get_login_qr)
        self._login_started_at = time.time()
        self._login_status = "waiting"
        self._save_state()

    def _ensure_runtime_tasks(self) -> None:
        if not self._poll_task or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())
        if not self._push_task or self._push_task.done():
            self._push_task = asyncio.create_task(self._push_loop())

    async def _poll_loop(self) -> None:
        while not self._stopping.is_set() and self.client.token:
            try:
                await self._poll_inbound_once()
            except OpenClawError as exc:
                self._last_error = str(exc)
                await asyncio.sleep(5)
            except Exception as exc:
                self._last_error = str(exc)
                await asyncio.sleep(5)

    async def _push_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(max(1, self.config.push_poll_seconds))
            if self.client.token:
                await self._deliver_due_pushes()

    async def _poll_inbound_once(self) -> None:
        data = await asyncio.to_thread(self.client.get_updates, self.state.sync_buf)
        if not self.client.is_success(data):
            if self._api_errcode(data) == SESSION_TIMEOUT_ERRCODE:
                self._clear_login()
                return
            raise OpenClawError(self.client.error_text(data))
        next_buf = str(data.get("get_updates_buf") or "").strip()
        if next_buf and next_buf != self.state.sync_buf:
            self.state.sync_buf = next_buf
            self._save_state()
        msgs = data.get("msgs")
        if not isinstance(msgs, list):
            return
        for msg in msgs:
            if isinstance(msg, dict):
                await self._handle_inbound_message(msg)

    async def _handle_inbound_message(self, msg: dict[str, Any]) -> None:
        platform_user_id = str(msg.get("from_user_id") or "").strip()
        if not platform_user_id:
            return
        context_token = str(msg.get("context_token") or "").strip()
        if context_token:
            self.state.context_tokens[platform_user_id] = context_token
            self._save_state()
        text, signal = self.codec.input_from_item_list(msg.get("item_list"))
        if not text and signal is None:
            return
        coach_user_id = self._coach_user_id(platform_user_id)
        turn = (
            self.dialogue.respond(coach_user_id, text)
            if text
            else self.dialogue.respond_signal(coach_user_id, signal)
        )
        for segment in self.codec.split_outbound_text(turn.reply):
            await self.send(MessageResponse(conversation_id=platform_user_id, text=segment))

    async def _deliver_due_pushes(self) -> None:
        for platform_user_id in list(self.state.context_tokens):
            coach_user_id = self._coach_user_id(platform_user_id)
            due = self.coordinator.pop_due_pushes(coach_user_id)
            for push in due:
                message = str(push.get("message") or "").strip()
                if not message:
                    continue
                await self.send(
                    MessageResponse(
                        conversation_id=platform_user_id,
                        text=self.codec.natural_reminder_text(message),
                        metadata={"source": "scheduled_push"},
                    )
                )

    def _coach_user_id(self, platform_user_id: str) -> str:
        return f"wechat:{self.account_id}:{platform_user_id}"

    def _clear_login(self) -> None:
        self.state.token = ""
        self.state.account_id = ""
        self.state.sync_buf = ""
        self.state.context_tokens = {}
        self.client.token = None
        self._login_status = "session_expired"
        self._save_state()

    def _load_state(self) -> OpenClawAdapterState:
        if not self.state_file.exists():
            return OpenClawAdapterState()
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return OpenClawAdapterState()
        if not isinstance(raw, dict):
            return OpenClawAdapterState()
        context_tokens = raw.get("context_tokens")
        return OpenClawAdapterState(
            token=str(raw.get("token") or ""),
            account_id=str(raw.get("account_id") or ""),
            base_url=str(raw.get("base_url") or ""),
            sync_buf=str(raw.get("sync_buf") or ""),
            context_tokens={
                str(key): str(value)
                for key, value in (context_tokens or {}).items()
                if key and value
            }
            if isinstance(context_tokens, dict)
            else {},
        )

    def _save_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(self.state), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.state_file)

    @staticmethod
    def _api_errcode(payload: dict[str, Any]) -> int:
        try:
            return int(payload.get("errcode") or 0)
        except (TypeError, ValueError):
            return 0


class OpenClawMultiAccountManager:
    """Own and supervise all hosted OpenClaw account sessions."""

    def __init__(
        self,
        *,
        coordinator: CentralCoordinator,
        dialogue: DialogueAgent,
        config: OpenClawConfig,
        accounts_dir: Path,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.dialogue = dialogue
        self.config = config
        self.accounts_dir = Path(accounts_dir)
        self.client_factory = client_factory
        self.accounts: dict[str, HostedOpenClawAccount] = {}

    async def load_existing(self) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.accounts_dir.iterdir()):
            if path.is_dir():
                account = self._build_account(path.name)
                self.accounts[account.account_id] = account
                await account.start()

    async def create_account(self) -> HostedOpenClawAccount:
        account_id = self._new_account_id()
        account = self._build_account(account_id)
        self.accounts[account_id] = account
        await account.start_login()
        return account

    async def start_login(self, account_id: str) -> HostedAccountStatus:
        account = self.get_account(account_id)
        return await account.start_login()

    async def stop_all(self) -> None:
        for account in list(self.accounts.values()):
            await account.stop()

    def list_statuses(self) -> list[HostedAccountStatus]:
        return [account.status() for account in sorted(self.accounts.values(), key=lambda item: item.account_id)]

    def get_status(self, account_id: str) -> HostedAccountStatus:
        return self.get_account(account_id).status()

    def get_account(self, account_id: str) -> HostedOpenClawAccount:
        account = self.accounts.get(account_id)
        if not account:
            raise KeyError(account_id)
        return account

    def _build_account(self, account_id: str) -> HostedOpenClawAccount:
        return HostedOpenClawAccount(
            account_id,
            coordinator=self.coordinator,
            dialogue=self.dialogue,
            config=self.config,
            state_dir=self.accounts_dir / account_id,
            client_factory=self.client_factory,
        )

    def _new_account_id(self) -> str:
        while True:
            account_id = "acct_" + uuid.uuid4().hex[:12]
            if account_id not in self.accounts and not (self.accounts_dir / account_id).exists():
                return account_id
