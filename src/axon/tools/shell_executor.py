from __future__ import annotations

import subprocess
from dataclasses import dataclass

from axon.observability.logging import get_logger
from axon.policies.command_policy import CommandPolicy

logger = get_logger(__name__)


@dataclass
class ShellResult:
    success: bool
    output: str
    error: str
    command: str


class ShellExecutor:
    """Safe shell executor — validates every command via CommandPolicy before running."""

    def __init__(self, cwd: str = ".") -> None:
        self._cwd = cwd

    def run(self, cmd: str, cwd: str | None = None) -> ShellResult:
        """Validate then execute a shell command.

        Raises PolicyViolationError if the command is not allowed.
        """
        CommandPolicy.validate(cmd)
        effective_cwd = cwd or self._cwd
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=effective_cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            shell_result = ShellResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip(),
                command=cmd,
            )
            logger.info("tool.invoked", tool="shell", command=cmd, success=shell_result.success)
            return shell_result
        except subprocess.TimeoutExpired:
            logger.warning("tool.invoked", tool="shell", command=cmd, success=False, error="timeout")
            return ShellResult(
                success=False,
                output="",
                error=f"Command timed out after 120s: {cmd}",
                command=cmd,
            )
