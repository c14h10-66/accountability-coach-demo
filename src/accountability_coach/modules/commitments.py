"""Executable pre-commitment contracts."""

from __future__ import annotations

from accountability_coach.core.models import (
    CHECKIN_COMPLETED,
    CHECKIN_PARTIAL,
    CHECKIN_SKIPPED,
    COMMITMENT_ACTIVE,
    COMMITMENT_BREACHED,
    COMMITMENT_FULFILLED,
    CommitmentSuggestion,
    UserState,
    make_id,
    now_iso,
    parse_datetime,
)


class CommitmentContractManager:
    """Make loss-aversion commitments explicit and evaluate them from DaKa."""

    def create_contract(
        self,
        state: UserState,
        task_id: str,
        text: str,
        due_at: str | None = None,
        penalty: str = "",
        proof_required: str = "DaKa check-in",
    ) -> CommitmentSuggestion:
        contract = CommitmentSuggestion(
            commitment_id=make_id("commitment"),
            task_id=task_id,
            text=text,
            penalty=penalty or "Choose a small, safe, non-shaming consequence before the next block.",
            status=COMMITMENT_ACTIVE,
            due_at=due_at,
            proof_required=proof_required,
            stake_description=penalty,
            activation_condition="accepted_by_user",
        )
        state.commitments.append(contract)
        state.updated_at = now_iso()
        return contract

    def activate_suggestions(self, state: UserState) -> list[CommitmentSuggestion]:
        activated: list[CommitmentSuggestion] = []
        for commitment in state.commitments:
            if commitment.status == "proposed":
                commitment.status = COMMITMENT_ACTIVE
                activated.append(commitment)
        if activated:
            state.updated_at = now_iso()
        return activated

    def evaluate_from_latest_checkin(self, state: UserState) -> list[CommitmentSuggestion]:
        if not state.checkins:
            return []
        checkin = state.checkins[-1]
        changed: list[CommitmentSuggestion] = []
        for commitment in state.commitments:
            if commitment.status != COMMITMENT_ACTIVE:
                continue
            if commitment.task_id and commitment.task_id != checkin.task_id:
                continue
            if checkin.status == CHECKIN_COMPLETED or (
                checkin.status == CHECKIN_PARTIAL and checkin.progress_percent >= 60
            ):
                commitment.status = COMMITMENT_FULFILLED
                commitment.fulfilled_at = checkin.created_at
                changed.append(commitment)
            elif checkin.status == CHECKIN_SKIPPED and not checkin.justified_delay:
                commitment.status = COMMITMENT_BREACHED
                commitment.breached_at = checkin.created_at
                changed.append(commitment)
            elif commitment.due_at and self._is_overdue(commitment.due_at, checkin.created_at):
                commitment.status = COMMITMENT_BREACHED
                commitment.breached_at = checkin.created_at
                changed.append(commitment)
        if changed:
            state.updated_at = now_iso()
        return changed

    def _is_overdue(self, due_at: str, at: str) -> bool:
        due = parse_datetime(due_at)
        current = parse_datetime(at)
        return bool(due and current and current > due)
