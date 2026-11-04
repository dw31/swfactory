"""swfactory: a thin software-factory orchestrator.

Intake (issue tracker) -> isolated worktree -> Claude Code run -> verification gate
-> retry with failure log -> push branch + PR -> human merge gate.
"""

__version__ = "0.2.0"
