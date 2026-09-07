import re
import subprocess
from dataclasses import dataclass, field

from axon.config.settings import TARGET_REPO_PATH
from axon.agents.dev.model_adapter import get_model_adapter
from axon.observability.logging import get_logger
from axon.tools.file_tools import read_file, write_file
from axon.tools.git_tools import commit_changes, create_branch, push_branch
from axon.tools.github_tools import create_pull_request
from axon.tools.repo_tools import list_repo_files
from axon.tools.validator_tools import run_build

logger = get_logger(__name__)


def slugify(text: str, max_length: int = 50) -> str:
    """Convert a requirement string into a safe git branch name."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")[:max_length]
    return f"axon/{slug}"


# Back-compat alias for the previous private name.
_slugify = slugify


def run_npm_install(target_repo_path: str = TARGET_REPO_PATH) -> str | None:
    """Run `npm install`. Returns an error message string on failure, else None."""
    logger.info("tool.invoked", tool="npm_install")
    result = subprocess.run(
        ["npm", "install"],
        cwd=target_repo_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    success = result.returncode == 0
    logger.info("tool.invoked", tool="npm_install", success=success)
    if not success:
        return result.stderr[:500]
    return None


@dataclass
class PlanEditResult:
    plan_summary: str
    relevant_files: list[str] = field(default_factory=list)
    edited_files: list[str] = field(default_factory=list)
    suggested_change: str = ""


def plan_and_edit(requirement: str) -> PlanEditResult:
    """Plan and apply file edits for a single requirement — no git/build/PR side effects."""
    files = list_repo_files(TARGET_REPO_PATH, limit=300)

    source_files = [
        f for f in files
        if f.startswith("src/") and f.endswith((".js", ".jsx", ".json"))
    ]

    preview_targets = source_files[:8]
    file_previews: dict[str, str] = {}

    for file in preview_targets:
        full_path = f"{TARGET_REPO_PATH}/{file}"
        file_previews[file] = read_file(full_path)[:1200]

    adapter = get_model_adapter()
    plan = adapter.plan_change(requirement, source_files, file_previews)

    full_file_contents: dict[str, str] = {}
    for file in plan.relevant_files:
        full_path = f"{TARGET_REPO_PATH}/{file}"
        try:
            full_file_contents[file] = read_file(full_path)
        except (FileNotFoundError, OSError):
            pass

    edits = adapter.generate_edits(requirement, plan, full_file_contents)

    edited_files: list[str] = []
    for edit in edits.edits:
        full_path = f"{TARGET_REPO_PATH}/{edit.path}"
        write_file(full_path, edit.new_content)
        edited_files.append(edit.path)

    return PlanEditResult(
        plan_summary=plan.summary,
        relevant_files=plan.relevant_files,
        edited_files=edited_files,
        suggested_change=plan.suggested_change,
    )


def run_agent(requirement: str) -> str:
    """Standalone single-requirement pipeline: plan, edit, build, and open one PR.

    Used by the root `agent.py` CLI. The SDLC pipeline's DevAgent uses
    `plan_and_edit()` directly so it can consolidate multiple tasks into one PR.
    """
    result = plan_and_edit(requirement)
    relevant = "\n".join(result.relevant_files) if result.relevant_files else "(none identified)"
    edited_files = result.edited_files

    output = (
        f"Requirement: {requirement}\n\n"
        f"Plan summary: {result.plan_summary}\n\n"
        f"Relevant files:\n{relevant}\n\n"
        f"Suggested change:\n{result.suggested_change}"
    )

    if edited_files:
        output += "\n\nEdits applied to:\n" + "\n".join(f"  {f}" for f in edited_files)

        # If package.json was modified, install new dependencies first
        if any("package.json" in f and "lock" not in f for f in edited_files):
            install_error = run_npm_install(TARGET_REPO_PATH)
            if install_error:
                output += f"\n\nnpm install failed:\n{install_error}"
                return output

        print("Running build validation...")
        build = run_build(TARGET_REPO_PATH)

        if build.success:
            output += "\n\nBuild: ✅ PASSED"

            branch_name = slugify(requirement)
            commit_msg = f"feat: {requirement[:72]}"
            pr_body = (
                f"## Summary\n{result.plan_summary}\n\n"
                f"## Change\n{result.suggested_change}\n\n"
                f"## Files edited\n"
                + "\n".join(f"- `{f}`" for f in edited_files)
                + "\n\n_Opened by Axon_"
            )

            print(f"Creating branch: {branch_name}")
            branch_result = create_branch(TARGET_REPO_PATH, branch_name)
            if not branch_result.success:
                output += f"\n\nGit branch failed: {branch_result.error}"
                return output

            print("Committing changes...")
            commit_result = commit_changes(TARGET_REPO_PATH, edited_files, commit_msg)
            if not commit_result.success:
                output += f"\n\nGit commit failed: {commit_result.error}"
                return output

            print(f"Pushing branch: {branch_name}")
            push_result = push_branch(TARGET_REPO_PATH, branch_name)
            if not push_result.success:
                output += f"\n\nGit push failed: {push_result.error}"
                return output

            print("Opening pull request...")
            pr = create_pull_request(
                title=f"feat: {requirement[:72]}",
                body=pr_body,
                branch=branch_name,
            )
            output += f"\n\nPull request opened: {pr.url}"

        else:
            output += "\n\nBuild: ❌ FAILED"
            if build.error:
                output += f"\n\nBuild errors:\n{build.error}"
            if build.output:
                output += f"\n\nBuild output:\n{build.output}"
    else:
        output += "\n\nNo file edits were applied."

    return output
