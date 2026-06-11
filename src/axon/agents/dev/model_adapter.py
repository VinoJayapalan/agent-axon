import json
from typing import Protocol

import requests

from axon.config.settings import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, MODEL_PROVIDER


from dataclasses import dataclass, field


@dataclass
class AgentPlan:
    summary: str
    relevant_files: list[str]  # files to edit (must already exist)
    suggested_change: str
    new_files: list[str] = field(default_factory=list)  # files to create from scratch


@dataclass
class FileEdit:
    path: str
    new_content: str


@dataclass
class AgentEdits:
    edits: list[FileEdit]
    summary: str


class ModelAdapter(Protocol):
    def plan_change(self, requirement: str, repo_files: list[str], file_previews: dict[str, str]) -> AgentPlan:
        ...

    def generate_edits(self, requirement: str, plan: AgentPlan, file_contents: dict[str, str]) -> AgentEdits:
        ...


class StubAdapter:
    def plan_change(self, requirement: str, repo_files: list[str], file_previews: dict[str, str]) -> AgentPlan:
        selected = repo_files[:3]
        return AgentPlan(
            summary=f"Stub plan for: {requirement}",
            relevant_files=selected,
            suggested_change="No real model call yet.",
        )

    def generate_edits(self, requirement: str, plan: AgentPlan, file_contents: dict[str, str]) -> AgentEdits:
        return AgentEdits(edits=[], summary="Stub: no edits applied.")


class AnthropicAdapter:
    def __init__(self) -> None:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")

    def plan_change(self, requirement: str, repo_files: list[str], file_previews: dict[str, str]) -> AgentPlan:
        system = (
            "You are Axon's Developer Agent's planning brain for a React operations dashboard repository. "
            "Your job is to understand a requirement, identify the most relevant files, and "
            "describe the smallest safe code change. "
            "Respond ONLY as valid JSON. Do not use markdown. Do not use code fences."
        )
        prompt = self._build_prompt(requirement, repo_files, file_previews)
        raw_text = self._call_api(system, prompt, max_tokens=1024)
        parsed = self._parse_json(raw_text)

        return AgentPlan(
            summary=parsed.get("summary", ""),
            relevant_files=parsed.get("relevant_files", []),
            suggested_change=parsed.get("suggested_change", ""),
            new_files=parsed.get("new_files", []),
        )

    def generate_edits(self, requirement: str, plan: AgentPlan, file_contents: dict[str, str]) -> AgentEdits:
        edits: list[FileEdit] = []
        system_edit = (
            "You are a careful code editor for a React operations dashboard. "
            "Apply only the minimal required change to satisfy the requirement. "
            "Respond ONLY as valid JSON. Do not use markdown. Do not use code fences."
        )
        system_create = (
            "You are a careful code author for a React operations dashboard. "
            "Create a complete, working new file that satisfies the requirement. "
            "Respond ONLY as valid JSON. Do not use markdown. Do not use code fences."
        )

        # Edit existing files
        for file_path in plan.relevant_files:
            if file_path not in file_contents:
                continue
            original = file_contents[file_path]
            prompt = self._build_edit_prompt(requirement, plan, file_path, original)
            raw_text = self._call_api(system_edit, prompt, max_tokens=4096)
            result = self._parse_json(raw_text)
            if result.get("changed") and result.get("new_content"):
                edits.append(FileEdit(path=file_path, new_content=result["new_content"]))

        # Create new files
        for file_path in plan.new_files:
            prompt = self._build_create_prompt(requirement, plan, file_path)
            raw_text = self._call_api(system_create, prompt, max_tokens=4096)
            result = self._parse_json(raw_text)
            if result.get("new_content"):
                edits.append(FileEdit(path=file_path, new_content=result["new_content"]))

        return AgentEdits(edits=edits, summary=plan.suggested_change)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _raise_for_api_error(response: requests.Response) -> None:
        """Raise RuntimeError with a human-readable message on API failure."""
        if response.ok:
            return
        try:
            body = response.json()
            message = body.get("error", {}).get("message", response.text)
        except Exception:
            message = response.text
        raise RuntimeError(f"Anthropic API error {response.status_code}: {message}")

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Concatenate all text blocks from the Anthropic response body."""
        chunks = [
            item.get("text", "")
            for item in data.get("content", [])
            if item.get("type") == "text"
        ]
        return "\n".join(chunks).strip()

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences or leading prose and return raw JSON text."""
        text = text.strip()
        if text.startswith("```"):
            # Drop the opening fence line (e.g. ```json)
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            # Drop the closing fence
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
            return text.strip()

        # Handle prose preamble: find the first JSON object or array
        brace = text.find("{")
        bracket = text.find("[")
        if brace == -1 and bracket == -1:
            return text  # let _parse_json raise a clear error
        if brace == -1:
            return text[bracket:]
        if bracket == -1:
            return text[brace:]
        return text[min(brace, bracket):]

    def _parse_json(self, raw_text: str) -> dict:
        """Parse JSON from model response, with a clear error on failure."""
        cleaned = self._extract_json(raw_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Model returned invalid JSON.\n"
                f"Parse error: {exc}\n"
                f"Raw response:\n{raw_text}"
            ) from exc

    def _call_api(self, system: str, prompt: str, max_tokens: int) -> str:
        """Make a single Anthropic API call and return the extracted response text."""
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": max_tokens,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        self._raise_for_api_error(response)
        return self._extract_text(response.json())

    def _build_edit_prompt(
        self, requirement: str, plan: AgentPlan, file_path: str, original: str
    ) -> str:
        """Build the per-file edit prompt for an existing file."""
        return f"""Requirement:
{requirement}

Plan summary:
{plan.summary}

Suggested change:
{plan.suggested_change}

File to edit: {file_path}

Current file content:
{original}

Apply only the minimal required change to satisfy the requirement.
Return ONLY valid JSON. Do not use markdown. Do not use code fences.

Use exactly this schema:
{{
  "changed": true,
  "new_content": "full new file content here"
}}

If this file does not need to be changed, return:
{{
  "changed": false,
  "new_content": ""
}}""".strip()

    def _build_create_prompt(
        self, requirement: str, plan: AgentPlan, file_path: str
    ) -> str:
        """Build the prompt to generate a brand-new file from scratch."""
        return f"""Requirement:
{requirement}

Plan summary:
{plan.summary}

Suggested change:
{plan.suggested_change}

New file to create: {file_path}

This file does NOT yet exist. Create the complete, working file content from scratch.
Return ONLY valid JSON. Do not use markdown. Do not use code fences.

Use exactly this schema:
{{
  "new_content": "complete file content here"
}}""".strip()

    def _build_prompt(self, requirement: str, repo_files: list[str], file_previews: dict[str, str]) -> str:
        previews_text = []

        for file_name, preview in file_previews.items():
            previews_text.append(f"FILE: {file_name}\n{preview}")

        return f"""
Requirement:
{requirement}

Available repo files:
{json.dumps(repo_files, indent=2)}

Relevant file previews:
{chr(10).join(previews_text)}

Return ONLY valid JSON.
Do not use markdown.
Do not use code fences.

Use exactly this schema:
{{
  "summary": "short summary",
  "relevant_files": ["src/pages/DashboardPage.jsx"],
  "new_files": ["src/pages/NewPage.jsx"],
  "suggested_change": "short description of minimal safe change"
}}

Rules:
- relevant_files: ONLY files that already exist in the repo and need to be edited
- new_files: ONLY files that do NOT yet exist and must be created from scratch
- If no new files are needed, return an empty list for new_files
""".strip()


def get_model_adapter() -> ModelAdapter:
    if MODEL_PROVIDER == "anthropic":
        return AnthropicAdapter()

    return StubAdapter()