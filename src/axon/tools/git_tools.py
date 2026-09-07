import subprocess
from dataclasses import dataclass

from axon.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GitResult:
    success: bool
    output: str
    error: str


def _run(args: list[str], cwd: str) -> GitResult:
    """Run a git command and return a GitResult."""
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return GitResult(
        success=result.returncode == 0,
        output=result.stdout.strip(),
        error=result.stderr.strip(),
    )


def create_branch(repo_path: str, branch_name: str) -> GitResult:
    """Create and checkout a new branch from the current HEAD.

    If the branch already exists locally (e.g. from a previous failed run),
    switch to main first, delete the stale branch, then recreate it.
    """
    check = _run(["git", "branch", "--list", branch_name], cwd=repo_path)
    if check.output:  # non-empty means branch exists locally
        # Switch back to main so we can delete it
        switch = _run(["git", "checkout", "main"], cwd=repo_path)
        if not switch.success:
            return switch
        delete = _run(["git", "branch", "-D", branch_name], cwd=repo_path)
        if not delete.success:
            return delete
    result = _run(["git", "checkout", "-b", branch_name], cwd=repo_path)
    logger.info("tool.invoked", tool="git_create_branch", branch=branch_name, success=result.success)
    return result


def commit_changes(repo_path: str, files: list[str], message: str) -> GitResult:
    """Stage only the specified files and create a commit."""
    stage = _run(["git", "add", "--"] + files, cwd=repo_path)
    if not stage.success:
        return stage
    result = _run(["git", "commit", "-m", message], cwd=repo_path)
    logger.info("tool.invoked", tool="git_commit", file_count=len(files), success=result.success)
    return result


def push_branch(repo_path: str, branch_name: str) -> GitResult:
    """Push the branch to origin."""
    result = _run(["git", "push", "origin", branch_name], cwd=repo_path)
    logger.info("tool.invoked", tool="git_push", branch=branch_name, success=result.success)
    return result
