from __future__ import annotations

from pydantic import BaseModel, Field


class DevInput(BaseModel):
    requirement: str
    task_id: str
    workflow_id: str


class DevOutput(BaseModel):
    task_id: str
    requirement: str
    plan_summary: str = ""
    relevant_files: list[str] = Field(default_factory=list)
    edits_applied: list[str] = Field(default_factory=list)
    build_passed: bool = False
    pr_url: str | None = None
    error_message: str | None = None
    human_review_required: bool = False
    raw_output: str = ""
