from __future__ import annotations

from axon.core.errors import WorkflowTransitionError
from axon.core.workflow import WorkflowStatus

# (current_status, event_type) -> next_status
TRANSITIONS: dict[tuple[WorkflowStatus, str], WorkflowStatus] = {
    (WorkflowStatus.REQUEST_RECEIVED,       "start"):               WorkflowStatus.PO_IN_PROGRESS,
    (WorkflowStatus.PO_IN_PROGRESS,         "po.success"):          WorkflowStatus.PO_COMPLETED,
    (WorkflowStatus.PO_IN_PROGRESS,         "po.ambiguous"):        WorkflowStatus.PO_AMBIGUOUS,
    (WorkflowStatus.PO_IN_PROGRESS,         "po.failed"):           WorkflowStatus.FAILED,
    (WorkflowStatus.PO_AMBIGUOUS,           "human.approve"):       WorkflowStatus.SM_IN_PROGRESS,
    (WorkflowStatus.PO_AMBIGUOUS,           "human.reject"):        WorkflowStatus.FAILED,
    (WorkflowStatus.PO_COMPLETED,           "sm.start"):            WorkflowStatus.SM_IN_PROGRESS,
    (WorkflowStatus.SM_IN_PROGRESS,         "sm.success"):          WorkflowStatus.SM_COMPLETED,
    (WorkflowStatus.SM_IN_PROGRESS,         "sm.failed"):           WorkflowStatus.HUMAN_APPROVAL_REQUIRED,
    (WorkflowStatus.SM_COMPLETED,           "dev.start"):           WorkflowStatus.DEV_IN_PROGRESS,
    (WorkflowStatus.DEV_IN_PROGRESS,        "dev.success"):         WorkflowStatus.DEV_COMPLETED,
    (WorkflowStatus.DEV_IN_PROGRESS,        "dev.failed"):          WorkflowStatus.BUILD_FAILED,
    (WorkflowStatus.BUILD_FAILED,           "*"):                   WorkflowStatus.HUMAN_APPROVAL_REQUIRED,
    (WorkflowStatus.DEV_COMPLETED,          "dev.start"):           WorkflowStatus.DEV_IN_PROGRESS,
    (WorkflowStatus.DEV_COMPLETED,          "dev.all_tasks_complete"): WorkflowStatus.QA_IN_PROGRESS,
    (WorkflowStatus.QA_IN_PROGRESS,         "qa.success"):          WorkflowStatus.QA_COMPLETED,
    (WorkflowStatus.QA_IN_PROGRESS,         "qa.failed"):           WorkflowStatus.QA_FAILED,
    (WorkflowStatus.QA_FAILED,              "sm.start"):            WorkflowStatus.SM_IN_PROGRESS,
    (WorkflowStatus.QA_FAILED,              "*"):                   WorkflowStatus.HUMAN_APPROVAL_REQUIRED,
    (WorkflowStatus.QA_COMPLETED,           "*"):                   WorkflowStatus.HUMAN_APPROVAL_REQUIRED,
    (WorkflowStatus.HUMAN_APPROVAL_REQUIRED, "human.approve"):      WorkflowStatus.APPROVED,
    (WorkflowStatus.HUMAN_APPROVAL_REQUIRED, "human.reject"):       WorkflowStatus.REJECTED,
    (WorkflowStatus.APPROVED,               "*"):                   WorkflowStatus.DONE,
    (WorkflowStatus.REJECTED,               "*"):                   WorkflowStatus.FAILED,
}


class StateMachine:
    """Deterministic workflow state machine.

    Looks up (current_status, event_type) in TRANSITIONS.
    Falls back to (current_status, "*") wildcard when no exact match.
    """

    def transition(self, current: WorkflowStatus, event_type: str) -> WorkflowStatus:
        key = (current, event_type)
        if key in TRANSITIONS:
            return TRANSITIONS[key]
        wildcard = (current, "*")
        if wildcard in TRANSITIONS:
            return TRANSITIONS[wildcard]
        raise WorkflowTransitionError(
            f"No transition from '{current.value}' on event '{event_type}'"
        )
