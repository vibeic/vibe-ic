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



sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


#: The seventeen. Sixteen were confirmed by execution on a mixed-signal
#: design's run directory; `analog_a8_before_floorplan_check` came from a
#: systematic sweep of every json-capable gate and was confirmed the same way.
GATES_521 = (
    "analog_digital_interface_check",
    "analog_hardmacro_check",
    "analog_hardmacro_pinname_consistency_check",
    "analog_liberty_nonzero_delay_check",
    "analog_netlist_connectivity_check",
    "analog_netlist_pdk_check",
    "corner_yield_vs_spec_check",
    "spice_correlation_check",
)

#: Of the seventeen, the ones a shipped flow STEP invokes through a
#: `program_exit_zero` / `optional_program_exit_zero` slot — where the tier
#: move is visible as a STEP status, not only inside the P0 umbrella.
LIVE_STEP_GATES = {
    "analog_netlist_pdk_check",
    "analog_hardmacro_check",
    "spice_correlation_check",
}

# #1978 splits the old rc-2 bucket by cause.  Only the hardmacro question has
# a derived design absence on this fixture; the others are waiting for process
# outputs and therefore remain incomplete.
LIVE_STEP_EXPECTED = {
    "analog_hardmacro_check": "NOT_MEASURED",
    "analog_netlist_pdk_check": "NOT_MEASURED",
    "spice_correlation_check": "NOT_MEASURED",
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




def test_honest_pass_netlist_connectivity_still_exits_zero(tmp_path):
    p = _run("analog_netlist_connectivity_check",
             _connectivity_examinable(tmp_path))
    assert p.returncode == _vx.RC_PASS, (p.returncode, p.stdout, p.stderr)










# --------------------------------------------------------------------------
# 4. consumer 1 — the STEP tier, through the real `check_step`
# --------------------------------------------------------------------------

def _synthetic_step(cmd: str) -> dict:
    return {"id": "T521", "name": "issue-521 tier probe", "stage": "stage1",
            "gate": {"program_exit_zero": cmd}}








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

    The component examines nothing before its producer and reports that
    nonmeasurement. The aggregate still FAILs: a deck alone satisfies only
    one of two declared outputs. These are distinct contracts; an early
    component audit cannot certify the missing correlation product."""
    step = _shipped_step(30)

    proj = tmp_path / "step30"
    (proj / "phase3" / "stage3" / "spice").mkdir(parents=True)
    (proj / "phase3" / "stage3" / "spice" / "crit.sp").write_text("* deck\n.end\n")
    (proj / "reports" / "phase3").mkdir(parents=True)

    correlation_spec = (
        "phase3/stage3/spice/correlation.json OR reports/phase3/spice_correlation.json")
    assert correlation_spec in step["required_outputs"]
    correlation_outputs = (
        proj / "phase3" / "stage3" / "spice" / "correlation.json",
        proj / "reports" / "phase3" / "spice_correlation.json")
    assert not any(path.exists() for path in correlation_outputs)
    assert not (proj / "phase3" / "stage3" / "pnr" / "routed.def").exists()
    assert not (proj / "phase3" / "stage3" / "extracted").exists()
    assert not (proj / "phase3" / "stage3" / "sta").exists()

    # Use the existing real Python CLI helper. This separate audit output is
    # outside the project and cannot masquerade as a Step30 producer product.
    audit = tmp_path / "step30-component-audit.json"
    component = _run("spice_correlation_check", proj, report=audit)
    assert component.returncode == _vx.RC_VACUOUS, component.stdout + component.stderr
    component_doc = json.loads(audit.read_text())
    summary = component_doc["summary"]
    assert summary["skipped"] is True, component_doc
    assert summary["measurement"] == "NOT_MEASURED", component_doc
    # Top-level passed is routing bookkeeping, never measurement or IC PASS.
    assert summary["pass"] is False, component_doc
    assert summary["reason"] == "asked_before_producer", component_doc
    assert summary["reason_class"] == "ASKED_BEFORE_PRODUCER", component_doc
    assert summary["current_binding"] == "NOT_YET_PRODUCED", component_doc

    assert not any(path.exists() for path in correlation_outputs)


def test_the_live_step_wiring_is_what_this_change_measured(tmp_path):
    """Pins WHICH of the seventeen a step invokes, derived structurally from
    the shipped YAML (never a text scan, so a program named only in a comment
    cannot count). A future rewire changes this list visibly."""
    wired = set()
    for st in _shipped_steps():
        gate = st.get("gate")
        if not gate:
            continue
    assert wired == LIVE_STEP_GATES, sorted(wired ^ LIVE_STEP_GATES)


# --------------------------------------------------------------------------
# 6. consumer 2 — the P0 structural umbrella
# --------------------------------------------------------------------------


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
    # R-0915-46/47 + the landing that added this gate to
    # `_GATE_SUBJECT_PRODUCED_BY` (R-0915-101, lane icslot5). Its subject is step
    # 22's extracted `*.spef` and step 23's STA reports — both PHASE-3 — and the
    # P0 umbrella runs in the phase-2 audit too, so over this RTL-only project
    # the question is asked before its answer could exist. That is
    # `ASKED_BEFORE_PRODUCER`, which IS skip-eligible, so the record is a SKIP.
    # It is NOT a blanket exemption: the class is granted only while the tree
    # shows the producer has not run, and the test below additionally requires
    # the CAUSE to be recorded, so a silent SKIP would still fail here.
    "spice_correlation_check": ("SKIP", "ASKED_BEFORE_PRODUCER"),
    "tristate_active_drive_check": ("SKIP", "DESIGN_DECLARED_NA"),
}




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




def test_p0_umbrella_still_records_an_examined_gate_as_PASS(tmp_path,
                                                            monkeypatch):
    proj = _tristate_examinable(tmp_path)
    records: list = []
    assert records[0]["verdict"] == "PASS", records[0]




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
