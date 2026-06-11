from dataclasses import dataclass

import requests

from axon.config.settings import GITHUB_BASE_BRANCH, GITHUB_OWNER, GITHUB_REPO, GITHUB_TOKEN


@dataclass
class PullRequest:
    url: str
    number: int
    title: str


def create_pull_request(title: str, body: str, branch: str) -> PullRequest:
    """Open a pull request on GitHub and return its URL and number."""
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set in .env")

    response = requests.post(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/pulls",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "title": title,
            "body": body,
            "head": branch,
            "base": GITHUB_BASE_BRANCH,
        },
        timeout=30,
    )

    if not response.ok:
        try:
            message = response.json().get("message", response.text)
        except Exception:
            message = response.text
        raise RuntimeError(f"GitHub API error {response.status_code}: {message}")

    data = response.json()
    return PullRequest(
        url=data["html_url"],
        number=data["number"],
        title=data["title"],
    )
