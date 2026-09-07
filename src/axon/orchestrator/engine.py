from __future__ import annotations

import json
import uuid
from pathlib import Path

from axon.agents.dev.agent import DevAgent
from axon.agents.devops.agent import DevOpsAgent
from axon.agents.po.agent import POAgent
from axon.agents.prod.agent import ProdAgent
from axon.agents.qa.agent import QAAgent
from axon.agents.sm.agent import ScrumMasterAgent
from axon.core.events import Event
from axon.core.results import AgentResult
from axon.core.workflow import WorkflowState, WorkflowStatus, WorkflowSummary
from axon.llm.base import LLMProvider
from axon.observability.logging import bind_workflow_context, clear_workflow_context, get_logger
from axon.orchestrator.router import AgentRouter
from axon.orchestrator.state_machine import StateMachine
from axon.stores.local_artifact_store import LocalArtifactStore
from axon.stores.sqlite_state_store import SQLiteStateStore

logger = get_logger(__name__)


class WorkflowEngine:
    """Drives the full PO → SM → Dev → QA pipeline.

    Stops automatically at HUMAN_APPROVAL_REQUIRED and returns a
    WorkflowSummary describing what happened and what action is needed.
    """

    def __init__(
        self,
        llm: LLMProvider,
        artifact_store: LocalArtifactStore,
        state_store: SQLiteStateStore,
    ) -> None:
        self._llm = llm
        self._artifact_store = artifact_store
        self._state_store = state_store
        self._sm_machine = StateMachine()
        agents = {
            "po":     POAgent(llm, artifact_store, state_store),
            "sm":     ScrumMasterAgent(llm, artifact_store, state_store),
            "dev":    DevAgent(llm=None, artifact_store=artifact_store, state_store=state_store),
            "qa":     QAAgent(llm, artifact_store, state_store),
            "devops": DevOpsAgent(llm=None, artifact_store=artifact_store, state_store=state_store),
            "prod":   ProdAgent(llm=None, artifact_store=artifact_store, state_store=state_store),
        }
        self._router = AgentRouter(agents)

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def run(self, request: str) -> WorkflowSummary:
        workflow_id = str(uuid.uuid4())
        wf_state = WorkflowState(workflow_id=workflow_id)
        self._state_store.save_workflow(wf_state)
        # Persist the raw request so it can be recovered on approve/resume
        self._artifact_store.save(workflow_id, "engine", "raw_request.txt", request)

        agents_executed: list[str] = []
        artifacts_created: list[str] = []
        prs_opened: list[str] = []
        qa_verdict: str | None = None

        def set_status(status: WorkflowStatus) -> None:
            wf_state.status = status
            self._state_store.update_workflow_status(workflow_id, status)
            logger.info("workflow.status_changed", status=status.value)

        def make_event(source: str, target: str, event_type: str, retry_count: int = 0, extra_meta: dict | None = None) -> Event:
            meta: dict = {"raw_request": request}
            if extra_meta:
                meta.update(extra_meta)
            ev = Event(
                workflow_id=workflow_id,
                source_agent=source,
                target_agent=target,
                event_type=event_type,
                retry_count=retry_count,
                metadata=meta,
            )
            self._state_store.save_event(ev)
            return ev

        def collect(result: AgentResult, agent_name: str) -> None:
            agents_executed.append(agent_name)
            for ref in result.output_artifacts:
                artifacts_created.append(ref.path)

        def summary(human: bool, next_step: str, errors: list[str] | None = None) -> WorkflowSummary:
            return WorkflowSummary(
                workflow_id=workflow_id,
                current_status=wf_state.status,
                agents_executed=agents_executed,
                artifacts_created=artifacts_created,
                human_approval_required=human,
                next_recommended_step=next_step,
                prs_opened=prs_opened,
                qa_verdict=qa_verdict,
            )

        def _execute() -> WorkflowSummary:
            nonlocal qa_verdict
            try:
                # ── PO Phase ─────────────────────────────────────────────────
                set_status(WorkflowStatus.PO_IN_PROGRESS)
                po_result = self._router.get_agent_by_name("po").run(
                    make_event("engine", "po", "start")
                )
                collect(po_result, "po")

                if po_result.status == "failed" or po_result.next_event == "po.ambiguous":
                    new_st = (
                        WorkflowStatus.PO_AMBIGUOUS
                        if po_result.next_event == "po.ambiguous"
                        else WorkflowStatus.FAILED
                    )
                    set_status(new_st)
                    err_detail = f": {po_result.errors[0]}" if po_result.errors else ""
                    if new_st == WorkflowStatus.PO_AMBIGUOUS:
                        msg = "PO flagged request as ambiguous — review open_questions.json and re-submit."
                    else:
                        msg = f"PO Agent failed{err_detail}"
                    return summary(True, msg, po_result.errors)

                set_status(WorkflowStatus.PO_COMPLETED)

                # ── SM → Dev → QA loop (up to 1 QA retry) ───────────────────
                qa_retry = 0
                while qa_retry <= 1:

                    # SM Phase
                    set_status(WorkflowStatus.SM_IN_PROGRESS)
                    sm_result = self._router.get_agent_by_name("sm").run(
                        make_event("engine", "sm", "sm.start", retry_count=qa_retry)
                    )
                    collect(sm_result, "sm")

                    if sm_result.status == "failed" or sm_result.human_approval_required:
                        set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                        return summary(True, "SM planning failed (DoR violations). Human review required.", sm_result.errors)

                    set_status(WorkflowStatus.SM_COMPLETED)

                    # Dev Phase
                    set_status(WorkflowStatus.DEV_IN_PROGRESS)
                    dev_result = self._router.get_agent_by_name("dev").run(
                        make_event("engine", "dev", "dev.start", retry_count=qa_retry)
                    )
                    collect(dev_result, "dev")

                    pr_url = self._load_dev_pr_url(artifacts_created)
                    if pr_url and pr_url not in prs_opened:
                        prs_opened.append(pr_url)

                    if dev_result.status == "failed":
                        set_status(WorkflowStatus.BUILD_FAILED)
                        set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                        return summary(True, "Developer Agent build failed — review errors and fix manually.", dev_result.errors)

                    set_status(WorkflowStatus.DEV_COMPLETED)
                    self._write_sprint_progress(workflow_id, sm_result, dev_result)

                    # QA Phase
                    set_status(WorkflowStatus.QA_IN_PROGRESS)
                    qa_result = self._router.get_agent_by_name("qa").run(
                        make_event("engine", "qa", "qa.start", retry_count=qa_retry)
                    )
                    collect(qa_result, "qa")
                    qa_verdict = self._load_qa_verdict(workflow_id)

                    if qa_result.status == "success":
                        set_status(WorkflowStatus.QA_COMPLETED)
                        set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                        return summary(
                            True,
                            f"QA verdict: {qa_verdict or 'PASS'}. "
                            f"Run `axon approve {workflow_id}` to proceed to release.",
                        )

                    if qa_result.next_event == "qa.env_blocked":
                        # A broken test environment isn't fixable by an SM/Dev replan — escalate immediately.
                        set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                        return summary(True, "QA blocked by a test-environment issue (not a code defect) — manual investigation required.", qa_result.errors)

                    # QA failed
                    set_status(WorkflowStatus.QA_FAILED)
                    if qa_retry < 1:
                        qa_retry += 1
                        continue  # rerun SM + Dev + QA with retry_count=1

                    # Second failure — escalate
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(True, "QA failed after retry — manual investigation required.", qa_result.errors)

            except Exception as exc:
                set_status(WorkflowStatus.FAILED)
                logger.error("workflow.failed", error=str(exc))
                return summary(True, f"Unexpected engine error: {exc}", [str(exc)])

            # Satisfy type-checker (unreachable)
            return summary(False, "Workflow loop exited unexpectedly.")

        bind_workflow_context(workflow_id=workflow_id)
        logger.info("workflow.started", request_preview=request[:80])
        try:
            result = _execute()
            logger.info("workflow.finished", status=result.current_status.value, qa_verdict=result.qa_verdict)
            return result
        finally:
            clear_workflow_context()

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    def _write_sprint_progress(
        self, workflow_id: str, sm_result: AgentResult, dev_result: AgentResult
    ) -> None:
        data = {
            "sm_artifacts": [r.path for r in sm_result.output_artifacts],
            "dev_artifacts": [r.path for r in dev_result.output_artifacts],
            "status": "DEV_COMPLETED",
        }
        self._artifact_store.save(
            workflow_id, "sm", "sprint_progress_summary.json",
            json.dumps(data, indent=2),
        )

    def _load_qa_verdict(self, workflow_id: str) -> str | None:
        signoff = self._load_qa_signoff(workflow_id)
        return signoff.get("verdict") if signoff else None

    def _load_qa_signoff(self, workflow_id: str) -> dict:
        from axon.config.settings import settings
        path = Path(settings.artifacts_base_path) / workflow_id / "qa" / "qa_signoff.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def finalize_approval(self, workflow_id: str) -> WorkflowSummary:
        """Called once QA has already passed and a human has approved release.

        Generates release notes, refreshes the product catalog, runs the
        (gated) DevOps/Prod placeholder checks, and marks the workflow DONE.
        """
        qa_signoff = self._load_qa_signoff(workflow_id)
        agents_executed: list[str] = []
        artifacts_created: list[str] = []

        def collect(result: AgentResult, agent_name: str) -> None:
            agents_executed.append(agent_name)
            for ref in result.output_artifacts:
                artifacts_created.append(ref.path)

        bind_workflow_context(workflow_id=workflow_id)
        try:
            logger.info("workflow.finalize_approval.started", qa_verdict=qa_signoff.get("verdict"))
            po_agent = self._router.get_agent_by_name("po")
            po_agent.finalize_approved(workflow_id, qa_signoff)
            agents_executed.append("po")
            from axon.config.settings import settings
            artifacts_created.append(
                str(Path(settings.artifacts_base_path) / workflow_id / "po" / "release_notes.json")
            )

            self._state_store.update_workflow_status(workflow_id, WorkflowStatus.APPROVED)
            logger.info("workflow.status_changed", status=WorkflowStatus.APPROVED.value)

            devops_result = self._router.get_agent_by_name("devops").run(
                Event(workflow_id=workflow_id, source_agent="engine", target_agent="devops", event_type="devops.start")
            )
            collect(devops_result, "devops")

            prod_result = self._router.get_agent_by_name("prod").run(
                Event(workflow_id=workflow_id, source_agent="engine", target_agent="prod", event_type="prod.start")
            )
            collect(prod_result, "prod")

            self._state_store.update_workflow_status(workflow_id, WorkflowStatus.DONE)
            logger.info("workflow.status_changed", status=WorkflowStatus.DONE.value)
            logger.info("workflow.finished", status=WorkflowStatus.DONE.value, qa_verdict=qa_signoff.get("verdict"))

            return WorkflowSummary(
                workflow_id=workflow_id,
                current_status=WorkflowStatus.DONE,
                agents_executed=agents_executed,
                artifacts_created=artifacts_created,
                human_approval_required=False,
                next_recommended_step="Workflow approved and finalized. Release notes and deployment checklists generated.",
                qa_verdict=qa_signoff.get("verdict"),
            )
        finally:
            clear_workflow_context()

    def _resume_from_qa(self, workflow_id: str, request: str) -> WorkflowSummary:
        """Resume a workflow that has Dev artifacts, running QA only (with one retry)."""
        wf_state = self._state_store.get_workflow(workflow_id)
        if wf_state is None:
            from axon.core.workflow import WorkflowState
            wf_state = WorkflowState(workflow_id=workflow_id)

        agents_executed: list[str] = []
        artifacts_created: list[str] = []
        prs_opened: list[str] = []
        qa_verdict: str | None = None

        def set_status(status: WorkflowStatus) -> None:
            wf_state.status = status
            self._state_store.update_workflow_status(workflow_id, status)
            logger.info("workflow.status_changed", status=status.value)

        def make_event(source: str, target: str, event_type: str, retry_count: int = 0) -> Event:
            ev = Event(
                workflow_id=workflow_id,
                source_agent=source,
                target_agent=target,
                event_type=event_type,
                retry_count=retry_count,
                metadata={"raw_request": request},
            )
            self._state_store.save_event(ev)
            return ev

        def collect(result: AgentResult, agent_name: str) -> None:
            agents_executed.append(agent_name)
            for ref in result.output_artifacts:
                artifacts_created.append(ref.path)

        def summary(human: bool, next_step: str, errors: list[str] | None = None) -> WorkflowSummary:
            return WorkflowSummary(
                workflow_id=workflow_id,
                current_status=wf_state.status,
                agents_executed=agents_executed,
                artifacts_created=artifacts_created,
                human_approval_required=human,
                next_recommended_step=next_step,
                prs_opened=prs_opened,
                qa_verdict=qa_verdict,
            )

        bind_workflow_context(workflow_id=workflow_id)
        logger.info("workflow.resumed", phase="qa")
        try:
            for qa_retry in range(2):
                set_status(WorkflowStatus.QA_IN_PROGRESS)
                qa_result = self._router.get_agent_by_name("qa").run(
                    make_event("engine", "qa", "qa.start", retry_count=qa_retry)
                )
                collect(qa_result, "qa")
                qa_verdict = self._load_qa_verdict(workflow_id)

                if qa_result.status == "success":
                    set_status(WorkflowStatus.QA_COMPLETED)
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(
                        True,
                        f"QA verdict: {qa_verdict or 'PASS'}. Run `axon approve {workflow_id}` to release.",
                    )

                if qa_result.next_event == "qa.env_blocked":
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(True, "QA blocked by a test-environment issue (not a code defect) — manual investigation required.", qa_result.errors)

                set_status(WorkflowStatus.QA_FAILED)
                if qa_retry == 0:
                    continue
                set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                return summary(True, "QA failed after retry — manual investigation required.", qa_result.errors)

        except Exception as exc:
            set_status(WorkflowStatus.FAILED)
            logger.error("workflow.failed", error=str(exc))
            return summary(True, f"Engine error: {exc}", [str(exc)])
        finally:
            clear_workflow_context()

        return summary(False, "Workflow loop exited unexpectedly.")

    def _resume_from_sm(self, workflow_id: str, request: str) -> WorkflowSummary:
        """Resume a workflow that was paused at PO_AMBIGUOUS or HUMAN_APPROVAL_REQUIRED,
        continuing from SM planning onward."""
        # Re-run with the same workflow_id by delegating back to run() internals.
        # Simplest approach: create a minimal forked run that writes to the same wf_id.
        wf_state = self._state_store.get_workflow(workflow_id)
        if wf_state is None:
            from axon.core.workflow import WorkflowState
            wf_state = WorkflowState(workflow_id=workflow_id)

        agents_executed: list[str] = []
        artifacts_created: list[str] = []
        prs_opened: list[str] = []
        qa_verdict: str | None = None

        def set_status(status: WorkflowStatus) -> None:
            wf_state.status = status
            self._state_store.update_workflow_status(workflow_id, status)
            logger.info("workflow.status_changed", status=status.value)

        def make_event(source: str, target: str, event_type: str, retry_count: int = 0) -> Event:
            ev = Event(
                workflow_id=workflow_id,
                source_agent=source,
                target_agent=target,
                event_type=event_type,
                retry_count=retry_count,
                metadata={"raw_request": request},
            )
            self._state_store.save_event(ev)
            return ev

        def collect(result: AgentResult, agent_name: str) -> None:
            agents_executed.append(agent_name)
            for ref in result.output_artifacts:
                artifacts_created.append(ref.path)

        def summary(human: bool, next_step: str, errors: list[str] | None = None) -> WorkflowSummary:
            return WorkflowSummary(
                workflow_id=workflow_id,
                current_status=wf_state.status,
                agents_executed=agents_executed,
                artifacts_created=artifacts_created,
                human_approval_required=human,
                next_recommended_step=next_step,
                prs_opened=prs_opened,
                qa_verdict=qa_verdict,
            )

        bind_workflow_context(workflow_id=workflow_id)
        logger.info("workflow.resumed", phase="sm")
        try:
            qa_retry = 0
            while qa_retry <= 1:
                set_status(WorkflowStatus.SM_IN_PROGRESS)
                sm_result = self._router.get_agent_by_name("sm").run(
                    make_event("engine", "sm", "sm.start", retry_count=qa_retry)
                )
                collect(sm_result, "sm")
                if sm_result.status == "failed" or sm_result.human_approval_required:
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(True, "SM planning failed. Human review required.", sm_result.errors)

                set_status(WorkflowStatus.SM_COMPLETED)

                set_status(WorkflowStatus.DEV_IN_PROGRESS)
                dev_result = self._router.get_agent_by_name("dev").run(
                    make_event("engine", "dev", "dev.start", retry_count=qa_retry)
                )
                collect(dev_result, "dev")
                pr_url = self._load_dev_pr_url(artifacts_created)
                if pr_url and pr_url not in prs_opened:
                    prs_opened.append(pr_url)
                if dev_result.status == "failed":
                    set_status(WorkflowStatus.BUILD_FAILED)
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(True, "Developer Agent build failed.", dev_result.errors)

                set_status(WorkflowStatus.DEV_COMPLETED)
                self._write_sprint_progress(workflow_id, sm_result, dev_result)

                set_status(WorkflowStatus.QA_IN_PROGRESS)
                qa_result = self._router.get_agent_by_name("qa").run(
                    make_event("engine", "qa", "qa.start", retry_count=qa_retry)
                )
                collect(qa_result, "qa")
                qa_verdict = self._load_qa_verdict(workflow_id)

                if qa_result.status == "success":
                    set_status(WorkflowStatus.QA_COMPLETED)
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(True, f"QA verdict: {qa_verdict or 'PASS'}. Run `axon approve {workflow_id}` to release.")

                if qa_result.next_event == "qa.env_blocked":
                    set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                    return summary(True, "QA blocked by a test-environment issue (not a code defect) — manual investigation required.", qa_result.errors)

                set_status(WorkflowStatus.QA_FAILED)
                if qa_retry < 1:
                    qa_retry += 1
                    continue
                set_status(WorkflowStatus.HUMAN_APPROVAL_REQUIRED)
                return summary(True, "QA failed after retry — manual investigation required.", qa_result.errors)

        except Exception as exc:
            set_status(WorkflowStatus.FAILED)
            logger.error("workflow.failed", error=str(exc))
            return summary(True, f"Engine error: {exc}", [str(exc)])
        finally:
            clear_workflow_context()

        return summary(False, "Workflow loop exited unexpectedly.")

    def _load_dev_pr_url(self, artifacts: list[str]) -> str | None:
        for path_str in artifacts:
            if "dev_output" in path_str and path_str.endswith(".json"):
                p = Path(path_str)
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                        if data.get("pr_url"):
                            return data["pr_url"]
                    except Exception:
                        pass
        return None
