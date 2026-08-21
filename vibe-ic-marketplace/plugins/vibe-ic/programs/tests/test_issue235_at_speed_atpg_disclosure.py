"""vibe-ic#235 — DT2/DT3 producer-side disclosure artefact.

THE DEFECT (measured on real data before the fix)
=================================================
`benchmark-data/ic/sha256/clean_run_v1422_20260715` shipped with
`path_delay_coverage.json` present, `sdd_coverage.json` ABSENT,
`sdd_coverage_gate.json` ABSENT, and NO not-run record anywhere in the tree.
DT3 had vanished, and nothing on disk said whether it was inapplicable, never
launched, or broken. Running the two gates on that real tree gave:

    sdd_coverage_check       -> FAIL "sdd_coverage.json absent or invalid JSON"
    path_delay_coverage_check-> FAIL "path_delay_coverage.json absent or ..."

versus DT1, which was fixed by #219 and answers the same tree with

    transition_coverage_check-> FAIL "... and NO not-run record was left
                                 either — there is no evidence the step ran"

DT1 has a disclosure CHANNEL and reports its own emptiness; DT2/DT3 had none,
so "never ran", "ran and could not measure" and "ran and crashed" were a single
indistinguishable state — three different repairs behind one message. A missing
disclosure is indistinguishable from a step that passed.

WHAT IS ASSERTED HERE
=====================
Producer side  — every self-disable branch WRITES `<step>_atpg_not_run.json`
                 naming the missing inputs and the stage it stopped at, and a
                 REAL measurement DELETES any stale record.
Consumer side  — the DT2/DT3 gates read that record and answer BLOCKED (with
                 the reason) instead of a bare FAIL, while an absent artefact
                 with NO record stays FAIL. BLOCKED never exits 0.
Gating         — UNCHANGED. The helpers make the existing decisions speak; they
                 must not arm or disarm the producer differently, or a design
                 that grades today would stop grading.

Every assertion below names the mutation it catches, because a disclosure test
that passes on a permanently-silent producer is the bug it is testing for.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R          # noqa: E402
import path_delay_coverage_check as PDF     # noqa: E402
import sdd_coverage_check as SDD            # noqa: E402

DT_ALL = ("DT1", "DT2", "DT3")


# ---------------------------------------------------------------- fixtures
def _sdc(project: Path, clock: str = "clk") -> None:
    sdc = project / R._ATPG_SDC_REL
    sdc.parent.mkdir(parents=True, exist_ok=True)
    sdc.write_text(f"create_clock -name {clock} -period 10 [get_ports {clock}]\n")


def _cut(project: Path) -> None:
    cut = project / R._ATPG_CUT_REL
    cut.parent.mkdir(parents=True, exist_ok=True)
    cut.write_text("module cut(); endmodule\n")


def _coverage(project: Path, step: str, verdict: str = "PASS") -> Path:
    p = project / R._ATPG_COVERAGE_REL[step]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"verdict": verdict}))
    return p


def _record(project: Path, step: str) -> Path:
    return project / R._ATPG_NOT_RUN_REL[step]


def _real_grade_blob(step: str) -> dict:
    """A coverage artefact the gate's OWN recount grades PASS, per step.

    This used to be copied out of `benchmark-data/ic/spm/v1.5.58_ihp-sg13g2`.
    The published result cells now live in `vibeic/benchmark-data`, and reading
    one here made a test about the GATE depend on which cells happen to be
    published — the property is the gate's, so the fixture is the gate's too.

    It is not a rubber stamp. Both evaluators RE-DERIVE their verdict from the
    per-record lists and never trust a written top-level number
    (`path_delay_coverage_check._recount`, `sdd_coverage_check._recount`), so
    this blob reaches PASS only by being internally consistent:

      DT2  2 LOC-testable paths, both `nr_verdict`/`robust_verdict` = DET
           -> recount sensitised 2 / testable 2 = 100% >= floor 80%
      DT3  2 LOC-testable records with slack 8.8/8.9 ns against a margin
           re-derived as 0.1 x 10.0 ns -> both re-derive to `weak`, which is
           what they claim, so there is no strong-with-high-slack fabrication
           and no coverage over-claim

    A `{"verdict": "PASS"}` stub would NOT do: `no per-path PDF records present`
    / `no per-fault SDD records present` both FAIL, which is the point.
    """
    if step == "DT2":
        def _p(idx: int, slack: float) -> dict:
            return {"idx": idx, "startpoint": "ff_launch",
                    "endpoint": f"ff_capture_{idx}", "end_kind": "ff",
                    "end_edge": "^", "arrival": 1.0, "slack": slack,
                    "loc_testable": True, "nr_verdict": "DET",
                    "robust_verdict": "DET", "covered": True, "robust": True,
                    "status": "robust"}
        return {
            "program": "path_delay_fault_atpg_run", "clock": "clk", "top": "dut",
            "floor_pct": 80.0, "k_requested": 2, "k_selected": 2,
            "clock_period_ns": 10.0,
            "graded_paths": 2, "testable_paths": 2, "sensitised_paths": 2,
            "robust_paths": 2, "non_robust_paths": 0, "false_or_held_paths": 0,
            "aborted_paths": 0, "pdf_sensitised_coverage_pct": 100.0,
            "pdf_robust_coverage_pct": 100.0,
            "path_records": [_p(0, 8.8), _p(1, 8.9)],
            "verdict": "PASS", "status": "PASS", "reasons": [],
        }
    if step == "DT3":
        def _r(idx: int, slack: float) -> dict:
            return {"source": "sta_path", "idx": idx, "startpoint": "ff_launch",
                    "endpoint": f"ff_capture_{idx}", "direction": "STR",
                    "arrival_ns": 1.0, "detecting_path_slack_ns": slack,
                    "loc_testable": True, "sensitizable": True,
                    "nr_verdict": "DET", "robust_verdict": "DET",
                    "sdd_bucket": "weak"}
        return {
            "program": "sdd_atpg_run", "clock": "clk", "top": "dut",
            "margin_fraction": 0.1, "margin_fraction_cap": 1.0,
            "clock_period_ns": 10.0, "margin_ns": 1.0,
            "margin_ns_derivation": "margin_fraction × clock_period",
            "k_selected": 2, "graded_faults": 2, "strong": 0, "weak": 2,
            "undetected_at_speed": 0,
            "sdd_binary_strong_coverage_pct": 0.0,
            "sdd_slack_weighted_coverage_pct": 0.0,
            "sdd_records": [_r(0, 8.8), _r(1, 8.9)],
            "verdict": "PASS", "status": "PASS", "reasons": [],
        }
    raise AssertionError(f"no real-grade fixture for {step}")


def _armed(project: Path) -> None:
    """Every DT1/DT2/DT3 precondition satisfied."""
    _sdc(project)
    _cut(project)
    _coverage(project, "DT1")
    _coverage(project, "DT2")


class _FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _run(project: Path):
    written: list = []
    notes: list = []
    R.run_at_speed_atpg_producers(project, written, notes)
    return written, notes


# ================================================================
# PRODUCER — the self-disable branches must speak
# ================================================================

def test_precondition_unmet_writes_a_record_for_every_at_speed_step(tmp_path):
    """The measured shape: no scan cut, no routed SDC → all three steps
    self-disable. Before the fix this wrote NOTHING to disk.

    MUTATION THIS CATCHES: dropping the `atpg_disclose_not_run` call in the
    precondition branch (i.e. reverting to the in-memory `notes.append`) —
    the tree goes silent again and every assertion below fails.
    """
    written, notes = _run(tmp_path)

    assert written == [], "nothing can be produced with no inputs"
    for step in DT_ALL:
        rec = _record(tmp_path, step)
        assert rec.is_file(), (
            f"{step} self-disabled and left no disclosure artefact — that is "
            f"exactly #235: absence indistinguishable from a pass. "
            f"tree={[str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*') if p.is_file()]}")
        blob = json.loads(rec.read_text())
        assert blob["verdict"] == "SKIPPED-CONDITION", blob
        assert blob["not_run_stage"] == "precondition_unmet", blob
        assert blob["step"] == step
        assert blob["skips_required_output"] == R._ATPG_COVERAGE_REL[step]
        # The record must NAME what is missing; a record that says only
        # "skipped" is the same silence with extra steps.
        assert blob["missing_inputs"], blob
        assert any(R._ATPG_SDC_REL in m for m in blob["missing_inputs"]), blob
    # DT1/DT2 miss the scan cut; DT3 misses the two upstream grades it fuses.
    for step in ("DT1", "DT2"):
        blob = json.loads(_record(tmp_path, step).read_text())
        assert any(R._ATPG_CUT_REL in m for m in blob["missing_inputs"]), blob
    dt3 = json.loads(_record(tmp_path, "DT3").read_text())
    assert any(R._ATPG_COVERAGE_REL["DT2"] in m for m in dt3["missing_inputs"])
    assert any(R._ATPG_COVERAGE_REL["DT1"] in m for m in dt3["missing_inputs"])


def test_dt3_cascade_is_disclosed_when_only_the_upstream_grade_is_missing(tmp_path):
    """DT3's own case from the issue: DT1/DT2 are fine, DT2's grade is not
    there, so DT3 vanishes. It must say so rather than disappear.

    MUTATION THIS CATCHES: disclosing only DT2 and leaving DT3's cascade
    silent — the exact half-fix the baseline registry warned about.
    """
    _sdc(tmp_path)
    _cut(tmp_path)
    _coverage(tmp_path, "DT1")
    # DT2's grade deliberately absent.

    calls: list = []

    def _fake(cmd, **kw):
        calls.append(cmd)
        return _FakeProc(rc=0)

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = _fake
    try:
        _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    rec = _record(tmp_path, "DT3")
    assert rec.is_file(), "DT3's cascade self-disable left no record"
    blob = json.loads(rec.read_text())
    assert blob["not_run_stage"] == "precondition_unmet"
    assert any(R._ATPG_COVERAGE_REL["DT2"] in m for m in blob["missing_inputs"])


def test_a_producer_that_writes_nothing_is_disclosed_with_its_exit_status(tmp_path):
    """Ran, produced nothing. HEAD dropped this on the floor entirely — no
    note, no record, no trace of the non-zero exit.

    MUTATION THIS CATCHES: `if out_json.is_file(): written.append(...)` with no
    else, which is precisely what the phase3 block did.
    """
    # DT1/DT2 armed (scan cut + routed SDC), no coverage artefact anywhere yet.
    _sdc(tmp_path)
    _cut(tmp_path)

    def _fake(cmd, **kw):
        return _FakeProc(rc=3, err="engine aborted: no liberty")

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = _fake
    try:
        written, notes = _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    assert written == []
    for step in ("DT1", "DT2"):
        rec = _record(tmp_path, step)
        assert rec.is_file(), f"{step} ran, wrote nothing, and said nothing"
        blob = json.loads(rec.read_text())
        assert blob["not_run_stage"] == "producer_wrote_no_artifact", blob
        assert blob["producer_exit"] == 3, blob
        assert blob["tool_attempted"] is True, (
            "the tool WAS launched here; the record must not claim otherwise")
        assert "engine aborted: no liberty" in blob["reason"], blob
    # DT3 cascades off the two grades that were never produced, and says so.
    dt3 = json.loads(_record(tmp_path, "DT3").read_text())
    assert dt3["not_run_stage"] == "precondition_unmet", dt3


def test_an_exception_from_the_producer_is_disclosed(tmp_path):
    """A timeout / OSError killed the producer. HEAD appended an in-memory note
    that died with the process.

    MUTATION THIS CATCHES: reverting the except branch to `notes.append(...)`.
    """
    _armed(tmp_path)
    _coverage(tmp_path, "DT2", "BLOCKED")

    def _boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = _boom
    try:
        _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    blob = json.loads(_record(tmp_path, "DT2").read_text())
    assert blob["not_run_stage"] == "producer_execution_error", blob
    assert blob["tool_attempted"] is True


# ================================================================
# PRODUCER — the OTHER direction. Without these, "always write a record"
# would pass every test above and be a new lie on disk.
# ================================================================

def test_a_real_measurement_leaves_no_record(tmp_path):
    """CONTROL for every producer test above. A step that actually graded must
    NOT carry a not-run record, or the gate reads a fresh result as blocked.

    MUTATION THIS CATCHES: writing the disclosure unconditionally.
    """
    _armed(tmp_path)
    _coverage(tmp_path, "DT1", "BLOCKED")
    _coverage(tmp_path, "DT2", "BLOCKED")

    def _fake(cmd, **kw):
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"verdict": "PASS"}))
        return _FakeProc(rc=0)

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = _fake
    try:
        written, notes = _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    assert len(written) == 3, written
    for step in DT_ALL:
        assert not _record(tmp_path, step).exists(), (
            f"{step} produced a real grade but still carries a not-run record")


def test_a_real_measurement_retires_a_stale_record(tmp_path):
    """A record that outlives the condition it described is a lie on disk.

    MUTATION THIS CATCHES: dropping `atpg_clear_not_run` on the success path —
    the run grades correctly and the gate still answers BLOCKED forever.
    """
    _armed(tmp_path)
    _coverage(tmp_path, "DT2", "BLOCKED")
    stale = R.atpg_disclose_not_run(tmp_path, "DT2", "an earlier pass gave up",
                                    "precondition_unmet")
    assert stale.is_file()

    def _fake(cmd, **kw):
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"verdict": "PASS"}))
        return _FakeProc(rc=0)

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = _fake
    try:
        _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    assert not stale.exists(), "a real grade must retire the stale record"


def test_an_existing_grade_is_neither_regraded_nor_recorded(tmp_path):
    """Idempotence + the no-spurious-record control, and the gating check: a
    tree that already carries genuine grades must be left completely alone,
    even with the scan cut long since cleaned up (every published benchmark
    run is in exactly that state).

    MUTATION THIS CATCHES: checking preconditions BEFORE `atpg_needs_regrade`,
    which stamps a not-run record onto every finished run in the repo.
    """
    _sdc(tmp_path)
    _coverage(tmp_path, "DT1")
    _coverage(tmp_path, "DT2")
    _coverage(tmp_path, "DT3")
    # No cut_netlist.v on purpose.
    launched: list = []

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = lambda cmd, **kw: (launched.append(cmd)
                                           or _FakeProc(rc=0))
    try:
        written, notes = _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    assert launched == [], "a graded tree must not re-launch any producer"
    assert written == [] and notes == []
    assert list(tmp_path.rglob("*atpg_not_run*")) == []


def test_a_stale_record_is_retired_even_without_a_rerun(tmp_path):
    """The record and the grade contradict each other and no producer runs.
    The grade is the measurement; the record must go.

    MUTATION THIS CATCHES: `continue`-ing on `not needs_regrade` before
    clearing, leaving a permanent contradiction beside a real result.
    """
    _sdc(tmp_path)
    _coverage(tmp_path, "DT2")
    stale = R.atpg_disclose_not_run(tmp_path, "DT2", "stale", "precondition_unmet")
    _run(tmp_path)
    assert not stale.exists()


# ================================================================
# GATING PARITY — the refactor must not change WHEN the producer runs or HOW
# it is invoked. This is the regression guard on the extraction itself.
# ================================================================

def test_producer_argv_is_unchanged(tmp_path):
    """Pins the invocation the inline block used: the SDC clock, DT1's
    --max-faults 400, the canonical --json target, and --pdk-dir only when
    input/pdk exists.

    MUTATION THIS CATCHES: any drift in the extracted call (a lost
    --max-faults, a wrong clock, a moved output path) — all of which would
    silently change grading rather than fail loudly.
    """
    _armed(tmp_path)
    _coverage(tmp_path, "DT1", "BLOCKED")
    _coverage(tmp_path, "DT2", "BLOCKED")
    (tmp_path / "input" / "pdk").mkdir(parents=True)
    cmds: list = []

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = lambda cmd, **kw: (cmds.append(cmd) or _FakeProc(rc=0))
    try:
        _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    assert len(cmds) == 3
    progs = [Path(c[1]).name for c in cmds]
    assert progs == ["transition_fault_atpg_run.py",
                     "path_delay_fault_atpg_run.py",
                     "sdd_atpg_run.py"], progs
    for cmd, step in zip(cmds, DT_ALL):
        assert cmd[2] == str(tmp_path)
        assert cmd[cmd.index("--clock") + 1] == "clk"
        assert cmd[cmd.index("--json") + 1] == str(
            tmp_path / R._ATPG_COVERAGE_REL[step])
        assert cmd[cmd.index("--pdk-dir") + 1] == str(
            (tmp_path / "input" / "pdk").resolve())
    assert cmds[0][cmds[0].index("--max-faults") + 1] == "400"
    for c in cmds[1:]:
        assert "--max-faults" not in c


def test_no_pdk_dir_argument_when_there_is_no_staged_pdk(tmp_path):
    """Control for the argv test: --pdk-dir is conditional, as it was."""
    _armed(tmp_path)
    _coverage(tmp_path, "DT2", "BLOCKED")
    cmds: list = []

    import phase3_one_shot_runner as _R
    orig = _R.subprocess.run
    _R.subprocess.run = lambda cmd, **kw: (cmds.append(cmd) or _FakeProc(rc=0))
    try:
        _run(tmp_path)
    finally:
        _R.subprocess.run = orig

    assert cmds and all("--pdk-dir" not in c for c in cmds)


@pytest.mark.parametrize("sdc_text,expected", [
    ("create_clock -name clk -period 10 [get_ports clk]\n", "clk"),
    ("create_clock -period 10 [get_ports sysclk]\n", "sysclk"),
    ("# no clock here\n", None),
])
def test_clock_discovery_matches_the_inline_regex(tmp_path, sdc_text, expected):
    """The three inline copies of the clock regex became one helper; it must
    resolve the same names, including the -name-less get_ports form."""
    sdc = tmp_path / R._ATPG_SDC_REL
    sdc.parent.mkdir(parents=True, exist_ok=True)
    sdc.write_text(sdc_text)
    assert R.routed_sdc_clock(tmp_path) == expected


def test_missing_sdc_is_a_named_missing_input_not_a_crash(tmp_path):
    assert R.routed_sdc_clock(tmp_path) is None
    assert any(R._ATPG_SDC_REL in m
               for m in R.atpg_missing_inputs(tmp_path, "DT2"))


@pytest.mark.parametrize("verdict,regrade", [
    ("PASS", False), ("NOT_APPLICABLE", False),
    ("BLOCKED", True), ("ENGINE_LIMITED", True), ("ERROR", True),
])
def test_regrade_policy_is_unchanged(tmp_path, verdict, regrade):
    """A genuine measurement is never re-run; a non-graded placeholder is."""
    p = _coverage(tmp_path, "DT2", verdict)
    assert R.atpg_needs_regrade(p) is regrade


# ================================================================
# CONSUMER — the gates must turn the record into BLOCKED, and must NOT turn
# silence into BLOCKED.
# ================================================================

@pytest.mark.parametrize("step,mod", [("DT2", PDF), ("DT3", SDD)])
def test_gate_reports_blocked_with_the_recorded_reason(tmp_path, step, mod):
    """MUTATION THIS CATCHES: leaving the gate's `blob is None` branch as a
    bare FAIL — the record is written and nothing reads it, so the disclosure
    is decorative and the operator still cannot tell the three cases apart.
    """
    R.atpg_disclose_not_run(tmp_path, step, "the scan cut never arrived",
                            "precondition_unmet")
    report = mod.audit(tmp_path)
    assert report["verdict"] == "BLOCKED", report
    assert report["not_run_stage"] == "precondition_unmet"
    assert report["not_run_record"] == str(tmp_path / R._ATPG_NOT_RUN_REL[step])
    assert "the scan cut never arrived" in " ".join(report["reasons"])


@pytest.mark.parametrize("step,mod", [("DT2", PDF), ("DT3", SDD)])
def test_gate_still_fails_when_nothing_was_recorded(tmp_path, step, mod):
    """THE DISCRIMINATION, and the control that stops the test above from
    passing on `return BLOCKED` unconditionally. An absent artefact with no
    record is not blocked — nobody knows whether the step ever ran.

    MUTATION THIS CATCHES: returning BLOCKED whenever the coverage is absent,
    which would launder every silently-vanished step into a named deferral.
    """
    report = mod.audit(tmp_path)
    assert report["verdict"] == "FAIL", report
    assert report["not_run_record"] is None
    assert "NO not-run record" in " ".join(report["reasons"])


@pytest.mark.parametrize("step,mod", [("DT2", PDF), ("DT3", SDD)])
def test_blocked_is_not_a_pass(tmp_path, step, mod):
    """An unmeasured at-speed step must not exit 0, or the flow's
    `program_exit_zero` gate reads the deferral as a green step.

    MUTATION THIS CATCHES: adding BLOCKED to the rc-0 set beside
    NOT_APPLICABLE.
    """
    R.atpg_disclose_not_run(tmp_path, step, "nothing to grade",
                            "precondition_unmet")
    assert mod.main([str(tmp_path)]) == 1


@pytest.mark.parametrize("step,mod", [("DT2", PDF), ("DT3", SDD)])
def test_a_real_grade_is_never_downgraded_by_a_stale_record(tmp_path, step, mod):
    """§4.05 no-leak, the reverse direction: the record is only consulted when
    there is NO artefact. A real grade governs, and a leftover record can
    never demote it — nor can it rescue a real FAIL.

    MUTATION THIS CATCHES: consulting the record before the coverage blob.
    """
    R.atpg_disclose_not_run(tmp_path, step, "stale", "precondition_unmet")

    # CONTROL, and the reason this is not a weakened test: the record on disk is
    # LIVE — resolvable, parseable, and on its own it drives the gate to BLOCKED.
    # Without this arm a PASS below could come from a record the gate merely
    # failed to read, which is a different cause and would not catch the
    # mutation. Measured here, on the same tree, one call earlier.
    blocked = mod.audit(tmp_path)
    assert blocked["verdict"] == "BLOCKED", blocked
    assert blocked["not_run_record"], (
        "fixture premise: the stale record must be RESOLVED when there is no "
        "artefact, or the no-leak direction below is asserting on nothing")

    dst = tmp_path / R._ATPG_COVERAGE_REL[step]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(_real_grade_blob(step)))

    report = mod.audit(tmp_path)
    assert report["verdict"] == "PASS", report
    assert report["not_run_record"] is None, (
        "a graded run must not even resolve the record")


@pytest.mark.parametrize("step,mod", [("DT2", PDF), ("DT3", SDD)])
def test_an_unparseable_record_is_not_a_deferral(tmp_path, step, mod):
    """A corrupt sentinel is not a reason. It must fall back to FAIL, not be
    read as 'the step said why'."""
    rec = _record(tmp_path, step)
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text("{not json")
    report = mod.audit(tmp_path)
    assert report["verdict"] == "FAIL", report
    assert report["not_run_record"] is None


# ================================================================
# FLOW LEVEL — what the disclosure is allowed to BUY
# ================================================================
# Everything above measures the record and the two gates that read it. None of
# it looks at the VERDICT `flow_compliance_check` prints, which is the number a
# reviewer actually reads — and that gap let a change land that flipped the
# whole flow FAIL -> PASS while every assertion above stayed green. The two
# tests below close it from both sides: the defect input must stay red, and the
# legitimate input must stay green.

FLOW_YAML = PROGS.parent / "flow" / "phase1_phase2_phase3.yaml"
FCC_PY = PROGS / "flow_compliance_check.py"


def _dt_subflow(tmp_path: Path) -> Path:
    """A flow def carrying DT1/DT2/DT3 VERBATIM from the live flow yaml.

    Copied, never hand-written: the point is to measure the shipped step
    definitions, so an edit to the real `condition` / `required_outputs` is
    felt here. `blocks_on` is pruned to the ids present so the subset parses.
    """
    import yaml  # local: only this leg needs it
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    keep = {"DT1", "DT2", "DT3"}
    steps = [s for s in doc["steps"] if str(s.get("id")) in keep]
    assert {str(s["id"]) for s in steps} == keep, (
        f"the live flow yaml no longer declares all of {keep}")
    for s in steps:
        s["blocks_on"] = [b for b in (s.get("blocks_on") or [])
                          if str(b) in keep]
    out = tmp_path / "dt_subflow.yaml"
    out.write_text(yaml.safe_dump(
        {"version": doc.get("version", 2),
         "flow_name": doc.get("flow_name", "phase1_phase2_phase3"),
         "steps": steps},
        sort_keys=False, allow_unicode=True))
    return out


def _fcc(project: Path, flow_def: Path) -> Tuple[int, dict]:
    rep = project / "_fcc.json"
    proc = subprocess.run(
        [sys.executable, str(FCC_PY), str(project),
         "--flow-def", str(flow_def), "--strict", "--json", str(rep)],
        capture_output=True, text=True, timeout=60)
    doc = json.loads(rep.read_text())
    doc["_stdout"] = proc.stdout
    return proc.returncode, doc


def _status_of(doc: dict, step: str) -> Optional[str]:
    for s in doc["steps"]:
        if str(s.get("id")) == step:
            return s.get("status")
    return None


def test_a_disclosed_not_run_is_never_cost_free_at_the_flow_level(tmp_path):
    """THE DEFECT INPUT. A tree that has a scan cut, post-layout parasitics and
    a routed netlist, and NO at-speed grade at all — every one of DT1/DT2/DT3
    disclosed as not-run by the producer.

    The disclosure must buy a REASON, never a DISCOUNT. Concretely: DT1 and
    DT2 stay MISSING (their required coverage artefact is absent and nothing
    produced it), the flow verdict stays FAIL and the exit code stays 1.

    MUTATION THIS CATCHES — and it is the one that shipped: mirroring the
    not-run record into `reports/phase2/dft/` beside the coverage artefact so
    `flow_compliance_check._declared_sibling_self_skip_for_missing` promotes
    MISSING -> SKIPPED-CONDITION. `total_required` SUBTRACTS
    SKIPPED-CONDITION, so all three steps leave the executed-PASS denominator
    and this whole tree reports `Overall: PASS`. Measured: with the mirror,
    MISSING=0 SKIPPED=4 `0/-1 executed PASS` rc 0; without it, MISSING=2 rc 1.
    """
    _sdc(tmp_path)
    _cut(tmp_path)
    spef = tmp_path / "phase3/stage3/extracted/top.spef"
    spef.parent.mkdir(parents=True, exist_ok=True)
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    pnr = tmp_path / "phase3/stage3/pnr/top_pnr.v"
    pnr.parent.mkdir(parents=True, exist_ok=True)
    pnr.write_text("module top(); endmodule\n")
    for step in DT_ALL:
        R.atpg_disclose_not_run(tmp_path, step, "producer wrote no artefact",
                                "producer_wrote_no_artifact")

    # The record must not be co-located with the artefact whose absence it
    # discloses — that directory is where the MISSING->SKIPPED-CONDITION
    # promoter looks, and a promotion there is the discount this test refuses.
    for step in DT_ALL:
        mirror = tmp_path / R._ATPG_NOT_RUN_LEGACY_COLOCATED_REL[step]
        assert not mirror.exists(), (
            f"{step}'s not-run record was written co-located with its coverage "
            f"artefact at {mirror.relative_to(tmp_path)}; that is where "
            f"_declared_sibling_self_skip_for_missing looks, and the "
            f"SKIPPED-CONDITION it grants is subtracted from the "
            f"executed-PASS denominator")

    rc, doc = _fcc(tmp_path, _dt_subflow(tmp_path))
    assert _status_of(doc, "DT1") == "MISSING", doc["_stdout"]
    assert _status_of(doc, "DT2") == "MISSING", doc["_stdout"]
    assert doc["overall"] == "FAIL", doc["_stdout"]
    assert rc == 1, doc["_stdout"]
    assert doc["counts"]["MISSING"] >= 2, doc["counts"]


def test_a_routed_extracted_design_with_no_dft_does_not_arm_dt2(tmp_path):
    """THE LEGITIMATE INPUT, and the control that stops the test above from
    being satisfied by an over-eager condition.

    A design that routed and extracted parasitics but carries no DFT at all is
    the case where DT1 itself legitimately self-skips: there is no scan cut, so
    no at-speed ATPG was ever asked for. DT2 must self-skip alongside it.

    MUTATION THIS CATCHES: adding `phase3/stage3/extracted/*.spef` to DT2's
    any-of condition as "DT1's cut_netlist.v analogue". The SPEF alone then
    arms DT2, its `path_delay_coverage.json` is absent, and this tree takes a
    hard MISSING and `Overall: FAIL` rc 1 — a false alarm bought with the
    false clean above. Measured: with the SPEF branch, DT2 MISSING rc 1;
    without it, DT2 SKIPPED-CONDITION rc 0.
    """
    spef = tmp_path / "phase3/stage3/extracted/top.spef"
    spef.parent.mkdir(parents=True, exist_ok=True)
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    pnr = tmp_path / "phase3/stage3/pnr/top_pnr.v"
    pnr.parent.mkdir(parents=True, exist_ok=True)
    pnr.write_text("module top(); endmodule\n")

    rc, doc = _fcc(tmp_path, _dt_subflow(tmp_path))
    assert _status_of(doc, "DT1") == "SKIPPED-CONDITION", doc["_stdout"]
    assert _status_of(doc, "DT2") == "SKIPPED-CONDITION", (
        "a routed+extracted design with NO DFT armed DT2 and took a hard "
        "MISSING for a grade no producer was ever asked for:\n"
        + doc["_stdout"])
    assert doc["counts"]["MISSING"] == 0, doc["_stdout"]
    assert doc["overall"] == "PASS", doc["_stdout"]
    assert rc == 0, doc["_stdout"]


def test_dt2_arms_and_goes_red_when_its_own_grade_is_absent(tmp_path):
    """A design that has EVERYTHING DT2 needs and no at-speed grade must go
    red, and must stay inside the executed-PASS denominator.

    This is the direction that was measured and lost at the 2026-07-28
    convergence merge, so it is pinned here rather than argued. A dimension-6
    change had re-armed DT2 on the PRODUCER'S OWN OUTPUTS (any-of over
    `reports/phase2/dft/path_delay_coverage.json` or
    `phase2/stage2/dft/path_delay_atpg_not_run.json`) to close the #235
    self-disabling hole. On THIS tree that spelling gives DT2
    SKIPPED-CONDITION, `Steps: 1 total (0/-1 executed PASS)` and
    `Overall: PASS` rc 0 — the step leaves the denominator entirely, because
    `total_required` subtracts SKIPPED-CONDITION. The ALL-of spelling gives
    `MISSING=1`, `Overall: FAIL`, rc 1, which is what this asserts.

    MUTATION THIS CATCHES: re-arming DT2's condition on its own producer's
    outputs (in either the any-of or the mirrored-record form).

    WHAT THIS DOES **NOT** COVER, and it is a waived gap, not an oversight:
    the mirror case — the producer ran and disclosed, and DT2's INPUTS were
    then cleaned away. On this ALL-of condition DT2 goes SKIPPED-CONDITION
    there. That is the vibe-ic#235 self-disabling hole; it is carried in
    `flow/flow_condition_reachability_baseline.json` and waived at DT2/dim-6,
    and closing it needs a flow-level non-fatal "ran, disclosed, could not
    measure" verdict that COSTS the denominator — not another condition.
    """
    cut = tmp_path / "phase2/stage2/dft/cut_netlist.v"
    cut.parent.mkdir(parents=True, exist_ok=True)
    cut.write_text("module cut(); endmodule\n")
    spef = tmp_path / "phase3/stage3/extracted/top.spef"
    spef.parent.mkdir(parents=True, exist_ok=True)
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    pnr = tmp_path / "phase3/stage3/pnr/top_pnr.v"
    pnr.parent.mkdir(parents=True, exist_ok=True)
    pnr.write_text("module top(); endmodule\n")

    rc, doc = _fcc(tmp_path, _dt_subflow(tmp_path))
    assert _status_of(doc, "DT2") == "MISSING", (
        "a design carrying DT2's scan cut, its SPEF and its routed netlist, "
        "with NO at-speed grade on disk, did not go red — the step whose only "
        "job is to report that grade vanished instead:\n" + doc["_stdout"])
    assert doc["counts"]["MISSING"] >= 1, doc["_stdout"]
    assert doc["overall"] == "FAIL", doc["_stdout"]
    assert rc == 1, doc["_stdout"]
