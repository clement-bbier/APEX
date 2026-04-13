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

    file_path = data.get("tool_response", {}).get("filePath", "") or data.get("tool_input", {}).get(
        "file_path", ""
    )
    if not file_path or not file_path.endswith(".py"):
        return

    proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    full = os.path.join(proj, file_path) if not os.path.isabs(file_path) else file_path
    if not os.path.isfile(full):
        return

    messages: list[str] = []

    # ruff check
    try:
        r1 = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "ruff", "check", full],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (r1.stdout.strip() + "\n" + r1.stderr.strip()).strip()
        if r1.returncode != 0 and output:
            messages.append(f"ruff check:\n{output}")
    except FileNotFoundError:
        messages.append("ruff check: ruff not found on PATH")
    except subprocess.TimeoutExpired:
        messages.append("ruff check: timed out after 10s")

    # ruff format
    try:
        r2 = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "ruff", "format", "--check", full],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (r2.stdout.strip() + "\n" + r2.stderr.strip()).strip()
        if r2.returncode != 0 and output:
            messages.append(f"ruff format:\n{output}")
    except FileNotFoundError:
        messages.append("ruff format: ruff not found on PATH")
    except subprocess.TimeoutExpired:
        messages.append("ruff format: timed out after 10s")

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
