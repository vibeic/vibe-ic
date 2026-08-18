#!/usr/bin/env python3
"""Tests for foundry_handoff_pack_gen.py (v1.6.36 — Step 35 skeleton)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "foundry_handoff_pack_gen.py")


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def test_emits_all_skeleton_artefacts(tmp_path):
    """Verifies that the generator emits the canonical handoff files.
    #446: NO fabricated scribe .gds — the foundry-supplied need is a
    plainly-named TODO note instead."""
    r = _run(tmp_path)
    assert r.returncode == 0
    handoff = tmp_path / "phase3/stage4/foundry_handoff"
    assert (handoff / "mask_spec.json").is_file()
    assert (handoff / "wat_plan.json").is_file()
    assert (handoff / "corner_test_vectors.json").is_file()
    assert not (handoff / "scribe_line_layout.gds").exists()
    assert (handoff / "scribe_line_layout.PENDING_FOUNDRY.txt").is_file()
    assert (handoff / "README.txt").is_file()


def test_emits_audit_summary(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    audit = tmp_path / "reports/phase3/foundry_handoff_audit.json"
    assert audit.is_file()
    payload = json.loads(audit.read_text())
    assert payload["verdict"] == "SKELETON_EMITTED"
    assert "design_facts" in payload


def test_includes_design_facts_from_synth_log(tmp_path):
    """Number-of-cells from synth.log lands in design_facts."""
    (tmp_path / "phase2/stage2/synth").mkdir(parents=True)
    (tmp_path / "phase2/stage2/synth/synth.log").write_text(
        "Yosys 0.62\nNumber of cells: 12345\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    audit = json.loads(
        (tmp_path / "reports/phase3/foundry_handoff_audit.json").read_text())
    assert audit["design_facts"]["cell_count"] == 12345


def test_detects_process_node_from_pdk_lib(tmp_path):
    """180 in lib filename → process_nm = 180."""
    (tmp_path / "input/pdk/liberty").mkdir(parents=True)
    (tmp_path / "input/pdk/liberty/commercial_pdk_180nm_typ.lib").write_text("library(x);")
    r = _run(tmp_path)
    audit = json.loads(
        (tmp_path / "reports/phase3/foundry_handoff_audit.json").read_text())
    assert audit["design_facts"]["process_nm"] == 180


def test_mask_spec_includes_pending_foundry_markers(tmp_path):
    """#449: foundry-supplied fields use the structured
    PENDING_FOUNDRY_* namespace (the checker lists them as open items)
    — never TODO_*, which the checker rightly ERRORs as design-derivable
    residue."""
    r = _run(tmp_path)
    mask = json.loads(
        (tmp_path / "phase3/stage4/foundry_handoff/mask_spec.json").read_text())
    assert "PENDING_FOUNDRY_mask_layers" in mask
    assert "PENDING_FOUNDRY_reticle_steppers" in mask
    assert not any(k.startswith("TODO_") for k in mask)


def test_vacuous_pass_when_project_missing():
    r = subprocess.run(
        [sys.executable, str(PROG), "/no/such/foundry/project"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
