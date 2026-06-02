"""Small OpenClaw WeChat client used by the personal-WeChat adapter.

This module intentionally stays independent from AstrBot.  It implements only
the text-message subset needed by the accountability coach runtime: QR login,
long-poll updates, and plain-text sends.
"""

from __future__ import annotations

import base64
import json
import random
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_OPENCLAW_BASE_URL = "https://ilinkai.weixin.qq.com"


class OpenClawError(RuntimeError):
    """Raised when the OpenClaw API request fails or returns invalid data."""


@dataclass(slots=True)
class OpenClawConfig:
    """Runtime configuration for the personal-WeChat transport."""

    base_url: str = DEFAULT_OPENCLAW_BASE_URL
    bot_type: str = "3"
    channel_version: str = "accountability-coach"
    qr_poll_interval_seconds: int = 1
    long_poll_timeout_ms: int = 35_000
    api_timeout_ms: int = 15_000
    push_poll_seconds: int = 5


@dataclass(slots=True)
class OpenClawLoginQR:
    """QR login payload returned by OpenClaw."""

    qrcode: str
    qrcode_img_content: str


class OpenClawClient:
    """Dependency-free wrapper around the OpenClaw text endpoints."""

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        *,
        token: str | None = None,
    ) -> None:
        self.config = config or OpenClawConfig()
        self.token = token

    def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        token_required: bool = False,
        timeout_ms: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._url(endpoint, params)
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            url,
            data=body,
            headers=self._headers(token_required=token_required, extra=headers),
            method=method.upper(),
        )
        timeout = (timeout_ms or self.config.api_timeout_ms) / 1000
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise OpenClawError(f"{method.upper()} {endpoint} failed: {exc}") from exc
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenClawError(f"{method.upper()} {endpoint} returned non-JSON data") from exc
        if not isinstance(data, dict):
            raise OpenClawError(f"{method.upper()} {endpoint} returned unexpected JSON")
        return data

    def get_login_qr(self) -> OpenClawLoginQR:
        data = self.request_json(
            "GET",
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": self.config.bot_type},
            timeout_ms=15_000,
        )
        qrcode = str(data.get("qrcode") or "").strip()
        qrcode_img_content = str(data.get("qrcode_img_content") or "").strip()
        if not qrcode or not qrcode_img_content:
            raise OpenClawError("QR response missing qrcode or qrcode_img_content")
        return OpenClawLoginQR(qrcode=qrcode, qrcode_img_content=qrcode_img_content)

    def poll_login(self, qrcode: str) -> dict[str, Any]:
        return self.request_json(
            "GET",
            "ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            timeout_ms=self.config.long_poll_timeout_ms,
            headers={"iLink-App-ClientVersion": "1"},
        )

    def get_updates(self, sync_buf: str) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "ilink/bot/getupdates",
            payload={
                "base_info": {"channel_version": self.config.channel_version},
                "get_updates_buf": sync_buf,
            },
            token_required=True,
            timeout_ms=self.config.long_poll_timeout_ms,
        )

    def send_text(self, user_id: str, context_token: str, text: str) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "ilink/bot/sendmessage",
            payload={
                "base_info": {"channel_version": self.config.channel_version},
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": uuid.uuid4().hex,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                },
            },
            token_required=True,
        )

    @staticmethod
    def is_success(payload: dict[str, Any]) -> bool:
        try:
            ret = int(payload.get("ret") or 0)
            errcode = int(payload.get("errcode") or 0)
            return ret == 0 and errcode == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def error_text(payload: dict[str, Any]) -> str:
        ret = payload.get("ret", 0)
        errcode = payload.get("errcode", 0)
        errmsg = payload.get("errmsg", "")
        return f"ret={ret}, errcode={errcode}, errmsg={errmsg}"

    def _url(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        base = self.config.base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        if not params:
            return base
        return base + "?" + urlencode(params)

    def _headers(
        self,
        *,
        token_required: bool,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(
                str(random.getrandbits(32)).encode("utf-8")
            ).decode("utf-8"),
        }
        if token_required:
            if not self.token:
                raise OpenClawError("OpenClaw token is required")
            headers["Authorization"] = f"Bearer {self.token}"
        if extra:
            headers.update(extra)
        return headers
