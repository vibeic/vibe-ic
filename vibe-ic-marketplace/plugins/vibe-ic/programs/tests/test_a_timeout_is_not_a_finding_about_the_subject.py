#!/usr/bin/env python3
"""test_a_timeout_is_not_a_finding_about_the_subject.py

Handlers from the timeout-as-verdict census that CAUGHT a runtime bound firing
and recorded it as a defect in whatever they were pointed at.

THE FIRST VERSION OF THIS FILE TESTED THE WRONG FIX, AND IT IS RETRACTED. It
asserted that each site had stopped ACCUSING — moving the exit code to "cannot
adjudicate", the detail string to INCONCLUSIVE, the skip reason to NOT MEASURED —
while leaving every kill in place. That is honest reporting of destroyed work.
A bound that fires on a job which was one second from finishing has thrown the
result away whatever it then writes in the log, and a fast host and a loaded
host still disagree about the same subject.

THE KILL IS THE DEFECT. Every site below now runs under
`_watchdog.run_host_supervised`, which bounds NO PROGRESS and never runtime:
CPU (`utime+stime`) and I/O (`read_bytes+write_bytes`) are read from `/proc`
across the whole process tree and the captured output is watched for growth, so
any signal moving resets the grace. The old constants survive as GRACE windows,
which can only ever kill LESS than they did as runtime caps — both stop a job
idle for N, and only the runtime cap stopped a job still working at N.

What each site says on a genuine stall is now a MEASURED finding with evidence
("no CPU, no I/O for Ns; it was not slow, it was doing nothing"), which is a real
verdict rather than a shrug — and where that verdict is still "cannot
adjudicate", it is because a wedged adjudicator genuinely made no finding about
its subject, not because a clock ran out.

  * `verilator_timing_fallback_check.adjudicate` — the file's own exit-code
    table says rc 1 is "golden FAILS its own TB under Verilator" and rc 2 is
    "cannot adjudicate". Both timeout branches printed "cannot adjudicate" and
    returned 1.
  * `tb_vcs_only_construct_detect.floor_proof` — every rc it did not recognise
    was labelled VERILATOR_ABSENT, so a host where Verilator was PRESENT and
    merely slow published a record saying the tool was missing.
  * `handoff_bundle_check._git_apply_check` — "`git apply --check` timed out"
    was returned in the slot that means "does not apply", i.e. a finding about
    the candidate patch. The same file already had the right shape one function
    away, for a composed program that CRASHES.
  * `fresh_agent_rtl_bug_density_metric._resolve_repo_root` — git failing to RUN
    and git saying "not a repository" both became `None`, and the caller
    published the second as the reason. On a slow host the metric asserted
    something FALSE about the project it was pointed at.

BOTH DIRECTIONS, everywhere. Each fix keeps the conservative outcome exactly
where it was — the FLOOR still stands, the bundle is still not admitted, the
metric still declines to report a number — and changes only what the record
CLAIMS was observed. Where the fix moved an rc, the accompanying test asserts
the old rc's own meaning is still reachable by the thing that really means it.

No design, PDK, vendor or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_a_timeout_is_not_a_finding_about_the_subject.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _watchdog as W                            # noqa: E402
import verilator_timing_fallback_check as VF      # noqa: E402
import tb_vcs_only_construct_detect as TB         # noqa: E402
import dynamic_ir_vectored_emit as DIE            # noqa: E402
import dynamic_ir_drop_check as DIC               # noqa: E402


# ── the constructed violation, one shape reused ─────────────────────────────

class _Stalls:
    """A `run_host_supervised` that reports the job's tree made no progress.

    The SUBJECT is the handler, not the clock: what a program does once the
    supervisor has told it "this tree is idle" is the question, and the answer
    does not depend on how long the real grace would have taken. The live
    supervisor itself is exercised end to end in
    `test_a_wedged_tool_is_caught_a_slow_one_is_not.py`.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, argv, *a, **kw):
        self.calls += 1
        return W.SupervisedResult(rc=W.RC_STALLED, out="", err="WATCHDOG_STALLED",
                                  outcome="stalled", elapsed_s=1.0)


class _StallsDocker:
    """The same constructed violation for `run_docker_supervised`, which
    returns a plain `(rc, out, err)` triple rather than a `SupervisedResult`.
    The SUBJECT is still the handler: what the program writes once the
    supervisor has said "this tree is idle"."""

    def __init__(self):
        self.calls = 0

    def __call__(self, container, cmd, marker, **kw):
        self.calls += 1
        return (W.RC_STALLED, "",
                "WATCHDOG_STALLED: configured forward-progress signals did not "
                "advance for > 1800s — killed as hung, not slow.")


class _Completes:
    """A `run_host_supervised` that reports a natural exit with a given rc."""

    def __init__(self, rc=0, out="", err=""):
        self._r = (rc, out, err)

    def __call__(self, argv, *a, **kw):
        rc, out, err = self._r
        return W.SupervisedResult(rc=rc, out=out, err=err, outcome="natural",
                                  elapsed_s=0.1)


# ── verilator_timing_fallback_check ─────────────────────────────────────────

_GOLDEN = ("module dut(input clk, output reg [3:0] q);\n"
           "  always @(posedge clk) q <= 4'd5;\n"
           "endmodule\n")
_TB_SRC = ("module tb;\n  reg clk = 0; wire [3:0] q;\n"
           "  dut uut(.clk(clk), .q(q));\n"
           "  initial begin #20; $finish; end\n"
           "endmodule\n")


def _tb_and_golden(tmp_path: Path):
    tb = tmp_path / "tb.v"
    golden = tmp_path / "golden.v"
    tb.write_text(_TB_SRC)
    golden.write_text(_GOLDEN)
    return tb, golden


def _adjudicate(tmp_path, monkeypatch, runner):
    tb, golden = _tb_and_golden(tmp_path)
    monkeypatch.setattr(VF, "verilator_available", lambda: True)
    monkeypatch.setattr(VF._wd, "run_host_supervised", runner)
    return VF.adjudicate(tb, golden, "tb", "dut", "dut", None,
                         list(VF._DEFAULT_PASS), list(VF._DEFAULT_FAIL))


def test_a_verilator_build_that_is_WEDGED_is_not_a_finding_about_the_golden(
        tmp_path, monkeypatch):
    """A build whose whole tree is idle is wedged — a measured fact about the
    adjudicator, so it adjudicated nothing. rc 1 would accuse the golden of
    failing a build that never ran."""
    rc, msg = _adjudicate(tmp_path, monkeypatch, _Stalls())
    assert rc == 2, (rc, msg)
    assert "STALLED" in msg and "no forward progress" in msg, msg
    assert "It was not slow; it was doing nothing." in msg, msg
    assert "NOT a finding about the golden" in msg


def test_the_floor_still_stands_when_verilator_could_not_be_adjudicated(
        tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT MOVE. The conservative direction of this gate is
    that an unadjudicated construct stays floored — never waved through as
    scorable. Moving the rc must not have moved that."""
    rc, msg = _adjudicate(tmp_path, monkeypatch, _Stalls())
    assert rc != 0, "an unadjudicated TB became FAITHFUL — the guard was deleted"
    assert "FLOOR-D stands" in msg


def test_rc_one_is_still_reachable_by_a_golden_that_actually_fails(
        tmp_path, monkeypatch):
    """NON-VACUITY. The fix must not have emptied rc 1 of its meaning: a build
    that RAN and returned non-zero is still VERILATOR_UNFAITHFUL."""
    rc, msg = _adjudicate(tmp_path, monkeypatch,
                          _Completes(rc=1, err="%Error: no.\n"))
    assert rc == 1, (rc, msg)
    assert "VERILATOR_BUILD_FAIL" in msg


def test_the_exit_code_table_states_that_nothing_is_bounded_by_runtime():
    """The table is what a caller reads before writing the branch. It must say
    the thing that is now true and was not: neither the build nor the sim has a
    runtime cap at all."""
    doc = VF.__doc__
    assert "CANNOT ADJUDICATE" in doc
    assert "neither the build nor the" in doc and "RUNTIME" in doc, doc
    assert "A run that was wedged is not" in doc


# ── tb_vcs_only_construct_detect ────────────────────────────────────────────

def test_a_slow_verilator_is_not_recorded_as_an_absent_one(
        tmp_path, monkeypatch):
    """The record is what survives the run. VERILATOR_ABSENT on a host that HAS
    verilator is a false statement about the host, published as measured."""
    tb, golden = _tb_and_golden(tmp_path)
    monkeypatch.setattr(VF, "verilator_available", lambda: True)
    monkeypatch.setattr(VF._wd, "run_host_supervised", _Stalls())
    rec = TB.floor_proof(tb, golden, "tb", "dut")
    assert rec["verdict"] == "CANNOT_ADJUDICATE", rec
    assert rec["verdict"] != "VERILATOR_ABSENT"
    # and the conservative disposition is untouched
    assert rec["disposition"] == "FORK-FIXABLE", rec
    assert rec["rc"] == 2, rec


# ── handoff_bundle_check ────────────────────────────────────────────────────







# ── fresh_agent_rtl_bug_density_metric ──────────────────────────────────────







# ── the pre-fix control ─────────────────────────────────────────────────────





# ── dynamic_ir_vectored_emit ────────────────────────────────────────────────
#
# The payload is the whole product here: this program's caller in
# `phase3_one_shot_runner` runs it with `check=False`, discards the return value
# entirely, and asks only whether the JSON file exists. So what the FILE says is
# what the flow believes — and it was being told a tool error, by a 1800 s cap
# on a transient PSM solve over a large die, which is precisely the honest long
# work a runtime bound destroys.


def _stage_declared_views(tmp_path) -> None:
    """The physical views the run DECLARES, staged so they can be read.

    RE-PINNED 2026-09-21. This test used to name four paths it never created and
    reach the openroad launch anyway. c34f56d2a (v1.22.13, #2376) gave
    `dynamic_ir_vectored_emit` a pre-flight over its declared views -- every LEF
    non-empty, no master defined twice, every DEF component master defined by
    some LEF -- and refuses ERROR_INPUT_VIEWS before launching anything. So the
    fixture stopped reaching the watchdog path at all and the payload came back

        status ERROR_INPUT_VIEWS
        reason "missing, empty or unreadable declared LEF: <tmp>/t.lef"

    THE PROGRAM IS RIGHT and the ordering is not the defect: an IR solve over
    views that cannot describe the design has nothing to measure, and finding
    that out before starting a long solve is the cheap end of the check. What
    was wrong is a fixture that only worked while the program skipped it.

    The views are minimal but VALID rather than merely non-empty -- the DEF
    names a master the cell LEF defines -- so the pre-flight is exercised on its
    real path instead of being satisfied by an empty COMPONENTS section.
    """
    (tmp_path / "t.lef").write_text(
        "VERSION 5.8 ;\nUNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\n")
    (tmp_path / "c.lef").write_text(
        "VERSION 5.8 ;\nMACRO CELLA\n  CLASS CORE ;\nEND CELLA\n")
    (tmp_path / "x.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\n"
        "COMPONENTS 1 ;\n- u1 CELLA ;\nEND COMPONENTS\n"
        "END DESIGN\n")
    (tmp_path / "l.lib").write_text("library (l) { }\n")


def test_a_wedged_openroad_is_named_as_wedged_and_not_as_a_failed_run(
        tmp_path, monkeypatch):
    """The reason string is what a reader gets. "openroad run failed" is false
    of a solver that was still solving; "made no forward progress ... it was
    doing nothing" is a measurement, and only reachable when it is true."""
    monkeypatch.setattr(DIE._dw, "run_docker_supervised", _StallsDocker())
    _stage_declared_views(tmp_path)
    out = tmp_path / "dynamic_ir.json"
    rc, payload = DIE.emit(
        def_file=tmp_path / "x.def", tech_lef=tmp_path / "t.lef",
        cell_lef=tmp_path / "c.lef", liberty=tmp_path / "l.lib",
        macro_lefs=[], sdc=None, out_json=out, power_net="VDD",
        container="c", metal_prefix="met", static_json=None, budget_pct=5.0,
        period_ns=8.0, steps=50, decap_cap=None)
    assert payload.get("status") != "ERROR_INPUT_VIEWS", (
        "the declared views must pass the pre-flight, or this test is measuring "
        "input validation and not the watchdog: " + str(payload))
    assert payload["dynamic_ir_report_emitted"] is False
    assert "no forward progress" in payload["reason"], payload
    assert "WEDGED" in payload["reason"], payload
    assert "did not finish within its bound" not in payload["reason"]


def test_the_wedged_report_reads_as_a_tool_error_downstream(tmp_path):
    """THE HALF THAT MUST NOT MOVE — and #2109 corrected which half that is.

    This test used to assert the wedged report "still reads as a SKIP
    downstream". That was the wrong invariant, and it pinned the defect: a
    WEDGED openroad exited 0 through step 24's declared-blocking clause. The
    half that genuinely must not move is the one this file is named for — a
    tool that was stopped is a measured fact ABOUT THE TOOL, and it must reach
    the reader saying so. So: no droop number is read out of it, the WEDGED
    wording survives, and the verdict is a tool error that BLOCKS.

    (Renamed from `test_the_wedged_report_still_reads_as_a_skip_downstream`.)"""
    payload = {"status": "ERROR_TOOL", "dynamic_ir_report_emitted": False,
               "reason": ("the openroad transient run made no forward progress "
                          "for 1800s and was stopped. openroad was WEDGED.")}
    j = tmp_path / "dynamic_ir.json"
    j.write_text(json.dumps(payload))
    res = DIC.check(j, 1.8)
    # The VALUE comparison first, so the pre-fix arm fails on a concrete pair
    # (['SKIPPED_CONDITION', None]) rather than on an `is None` sentinel.
    assert [res.get("verdict"), res.get("status")] == \
        ["TOOL_ERROR", "ERROR_TOOL"], res
    assert "WEDGED" in res.get("tool_line", ""), res
    # it is NOT an honest skip — that is what let it exit 0
    assert DIC._is_honest_skip(payload) is None, "a wedged tool still skips"
    status, why = DIC._is_tool_error(payload)
    assert status == "ERROR_TOOL"
    assert "WEDGED" in why, why
    # no droop number is read out of it (the original property, kept)
    assert "worst_transient_droop_mv" not in res, res
    assert DIC.main([str(j)]) == 1
