from __future__ import annotations


class FakeLLMProvider:
    """Deterministic LLM provider for offline testing.

    response_map: dict mapping a substring key to a canned JSON string.
    When complete() is called, the first key that appears as a substring
    of the user prompt is returned.  Falls back to a default response.
    """

    def __init__(self, response_map: dict[str, str], default: str = "{}") -> None:
        self._map = response_map
        self._default = default

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        for key, response in self._map.items():
            if key in user:
                return response
        return self._default
