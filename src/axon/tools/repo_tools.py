from pathlib import Path
from typing import List, Optional


IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}


def list_repo_files(repo_path: str, limit: int = 200) -> List[str]:
    root = Path(repo_path)
    files: List[str] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if any(part in IGNORED_DIRS for part in path.parts):
            continue

        files.append(str(path.relative_to(root)))

        if len(files) >= limit:
            break

    return files


def find_files_by_name(repo_path: str, filename: str) -> List[str]:
    root = Path(repo_path)
    matches: List[str] = []

    for path in root.rglob(filename):
        if not path.is_file():
            continue

        if any(part in IGNORED_DIRS for part in path.parts):
            continue

        matches.append(str(path.relative_to(root)))

    return matches


def find_first_matching_file(repo_path: str, candidates: List[str]) -> Optional[str]:
    for name in candidates:
        matches = find_files_by_name(repo_path, name)
        if matches:
            return matches[0]
    return None