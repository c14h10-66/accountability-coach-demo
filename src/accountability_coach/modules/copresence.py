"""Virtual co-presence and Pomodoro companion mode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from accountability_coach.core.models import (
    COPRESENCE_ACTIVE,
    COPRESENCE_INTERRUPTED,
    CoPresencePing,
    CoPresenceSession,
    UserState,
    iso_from_datetime,
    make_id,
    now_iso,
    parse_datetime,
)


class CoPresenceAgent:
    """AI version of synchronous tracking: lightweight virtual co-presence."""

    DISTRACTION_APPS = {"steam", "game", "netflix", "youtube", "bilibili", "douyin", "tiktok", "weibo"}

    def start_pomodoro_session(
        self,
        state: UserState,
        task_id: str,
        block_id: str | None = None,
        duration_minutes: int = 25,
        ping_interval_minutes: int = 5,
        authorized_screen_activity: bool = False,
        start_at: datetime | None = None,
    ) -> CoPresenceSession:
        start = start_at or datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=duration_minutes)
        pings: list[CoPresencePing] = []
        cursor = start + timedelta(minutes=ping_interval_minutes)
        while cursor < end:
            pings.append(
                CoPresencePing(
                    ping_id=make_id("ping"),
                    scheduled_at=iso_from_datetime(cursor),
                    message_hint="Still with me? One breath, then keep the next tiny step moving.",
                    response_required=False,
                    intervention_level="light",
                )
            )
            cursor += timedelta(minutes=ping_interval_minutes)
        session = CoPresenceSession(
            session_id=make_id("copresence"),
            task_id=task_id,
            block_id=block_id,
            started_at=iso_from_datetime(start),
            ends_at=iso_from_datetime(end),
            ping_interval_minutes=ping_interval_minutes,
            authorized_screen_activity=authorized_screen_activity,
            pings=pings,
        )
        state.copresence_sessions.append(session)
        state.updated_at = now_iso()
        return session

    def due_pings(
        self,
        state: UserState,
        now: datetime | None = None,
    ) -> list[CoPresencePing]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        due: list[CoPresencePing] = []
        for session in state.copresence_sessions:
            if session.status != COPRESENCE_ACTIVE:
                continue
            for ping in session.pings:
                scheduled = parse_datetime(ping.scheduled_at)
                if scheduled and ping.responded_at is None and scheduled <= now:
                    due.append(ping)
        return due

    def record_activity_sample(
        self,
        state: UserState,
        session_id: str,
        activity_app: str,
        window_title: str,
        observed_at: str | None = None,
    ) -> CoPresenceSession | None:
        session = self._find_session(state, session_id)
        if not session:
            return None
        sample = {
            "observed_at": observed_at or now_iso(),
            "activity_app": activity_app,
            "window_title": window_title,
        }
        session.activity_log.append(sample)
        if session.authorized_screen_activity and self._is_distracting(activity_app, window_title):
            session.pings.append(
                CoPresencePing(
                    ping_id=make_id("ping"),
                    scheduled_at=sample["observed_at"],
                    message_hint="Looks like you may have drifted from the study task. Close or park it, then tell me the next 2-minute action.",
                    response_required=True,
                    intervention_level="redirect",
                    observed_activity=f"{activity_app} {window_title}".strip(),
                    flags=["possible_distraction"],
                )
            )
        state.updated_at = now_iso()
        return session

    def complete_session(self, state: UserState, session_id: str, interrupted: bool = False) -> CoPresenceSession | None:
        session = self._find_session(state, session_id)
        if not session:
            return None
        session.status = COPRESENCE_INTERRUPTED if interrupted else "completed"
        state.updated_at = now_iso()
        return session

    def _find_session(self, state: UserState, session_id: str) -> CoPresenceSession | None:
        for session in state.copresence_sessions:
            if session.session_id == session_id:
                return session
        return None

    def _is_distracting(self, activity_app: str, window_title: str) -> bool:
        haystack = f"{activity_app} {window_title}".lower()
        return any(term in haystack for term in self.DISTRACTION_APPS)
