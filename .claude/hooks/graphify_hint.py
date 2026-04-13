"""PreToolUse hook: injects graphify hint if knowledge graph exists."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    graph_path = Path(project_dir) / "graphify-out" / "graph.json"

    if not graph_path.is_file():
        return 0

    hint = (
        "graphify: Knowledge graph exists. Read graphify-out/GRAPH_REPORT.md "
        "for god nodes and community structure before searching raw files."
    )

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": hint,
        }
    }
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
