"""Local JSON tracker for dry runs and tests. Same label semantics as GitHub."""

from __future__ import annotations

import json
from pathlib import Path

from swfactory.config import TrackerConfig
from swfactory.tracker import Issue


class LocalTracker:
    def __init__(self, cfg: TrackerConfig):
        self.cfg = cfg
        self.path = Path(cfg.path)
        self._states = {cfg.ready_label, cfg.running_label, cfg.review_label, cfg.failed_label}

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def _save(self, rows: list[dict]) -> None:
        self.path.write_text(json.dumps(rows, indent=2))

    def list_ready(self) -> list[Issue]:
        out = []
        for r in self._load():
            if self.cfg.ready_label in r.get("labels", []):
                out.append(Issue(**{k: r[k] for k in r if k in Issue.__dataclass_fields__}))
        return out

    def set_state(self, issue: Issue, state: str) -> None:
        rows = self._load()
        for r in rows:
            if r["number"] == issue.number:
                r["labels"] = [lab for lab in r.get("labels", []) if lab not in self._states]
                r["labels"].append(state)
        self._save(rows)
        issue.labels = [lab for lab in issue.labels if lab not in self._states] + [state]

    def comment(self, issue: Issue, body: str) -> None:
        rows = self._load()
        for r in rows:
            if r["number"] == issue.number:
                r.setdefault("comments", []).append(body)
        self._save(rows)
