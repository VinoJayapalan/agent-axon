import re

from axon.config.settings import TARGET_REPO_PATH
from axon.agents.dev.model_adapter import get_model_adapter
from axon.tools.file_tools import read_file, write_file
from axon.tools.git_tools import commit_changes, create_branch, push_branch
from axon.tools.github_tools import create_pull_request
from axon.tools.repo_tools import list_repo_files
from axon.tools.validator_tools import run_build


def _slugify(text: str, max_length: int = 50) -> str:
    """Convert a requirement string into a safe git branch name."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")[:max_length]
    return f"axon/{slug}"


def run_agent(requirement: str) -> str:
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

    relevant = "\n".join(plan.relevant_files) if plan.relevant_files else "(none identified)"

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

    output = (
        f"Requirement: {requirement}\n\n"
        f"Plan summary: {plan.summary}\n\n"
        f"Relevant files:\n{relevant}\n\n"
        f"Suggested change:\n{plan.suggested_change}"
    )

    if edited_files:
        output += "\n\nEdits applied to:\n" + "\n".join(f"  {f}" for f in edited_files)

        # If package.json was modified, install new dependencies first
        if any("package.json" in f and "lock" not in f for f in edited_files):
            import subprocess
            print("package.json changed — running npm install...")
            npm_result = subprocess.run(
                ["npm", "install"],
                cwd=TARGET_REPO_PATH,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if npm_result.returncode != 0:
                output += f"\n\nnpm install failed:\n{npm_result.stderr[:500]}"
                return output

        print("Running build validation...")
        build = run_build(TARGET_REPO_PATH)

        if build.success:
            output += "\n\nBuild: ✅ PASSED"

            branch_name = _slugify(requirement)
            commit_msg = f"feat: {requirement[:72]}"
            pr_body = (
                f"## Summary\n{plan.summary}\n\n"
                f"## Change\n{plan.suggested_change}\n\n"
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
