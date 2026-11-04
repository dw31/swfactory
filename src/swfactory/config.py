"""WORKFLOW.md loader: YAML frontmatter + Jinja prompt template (Symphony-style)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _expand_env(value: Any) -> Any:
    """Expand $VAR and ${VAR} in strings, recursively."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class TrackerConfig:
    kind: str = "github"  # github | local
    repo: str = ""  # owner/name for github
    path: str = "issues.json"  # for local
    ready_label: str = "agent:ready"
    running_label: str = "agent:running"
    review_label: str = "agent:review"
    failed_label: str = "agent:failed"


@dataclass
class WorkspaceConfig:
    repo_path: str = "."
    root: str = ".swfactory/workspaces"
    base_branch: str = "main"
    branch_prefix: str = "agent/issue-"
    include: list[str] = field(default_factory=list)  # gitignored files to copy in


@dataclass
class AgentConfig:
    command: str = (
        "claude -p --output-format json --permission-mode acceptEdits "
        "--allowedTools \"Read,Edit,Write,Glob,Grep,Bash\" --max-turns 60"
    )
    max_concurrent: int = 3
    timeout_seconds: int = 1800
    max_attempts: int = 3


@dataclass
class GateConfig:
    checks: list[str] = field(default_factory=list)  # shell commands; all must exit 0
    timeout_seconds: int = 600


@dataclass
class ShipConfig:
    enabled: bool = True
    push: bool = True
    open_pr: bool = True
    draft: bool = False
    commit_message: str = "Resolve #{{ issue.number }}: {{ issue.title }}"


@dataclass
class WorkflowConfig:
    tracker: TrackerConfig
    workspace: WorkspaceConfig
    agent: AgentConfig
    gate: GateConfig
    ship: ShipConfig
    poll_interval_seconds: int = 30
    state_file: str = ".swfactory/state.json"
    log_dir: str = ".swfactory/logs"
    prompt_template: str = ""

    def render_prompt(self, **ctx: Any) -> str:
        env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
        return env.from_string(self.prompt_template).render(**ctx)

    def render(self, template: str, **ctx: Any) -> str:
        env = Environment(undefined=StrictUndefined)
        return env.from_string(template).render(**ctx)


def _build(cls, data: dict | None):
    data = data or {}
    allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{cls.__name__}: unknown keys {sorted(unknown)}")
    return cls(**data)


def load_workflow(path: str | Path = "WORKFLOW.md") -> WorkflowConfig:
    text = Path(path).read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError(f"{path}: expected YAML frontmatter delimited by '---'")
    raw = _expand_env(yaml.safe_load(m.group(1)) or {})
    prompt = m.group(2).strip() + "\n"

    cfg = WorkflowConfig(
        tracker=_build(TrackerConfig, raw.get("tracker")),
        workspace=_build(WorkspaceConfig, raw.get("workspace")),
        agent=_build(AgentConfig, raw.get("agent")),
        gate=_build(GateConfig, raw.get("gate")),
        ship=_build(ShipConfig, raw.get("ship")),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 30)),
        state_file=raw.get("state_file", ".swfactory/state.json"),
        log_dir=raw.get("log_dir", ".swfactory/logs"),
        prompt_template=prompt,
    )
    if not cfg.gate.checks:
        raise ValueError("gate.checks must list at least one verification command")
    return cfg
