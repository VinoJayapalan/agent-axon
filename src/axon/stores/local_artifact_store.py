from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from axon.core.events import ArtifactRef


class LocalArtifactStore:
    """Filesystem-backed artifact store.

    Artifacts are stored at:
        <base_path>/<workflow_id>/<agent_name>/<artifact_name>
    """

    def __init__(self, base_path: str = "artifacts") -> None:
        self._base = Path(base_path)

    def save(
        self,
        workflow_id: str,
        agent_name: str,
        artifact_name: str,
        content: str,
    ) -> ArtifactRef:
        target = self._base / workflow_id / agent_name / artifact_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return ArtifactRef(
            artifact_id=str(uuid.uuid4()),
            artifact_type=Path(artifact_name).suffix.lstrip(".") or "txt",
            path=str(target),
            version=1,
            created_by=agent_name,
            created_at=datetime.now(timezone.utc),
        )

    def load(self, ref: ArtifactRef) -> str:
        return Path(ref.path).read_text(encoding="utf-8")
