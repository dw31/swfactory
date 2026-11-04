"""Commit, push, open a PR. The merge itself is always a human action."""

from __future__ import annotations

import subprocess

from swfactory.config import ShipConfig, WorkflowConfig
from swfactory.tracker import Issue
from swfactory.workspace import Workspace, git


class Shipper:
    def __init__(self, cfg: WorkflowConfig):
        self.cfg = cfg
        self.ship: ShipConfig = cfg.ship

    def commit(self, ws: Workspace, issue: Issue) -> str:
        git("add", "-A", cwd=ws.path)
        msg = self.cfg.render(self.ship.commit_message, issue=issue)
        git("-c", "user.name=swfactory", "-c", "user.email=swfactory@localhost",
            "commit", "-m", msg, "--allow-empty", cwd=ws.path)
        return git("rev-parse", "--short", "HEAD", cwd=ws.path)

    def push(self, ws: Workspace) -> None:
        if self.ship.push:
            git("push", "-u", "origin", ws.branch, "--force-with-lease", cwd=ws.path)

    def open_pr(self, ws: Workspace, issue: Issue, body: str) -> str:
        if not self.ship.open_pr:
            return ""
        args = ["gh", "pr", "create", "--head", ws.branch, "--base", self.cfg.workspace.base_branch,
                "--title", f"{issue.title} (#{issue.number})", "--body", body]
        if self.ship.draft:
            args.append("--draft")
        res = subprocess.run(args, cwd=str(ws.path), capture_output=True, text=True)
        if res.returncode != 0:
            if "already exists" in res.stderr:
                return "existing PR"
            raise RuntimeError(f"gh pr create failed: {res.stderr.strip()}")
        return res.stdout.strip()
