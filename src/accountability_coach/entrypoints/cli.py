"""Small CLI wrapper around CentralCoordinator."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from accountability_coach import CentralCoordinator


def main() -> int:
    parser = argparse.ArgumentParser(prog="accountability-coach")
    parser.add_argument("--memory-dir", default=".accountability_coach_memory")
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser("configure")
    configure.add_argument("user_id")
    configure.add_argument("--style", default="gentle")
    configure.add_argument("--intensity", default="moderate")
    configure.add_argument("--goal", action="append", default=[])
    configure.add_argument("--major", default="")
    configure.add_argument("--background", default="")

    add_task = sub.add_parser("add-task")
    add_task.add_argument("user_id")
    add_task.add_argument("title")
    add_task.add_argument("--task-id", default="")
    add_task.add_argument("--priority", default="medium")
    add_task.add_argument("--importance", type=int, default=3)
    add_task.add_argument("--minutes", type=int, default=50)
    add_task.add_argument("--deadline", default=None)
    add_task.add_argument("--tag", action="append", default=[])

    plan = sub.add_parser("plan")
    plan.add_argument("user_id")
    plan.add_argument("--available-minutes", type=int, default=None)

    checkin = sub.add_parser("checkin")
    checkin.add_argument("user_id")
    checkin.add_argument("task_id")
    checkin.add_argument("--block-id", default=None)
    checkin.add_argument("--status", default="completed")
    checkin.add_argument("--progress", type=int, default=100)
    checkin.add_argument("--note", default="")
    checkin.add_argument("--emotion", action="append", default=[])

    status = sub.add_parser("status")
    status.add_argument("user_id")

    onboarding = sub.add_parser("onboarding")
    onboarding.add_argument("user_id")

    risk = sub.add_parser("risk")
    risk.add_argument("user_id")
    risk.add_argument("text")

    dialogue = sub.add_parser("dialogue")
    dialogue.add_argument("user_id")
    dialogue.add_argument("text")

    resources = sub.add_parser("resources")
    resources.add_argument("user_id")
    resources.add_argument("--task-id", default=None)
    resources.add_argument("--query", default="")

    review = sub.add_parser("review")
    review.add_argument("user_id")
    review.add_argument("--period", default="weekly")

    commit = sub.add_parser("commit")
    commit.add_argument("user_id")
    commit.add_argument("task_id")
    commit.add_argument("text")
    commit.add_argument("--due-at", default=None)
    commit.add_argument("--penalty", default="")

    copresence = sub.add_parser("copresence")
    copresence.add_argument("user_id")
    copresence.add_argument("task_id")
    copresence.add_argument("--duration-minutes", type=int, default=25)
    copresence.add_argument("--ping-interval-minutes", type=int, default=5)
    copresence.add_argument("--authorized-screen-activity", action="store_true")

    activity = sub.add_parser("activity")
    activity.add_argument("user_id")
    activity.add_argument("session_id")
    activity.add_argument("activity_app")
    activity.add_argument("window_title")

    args = parser.parse_args()
    coach = CentralCoordinator(memory_dir=Path(args.memory_dir))

    if args.command == "configure":
        result = coach.configure_supervision(
            args.user_id,
            {
                "style": args.style,
                "intensity": args.intensity,
                "goals": args.goal,
                "major": args.major,
                "academic_background": args.background,
            },
        )
        _print_json(asdict(result))
    elif args.command == "add-task":
        result = coach.add_or_update_task(
            args.user_id,
            {
                "task_id": args.task_id,
                "title": args.title,
                "priority": args.priority,
                "importance": args.importance,
                "estimated_minutes": args.minutes,
                "deadline": args.deadline,
                "tags": args.tag,
            },
        )
        _print_json(asdict(result))
    elif args.command == "plan":
        options = {}
        if args.available_minutes is not None:
            options["available_minutes"] = args.available_minutes
        result = coach.plan_schedule(args.user_id, options)
        _print_json(asdict(result))
    elif args.command == "checkin":
        result = coach.record_checkin(
            args.user_id,
            {
                "task_id": args.task_id,
                "block_id": args.block_id,
                "status": args.status,
                "progress_percent": args.progress,
                "note": args.note,
                "emotion_tags": args.emotion,
            },
        )
        _print_json(result)
    elif args.command == "status":
        _print_json(coach.query_status(args.user_id))
    elif args.command == "onboarding":
        _print_json(coach.start_onboarding(args.user_id))
    elif args.command == "risk":
        _print_json(coach.assess_risk(args.user_id, args.text))
    elif args.command == "dialogue":
        _print_json(coach.get_emotional_dialogue(args.user_id, args.text))
    elif args.command == "resources":
        _print_json(coach.suggest_resources(args.user_id, args.task_id, args.query))
    elif args.command == "review":
        _print_json(coach.generate_progress_review(args.user_id, args.period))
    elif args.command == "commit":
        _print_json(
            coach.create_commitment(
                args.user_id,
                args.task_id,
                args.text,
                due_at=args.due_at,
                penalty=args.penalty,
            )
        )
    elif args.command == "copresence":
        _print_json(
            coach.start_copresence_session(
                args.user_id,
                args.task_id,
                {
                    "duration_minutes": args.duration_minutes,
                    "ping_interval_minutes": args.ping_interval_minutes,
                    "authorized_screen_activity": args.authorized_screen_activity,
                },
            )
        )
    elif args.command == "activity":
        _print_json(
            coach.record_screen_activity(
                args.user_id,
                args.session_id,
                args.activity_app,
                args.window_title,
            )
        )
    return 0


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
