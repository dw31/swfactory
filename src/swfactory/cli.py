"""swfactory CLI."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from swfactory.config import load_workflow
from swfactory.orchestrator import Orchestrator, State
from swfactory.profiles import PROFILES


@click.group()
@click.option("-v", "--verbose", is_flag=True)
def main(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


@main.command()
@click.option("--path", default="WORKFLOW.md", show_default=True)
@click.option("--profile", type=click.Choice(sorted(PROFILES)), default="default", show_default=True,
              help="Working style. 'superpowers' configures the worker for obra/superpowers skills.")
@click.option("--force", is_flag=True, help="Overwrite WORKFLOW.md if present.")
def init(path: str, profile: str, force: bool) -> None:
    """Write WORKFLOW.md (and, for some profiles, CLAUDE.md / .claude settings)."""
    prof = PROFILES[profile]
    p = Path(path)
    if p.exists() and not force:
        raise click.ClickException(f"{path} already exists (use --force)")
    p.write_text(prof.workflow())
    click.echo(f"wrote {path} [{profile}]")
    for rel, content in prof.extra_files.items():
        f = Path(rel)
        if f.exists():
            click.echo(f"kept  {rel} (exists)")
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        if rel.endswith(".sh"):
            f.chmod(0o755)
        click.echo(f"wrote {rel}")
    for rel, content in prof.append_files.items():
        f = Path(rel)
        if f.exists() and content.strip() in f.read_text():
            click.echo(f"kept  {rel} (already contains block)")
            continue
        with f.open("a", encoding="utf-8") as fh:
            fh.write(content)
        click.echo(f"appended {rel}")
    click.echo("next: edit tracker.repo and gate.checks, then: swfactory run --once")
    for note in prof.post_init_notes:
        click.echo(f"  - {note}")


@main.command()
@click.option("--workflow", default="WORKFLOW.md", show_default=True)
@click.option("--once", is_flag=True, help="One poll tick; wait for dispatched work to finish.")
def run(workflow: str, once: bool) -> None:
    """Poll the tracker and dispatch agents."""
    cfg = load_workflow(workflow)
    orch = Orchestrator(cfg)
    if once:
        orch.run_once()
    else:
        orch.run_forever()


@main.command()
@click.option("--workflow", default="WORKFLOW.md", show_default=True)
def status(workflow: str) -> None:
    """Show the claim ledger and live worktrees."""
    cfg = load_workflow(workflow)
    repo = Path(cfg.workspace.repo_path).resolve()
    st = State(repo / cfg.state_file)
    rows = sorted(st.records.values(), key=lambda r: r.number)
    if not rows:
        click.echo("no issues tracked yet")
    for r in rows:
        click.echo(f"#{r.number:<5} {r.status:<8} attempts={r.attempts} cost=${r.cost_usd:.2f} "
                   f"{r.branch} {r.pr_url} {r.last_error}")
    from swfactory.workspace import WorkspaceManager

    for ln in WorkspaceManager(cfg.workspace).list():
        click.echo(f"worktree  {ln}")


@main.command()
@click.option("--workflow", default="WORKFLOW.md", show_default=True)
@click.argument("issue", type=int)
@click.option("--delete-branch", is_flag=True)
def clean(workflow: str, issue: int, delete_branch: bool) -> None:
    """Remove an issue's worktree (after merge or abandonment)."""
    cfg = load_workflow(workflow)
    from swfactory.workspace import WorkspaceManager

    WorkspaceManager(cfg.workspace).remove(issue, delete_branch=delete_branch)
    click.echo(f"removed worktree for #{issue}")


@main.command()
@click.option("--workflow", default="WORKFLOW.md", show_default=True)
@click.argument("issue", type=int)
def retry(workflow: str, issue: int) -> None:
    """Reset a failed issue so the next tick re-dispatches it (relabel it ready yourself)."""
    cfg = load_workflow(workflow)
    repo = Path(cfg.workspace.repo_path).resolve()
    st = State(repo / cfg.state_file)
    st.update(issue, status="pending", attempts=0, last_error="")
    click.echo(json.dumps(st.records[issue].__dict__, indent=2))


if __name__ == "__main__":
    main()
