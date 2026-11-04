"""Deterministic stand-in for `claude -p`, used by tests and `swfactory` dry runs.

Reads the prompt on stdin. Behavior is driven by environment variables so a test can
script a failure-then-success sequence:

  SWF_STUB_FILE   path (relative to cwd) to write
  SWF_STUB_FIRST  content to write when the prompt contains no feedback (attempt 1)
  SWF_STUB_FIXED  content to write when the prompt contains gate feedback (attempt 2+)

Emits the same JSON shape as `claude -p --output-format json`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def main() -> int:
    prompt = sys.stdin.read()
    target = Path(os.environ.get("SWF_STUB_FILE", "stub_output.txt"))
    has_feedback = "Feedback from the previous attempt" in prompt
    content = os.environ.get("SWF_STUB_FIXED" if has_feedback else "SWF_STUB_FIRST", "ok\n")
    # SWF_STUB_FAIL_ISSUES="2,9": issues the stub can never satisfy (writes broken code)
    m = re.search(r"#(\d+)", prompt)
    fail_set = {s.strip() for s in os.environ.get("SWF_STUB_FAIL_ISSUES", "").split(",") if s.strip()}
    if m and m.group(1) in fail_set:
        content = "raise RuntimeError('stub: unsatisfiable issue')\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    print(json.dumps({
        "type": "result", "is_error": False, "session_id": "stub-session",
        "total_cost_usd": 0.0123,
        "result": f"stub agent wrote {target} ({'after feedback' if has_feedback else 'first attempt'})",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
