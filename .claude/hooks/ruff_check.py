"""PostToolUse hook: run ruff check + format --check on edited Python files."""

import json
import os
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    file_path = (
        data.get("tool_response", {}).get("filePath", "")
        or data.get("tool_input", {}).get("file_path", "")
    )
    if not file_path or not file_path.endswith(".py"):
        return

    proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    full = os.path.join(proj, file_path) if not os.path.isabs(file_path) else file_path
    if not os.path.isfile(full):
        return

    messages = []
    try:
        r1 = subprocess.run(
            ["ruff", "check", full],
            capture_output=True, text=True, timeout=10,
        )
        if r1.returncode != 0 and r1.stdout.strip():
            messages.append(f"ruff check:\n{r1.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        r2 = subprocess.run(
            ["ruff", "format", "--check", full],
            capture_output=True, text=True, timeout=10,
        )
        if r2.returncode != 0 and r2.stdout.strip():
            messages.append(f"ruff format:\n{r2.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if messages:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": " | ".join(messages),
            }
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
