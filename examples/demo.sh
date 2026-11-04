#!/usr/bin/env bash
# Stand up a sample repo and run the factory offline (local tracker + stub agent).
# Usage: bash examples/demo.sh [workdir]
set -euo pipefail
WORK="${1:-$(mktemp -d)}"
PY="$(command -v python3)"
mkdir -p "$WORK" && cd "$WORK"

# --- sample project: a tiny pricing module with a failing spec ---------------
mkdir -p repo && cd repo
git init -q -b main
git config user.email demo@local && git config user.name demo
cat > pricing.py <<'EOF'
def total(items, tax_rate=0.0):
    """Sum item prices. Tax not yet applied (see issue #1)."""
    return sum(p for _, p in items)
EOF
cat > test_pricing.py <<'EOF'
from pricing import total

def test_subtotal():
    assert total([("a", 10.0), ("b", 5.0)]) == 15.0

def test_tax_applied():
    assert total([("a", 100.0)], tax_rate=0.08) == 108.0
EOF
cat > CLAUDE.md <<'EOF'
# Demo project
- Pure Python, no deps. Run `pytest -q`.
EOF
printf '.swfactory/\n__pycache__/\n' > .gitignore
git add -A && git commit -qm "init: pricing module, tax test failing"
cd ..

# --- issues (local tracker) ----------------------------------------------------
cat > issues.json <<'EOF'
[
  {"number": 1, "title": "Apply tax_rate in pricing.total()", "priority": 0,
   "body": "total(items, tax_rate) must multiply the subtotal by (1 + tax_rate). test_tax_applied must pass.",
   "labels": ["agent:ready"]},
  {"number": 2, "title": "Make 1 == 2", "priority": 3,
   "body": "Cannot be satisfied. Demonstrates the failure path.",
   "labels": ["agent:ready"]}
]
EOF

# --- stub agent behavior: wrong on attempt 1, correct after gate feedback -------
export SWF_STUB_FILE=pricing.py
export SWF_STUB_FAIL_ISSUES=2
export SWF_STUB_FIRST='def total(items, tax_rate=0.0):
    return sum(p for _, p in items) + tax_rate   # bug: adds rate instead of applying it
'
export SWF_STUB_FIXED='def total(items, tax_rate=0.0):
    return round(sum(p for _, p in items) * (1 + tax_rate), 2)
'

# --- workflow -------------------------------------------------------------------
cat > WORKFLOW.md <<EOF
---
tracker: {kind: local, path: $WORK/issues.json}
workspace: {repo_path: $WORK/repo, base_branch: main}
agent:
  command: "$PY -m swfactory.stub_agent"   # swap for: claude -p --output-format json ...
  max_concurrent: 2
  max_attempts: 2
gate:
  checks: ["$PY -m pytest -q"]
ship: {enabled: false}                      # no remote in the demo; commit still happens
---
Issue #{{ issue.number }}: {{ issue.title }}
{{ issue.body }}
{% if feedback %}
Attempt {{ attempt }}. Feedback from the previous attempt:
{{ feedback }}
{% endif %}
EOF

echo "== workdir: $WORK"
swfactory run --once --workflow WORKFLOW.md
echo; echo "== status"; swfactory status --workflow WORKFLOW.md
echo; echo "== branch log"; git -C repo log --oneline --all
echo; echo "== main is untouched"; git -C repo diff main agent/issue-1 --stat
echo; echo "== tracker comments"; "$PY" -c "import json;[print(f'#{r[\"number\"]} {r[\"labels\"]}: {r.get(\"comments\",[])[-1][:160]}') for r in json.load(open('issues.json'))]"
echo; echo "== gate log, issue 1 attempt 1"; sed -n '1,25p' repo/.swfactory/logs/issue-1/gate-1.log
