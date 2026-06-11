from typing import Protocol

from axon.core.events import ArtifactRef


class ArtifactStore(Protocol):
    """Port interface for artifact persistence."""

    def save(
        self,
        workflow_id: str,
        agent_name: str,
        artifact_name: str,
        content: str,
    ) -> ArtifactRef:
        """Persist content and return a reference to it."""
        ...

    def load(self, ref: ArtifactRef) -> str:
        """Load artifact content by reference."""
        ...
