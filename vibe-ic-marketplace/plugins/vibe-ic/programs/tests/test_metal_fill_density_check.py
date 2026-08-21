#!/usr/bin/env python3
"""Tests for metal_fill_density_check.py (G5: Metal Fill + Density)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "metal_fill_density_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_pass_filled_def(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("x" * 1000)
    (pnr / "filled.def").write_text("x" * 2000)
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True


def test_done_marker_alone_is_not_substance(tmp_path):
    # #445: the done marker alone (no fillers, no growth, no density
    # data) substantiates nothing — the gate FAILs it now.
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "metal_fill.done").write_text("done")
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_fill(tmp_path):
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_filled_not_larger_no_substance_fails(tmp_path):
    # #445: shrinking/unchanged filled.def with no other substance is a
    # no-op fill — FAIL (was warning-only pre-v0.2.75).
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("x" * 2000)
    (pnr / "filled.def").write_text("x" * 500)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_density_out_of_bounds(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "filled.def").write_text("x" * 2000)
    _write_json(tmp_path / "reports" / "phase3" / "density.json", {
        "layers": [
            {"name": "M1", "density_pct": 50.0},
            {"name": "M2", "density_pct": 95.0},
        ]
    })
    result = _run(tmp_path)
    assert result.returncode == 1


def test_pass_density_in_bounds(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "filled.def").write_text("x" * 2000)
    _write_json(tmp_path / "reports" / "phase3" / "density.json", {
        "layers": [
            {"name": "M1", "density_pct": 45.0},
            {"name": "M2", "density_pct": 60.0},
        ]
    })
    result = _run(tmp_path)
    assert result.returncode == 0


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2


# ── #364: a byte-identical filled.def is a no-op, and no hatch may excuse it ──
# Measured on spm x gf180mcuD (plugin 1.6.7): filled.def and routed.def
# identical at 472,921 B, zero FILLWIRES, `metal_fill.done` present, step-34
# PASS — and the shipped GDS then measured 6 whole-die density violations
# (M1-MT under the deck's per-layer floor). It passed because the ERROR-level
# substance test can be satisfied by an IN-WINDOW per-layer density reading,
# while the rule it stands in for is per-layer over the WHOLE DIE: an escape
# hatch whose evidence is measured at a different scope than the thing it
# excuses.

def _noop_pair(tmp_path, body: str = "DESIGN x ;\nEND DESIGN\n"):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text(body)
    (pnr / "filled.def").write_text(body)          # BYTE-IDENTICAL
    (pnr / "metal_fill.done").write_text("done\n")
    return pnr


def test_364_byte_identical_filled_def_fails(tmp_path):
    """The measured shape: marker present, DEFs identical. Fill emitted
    nothing, so it must not pass."""
    _noop_pair(tmp_path)
    r = _run(tmp_path)
    assert r.returncode != 0, r.stdout
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["summary"]["pass"] is False
    assert any(f.get("code") == "FILL_NOOP" or "FILL_NOOP" in str(f)
               for f in rep.get("findings", [])), rep


def test_364_in_window_density_cannot_excuse_a_byte_identical_noop(tmp_path):
    """THE regression. In-window per-layer density is the hatch the measured
    run went through: a window can read fine while the die is under the
    deck's floor. It must not stand in for fill that produced not one
    byte."""
    _noop_pair(tmp_path)
    _write_json(tmp_path / "reports" / "phase3" / "density.json", {
        "layers": [{"name": "M1", "density_pct": 45.0},
                   {"name": "M2", "density_pct": 60.0}]})
    r = _run(tmp_path)
    assert r.returncode != 0, r.stdout
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["summary"]["pass"] is False


def test_364_real_fill_growth_still_passes(tmp_path):
    """NO-LEAK: the new rule must only fire on byte-identity. A DEF that
    actually grew is untouched."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("x" * 1000)
    (pnr / "filled.def").write_text("x" * 2000)
    (pnr / "metal_fill.done").write_text("done\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_364_same_size_but_different_bytes_is_not_a_noop(tmp_path):
    """Equal SIZE is not equal CONTENT — the check must compare bytes, or a
    re-encoding of the same length would be mislabelled a no-op."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_text("A" * 2000)
    (pnr / "filled.def").write_text("B" * 2000)     # same size, different
    (pnr / "metal_fill.done").write_text("done\n")
    _write_json(tmp_path / "reports" / "phase3" / "density.json", {
        "layers": [{"name": "M1", "density_pct": 45.0}]})
    r = _run(tmp_path)
    rep = json.loads((tmp_path / "out.json").read_text())
    assert not any("FILL_NOOP" in str(f) for f in rep.get("findings", [])), rep


def test_364_attested_sparse_die_skip_still_exempt(tmp_path):
    """#684's attested sparse-die skip is a RECORDED engineering decision
    that fill was deliberately not run — it stays exempt, so this change
    does not re-break the case that exemption exists for."""
    _noop_pair(tmp_path)
    _write_json(tmp_path / "reports" / "phase3" / "sparse_die_skip.json",
                {"fill_skipped": True,
                 "reason": "sub-threshold sparse fixed wrapper",
                 "core_utilization_pct": 3.1})
    r = _run(tmp_path)
    rep = json.loads((tmp_path / "out.json").read_text())
    assert not any("FILL_NOOP" in str(f) for f in rep.get("findings", [])), rep
