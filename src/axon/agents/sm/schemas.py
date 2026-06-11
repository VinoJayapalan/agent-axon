from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Task(BaseModel):
    task_id: str
    story_id: str = ""
    description: str
    story_points: Literal[1, 2, 3, 5, 8] = 3
    parallel: bool = False
    depends_on: list[str] = Field(default_factory=list)
    requirement_for_dev_agent: str


class SMInput(BaseModel):
    user_stories: list[dict]
    acceptance_criteria: list[str]
    workflow_id: str
    defect_report: list[dict] | None = None


class SMOutput(BaseModel):
    sprint_goal: str
    task_breakdown: list[Task] = Field(default_factory=list)
    dependency_graph: dict = Field(default_factory=dict)
    execution_plan: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    story_points_total: int = 0
    dor_failures: list[str] = Field(default_factory=list)
    human_approval_required: bool = False
