from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from axon.agents.base import BaseAgent
from axon.agents.qa.prompts import QA_SYSTEM, QA_ANALYSIS_SYSTEM
from axon.agents.qa.schemas import QAOutput, TestCase, Defect
from axon.config.settings import settings
from axon.core.artifacts import archive_agent_name
from axon.core.errors import LLMValidationError
from axon.core.events import Event
from axon.observability.logging import get_logger
from axon.tools.file_tools import write_file
from axon.tools.shell_executor import ShellExecutor

logger = get_logger(__name__)

# Substrings in test-runner stderr that indicate a broken test environment,
# not a code defect (e.g. the target repo has no "test" script configured).
_ENV_ISSUE_MARKERS = ("missing script", "command not found", "enoent", "cannot find module")


def _is_test_env_issue(test_results: dict) -> bool:
    error_text = (test_results.get("error") or "").lower()
    return any(marker in error_text for marker in _ENV_ISSUE_MARKERS)


class QAAgent(BaseAgent):

    @property
    def name(self) -> str:
        return "qa"

    @property
    def role(self) -> str:
        return "QA Agent — test generation, execution, defect analysis, release verdict"

    def load_context(self, event: Event) -> dict[str, Any]:
        wf = event.workflow_id
        base = settings.artifacts_base_path

        ac = _load_json(base, wf, "po", "acceptance_criteria.json") or []
        sprint_summary = _load_json(base, wf, "sm", "sprint_progress_summary.json") or {}
        sprint_goal = _load_json(base, wf, "sm", "sprint_goal.json") or ""

        dev_outputs = []
        dev_dir = Path(base) / wf / "dev"
        if dev_dir.exists():
            for f in sorted(dev_dir.glob("dev_output_*.json")):
                try:
                    dev_outputs.append(json.loads(f.read_text()))
                except Exception:
                    pass

        changed_files = []
        for d in dev_outputs:
            changed_files.extend(d.get("edits_applied", []))

        return {
            "workflow_id": wf,
            "acceptance_criteria": ac,
            "sprint_summary": sprint_summary,
            "sprint_goal": sprint_goal,
            "dev_outputs": dev_outputs,
            "changed_files": list(set(changed_files)),
            "retry_count": event.retry_count,
        }

    def build_prompt(self, context: dict[str, Any]) -> str:
        # Cap inputs to keep token usage predictable
        ac = context['acceptance_criteria'][:10]
        changed = context['changed_files'][:15]
        return f"""Acceptance criteria (max 5 test cases total — one per AC):
{json.dumps(ac, indent=2)}

Sprint goal:
{json.dumps(context['sprint_goal'], indent=2)}

Files changed by Developer Agent:
{json.dumps(changed, indent=2)}

Generate at most 5 concise test cases. Keep test_content under 20 lines each."""

    def validate_response(self, raw: str) -> dict[str, Any]:
        cleaned = _extract_json(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"QA Agent: invalid JSON: {exc}") from exc
        try:
            output = QAOutput(**data)
        except Exception as exc:
            raise LLMValidationError(f"QA Agent: schema error: {exc}") from exc
        return output.model_dump()

    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list:
        wf = event.workflow_id
        refs = []
        refs.append(self._artifact_store.save(wf, "qa", "test_cases.json",
                                               json.dumps(validated.get("test_cases", []), indent=2)))
        return refs

    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str:
        return "qa.success"

    def run(self, event: Event) -> Any:
        self._check_permissions()
        structlog.contextvars.bind_contextvars(agent=self.name)
        logger.info("agent.started")
        from axon.core.results import AgentResult

        context = self.load_context(event)
        wf = context["workflow_id"]

        try:
            # Phase 2: generate test cases
            prompt = self.build_prompt(context)
            raw = self.call_llm(prompt, system=QA_SYSTEM, max_tokens=6000)
            validated = self.validate_response(raw)

            # Write test files to target repo
            test_files_written = []
            if settings.target_repo_path:
                for tc in validated.get("test_cases", []):
                    if isinstance(tc, dict) and tc.get("test_file_path") and tc.get("test_content"):
                        full_path = f"{settings.target_repo_path}/{tc['test_file_path']}"
                        write_file(full_path, tc["test_content"])
                        test_files_written.append(tc["test_file_path"])

            # Phase 2b: run npm test
            test_results = {"passed": 0, "failed": 0, "output": "", "error": "", "success": False}
            if settings.target_repo_path:
                try:
                    executor = ShellExecutor(cwd=settings.target_repo_path)
                    shell_result = executor.run("npm test")
                    import re
                    combined = shell_result.output + shell_result.error
                    passed = sum(int(m) for m in re.findall(r"(\d+) passed", combined))
                    failed = sum(int(m) for m in re.findall(r"(\d+) failed", combined))
                    test_results = {
                        "passed": passed,
                        "failed": failed,
                        "output": shell_result.output[:2000],
                        "error": shell_result.error[:2000],
                        "success": shell_result.success,
                    }
                except Exception as exc:
                    test_results["error"] = str(exc)

            # Phase 3: analyse results
            analysis_prompt = f"""Test results:
{json.dumps(test_results, indent=2)}

Acceptance criteria:
{json.dumps(context['acceptance_criteria'], indent=2)}

Sprint goal: {context['sprint_goal']}

Classify defects, validate DoD, and produce verdict."""

            raw2 = self.call_llm(analysis_prompt, system=QA_ANALYSIS_SYSTEM, max_tokens=3000)
            analysis = _safe_json(raw2)

            verdict = analysis.get("verdict", "FAIL" if not test_results["success"] else "PASS")
            env_issue = _is_test_env_issue(test_results)

            # Persist all artifacts (canonical + a per-round archival copy so retries don't overwrite history)
            round_n = context.get("retry_count", 0)
            refs = []
            for name, payload in [
                ("test_cases.json", validated.get("test_cases", [])),
                ("test_results.json", test_results),
                ("defect_report.json", analysis.get("defect_report", [])),
                ("qa_signoff.json", analysis),
            ]:
                content = json.dumps(payload, indent=2)
                refs.append(self._artifact_store.save(wf, "qa", name, content))
                self._artifact_store.save(wf, archive_agent_name("qa", round_n), name, content)

            if env_issue:
                # A broken test environment is not a code defect the Dev Agent can fix by replanning —
                # escalate immediately instead of burning the single SM/Dev/QA retry on it.
                logger.warning("qa.test_env_issue", round=round_n)
                return AgentResult(
                    status="failed",
                    output_artifacts=refs,
                    next_event="qa.env_blocked",
                    errors=[f"QA blocked by a test-environment issue (not a code defect): {analysis.get('summary', '')}"],
                    human_approval_required=True,
                )

            if verdict == "FAIL":
                if round_n < 1:
                    logger.info("agent.completed", status="failed", next_event="qa.failed", verdict=verdict)
                    return AgentResult(
                        status="failed",
                        output_artifacts=refs,
                        next_event="qa.failed",
                        errors=[f"QA verdict: FAIL — {analysis.get('summary', '')}"],
                        human_approval_required=False,
                    )
                else:
                    logger.info("agent.completed", status="failed", next_event="qa.failed", verdict=verdict)
                    return AgentResult(
                        status="failed",
                        output_artifacts=refs,
                        next_event="qa.failed",
                        errors=[f"QA failed after retry"],
                        human_approval_required=True,
                    )

            logger.info("agent.completed", status="success", next_event="qa.success", verdict=verdict)
            return AgentResult(
                status="success",
                output_artifacts=refs,
                next_event="qa.success",
                human_approval_required=True,  # always pause at QA_COMPLETED
            )

        except Exception as exc:
            logger.error("agent.failed", error=str(exc))
            return AgentResult(
                status="failed",
                errors=[str(exc)],
                next_event="qa.failed",
                human_approval_required=True,
            )
        finally:
            structlog.contextvars.unbind_contextvars("agent")


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
    bracket = text.find("[")
    if brace == -1 and bracket == -1:
        return text
    if brace == -1:
        return text[bracket:]
    if bracket == -1:
        return text[brace:]
    return text[min(brace, bracket):]


def _safe_json(text: str) -> dict:
    try:
        return json.loads(_extract_json(text))
    except Exception:
        return {"verdict": "CONDITIONAL_PASS", "summary": text[:200], "defect_report": []}
