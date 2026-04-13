"""PostToolUse hook: run targeted pytest on calculator files after edit.

Only triggers for files in features/calculators/. Runs the matching
test_<name>.py file if it exists.
"""

import json
import os
import re
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
    if not file_path:
        return

    # Only trigger for features/calculators/*.py (not __init__.py)
    if not re.search(r"features[\\/]calculators[\\/](?!__)", file_path):
        return
    if not file_path.endswith(".py"):
        return

    basename = os.path.splitext(os.path.basename(file_path))[0]
    proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    test_file = os.path.join(
        proj, "tests", "unit", "features", "calculators", f"test_{basename}.py"
    )

    if not os.path.isfile(test_file):
        return

    try:
        env = {**os.environ, "CI": "true"}
        r = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", test_file, "--timeout=30", "-x", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            cwd=proj,
        )
        # Show last 15 lines of output
        output_lines = (r.stdout + r.stderr).strip().splitlines()
        tail = "\n".join(output_lines[-15:])
        status = "PASSED" if r.returncode == 0 else "FAILED"
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"pytest {basename}: {status}\n{tail}",
            }
        }
        print(json.dumps(result))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


if __name__ == "__main__":
    main()
