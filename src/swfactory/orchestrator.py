"""Poll loop: claim ready issues, fan out to workspaces, gate, retry, ship."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from swfactory.config import WorkflowConfig
from swfactory.gate import Gate
from swfactory.runner import AgentRunner
from swfactory.ship import Shipper
from swfactory.tracker import Issue, Tracker, build_tracker
from swfactory.workspace import WorkspaceManager

log = logging.getLogger("swfactory")


@dataclass
class IssueRecord:
    number: int
    status: str = "pending"  # pending | running | review | failed
    attempts: int = 0
    cost_usd: float = 0.0
    branch: str = ""
    pr_url: str = ""
    last_error: str = ""
    updated_at: float = field(default_factory=time.time)


class State:
    """Durable claim ledger so a restart never double-dispatches an issue."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.records: dict[int, IssueRecord] = {}
        if path.exists():
            for k, v in json.loads(path.read_text()).items():
                self.records[int(k)] = IssueRecord(**v)

    def get(self, number: int) -> IssueRecord:
        with self._lock:
            return self.records.setdefault(number, IssueRecord(number=number))

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({k: asdict(v) for k, v in self.records.items()}, indent=2)
            )

    def update(self, number: int, **kw) -> None:
        rec = self.get(number)
        for k, v in kw.items():
            setattr(rec, k, v)
        rec.updated_at = time.time()
        self.save()


class Orchestrator:
    def __init__(self, cfg: WorkflowConfig, tracker: Tracker | None = None):
        self.cfg = cfg
        self.tracker = tracker or build_tracker(cfg.tracker)
        self.workspaces = WorkspaceManager(cfg.workspace)
        self.runner = AgentRunner(cfg.agent)
        self.gate = Gate(cfg.gate)
        self.shipper = Shipper(cfg)
        repo = Path(cfg.workspace.repo_path).resolve()
        self.state = State(repo / cfg.state_file)
        self.log_dir = repo / cfg.log_dir
        self._inflight: dict[int, Future] = {}
        self._pool = ThreadPoolExecutor(max_workers=cfg.agent.max_concurrent)

    # ---- selection ------------------------------------------------------
    def select(self) -> list[Issue]:
        """Symphony selection pipeline: fetch, filter claimed, sort by priority, cap."""
        ready = self.tracker.list_ready()
        candidates = [i for i in ready if i.number not in self._inflight
                      and self.state.get(i.number).status not in ("running", "review")]
        candidates.sort(key=lambda i: (i.priority, i.number))
        slots = max(0, self.cfg.agent.max_concurrent - len(self._inflight))
        return candidates[:slots]

    # ---- one tick -------------------------------------------------------
    def tick(self) -> int:
        self._inflight = {n: f for n, f in self._inflight.items() if not f.done()}
        dispatched = 0
        for issue in self.select():
            self.tracker.set_state(issue, self.cfg.tracker.running_label)
            self.state.update(issue.number, status="running")
            self._inflight[issue.number] = self._pool.submit(self._safe_work, issue)
            dispatched += 1
            log.info("dispatched #%s %s", issue.number, issue.title)
        return dispatched

    def run_forever(self) -> None:
        log.info("swfactory polling every %ss (max %s concurrent)",
                 self.cfg.poll_interval_seconds, self.cfg.agent.max_concurrent)
        while True:
            try:
                self.tick()
            except Exception as e:  # tracker hiccup; keep the loop alive
                log.exception("tick failed: %s", e)
            time.sleep(self.cfg.poll_interval_seconds)

    def run_once(self) -> None:
        self.tick()
        for f in list(self._inflight.values()):
            f.result()

    # ---- per-issue pipeline --------------------------------------------
    def _safe_work(self, issue: Issue) -> None:
        try:
            self._work(issue)
        except Exception as e:
            log.exception("#%s crashed: %s", issue.number, e)
            self.state.update(issue.number, status="failed", last_error=str(e))
            self.tracker.set_state(issue, self.cfg.tracker.failed_label)
            self.tracker.comment(issue, f"swfactory crashed: `{e}`")

    def _work(self, issue: Issue) -> None:
        ws = self.workspaces.create(issue.number)
        self.state.update(issue.number, branch=ws.branch)
        feedback = ""
        gate_result = None
        for attempt in range(1, self.cfg.agent.max_attempts + 1):
            prompt = self.cfg.render_prompt(issue=issue, attempt=attempt, feedback=feedback)
            log_path = self.log_dir / f"issue-{issue.number}" / f"attempt-{attempt}.log"
            log.info("#%s attempt %s/%s", issue.number, attempt, self.cfg.agent.max_attempts)
            res = self.runner.run(prompt, cwd=ws.path, log_path=log_path)
            rec = self.state.get(issue.number)
            self.state.update(issue.number, attempts=attempt,
                              cost_usd=rec.cost_usd + (res.cost_usd or 0.0))
            if not res.ok:
                feedback = f"Previous agent run failed (exit {res.exit_code}).\n{res.stderr[-3000:]}"
                continue
            gate_result = self.gate.run(ws.path)
            (log_path.parent / f"gate-{attempt}.log").write_text(
                gate_result.summary() + "\n\n" + gate_result.failure_report()
            )
            if gate_result.ok:
                break
            feedback = (
                "The verification gate FAILED on your previous attempt. Fix the root cause.\n\n"
                + gate_result.failure_report()
            )
            log.info("#%s gate failed on attempt %s", issue.number, attempt)

        if gate_result is None or not gate_result.ok:
            self.state.update(issue.number, status="failed",
                              last_error="gate failed after max attempts")
            self.tracker.set_state(issue, self.cfg.tracker.failed_label)
            self.tracker.comment(
                issue,
                f"swfactory: gate failed after {self.cfg.agent.max_attempts} attempts on `{ws.branch}`.\n\n"
                f"```\n{(gate_result.failure_report(2000) if gate_result else 'agent never completed')}\n```",
            )
            return

        # Ship: commit, push, PR. Merge stays human.
        sha = self.shipper.commit(ws, issue)
        pr_url = ""
        if self.cfg.ship.enabled:
            self.shipper.push(ws)
            body = (
                f"Closes #{issue.number}\n\n"
                f"Automated by swfactory. Gate passed on attempt {attempt}.\n\n"
                f"```\n{gate_result.summary()}\n```\n\n"
                f"Diff stat:\n```\n{self.workspaces.diff_stat(ws)}\n```\n\n"
                f"Agent summary:\n{res.result_text[:2000]}"
            )
            pr_url = self.shipper.open_pr(ws, issue, body)
        self.state.update(issue.number, status="review", pr_url=pr_url)
        self.tracker.set_state(issue, self.cfg.tracker.review_label)
        self.tracker.comment(
            issue,
            f"swfactory: ready for review on `{ws.branch}` ({sha}), attempt {attempt}, "
            f"gate passed.{(' PR: ' + pr_url) if pr_url else ''}",
        )
        log.info("#%s ready for review (%s)", issue.number, pr_url or ws.branch)
