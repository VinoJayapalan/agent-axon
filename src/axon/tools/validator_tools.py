import subprocess
from dataclasses import dataclass


@dataclass
class BuildResult:
    success: bool
    output: str    # stdout from the build
    error: str     # stderr from the build


def run_build(repo_path: str) -> BuildResult:
    """Run `npm run build` inside repo_path and return the result."""
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return BuildResult(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip(),
        )
    except subprocess.TimeoutExpired:
        return BuildResult(
            success=False,
            output="",
            error="Build timed out after 120 seconds.",
        )
    except FileNotFoundError:
        return BuildResult(
            success=False,
            output="",
            error="npm not found. Ensure Node.js and npm are installed and on PATH.",
        )


@dataclass
class TestResult:
    success: bool
    output: str   # stdout from the test runner
    error: str    # stderr from the test runner
    passed: int   # number of passing tests
    failed: int   # number of failing tests


def run_tests(repo_path: str) -> TestResult:
    """Run `npm test -- --watchAll=false --ci` and return the result."""
    try:
        result = subprocess.run(
            ["npm", "test", "--", "--watchAll=false", "--ci"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=180,
            env={**__import__("os").environ, "CI": "true"},
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        combined = stdout + "\n" + stderr

        # Parse summary line e.g. "Tests: 3 passed, 1 failed, 4 total"
        import re
        passed = sum(int(m) for m in re.findall(r"(\d+) passed", combined))
        failed = sum(int(m) for m in re.findall(r"(\d+) failed", combined))

        return TestResult(
            success=result.returncode == 0,
            output=stdout,
            error=stderr,
            passed=passed,
            failed=failed,
        )
    except subprocess.TimeoutExpired:
        return TestResult(
            success=False,
            output="",
            error="Test run timed out after 180 seconds.",
            passed=0,
            failed=0,
        )
    except FileNotFoundError:
        return TestResult(
            success=False,
            output="",
            error="npm not found. Ensure Node.js and npm are installed and on PATH.",
            passed=0,
            failed=0,
        )
