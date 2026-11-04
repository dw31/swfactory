# swfactory

A thin software-factory orchestrator for a one-person shop on macOS. It implements the
Symphony pattern (tracker as source of truth, one isolated workspace per issue, poll, claim,
dispatch, verify, retry, ship) on top of commodity parts you already have: Claude Code,
git worktrees, GitHub Issues, and `gh`.

```
GitHub Issues ──poll──▶ swfactory ──▶ worktree/issue-N ──▶ claude -p ──▶ gate (ruff, pytest)
   agent:ready            │                                     ▲             │
                          │                                     └── feedback ─┘ (retry ≤ N)
                          └──▶ commit ──▶ push ──▶ gh pr create ──▶ agent:review ──▶ YOU merge
```

Nothing merges without you. The factory produces reviewed-by-gate branches and PRs; the merge
gate is human.

---

## Part 1: Tutorial

### 1.1 Prerequisites (macOS)

```bash
# Claude Code CLI (Apple Silicon or Intel)
curl -fsSL https://claude.ai/install.sh | bash
claude --version          # 2.1.32+ required for agent teams

# GitHub CLI, authenticated with repo scope
brew install gh
gh auth login
gh auth status

# Python 3.11+
brew install python@3.12
```

Sign in to Claude Code once interactively (`claude`) so headless runs inherit the session.
A Max plan is the right fit for sustained factory use; API billing works too and the
orchestrator records `total_cost_usd` per run either way.

### 1.2 Install swfactory

```bash
git clone <this repo> ~/src/swfactory
cd ~/src/swfactory
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q               # 4 tests, no network, ~2s
```

`pipx install .` also works if you want `swfactory` on PATH globally.

### 1.3 Prepare the target repository

Three things make a repo "factory-ready". Do these once per project.

**a. A `CLAUDE.md` at the repo root.** This is the standing brief every agent reads first.
Keep it short and operational:

```markdown
# Project brief
- Python 3.12, FastAPI, SQLAlchemy. Tests in tests/, run with `pytest -q`.
- Lint: `ruff check .` must pass. Format with `ruff format`.
- Never edit migrations by hand; run `alembic revision --autogenerate`.
- Public API changes require a docs/ update in the same change.
```

**b. A deterministic gate.** The gate is a list of shell commands that must all exit 0. If
your repo cannot answer "is this change acceptable?" from the command line, fix that first.
Typical: `ruff check .`, `pytest -q`, `mypy src`, `npm test`, `terraform validate`.

**c. Gitignored files agents need.** Worktrees start clean. List anything an agent needs
that git does not track (`.env`, `node_modules`, a `.venv` symlink) under
`workspace.include` and swfactory copies it into every worktree.

### 1.4 Create the workflow

```bash
cd ~/src/your-project
swfactory init             # writes WORKFLOW.md
```

`WORKFLOW.md` is YAML frontmatter plus a Jinja prompt template, same shape as Symphony's.
Edit it:

```yaml
---
tracker:
  kind: github
  repo: doug/your-project
workspace:
  repo_path: .
  base_branch: main
  include: [".env"]
agent:
  command: >-
    claude -p --output-format json --permission-mode acceptEdits
    --allowedTools "Read,Edit,Write,Glob,Grep,Bash(pytest*),Bash(ruff*),Bash(git status*),Bash(git diff*)"
    --max-turns 60
  max_concurrent: 3
  timeout_seconds: 1800
  max_attempts: 3
gate:
  checks:
    - "ruff check ."
    - "pytest -q"
ship:
  enabled: true
  push: true
  open_pr: true
poll_interval_seconds: 30
---
You are working on GitHub issue #{{ issue.number }}: {{ issue.title }}

{{ issue.body }}

Rules:
- Work only inside this worktree.
- Read CLAUDE.md first. Follow existing conventions.
- Add or update tests for the behavior you change.
- Run `ruff check .` and `pytest -q` before finishing.
- Do not commit. The orchestrator commits and opens the PR.
{% if feedback %}
Attempt {{ attempt }}. Feedback from the previous attempt:

{{ feedback }}
{% endif %}
```

Notes on the agent command:

- `-p` is headless mode; the prompt arrives on stdin.
- `--output-format json` gives the orchestrator `result`, `total_cost_usd`, and `session_id`.
- `--permission-mode acceptEdits` plus a narrow `--allowedTools` list is the safe default.
  Use `--dangerously-skip-permissions` only inside a sandbox you control.
- `--max-turns` is your runaway-cost brake. The orchestrator's `timeout_seconds` is the second brake.

### 1.5 Create the labels

```bash
for l in agent:ready agent:running agent:review agent:failed priority:p0 priority:p1 priority:p2; do
  gh label create "$l" --repo doug/your-project 2>/dev/null || true
done
```

State machine, driven entirely by labels so you can see it in the GitHub UI:

| Label | Meaning | Who sets it |
|---|---|---|
| `agent:ready` | Intake: this issue is well-specified enough for an agent | You |
| `agent:running` | Claimed; worktree exists; agent is working | swfactory |
| `agent:review` | Gate passed; PR open; waiting for your merge | swfactory |
| `agent:failed` | Gate failed after `max_attempts`; log attached as a comment | swfactory |

`priority:p0` through `p3` control dispatch order. Issues without a priority label run last.

### 1.6 Write issues agents can execute

The factory is only as good as its intake. An executable issue has:

1. **Observable outcome.** "Add `GET /users/{id}/orders` returning the user's orders newest
   first, paginated 50 per page" beats "improve the orders API".
2. **Acceptance criteria the gate can check.** Name the test you expect to exist.
3. **Boundaries.** Files or modules it must not touch, if any.
4. **No open design questions.** If you would have to answer a question before a contractor
   could start, answer it in the issue first. Design is your bottleneck, not execution.

Then label it `agent:ready`.

### 1.7 Run the factory

```bash
swfactory run --once       # one tick; good for the first run
swfactory run              # daemon; polls every 30s
swfactory status           # claim ledger + live worktrees
```

Keep it running on your Mac with `caffeinate -i swfactory run`, or as a `launchd` agent
(see `examples/com.swfactory.plist`). For runs that must survive the laptop lid closing,
run the same package on a Linux box or a Mac mini; nothing in it is macOS-specific.

What a tick does, per issue:

1. `git worktree add .swfactory/workspaces/issue-N -b agent/issue-N main`
2. Render the prompt and pipe it to `claude -p` with `cwd` set to the worktree.
3. Run the gate. On failure, append the failing check's output to the prompt as
   `feedback` and run the agent again, up to `max_attempts`.
4. On pass: commit as `Resolve #N: <title>`, push `agent/issue-N`, `gh pr create` with the
   gate summary and diff stat in the body, label `agent:review`.
5. On exhaustion: label `agent:failed`, comment the failure report. Worktree is kept for
   inspection.

Logs land in `.swfactory/logs/issue-N/attempt-K.log` and `gate-K.log`.

### 1.8 The human merge gate

For each `agent:review` issue:

```bash
gh pr list --label agent:review     # or just the PR tab
gh pr checkout 42                    # or open it in Claude Code Desktop for diff review
gh pr merge 42 --squash --delete-branch
swfactory clean 42 --delete-branch   # drop the worktree
```

CI on the PR is your second gate. Make the GitHub branch protection rule require it, so the
factory's local gate and CI must both pass before merge is even possible.

### 1.9 Where Claude Code's own features fit

swfactory is the outer loop. Inside a single run you can still use everything Claude Code
offers:

- **Subagents with worktree isolation.** Put `isolation: worktree` in a custom subagent's
  frontmatter under `.claude/agents/` and the agent can fan out inside its own workspace.
- **Agent teams** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). For a large issue, the prompt
  can say "use an agent team: one teammate per module, shared task list". The lead/teammate
  coordination happens inside the run; the gate still judges the combined result.
- **Claude Code Desktop** for review. Open the repo, pick the `agent/issue-N` branch, use the
  diff view and built-in browser to check a web change before merging.
- **Hooks.** A `PostToolUse` hook that runs `ruff format` on every edit keeps attempt 1
  gate-clean more often.

### 1.10 Using swfactory with Superpowers

[Superpowers](https://github.com/obra/superpowers) is a skills library for Claude Code
(brainstorming, writing-plans, executing-plans, subagent-driven-development,
test-driven-development, systematic-debugging, verification-before-completion, and more).
It governs how one session works; swfactory governs which sessions start and what happens
to their output. They compose, with one rule: interactive skills run at intake with you,
non-interactive skills run inside the worker.

| Phase | Owner | Superpowers skills |
|---|---|---|
| Intake | You, interactive `claude` | `brainstorming`, `writing-plans` |
| Dispatch | swfactory | (replaces `using-git-worktrees`) |
| Execution | `claude -p` worker | `executing-plans` / `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, `verification-before-completion` |
| Gate + retry | swfactory | gate output is fed to `systematic-debugging` on retry |
| Ship | swfactory | (replaces `finishing-a-development-branch`) |
| Review | You | optional `requesting-code-review` pass as a gate check |

```bash
cd ~/src/your-project
swfactory init --profile superpowers
```

That writes:

- `WORKFLOW.md` whose prompt treats the issue body as a writing-plans plan, invokes
  executing-plans and TDD, and routes gate failures through systematic-debugging. The
  agent command adds `Skill`, `Task`, `Agent` to `--allowedTools` (needed for
  subagent-driven-development) and raises `--max-turns` to 120.
- `.claude/settings.json` enabling the superpowers plugin at project level so every
  worktree inherits it. Left untouched if one already exists; merge the `enabledPlugins`
  block by hand.
- An appended block in `CLAUDE.md` with the unattended-execution rules: no questions, the
  plan is the spec, TDD always, do not use the worktree or branch-finishing skills.
  Idempotent; re-running does not duplicate it.
- `.swfactory/review-gate.sh`, an optional second gate that runs `requesting-code-review`
  in a fresh headless session over the diff and fails on `VERDICT: BLOCK`. Enable it by
  adding `"bash .swfactory/review-gate.sh"` to `gate.checks`.

Intake workflow with the profile:

```bash
claude                       # interactive, in the repo
> use brainstorming to design: <feature idea>
> use writing-plans to turn that into an implementation plan
# copy the plan into a new GitHub issue body
gh issue create --title "..." --body-file plan.md --label agent:ready,priority:p1
```

Check that the plugin actually loads headless before the first real run:
`echo 'list your skills' | claude -p` inside the repo should name the superpowers skills.

### 1.11 Operating rules that keep costs sane

- Start with `max_concurrent: 2` and `max_attempts: 2`. Raise only when the failure rate is low.
- A failed issue is a signal about the issue, not the model. Rewrite it before relabeling.
- Review every PR. The point of the factory is that you spend your time on design and review,
  not that you stop reading code.
- Track `swfactory status` cost totals weekly. If an issue cost more than it would have taken
  you to do, it was under-specified.

---

## Part 2: Worked example

See the chat transcript or run `examples/demo.sh`, which stands up a sample repo, two issues
(one that passes on the second attempt after gate feedback, one that is impossible), and
runs the factory with the local tracker and the stub agent so you can see every stage
without spending tokens.

---

## Reference

```
swfactory init [--profile default|superpowers] [--force]   write WORKFLOW.md (+ profile files)
swfactory run [--once] [--workflow F]    poll and dispatch
swfactory status                         claim ledger and worktrees
swfactory clean ISSUE [--delete-branch]  remove a worktree
swfactory retry ISSUE                    reset ledger entry (relabel agent:ready yourself)
```

Trackers: `github` (via `gh`) and `local` (JSON file, for tests and dry runs).
Swapping in Linear or Jira is one adapter implementing `list_ready`, `set_state`, `comment`.

Package layout:

```
src/swfactory/
  config.py        WORKFLOW.md loader (YAML frontmatter + Jinja prompt)
  tracker/         github.py, local.py
  workspace.py     git worktree lifecycle
  runner.py        claude -p subprocess, JSON result parsing
  gate.py          verification checks + failure report for feedback
  ship.py          commit, push, gh pr create
  orchestrator.py  poll loop, claim ledger, retry, state machine
  cli.py           click CLI
  profiles.py      init profiles (default, superpowers): templates and supporting files
  stub_agent.py    deterministic fake agent for tests
```
