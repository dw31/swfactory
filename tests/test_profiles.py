"""`swfactory init --profile` writes a loadable workflow and the supporting files."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from swfactory.cli import main
from swfactory.config import load_workflow
from swfactory.profiles import PROFILES


def _in(tmp_path: Path):
    os.chdir(tmp_path)
    return CliRunner()


def test_every_profile_renders_loadable_workflow(tmp_path):
    for name, prof in PROFILES.items():
        wf = tmp_path / f"{name}.md"
        wf.write_text(prof.workflow())
        cfg = load_workflow(wf)
        assert cfg.gate.checks, name
        # Prompt must render with and without feedback
        assert "#42" in cfg.render_prompt(
            issue=type("I", (), {"number": 42, "title": "t", "body": "b"})(), attempt=1, feedback="")
        out = cfg.render_prompt(
            issue=type("I", (), {"number": 42, "title": "t", "body": "b"})(), attempt=2, feedback="BOOM")
        assert "BOOM" in out and "Attempt 2" in out


def test_default_init(tmp_path):
    r = _in(tmp_path).invoke(main, ["init"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "WORKFLOW.md").exists()
    assert not (tmp_path / ".claude").exists()
    r2 = _in(tmp_path).invoke(main, ["init"])
    assert r2.exit_code != 0 and "already exists" in r2.output


def test_superpowers_init_writes_supporting_files_idempotently(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Existing brief\n")
    runner = _in(tmp_path)
    r = runner.invoke(main, ["init", "--profile", "superpowers"])
    assert r.exit_code == 0, r.output

    wf = load_workflow(tmp_path / "WORKFLOW.md")
    assert "Task" in wf.agent.command and "Skill" in wf.agent.command
    assert "systematic-debugging" in wf.prompt_template
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["enabledPlugins"]["superpowers@superpowers-marketplace"] is True
    gate = tmp_path / ".swfactory" / "review-gate.sh"
    assert gate.exists() and os.access(gate, os.X_OK)
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert claude_md.startswith("# Existing brief") and "unattended execution rules" in claude_md

    # second run with --force must not duplicate the CLAUDE.md block or clobber settings
    (tmp_path / ".claude" / "settings.json").write_text('{"custom": true}')
    r = runner.invoke(main, ["init", "--profile", "superpowers", "--force"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "CLAUDE.md").read_text().count("unattended execution rules") == 1
    assert json.loads((tmp_path / ".claude" / "settings.json").read_text()) == {"custom": True}
