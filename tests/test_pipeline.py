"""End-to-end pipeline test with the local tracker and the stub agent. No network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from swfactory.config import load_workflow
from swfactory.orchestrator import Orchestrator

WORKFLOW = """---
tracker:
  kind: local
  path: {issues}
workspace:
  repo_path: {repo}
  base_branch: main
agent:
  command: "{python} -m swfactory.stub_agent"
  max_concurrent: 2
  max_attempts: 3
gate:
  checks:
    - "{python} check.py"
ship:
  enabled: false
---
Issue #{{{{ issue.number }}}}: {{{{ issue.title }}}}
{{{{ issue.body }}}}
{{% if feedback %}}
Attempt {{{{ attempt }}}}. Feedback from the previous attempt:
{{{{ feedback }}}}
{{% endif %}}
"""


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-q", "-b", "main", cwd=r)
    _git("config", "user.email", "t@t", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "check.py").write_text(
        "import sys, pathlib\n"
        "p = pathlib.Path('answer.txt')\n"
        "sys.exit(0 if p.exists() and p.read_text().strip() == '42' else 1)\n"
    )
    (r / ".gitignore").write_text(".swfactory/\n")
    _git("add", "-A", cwd=r)
    _git("commit", "-qm", "init", cwd=r)
    return r


def _workflow(tmp_path: Path, repo: Path, issues: list[dict]) -> Path:
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(issues))
    wf = tmp_path / "WORKFLOW.md"
    wf.write_text(WORKFLOW.format(issues=issues_path, repo=repo, python=sys.executable))
    return wf


def test_gate_failure_then_retry_succeeds(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("SWF_STUB_FILE", "answer.txt")
    monkeypatch.setenv("SWF_STUB_FIRST", "41\n")   # wrong on attempt 1
    monkeypatch.setenv("SWF_STUB_FIXED", "42\n")   # fixed after feedback
    wf = _workflow(tmp_path, repo, [
        {"number": 7, "title": "Write the answer", "body": "answer.txt must contain 42",
         "labels": ["agent:ready"], "priority": 1},
    ])
    cfg = load_workflow(wf)
    orch = Orchestrator(cfg)
    orch.run_once()

    rec = orch.state.get(7)
    assert rec.status == "review"
    assert rec.attempts == 2
    assert rec.cost_usd == pytest.approx(0.0246)
    tracker_rows = json.loads((tmp_path / "issues.json").read_text())
    assert "agent:review" in tracker_rows[0]["labels"]
    assert "ready for review" in tracker_rows[0]["comments"][-1]
    # committed on its own branch, main untouched
    log = subprocess.run(["git", "log", "--oneline", "agent/issue-7"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "Resolve #7" in log
    assert not (repo / "answer.txt").exists()
    assert (cfg.log_dir and (repo / cfg.log_dir / "issue-7" / "gate-1.log").exists())


def test_exhausted_attempts_marks_failed(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("SWF_STUB_FILE", "answer.txt")
    monkeypatch.setenv("SWF_STUB_FIRST", "nope\n")
    monkeypatch.setenv("SWF_STUB_FIXED", "still nope\n")
    wf = _workflow(tmp_path, repo, [
        {"number": 8, "title": "Impossible", "body": "", "labels": ["agent:ready"]},
    ])
    orch = Orchestrator(load_workflow(wf))
    orch.run_once()
    assert orch.state.get(8).status == "failed"
    rows = json.loads((tmp_path / "issues.json").read_text())
    assert "agent:failed" in rows[0]["labels"]


def test_priority_and_concurrency_cap(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("SWF_STUB_FILE", "answer.txt")
    monkeypatch.setenv("SWF_STUB_FIRST", "42\n")
    wf = _workflow(tmp_path, repo, [
        {"number": 1, "title": "low", "body": "", "labels": ["agent:ready"], "priority": 3},
        {"number": 2, "title": "high", "body": "", "labels": ["agent:ready"], "priority": 0},
        {"number": 3, "title": "mid", "body": "", "labels": ["agent:ready"], "priority": 1},
    ])
    orch = Orchestrator(load_workflow(wf))
    picked = [i.number for i in orch.select()]
    assert picked == [2, 3]  # max_concurrent=2, sorted by priority
    orch.run_once()
    assert orch.state.get(2).status == "review"
    assert orch.state.get(3).status == "review"
    assert orch.state.get(1).status == "pending"
    orch.run_once()
    assert orch.state.get(1).status == "review"


def test_state_survives_restart(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("SWF_STUB_FILE", "answer.txt")
    monkeypatch.setenv("SWF_STUB_FIRST", "42\n")
    wf = _workflow(tmp_path, repo, [
        {"number": 5, "title": "x", "body": "", "labels": ["agent:ready"]},
    ])
    Orchestrator(load_workflow(wf)).run_once()
    orch2 = Orchestrator(load_workflow(wf))
    assert orch2.state.get(5).status == "review"
    assert orch2.select() == []
