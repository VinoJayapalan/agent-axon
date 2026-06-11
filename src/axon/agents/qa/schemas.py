from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class TestCase(BaseModel):
    test_id: str
    scenario: str
    input: str = ""
    expected_output: str = ""
    test_file_path: str = ""
    test_content: str = ""


class Defect(BaseModel):
    defect_id: str
    test_id: str
    severity: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    root_cause: Literal["DevBug", "MissingImpl", "TestEnvIssue", "ACMismatch"] = "DevBug"
    description: str
    reproduction_steps: list[str] = []


class QAOutput(BaseModel):
    test_cases: list[TestCase] = []
    test_results: dict = {}
    defect_report: list[Defect] = []
    dod_validation: list[str] = []
    verdict: Literal["PASS", "CONDITIONAL_PASS", "FAIL"] = "CONDITIONAL_PASS"
    qa_signoff: bool = False
    summary: str = ""
