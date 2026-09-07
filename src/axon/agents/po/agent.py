from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from axon.agents.base import BaseAgent
from axon.agents.po.prompts import ASSESSMENT_SYSTEM, CATALOG_REFRESH_SYSTEM, RELEASE_NOTES_SYSTEM
from axon.agents.po.schemas import POOutput, UserStory
from axon.config.settings import settings
from axon.core.errors import LLMValidationError
from axon.core.events import Event
from axon.observability.logging import get_logger
from axon.tools.repo_tools import list_repo_files
from axon.tools.file_tools import read_file

logger = get_logger(__name__)


class POAgent(BaseAgent):
    """Product Owner Agent.

    Phase 1 — Catalog Refresh: shallow repo scan → product catalog.
    Phase 2 — Request Assessment: feasibility, duplicates, risk, user stories.
    Phase 3 — Post-approved: story completion validation + release notes.
    """

    @property
    def name(self) -> str:
        return "po"

    @property
    def role(self) -> str:
        return "Product Owner — catalog refresh, feasibility analysis, user stories, backlog"

    # ------------------------------------------------------------------ #
    # Lifecycle                                                              #
    # ------------------------------------------------------------------ #

    def load_context(self, event: Event) -> dict[str, Any]:
        raw_request = event.metadata.get("raw_request", "")
        workflow_id = event.workflow_id

        # Phase 1: catalog refresh
        catalog = self._refresh_catalog(workflow_id)

        # Existing backlog for duplicate detection
        existing_stories = self._state_store.list_user_stories()

        return {
            "raw_request": raw_request,
            "workflow_id": workflow_id,
            "catalog": catalog,
            "existing_stories": existing_stories,
        }

    def build_prompt(self, context: dict[str, Any]) -> str:
        catalog = context.get("catalog", {})
        existing = context.get("existing_stories", [])
        raw_request = context.get("raw_request", "")

        existing_titles = [s.get("title", "") for s in existing]

        return f"""New feature request:
{raw_request}

Existing product catalog:
{json.dumps(catalog, indent=2)}

Existing user stories in backlog (check for duplicates):
{json.dumps(existing_titles, indent=2)}

Evaluate this request and return the required JSON."""

    def validate_response(self, raw: str) -> dict[str, Any]:
        cleaned = self._extract_json(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"PO Agent: invalid JSON from LLM: {exc}\nRaw: {raw}") from exc

        try:
            output = POOutput(**data)
        except Exception as exc:
            raise LLMValidationError(f"PO Agent: schema validation failed: {exc}") from exc

        # Auto-flag ambiguous/high-risk for human approval
        if output.is_ambiguous or output.risk_level == "High":
            output.human_approval_required = True

        return output.model_dump()

    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list:
        wf = event.workflow_id
        refs = []

        # Save main artifacts
        for name, key in [
            ("prd.json", "prd"),
            ("user_stories.json", "user_stories"),
            ("acceptance_criteria.json", "acceptance_criteria"),
            ("feasibility_report.json", "feasibility_report"),
            ("open_questions.json", "open_questions"),
        ]:
            content = json.dumps(validated.get(key, {}), indent=2)
            ref = self._artifact_store.save(wf, "po", name, content)
            refs.append(ref)

        # Persist user stories to SQLite backlog
        for story_data in validated.get("user_stories", []):
            if isinstance(story_data, dict):
                story = UserStory(**story_data)
            else:
                story = story_data
            self._state_store.save_user_story(
                workflow_id=wf,
                title=story.title,
                description=story.description,
                acceptance_criteria=story.acceptance_criteria,
                priority=story.priority,
            )

        return refs

    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str:
        # Determined by human_approval_required flag set in validate_response
        return "po.success"

    # ------------------------------------------------------------------ #
    # Post-approved: release notes + story completion                        #
    # ------------------------------------------------------------------ #

    def finalize_approved(self, workflow_id: str, qa_signoff: dict) -> None:
        """Called by engine after APPROVED. Validates stories, writes release notes,
        and refreshes the product catalog so it reflects the just-shipped feature."""
        stories = self._state_store.list_user_stories(workflow_id)
        for story in stories:
            self._state_store.update_user_story_status(story["story_id"], "DONE")

        release_notes = self._generate_release_notes(workflow_id, qa_signoff)
        self._artifact_store.save(
            workflow_id, "po", "release_notes.json", json.dumps(release_notes, indent=2)
        )
        self._refresh_catalog(workflow_id)

    def _generate_release_notes(self, workflow_id: str, qa_signoff: dict) -> dict:
        stories = self._state_store.list_user_stories(workflow_id)
        story_titles = [s.get("title", "") for s in stories]

        prompt = f"""Workflow ID: {workflow_id}
Stories delivered: {json.dumps(story_titles, indent=2)}
QA sign-off: {json.dumps(qa_signoff, indent=2)}

Generate release notes."""

        try:
            raw = self.call_llm(prompt, system=RELEASE_NOTES_SYSTEM, max_tokens=1024)
            return json.loads(self._extract_json(raw))
        except Exception:
            return {
                "version": f"MVP-{workflow_id[:8]}",
                "summary": "Workflow completed and approved.",
                "changes": story_titles,
                "quality_notes": str(qa_signoff.get("verdict", "")),
                "known_limitations": [],
            }

    # ------------------------------------------------------------------ #
    # Catalog refresh                                                         #
    # ------------------------------------------------------------------ #

    def _refresh_catalog(self, workflow_id: str) -> dict:
        target = settings.target_repo_path
        if not target:
            return {}

        try:
            files = list_repo_files(target, limit=300)
        except Exception:
            return {}

        source_files = [
            f for f in files if f.startswith("src/") and f.endswith((".js", ".jsx", ".ts", ".tsx"))
        ]
        preview_targets = source_files[:8]
        previews: dict[str, str] = {}
        for f in preview_targets:
            try:
                previews[f] = read_file(f"{target}/{f}")[:200 * 5]  # ~200 lines
            except Exception:
                pass

        previews_text = "\n\n".join(f"FILE: {k}\n{v}" for k, v in previews.items())
        prompt = f"""Repository files:
{json.dumps(files[:50], indent=2)}

File previews:
{previews_text}

Extract the product catalog."""

        try:
            raw = self.call_llm(prompt, system=CATALOG_REFRESH_SYSTEM, max_tokens=1024)
            catalog = json.loads(self._extract_json(raw))
        except Exception:
            catalog = {"use_cases": [], "user_workflows": [], "design_decisions": [], "components": []}

        # Persist to SQLite + markdown snapshot
        self._state_store.save_product_catalog(
            workflow_id=workflow_id,
            use_cases=catalog.get("use_cases", []),
            user_workflows=catalog.get("user_workflows", []),
            design_decisions=catalog.get("design_decisions", []),
            components=catalog.get("components", []),
        )

        catalog_md_path = Path(settings.artifacts_base_path) / "product_knowledge" / "catalog.md"
        catalog_md_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Product Catalog\n",
            f"*Last updated: workflow {workflow_id}*\n\n",
            "## Use Cases\n",
            *[f"- {uc}\n" for uc in catalog.get("use_cases", [])],
            "\n## User Workflows\n",
            *[f"- {wf}\n" for wf in catalog.get("user_workflows", [])],
            "\n## Design Decisions\n",
            *[f"- {dd}\n" for dd in catalog.get("design_decisions", [])],
            "\n## Components\n",
            *[f"- {c}\n" for c in catalog.get("components", [])],
        ]
        catalog_md_path.write_text("".join(lines), encoding="utf-8")

        return catalog

    # ------------------------------------------------------------------ #
    # Helper                                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
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

    def run(self, event: Event):
        self._check_permissions()
        structlog.contextvars.bind_contextvars(agent=self.name)
        logger.info("agent.started")
        try:
            context = self.load_context(event)
            prompt = self.build_prompt(context)
            raw = self.call_llm(prompt, system=ASSESSMENT_SYSTEM, max_tokens=4096)
            validated = self.validate_response(raw)
            artifacts = self.persist_artifacts(validated, event)
            next_event = "po.ambiguous" if validated.get("human_approval_required") else "po.success"

            if next_event == "po.ambiguous":
                logger.warning(
                    "po.request_ambiguous",
                    is_ambiguous=validated.get("is_ambiguous", False),
                    risk_level=validated.get("risk_level"),
                    open_questions=validated.get("open_questions", []),
                )

            from axon.core.results import AgentResult
            logger.info("agent.completed", status="success", next_event=next_event)
            return AgentResult(
                status="success",
                output_artifacts=artifacts,
                next_event=next_event,
                human_approval_required=validated.get("human_approval_required", False),
            )
        except Exception as exc:
            from axon.core.results import AgentResult
            logger.error("agent.failed", error=str(exc))
            return AgentResult(
                status="failed",
                errors=[str(exc)],
                next_event="po.failed",
                human_approval_required=True,
            )
        finally:
            structlog.contextvars.unbind_contextvars("agent")
