from __future__ import annotations

import json
from typing import Any

from axon.agents.base import BaseAgent
from axon.agents.prod.schemas import ProdOutput
from axon.core.events import Event
from axon.core.results import AgentResult


class ProdAgent(BaseAgent):
    """Placeholder Prod agent — production release is gated pending human approvals."""

    @property
    def name(self) -> str:
        return "prod"

    @property
    def role(self) -> str:
        return "Prod Agent — production release gate (human approval required)"

    def run(self, event: Event) -> AgentResult:
        self._check_permissions()
        output = ProdOutput()
        refs = [
            self._artifact_store.save(
                event.workflow_id, "prod", "prod_release_gate.json",
                json.dumps(output.model_dump(), indent=2),
            )
        ]
        return AgentResult(
            status="success",
            output_artifacts=refs,
            next_event="prod.gated",
            human_approval_required=True,
        )

    # Abstract method stubs — never called since run() is overridden
    def load_context(self, event: Event) -> dict[str, Any]: return {}
    def build_prompt(self, context: dict[str, Any]) -> str: return ""
    def validate_response(self, raw: str) -> dict[str, Any]: return {}
    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list: return []
    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str: return ""
