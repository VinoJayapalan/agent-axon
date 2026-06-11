class AxonError(Exception):
    """Base exception for all Axon errors."""


class PolicyViolationError(AxonError):
    """Raised when a command or action violates the safety policy."""


class LLMValidationError(AxonError):
    """Raised when an LLM response fails schema validation."""


class WorkflowTransitionError(AxonError):
    """Raised when an invalid workflow state transition is attempted."""
