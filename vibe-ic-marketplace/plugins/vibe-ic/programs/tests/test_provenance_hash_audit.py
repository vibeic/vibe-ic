#!/usr/bin/env python3
"""Tests for provenance_hash_audit.py"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "provenance_hash_audit.py"


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw
    )


def _write_report(project: Path, name: str, report: dict) -> Path:
    rdir = project / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    rp = rdir / name
    rp.write_text(json.dumps(report, indent=2))
    return rp


def _stale_findings(result_json: dict):
    return [f for f in result_json["findings"] if f["category"] == "STALE_OUTPUT"]


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_empty_project(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# ORGANIC-20260531-provenance-audit-reads-bare-artefact-labels-as-paths
# ---------------------------------------------------------------------------


def test_bare_labels_with_mapping_all_present_pass(tmp_path):
    """(a) artefacts=[label,...] + artefact_paths -> all mapped files exist.

    PASS, zero STALE_OUTPUT. The bare labels def/gds/netlist must NOT be
    resolved against the project root.
    """
    # Stage the real artefacts the mapping points at.
    (tmp_path / "phase3").mkdir(parents=True, exist_ok=True)
    for rel in ("phase3/spm.def", "phase3/spm.gds", "phase3/spm_net.v"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")

    _write_report(
        tmp_path,
        "spare_cell_preservation.json",
        {
            "status": "PASS",
            "artefacts": ["def", "gds", "netlist"],
            "artefact_paths": {
                "def": "phase3/spm.def",
                "gds": "phase3/spm.gds",
                "netlist": "phase3/spm_net.v",
            },
        },
    )

    r = _run([str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    assert out["summary"]["pass"] is True
    assert _stale_findings(out) == []
    assert r.returncode == 0


def test_mapped_path_absent_emits_one_stale_against_real_path(tmp_path):
    """(b) same shape but one mapped path absent -> exactly ONE STALE_OUTPUT
    naming the REAL missing path, not the bare label."""
    (tmp_path / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/spm.def").write_text("x")
    (tmp_path / "phase3/spm.gds").write_text("x")
    # netlist deliberately NOT created -> genuinely absent

    _write_report(
        tmp_path,
        "spare_cell_preservation.json",
        {
            "status": "PASS",
            "artefacts": ["def", "gds", "netlist"],
            "artefact_paths": {
                "def": "phase3/spm.def",
                "gds": "phase3/spm.gds",
                "netlist": "phase3/stage3/pnr/spm_pnr.v",
            },
        },
    )

    r = _run([str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    stale = _stale_findings(out)
    assert len(stale) == 1, stale
    # The message must name the REAL path, not the bare label "netlist".
    assert "spm_pnr.v" in stale[0]["message"]
    assert "phase3/stage3/pnr" in stale[0]["message"]
    assert out["summary"]["pass"] is False
    assert r.returncode == 1


def test_string_path_entry_still_validated_as_path(tmp_path):
    """(c) a string entry that IS path-like is still validated as a path."""
    # absent path-like string -> STALE_OUTPUT (prior behavior preserved)
    _write_report(
        tmp_path,
        "g.json",
        {"status": "PASS", "outputs": ["phase3/x.def"]},
    )
    r = _run([str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    stale = _stale_findings(out)
    assert len(stale) == 1
    assert "x.def" in stale[0]["message"]
    assert r.returncode == 1

    # present path-like string -> no STALE_OUTPUT
    (tmp_path / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/x.def").write_text("x")
    r2 = _run([str(tmp_path), "--json"])
    out2 = json.loads(r2.stdout)
    assert _stale_findings(out2) == []
    assert r2.returncode == 0


def test_unmapped_bare_label_is_skipped_not_resolved(tmp_path):
    """(d) regression: a bare label with no mapping and no separator is
    skipped, NOT resolved against the project root (which previously
    false-positived as <project>/def etc.)."""
    _write_report(
        tmp_path,
        "g.json",
        {"status": "PASS", "artefacts": ["def", "gds", "netlist"]},
    )
    r = _run([str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    # No mapping field present -> bare labels skipped -> zero STALE_OUTPUT.
    assert _stale_findings(out) == []
    assert out["summary"]["pass"] is True
    assert r.returncode == 0


def test_generic_values_are_paths_mapping_detected(tmp_path):
    """A generic dict whose values are ALL path-like is also recognized as a
    mapping (not only the explicit artefact_paths key)."""
    (tmp_path / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/a.def").write_text("x")
    (tmp_path / "phase3/b.gds").write_text("x")

    _write_report(
        tmp_path,
        "g.json",
        {
            "status": "PASS",
            "artefacts": ["def", "gds"],
            "resolved": {"def": "phase3/a.def", "gds": "phase3/b.gds"},
        },
    )
    r = _run([str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    assert _stale_findings(out) == []
    assert out["summary"]["pass"] is True
    assert r.returncode == 0


def test_artifacts_spelling_with_i_is_read(tmp_path):
    """The 'artifacts' (with i) key fallback is honored too."""
    _write_report(
        tmp_path,
        "g.json",
        {"status": "PASS", "artifacts": ["phase3/missing.def"]},
    )
    r = _run([str(tmp_path), "--json"])
    out = json.loads(r.stdout)
    stale = _stale_findings(out)
    assert len(stale) == 1
    assert "missing.def" in stale[0]["message"]
    assert r.returncode == 1
