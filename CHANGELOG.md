# Changelog

## 0.2.0 (2026-11-03)

- `swfactory init --profile superpowers`: WORKFLOW.md prompt built around obra/superpowers
  (executing-plans, subagent-driven-development, test-driven-development, systematic-debugging
  on retry, verification-before-completion); `Skill`, `Task`, `Agent` added to allowed tools;
  `--max-turns 120`, `timeout_seconds 2700`.
- Writes `.claude/settings.json` (project-level plugin enablement, never overwritten),
  appends an idempotent unattended-execution block to `CLAUDE.md`, and writes
  `.swfactory/review-gate.sh`, an optional adversarial-review gate check.
- `swfactory init --force` to regenerate WORKFLOW.md.
- Templates moved from `cli.py` into `profiles.py`.
- Tests: 7 (was 4). Profile rendering, default init, superpowers init idempotency.

## 0.1.0 (2026-11-02)

- Initial release: WORKFLOW.md loader, GitHub and local trackers, worktree manager,
  Claude Code headless runner, verification gate with feedback retry, ship (commit/push/PR),
  poll-loop orchestrator with durable claim ledger, CLI, offline demo.
