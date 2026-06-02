"""Structured reminder scheduling helpers.

The LLM dialogue layer is responsible for understanding user language.  This
module only turns structured tool arguments into persisted reminder requests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class ReminderRequest:
    """A parsed user request for a future reminder."""

    message: str
    due_at: str
    delay_seconds: int

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


class ReminderScheduler:
    """Build reminder requests from LLM-routed structured payloads."""

    def build_request(
        self,
        message: str,
        *,
        due_at: str | None = None,
        delay_seconds: int | None = None,
        now: datetime | None = None,
    ) -> ReminderRequest:
        message = self.clean_message(message)
        if due_at:
            parsed_due_at = self._normalize_due_at(due_at)
            delay = self._seconds_until(parsed_due_at, now or datetime.now(timezone.utc))
            return ReminderRequest(message=message, due_at=parsed_due_at, delay_seconds=delay)
        if delay_seconds is None:
            raise ValueError("Reminder payload requires due_at or delay_seconds")
        delay = max(1, int(delay_seconds))
        current = now or datetime.now(timezone.utc)
        parsed_due_at = (current + timedelta(seconds=delay)).replace(microsecond=0).isoformat()
        return ReminderRequest(
            message=message,
            due_at=parsed_due_at,
            delay_seconds=delay,
        )

    def clean_message(self, text: str) -> str:
        cleaned = str(text).strip(" \t\n\r，。,.")
        return cleaned or "回来打卡"

    def human_due_at(self, value: str) -> str:
        try:
            due = datetime.fromisoformat(value)
        except ValueError:
            return value
        return due.astimezone().strftime("%H:%M:%S")

    def _normalize_due_at(self, value: str) -> str:
        try:
            due = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_at must be an ISO-8601 datetime") from exc
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return due.replace(microsecond=0).isoformat()

    def _seconds_until(self, due_at: str, now: datetime) -> int:
        due = datetime.fromisoformat(due_at)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return max(1, int((due - now).total_seconds()))
