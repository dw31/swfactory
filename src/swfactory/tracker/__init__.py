"""Issue tracker adapters. The tracker is the source of truth for work."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from swfactory.config import TrackerConfig


@dataclass
class Issue:
    number: int
    title: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    priority: int = 100  # lower runs first
    url: str = ""


class Tracker(Protocol):
    def list_ready(self) -> list[Issue]: ...
    def set_state(self, issue: Issue, state: str) -> None: ...
    def comment(self, issue: Issue, body: str) -> None: ...


def build_tracker(cfg: TrackerConfig) -> Tracker:
    if cfg.kind == "github":
        from swfactory.tracker.github import GitHubTracker

        return GitHubTracker(cfg)
    if cfg.kind == "local":
        from swfactory.tracker.local import LocalTracker

        return LocalTracker(cfg)
    raise ValueError(f"unknown tracker kind: {cfg.kind}")
