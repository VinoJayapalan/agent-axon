from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from axon.core.events import Event
from axon.core.results import AgentResult
from axon.core.errors import AxonError
from axon.llm.base import LLMProvider
from axon.policies.agent_permissions import AGENT_PERMISSIONS
from axon.stores.local_artifact_store import LocalArtifactStore
from axon.stores.sqlite_state_store import SQLiteStateStore


class BaseAgent(ABC):
    """Template method base class for all Axon agents.

    Lifecycle (enforced by run()):
        1. load_context(event)      → context dict
        2. build_prompt(context)    → prompt string (optional for non-LLM agents)
        3. call_llm(prompt)         → raw LLM response (optional for non-LLM agents)
        4. validate_response(raw)   → validated output dict
        5. persist_artifacts(output)→ list[ArtifactRef]
        6. create_next_event(refs)  → next event_type string
        7. return AgentResult
    """

    def __init__(
        self,
        llm: LLMProvider | None,
        artifact_store: LocalArtifactStore,
        state_store: SQLiteStateStore,
    ) -> None:
        self._llm = llm
        self._artifact_store = artifact_store
        self._state_store = state_store

    # ------------------------------------------------------------------ #
    # Identity — subclasses must declare these                              #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in permissions, artifacts, and events."""

    @property
    @abstractmethod
    def role(self) -> str:
        """Human-readable role description."""

    # ------------------------------------------------------------------ #
    # Lifecycle hooks — subclasses implement these                          #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def load_context(self, event: Event) -> dict[str, Any]:
        """Load all context needed to process this event."""

    @abstractmethod
    def build_prompt(self, context: dict[str, Any]) -> str:
        """Build the LLM prompt from context."""

    @abstractmethod
    def validate_response(self, raw: str) -> dict[str, Any]:
        """Validate and parse the raw LLM response."""

    @abstractmethod
    def persist_artifacts(self, validated: dict[str, Any], event: Event) -> list:
        """Persist output artifacts and return list[ArtifactRef]."""

    @abstractmethod
    def create_next_event(self, artifacts: list, context: dict[str, Any]) -> str:
        """Return the next event_type string."""

    # ------------------------------------------------------------------ #
    # Concrete helpers                                                       #
    # ------------------------------------------------------------------ #

    def call_llm(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        if self._llm is None:
            raise AxonError(f"Agent '{self.name}' has no LLM provider configured.")
        return self._llm.complete(system=system, user=prompt, max_tokens=max_tokens)

    # ------------------------------------------------------------------ #
    # Template method                                                        #
    # ------------------------------------------------------------------ #

    def run(self, event: Event) -> AgentResult:
        self._check_permissions()
        try:
            context = self.load_context(event)
            prompt = self.build_prompt(context)
            raw = self.call_llm(prompt) if prompt else ""
            validated = self.validate_response(raw)
            artifacts = self.persist_artifacts(validated, event)
            next_event = self.create_next_event(artifacts, context)

            return AgentResult(
                status="success",
                output_artifacts=artifacts,
                next_event=next_event,
                human_approval_required=validated.get("human_approval_required", False),
            )
        except AxonError:
            raise
        except Exception as exc:
            return AgentResult(
                status="failed",
                errors=[str(exc)],
                human_approval_required=True,
            )

    def _check_permissions(self) -> None:
        allowed = AGENT_PERMISSIONS.get(self.name, [])
        if not allowed:
            raise AxonError(
                f"Agent '{self.name}' has no permissions defined in agent_permissions.py"
            )
