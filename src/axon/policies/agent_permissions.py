"""Agent permissions map — defines which tool categories each agent may use.

Enforced in BaseAgent.run() before the lifecycle begins.
Categories are logical groupings; concrete enforcement is in BaseAgent.
"""

AGENT_PERMISSIONS: dict[str, list[str]] = {
    "po": ["artifact_store", "state_store", "llm", "repo_read"],
    "sm": ["artifact_store", "state_store", "llm", "shell_readonly"],
    "dev": ["artifact_store", "state_store", "shell_readonly", "shell_write", "git", "github"],
    "qa": ["artifact_store", "state_store", "llm", "shell_readonly", "shell_write", "repo_read"],
    "devops": ["artifact_store"],
    "prod": ["artifact_store"],
}
