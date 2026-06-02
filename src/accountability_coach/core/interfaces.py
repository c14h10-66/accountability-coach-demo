"""Small protocols for replaceable storage and skill repositories."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from accountability_coach.core.models import UserState


class UserStateStore(Protocol):
    """Persistence boundary for ACSP user state."""

    def load(self, user_id: str) -> UserState:
        """Load an existing user state or return defaults."""

    def save(self, state: UserState) -> None:
        """Persist a state snapshot."""

    def list_users(self) -> list[str]:
        """List known user ids."""


class SkillRepository(Protocol):
    """Read-only access to procedural coach strategy documents."""

    def list_skills(self) -> Sequence[str]:
        """List available skill identifiers."""

    def read_skill(self, skill_name: str) -> str:
        """Return a skill document."""
