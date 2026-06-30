from __future__ import annotations

from src.literature_review.models import WorkflowStage


class InvalidTransitionError(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[WorkflowStage, frozenset[WorkflowStage]] = {
    WorkflowStage.CREATED: frozenset({WorkflowStage.PLANNING}),
    WorkflowStage.PLANNING: frozenset(
        {WorkflowStage.DISCOVERING, WorkflowStage.DRAFTING}
    ),
    WorkflowStage.DISCOVERING: frozenset({WorkflowStage.SCREENING}),
    WorkflowStage.SCREENING: frozenset(
        {WorkflowStage.AWAITING_CORPUS_APPROVAL}
    ),
    WorkflowStage.AWAITING_CORPUS_APPROVAL: frozenset(
        {WorkflowStage.DRAFTING}
    ),
    WorkflowStage.DRAFTING: frozenset(
        {WorkflowStage.REVIEWING, WorkflowStage.COMPLETED}
    ),
    WorkflowStage.REVIEWING: frozenset(
        {WorkflowStage.REVISING, WorkflowStage.POLISHING}
    ),
    WorkflowStage.REVISING: frozenset({WorkflowStage.REVIEWING}),
    WorkflowStage.POLISHING: frozenset(
        {WorkflowStage.FINAL_VERIFICATION}
    ),
    WorkflowStage.FINAL_VERIFICATION: frozenset(
        {WorkflowStage.COMPLETED, WorkflowStage.REVISING}
    ),
    WorkflowStage.COMPLETED: frozenset(),
}


def can_transition(
    current: WorkflowStage,
    following: WorkflowStage,
) -> bool:
    return following in ALLOWED_TRANSITIONS[current]


def require_transition(
    current: WorkflowStage,
    following: WorkflowStage,
) -> None:
    if not can_transition(current, following):
        raise InvalidTransitionError(
            f"invalid workflow transition: {current.value} -> {following.value}"
        )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "InvalidTransitionError",
    "can_transition",
    "require_transition",
]
