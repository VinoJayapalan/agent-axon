from __future__ import annotations

from axon.agents.base import BaseAgent
from axon.core.workflow import WorkflowStatus

# Maps workflow status to the agent name responsible for that phase
STATUS_TO_AGENT: dict[WorkflowStatus, str] = {
    WorkflowStatus.PO_IN_PROGRESS:  "po",
    WorkflowStatus.SM_IN_PROGRESS:  "sm",
    WorkflowStatus.DEV_IN_PROGRESS: "dev",
    WorkflowStatus.QA_IN_PROGRESS:  "qa",
    WorkflowStatus.APPROVED:        "devops",
}


class AgentRouter:
    """Routes workflow states to agent instances."""

    def __init__(self, agents: dict[str, BaseAgent]) -> None:
        self._agents = agents

    def get_agent(self, status: WorkflowStatus) -> BaseAgent | None:
        name = STATUS_TO_AGENT.get(status)
        return self._agents.get(name) if name else None

    def get_agent_by_name(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)
