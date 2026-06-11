from axon.core.results import AgentResult


class ApprovalPolicy:
    """Determines whether a workflow step requires human approval before proceeding."""

    @staticmethod
    def requires_human(result: AgentResult) -> bool:
        return result.human_approval_required or result.status in ("failed", "ambiguous")
