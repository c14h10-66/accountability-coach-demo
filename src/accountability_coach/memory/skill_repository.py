"""File-backed repository for coach strategy SOPs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class FileSkillRepository:
    """Reads `SKILL.md` documents from a local skills directory."""

    def __init__(self, skills_root: str | Path) -> None:
        self.skills_root = Path(skills_root)

    def list_skills(self) -> Sequence[str]:
        if not self.skills_root.exists():
            return []
        names: list[str] = []
        for path in sorted(self.skills_root.rglob("SKILL.md")):
            names.append(str(path.parent.relative_to(self.skills_root)))
        return names

    def read_skill(self, skill_name: str) -> str:
        skill_path = self.skills_root / skill_name / "SKILL.md"
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        return skill_path.read_text(encoding="utf-8")
