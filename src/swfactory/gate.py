"""Verification gate: every check must exit 0. Failure output is fed back to the agent."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from swfactory.config import GateConfig


@dataclass
class CheckResult:
    command: str
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass
class GateResult:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def failure_report(self, max_chars: int = 6000) -> str:
        parts = []
        for c in self.checks:
            if not c.ok:
                tail = c.output[-max_chars:]
                parts.append(f"$ {c.command}\n(exit {c.exit_code})\n{tail}")
        return "\n\n".join(parts)

    def summary(self) -> str:
        return "\n".join(f"{'PASS' if c.ok else 'FAIL'}  {c.command}" for c in self.checks)


class Gate:
    def __init__(self, cfg: GateConfig):
        self.cfg = cfg

    def run(self, cwd: Path) -> GateResult:
        result = GateResult()
        for cmd in self.cfg.checks:
            try:
                p = subprocess.run(
                    cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
                    timeout=self.cfg.timeout_seconds,
                )
                result.checks.append(CheckResult(cmd, p.returncode, p.stdout + p.stderr))
            except subprocess.TimeoutExpired:
                result.checks.append(CheckResult(cmd, 124, "timed out"))
            if not result.checks[-1].ok:
                break  # fail fast; the agent gets the first failing check
        return result
