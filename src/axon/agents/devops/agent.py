from __future__ import annotations

import json
from typing import Any

from axon.agents.base import BaseAgent
from axon.agents.devops.schemas import DevOpsOutput
from axon.core.events import Event
from axon.core.results import AgentResult


class DevOpsAgent(BaseAgent):
    """Placeholder DevOps agent — production deployment is disabled."""

    @property
    def name(self) -> str:
        return "devops"

    @property
    def role(self) -> str:
        return "DevOps Agent — deployment readiness assessment (production gated)"

    def run(self, event: Event) -> AgentResult:
        self._check_permissions()
        output = DevOpsOutput(
            deployment_readiness_checklist=[
                "All QA tests passing: PENDING",
                "Security scan completed: PENDING",
                "Staging environment validated: PENDING",
                "Change Advisory Board approval: PENDING",
            ]
        )
        refs = [
            self._artifact_store.save(
                event.workflow_id, "devops", "devops_assessment.json",
                json.dumps(output.model_dump(), indent=2),
            )
        ]
        return AgentResult(
            status="success",
            output_artifacts=refs,
            next_event="devops.assessment_complete",
            human_approval_required=True,
        )

    # Abstract method stubs — never called since run() is overridden
    def load_context(self, event: Event) -> dict[str, Any]: return {}
    def build_prompt(self, context: dict[str, Any]) -> str: return ""
    def validate_response(self, raw: str) -> dict[str, Any]: return {}
    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list: return []
    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str: return ""
