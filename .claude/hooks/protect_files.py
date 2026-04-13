"""PreToolUse hook: protect critical files from unintended modification.

Blocks writes to S01-S10 services, ADRs, PHASE_SPEC, .env, pyproject.toml,
and CI workflows. Claude Code must ask the user before modifying these paths.
"""

import json
import re
import sys

PROTECTED_PATTERN = re.compile(
    r"(^|[\\/])"
    r"(services[\\/]s[0-9]+_"
    r"|docs[\\/]adr[\\/]"
    r"|docs[\\/]phases[\\/]PHASE_[0-9]+_SPEC"
    r"|\.env$"
    r"|pyproject\.toml$"
    r"|\.github[\\/]workflows[\\/])"
)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    if PROTECTED_PATTERN.search(file_path):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"PROTECTED: {file_path} — ask user before modifying."
                ),
            }
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
