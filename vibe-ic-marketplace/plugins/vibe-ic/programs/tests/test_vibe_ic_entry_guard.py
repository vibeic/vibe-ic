#!/usr/bin/env python3
"""Tests for vibe_ic_entry_guard.py.

Covers:
- PASS when any runner evidence file is present.
- FAIL when no evidence is present.
- --allow-direct-agent turns FAIL into WARN rc=0.
- --strict rc=1 vs default rc=0 on FAIL.
- missing project dir returns rc=2.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GUARD = PROGRAMS / "vibe_ic_entry_guard.py"


def run(args, cwd=None):
    cp = subprocess.run([sys.executable, str(GUARD), *args],
                        capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return cp.returncode, cp.stdout, cp.stderr


def _valid_orchestrator_report(project: Path):
    return {"phase": "vibe-ic", "project": str(project), "verdict": "PASS",
            "phases": []}


def _valid_phase1_report(project: Path):
    return {"phase": 1, "project": str(project), "verdict": "PASS",
            "mode": "docs", "delegated_to": "phase1_doc_one_shot_runner",
            "delegated_rc": 0}


def _valid_layer_doc(content=None):
    doc = {
        "doc_id": "L1",
        "fields": {"ic_name": "TopModule"},
        "_generator": {
            "plugin": "vibe-ic",
            "plugin_version": "1.10.48",
            "l_doc_taxonomy_digest": "0123456789ab",
            "l_doc_taxonomy_docs": 28,
            "emitter": "phase1_engine.render",
        },
    }
    if content:
        doc.update(content)
    return doc


def test_pass_with_orchestrator_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps(_valid_orchestrator_report(td)))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0
        assert "PASS" in out


def test_pass_with_phase1_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports"
        rep.mkdir()
        (rep / "phase1_one_shot.json").write_text(
            json.dumps(_valid_phase1_report(td)))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0


def test_pass_with_l1_datasheet():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps(_valid_layer_doc()))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0


def test_fail_strict():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1
        assert "no Vibe-IC runner evidence" in err


def test_fail_default_warn_rc0():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td)])
        assert rc == 0
        assert "FAIL" in err


def test_allow_direct_agent_warn_rc0():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td), "--allow-direct-agent"])
        assert rc == 0
        assert "WARN(direct-agent)" in out


def test_missing_dir_rc2():
    rc, out, err = run(["/tmp/nonexistent_vibe_ic_entry_guard_test"])
    assert rc == 2


def test_json_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        json_out = td / "report.json"
        rc, out, err = run([str(td), "--strict", "--json", str(json_out)])
        assert rc == 1
        data = json.loads(json_out.read_text())
        assert data["gate"] == "vibe_ic_entry_guard"
        assert data["verdict"] == "FAIL"
        assert data["findings_count"] == 1


# ---------------------------------------------------------------------------
# Shape-C per-problem phase1 evidence (open-benchmark-methodology § 7.5 rule 3).
#
# A Shape-C (atomic-micro-problem) run drives phase1_engine ONCE PER PROBLEM, so
# the fact-graph lands under <run>/work/<prob>/…/generated_docs/L*.json rather
# than at the run root. The guard originally had no branch for that layout and
# rejected fully-compliant Shape-C runs as direct-agent authoring.
#
# This is a guard-RELAXING branch, so per § 4.05 the NEGATIVE no-leak cases
# below are the load-bearing half: each sits JUST OUTSIDE the intended boundary
# and MUST still be caught.
# ---------------------------------------------------------------------------

def _shape_c(td: Path, rel: str, name: str, body: str | None = None):
    p = td / rel
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(body if body is not None
                          else json.dumps(_valid_layer_doc()))


# ---- POSITIVE: both layouts gates_atomic.py itself accepts ----

def test_pass_shape_c_out_generated_docs():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "L1_DATASHEET.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err
        assert "PASS" in out


def test_pass_shape_c_phase1_proj_layout():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob153_gshare/phase1_proj/phase1/generated_docs",
                 "L9_INTEGRATION_SPEC.json",
                 json.dumps(_valid_layer_doc({"top_module": "TopModule"})))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


# ---- POSITIVE: Shape-B per-design layouts -------------------------------

def test_pass_shape_b_orchestrator_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "work" / "design_a" / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps({"verdict": "PASS", "project": str(rep.parents[2]),
                        "phases": {}}))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


def test_pass_shape_b_phase1_layer_doc():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/design_a/phase1/generated_docs",
                 "L1_DATASHEET.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


# ---- NEGATIVE no-leak (§ 4.05): boundary-outside, must STILL be caught ----

def test_noleak_bare_work_dir_still_caught():
    """Direct-agent authoring: RTL in work/ but phase1 never ran."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "Prob001_zero").mkdir(parents=True)
        (td / "work" / "Prob001_zero" / "sample.sv").write_text("module TopModule(); endmodule")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1
        assert "no Vibe-IC runner evidence" in err


def test_noleak_empty_generated_docs_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "Prob001_zero" / "out" / "generated_docs").mkdir(parents=True)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_non_layer_json_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "notes.json", '{"faked":true}')
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_backup_layer_doc_still_caught():
    """A stale .bak is not live phase1 output."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "L1_DATASHEET.json.bak")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_unnumbered_layer_name_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "Lfoo.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_layer_doc_at_wrong_depth_still_caught():
    """A layer doc at the run root (not under work/<prob>/) must not qualify."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "generated_docs", "L1_DATASHEET.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_directory_named_like_layer_doc_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "Prob001_zero" / "out" / "generated_docs" /
         "L1_DATASHEET.json").mkdir(parents=True)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_shape_b_empty_work_design_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "design_a").mkdir(parents=True)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("name", ["Lfoo.json", "L1.json", "notes.json"])
def test_noleak_shape_b_fake_layer_names_still_caught(name):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/design_a/phase1/generated_docs", name)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("rel", [
    "work/design_a/reports/orchestrator/summary.json",
    "work/design_a/reports/vibe_ic_one_shot.json",
    "work/design_a/orchestrator/vibe_ic_one_shot.json",
])
def test_noleak_shape_b_arbitrary_json_at_similar_depth_is_rejected(rel):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / rel
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"verdict": "PASS"}))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("body", [
    "",
    "not json",
    json.dumps({"verdict": "PASS"}),
    json.dumps({"verdict": "PASS", "project": "/tmp/p"}),
])
def test_noleak_shape_b_fake_exact_report_is_rejected(body):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = (td / "work" / "design_a" / "reports" / "orchestrator" /
             "vibe_ic_one_shot.json")
        p.parent.mkdir(parents=True)
        p.write_text(body)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("rel", [
    "phase1/generated_docs",
    "work/design_a/phase1/generated_docs",
    "work/Prob001_zero/out/generated_docs",
    "work/Prob001_zero/phase1_proj/phase1/generated_docs",
])
@pytest.mark.parametrize("body", [
    "",
    "not json",
    "{}",
    json.dumps({
        "_generator": {
            "plugin": "vibe-ic",
            "plugin_version": "1.10.48",
            "l_doc_taxonomy_digest": "0123456789ab",
            "l_doc_taxonomy_docs": 28,
            "emitter": "phase1_engine.render",
        }
    }),
    json.dumps({
        "doc_id": "L1",
        "_generator": {
            "plugin": "not-vibe-ic",
            "plugin_version": "1.10.48",
            "l_doc_taxonomy_digest": "0123456789ab",
            "l_doc_taxonomy_docs": 28,
            "emitter": "phase1_engine.render",
        }
    }),
])
def test_noleak_layer_doc_requires_substantive_generator_evidence(rel, body):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, rel, "L1_DATASHEET.json", body)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize(("rel", "body"), [
    ("reports/orchestrator/vibe_ic_one_shot.json",
     json.dumps({"verdict": "PASS"})),
    ("reports/phase1_one_shot.json", json.dumps({"verdict": "PASS"})),
])
def test_noleak_root_report_requires_canonical_envelope(rel, body):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / rel
        p.parent.mkdir(parents=True)
        p.write_text(body)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
