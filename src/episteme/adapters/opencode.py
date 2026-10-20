"""OpenCode adapter. Mounts agents, skills and a managed region of
``~/.config/opencode/AGENTS.md``, and installs the V2 plugin that bridges
OpenCode's tool hooks to the Python gates.

## Why a plugin, not config

OpenCode V2 has no hook table in its config: a plugin is the only thing
that can veto a tool call, via a throw from ``tool.execute.before``. So the
gate itself stays in ``core/hooks`` — the same scripts Claude Code runs —
and the plugin is a transport, not a reimplementation. One gate, two
runtimes.

## Why a managed REGION, not a managed file

``~/.config/opencode/AGENTS.md`` is the operator's own primary contract.
Overwriting it would destroy text that exists nowhere else (the failure
class E166 recovered from). episteme owns only the text between its
markers; every byte outside them survives every sync. The file is backed
up once, before the first block is written, per the operator's config-edit
rule.
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

from .. import cli as _cli


OPENCODE_MARKER = "episteme:opencode"
PLUGIN_NAME = "episteme.ts"
PLUGIN_SOURCE = _cli.REPO_ROOT / "core" / "adapters" / "opencode" / "plugin.ts"


def _compose_context() -> str:
    """The managed block written into ~/.config/opencode/AGENTS.md.

    Path-references the operator's real memory files rather than inlining
    them: the files are the source of truth and a copy here would rot.
    """
    memory = _cli.REPO_ROOT / "core" / "memory" / "global"
    digest = _cli._resolve_memory_file("runtime_digest")
    feedback = _cli._resolve_memory_file("agent_feedback")
    python_policy = _cli._resolve_memory_file("python_runtime_policy")
    return (
        "# episteme — operator governance contract\n\n"
        "Managed by `episteme sync`. Edit the source of truth in\n"
        f"`{memory}`, not this block — changes here are overwritten.\n\n"
        "## Always-on\n\n"
        f"- `{digest}` — the single control surface: precedence contract,\n"
        "  hard rules, decision posture, session flow.\n"
        f"- `{feedback}` — behavioral rules learned across sessions.\n"
        f"- `{python_policy}` — Python runtime policy for this machine.\n\n"
        "## Read on demand\n\n"
        f"- `{memory / 'cognitive_profile.md'}` — mental models + Decision Protocol\n"
        f"- `{memory / 'workflow_policy.md'}` — the five stages, signal-over-noise rules\n"
        f"- `{memory / 'operator_profile.md'}` — per-axis operator profile\n"
        f"- `{memory / 'overview.md'}` — project topology\n\n"
        "## Enforcement in OpenCode\n\n"
        "`~/.config/opencode/plugins/episteme.ts` runs the same PreToolUse\n"
        "gates as Claude Code: high-impact commands and sensitive-path edits\n"
        "block until a Reasoning Surface exists at `.episteme/`.\n\n"
        "## Precedence with the rest of this file\n\n"
        "This block is additive. Where a directive elsewhere in AGENTS.md\n"
        "conflicts with the governance posture above — most likely around\n"
        "autonomy versus gating irreversible operations — the operator's\n"
        "own text in this file wins, and the conflict should be raised\n"
        "rather than silently resolved in either direction.\n"
    )


def _backup_once(agents_md: Path, marker: str) -> None:
    """Back up AGENTS.md before episteme first writes into it."""
    if not agents_md.exists():
        return
    existing = agents_md.read_text(encoding="utf-8")
    if _managed_markers_present(existing, marker):
        return
    backup = agents_md.with_name(
        f"{agents_md.name}.bak-episteme-{date.today().isoformat()}"
    )
    if not backup.exists():
        shutil.copy2(agents_md, backup)


def _managed_markers_present(existing: str, marker: str) -> bool:
    begin, end = _cli._managed_markers(marker)
    return begin in existing and end in existing


def install_plugin(opencode_root: Path) -> Path:
    """Render the plugin template with this checkout's paths and write it.

    Paths are baked at sync time so the plugin needs no lookup at runtime;
    the cost is that moving the checkout needs another sync.
    """
    body = PLUGIN_SOURCE.read_text(encoding="utf-8")
    body = body.replace("__EPISTEME_PYTHON__", sys.executable)
    body = body.replace("__EPISTEME_HOOKS__", str(_cli.REPO_ROOT / "core" / "hooks"))
    dest = opencode_root / "plugins" / PLUGIN_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.read_text(encoding="utf-8") == body:
        return dest
    dest.write_text(body, encoding="utf-8")
    return dest


def sync() -> bool:
    """Mount agents, managed skills, the AGENTS.md region and the plugin.

    Returns True when OpenCode was found and synced, False when its config
    directory is absent. Never removes or rewrites operator-authored text.
    """
    opencode_root = _cli.HOME / ".config" / "opencode"
    if not opencode_root.is_dir():
        return False

    for agent_file in sorted((_cli.REPO_ROOT / "core" / "agents").glob("*.md")):
        _cli._copy_file(agent_file, opencode_root / "agents" / agent_file.name)

    for skill_dir in _cli._managed_skills():
        _cli._copy_tree(skill_dir, opencode_root / "skills" / skill_dir.name)

    agents_md = opencode_root / "AGENTS.md"
    _backup_once(agents_md, OPENCODE_MARKER)
    _cli._write_managed_file(
        agents_md,
        _compose_context(),
        marker=OPENCODE_MARKER,
    )

    install_plugin(opencode_root)
    return True


__all__ = ["sync", "install_plugin", "OPENCODE_MARKER", "PLUGIN_NAME"]
