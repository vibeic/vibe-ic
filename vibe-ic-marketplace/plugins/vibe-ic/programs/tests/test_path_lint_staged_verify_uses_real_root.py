"""Staged verification must judge containment against the REAL project root.

WHAT WENT WRONG (measured, u_hawaii_adc round-5b @ v1.14.77 — ONE round after
the project-internal rung landed): A3's `verify_with_checkers` copies the deck
into a TemporaryDirectory and runs the checkers on that staging tree, so the
path lint's containment rung tested `/tmp/a3verify_*` — and the deck's correct
binding of the REAL project's `input/pdk/models/<lib>` read as a foreign
absolute path all over again. Same dead-end (NETLIST_REJECTED_BY_CHECKS →
WAIVE → A4 blocked), one directory level deeper.

THE RULE. The lint gains `--project-root` naming the real project; A3's
staged verification passes it. Containment is judged against the tree that
will actually exist on disk. Without the flag nothing changes (pin).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent))

PROG = TESTS.parent / "analog_netlist_path_lint.py"


def _staging(tmp_path: Path, lib_path: str) -> Path:
    stage = tmp_path / "staging"
    bdir = stage / "phase3" / "analog" / "blk"
    bdir.mkdir(parents=True)
    (bdir / "blk.sp").write_text(
        f"* blk\n.lib {lib_path} mos_tt\n.subckt blk a b\nr1 a b 1k\n"
        f".ends blk\n")
    return stage


def _run(stage: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(stage), "--json",
         str(stage / "r.json"), *extra],
        capture_output=True, text=True, timeout=60)


def test_staged_lint_with_real_root_accepts_the_projects_own_binding(
        tmp_path: Path) -> None:
    real = tmp_path / "real_project"
    lib = real / "input" / "pdk" / "models" / "cornerMOShv.lib"
    lib.parent.mkdir(parents=True)
    lib.write_text("* model lib\n")
    stage = _staging(tmp_path, str(lib))
    r = _run(stage, "--project-root", str(real))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((stage / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "PROJECT_INTERNAL_ABSOLUTE_PATH" in rules


def test_without_the_flag_the_staging_tree_still_refuses(
        tmp_path: Path) -> None:
    """Pin: containment stays strict when no real root is named — a genuinely
    foreign path in a staging tree must not ride along."""
    real = tmp_path / "real_project"
    lib = real / "input" / "pdk" / "models" / "cornerMOShv.lib"
    lib.parent.mkdir(parents=True)
    lib.write_text("* model lib\n")
    stage = _staging(tmp_path, str(lib))
    r = _run(stage)
    assert r.returncode == 1


def test_real_root_does_not_admit_paths_outside_it(tmp_path: Path) -> None:
    stage = _staging(tmp_path, "/home/somebody_else/models/foo.lib")
    r = _run(stage, "--project-root", str(tmp_path / "real_project"))
    assert r.returncode == 1


def test_a3_verify_threads_the_real_project(tmp_path: Path) -> None:
    """Integration: verify_with_checkers(real_project=...) lets a deck bound
    to the real project's own input/pdk pass the checker set's path lint."""
    import analog_a3_netlist_emit as A3
    real = tmp_path / "proj"
    lib = real / "input" / "pdk" / "models" / "cornerMOShv.lib"
    lib.parent.mkdir(parents=True)
    lib.write_text("* model lib\n")
    sp = (f"* blk\n.lib {lib} mos_tt\n"
          f".subckt blk a b\nr1 a b 1k\n.ends blk\n")
    ok, findings = A3.verify_with_checkers(
        "blk", sp, None, design_content="structure_only", real_project=real)
    plint = [f for f in findings if f.get("checker") == "path_lint"]
    assert plint and plint[0]["rc"] == 0, findings
