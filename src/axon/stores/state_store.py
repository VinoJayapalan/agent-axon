from typing import Protocol

from axon.core.workflow import WorkflowState, WorkflowStatus
from axon.core.events import Event


class StateStore(Protocol):
    """Port interface for workflow and event state persistence."""

    # --- Workflow ---
    def save_workflow(self, state: WorkflowState) -> None: ...
    def get_workflow(self, workflow_id: str) -> WorkflowState | None: ...
    def update_workflow_status(self, workflow_id: str, status: WorkflowStatus) -> None: ...

    # --- Events ---
    def save_event(self, event: Event) -> None: ...
    def list_events(self, workflow_id: str) -> list[Event]: ...

    # --- User Stories ---
    def save_user_story(
        self,
        workflow_id: str,
        title: str,
        description: str,
        acceptance_criteria: list,
        priority: str,
    ) -> str: ...

    def update_user_story_status(self, story_id: str, status: str) -> None: ...
    def list_user_stories(self, workflow_id: str | None = None) -> list[dict]: ...
    def find_similar_story(self, title: str) -> dict | None: ...

    # --- Product Catalog ---
    def save_product_catalog(
        self,
        workflow_id: str,
        use_cases: list,
        user_workflows: list,
        design_decisions: list,
        components: list,
    ) -> None: ...

    def get_latest_product_catalog(self) -> dict | None: ...
