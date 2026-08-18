#!/usr/bin/env python3
"""Tests for migrate_to_layout_p.py — pre-v2 -> v2 Layout P migrator.

Pins the real migration moves:
  * phase2a/ -> phase1/, phase2a/extracted_docs/ -> phase1/input_doc/
  * phase2b/ -> phase2/
  * manufacturing/ -> phase3/stage5_manufacturing/
  * analog/<block>/ distributed by anchor heuristic (phase3 > phase2 >
    phase1; default phase3)
  * provenance.jsonl path rewrites carry a migration_note
Idempotency: a second run is a no-op (zero moves).
"""
from __future__ import annotations

import json
from pathlib import Path

# programs/ is on sys.path via programs/tests/conftest.py.
import migrate_to_layout_p as mod  # noqa: E402


# ----------------------------------------------------------------------
# fixture: build a pre-v2 project tree.
# ----------------------------------------------------------------------
def _build_prev2(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase2a" / "extracted_docs").mkdir(parents=True)
    (proj / "phase2a" / "extracted_docs" / "spec.md").write_text("doc")
    (proj / "phase2b").mkdir()
    (proj / "phase2b" / "rtl.v").write_text("module t; endmodule")
    (proj / "manufacturing").mkdir()
    (proj / "manufacturing" / "yield.json").write_text("{}")

    analog = proj / "analog"
    analog.mkdir()
    (analog / "ldo").mkdir()
    (analog / "ldo" / "spec.json").write_text("{}")          # -> phase1
    (analog / "pll").mkdir()
    (analog / "pll" / "layout.mag").write_text("magic")        # -> phase3
    (analog / "amp").mkdir()
    (analog / "amp" / "topology.md").write_text("topo")        # -> phase2
    (analog / "analog_block_list.json").write_text("[]")
    (analog / "hardmacro").mkdir()
    (analog / "hardmacro" / "x.lef").write_text("lef")

    (proj / "provenance.jsonl").write_text(
        "\n".join([
            json.dumps({"output": "phase2a/extracted_docs/spec.md"}),
            json.dumps({"output": "phase2b/rtl.v"}),
            json.dumps({"output": "manufacturing/yield.json"}),
        ]) + "\n"
    )
    return proj


def _run_all_steps(proj: Path, dry_run: bool = False) -> mod.MigCtx:
    ctx = mod.MigCtx(project=proj, use_git=False, dry_run=dry_run)
    mod._step1_phase2a_to_phase1(ctx)
    mod._step2_extracted_docs_to_input_doc(ctx)
    mod._step3_phase2b_to_phase2(ctx)
    mod._step4_analog_distribution(ctx)
    mod._step5_manufacturing(ctx)
    mod._step6_rewrite_provenance(ctx)
    return ctx


# ----------------------------------------------------------------------
# PASS — every canonical move applied.
# ----------------------------------------------------------------------
def test_full_migration_moves(tmp_path):
    proj = _build_prev2(tmp_path)
    ctx = _run_all_steps(proj)

    assert (proj / "phase1").is_dir()
    assert (proj / "phase1" / "input_doc" / "spec.md").is_file()
    assert (proj / "phase2" / "rtl.v").is_file()
    assert (proj / "phase3" / "stage5_manufacturing" / "yield.json").is_file()
    # analog blocks distributed by anchor heuristic
    assert (proj / "phase1" / "analog" / "ldo" / "spec.json").is_file()
    assert (proj / "phase3" / "analog" / "pll" / "layout.mag").is_file()
    assert (proj / "phase2" / "analog" / "amp" / "topology.md").is_file()
    assert (proj / "phase1" / "analog" / "analog_block_list.json").is_file()
    assert (proj / "phase3" / "analog" / "hardmacro" / "x.lef").is_file()
    # pre-v2 dirs are gone
    assert not (proj / "phase2a").exists()
    assert not (proj / "phase2b").exists()
    assert ctx.moves, "migration recorded zero moves on a pre-v2 tree"


def test_provenance_rewrite_and_note(tmp_path):
    proj = _build_prev2(tmp_path)
    _run_all_steps(proj)
    prov = (proj / "provenance.jsonl").read_text()
    recs = [json.loads(line) for line in prov.splitlines() if line.strip()]
    outputs = {r["output"] for r in recs}
    assert "phase1/input_doc/spec.md" in outputs
    assert "phase2/rtl.v" in outputs
    assert "phase3/stage5_manufacturing/yield.json" in outputs
    # every rewritten record carries an audit-trail note
    assert all("migration_note" in r for r in recs)


# ----------------------------------------------------------------------
# Idempotency — a second run does nothing.
# ----------------------------------------------------------------------
def test_idempotent_second_run(tmp_path):
    proj = _build_prev2(tmp_path)
    _run_all_steps(proj)
    ctx2 = _run_all_steps(proj)
    assert ctx2.moves == [], "second migration must be a no-op"


# ----------------------------------------------------------------------
# Analog-block classification heuristic — phase3 > phase2 > phase1.
# ----------------------------------------------------------------------
def test_classify_phase1_spec_only(tmp_path):
    b = tmp_path / "ldo"
    b.mkdir()
    (b / "spec.json").write_text("{}")
    assert mod._classify_analog_block(b) == "phase1"


def test_classify_phase2_topology(tmp_path):
    b = tmp_path / "amp"
    b.mkdir()
    (b / "topology.md").write_text("topo")
    assert mod._classify_analog_block(b) == "phase2"


def test_classify_phase2_spice_glob(tmp_path):
    b = tmp_path / "buf"
    b.mkdir()
    (b / "buf.sp").write_text("* spice")
    assert mod._classify_analog_block(b) == "phase2"


def test_classify_phase3_layout_wins_over_spec(tmp_path):
    # Most-backend anchor wins: a block with both spec and layout -> phase3.
    b = tmp_path / "pll"
    b.mkdir()
    (b / "spec.json").write_text("{}")
    (b / "layout.mag").write_text("magic")
    assert mod._classify_analog_block(b) == "phase3"


def test_classify_default_phase3_when_no_anchor(tmp_path):
    b = tmp_path / "mystery"
    b.mkdir()
    (b / "notes.txt").write_text("nothing anchoring")
    assert mod._classify_analog_block(b) == "phase3"


# ----------------------------------------------------------------------
# Path-rewrite unit behavior.
# ----------------------------------------------------------------------
def test_rewrite_str_prefix_maps():
    assert mod._rewrite_str("/abs/proj/phase2b/rtl.v") == "/abs/proj/phase2/rtl.v"
    assert mod._rewrite_str("phase2a/extracted_docs/x.md") == \
        "phase1/input_doc/x.md"
    assert mod._rewrite_str("manufacturing/y.json") == \
        "phase3/stage5_manufacturing/y.json"
    # a path with no mapped prefix is unchanged
    assert mod._rewrite_str("phase3/stage1_synth/net.v") == \
        "phase3/stage1_synth/net.v"


# ----------------------------------------------------------------------
# Edge / IO behavior — missing dir -> rc 2; dry-run touches nothing.
# ----------------------------------------------------------------------
def test_dry_run_makes_no_changes(tmp_path):
    proj = _build_prev2(tmp_path)
    ctx = _run_all_steps(proj, dry_run=True)
    # moves were planned...
    assert ctx.moves
    # ...but the pre-v2 layout is still intact on disk.
    assert (proj / "phase2a").is_dir()
    assert (proj / "phase2b").is_dir()
    assert not (proj / "phase1").exists()


def test_main_missing_project_dir_returns_2(tmp_path, monkeypatch):
    import sys
    target = tmp_path / "does_not_exist"
    monkeypatch.setattr(sys, "argv", ["migrate_to_layout_p.py", str(target)])
    assert mod.main() == 2
