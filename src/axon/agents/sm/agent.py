from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axon.agents.base import BaseAgent
from axon.agents.sm.prompts import SM_SYSTEM
from axon.agents.sm.schemas import SMOutput, Task
from axon.config.settings import settings
from axon.core.errors import LLMValidationError
from axon.core.events import Event
from axon.tools.shell_executor import ShellExecutor


class ScrumMasterAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "sm"

    @property
    def role(self) -> str:
        return "Scrum Master — sprint planning simulation, DoR check, execution plan"

    def load_context(self, event: Event) -> dict[str, Any]:
        wf = event.workflow_id
        base = settings.artifacts_base_path

        user_stories = self._load_json(base, wf, "po", "user_stories.json") or []
        acceptance_criteria = self._load_json(base, wf, "po", "acceptance_criteria.json") or []
        defect_report = self._load_json(base, wf, "qa", "defect_report.json")

        return {
            "workflow_id": wf,
            "user_stories": user_stories,
            "acceptance_criteria": acceptance_criteria,
            "defect_report": defect_report,
            "retry_count": event.retry_count,
        }

    def build_prompt(self, context: dict[str, Any]) -> str:
        parts = [
            f"User stories:\n{json.dumps(context['user_stories'], indent=2)}",
            f"\nAcceptance criteria:\n{json.dumps(context['acceptance_criteria'], indent=2)}",
        ]
        if context.get("defect_report"):
            parts.append(f"\nDefect report (replan requested):\n{json.dumps(context['defect_report'], indent=2)}")
        parts.append("\nProduce the sprint plan JSON.")
        return "\n".join(parts)

    def validate_response(self, raw: str) -> dict[str, Any]:
        cleaned = _extract_json(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"SM Agent: invalid JSON: {exc}") from exc
        try:
            output = SMOutput(**data)
        except Exception as exc:
            raise LLMValidationError(f"SM Agent: schema error: {exc}") from exc
        if output.dor_failures:
            output.human_approval_required = True
        return output.model_dump()

    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list:
        wf = event.workflow_id
        refs = []
        for name, key in [
            ("sprint_goal.json", "sprint_goal"),
            ("task_breakdown.json", "task_breakdown"),
            ("dependency_graph.json", "dependency_graph"),
            ("execution_plan.json", "execution_plan"),
            ("risk_notes.json", "risk_notes"),
        ]:
            content = json.dumps(validated.get(key, {}), indent=2)
            refs.append(self._artifact_store.save(wf, "sm", name, content))

        # Update user stories to IN_PROGRESS
        for story in self._state_store.list_user_stories(wf):
            self._state_store.update_user_story_status(story["story_id"], "IN_PROGRESS")

        return refs

    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str:
        return "sm.success"

    def run(self, event: Event) -> Any:
        self._check_permissions()
        context = self.load_context(event)

        # Pre-flight: git status
        if settings.target_repo_path:
            try:
                executor = ShellExecutor(cwd=settings.target_repo_path)
                result = executor.run("git status")
                if not result.success:
                    from axon.core.results import AgentResult
                    return AgentResult(
                        status="failed",
                        errors=[f"Pre-flight git status failed: {result.error}"],
                        next_event="sm.failed",
                        human_approval_required=True,
                    )
            except Exception:
                pass  # non-fatal for MVP

        try:
            prompt = self.build_prompt(context)
            raw = self.call_llm(prompt, system=SM_SYSTEM, max_tokens=4096)
            validated = self.validate_response(raw)
            artifacts = self.persist_artifacts(validated, event)
            next_event = "sm.failed" if validated.get("human_approval_required") else "sm.success"

            from axon.core.results import AgentResult
            return AgentResult(
                status="success" if next_event == "sm.success" else "failed",
                output_artifacts=artifacts,
                next_event=next_event,
                human_approval_required=validated.get("human_approval_required", False),
            )
        except Exception as exc:
            from axon.core.results import AgentResult
            return AgentResult(
                status="failed",
                errors=[str(exc)],
                next_event="sm.failed",
                human_approval_required=True,
            )

    @staticmethod
    def _load_json(base: str, wf: str, agent: str, name: str):
        path = Path(base) / wf / agent / name
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1:] if nl != -1 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        return text.strip()
    brace = text.find("{")
    return text[brace:] if brace != -1 else text
