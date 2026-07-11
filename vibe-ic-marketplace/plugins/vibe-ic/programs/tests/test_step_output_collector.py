"""Tests for step_output_collector + the dashboard per-step folder routes.

step_output_collector materializes <project>/steps/<id>_<slug>/ (symlink views
of each flow step's resolved outputs) + manifests, non-invasively (the canonical
phaseN/ tree is never moved). The web route serving those folders is path-
traversal guarded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import step_output_collector as SOC  # noqa: E402


def _mk_project(tmp: Path) -> Path:
    # a real flow-step output: step 1 (Spec-to-RTL) → phase2/stage1/rtl/*
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text("module spm; endmodule\n")
    return tmp


def test_materialize_creates_steps_tree(tmp_path):
    _mk_project(tmp_path)
    res = SOC.materialize(tmp_path)
    assert res["n_steps"] > 0
    steps_root = tmp_path / "steps"
    assert (steps_root / "index.json").is_file()
    idx = json.loads((steps_root / "index.json").read_text())
    assert isinstance(idx.get("steps"), list) and idx["steps"]


def test_authored_rtl_is_symlinked_into_its_step_folder(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    # find the step folder that captured spm.v
    hits = list((tmp_path / "steps").glob("*/spm.v"))
    assert hits, "spm.v should be symlinked under some steps/<id>_<slug>/"
    link = hits[0]
    assert link.is_symlink()
    assert link.resolve() == (tmp_path / "phase2/stage1/rtl/spm.v").resolve()
    # manifest present + well-formed
    man = json.loads((link.parent / "outputs.json").read_text())
    assert man["id"] and man["outputs"]


def test_canonical_tree_is_not_moved(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    # the original file stays exactly where inter-step contracts expect it
    assert (tmp_path / "phase2/stage1/rtl/spm.v").is_file()
    assert not (tmp_path / "phase2/stage1/rtl/spm.v").is_symlink()


def test_idempotent(tmp_path):
    _mk_project(tmp_path)
    a = SOC.materialize(tmp_path)
    b = SOC.materialize(tmp_path)   # second run must not error or duplicate
    assert a["n_steps"] == b["n_steps"]


def test_web_stepfile_path_traversal_guarded(tmp_path):
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    import flow_dashboard_web as W
    # a legitimate file inside a step folder resolves
    folder = next(p.name for p in (tmp_path / "steps").iterdir()
                  if p.is_dir() and (p / "spm.v").exists())
    ok = W._step_file_response(str(tmp_path), folder, "spm.v")
    assert ok is not None and b"module spm" in ok[0]
    # traversal attempts are rejected
    assert W._step_file_response(str(tmp_path), "..", "x") is None
    assert W._step_file_response(str(tmp_path), folder, "../../etc/passwd") is None
    assert W._step_file_response(str(tmp_path), folder, "nope.xyz") is None
