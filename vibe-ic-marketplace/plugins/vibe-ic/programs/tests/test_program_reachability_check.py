#!/usr/bin/env python3
"""Wave 81 — tests for tools/program_reachability_check.py.

Uses temporary fixture trees so the audit logic is tested in isolation
from the live plugin layout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _plugin_tree import repo_resource_or_skip

# flow #486: program_reachability_check.py is a monorepo-only audit tool
# that is NOT shipped in the flattened install cache. Resolve it lazily via
# repo_resource_or_skip so the fixture builder yields a NAMED skip there
# instead of a FileNotFoundError ERROR.
# flow #488: the tool lives under vibe-ic-marketplace/tools/ (NOT repo-root
# tools/ — the #486 sweep mis-anchored it and these 4 tests went dormant on
# BOTH trees). marketplace-relative path + required_on_source=True so a
# source-tree miss is a loud path-misplaced FAIL, never a misleading
# not-shipped skip.
TOOL_REL = ("vibe-ic-marketplace", "tools", "program_reachability_check.py")


def _build_fixture(root: Path, *,
                   reachable_via_import: bool = False,
                   reachable_via_yaml: bool = False,
                   helper_imported: bool = False,
                   helper_only_referenced_in_yaml: bool = False) -> None:
    """Lay out a fake AI_IC_design / vibe-ic-marketplace / plugins / vibe-ic
    tree with deterministic content. The tool resolves ROOT via
    parents[3] from its own location, so we copy the real tool into
    `root/vibe-ic-marketplace/tools/program_reachability_check.py`."""
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    (plugin / "flow").mkdir(parents=True, exist_ok=True)

    # Always present: a "core" peer file used to hold imports / mentions.
    (plugin / "programs" / "core_runner.py").write_text("# placeholder\n")

    # Entry-point program under audit.
    (plugin / "programs" / "demo_check.py").write_text(
        '"""demo gate."""\n\nif __name__ == "__main__": pass\n'
    )

    # Helper program under audit.
    (plugin / "programs" / "_demo_helper.py").write_text(
        '"""demo helper."""\n\ndef ping(): return 1\n'
    )

    # Wire references on demand.
    core_text = "# peer\n"
    if reachable_via_import:
        core_text += "from demo_check import main as _demo_main\n"
    if helper_imported:
        core_text += "from _demo_helper import ping as _ping\n"
    (plugin / "programs" / "core_runner.py").write_text(core_text)

    yaml_text = "steps: []\n"
    if reachable_via_yaml:
        yaml_text = "steps:\n  - command: demo_check\n"
    if helper_only_referenced_in_yaml:
        yaml_text += "  - command: _demo_helper\n"
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(yaml_text)

    # Copy the tool into the fixture root so its parents[3] lands on
    # `root` and PROGRAMS resolves to the fixture programs/.
    tool = repo_resource_or_skip(*TOOL_REL, required_on_source=True)  # cache: named skip; source-miss: FAIL (#488)
    tool_dir = root / "vibe-ic-marketplace" / "tools"
    tool_dir.mkdir(parents=True)
    shutil.copyfile(tool, tool_dir / "program_reachability_check.py")


def _run(root: Path, *extra: str) -> dict:
    """Invoke the copied tool, write JSON, and return the parsed report."""
    out = root / "report.json"
    cp = subprocess.run(
        [
            sys.executable,
            str(root / "vibe-ic-marketplace" / "tools"
                / "program_reachability_check.py"),
            "--json", str(out),
            *extra,
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert cp.returncode in (0, 1), (cp.stdout, cp.stderr)
    return json.loads(out.read_text())


def test_entry_point_reachable_via_python_import(tmp_path):
    _build_fixture(tmp_path, reachable_via_import=True)
    rep = _run(tmp_path)
    by = {r["name"]: r for r in rep["rows"]}
    assert by["demo_check"]["status"] == "REACHABLE"
    assert by["demo_check"]["python_import_hits"]


def test_entry_point_unreachable(tmp_path):
    _build_fixture(tmp_path)  # no wiring at all
    rep = _run(tmp_path)
    by = {r["name"]: r for r in rep["rows"]}
    assert by["demo_check"]["status"] == "POTENTIALLY_UNREACHABLE"
    assert "demo_check" in rep["unreachable"]


def test_helper_reachable_via_import_only(tmp_path):
    """Helpers (leading-underscore names) only count Python imports —
    a helper referenced solely in YAML is *not* reachable."""
    _build_fixture(tmp_path, helper_imported=True)
    rep = _run(tmp_path)
    by = {r["name"]: r for r in rep["rows"]}
    assert by["_demo_helper"]["status"] == "REACHABLE"
    assert by["_demo_helper"]["python_import_hits"]


def test_entry_point_reachable_via_yaml_command(tmp_path):
    _build_fixture(tmp_path, reachable_via_yaml=True)
    rep = _run(tmp_path)
    by = {r["name"]: r for r in rep["rows"]}
    assert by["demo_check"]["status"] == "REACHABLE"
    assert by["demo_check"]["yaml_command_hits"]
