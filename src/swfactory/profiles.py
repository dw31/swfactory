"""Init profiles: the files `swfactory init` writes for a given working style.

default      plain Claude Code headless worker
superpowers  worker runs obra/superpowers skills (TDD, systematic-debugging, executing-plans,
             verification-before-completion); intake uses brainstorming + writing-plans
"""

from __future__ import annotations

from dataclasses import dataclass, field

_FRONTMATTER = """---
tracker:
  kind: github
  repo: OWNER/REPO            # gh must be authenticated: `gh auth status`
workspace:
  repo_path: .
  base_branch: main
  include: [".env", "node_modules"]   # gitignored files to copy into each worktree
agent:
  command: >-
    claude -p --output-format json --permission-mode acceptEdits
    --allowedTools "{allowed_tools}"
    --max-turns {max_turns}
  max_concurrent: 3
  timeout_seconds: {timeout}
  max_attempts: 3
gate:
  checks:
{gate_checks}
ship:
  enabled: true
  push: true
  open_pr: true
  draft: false
poll_interval_seconds: 30
---
"""

_DEFAULT_PROMPT = """You are working on GitHub issue #{{ issue.number }}: {{ issue.title }}

{{ issue.body }}

Rules:
- Work only inside this worktree. Do not touch other branches.
- Follow the repository's existing conventions. Read CLAUDE.md first if present.
- Add or update tests for the behavior you change.
- Run the gate yourself before finishing: `ruff check .` and `pytest -q` must pass.
- Do not commit. The orchestrator commits and opens the PR.
- Finish with a short summary of what changed and why.
{% if feedback %}
Attempt {{ attempt }}. Feedback from the previous attempt:

{{ feedback }}
{% endif %}
"""

_SUPERPOWERS_PROMPT = """You are working on GitHub issue #{{ issue.number }}: {{ issue.title }}

The issue body below is an approved implementation plan produced with the writing-plans skill.
Execute it with executing-plans. If the plan lists independent tasks, use
subagent-driven-development to run them in parallel inside this worktree.
Use test-driven-development for every behavior change: failing test first, then the code.
Before you finish, run verification-before-completion and make sure `ruff check .` and
`pytest -q` pass.

You are unattended. Do not ask questions. If the plan is ambiguous, take the most conservative
reading and record the ambiguity in your final summary. Do not create worktrees or branches,
and do not commit; the orchestrator owns branching, commits, and the PR.

{{ issue.body }}
{% if feedback %}
Attempt {{ attempt }}. The verification gate FAILED. Apply systematic-debugging to the output
below (reproduce, isolate the root cause, then fix) before changing any code:

{{ feedback }}
{% endif %}
"""

_SUPERPOWERS_CLAUDE_MD = """
## swfactory: unattended execution rules

These apply when you are launched headless by swfactory (the prompt will say so).

- You are unattended. Do not ask questions. The issue body is the approved plan.
  If it is ambiguous, implement the most conservative reading and note the ambiguity
  in your final summary.
- Use test-driven-development for every behavior change.
- Use systematic-debugging when the prompt includes gate feedback.
- Run verification-before-completion before you finish.
- Do not use using-git-worktrees or finishing-a-development-branch. You are already in an
  isolated worktree. Do not create branches, do not commit, do not open PRs.
- Gate: `ruff check .` and `pytest -q` must pass.
"""

_SUPERPOWERS_SETTINGS = """{
  "_comment": "Project-level Claude Code settings so every swfactory worktree inherits the plugin.",
  "enabledPlugins": {
    "superpowers@superpowers-marketplace": true
  },
  "extraKnownMarketplaces": {
    "superpowers-marketplace": {
      "source": { "source": "github", "repo": "obra/superpowers-marketplace" }
    }
  }
}
"""

_REVIEW_GATE = """#!/usr/bin/env bash
# Optional second gate: an adversarial code review by a fresh headless Claude session.
# Exits 1 if the reviewer reports a blocking finding. Add to WORKFLOW.md:
#   gate:
#     checks: ["ruff check .", "pytest -q", "bash .swfactory/review-gate.sh"]
set -euo pipefail
BASE="${1:-main}"
DIFF="$(git diff "$BASE"...HEAD; git diff)"   # committed + uncommitted work in this worktree
[ -z "$DIFF" ] && { echo "review-gate: no diff"; exit 0; }

PROMPT=$(cat <<EOF
Use the requesting-code-review skill to review the following diff as a senior engineer.
Report findings as a list. End your reply with exactly one line: VERDICT: PASS or VERDICT: BLOCK.
BLOCK only for correctness bugs, security issues, data loss, or missing tests for changed behavior.
Style nits are PASS.

$DIFF
EOF
)
OUT="$(printf '%s' "$PROMPT" | claude -p --output-format json --max-turns 8 \\
        --allowedTools "Read,Glob,Grep" 2>/dev/null \\
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result",""))')"
echo "$OUT"
grep -q "VERDICT: PASS" <<<"$OUT" || { echo "review-gate: BLOCK"; exit 1; }
"""


@dataclass
class Profile:
    name: str
    prompt: str
    allowed_tools: str
    max_turns: int
    timeout: int
    gate_checks: list[str]
    extra_files: dict[str, str] = field(default_factory=dict)  # path -> content (created if absent)
    append_files: dict[str, str] = field(default_factory=dict)  # path -> content (appended)
    post_init_notes: list[str] = field(default_factory=list)

    def workflow(self) -> str:
        checks = "\n".join(f'    - "{c}"' for c in self.gate_checks)
        return _FRONTMATTER.format(
            allowed_tools=self.allowed_tools, max_turns=self.max_turns,
            timeout=self.timeout, gate_checks=checks,
        ) + self.prompt


PROFILES: dict[str, Profile] = {
    "default": Profile(
        name="default",
        prompt=_DEFAULT_PROMPT,
        allowed_tools=(
            "Read,Edit,Write,Glob,Grep,Bash(pytest*),Bash(ruff*),Bash(git status*),Bash(git diff*)"
        ),
        max_turns=60,
        timeout=1800,
        gate_checks=["ruff check .", "pytest -q"],
    ),
    "superpowers": Profile(
        name="superpowers",
        prompt=_SUPERPOWERS_PROMPT,
        # Task/Agent is required for subagent-driven-development; Skill loads the skills.
        allowed_tools=(
            "Read,Edit,Write,Glob,Grep,Skill,Task,Agent,"
            "Bash(pytest*),Bash(ruff*),Bash(git status*),Bash(git diff*),Bash(git log*)"
        ),
        max_turns=120,
        timeout=2700,
        gate_checks=["ruff check .", "pytest -q"],
        extra_files={
            ".claude/settings.json": _SUPERPOWERS_SETTINGS,
            ".swfactory/review-gate.sh": _REVIEW_GATE,
        },
        append_files={"CLAUDE.md": _SUPERPOWERS_CLAUDE_MD},
        post_init_notes=[
            "Intake: run `claude` interactively, use brainstorming then writing-plans, paste the plan "
            "into the issue body, label agent:ready.",
            "If .claude/settings.json already existed it was left alone; merge the enabledPlugins "
            "block from the profile by hand.",
            "Optional review gate: add \"bash .swfactory/review-gate.sh\" to gate.checks.",
            "Verify the plugin loads headless: `echo 'list your skills' | claude -p` inside the repo.",
        ],
    ),
}
