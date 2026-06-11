from __future__ import annotations

import requests

from axon.config.settings import settings
from axon.core.errors import LLMValidationError


class ClaudeProvider:
    """LLM adapter for Anthropic Claude via direct HTTP (no SDK)."""

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=90,
        )
        self._raise_for_error(response)
        return self._extract_text(response.json())

    @staticmethod
    def _raise_for_error(response: requests.Response) -> None:
        if response.ok:
            return
        try:
            message = response.json().get("error", {}).get("message", response.text)
        except Exception:
            message = response.text
        raise LLMValidationError(f"Anthropic API error {response.status_code}: {message}")

    @staticmethod
    def _extract_text(data: dict) -> str:
        chunks = [
            item.get("text", "")
            for item in data.get("content", [])
            if item.get("type") == "text"
        ]
        return "\n".join(chunks).strip()
