from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    PO_IN_PROGRESS = "PO_IN_PROGRESS"
    PO_COMPLETED = "PO_COMPLETED"
    PO_AMBIGUOUS = "PO_AMBIGUOUS"
    SM_IN_PROGRESS = "SM_IN_PROGRESS"
    SM_COMPLETED = "SM_COMPLETED"
    DEV_IN_PROGRESS = "DEV_IN_PROGRESS"
    DEV_COMPLETED = "DEV_COMPLETED"
    BUILD_FAILED = "BUILD_FAILED"
    QA_IN_PROGRESS = "QA_IN_PROGRESS"
    QA_COMPLETED = "QA_COMPLETED"
    QA_FAILED = "QA_FAILED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DONE = "DONE"
    FAILED = "FAILED"


class WorkflowState(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    current_stage: str = WorkflowStatus.REQUEST_RECEIVED
    status: WorkflowStatus = WorkflowStatus.REQUEST_RECEIVED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0


class WorkflowSummary(BaseModel):
    workflow_id: str
    current_status: WorkflowStatus
    agents_executed: list[str] = Field(default_factory=list)
    artifacts_created: list[str] = Field(default_factory=list)
    human_approval_required: bool = False
    next_recommended_step: str = ""
    user_stories_created: int = 0
    prs_opened: list[str] = Field(default_factory=list)
    qa_verdict: str | None = None
