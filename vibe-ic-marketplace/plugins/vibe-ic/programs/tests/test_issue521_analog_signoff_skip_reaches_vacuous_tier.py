#!/usr/bin/env python3
"""#521 — the analog sign-off set must not report PASS about nothing.

THE DEFECT, AND WHY IT IS THE SAME ONE AS #515
==============================================
`flow_compliance_check` once decided tier membership purely from a gate's exit
code (rc 0 PASS / rc 1 FAIL / rc 2 VACUOUS). Seventeen gates computed
``summary["skipped"] = True``, stated an explicit reason in their own report,
and then returned ``0 if result.passed else 1`` — discarding that distinction
at the one place every automated consumer reads.

Measured on a mixed-signal design's own run directory, all seventeen answered
``rc=0`` with ``skipped: true``, while two gates on the SAME directory
(`analog_flow_compliance_check`, `mixed_signal_cosim_check`) answered rc 2 for
the identical situation. The set reporting PASS about analog content that was
never there is the analog sign-off set: block coverage, corner margin, corner
sweep, netlist connectivity, PDK conventions, pre-vs-post layout, SPICE
correlation, hard-macro pin consistency, Liberty non-degeneracy, A8-before-
floorplan ordering.

#1978 adds the cause boundary: a declared absence of analog content may remain
N/A, while absent post-layout or upstream outputs are BLOCKED/INCOMPLETE.

WHAT THESE TESTS DRIVE, AND WHAT THEY DELIBERATELY DO NOT
=========================================================
Asserting ``rc == 2`` in isolation proves a gate changed its mind, not that
the TIER moved. So the step-level and umbrella-level tests below call the
SHIPPED consumers unmocked, running each gate as a real subprocess, and the
step-30 test reads its gate spec out of the SHIPPED flow YAML rather than
restating it — a rewire that silently drops the gate makes that test fail.

Nothing here greps a gate's stdout to decide anything. The verdict under test
is the exit code, and the corroboration is the gate's OWN ``--json`` report.
The printed text is asserted only as OUTPUT — never used as an input to a
verdict, which would be the same defect one layer up.

THE PAIRED HALF IS NOT OPTIONAL
===============================
A change that made every gate skip everywhere would satisfy every vacuous
assertion here and would have BROKEN the seventeen. Each honest-PASS and
real-FAIL case below is a fixture the gate genuinely examines, and it is the
control that separates "the accounting was fixed" from "the gates were
disabled". `analog_a8_before_floorplan_check` earns both: it is VACUOUS on
200 of 200 tracked project roots, so its proof that it can still PASS and
still FAIL comes from a constructed fixture, not from the corpus.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

import _vacuous_exit as _vx  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)

import gate_discloses_denominator_check as _gdd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


#: The seventeen. Sixteen were confirmed by execution on a mixed-signal
#: design's run directory; `analog_a8_before_floorplan_check` came from a
#: systematic sweep of every json-capable gate and was confirmed the same way.
GATES_521 = (
    "analog_a8_before_floorplan_check",
    "analog_block_coverage_check",
    "analog_corner_margin_check",
    "analog_corner_sweep_check",
    "analog_digital_interface_check",
    "analog_hardmacro_check",
    "analog_hardmacro_pinname_consistency_check",
    "analog_hw_spice_correlation_check",
    "analog_liberty_nonzero_delay_check",
    "analog_netlist_connectivity_check",
    "analog_netlist_pdk_check",
    "analog_pre_vs_post_layout_check",
    "analog_tb_supply_pdk_check",
    "corner_yield_vs_spec_check",
    "otp_image_layer_consistency_check",
    "spice_correlation_check",
    "tristate_active_drive_check",
)

#: Of the seventeen, the ones a shipped flow STEP invokes through a
#: `program_exit_zero` / `optional_program_exit_zero` slot — where the tier
#: move is visible as a STEP status, not only inside the P0 umbrella.
LIVE_STEP_GATES = {
    "analog_netlist_pdk_check",             # A3
    "analog_pre_vs_post_layout_check",      # A7
    "analog_hardmacro_check",               # A8
    "analog_hw_spice_correlation_check",    # A9 (optional slot)
    "spice_correlation_check",              # 30
}

# #1978 splits the old rc-2 bucket by cause.  Only the hardmacro question has
# a derived design absence on this fixture; the others are waiting for process
# outputs and therefore remain incomplete.
LIVE_STEP_EXPECTED = {
    "analog_hardmacro_check": "VACUOUS_PASS",
    "analog_hw_spice_correlation_check": "INCOMPLETE",
    "analog_netlist_pdk_check": "INCOMPLETE",
    "analog_pre_vs_post_layout_check": "INCOMPLETE",
    "spice_correlation_check": "INCOMPLETE",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _run(gate: str, project: Path, report: Path | None = None):
    argv = [sys.executable, str(_PROGRAMS / f"{gate}.py"), str(project)]
    if report is not None:
        argv += ["--json", str(report)]
    return _pr.run(argv, capture_output=True, text=True,
                          cwd=str(_PROGRAMS))


def _report_says_skipped(report: Path):
    """The gate's OWN structured conclusion — the only thing routed."""
    doc = json.loads(report.read_text())
    summary = doc.get("summary")
    assert isinstance(summary, dict), doc
    return summary.get("skipped"), summary.get("reason")


def _empty_project(tmp_path: Path) -> Path:
    """A structurally empty but well-formed project: no analog, no RTL, no
    SPEF, no L11 — nothing any of the seventeen audits."""
    proj = tmp_path / "empty_project"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    return proj


# --------------------------------------------------------------------------
# 1. the shared router's #521 additions
# --------------------------------------------------------------------------

def test_skip_reason_reads_the_gates_own_token():
    assert _vx.skip_reason({"skipped": True, "reason": "no_analog_dir"}) \
        == "no_analog_dir"


def test_skip_reason_is_fail_safe_on_anything_unusable():
    """It only ever LABELS a conclusion already reached, so its uncertain
    case must be inert rather than raising."""
    for bad in (None, {}, "reason", [], {"reason": ""}, {"reason": None}):
        assert _vx.skip_reason(bad) == "unspecified"


def test_verdict_line_renders_the_same_three_way_split_exit_code_routes():
    assert _vx.verdict_line("g", passed=True, skipped=False,
                            reason="x") == "[PASS] g"
    assert _vx.verdict_line("g", passed=False, skipped=False,
                            reason="x").startswith("[FAIL] ")
    line = _vx.verdict_line("g", passed=True, skipped=True, reason="no_rtl")
    assert line.startswith("[VACUOUS] ")
    assert "no_rtl" in line


def test_verdict_line_and_exit_code_can_never_disagree():
    """Both are derived from the same (passed, skipped) pair. A gate that
    printed one verdict and exited with another is the drift that let a skip
    be announced in prose and credited as a pass."""
    token = {_vx.RC_PASS: "[PASS]", _vx.RC_FAIL: "[FAIL]",
             _vx.RC_VACUOUS: "[VACUOUS]"}
    for passed in (True, False):
        for skipped in (True, False):
            rc = _vx.exit_code(passed, skipped)
            assert _vx.verdict_line("g", passed, skipped, "r").startswith(
                token[rc]), (passed, skipped, rc)


def test_a_waiver_token_can_never_label_a_run_that_examined_nothing():
    """PASS_WITH_WAIVERS is a judgement about findings made over artefacts
    the gate read; it cannot describe a run that read none."""
    line = _vx.verdict_line("g", passed=True, skipped=True, reason="no_rtl",
                            pass_token="PASS_WITH_WAIVERS")
    assert line.startswith("[VACUOUS] ")
    assert "WAIVER" not in line.upper()


# --------------------------------------------------------------------------
# 2. every one of the seventeen, as a real subprocess, over an empty project
# --------------------------------------------------------------------------

@pytest.mark.parametrize("gate", GATES_521)
def test_gate_that_examined_nothing_exits_vacuous_not_pass(gate, tmp_path):
    """The core regression. Before #521 every one of these returned rc 0 with
    `skipped: true` in its own report."""
    proj = _empty_project(tmp_path)
    report = tmp_path / "r.json"
    p = _run(gate, proj, report)
    skipped, reason = _report_says_skipped(report)
    assert skipped is True, (gate, reason)
    assert p.returncode == _vx.RC_VACUOUS, (gate, p.returncode, reason,
                                            p.stdout[-400:], p.stderr[-400:])


@pytest.mark.parametrize("gate", GATES_521)
def test_the_rc_independent_sentinel_is_emitted_and_is_recognised(gate,
                                                                  tmp_path):
    """The second disclosure channel. It goes to stderr because `--json -`
    puts the report document on stdout for some of these gates, and it must
    be the token `flow_compliance_check` actually scans for."""
    proj = _empty_project(tmp_path)
    p = _run(gate, proj, tmp_path / "r.json")
    assert _flow._stdout_signals_vacuous(p.stderr), (gate, p.stderr[-300:])
    assert not _flow._stdout_signals_waiver(p.stderr), gate


@pytest.mark.parametrize("gate", GATES_521)
def test_human_mode_names_the_reason_instead_of_a_bare_pass(gate, tmp_path):
    """The issue's other half: `[PASS] <gate>` with no count, no evidence and
    no reason was the ENTIRE output of most of these."""
    proj = _empty_project(tmp_path)
    p = _run(gate, proj)
    head = p.stdout.strip().splitlines()[0]
    assert head.startswith("[VACUOUS] "), (gate, head)
    assert gate in head
    _skipped, reason = _report_says_skipped_from(gate, proj, tmp_path)
    assert reason and reason in head, (gate, head, reason)


def _report_says_skipped_from(gate: str, proj: Path, tmp_path: Path):
    report = tmp_path / f"{gate}.json"
    _run(gate, proj, report)
    return _report_says_skipped(report)


@pytest.mark.parametrize("gate", GATES_521)
def test_a_gate_is_never_credited_rc_zero_while_its_report_says_skipped(
        gate, tmp_path):
    """The invariant, stated directly: over the empty project the pair
    (rc == 0, summary.skipped == True) must be unreachable. This is the
    number the corpus sweep drove from 3299 to 0."""
    proj = _empty_project(tmp_path)
    report = tmp_path / "r.json"
    p = _run(gate, proj, report)
    skipped, _reason = _report_says_skipped(report)
    assert not (p.returncode == _vx.RC_PASS and skipped is True), gate


# --------------------------------------------------------------------------
# 3. THE PAIRED HALF — an honest pass and a real failure must both survive
# --------------------------------------------------------------------------

def _tristate_examinable(tmp_path: Path) -> Path:
    """RTL with a real inout pad driven active-high — something to audit."""
    proj = tmp_path / "tristate"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "pad.v").write_text(
        "module pad(input clk, input oe, input dout, inout wire bus);\n"
        "  assign bus = oe ? dout : 1'bz;\n"
        "endmodule\n")
    return proj


def _a8_ordering_observed(tmp_path: Path, with_lef: bool) -> Path:
    """A block list AND a floorplan DEF: the ordering constraint is live, so
    this gate genuinely evaluates it. `with_lef` selects PASS vs FAIL."""
    proj = tmp_path / ("a8_pass" if with_lef else "a8_fail")
    (proj / "phase3" / "analog").mkdir(parents=True)
    (proj / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["blk"]}))
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (proj / "phase3" / "stage3" / "pnr" / "floorplan.def").write_text(
        "VERSION 5.8 ;\nEND DESIGN\n")
    if with_lef:
        hm = proj / "phase3" / "analog" / "hardmacro" / "blk"
        hm.mkdir(parents=True)
        (hm / "blk.lef").write_text("MACRO blk\n  PIN a\n  END a\nEND blk\n")
    return proj


def _connectivity_examinable(tmp_path: Path) -> Path:
    proj = tmp_path / "conn"
    blk = proj / "phase3" / "analog" / "blk"
    blk.mkdir(parents=True)
    (blk / "blk.sp").write_text(
        ".subckt inv vin vout vdd vss\n"
        "Xm1 vout vin vdd vdd pfet w=1u l=1u\n"
        "Xm2 vout vin vss vss nfet w=1u l=1u\n"
        ".ends\n")
    return proj


def _otp_examinable(tmp_path: Path, matching: bool) -> Path:
    proj = tmp_path / ("otp_ok" if matching else "otp_bad")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    gd.joinpath("L11_OTP_CONTENT.json").write_text(json.dumps(
        {"address_map": [{"address": "0x00", "value": "0x5A"}]}))
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    val = "5A" if matching else "0A"
    (rtl / "otp.v").write_text(
        f"module otp;\n  initial begin\n    mem[8'h00] = 8'h{val};\n"
        "  end\nendmodule\n")
    return proj


def test_honest_pass_tristate_still_exits_zero(tmp_path):
    p = _run("tristate_active_drive_check", _tristate_examinable(tmp_path))
    assert p.returncode == _vx.RC_PASS, (p.returncode, p.stdout, p.stderr)
    assert p.stdout.strip().splitlines()[0].startswith("[PASS] ")


def test_honest_pass_netlist_connectivity_still_exits_zero(tmp_path):
    p = _run("analog_netlist_connectivity_check",
             _connectivity_examinable(tmp_path))
    assert p.returncode == _vx.RC_PASS, (p.returncode, p.stdout, p.stderr)


def test_honest_pass_otp_still_exits_zero(tmp_path):
    p = _run("otp_image_layer_consistency_check",
             _otp_examinable(tmp_path, matching=True))
    assert p.returncode == _vx.RC_PASS, (p.returncode, p.stdout, p.stderr)


def test_real_failure_otp_still_exits_one(tmp_path):
    p = _run("otp_image_layer_consistency_check",
             _otp_examinable(tmp_path, matching=False))
    assert p.returncode == _vx.RC_FAIL, (p.returncode, p.stdout, p.stderr)


def test_a8_ordering_gate_can_still_earn_a_plain_pass(tmp_path):
    """This gate is VACUOUS on 200 of 200 tracked project roots — every rc-0
    result it produced there came from a skip branch. That makes a corpus
    number useless as proof it still works, so the proof is constructed: a
    floorplan DEF plus a present A8 LEF is the one situation the gate exists
    to certify, and it must remain a plain PASS."""
    p = _run("analog_a8_before_floorplan_check",
             _a8_ordering_observed(tmp_path, with_lef=True))
    assert p.returncode == _vx.RC_PASS, (p.returncode, p.stdout, p.stderr)
    assert p.stdout.strip().splitlines()[0].startswith("[PASS] ")


def test_a8_ordering_gate_still_fails_a_real_ordering_inversion(tmp_path):
    """The other half of the same proof: the ordering violation this gate was
    written for must still be rc 1, not swallowed by the vacuous tier."""
    p = _run("analog_a8_before_floorplan_check",
             _a8_ordering_observed(tmp_path, with_lef=False))
    assert p.returncode == _vx.RC_FAIL, (p.returncode, p.stdout, p.stderr)


# --------------------------------------------------------------------------
# 4. consumer 1 — the STEP tier, through the real `check_step`
# --------------------------------------------------------------------------

def _synthetic_step(cmd: str) -> dict:
    return {"id": "T521", "name": "issue-521 tier probe", "stage": "stage1",
            "gate": {"program_exit_zero": cmd}}


@pytest.mark.parametrize("gate", sorted(LIVE_STEP_GATES))
def test_check_step_consumes_each_live_gate_reason_class(gate, tmp_path):
    """The real subprocess reason, not rc=2 alone, decides the step tier."""
    proj = _empty_project(tmp_path)
    result = _flow.check_step(proj, _synthetic_step(f"{gate} ."), waivers={})
    assert result.status == LIVE_STEP_EXPECTED[gate], (
        gate, result.status, result.reasons)


def test_check_step_keeps_an_examined_gate_in_the_plain_PASS_tier(tmp_path):
    """The paired half at step level. If the honest pass followed its
    neighbours into the vacuous tier, the gates would have been broken rather
    than the accounting fixed."""
    proj = _tristate_examinable(tmp_path)
    result = _flow.check_step(
        proj, _synthetic_step("tristate_active_drive_check ."), waivers={})
    assert result.status == "PASS", (result.status, result.reasons)


def test_check_step_still_FAILs_a_gate_that_found_a_violation(tmp_path):
    proj = _a8_ordering_observed(tmp_path, with_lef=False)
    result = _flow.check_step(
        proj, _synthetic_step("analog_a8_before_floorplan_check ."),
        waivers={})
    assert result.status == "FAIL", (result.status, result.reasons)


# --------------------------------------------------------------------------
# 5. the SHIPPED step, not a synthetic one
# --------------------------------------------------------------------------

def _shipped_steps() -> list:
    doc = yaml.safe_load(
        (_PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())
    steps = doc.get("steps") or []
    return steps if isinstance(steps, list) else []


def _shipped_step(step_id) -> dict:
    for st in _shipped_steps():
        if str(st.get("id")) == str(step_id):
            return st
    raise AssertionError(f"step {step_id} is not in the shipped flow")


def test_shipped_step_30_is_incomplete_without_correlation_inputs(
        tmp_path):
    """END-TO-END on the step definition the flow actually ships, so a rewire
    that drops the gate breaks this test rather than passing quietly.

    The fixture satisfies step 30's `files_exist` sub-gate (a SPICE deck is
    present) while the program still has nothing to correlate — no SPEF, no
    STA. That is precisely the state the vacuous tier exists to name."""
    step = _shipped_step(30)
    assert "spice_correlation_check" in _flow._declared_gate_commands(
        step["gate"]), step["gate"]

    proj = tmp_path / "step30"
    (proj / "phase3" / "stage3" / "spice").mkdir(parents=True)
    (proj / "phase3" / "stage3" / "spice" / "crit.sp").write_text("* deck\n.end\n")
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "spice_correlation.json").write_text("{}")

    result = _flow.check_step(proj, step, waivers={})
    assert result.status == "INCOMPLETE", (result.status, result.reasons)


def test_the_live_step_wiring_is_what_this_change_measured(tmp_path):
    """Pins WHICH of the seventeen a step invokes, derived structurally from
    the shipped YAML (never a text scan, so a program named only in a comment
    cannot count). A future rewire changes this list visibly."""
    wired = set()
    for st in _shipped_steps():
        gate = st.get("gate")
        if not gate:
            continue
        for prog in _flow._declared_gate_commands(gate):
            if prog in GATES_521:
                wired.add(prog)
    assert wired == LIVE_STEP_GATES, sorted(wired ^ LIVE_STEP_GATES)


# --------------------------------------------------------------------------
# 6. consumer 2 — the P0 structural umbrella
# --------------------------------------------------------------------------

_P0_REGISTERED = tuple(
    g for g in GATES_521 if g in set(_flow._STRUCTURAL_RTL_GATES))

_P0_EXPECTED = {
    "analog_block_coverage_check": ("SKIP", "DESIGN_DECLARED_NA"),
    "analog_corner_sweep_check": ("BLOCKED", "BLOCKED_BY_UPSTREAM"),
    "analog_digital_interface_check": ("SKIP", "DESIGN_DECLARED_NA"),
    "analog_hardmacro_check": ("SKIP", "DESIGN_DECLARED_NA"),
    "analog_hw_spice_correlation_check":
        ("BLOCKED", "BLOCKED_BY_UPSTREAM"),
    "analog_netlist_pdk_check": ("BLOCKED", "BLOCKED_BY_UPSTREAM"),
    "analog_pre_vs_post_layout_check":
        ("BLOCKED", "BLOCKED_BY_UPSTREAM"),
    "otp_image_layer_consistency_check":
        ("BLOCKED", "BLOCKED_BY_UPSTREAM"),
    "spice_correlation_check": ("BLOCKED", "BLOCKED_BY_UPSTREAM"),
    "tristate_active_drive_check": ("SKIP", "DESIGN_DECLARED_NA"),
}


def test_the_umbrella_registers_the_expected_subset():
    """Ten of the seventeen are registered structural gates; the other seven
    reach a report only through direct invocation or a step slot. Pinned so
    the split is a stated fact rather than an assumption of the test below."""
    assert len(_P0_REGISTERED) == 10, _P0_REGISTERED


def _rtl_only_project(tmp_path: Path) -> Path:
    """The umbrella only runs its structural gates when RTL is present, so an
    EMPTY project would make the tests below vacuous in their own right.

    This RTL is deliberately plain — a counter, no inout pad, no OTP, no
    analog, no SPEF — so every gate under test still has nothing to examine
    and must land in the SKIP tier, while the umbrella genuinely runs."""
    proj = tmp_path / "rtl_only"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "counter.v").write_text(
        "module counter(input clk, input rst, output reg [7:0] q);\n"
        "  always @(posedge clk) if (rst) q <= 8'd0; else q <= q + 8'd1;\n"
        "endmodule\n")
    return proj


@pytest.mark.parametrize("gate", _P0_REGISTERED)
def test_p0_umbrella_records_the_nonverdict_cause(gate, tmp_path, monkeypatch):
    proj = _rtl_only_project(tmp_path)
    monkeypatch.setattr(_flow, "_STRUCTURAL_RTL_GATES", (gate,))
    records: list = []
    _flow._run_structural_rtl_gates(proj, records_out=records)
    assert len(records) == 1, records
    rec = records[0]
    expected_verdict, expected_class = _P0_EXPECTED[gate]
    assert rec["verdict"] == expected_verdict, rec
    assert rec["reason_class"] == expected_class, rec
    assert rec["evidence"]["exit_code"] == _vx.RC_VACUOUS, rec
    assert rec["evidence"]["skip_kind"] == "input-missing", rec
    assert _flow._p0_passed_count(records) == 0


def test_p0_umbrella_still_records_an_examined_gate_as_PASS(tmp_path,
                                                            monkeypatch):
    proj = _tristate_examinable(tmp_path)
    monkeypatch.setattr(_flow, "_STRUCTURAL_RTL_GATES",
                        ("tristate_active_drive_check",))
    records: list = []
    _flow._run_structural_rtl_gates(proj, records_out=records)
    assert records[0]["verdict"] == "PASS", records[0]
    assert _flow._p0_passed_count(records) == 1


def test_a_vacuous_skip_is_never_misread_as_a_caller_defect(tmp_path):
    """rc 2 also means "argparse rejected your argv" (#492), and the umbrella
    separates the two by reading the callee's error protocol. The disclosure
    line these gates now emit must not trip that classifier — otherwise a
    benign skip would be reported as NOT_INVOCABLE."""
    import _gate_invocation as _gi
    proj = _empty_project(tmp_path)
    for gate in GATES_521:
        p = _run(gate, proj)
        assert _gi.classify_not_invocable(p.stdout, p.stderr,
                                          supplied_flags=[]) is None, gate


# --------------------------------------------------------------------------
# 7. the disclosure ratchet this change shortened
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# 8. two of #515's three unreproduced LEADS, reproduced
#
# #515 left three leads it could not make skip, and this issue restated them
# as leads. They stayed unreproduced for a MEASUREMENT reason, not a code
# reason: all three take FLAGS (`--rtl-dir`, `--project-dir`, `--l9-file`),
# not a positional project directory. A probe that passes a project directory
# is rejected by argparse, which exits 2 — and an rc of 2 from a probe looking
# for rc 0 reads as "did not reproduce". Driven through their own documented
# interfaces, two of the three reproduce immediately and the third turns out
# not to be an instance of this class at all.
# --------------------------------------------------------------------------

def test_lead_pre_awake_silence_reproduces_and_is_now_vacuous(tmp_path):
    """RTL with no wake/sleep signal: 106 of the 107 tracked RTL directories.
    Confirmed on a tracked design's RTL before the fix."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(
        "module top(input clk, input [7:0] cmd, output reg [7:0] rsp);\n"
        "  always @(posedge clk) rsp <= cmd;\n"
        "endmodule\n")
    p = _pr.run(
        [sys.executable, str(_PROGRAMS / "pre_awake_silence_check.py"),
         "--rtl-dir", str(rtl)],
        capture_output=True, text=True, cwd=str(_PROGRAMS))
    doc = json.loads(p.stdout)
    assert doc["summary"]["skipped"] is True
    assert p.returncode == _vx.RC_VACUOUS, (p.returncode, p.stderr[-300:])
    assert _flow._stdout_signals_vacuous(p.stderr)


def test_lead_pre_awake_silence_still_fails_an_ungated_dispatcher(tmp_path):
    """The paired half: RTL that DOES have a wake signal and dispatches
    without guarding on it must still be rc 1."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "ctrl.v").write_text(
        "module ctrl(input clk, input wake_req, output reg awake);\n"
        "  always @(posedge clk) if (wake_req) awake <= 1'b1;\n"
        "endmodule\n")
    (rtl / "dispatch.v").write_text(
        "module dispatch(input clk, input [7:0] opcode, output reg [7:0] q);\n"
        "  always @(posedge clk) begin\n"
        "    case (opcode)\n"
        "      8'h01: q <= 8'hA0;\n"
        "      8'h02: q <= 8'hB0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n")
    p = _pr.run(
        [sys.executable, str(_PROGRAMS / "pre_awake_silence_check.py"),
         "--rtl-dir", str(rtl)],
        capture_output=True, text=True, cwd=str(_PROGRAMS))
    assert p.returncode == _vx.RC_FAIL, (p.returncode, p.stdout[-400:])


def test_lead_warn_acceptance_policy_reproduces_and_is_now_vacuous(tmp_path):
    """No reports directory: not one gate report was read, so "every WARN is
    addressed" holds only because no WARN was ever loaded."""
    proj = tmp_path / "no_reports"
    proj.mkdir()
    p = _pr.run(
        [sys.executable, str(_PROGRAMS / "warn_acceptance_policy_check.py"),
         "--project-dir", str(proj)],
        capture_output=True, text=True, cwd=str(_PROGRAMS))
    doc = json.loads(p.stdout)
    assert doc["summary"]["skipped"] is True
    assert p.returncode == _vx.RC_VACUOUS, (p.returncode, p.stderr[-300:])
    assert _flow._stdout_signals_vacuous(p.stderr)


def test_lead_warn_acceptance_policy_keeps_its_honest_pass(tmp_path):
    """The paired half, and the one that matters most here: 112 of the 132
    tracked project roots DO have a reports directory and pass honestly. That
    path builds a summary with no `skipped` key at all, which
    `summary_is_skipped` reads as "examined something"."""
    proj = tmp_path / "with_reports"
    (proj / "reports").mkdir(parents=True)
    (proj / "reports" / "gate.json").write_text(json.dumps(
        {"program": "some_check", "findings": []}))
    p = _pr.run(
        [sys.executable, str(_PROGRAMS / "warn_acceptance_policy_check.py"),
         "--project-dir", str(proj)],
        capture_output=True, text=True, cwd=str(_PROGRAMS))
    assert p.returncode == _vx.RC_PASS, (p.returncode, p.stdout[-400:])
    assert "skipped" not in json.loads(p.stdout)["summary"]


def test_lead_l9_completeness_is_not_an_instance_of_this_class():
    """The third lead, and the reason it stays unfixed: its `skipped` is a
    PER-SECTION field inside `section_summary["registers"]`, describing one
    requirement that a declared `no_registers: true` waives. There is no
    top-level `summary.skipped` for a router to read, and the gate never
    claims to have examined nothing overall. Recorded so the next sweep does
    not re-open it as an oversight."""
    src = (_PROGRAMS / "l9_completeness_check.py").read_text()
    assert '"skip_reason": "L9.no_registers=true (declared)"' in src
    assert "_vacuous_exit" not in src


def test_the_silent_pass_inventory_no_longer_lists_these_gates():
    """`gate_discloses_denominator_check` froze fourteen of these on
    2026-07-28 as answering a bare `[PASS] <gate>` over an empty project. Its
    inventory is an exact-set ratchet in BOTH directions, so leaving them in
    after they started exiting rc 2 would have raised fourteen
    STALE_INVENTORY_ENTRY findings. The list can only get shorter, and only
    by a visible edit — this is that edit, pinned."""
    inventory = set(_gdd._EMPTY_PROJECT_SILENT_PASS)
    assert inventory & set(GATES_521) == set(), sorted(
        inventory & set(GATES_521))
    assert "benchmark_clean_room_check" in inventory, (
        "a different defect, out of #521's reach; it must keep being counted")
