"""ICBT-informed dialogue moves for procrastination coaching.

This module does not provide therapy.  It operationalizes common internet CBT
patterns as structured coaching moves: normalize, identify thoughts, reframe,
choose graded behavior, and preserve escalation boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from accountability_coach.core.models import CHECKIN_SKIPPED, UserState


@dataclass(slots=True)
class ICBTFormulation:
    """A compact ICBT-style formulation for one dialogue turn."""

    concern: str
    distortions: list[str] = field(default_factory=list)
    response_moves: list[str] = field(default_factory=list)
    micro_action: str = ""
    shared_responsibility: bool = False
    escalation_boundary: str = ""


class ICBTDialoguePlaybook:
    """Generate safe, structured dialogue moves for academic procrastination."""

    DISTORTIONS = {
        "all_or_nothing": ("永远", "从来", "完全", "全都", "一事无成", "never", "always", "everything"),
        "catastrophizing": ("完了", "毁了", "来不及", "没救", "灾难", "ruined", "disaster"),
        "self_labeling": ("废物", "垃圾", "失败者", "我太差", "没用", "failure", "useless"),
        "should_statement": ("应该", "必须", "早该", "should", "must"),
        "mind_reading": ("别人肯定", "老师肯定", "一定觉得", "they must think"),
    }

    def formulate(self, state: UserState, text: str) -> ICBTFormulation:
        lowered = text.lower()
        distortions = [
            label
            for label, terms in self.DISTORTIONS.items()
            if any(term in lowered for term in terms)
        ]
        recent_skips = sum(1 for item in state.checkins[-5:] if item.status == CHECKIN_SKIPPED)
        distress = state.emotion.distress_detected or state.emotion.morale <= 0.35
        concern = self._concern(text)
        response_moves = ["empathic_reflection", "validation"]
        if recent_skips >= 2:
            response_moves.append("shared_responsibility")
        if distortions:
            response_moves.append("cognitive_reframing")
        response_moves.append("graded_behavioral_activation")
        if distress:
            response_moves.insert(0, "pressure_downshift")
        return ICBTFormulation(
            concern=concern,
            distortions=distortions,
            response_moves=response_moves,
            micro_action=self._micro_action(state),
            shared_responsibility=recent_skips >= 2,
            escalation_boundary=(
                "如果出现自伤念头、持续失眠崩溃或无法保证安全，普通监督要暂停，优先联系真人和专业支持。"
            ),
        )

    def render(self, formulation: ICBTFormulation) -> str:
        """Render a concise Chinese response when no LLM is available."""
        lines = [
            f"我听到了：{formulation.concern}",
            "这不是给你下结论，我们只是先把事情说清楚一点。",
        ]
        if formulation.shared_responsibility:
            lines.append("如果连续没启动，计划也要承担一部分责任：可能太大、太糊，或者放在了错误时间。")
        if formulation.distortions:
            lines.append("先做一个 ICBT 小重构：把自动想法写成一句话，再找一个更平衡的替代表述。")
        lines.append(f"现在只做一个微动作：{formulation.micro_action}")
        return "\n".join(lines)

    def _concern(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return "你现在有点卡住，但还没说清楚卡点。"
        return stripped[:80]

    def _micro_action(self, state: UserState) -> str:
        active = [task for task in state.tasks if task.status != "completed"]
        if not active:
            return "说出今天最想推进的一件学业任务。"
        return f"打开「{active[-1].title}」相关材料，只做 10 分钟，并在结束后发一句打卡。"
