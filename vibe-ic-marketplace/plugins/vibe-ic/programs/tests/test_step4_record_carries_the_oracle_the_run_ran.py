#!/usr/bin/env python3
"""The canonical Step-4 record must not contradict the run that produced it.

`step_reference_tb`'s connectivity bridge writes `phase2/stage1/sim/results.xml`
— the one path the flow treats as canonical — and its waiver text says
functional verification is "DEFERRED to a per-IC oracle TB". In the SAME Phase-2
pass, `professional_tb_gen` runs FIRST and, when its Tier-3 hook is filled,
closes exactly that deferral with a real cocotb run against the real rtl/.
Nothing reconciled the two, so the canonical record kept saying
`functional_verified=false` while the run's own JUnit transcript said otherwise.

MEASURED, sha256 x sky130A, plugin 1.15.87:

    phase2/stage1/sim/results.xml                 functional_verified=false
    phase2/stage1/sim_professional/*/results.xml  tests=1 failures=0 errors=0

The half that keeps this honest is the REVERSE direction, and most of the cases
below are it: a claim of functional verification is a forgery unless the record
can SHOW the transcript, and every unshowable shape — no pointer, a dangling
pointer, a non-JUnit file, a zero-test result, a failing result — must still be
refused exactly as it was before. Those cases pass on BOTH trees by design.

All fixtures are synthetic; no chip, PDK or vendor literal decides anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR              # noqa: E402
import cpu_functional_oracle_waiver_check as GATE  # noqa: E402

TRACK_REASON = "class 'widget_engine' verification_track='generic_full_stack'"
TOP = "widget_engine"


def _junit(tests: int, failures: int = 0, errors: int = 0,
           skipped: int = 0) -> str:
    """A cocotb-shaped JUnit document with `tests` testcase elements.

    The count and the elements are kept CONSISTENT on purpose: `parse_junit`
    falls back to counting `<testcase>` when the attribute reads 0, so a
    `tests="0"` suite that still lists a case is not a vacuous result and
    would not exercise the control it looks like it exercises.
    """
    cases = "".join(
        f'<testcase classname="tb_{TOP}" name="oracle{i}" time="1.0"/>'
        for i in range(tests))
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f'<testsuites name="cocotb tests"><testsuite name="tb_{TOP}" '
        f'errors="{errors}" failures="{failures}" skipped="{skipped}" '
        f'tests="{tests}" time="1.0">'
        f"{cases}"
        "</testsuite></testsuites>\n")


def _project(tmp_path: Path, professional: "str | None") -> Path:
    """A project with a completed connectivity transcript, optionally beside a
    professional-TB result."""
    proj = tmp_path / "proj"
    fs = proj / "phase2" / "stage1" / "sim_full_stack" / "run"
    fs.mkdir(parents=True, exist_ok=True)
    transcript = fs / "full_stack.log"
    transcript.write_text(
        "binding widget_engine\nFULL_STACK_TB_CHECKS pass=4 fail=0\n"
        "FULL_STACK_TB_DONE\n", encoding="utf-8")
    if professional is not None:
        pd = proj / "phase2" / "stage1" / "sim_professional" / TOP
        pd.mkdir(parents=True, exist_ok=True)
        (pd / "results.xml").write_text(professional, encoding="utf-8")
    return proj


def _emit(proj: Path) -> bool:
    transcript = (proj / "phase2" / "stage1" / "sim_full_stack" / "run"
                  / "full_stack.log")
    return DOSR._emit_connectivity_sim_bridge(proj, transcript, TOP,
                                              TRACK_REASON)


def _record(proj: Path) -> str:
    return (proj / "phase2" / "stage1" / "sim"
            / "results.xml").read_text(encoding="utf-8")


def _field(xml: str, name: str) -> str:
    return GATE._read_xml_field(xml, name)


# ===========================================================================
# forward — the run's own oracle must reach the canonical record
# ===========================================================================
def test_the_canonical_record_reports_the_oracle_this_run_ran(tmp_path):
    proj = _project(tmp_path, _junit(tests=3))
    assert _emit(proj) is True
    xml = _record(proj)
    assert _field(xml, "functional_verified") == "true", (
        "the run closed functional verification with a real cocotb PASS and "
        "the canonical Step-4 record still says functional_verified=false; "
        f"record was: {xml}")


def test_the_record_shows_the_transcript_it_claims(tmp_path):
    """A flag is a claim; a resolvable pointer is evidence."""
    proj = _project(tmp_path, _junit(tests=3))
    _emit(proj)
    pointer = _field(_record(proj), "functional_evidence")
    assert pointer, "functional_verified=true was written with no pointer"
    assert (proj / pointer).is_file(), (
        f"<functional_evidence>{pointer}</> does not resolve inside the project")


def test_the_gate_accepts_a_claim_it_can_check(tmp_path):
    """A reverse control, not a discriminator: the gate already reached rc 0 on
    this shape through `find_professional_tb_pass`. It is here so a fix that
    made the RECORD honest by breaking the GATE would be caught."""
    proj = _project(tmp_path, _junit(tests=3))
    _emit(proj)
    rc, msg = GATE._evaluate(proj)
    assert rc == 0, f"the gate refused a substantiated record: {msg}"


# ===========================================================================
# reverse controls — these must hold on BOTH trees
# ===========================================================================
def test_with_no_oracle_the_record_is_the_connectivity_record(tmp_path):
    proj = _project(tmp_path, None)
    assert _emit(proj) is True
    xml = _record(proj)
    assert _field(xml, "verdict") == "CONNECTIVITY_PASS"
    assert _field(xml, "functional_verified") == "false", (
        "a run with no functional oracle must still record none")


def test_a_failing_oracle_does_not_become_a_functional_pass(tmp_path):
    proj = _project(tmp_path, _junit(tests=3, failures=1))
    _emit(proj)
    assert _field(_record(proj), "functional_verified") == "false", (
        "a professional TB with a failure was recorded as functional evidence")


def test_a_zero_test_oracle_does_not_become_a_functional_pass(tmp_path):
    proj = _project(tmp_path, _junit(tests=0))
    _emit(proj)
    assert _field(_record(proj), "functional_verified") == "false", (
        "a vacuous zero-test professional result was recorded as evidence")


def test_the_per_case_oracle_gap_marker_survives_both_branches(tmp_path):
    """`l10_tb_conformance_check` keys its strictness on this marker; a
    whole-design functional TB says nothing about the per-case gap, so the
    marker must not disappear when the oracle appears."""
    with_oracle = _project(tmp_path / "a", _junit(tests=3))
    without = _project(tmp_path / "b", None)
    _emit(with_oracle)
    _emit(without)
    for proj in (with_oracle, without):
        assert _field(_record(proj), "capability_gap") == \
            GATE.CAP_CPU_FUNCTIONAL_ORACLE, (
            f"the per-case oracle gap marker was dropped in {proj}")


def test_a_bare_claim_with_no_pointer_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"), encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, (
        f"a hand-edited flag with nothing behind it was accepted: {msg}")


def test_a_pointer_to_a_non_junit_file_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    (proj / "not_junit.xml").write_text("<results><verdict>PASS</verdict>"
                                        "</results>", encoding="utf-8")
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"
        "<functional_evidence>not_junit.xml</functional_evidence>"),
        encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, f"a non-JUnit document was accepted as a transcript: {msg}"


def test_a_pointer_to_a_failing_transcript_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    (proj / "failing.xml").write_text(_junit(tests=3, failures=2),
                                      encoding="utf-8")
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"
        "<functional_evidence>failing.xml</functional_evidence>"),
        encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, f"a failing transcript was accepted as a PASS: {msg}"


def test_a_dangling_pointer_is_still_a_forgery(tmp_path):
    proj = _project(tmp_path, None)
    _emit(proj)
    rec = proj / "phase2" / "stage1" / "sim" / "results.xml"
    rec.write_text(_record(proj).replace(
        "<functional_verified>false</functional_verified>",
        "<functional_verified>true</functional_verified>"
        "<functional_evidence>nowhere/results.xml</functional_evidence>"),
        encoding="utf-8")
    rc, msg = GATE._evaluate(proj)
    assert rc == 1, f"a dangling pointer was accepted: {msg}"


def test_a_connectivity_record_with_no_claim_still_refuses(tmp_path):
    """The pre-existing INCOMPLETE path must be untouched."""
    proj = _project(tmp_path, None)
    _emit(proj)
    rc, msg = GATE._evaluate(proj)
    assert rc == 1 and "INCOMPLETE" in msg, (
        f"connectivity-only evidence stopped being refused: rc={rc} {msg}")
