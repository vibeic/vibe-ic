#!/usr/bin/env python3
"""The professional-TB bundle the producer DECLARES must be on disk.

THE DEFECT
==========
`professional_tb_gen.generate()` writes a durable bundle under
`phase2/stage1/sim_professional/<top>/` — `tb_<top>.py`,
`<top>_coverage_model.json`, `<top>_assertions.sva`, `Makefile`,
`verification_plan.json` — and RECORDS it in
`reports/phase2/gates/professional_tb.json` as `out_dir` + `files`.

Nothing read that declaration back. Step 4's `required_outputs` names none of
those paths (only the sim transcript and the coverage artefact), and
`professional_tb_check` looked only at `functional_mismatch`. Measured on the
live spm x ihp-sg13g2 run: `professional_tb_check.json` contained
`{gate, verdict, status, dut_kind, ran_cocotb}` and not one word about the
five files the producer said it wrote, nor about the functional coverage the
generated TB exported.

WHY HERE AND NOT IN `required_outputs`
======================================
`required_outputs` is ALL-of-N since PR #455, and
`design_one_shot_runner.step_professional_tb_gen` legitimately SKIPs for a
class with no derivable arithmetic/streaming interface. Declaring the bundle
there would manufacture a MISSING for every such design. Keying off the
producer's OWN `files`/`out_dir` declaration cannot fire when the generator
did not generate — which is the property `test_GUARD_*` below pins down.

TEST FAMILIES
=============
  test_DEFECT_*  fail on origin/main (the check does not exist there).
  test_GUARD_*   pass on BOTH trees — the pre-existing verdicts, and the
                 "no declaration -> nothing owed" scoping that keeps this
                 from manufacturing red.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import professional_tb_check as G  # noqa: E402

_BUNDLE_FILES = ["tb_dut.py", "dut_coverage_model.json", "dut_assertions.sva",
                 "Makefile", "verification_plan.json"]


def _report(project: Path, obj) -> Path:
    d = project / "reports" / "phase2" / "gates"
    d.mkdir(parents=True, exist_ok=True)
    (d / "professional_tb.json").write_text(json.dumps(obj))
    return project


def _bundle(project: Path, files=_BUNDLE_FILES, top="dut") -> Path:
    out = project / "phase2" / "stage1" / "sim_professional" / top
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        (out / f).write_text("// content\n")
    return out


def _passing_record(out_dir: Path, files=_BUNDLE_FILES) -> dict:
    return {"status": "PASS", "ic_class": "digital_arithmetic_primitive",
            "dut_kind": "serial_stream", "ran_cocotb": True,
            "functional_mismatch": False,
            "out_dir": str(out_dir), "files": list(files)}


# ── DEFECT direction ─────────────────────────────────────────────────────────

def test_DEFECT_missing_declared_file_fails(tmp_path):
    """One declared file absent -> FAIL, exit 1."""
    out = _bundle(tmp_path)
    (out / "dut_coverage_model.json").unlink()
    _report(tmp_path, _passing_record(out))
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL", json.dumps(res, indent=2)
    assert res["bundle"]["missing"] == ["dut_coverage_model.json"]
    assert G.main([str(tmp_path)]) == 1


def test_DEFECT_empty_declared_file_fails(tmp_path):
    """A zero-byte declared file is not a produced artefact."""
    out = _bundle(tmp_path)
    (out / "dut_assertions.sva").write_text("")
    _report(tmp_path, _passing_record(out))
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL", json.dumps(res, indent=2)
    assert res["bundle"]["empty"] == ["dut_assertions.sva"]
    assert G.main([str(tmp_path)]) == 1


def test_DEFECT_out_dir_absent_entirely_fails(tmp_path):
    """The producer declared a bundle and no directory exists for it."""
    _report(tmp_path, _passing_record(
        tmp_path / "phase2" / "stage1" / "sim_professional" / "dut"))
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL", json.dumps(res, indent=2)
    assert res["bundle"]["resolved_out_dir"] is None
    assert sorted(res["bundle"]["missing"]) == sorted(_BUNDLE_FILES)
    assert G.main([str(tmp_path)]) == 1


def test_DEFECT_relocated_project_resolves_by_layout_not_literal_path(tmp_path):
    """The producer records an ABSOLUTE path from the host it ran on.

    A copied/moved project must still be verifiable — otherwise the check
    would report a false MISSING for every relocated tree.
    """
    out = _bundle(tmp_path)
    rec = _passing_record(Path("/somewhere/else/phase2/stage1/"
                               "sim_professional/dut"))
    _report(tmp_path, rec)
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", json.dumps(res, indent=2)
    assert Path(res["bundle"]["resolved_out_dir"]) == out


def test_DEFECT_complete_bundle_is_recorded_as_verified(tmp_path):
    """A PASS must carry the evidence that the bundle was checked.

    origin/main writes `{gate, verdict, status, dut_kind, ran_cocotb}` and
    nothing about the five declared files — a PASS with no record of what was
    verified is indistinguishable from a PASS that verified nothing.
    """
    out = _bundle(tmp_path)
    _report(tmp_path, _passing_record(out))
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", json.dumps(res, indent=2)
    assert res["bundle"]["missing"] == [] and res["bundle"]["empty"] == []
    assert sorted(res["bundle"]["declared"]) == sorted(_BUNDLE_FILES)
    assert Path(res["bundle"]["resolved_out_dir"]) == out


def test_DEFECT_out_of_project_dir_never_certifies(tmp_path):
    """An absolute out_dir that exists OUTSIDE the project is not evidence."""
    foreign = tmp_path / "foreign_host" / "sim_professional_elsewhere"
    foreign.mkdir(parents=True)
    for f in _BUNDLE_FILES:
        (foreign / f).write_text("// content\n")
    project = tmp_path / "proj"
    project.mkdir()
    _report(project, _passing_record(foreign))
    res = G.check(project)
    assert res["verdict"] == "FAIL", json.dumps(res, indent=2)


def test_DEFECT_functional_coverage_is_measured_against_the_models_policy(
        tmp_path):
    """The cocotb export vs the model's own declared closure policy.

    Both files are produced today and nothing compared them — measured on the
    reference run: 12.5 % against a declared 100 %.
    """
    out = _bundle(tmp_path)
    (out / "dut_coverage_model.json").write_text(json.dumps(
        {"doc_id": "L28",
         "fields": {"closure_policy": {"functional_bins_required_pct": 100}}}))
    (out / "coverage_dut.xml").write_text(
        '<top abs_name="top" size="16" coverage="2" cover_percentage="12.5" />')
    _report(tmp_path, _passing_record(out))
    res = G.check(tmp_path)
    fc = res.get("functional_coverage")
    assert fc, json.dumps(res, indent=2)
    assert fc["measured_pct"] == 12.5
    assert fc["required_pct"] == 100.0
    assert fc["closed"] is False
    # DISCLOSED, not enforced — and the report must say which, so a reader is
    # never left to assume the number gated anything.
    assert fc["enforcement"] == "DISCLOSED_NOT_BLOCKING"
    assert res["verdict"] == "PASS"
    assert G.main([str(tmp_path)]) == 0


# ── GUARD direction — must hold on BOTH trees ────────────────────────────────

def test_GUARD_absent_report_is_still_not_applicable(tmp_path):
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_APPLICABLE"
    assert G.main([str(tmp_path)]) == 0


def test_GUARD_functional_mismatch_still_fails_first(tmp_path):
    """A real RTL mismatch must keep FAILing, bundle or no bundle."""
    out = _bundle(tmp_path)
    rec = _passing_record(out)
    rec.update({"status": "FAIL", "functional_mismatch": True,
                "cocotb_xml_failures": 3})
    _report(tmp_path, rec)
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL"
    assert res["cocotb_xml_failures"] == 3
    assert G.main([str(tmp_path)]) == 1


def test_GUARD_complete_bundle_still_passes(tmp_path):
    """Direction-1: a complete bundle must not become a new FAIL."""
    out = _bundle(tmp_path)
    _report(tmp_path, _passing_record(out))
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", json.dumps(res, indent=2)
    assert G.main([str(tmp_path)]) == 0


@pytest.mark.parametrize("rec", [
    {"status": "SKIP", "reason": "class not derivable"},
    {"status": "PASS", "dut_kind": "generic", "ran_cocotb": False,
     "functional_mismatch": False},                      # no out_dir/files
    {"status": "PASS", "out_dir": "", "files": [],
     "functional_mismatch": False},                      # empty declaration
])
def test_GUARD_no_declaration_means_nothing_owed(tmp_path, rec):
    """The scoping that keeps this from manufacturing red.

    `step_professional_tb_gen` SKIPs for a class with no derivable interface,
    and older reports carry no `files`. A producer that declared nothing must
    not be failed for not delivering it — this is the property that made a
    `required_outputs` entry the wrong instrument.
    """
    _report(tmp_path, rec)
    res = G.check(tmp_path)
    assert res["verdict"] == "PASS", json.dumps(res, indent=2)
    assert "bundle" not in res
    assert G.main([str(tmp_path)]) == 0


def test_GUARD_corrupt_report_is_still_io_error(tmp_path):
    d = tmp_path / "reports" / "phase2" / "gates"
    d.mkdir(parents=True)
    (d / "professional_tb.json").write_text("{ not json")
    assert G.check(tmp_path)["verdict"] == "IO_ERROR"
    assert G.main([str(tmp_path)]) == 2


def test_GUARD_absent_coverage_export_is_absent_not_closed(tmp_path):
    """No cocotb export -> no functional_coverage record at all.

    Reporting `closed: true` (or omitting the distinction) for a run that
    exported nothing is the empty-equals-clean substitution.
    """
    out = _bundle(tmp_path)
    (out / "dut_coverage_model.json").write_text(json.dumps(
        {"doc_id": "L28",
         "fields": {"closure_policy": {"functional_bins_required_pct": 100}}}))
    _report(tmp_path, _passing_record(out))
    res = G.check(tmp_path)
    assert "functional_coverage" not in res, json.dumps(res, indent=2)
    assert res["verdict"] == "PASS"
