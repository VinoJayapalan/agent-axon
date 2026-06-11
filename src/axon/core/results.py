from __future__ import annotations

from pydantic import BaseModel, Field

from axon.core.events import ArtifactRef


class AgentResult(BaseModel):
    status: str  # "success" | "failed" | "ambiguous"
    output_artifacts: list[ArtifactRef] = Field(default_factory=list)
    next_event: str = ""
    errors: list[str] = Field(default_factory=list)
    human_approval_required: bool = False
