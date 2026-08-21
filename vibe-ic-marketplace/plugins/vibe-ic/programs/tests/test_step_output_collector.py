"""Tests for step_output_collector + the dashboard per-step folder routes.

step_output_collector materializes
<project>/steps/<phase>/<stage>/<id>_<slug>/ (symlink views of each flow
step's resolved outputs) + manifests, non-invasively (the canonical phaseN/
tree is never moved). Nested by phase then stage (owner directive) so a
step's place in the flow is visible from its path, not just a flat peer
list. The web route serving those folders is path-traversal guarded.
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
    # find the step folder that captured spm.v — nested 3 levels deep now:
    # steps/<phase>/<stage>/<id>_<slug>/spm.v
    hits = list((tmp_path / "steps").glob("*/*/*/spm.v"))
    assert hits, "spm.v should be symlinked under steps/<phase>/<stage>/<id>_<slug>/"
    link = hits[0]
    assert link.is_symlink()
    assert link.resolve() == (tmp_path / "phase2/stage1/rtl/spm.v").resolve()
    # manifest present + well-formed, and carries the phase/stage that
    # produced this exact nesting
    man = json.loads((link.parent / "outputs.json").read_text())
    assert man["id"] and man["outputs"]
    assert man["phase"] and man["stage"]
    assert link.parent.relative_to(tmp_path / "steps") == Path(man["folder"])


def test_folder_is_nested_phase_then_stage(tmp_path):
    """The owner directive this collector implements: a step's directory
    encodes WHERE in the flow it sits, not just a flat peer list."""
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    idx = json.loads((tmp_path / "steps/index.json").read_text())
    step1 = next(s for s in idx["steps"] if s["id"] == "1")
    assert step1["folder"] == f"{step1['phase']}/{step1['stage']}/1_spec_to_rtl"
    assert (tmp_path / "steps" / step1["folder"]).is_dir()


def test_two_steps_in_different_stages_do_not_collide(tmp_path):
    """DIRECTION 1: nesting must not accidentally MERGE unrelated steps just
    because a flat id/slug happened to be unique before — every step gets
    its own leaf directory regardless of how many share a phase or stage."""
    _mk_project(tmp_path)
    SOC.materialize(tmp_path)
    idx = json.loads((tmp_path / "steps/index.json").read_text())
    folders = [s["folder"] for s in idx["steps"]]
    assert len(folders) == len(set(folders)), "duplicate step folder paths"


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
    # a legitimate file inside a step folder resolves. `folder` is now a
    # multi-segment relative path (phase/stage/id_slug) — the dashboard's own
    # `_steps_root(project) / folder` must nest on that string with no
    # change on its side (Path's "/" already handles embedded "/"), which is
    # exactly what this test is pinning.
    idx = json.loads((tmp_path / "steps/index.json").read_text())
    folder = next(s["folder"] for s in idx["steps"]
                  if (tmp_path / "steps" / s["folder"] / "spm.v").exists())
    ok = W._step_file_response(str(tmp_path), folder, "spm.v")
    assert ok is not None and b"module spm" in ok[0]
    # traversal attempts are rejected
    assert W._step_file_response(str(tmp_path), "..", "x") is None
    assert W._step_file_response(str(tmp_path), folder, "../../etc/passwd") is None
    assert W._step_file_response(str(tmp_path), folder, "nope.xyz") is None
    # traversal THROUGH the now-multi-segment folder itself must still be
    # rejected — a nested folder string is more surface for ".." to hide in
    assert W._step_file_response(str(tmp_path), folder + "/../../..", "spm.v") is None


def test_migrating_from_a_prior_flat_layout_prunes_the_old_folder(tmp_path):
    """A run materialized under the OLD flat `<id>_<slug>/` scheme, then
    re-materialized under this nested one, must not leave the old folder
    sitting next to the new tree forever — it would look like a second,
    increasingly stale copy of the same step's outputs."""
    _mk_project(tmp_path)
    steps_root = tmp_path / "steps"
    old_folder = steps_root / "1_spec_to_rtl"
    old_folder.mkdir(parents=True)
    (old_folder / "spm.v").symlink_to(tmp_path / "phase2/stage1/rtl/spm.v")
    (old_folder / "outputs.json").write_text(json.dumps(
        {"id": "1", "name": "Spec-to-RTL", "status": "pass",
         "folder": "1_spec_to_rtl", "outputs": []}))
    (steps_root / "index.json").write_text(json.dumps({"steps": [
        {"id": "1", "name": "Spec-to-RTL", "status": "pass",
         "folder": "1_spec_to_rtl", "n_outputs": 0}]}))

    SOC.materialize(tmp_path)

    assert not old_folder.exists(), "stale flat-layout folder must be pruned"
    idx = json.loads((steps_root / "index.json").read_text())
    step1 = next(s for s in idx["steps"] if s["id"] == "1")
    assert "/" in step1["folder"], "the new run must be nested"
    assert (steps_root / step1["folder"] / "spm.v").is_symlink()


def test_pruning_removes_now_empty_phase_and_stage_parents(tmp_path):
    """DIRECTION 1 sibling: pruning a stale leaf must not leave an empty
    phase/ or stage/ directory behind as debris, but must also not remove
    anything ABOVE `steps/` itself."""
    _mk_project(tmp_path)
    steps_root = tmp_path / "steps"
    stale = steps_root / "phaseX" / "stageY" / "1_old_name"
    stale.mkdir(parents=True)
    (steps_root / "index.json").write_text(json.dumps({"steps": [
        {"id": "1", "name": "Old Name", "status": "pass",
         "folder": "phaseX/stageY/1_old_name", "n_outputs": 0}]}))

    SOC.materialize(tmp_path)

    assert not stale.exists()
    assert not (steps_root / "phaseX").exists(), "emptied stage/phase left behind"
    assert steps_root.is_dir(), "must never remove steps/ itself"


# ── gatekeeper, at land time ───────────────────────────────────────────────
def test_prune_never_escapes_steps_root(tmp_path):
    """THE LOAD-BEARING CASE. `_prune_stale_folders` reads its folder list from
    a PRIOR index.json — a file on disk, not a value the call computed — and it
    DELETES.

    Measured before the guard: a list entry of `../../OUTSIDE` made
    `steps_root / rel` resolve outside the project, and the loop unlinked a
    symlink and an `outputs.json` in an unrelated directory and then rmdir'd
    it. The unlink is bounded to symlinks and `outputs.json`, but bounded
    damage is still damage, and deletion code does not get to assume its input
    is well formed.
    """
    import step_output_collector as C

    outside = tmp_path / "OUTSIDE"
    outside.mkdir()
    (tmp_path / "real.txt").write_text("x")
    (outside / "link").symlink_to(tmp_path / "real.txt")
    (outside / "outputs.json").write_text("{}")

    steps_root = tmp_path / "proj" / "steps"
    steps_root.mkdir(parents=True)

    C._prune_stale_folders(steps_root, ["../../OUTSIDE"], set())

    assert outside.is_dir(), "an escaping entry deleted a directory outside the project"
    assert sorted(p.name for p in outside.iterdir()) == ["link", "outputs.json"]


def test_prune_still_removes_a_genuinely_stale_folder(tmp_path):
    """The paired half, and the one that keeps the guard from being a way to
    disable the feature: a stale folder INSIDE steps_root must still go, and
    its now-empty phase/stage parents with it. That is the flat-to-nested
    migration this change exists to make survivable."""
    import step_output_collector as C

    steps_root = tmp_path / "steps"
    stale = steps_root / "phase1" / "stage1" / "01_old_name"
    stale.mkdir(parents=True)
    (tmp_path / "target.txt").write_text("x")
    (stale / "artifact.v").symlink_to(tmp_path / "target.txt")
    (stale / "outputs.json").write_text("{}")

    C._prune_stale_folders(steps_root, ["phase1/stage1/01_old_name"], set())

    assert not stale.exists()
    assert not (steps_root / "phase1").exists(), "empty parents were not pruned"
    assert (tmp_path / "target.txt").is_file(), "the symlink TARGET was deleted"


def test_prune_keeps_a_folder_the_current_run_still_produces(tmp_path):
    """A folder in both the prior and the current set is not stale."""
    import step_output_collector as C

    steps_root = tmp_path / "steps"
    keep = steps_root / "phase2" / "stage1" / "07_rtl"
    keep.mkdir(parents=True)
    (keep / "outputs.json").write_text("{}")

    C._prune_stale_folders(steps_root, ["phase2/stage1/07_rtl"],
                           {"phase2/stage1/07_rtl"})
    assert keep.is_dir() and (keep / "outputs.json").is_file()
