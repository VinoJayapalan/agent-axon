from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from axon.agents.base import BaseAgent
from axon.agents.dev.orchestrator import plan_and_edit, run_npm_install, slugify
from axon.agents.dev.prompts import load_execution_plan
from axon.agents.dev.schemas import DevOutput
from axon.config.settings import settings
from axon.core.artifacts import archive_agent_name
from axon.core.events import Event, ArtifactRef
from axon.core.results import AgentResult
from axon.observability.logging import get_logger
from axon.tools.git_tools import commit_changes, create_branch, push_branch
from axon.tools.github_tools import create_pull_request
from axon.tools.validator_tools import run_build

logger = get_logger(__name__)


class DevAgent(BaseAgent):
    """Developer Agent — wraps the full Agent Dave pipeline.

    For each task in the SM execution plan, plans and applies file edits.
    All tasks in a round are then built and shipped as a SINGLE branch/commit/PR,
    instead of one PR per task.
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
        return {"tasks": tasks, "workflow_id": event.workflow_id, "retry_count": event.retry_count}

    def build_prompt(self, context: dict[str, Any]) -> str:
        return ""  # Dev Agent does not call LLM directly

    def validate_response(self, raw: str) -> dict[str, Any]:
        return {}  # No LLM response to validate

    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list:
        return []  # Artifacts are persisted per-task inside run()

    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str:
        return "dev.all_tasks_complete"

    # ------------------------------------------------------------------ #
    # Override run() — plan+edit every task, then ONE build + ONE PR        #
    # ------------------------------------------------------------------ #

    def run(self, event: Event) -> AgentResult:
        self._check_permissions()
        structlog.contextvars.bind_contextvars(agent=self.name)
        logger.info("agent.started")
        try:
            return self._run(event)
        finally:
            structlog.contextvars.unbind_contextvars("agent")

    def _run(self, event: Event) -> AgentResult:
        context = self.load_context(event)
        tasks: list[str] = context.get("tasks", [])
        workflow_id: str = context.get("workflow_id", event.workflow_id)
        round_n: int = context.get("retry_count", 0)

        if not tasks:
            logger.error("agent.failed", error="No tasks found in SM execution_plan.json")
            return AgentResult(
                status="failed",
                errors=["No tasks found in SM execution_plan.json"],
                human_approval_required=True,
            )

        task_plans: list[dict[str, Any]] = []
        all_edited_files: list[str] = []

        for i, requirement in enumerate(tasks):
            task_id = f"task_{i + 1}"
            structlog.contextvars.bind_contextvars(task_id=task_id)
            logger.info("dev.task_started", requirement_preview=requirement[:80], task_index=i + 1, task_count=len(tasks))
            try:
                result = plan_and_edit(requirement)
            except Exception as exc:
                logger.error("dev.task_failed", error=str(exc))
                task_plans.append({
                    "task_id": task_id, "requirement": requirement,
                    "plan_summary": "", "relevant_files": [], "edited_files": [],
                    "error": str(exc),
                })
                continue
            finally:
                structlog.contextvars.unbind_contextvars("task_id")

            logger.info("dev.task_completed", edited_files=len(result.edited_files))
            task_plans.append({
                "task_id": task_id, "requirement": requirement,
                "plan_summary": result.plan_summary, "relevant_files": result.relevant_files,
                "edited_files": result.edited_files, "error": None,
            })
            for f in result.edited_files:
                if f not in all_edited_files:
                    all_edited_files.append(f)

        build_passed = True
        build_error: str | None = None
        pr_url: str | None = None

        if all_edited_files:
            if any("package.json" in f and "lock" not in f for f in all_edited_files):
                install_error = run_npm_install(settings.target_repo_path)
                if install_error:
                    build_passed = False
                    build_error = f"npm install failed:\n{install_error}"

            if build_passed:
                logger.info("dev.build_started")
                build = run_build(settings.target_repo_path)
                build_passed = build.success
                if not build_passed:
                    build_error = f"{build.error}\n{build.output}".strip()

            if build_passed:
                pr_url, pr_error = self._ship_single_pr(workflow_id, round_n, tasks, task_plans, all_edited_files)
                if pr_error:
                    build_error = pr_error

        all_artifacts: list[ArtifactRef] = []
        any_task_error = False
        for tp in task_plans:
            if tp["error"]:
                any_task_error = True
            dev_out = DevOutput(
                task_id=tp["task_id"],
                requirement=tp["requirement"],
                plan_summary=tp["plan_summary"],
                relevant_files=tp["relevant_files"],
                edits_applied=tp["edited_files"],
                build_passed=build_passed,
                pr_url=pr_url,
                error_message=tp["error"] or (build_error if not build_passed else None),
                human_review_required=bool(tp["error"]) or not build_passed,
                raw_output="",
            )
            name = f"dev_output_{tp['task_id']}.json"
            content = dev_out.model_dump_json(indent=2)
            ref = self._artifact_store.save(workflow_id, "dev", name, content)
            all_artifacts.append(ref)
            # Archive a per-round snapshot so a later retry round doesn't erase this round's outputs.
            self._artifact_store.save(workflow_id, archive_agent_name("dev", round_n), name, content)

        if any_task_error or not build_passed:
            errors = [tp["error"] for tp in task_plans if tp["error"]]
            if build_error:
                errors.append(build_error)
            logger.info("agent.completed", status="success", build_passed=build_passed, any_task_error=any_task_error)
            return AgentResult(
                status="success",
                output_artifacts=all_artifacts,
                next_event="dev.all_tasks_complete",
                errors=errors,
                human_approval_required=False,
            )

        logger.info("agent.completed", status="success", build_passed=True, pr_url=pr_url)
        return AgentResult(
            status="success",
            output_artifacts=all_artifacts,
            next_event="dev.all_tasks_complete",
        )

    # ------------------------------------------------------------------ #
    # Ship all edits from this round as a single branch/commit/PR           #
    # ------------------------------------------------------------------ #

    def _ship_single_pr(
        self,
        workflow_id: str,
        round_n: int,
        tasks: list[str],
        task_plans: list[dict[str, Any]],
        edited_files: list[str],
    ) -> tuple[str | None, str | None]:
        target = settings.target_repo_path
        raw_request = self._load_raw_request(workflow_id)
        title_source = raw_request or tasks[0]

        branch_name = slugify(title_source)
        if round_n:
            branch_name = f"{branch_name}-r{round_n}"
        commit_msg = f"feat: {title_source[:72]}"

        body_sections = [f"## Requirement\n{raw_request or title_source}\n"]
        for tp in task_plans:
            if tp["edited_files"]:
                body_sections.append(
                    f"### {tp['task_id']}\n{tp['plan_summary']}\n"
                    + "\n".join(f"- `{f}`" for f in tp["edited_files"])
                )
        pr_body = "\n\n".join(body_sections) + "\n\n_Opened by Axon_"

        print(f"Creating branch: {branch_name}")
        branch_result = create_branch(target, branch_name)
        if not branch_result.success:
            return None, f"Git branch failed: {branch_result.error}"

        print("Committing changes...")
        commit_result = commit_changes(target, edited_files, commit_msg)
        if not commit_result.success:
            return None, f"Git commit failed: {commit_result.error}"

        print(f"Pushing branch: {branch_name}")
        push_result = push_branch(target, branch_name)
        if not push_result.success:
            return None, f"Git push failed: {push_result.error}"

        print("Opening pull request...")
        pr = create_pull_request(
            title=f"feat: {title_source[:72]}",
            body=pr_body,
            branch=branch_name,
        )
        return pr.url, None

    @staticmethod
    def _load_raw_request(workflow_id: str) -> str:
        path = Path(settings.artifacts_base_path) / workflow_id / "engine" / "raw_request.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

