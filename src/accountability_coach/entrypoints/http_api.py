"""Tiny stdlib HTTP API for manual ACSP loop testing."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from accountability_coach import CentralCoordinator
from accountability_coach.dialogue import DialogueAgent


def make_handler(coach: CentralCoordinator, dialogue: DialogueAgent | None = None):
    dialogue = dialogue or DialogueAgent(coach)

    class CoachHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            user_id = query.get("user_id", [""])[0]
            if parsed.path == "/status" and user_id:
                self._send(200, coach.query_status(user_id))
                return
            if parsed.path == "/pushes/due" and user_id:
                self._send(200, {"pushes": coach.pop_due_pushes(user_id)})
                return
            if parsed.path == "/proactive/suggestions" and user_id:
                self._send(200, coach.get_proactive_suggestions(user_id))
                return
            self._send(404, {"error": "unknown endpoint"})

        def do_POST(self) -> None:  # noqa: N802
            payload = self._read_json()
            user_id = str(payload.get("user_id", ""))
            if not user_id:
                self._send(400, {"error": "user_id is required"})
                return
            if self.path == "/configure":
                self._send(200, asdict(coach.configure_supervision(user_id, payload.get("config", payload))))
            elif self.path == "/chat":
                self._send(200, asdict(dialogue.respond(user_id, str(payload.get("text", "")))))
            elif self.path == "/tasks":
                self._send(200, asdict(coach.add_or_update_task(user_id, payload.get("task", payload))))
            elif self.path == "/plan":
                self._send(200, asdict(coach.plan_schedule(user_id, payload)))
            elif self.path == "/checkins":
                self._send(200, coach.record_checkin(user_id, payload.get("checkin", payload)))
            elif self.path == "/knowledge_sources":
                self._send(200, asdict(coach.register_knowledge_source(user_id, payload.get("source", payload))))
            elif self.path == "/onboarding/start":
                self._send(200, coach.start_onboarding(user_id))
            elif self.path == "/onboarding/response":
                self._send(200, coach.record_onboarding_response(user_id, payload))
            elif self.path == "/risk":
                self._send(200, coach.assess_risk(user_id, str(payload.get("text", ""))))
            elif self.path == "/emotional_dialogue":
                self._send(200, coach.get_emotional_dialogue(user_id, str(payload.get("text", ""))))
            elif self.path == "/resources":
                self._send(
                    200,
                    coach.suggest_resources(
                        user_id,
                        payload.get("task_id"),
                        str(payload.get("query", "")),
                    ),
                )
            elif self.path == "/reviews":
                self._send(200, coach.generate_progress_review(user_id, str(payload.get("period", "weekly"))))
            elif self.path == "/commitments":
                self._send(
                    200,
                    coach.create_commitment(
                        user_id,
                        str(payload.get("task_id", "")),
                        str(payload.get("text", "")),
                        due_at=payload.get("due_at"),
                        penalty=str(payload.get("penalty", "")),
                    ),
                )
            elif self.path == "/copresence/start":
                self._send(
                    200,
                    coach.start_copresence_session(
                        user_id,
                        str(payload.get("task_id", "")),
                        payload,
                    ),
                )
            elif self.path == "/break_reminders":
                self._send(
                    200,
                    coach.schedule_break_reminders(
                        user_id,
                        interval_minutes=int(payload.get("interval_minutes", 45) or 45),
                        duration_minutes=(
                            int(payload["duration_minutes"])
                            if payload.get("duration_minutes") not in (None, "")
                            else None
                        ),
                        start_at=payload.get("start_at"),
                        message=str(payload.get("message") or "到休息点了，站起来喝口水，活动一下再继续。"),
                    ),
                )
            elif self.path == "/copresence/activity":
                self._send(
                    200,
                    coach.record_screen_activity(
                        user_id,
                        str(payload.get("session_id", "")),
                        str(payload.get("activity_app", "")),
                        str(payload.get("window_title", "")),
                    ),
                )
            else:
                self._send(404, {"error": "unknown endpoint"})

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return CoachHandler


def main() -> int:
    parser = argparse.ArgumentParser(prog="accountability-coach-http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--memory-dir", default=".accountability_coach_memory")
    args = parser.parse_args()

    coach = CentralCoordinator(memory_dir=Path(args.memory_dir))
    server = HTTPServer((args.host, args.port), make_handler(coach, DialogueAgent(coach)))
    print(f"Serving accountability coach API on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
