"""JSON memory store for ACSP user state."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from accountability_coach.core.models import UserState, user_state_from_dict


class JsonUserStateStore:
    """Persist one JSON file per user under `base_dir/users`.

    This is the concrete shared memory used by the CentralCoordinator: task
    progress, check-ins, supervision preferences, emotional baseline, and
    knowledge sources are all saved atomically after each state transition.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.users_dir = self.base_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def load(self, user_id: str) -> UserState:
        path = self._path_for(user_id)
        if not path.exists():
            return UserState(user_id=user_id)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return UserState(user_id=user_id)
        data["user_id"] = data.get("user_id") or user_id
        return user_state_from_dict(data)

    def save(self, state: UserState) -> None:
        path = self._path_for(state.user_id)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(asdict(state), f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(path)

    def list_users(self) -> list[str]:
        return sorted(path.stem for path in self.users_dir.glob("*.json"))

    def _path_for(self, user_id: str) -> Path:
        safe_user_id = "".join(
            ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
            for ch in user_id
        )
        return self.users_dir / f"{safe_user_id}.json"
