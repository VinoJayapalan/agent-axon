"""Context loader for the Developer Agent.

Reads the SM execution_plan.json from the artifact store and returns
the ordered list of requirement strings for Agent Dave.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_execution_plan(artifacts_base: str, workflow_id: str) -> list[str]:
    """Read the SM execution_plan.json and return a list of requirement strings."""
    path = Path(artifacts_base) / workflow_id / "sm" / "execution_plan.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("tasks", [])
