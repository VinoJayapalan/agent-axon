from __future__ import annotations

import json
import re
from typing import Any

from axon.agents.base import BaseAgent
from axon.agents.dev.orchestrator import run_agent
from axon.agents.dev.prompts import load_execution_plan
from axon.agents.dev.schemas import DevOutput
from axon.config.settings import settings
from axon.core.events import Event, ArtifactRef
from axon.core.results import AgentResult


class DevAgent(BaseAgent):
    """Developer Agent — wraps the full Agent Dave pipeline.

    For each task in the SM execution plan:
      - Calls orchestrator.run_agent(requirement)
      - Parses the returned string for build status and PR URL
      - Persists a structured DevOutput artifact per task
    """

    @property
    def name(self) -> str:
        return "dev"

    @property
    def role(self) -> str:
        return "Developer Agent (Agent Dave) — plans, edits, builds, commits, and opens PRs"

    # ------------------------------------------------------------------ #
    # BaseAgent lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def load_context(self, event: Event) -> dict[str, Any]:
        tasks = load_execution_plan(settings.artifacts_base_path, event.workflow_id)
        return {"tasks": tasks, "workflow_id": event.workflow_id}

    def build_prompt(self, context: dict[str, Any]) -> str:
        return ""  # Dev Agent does not call LLM directly

    def validate_response(self, raw: str) -> dict[str, Any]:
        return {}  # No LLM response to validate

    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list:
        return []  # Artifacts are persisted per-task inside run()

    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str:
        return "dev.all_tasks_complete"

    # ------------------------------------------------------------------ #
    # Override run() — iterate tasks, one run_agent() call per task         #
    # ------------------------------------------------------------------ #

    def run(self, event: Event) -> AgentResult:
        self._check_permissions()
        context = self.load_context(event)
        tasks: list[str] = context.get("tasks", [])
        workflow_id: str = context.get("workflow_id", event.workflow_id)

        if not tasks:
            return AgentResult(
                status="failed",
                errors=["No tasks found in SM execution_plan.json"],
                human_approval_required=True,
            )

        all_artifacts: list[ArtifactRef] = []
        all_outputs: list[DevOutput] = []
        any_failure = False

        for i, requirement in enumerate(tasks):
            task_id = f"task_{i + 1}"
            print(f"\n[Dev Agent] Running task {i + 1}/{len(tasks)}: {requirement[:80]}")

            try:
                raw_output = run_agent(requirement)
            except Exception as exc:
                dev_out = DevOutput(
                    task_id=task_id,
                    requirement=requirement,
                    error_message=str(exc),
                    human_review_required=True,
                    raw_output="",
                )
                any_failure = True
            else:
                dev_out = self._parse_run_agent_output(raw_output, task_id, requirement)
                if not dev_out.build_passed:
                    any_failure = True

            all_outputs.append(dev_out)
            ref = self._artifact_store.save(
                workflow_id=workflow_id,
                agent_name="dev",
                artifact_name=f"dev_output_{task_id}.json",
                content=dev_out.model_dump_json(indent=2),
            )
            all_artifacts.append(ref)

        if any_failure:
            # Build failures are handed to QA as defects rather than hard-stopping.
            # Human approval is required at QA_COMPLETED regardless.
            return AgentResult(
                status="success",
                output_artifacts=all_artifacts,
                next_event="dev.all_tasks_complete",
                errors=[o.error_message for o in all_outputs if o.error_message],
                human_approval_required=False,
            )

        return AgentResult(
            status="success",
            output_artifacts=all_artifacts,
            next_event="dev.all_tasks_complete",
        )

    # ------------------------------------------------------------------ #
    # Parser: run_agent() string → DevOutput                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_run_agent_output(raw: str, task_id: str, requirement: str) -> DevOutput:
        build_passed = "Build: ✅ PASSED" in raw
        build_failed = "Build: ❌ FAILED" in raw

        pr_url: str | None = None
        pr_match = re.search(r"Pull request opened:\s*(https?://\S+)", raw)
        if pr_match:
            pr_url = pr_match.group(1)

        plan_summary = ""
        plan_match = re.search(r"Plan summary:\s*(.+?)(?:\n\n|\Z)", raw, re.DOTALL)
        if plan_match:
            plan_summary = plan_match.group(1).strip()

        relevant_files: list[str] = []
        files_match = re.search(r"Relevant files:\n(.*?)(?:\n\n|\Z)", raw, re.DOTALL)
        if files_match:
            relevant_files = [
                f.strip() for f in files_match.group(1).splitlines() if f.strip()
            ]

        edits_applied: list[str] = []
        edits_match = re.search(r"Edits applied to:\n(.*?)(?:\n\n|\Z)", raw, re.DOTALL)
        if edits_match:
            edits_applied = [
                f.strip().lstrip("  ") for f in edits_match.group(1).splitlines() if f.strip()
            ]

        error_message: str | None = None
        if build_failed:
            err_match = re.search(r"Build errors:\n(.*?)(?:\n\n|\Z)", raw, re.DOTALL)
            error_message = err_match.group(1).strip() if err_match else "Build failed"

        if not edits_applied and not build_failed:
            no_edits = "No file edits were applied" in raw
            if no_edits:
                build_passed = True  # No changes needed — treat as success

        return DevOutput(
            task_id=task_id,
            requirement=requirement,
            plan_summary=plan_summary,
            relevant_files=relevant_files,
            edits_applied=edits_applied,
            build_passed=build_passed,
            pr_url=pr_url,
            error_message=error_message,
            human_review_required=build_failed,
            raw_output=raw,
        )
