from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Port interface for all LLM backends."""

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        """Send a system + user message pair and return the raw text response."""
        ...
