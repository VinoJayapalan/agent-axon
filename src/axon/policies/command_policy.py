from __future__ import annotations

from axon.core.errors import PolicyViolationError

# Commands that are explicitly permitted for safe local execution
ALLOWED_COMMANDS: frozenset[str] = frozenset(
    [
        "python --version",
        "pytest",
        "pytest tests/",
        "git status",
        "git diff",
        "git branch",
        "ls",
        "pwd",
        "npm test",
    ]
)

# Substrings that must never appear in any executed command
BLOCKED_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "terraform",
    "kubectl",
    "aws iam",
    "git push origin main",
    "git push main",
    "sudo",
    "sh -c",
    "bash -c",
)

# Token/secret indicators — commands containing these are blocked
SECRET_INDICATORS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "sk-ant",
    "github_pat",
)


class CommandPolicy:
    """Gatekeeper that validates shell commands before execution."""

    @staticmethod
    def validate(cmd: str) -> None:
        """Raise PolicyViolationError if cmd is not safe to run.

        A command is allowed if:
          1. It exactly matches an entry in ALLOWED_COMMANDS, OR
          2. It starts with an allowed prefix (e.g. 'pytest tests/unit/')

        AND it does not match any blocked pattern or secret indicator.
        """
        cmd_stripped = cmd.strip()
        cmd_lower = cmd_stripped.lower()

        # Check blocked patterns first
        for pattern in BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                raise PolicyViolationError(
                    f"Command blocked — matches blocked pattern '{pattern}': {cmd_stripped!r}"
                )

        # Check for secret indicators
        for indicator in SECRET_INDICATORS:
            if indicator in cmd_lower:
                raise PolicyViolationError(
                    f"Command blocked — contains secret indicator '{indicator}': {cmd_stripped!r}"
                )

        # Check allowlist (exact match or prefix match)
        for allowed in ALLOWED_COMMANDS:
            if cmd_stripped == allowed or cmd_stripped.startswith(allowed + " "):
                return

        raise PolicyViolationError(
            f"Command not in allowlist: {cmd_stripped!r}. "
            f"Allowed: {sorted(ALLOWED_COMMANDS)}"
        )
