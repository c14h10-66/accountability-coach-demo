"""Public-language guardrails for user-facing coach replies."""

from __future__ import annotations

import re


class PublicLanguageGuard:
    """Remove or soften internal operations language before a reply is shown.

    The dialogue layer can use internal ideas such as context, policy, cadence,
    and supervision modes, but those terms should not leak into ordinary chat.
    This guard is intentionally presentation-only; it does not route intents or
    change coaching state.
    """

    DROP_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\bpush_[A-Za-z0-9_-]+"),
        re.compile(r"(提醒任务已进入排程|内部策略|监督策略|policy|metadata|task_action_mode|response_register)"),
        re.compile(r"(状态|上下文|情绪|感受|信号|节奏).{0,8}接住|接住.{0,8}(状态|上下文|情绪|感受|信号|节奏)"),
        re.compile(r"上下文"),
        re.compile(r"(继续)?按.{0,24}(节奏|方向|策略|路径|模式)(走|来|推进|陪你|回答|接着走)?"),
        re.compile(r"先稳住状态"),
    )

    REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\s*\[表情包[:：].*?\]\s*"), ""),
        (re.compile(r"^(好[，,]\s*)?已(?:经)?(?:帮你|给你|为你)?(?:设好|设置好|安排好)提醒了[。,.，\s]*"), "好，"),
        (re.compile(r"已经帮你把"), "我先把"),
        (re.compile(r"已(?:经)?为你"), "我先"),
        (re.compile(r"已记录"), "记下了"),
        (re.compile(r"已(?:经)?(?:帮你)?记下(?:来)?了"), "记下了"),
        (re.compile(r"(\d+\s*(?:秒|分钟|小时)后)(?:我会|我到时会|到时我会|我)(?:提醒|叫)你[:：]?\s*"), r"\1叫你"),
        (re.compile(r"(?:我会|我到时会|到时我会)提醒你[:：]?\s*"), "到点叫你"),
        (re.compile(r"提醒你[:：]\s*"), "叫你"),
        (re.compile(r"你这句[话]?[“\"].+?[”\"]，?"), ""),
        (re.compile(r"很真实[:：]"), ""),
        (re.compile(r"先稳住状态"), "先缓一下"),
        (re.compile(r"状态回一点"), "舒服一点"),
        (re.compile(r"状态不合适"), "现在不太合适"),
        (re.compile(r"改节奏"), "换个安排"),
        (re.compile(r"恢复节奏"), "慢慢回来"),
        (re.compile(r"节奏"), "安排"),
    )

    def polish(self, reply: str) -> str:
        """Return text with internal jargon stripped from user-facing output."""
        public_lines: list[str] = []
        for raw_line in reply.splitlines():
            line = raw_line.strip()
            if not line:
                public_lines.append("")
                continue
            if self._should_drop(line):
                continue
            public_lines.append(self._soften(line))
        polished = "\n".join(public_lines)
        polished = re.sub(r"\n{3,}", "\n\n", polished)
        polished = re.sub(r"好[，,]\s*好[，,]", "好，", polished)
        polished = re.sub(r"叫你[:：]\s*", "叫你", polished)
        polished = re.sub(r"到点叫你[:：]\s*", "到点叫你", polished)
        return polished.strip()

    def _should_drop(self, line: str) -> bool:
        return any(pattern.search(line) for pattern in self.DROP_PATTERNS)

    def _soften(self, line: str) -> str:
        softened = line
        for pattern, replacement in self.REPLACEMENTS:
            softened = pattern.sub(replacement, softened)
        return softened
