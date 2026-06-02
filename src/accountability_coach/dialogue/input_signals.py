"""Non-text input signals for natural-language dialogue.

Emoji and stickers are not reliable task text.  In chat-based supervision they
usually function as affective cues, so the dialogue layer passes them as
structured side-channel signals instead of pretending they are ordinary words.
"""

from __future__ import annotations

import re
import string
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class InputSignal:
    """A non-text or para-text signal extracted from a user message."""

    kind: str
    source: str
    description: str
    emotion_tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    expression_only: bool = True
    raw: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    def memory_text(self) -> str:
        if self.emotion_tags:
            tags = "、".join(self.emotion_tags[:3])
            return f"发了一个表情，可能在表达 {tags}。"
        return "发了一个表情，情绪含义不明确。"


class EmojiEmotionInterpreter:
    """Infer light emotional context from emoji/sticker-only messages.

    The mapping is deliberately small and presentation-agnostic.  It should
    only create an emotional hint; downstream LLM routing still decides how to
    respond in context.
    """

    BRACKET_TAGS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
        (("哭", "流泪", "大哭", "泪", "委屈", "难过", "失望"), ("sad",), "难过或委屈"),
        (("困", "睡", "累", "裂开", "苦涩"), ("tired",), "疲惫"),
        (("捂脸", "尴尬", "汗", "破涕为笑"), ("embarrassed",), "尴尬或自嘲"),
        (("抓狂", "烦", "发怒", "怒", "崩溃"), ("frustrated",), "烦躁"),
        (("惊", "恐惧", "衰"), ("anxious",), "紧张或不安"),
        (("疑问", "发呆", "白眼"), ("ambiguous",), "拿不准或无语"),
        (("笑", "微笑", "呲牙", "偷笑", "耶", "强", "加油", "OK"), ("positive",), "轻松或认可"),
    )
    UNICODE_TAGS: dict[str, tuple[tuple[str, ...], str]] = {
        "😭": (("sad", "overwhelmed"), "难过或有点崩"),
        "😢": (("sad",), "难过"),
        "🥲": (("sad", "relieved"), "有点苦笑"),
        "🥺": (("sad", "anxious"), "委屈或不安"),
        "😞": (("sad",), "低落"),
        "😔": (("sad",), "低落"),
        "😫": (("overwhelmed", "tired"), "疲惫或撑不住"),
        "😩": (("overwhelmed", "tired"), "疲惫或烦"),
        "😵": (("overwhelmed",), "混乱或压力大"),
        "😴": (("tired",), "困"),
        "🥱": (("tired",), "困"),
        "😪": (("tired",), "困"),
        "😡": (("frustrated",), "烦躁"),
        "😠": (("frustrated",), "生气"),
        "🤬": (("frustrated",), "很烦"),
        "😅": (("embarrassed",), "尴尬或自嘲"),
        "🙃": (("embarrassed", "ambiguous"), "无奈或自嘲"),
        "😂": (("positive",), "笑"),
        "🤣": (("positive",), "笑"),
        "😊": (("positive",), "轻松"),
        "🙂": (("calm",), "平静"),
        "👍": (("positive", "motivated"), "认可"),
        "💪": (("motivated",), "打气"),
        "👌": (("positive",), "认可"),
        "❤️": (("positive",), "友好"),
        "❤": (("positive",), "友好"),
        "🤔": (("ambiguous",), "犹豫或思考"),
        "😐": (("ambiguous",), "无语或不确定"),
        "😶": (("ambiguous",), "说不出来"),
    }
    BRACKET_RE = re.compile(r"[\[【]([^\]】]{1,16})[\]】]")
    WECHAT_FACE_RE = re.compile(r"/:[-@A-Za-z0-9?)(]+")
    EMOJI_RANGES = (
        (0x1F000, 0x1FAFF),
        (0x2600, 0x27BF),
    )
    EMOJI_COMPONENTS = {"\ufe0f", "\u200d"}
    IGNORABLE = set(string.whitespace + string.punctuation + "，。！？、；：…~～·")

    def from_text(self, text: str) -> InputSignal | None:
        raw = text.strip()
        if not raw:
            return None
        tags, descriptions, token_count = self._infer(raw)
        if token_count == 0:
            return None
        expression_only = self._is_expression_only(raw)
        if not expression_only and not tags:
            return None
        return InputSignal(
            kind="emoji",
            source="text",
            raw=raw,
            description=self._description(tags, descriptions),
            emotion_tags=tags or ["ambiguous"],
            confidence=0.78 if expression_only else 0.45,
            expression_only=expression_only,
        )

    def from_media_item(
        self,
        *,
        source: str,
        label: str = "",
        raw: str = "",
    ) -> InputSignal:
        probe = label or raw
        tags, descriptions, _ = self._infer(probe)
        return InputSignal(
            kind="emoji",
            source=source,
            raw=raw or label,
            description=self._description(tags, descriptions),
            emotion_tags=tags or ["ambiguous"],
            confidence=0.55 if tags else 0.35,
            expression_only=True,
            metadata={"label": label} if label else {},
        )

    def _infer(self, raw: str) -> tuple[list[str], list[str], int]:
        tags: list[str] = []
        descriptions: list[str] = []
        token_count = 0
        for match in self.BRACKET_RE.finditer(raw):
            token_count += 1
            self._append_bracket_tags(match.group(1), tags, descriptions)
        for match in self.WECHAT_FACE_RE.finditer(raw):
            token_count += 1
            self._append_once(tags, "ambiguous")
            self._append_once(descriptions, "微信表情")
        for char in raw:
            if not self._is_emoji_char(char):
                continue
            if char in self.EMOJI_COMPONENTS:
                continue
            token_count += 1
            if char in self.UNICODE_TAGS:
                mapped_tags, description = self.UNICODE_TAGS[char]
                for tag in mapped_tags:
                    self._append_once(tags, tag)
                self._append_once(descriptions, description)
            else:
                self._append_once(tags, "ambiguous")
        return tags[:4], descriptions[:3], token_count

    def _append_bracket_tags(self, token: str, tags: list[str], descriptions: list[str]) -> None:
        for needles, mapped_tags, description in self.BRACKET_TAGS:
            if any(needle in token for needle in needles):
                for tag in mapped_tags:
                    self._append_once(tags, tag)
                self._append_once(descriptions, description)
                return
        self._append_once(tags, "ambiguous")

    def _is_expression_only(self, raw: str) -> bool:
        scrubbed = self.BRACKET_RE.sub("", raw)
        scrubbed = self.WECHAT_FACE_RE.sub("", scrubbed)
        kept: list[str] = []
        for char in scrubbed:
            if self._is_emoji_char(char) or char in self.EMOJI_COMPONENTS or char in self.IGNORABLE:
                continue
            kept.append(char)
        return not "".join(kept).strip()

    def _is_emoji_char(self, char: str) -> bool:
        codepoint = ord(char)
        return any(start <= codepoint <= end for start, end in self.EMOJI_RANGES)

    def _description(self, tags: list[str], descriptions: list[str]) -> str:
        if descriptions:
            return "用户发了一个表情，可能是在表达：" + "、".join(descriptions) + "。"
        if tags:
            return "用户发了一个表情，可能带有情绪。"
        return "用户发了一个表情，具体含义不明确。"

    def _append_once(self, items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)
