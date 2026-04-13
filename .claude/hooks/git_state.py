"""UserPromptSubmit hook: injects current git repo state as context."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _run(args: list[str], cwd: str) -> str:
    """Run a git command, return stripped stdout, empty string on failure."""
    try:
        result = subprocess.run(  # noqa: S603
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def main() -> int:
    cwd = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    branch = _run(["git", "branch", "--show-current"], cwd) or "(unknown)"
    last_commit = _run(["git", "log", "--oneline", "-1"], cwd) or "(no commits)"

    status_raw = _run(["git", "status", "--porcelain"], cwd)
    uncommitted = len([line for line in status_raw.splitlines() if line.strip()])

    diff_raw = _run(["git", "diff", "--name-only", "HEAD~3"], cwd)
    modified = [line.strip() for line in diff_raw.splitlines() if line.strip()][:10]
    modified_str = ",".join(modified) if modified else "(none)"

    context = (
        f"REPO STATE: branch={branch} | last_commit={last_commit} | "
        f"uncommitted={uncommitted} files | "
        f"modified_last_3_commits={modified_str}"
    )

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
