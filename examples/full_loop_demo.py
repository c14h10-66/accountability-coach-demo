"""Demonstrate one ACSP loop without any web or messaging framework."""

from __future__ import annotations

from pprint import pprint
import tempfile
from pathlib import Path

from accountability_coach import CentralCoordinator


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        coach = CentralCoordinator(memory_dir=Path(tmp))
        user_id = "demo_user"

        coach.configure_supervision(
            user_id,
            {
                "style": "gentle",
                "intensity": "moderate",
                "goals": ["finish the literature review"],
                "academic_background": "graduate student preparing thesis",
                "major": "HCI",
            },
        )
        coach.add_or_update_task(
            user_id,
            {
                "task_id": "lit_review",
                "title": "Draft literature review outline",
                "priority": "urgent",
                "importance": 5,
                "estimated_minutes": 90,
                "tags": ["writing", "thesis"],
            },
        )
        planned = coach.plan_schedule(user_id)
        first_block = planned.schedule[0]
        result = coach.record_checkin(
            user_id,
            {
                "task_id": first_block.task_id,
                "block_id": first_block.block_id,
                "status": "partial",
                "progress_percent": 45,
                "focus_minutes": 15,
                "note": "I started but got tired and unsure how to structure the sources.",
                "emotion_tags": ["tired"],
            },
        )
        pprint(
            {
                "guidance_plan": result["guidance_plan"],
                "emotional_adjustment": result["emotional_adjustment"],
                "status": coach.query_status(user_id),
            }
        )


if __name__ == "__main__":
    main()
