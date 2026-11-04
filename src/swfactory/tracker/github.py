"""GitHub Issues via the `gh` CLI. No token handling in Python; gh owns auth."""

from __future__ import annotations

import json
import subprocess

from swfactory.config import TrackerConfig
from swfactory.tracker import Issue

_PRIORITY_LABELS = {"priority:p0": 0, "priority:p1": 1, "priority:p2": 2, "priority:p3": 3}


def _gh(*args: str, repo: str = "") -> str:
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


class GitHubTracker:
    def __init__(self, cfg: TrackerConfig):
        self.cfg = cfg
        self._states = {cfg.ready_label, cfg.running_label, cfg.review_label, cfg.failed_label}

    def list_ready(self) -> list[Issue]:
        out = _gh(
            "issue", "list", "--state", "open", "--label", self.cfg.ready_label,
            "--json", "number,title,body,labels,url", "--limit", "100",
            repo=self.cfg.repo,
        )
        issues = []
        for raw in json.loads(out or "[]"):
            labels = [lab["name"] for lab in raw.get("labels", [])]
            prio = min((_PRIORITY_LABELS[x] for x in labels if x in _PRIORITY_LABELS), default=100)
            issues.append(
                Issue(
                    number=raw["number"], title=raw["title"], body=raw.get("body") or "",
                    labels=labels, priority=prio, url=raw.get("url", ""),
                )
            )
        return issues

    def set_state(self, issue: Issue, state: str) -> None:
        remove = [s for s in self._states if s != state and s in issue.labels]
        args = ["issue", "edit", str(issue.number), "--add-label", state]
        for lab in remove:
            args += ["--remove-label", lab]
        _gh(*args, repo=self.cfg.repo)
        issue.labels = [lab for lab in issue.labels if lab not in self._states] + [state]

    def comment(self, issue: Issue, body: str) -> None:
        _gh("issue", "comment", str(issue.number), "--body", body, repo=self.cfg.repo)
