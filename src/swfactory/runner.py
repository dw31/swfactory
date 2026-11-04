"""Run the coding agent (Claude Code headless by default) inside a workspace."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from swfactory.config import AgentConfig


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    cost_usd: float | None = None
    session_id: str | None = None
    result_text: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class AgentRunner:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

    def run(self, prompt: str, cwd: Path, log_path: Path) -> RunResult:
        """Pipe the prompt on stdin; `claude -p` reads it. Any command honoring stdin works."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                shlex.split(self.cfg.command), input=prompt, cwd=str(cwd),
                capture_output=True, text=True, timeout=self.cfg.timeout_seconds,
            )
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out = True
            code = 124
            out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        secs = time.time() - t0

        res = RunResult(exit_code=code, stdout=out, stderr=err, seconds=secs, timed_out=timed_out)
        self._parse_claude_json(res)
        log_path.write_text(
            f"$ {self.cfg.command}\n--- prompt ---\n{prompt}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n"
            f"--- exit {code} in {secs:.1f}s ---\n"
        )
        return res

    @staticmethod
    def _parse_claude_json(res: RunResult) -> None:
        """`claude -p --output-format json` emits one JSON object with result/cost/session."""
        try:
            data = json.loads(res.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return
        if isinstance(data, dict):
            res.result_text = str(data.get("result", ""))
            res.cost_usd = data.get("total_cost_usd")
            res.session_id = data.get("session_id")
            if data.get("is_error"):
                res.exit_code = res.exit_code or 1
