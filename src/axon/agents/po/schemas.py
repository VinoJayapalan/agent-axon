from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class POInput(BaseModel):
    raw_request: str
    workflow_id: str


class UserStory(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class POOutput(BaseModel):
    prd: dict = Field(default_factory=dict)
    user_stories: list[UserStory] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    feasibility_report: dict = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    risk_level: Literal["Low", "Medium", "High"] = "Low"
    is_ambiguous: bool = False
    is_duplicate: bool = False
    impact_analysis: dict = Field(default_factory=dict)
    release_notes: dict | None = None
    human_approval_required: bool = False
