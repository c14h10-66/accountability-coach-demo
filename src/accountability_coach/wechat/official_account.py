"""WeChat Official Account webhook adapter.

This module implements the public-account server callback contract:
GET verifies the URL with token/timestamp/nonce/signature/echostr, and POST
receives XML text messages and returns XML text replies.
"""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from accountability_coach.core.coordinator import CentralCoordinator
from accountability_coach.dialogue import DialogueAgent


MAX_WECHAT_BODY_BYTES = 64 * 1024


def verify_wechat_signature(
    token: str,
    signature: str,
    timestamp: str,
    nonce: str,
) -> bool:
    """Verify WeChat callback signature using SHA1(sorted(token,timestamp,nonce))."""
    pieces = sorted([token, timestamp, nonce])
    digest = hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()
    return digest == signature


@dataclass(slots=True)
class WeChatMessage:
    to_user: str
    from_user: str
    msg_type: str
    content: str = ""
    msg_id: str = ""


class WeChatOfficialAccountHandler:
    """Convert WeChat XML messages into the natural-language dialogue layer."""

    def __init__(
        self,
        coordinator: CentralCoordinator,
        dialogue: DialogueAgent | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.dialogue = dialogue or DialogueAgent(coordinator)

    def handle_xml(self, xml_body: bytes) -> bytes:
        if len(xml_body) > MAX_WECHAT_BODY_BYTES:
            return b"success"
        message = self._parse_message(xml_body)
        if not message:
            return b"success"
        if message.msg_type != "text":
            reply = "现在先支持文字。你可以直接说：写论文吧、我卡住了、30 分钟后提醒我，或者发“帮助”。"
        else:
            reply = self._route_text(message.from_user, message.content)
        return self._text_reply(
            to_user=message.from_user,
            from_user=message.to_user,
            content=reply,
        )

    def _route_text(self, user_id: str, text: str) -> str:
        command = text.strip()
        if not command or command.lower() in {"帮助", "help", "/help"}:
            return self._help_text()
        if command in {"开始", "/start"}:
            return self.dialogue.opening(user_id)
        turn = self.dialogue.respond(user_id, command)
        return turn.reply

    def _parse_message(self, xml_body: bytes) -> WeChatMessage | None:
        try:
            root = ET.fromstring(xml_body)
        except ET.ParseError:
            return None
        get = lambda name: (root.findtext(name) or "").strip()
        return WeChatMessage(
            to_user=get("ToUserName"),
            from_user=get("FromUserName"),
            msg_type=get("MsgType"),
            content=get("Content"),
            msg_id=get("MsgId"),
        )

    def _text_reply(self, to_user: str, from_user: str, content: str) -> bytes:
        safe = content[:1800].replace("]]>", "]]]]><![CDATA[>")
        xml = (
            "<xml>"
            f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{safe}]]></Content>"
            "</xml>"
        )
        return xml.encode("utf-8")

    def _help_text(self) -> str:
        return (
            "你可以直接自然语言和我说：\n"
            "写论文吧\n"
            "今晚饭后看会书\n"
            "我只写了两句，卡住了\n"
            "30 分钟后提醒我喝水\n"
            "状态 / 周报 / 重置 / 退出"
        )
