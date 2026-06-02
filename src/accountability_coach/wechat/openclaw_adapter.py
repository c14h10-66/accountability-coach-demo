"""Personal-WeChat adapter backed by the OpenClaw text API."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from accountability_coach.core.coordinator import CentralCoordinator
from accountability_coach.dialogue import DialogueAgent
from accountability_coach.dialogue.input_signals import InputSignal
from accountability_coach.messaging.message import MessageResponse
from accountability_coach.wechat.openclaw_codec import OpenClawMessageCodec
from accountability_coach.wechat.openclaw_client import (
    OpenClawClient,
    OpenClawConfig,
    OpenClawError,
    OpenClawLoginQR,
)


SESSION_TIMEOUT_ERRCODE = -14


@dataclass(slots=True)
class OpenClawAdapterState:
    """Persisted transport state separate from the coach's user memory."""

    token: str = ""
    account_id: str = ""
    base_url: str = ""
    sync_buf: str = ""
    context_tokens: dict[str, str] = field(default_factory=dict)


class OpenClawWeChatAdapter:
    """Direct personal-WeChat adapter for natural-language coach dialogue."""

    def __init__(
        self,
        coordinator: CentralCoordinator,
        *,
        config: OpenClawConfig | None = None,
        state_dir: Path | str = ".accountability_coach_memory/wechat_openclaw",
        dialogue: DialogueAgent | None = None,
        client: OpenClawClient | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.config = config or OpenClawConfig()
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"
        self.state = self._load_state()
        if self.state.base_url:
            self.config.base_url = self.state.base_url
        self.dialogue = dialogue or DialogueAgent(coordinator)
        self.codec = OpenClawMessageCodec(self.dialogue.input_signals)
        self.client = client or OpenClawClient(
            self.config,
            token=self.state.token or None,
        )
        self.client.config = self.config
        self.client.token = self.state.token or None
        self._login_qr: OpenClawLoginQR | None = None
        self._login_started_at = 0.0
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Run login, inbound polling, and due-push delivery until stopped."""
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._poll_loop()),
            asyncio.create_task(self._push_loop()),
        ]
        try:
            await asyncio.gather(*self._tasks)
        finally:
            self._tasks = []

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def send(self, response: MessageResponse) -> None:
        user_id = response.conversation_id
        context_token = self.state.context_tokens.get(user_id, "")
        if not context_token:
            raise OpenClawError(
                f"Cannot send to {user_id}: no context_token yet. The user must message the coach first."
            )
        payload = await asyncio.to_thread(
            self.client.send_text,
            user_id,
            context_token,
            response.text,
        )
        if not self.client.is_success(payload):
            raise OpenClawError(self.client.error_text(payload))

    async def poll_once(self) -> None:
        """One adapter tick, useful for tests and supervised runtimes."""
        if not self.client.token:
            await self._login_step()
            return
        await self._poll_inbound_once()
        await self._deliver_due_pushes()

    async def _poll_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                if not self.client.token:
                    await self._login_step()
                    await asyncio.sleep(max(1, self.config.qr_poll_interval_seconds))
                    continue
                await self._poll_inbound_once()
            except OpenClawError as exc:
                print(f"OpenClaw adapter error: {exc}")
                await asyncio.sleep(5)
            except Exception as exc:
                print(f"OpenClaw adapter unexpected error: {exc}")
                await asyncio.sleep(5)

    async def _push_loop(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(max(1, self.config.push_poll_seconds))
            if self.client.token:
                await self._deliver_due_pushes()

    async def _login_step(self) -> None:
        if self._login_qr is None or time.time() - self._login_started_at > 300:
            self._login_qr = await asyncio.to_thread(self.client.get_login_qr)
            self._login_started_at = time.time()
            self._print_login_qr(self._login_qr)
            return
        data = await asyncio.to_thread(self.client.poll_login, self._login_qr.qrcode)
        status = str(data.get("status") or "wait")
        if status == "expired":
            self._login_qr = None
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
        self._save_state()
        print("OpenClaw WeChat login confirmed.")

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
        user_id = str(msg.get("from_user_id") or "").strip()
        if not user_id:
            return
        context_token = str(msg.get("context_token") or "").strip()
        if context_token:
            self.state.context_tokens[user_id] = context_token
            self._save_state()
        text, signal = self.codec.input_from_item_list(msg.get("item_list"))
        if not text and signal is None:
            return
        turn = (
            self.dialogue.respond(user_id, text)
            if text
            else self.dialogue.respond_signal(user_id, signal)
        )
        for segment in self.codec.split_outbound_text(turn.reply):
            await self.send(MessageResponse(conversation_id=user_id, text=segment))

    async def _deliver_due_pushes(self) -> None:
        for user_id in list(self.state.context_tokens):
            due = self.coordinator.pop_due_pushes(user_id)
            for push in due:
                message = str(push.get("message") or "").strip()
                if not message:
                    continue
                await self.send(
                    MessageResponse(
                        conversation_id=user_id,
                        text=self.codec.natural_reminder_text(message),
                        metadata={"source": "scheduled_push"},
                    )
                )

    def _clear_login(self) -> None:
        self.state.token = ""
        self.state.account_id = ""
        self.state.sync_buf = ""
        self.state.context_tokens = {}
        self.client.token = None
        self._save_state()
        print("OpenClaw session expired. Waiting for QR login again.")

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
            json.dumps(
                asdict(self.state),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.state_file)

    def _print_login_qr(self, login_qr: OpenClawLoginQR) -> None:
        helper_url = (
            "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data="
            + quote(login_qr.qrcode_img_content)
        )
        print("OpenClaw WeChat QR login required.")
        print(f"QR content: {login_qr.qrcode_img_content}")
        print(f"QR helper URL: {helper_url}")

    def _text_from_item_list(self, item_list: object) -> str:
        return self.codec.text_from_item_list(item_list)

    def _input_from_item_list(self, item_list: object) -> tuple[str, InputSignal | None]:
        return self.codec.input_from_item_list(item_list)

    def _signal_from_item(self, item: dict[str, Any]) -> InputSignal | None:
        return self.codec.signal_from_item(item)

    def _first_nested_text(self, value: object, *, preferred_keys: set[str]) -> str:
        return self.codec._first_nested_text(value, preferred_keys=preferred_keys)

    @staticmethod
    def _split_outbound_text(text: str) -> list[str]:
        return OpenClawMessageCodec.split_outbound_text(text)

    @staticmethod
    def _natural_reminder_text(message: str) -> str:
        return OpenClawMessageCodec.natural_reminder_text(message)

    @staticmethod
    def _api_errcode(payload: dict[str, Any]) -> int:
        try:
            return int(payload.get("errcode") or 0)
        except (TypeError, ValueError):
            return 0
