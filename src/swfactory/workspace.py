"""One git worktree per issue. Agents never share a working directory."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from swfactory.config import WorkspaceConfig


def git(*args: str, cwd: str | Path) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {res.stderr.strip()}")
    return res.stdout.strip()


@dataclass
class Workspace:
    path: Path
    branch: str
    issue_number: int


class WorkspaceManager:
    def __init__(self, cfg: WorkspaceConfig):
        self.cfg = cfg
        self.repo = Path(cfg.repo_path).resolve()
        self.root = (self.repo / cfg.root).resolve() if not Path(cfg.root).is_absolute() else Path(cfg.root)

    def create(self, issue_number: int) -> Workspace:
        self.root.mkdir(parents=True, exist_ok=True)
        branch = f"{self.cfg.branch_prefix}{issue_number}"
        path = self.root / f"issue-{issue_number}"
        if path.exists():
            self.remove(issue_number)
        # Branch may exist from a prior attempt; reuse it, otherwise fork from base.
        existing = git("branch", "--list", branch, cwd=self.repo)
        if existing:
            git("worktree", "add", str(path), branch, cwd=self.repo)
        else:
            git("worktree", "add", "-b", branch, str(path), self.cfg.base_branch, cwd=self.repo)
        self._copy_includes(path)
        return Workspace(path=path, branch=branch, issue_number=issue_number)

    def _copy_includes(self, path: Path) -> None:
        for rel in self.cfg.include:
            src = self.repo / rel
            dst = path / rel
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=True)
            elif src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    def remove(self, issue_number: int, delete_branch: bool = False) -> None:
        path = self.root / f"issue-{issue_number}"
        if path.exists():
            git("worktree", "remove", "--force", str(path), cwd=self.repo)
        git("worktree", "prune", cwd=self.repo)
        if delete_branch:
            branch = f"{self.cfg.branch_prefix}{issue_number}"
            subprocess.run(["git", "branch", "-D", branch], cwd=self.repo, capture_output=True)

    def list(self) -> list[str]:
        return [ln for ln in git("worktree", "list", cwd=self.repo).splitlines() if "issue-" in ln]

    def has_changes(self, ws: Workspace) -> bool:
        return bool(git("status", "--porcelain", cwd=ws.path))

    def diff_stat(self, ws: Workspace) -> str:
        git("add", "-A", cwd=ws.path)
        return git("diff", "--cached", "--stat", cwd=ws.path)
