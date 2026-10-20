"""OpenCode adapter: managed AGENTS.md region, plugin render, and the
payload contract the plugin depends on.

The plugin is TypeScript and cannot run under pytest, so the last test
pins the part that actually breaks the gate when it drifts: the shape of
the payload it hands the Python hooks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from episteme import cli as ecli
from episteme.adapters import opencode as adapter

REPO = Path(__file__).resolve().parents[1]


def _sync(home: Path) -> Path:
    root = home / ".config" / "opencode"
    root.mkdir(parents=True, exist_ok=True)
    orig = ecli.HOME
    ecli.HOME = home
    try:
        assert adapter.sync() is True
    finally:
        ecli.HOME = orig
    return root


def test_sync_preserves_operator_agents_md_and_backs_it_up_once(tmp_path):
    root = tmp_path / ".config" / "opencode"
    root.mkdir(parents=True)
    original = "# my own rules\n\nhand-authored\n"
    (root / "AGENTS.md").write_text(original, encoding="utf-8")

    _sync(tmp_path)

    text = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert original.strip() in text
    begin, end = ecli._managed_markers(adapter.OPENCODE_MARKER)
    assert begin in text and end in text

    backups = list(root.glob("AGENTS.md.bak-episteme-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original

    # A second sync rewrites the same block in place: one block, no
    # duplicate, operator text intact, no further backup.
    _sync(tmp_path)
    resynced = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert resynced.count(begin) == 1
    assert original.strip() in resynced
    assert len(list(root.glob("AGENTS.md.bak-episteme-*"))) == 1


def test_plugin_is_rendered_with_no_placeholders(tmp_path):
    root = _sync(tmp_path)

    plugin = (root / "plugins" / adapter.PLUGIN_NAME).read_text(encoding="utf-8")
    assert "__EPISTEME_" not in plugin
    # A named id/setup export is listed by `opencode plugin list` but never
    # instantiated; the loader only runs the default export.
    assert 'export default { id: "episteme", setup }' in plugin
    assert str(REPO / "core" / "hooks") in plugin
    for script in (
        "block_dangerous.py",
        "reasoning_surface_guard.py",
        "calibration_telemetry.py",
        "session_context.py",
    ):
        assert script in plugin


def test_guard_reads_the_payload_the_plugin_builds(tmp_path, monkeypatch):
    """An OpenCode `shell` call arrives as Bash + args.command, which the
    gate must block; an ordinary command must pass."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("EPISTEME_HOME", str(tmp_path / ".episteme"))
    guard = REPO / "core" / "hooks" / "reasoning_surface_guard.py"

    def call(command: str) -> subprocess.CompletedProcess:
        payload = {
            "session_id": "ses_opencode_test",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(tmp_path),
        }
        return subprocess.run(
            [sys.executable, str(guard)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=tmp_path,
        )

    blocked = call("git push origin master")
    assert blocked.returncode == 2
    assert blocked.stderr.strip()

    assert call("git status").returncode == 0


def test_sync_is_a_noop_without_the_config_dir(tmp_path):
    orig = ecli.HOME
    ecli.HOME = tmp_path
    try:
        assert adapter.sync() is False
    finally:
        ecli.HOME = orig
