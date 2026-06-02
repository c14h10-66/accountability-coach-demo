"""Message codec helpers shared by single and multi-account OpenClaw adapters."""

from __future__ import annotations

import json
from typing import Any

from accountability_coach.dialogue.input_signals import EmojiEmotionInterpreter, InputSignal


class OpenClawMessageCodec:
    """Parse OpenClaw item lists and format short outbound text."""

    def __init__(self, input_signals: EmojiEmotionInterpreter | None = None) -> None:
        self.input_signals = input_signals or EmojiEmotionInterpreter()

    def text_from_item_list(self, item_list: object) -> str:
        text, _ = self.input_from_item_list(item_list)
        return text

    def input_from_item_list(self, item_list: object) -> tuple[str, InputSignal | None]:
        if not isinstance(item_list, list):
            return "", None
        parts: list[str] = []
        signal: InputSignal | None = None
        for item in item_list:
            if not isinstance(item, dict):
                continue
            item_type = int(item.get("type") or 0)
            if item_type == 1:
                text = str((item.get("text_item") or {}).get("text") or "").strip()
                if text:
                    parts.append(text)
                continue
            item_signal = self.signal_from_item(item)
            if item_signal is not None:
                signal = signal or item_signal
                continue
            if item_type == 2:
                parts.append("[图片]")
            elif item_type == 3:
                voice_text = str((item.get("voice_item") or {}).get("text") or "").strip()
                parts.append(voice_text or "[语音]")
            elif item_type == 4:
                parts.append("[文件]")
            elif item_type == 5:
                parts.append("[视频]")
        return "\n".join(parts).strip(), signal

    def signal_from_item(self, item: dict[str, Any]) -> InputSignal | None:
        item_type = int(item.get("type") or 0)
        key_text = " ".join(str(key).lower() for key in item.keys())
        is_expression_item = item_type in {6, 7, 8, 47} or any(
            marker in key_text
            for marker in ("emoji", "sticker", "face", "expression", "emotion")
        )
        if not is_expression_item:
            return None
        label = self._first_nested_text(
            item,
            preferred_keys={
                "name",
                "text",
                "desc",
                "description",
                "alt",
                "title",
                "emoji_name",
                "sticker_name",
                "face_name",
            },
        )
        raw = json.dumps(item, ensure_ascii=False)[:500]
        return self.input_signals.from_media_item(
            source="wechat_emoji",
            label=label,
            raw=raw,
        )

    def _first_nested_text(self, value: object, *, preferred_keys: set[str]) -> str:
        if isinstance(value, dict):
            for key in preferred_keys:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            for nested in value.values():
                found = self._first_nested_text(nested, preferred_keys=preferred_keys)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = self._first_nested_text(nested, preferred_keys=preferred_keys)
                if found:
                    return found
        return ""

    @staticmethod
    def split_outbound_text(text: str) -> list[str]:
        """Split short paragraph replies into separate WeChat messages."""
        cleaned = text.strip()
        if not cleaned:
            return []
        raw_parts = [
            part.strip()
            for part in cleaned.replace("\r\n", "\n").split("\n\n")
            if part.strip()
        ]
        if not raw_parts:
            raw_parts = [cleaned]
        parts: list[str] = []
        for part in raw_parts:
            if len(part) <= 480:
                parts.append(part)
                continue
            current = ""
            for line in [line.strip() for line in part.splitlines() if line.strip()]:
                if current and len(current) + len(line) + 1 > 480:
                    parts.append(current)
                    current = line
                else:
                    current = line if not current else current + "\n" + line
            if current:
                parts.append(current)
        return parts[:4]

    @staticmethod
    def natural_reminder_text(message: str) -> str:
        text = message.strip()
        if not text:
            return ""
        if any(marker in text for marker in ("该", "记得", "别忘", "提醒", "到了", "啦", "吧", "。", "！", "？")):
            return text
        return f"该{text}啦"
