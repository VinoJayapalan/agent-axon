from __future__ import annotations

from pathlib import Path


def artifact_path(base: str, workflow_id: str, agent_name: str, artifact_name: str) -> Path:
    """Return the full path for a workflow artifact file.

    Example:
        artifact_path("artifacts", "wf-123", "po", "user_stories.json")
        → Path("artifacts/wf-123/po/user_stories.json")
    """
    return Path(base) / workflow_id / agent_name / artifact_name
