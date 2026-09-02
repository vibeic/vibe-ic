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

THREE ANSWERS, NOT TWO
======================
`out_dir` is an ABSOLUTE path recorded on the producer's host, so on a copied
project the literal is meaningless and the three states must stay distinct:

  * bundle tree present + declared files all there  -> PASS        rc=0
  * bundle tree PRESENT + a declared file missing   -> FAIL        rc=1
  * bundle tree ABSENT from this copy of the project-> NOT_CHECKED rc=2

The third exists because collapsing it into FAIL turns 3 of the 9 tracked
`benchmark-data` projects carrying a `professional_tb.json` red on a BLOCKING
Step-4 slot for a snapshotting artefact (measured; see the rc=2 test). rc=2 is
the tier `flow_compliance_check` already renders as a disclosed
"n/a (input not present)" — never as a clean result.

SCOPING
=======
Resolution must not WALK. An earlier revision globbed
`**/sim_professional/<name>` from the project root, which let a NESTED
snapshot's bundle certify the OUTER project — pinned by
`test_DEFECT_nested_snapshot_bundle_does_not_certify_outer_project`.

TEST FAMILIES
=============
  test_DEFECT_*  fail on origin/main (the check does not exist there).
  test_GUARD_*   pass on BOTH trees — the pre-existing verdicts, and the
                 "no declaration -> nothing owed" scoping that keeps this
                 from manufacturing red.
  test_WIRING_*  DRIVE the real `flow_compliance_check` gate runner so the
                 rc -> step-status mapping is EXECUTED, not asserted from
                 source text.
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


def test_DEFECT_bundle_dir_missing_from_a_PRESENT_tree_fails(tmp_path):
    """The bundle tree IS in the project and this bundle is not in it.

    This is the genuine incomplete-bundle defect, and it stays BLOCKING: the
    producer's own tree is right there, so its absence is about the run, not
    about what a snapshot happened to carry.
    """
    # a sibling bundle exists, so `sim_professional/` is present …
    _bundle(tmp_path, top="other_top")
    # … but the one the producer DECLARED is not.
    _report(tmp_path, _passing_record(
        tmp_path / "phase2" / "stage1" / "sim_professional" / "dut"))
    res = G.check(tmp_path)
    assert res["verdict"] == "FAIL", json.dumps(res, indent=2)
    assert res["bundle"]["resolved_out_dir"] is None
    assert res["bundle"]["bundle_root_present"] is True
    assert res["bundle"]["state"] == "incomplete"
    assert sorted(res["bundle"]["missing"]) == sorted(_BUNDLE_FILES)
    assert G.main([str(tmp_path)]) == 1


def test_DEFECT_absent_bundle_TREE_is_not_checked_rc2_not_a_fail(tmp_path):
    """No `sim_professional/` tree at all -> rc=2 NOT CHECKED, not rc=1.

    rc 0 = PASS, 1 = FAIL, 2 = NOT CHECKED. When this copy of the project
    carries no bundle tree whatsoever the gate examined NOTHING of this kind.
    PASS would be the false-clean this check exists to remove; FAIL asserts a
    defect from an absent input.

    MEASURED: 3 of the 9 tracked projects in `benchmark-data` carrying a
    `reports/phase2/gates/professional_tb.json` are exactly this shape
    (`ic/spm/v1.5.58_ihp-sg13g2`, `v1.5.65_sky130A`, `v1.5.66_gf180mcuD` —
    each declares 5 files and ships no `sim_professional/` tree). Answering
    FAIL turns 3 of 9 published runs red on a BLOCKING Step-4 slot for a
    snapshotting artefact.
    """
    _report(tmp_path, _passing_record(
        tmp_path / "phase2" / "stage1" / "sim_professional" / "dut"))
    res = G.check(tmp_path)
    assert res["verdict"] == "NOT_CHECKED", json.dumps(res, indent=2)
    assert res["bundle"]["resolved_out_dir"] is None
    assert res["bundle"]["bundle_root_present"] is False
    assert res["bundle"]["state"] == "tree_absent"
    assert G.main([str(tmp_path)]) == 2


def test_DEFECT_nested_snapshot_bundle_does_not_certify_outer_project(tmp_path):
    """A NESTED run's bundle must never certify the OUTER project.

    An earlier revision of this change resolved `out_dir` by
    `project.glob("**/sim_professional/<name>")` and took `hits[0]`. Measured
    on that revision: the outer project FAILed with `resolved_out_dir=None`,
    then PASSed once a nested snapshot gained the bundle, with
    `resolved_out_dir` pointing into the nested tree. `ic/sha256` and
    `ic/u_hawaii_adc` both carry the triggering `clean_run_*` shape, and it is
    the same defect class PR #485 item 6 removes from `eda_report_audit`.
    """
    nested = tmp_path / "clean_run_2026"
    _bundle(nested)                     # the CHILD run has a complete bundle
    _report(tmp_path, _passing_record(
        Path("/some/other/host/phase2/stage1/sim_professional/dut")))
    res = G.check(tmp_path)
    resolved = res["bundle"]["resolved_out_dir"]
    assert resolved is None, (
        "outer project resolved its bundle out of a NESTED snapshot: "
        + json.dumps(res, indent=2))
    assert res["verdict"] != "PASS", json.dumps(res, indent=2)
    assert G.main([str(tmp_path)]) != 0


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


@pytest.mark.parametrize("own_tree,expect,rc", [
    (False, "NOT_CHECKED", 2),   # project has no bundle tree of its own
    (True, "FAIL", 1),           # project HAS one; the foreign dir is not it
])
def test_DEFECT_out_of_project_dir_never_certifies(tmp_path, own_tree, expect,
                                                   rc):
    """An absolute out_dir that exists OUTSIDE the project is not evidence.

    The invariant under both shapes is the one that matters: a foreign
    directory NEVER produces a PASS. Which non-PASS answer is correct depends
    on whether this project carries a bundle tree of its own.
    """
    foreign = tmp_path / "foreign_host" / "sim_professional_elsewhere"
    foreign.mkdir(parents=True)
    for f in _BUNDLE_FILES:
        (foreign / f).write_text("// content\n")
    project = tmp_path / "proj"
    project.mkdir()
    if own_tree:
        _bundle(project, top="other_top")
    _report(project, _passing_record(foreign))
    res = G.check(project)
    assert res["verdict"] == expect, json.dumps(res, indent=2)
    assert res["verdict"] != "PASS"
    assert res["bundle"]["resolved_out_dir"] is None
    assert G.main([str(project)]) == rc


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


# ── WIRING — drive the real gate runner, do not assert on source text ────────

_STEP4_CMD = ("professional_tb_check . --json "
              "reports/phase2/gates/professional_tb_check.json")


@pytest.mark.parametrize("shape,step_passes,verdict,reason_class", [
    # rc=0 — clean
    ("complete", True, "PASS", None),
    # rc=1 — BLOCKS the step, as declared
    ("incomplete", False, "FAIL", None),
    # rc=2 — passes the exit-code clause WITH a disclosed non-verdict.
    #
    # BLOCKED, not VACUOUS_PASS, and the GATE is what says so. The producer
    # RAN — it wrote a report declaring a bundle — and the tree that bundle
    # names is not in this copy of the project. That is an artefact an upstream
    # step owes and has not delivered, so `professional_tb_check` publishes
    # `reason_class=BLOCKED_BY_UPSTREAM`, which is NOT skip-eligible: the
    # refusal stays disclosed and cannot become a clean skip. Untyped it fell
    # closed to EXECUTION_ERROR — "the gate blew up" — for a gate that read the
    # tree correctly, and #1978's whole point is that only the producer may say
    # which non-verdict this is, never a prose match on its output.
    ("tree_absent", True, "BLOCKED", "BLOCKED_BY_UPSTREAM"),
])
def test_WIRING_rc_maps_to_the_step_status_it_claims(tmp_path, shape,
                                                     step_passes, verdict,
                                                     reason_class):
    """Execute Step 4's own `program_exit_zero` runner on each shape.

    The claim "rc=2 is rendered as a disclosed n/a, not a clean result" is
    worthless as a source-text assertion — this runs
    `flow_compliance_check._check_program_exit_zero`, the exact function the
    blocking Step-4 slot calls, and reads what it returns.

    ASSERTED ON THE TIER, not on a prefix. `out_text.startswith(
    _VACUOUS_HINT_PREFIX) is discloses` cannot tell a disclosed non-verdict
    from a clean PASS on the FALSE arms: `INCOMPLETE: …`, `FAIL` and a bare
    PASS all satisfy `is False`. `_ProgramCheckResult` carries the tier the
    flow acts on and the class the gate declared, and both are asserted.
    """
    import flow_compliance_check as fcc

    if shape == "complete":
        out = _bundle(tmp_path)
    elif shape == "incomplete":
        out = _bundle(tmp_path)
        (out / "Makefile").unlink()
    else:
        out = tmp_path / "phase2/stage1/sim_professional/dut"
    _report(tmp_path, _passing_record(out))

    res = fcc._check_program_exit_zero(tmp_path, _STEP4_CMD)
    passed, out_text = res
    assert passed is step_passes, out_text
    assert res.verdict == verdict, (res.verdict, out_text)
    assert res.reason_class == reason_class, (res.reason_class, out_text)


def test_WIRING_an_unrun_producer_is_disclosed_and_not_a_clean_pass(tmp_path):
    """The OTHER rc=0 non-verdict, which the parametrization above cannot see.

    No `professional_tb.json` at all: the producing step did not run. rc stays
    0 (an absent optional step must not fail a run) and the flow must still
    stop recording "checked, fine". Untyped this was EXECUTION_ERROR too.
    """
    import flow_compliance_check as fcc
    res = fcc._check_program_exit_zero(tmp_path, _STEP4_CMD)
    assert res.exit_code == 0, res[1]
    assert res.reason_class == "BLOCKED_BY_UPSTREAM", (res.reason_class, res[1])
    assert res.verdict == "BLOCKED", (res.verdict, res[1])


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
