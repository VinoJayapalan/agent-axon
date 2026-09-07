from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    model_provider: str = "stub"

    target_repo_path: str = ""

    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""
    github_base_branch: str = "main"

    axon_db_path: str = "data/axon.db"
    artifacts_base_path: str = "artifacts/"

    log_format: str = "console"  # "console" or "json"
    log_level: str = "INFO"


settings = Settings()

# Aliases for compatibility with code that imports individual names
ANTHROPIC_API_KEY: str = settings.anthropic_api_key
ANTHROPIC_MODEL: str = settings.anthropic_model
MODEL_PROVIDER: str = settings.model_provider
TARGET_REPO_PATH: str = settings.target_repo_path
GITHUB_TOKEN: str = settings.github_token
GITHUB_OWNER: str = settings.github_owner
GITHUB_REPO: str = settings.github_repo
GITHUB_BASE_BRANCH: str = settings.github_base_branch
