#!/usr/bin/env python3
"""ORGANIC #705 — DETERMINISTIC latency-conformance gate
`programs/latency_conformance_check.py`.

The agent's SELF-testbench is untrustworthy for timing: across four blind
strategies agents scored 0/8 on off-by-one latency failures because each
improvised a counting convention that matched its OWN (wrong) RTL. The gate is
the independent yard-stick: it generates its OWN canonical measurement TB,
MEASURES the RTL's real event->output latency (counting posedges from the
one-cycle event pulse to the output assertion), RESOLVES the spec literal
against the module's parameters, and BLOCKS on mismatch.

Tests
=====
POSITIVE / 驗收 VERBATIM (iverilog-gated)
  * an OFF-BY-ONE divider (latency WIDTH+1) → `LATENCY-MISMATCH` + rc 1.
  * the CORRECTED divider (latency WIDTH+2) → `latency-conformance ok` + rc 0.
  * the corrected design scales with --param (WIDTH=4 → WIDTH+2 == 6).

iverilog-INDEPENDENT
  * --expect resolution (WIDTH+2 default + --param override + the `N+1`/literal
    forms), port/param parsing via the SHARED helpers, the safe evaluator
    REJECTING non-arithmetic (no eval of arbitrary code), reset-polarity
    auto-detect, the iverilog-absent SKIP path (monkeypatch shutil.which→None).

§4.05 NO-LEAK (this is a BLOCKING gate)
  * a correct-latency design PASSES (rc 0) and an off-by-one FAILS (rc 1) — the
    gate does NOT false-BLOCK a correct design and DOES block a wrong one.
  * a timeout design reports TIMEOUT (rc 1), never a bogus measurement.
  * iverilog ABSENT → SKIP (rc 0), NEVER a fabricated measurement or PASS.

chip-AGNOSTIC: pure measurement + comparison; no chip/SKU literal (enforced by
source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import shutil
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "latency_conformance_check.py"

_spec = importlib.util.spec_from_file_location("latency_conformance_check",
                                               str(_PROG))
lcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lcc)

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)


# ── the 驗收 fixtures: parameterised dividers (default WIDTH=8) ───────────────
# CORRECT: `valid` asserts WIDTH+2 cycles after `start`
#   (+1 IDLE->BUSY overhead, +WIDTH iterations, +1 register valid).
_RTL_CORRECT = """\
module divider #(parameter WIDTH = 8) (
    input                  clk,
    input                  rst_n,
    input                  start,
    input  [WIDTH-1:0]     dividend,
    input  [WIDTH-1:0]     divisor,
    output reg [WIDTH-1:0] quotient,
    output reg             valid
);
    localparam IDLE = 2'd0, BUSY = 2'd1, DONE = 2'd2;
    reg [1:0] state;
    reg [$clog2(WIDTH+2)-1:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; cnt <= 0; valid <= 1'b0; quotient <= 0;
        end else begin
            valid <= 1'b0;
            case (state)
                IDLE: if (start) begin state <= BUSY; cnt <= 0; end
                BUSY: if (cnt == WIDTH-1) state <= DONE;
                      else cnt <= cnt + 1'b1;
                DONE: begin valid <= 1'b1; quotient <= dividend; state <= IDLE; end
            endcase
        end
    end
endmodule
"""

# OFF-BY-ONE: terminal compare fires one iteration early → latency WIDTH+1.
_RTL_OFFBYONE = _RTL_CORRECT.replace("cnt == WIDTH-1", "cnt == WIDTH-2")

# a design whose output never asserts (timeout fixture).
_RTL_NEVER = """\
module divider #(parameter WIDTH = 8) (
    input clk, input rst_n, input start,
    input [WIDTH-1:0] dividend, output reg valid
);
    always @(posedge clk or negedge rst_n)
        if (!rst_n) valid <= 1'b0; else valid <= 1'b0;
endmodule
"""

# ── CANONICAL-CONVENTION boundary fixtures (clean shift regs, NO FSM) ─────────
# The convention MUST measure EXACTLY N for an N-stage shift register and 0 for
# a purely-combinational pass-through — pinning the latency-0/1 boundary that a
# negedge-sampled TB mis-reads (the HIGH bug). `out`/`start` are the
# event/output ports.
_RTL_SR1 = """\
module sr1 (input clk, input rst_n, input start, output reg out);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) out <= 1'b0; else out <= start;   // latency 1
endmodule
"""
_RTL_SR2 = """\
module sr2 (input clk, input rst_n, input start, output reg out);
  reg s1;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin s1 <= 1'b0; out <= 1'b0; end
    else        begin s1 <= start; out <= s1; end  // latency 2
endmodule
"""
_RTL_SR3 = """\
module sr3 (input clk, input rst_n, input start, output reg out);
  reg s1, s2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin s1<=0; s2<=0; out<=0; end
    else        begin s1<=start; s2<=s1; out<=s2; end  // latency 3
endmodule
"""
_RTL_COMB0 = """\
module comb0 (input clk, input rst_n, input start, output out);
  assign out = start;   // pure combinational: latency 0
endmodule
"""
# `out` is HIGH out of reset (and stays high) — a "valid" already asserted
# before the event must NOT read as a spurious latency 0.
_RTL_HIGHRESET = """\
module highreset (input clk, input rst_n, input start, output reg out);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) out <= 1'b1; else out <= 1'b1;
endmodule
"""


def _write_rtl_fixture(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def _run_cli(args, env=None):
    r = subprocess.run([sys.executable, str(_PROG), *args],
                       capture_output=True, text=True, timeout=60, env=env)
    return r.returncode, r.stdout, r.stderr


# ── POSITIVE / 驗收 VERBATIM (iverilog-gated) ────────────────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_acceptance_offbyone_MISMATCH_rc1(tmp_path):
    """驗收 VERBATIM — off-by-one RTL → LATENCY-MISMATCH measured=WIDTH+1,
    spec WIDTH+2, rc 1."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_OFFBYONE)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "WIDTH+2"])
    assert rc == 1, (out, err)
    assert "LATENCY-MISMATCH: measured=9 but spec WIDTH+2=10" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_acceptance_corrected_ok_rc0(tmp_path):
    """驗收 VERBATIM — corrected RTL → latency-conformance ok measured=WIDTH+2,
    rc 0."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "WIDTH+2"])
    assert rc == 0, (out, err)
    assert "latency-conformance ok: measured=10 == spec WIDTH+2" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_acceptance_corrected_scales_with_param_override(tmp_path):
    """The corrected design scales: --param WIDTH=4 → WIDTH+2 == 6, measured
    matches, rc 0."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "WIDTH+2", "--param", "WIDTH=4"])
    assert rc == 0, (out, err)
    assert "measured=6 == spec WIDTH+2" in out, out


# ── §4.05 NO-LEAK (the load-bearing proofs) ──────────────────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_noleak_correct_passes_offbyone_fails(tmp_path):
    """A correct-latency design PASSES (rc 0) and the off-by-one FAILS (rc 1) —
    the gate does NOT false-BLOCK a correct design and DOES block a wrong one."""
    good = _write_rtl_fixture(tmp_path, "good.sv", _RTL_CORRECT)
    bad = _write_rtl_fixture(tmp_path, "bad.sv", _RTL_OFFBYONE)
    base = ["--top", "divider", "--event", "start", "--output", "valid",
            "--expect", "WIDTH+2"]
    rc_good, out_good, _ = _run_cli(["--rtl", str(good), *base])
    rc_bad, out_bad, _ = _run_cli(["--rtl", str(bad), *base])
    assert rc_good == 0 and "ok" in out_good, out_good
    assert rc_bad == 1 and "LATENCY-MISMATCH" in out_bad, out_bad


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_noleak_timeout_reports_timeout_not_bogus_measurement(tmp_path):
    """A design whose output never asserts reports TIMEOUT (rc 1) — never a
    fabricated measurement that would silently pass."""
    rtl = _write_rtl_fixture(tmp_path, "never.sv", _RTL_NEVER)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "WIDTH+2"])
    assert rc == 1, (out, err)
    assert "LATENCY-TIMEOUT" in out and "never asserted" in out, out
    assert "MISMATCH" not in out and "ok" not in out, out


def test_noleak_iverilog_absent_is_SKIP_not_fake_pass(monkeypatch, tmp_path):
    """iverilog ABSENT → SKIP (rc 0), NEVER a fabricated measurement or PASS.

    Driven through the library entry point with shutil.which monkeypatched to
    None (so the test is portable on a host that DOES have iverilog)."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    monkeypatch.setattr(lcc.shutil, "which", lambda _x: None)
    rc, report = lcc.run_latency_conformance(
        rtl_path=rtl, top="divider", event="start", output="valid",
        expect="WIDTH+2", params_override={}, reset_override=None,
        reset_active_low_flag=None, input_const=-1, max_cycles_override=None)
    assert rc == 0
    assert report["verdict"] == "SKIP"
    assert report["tool_available"] is False
    # NEVER a fabricated measurement or PASS verdict
    assert report.get("measured_latency") is None
    assert report["verdict"] != "PASS"


# ── iverilog-INDEPENDENT: --expect resolution ────────────────────────────────
def test_expect_resolution_default_param(tmp_path):
    """--expect WIDTH+2 resolves against the module's own default WIDTH=8 → 10."""
    params = lcc.resolve_params(_RTL_CORRECT, "divider", {})
    assert params == {"WIDTH": 8}
    assert lcc.safe_eval_arith("WIDTH+2", params) == 10


def test_expect_resolution_param_override(tmp_path):
    """--param WIDTH=16 overrides the module default; WIDTH+2 → 18."""
    params = lcc.resolve_params(_RTL_CORRECT, "divider", {"WIDTH": 16})
    assert params == {"WIDTH": 16}
    assert lcc.safe_eval_arith("WIDTH+2", params) == 18


def test_expect_resolution_literal_and_other_param_names():
    """Bare integer and an `N+1` style expression both resolve."""
    assert lcc.safe_eval_arith("8", {}) == 8
    assert lcc.safe_eval_arith("N+1", {"N": 5}) == 6
    assert lcc.safe_eval_arith("(W*2)//2", {"W": 6}) == 6


def test_expect_param_override_cli_parse():
    """--param NAME=VAL parsing accepts ints (incl 0x..) and rejects junk."""
    assert lcc._parse_param_override(["WIDTH=8", "N=0x10"]) == {"WIDTH": 8,
                                                                "N": 16}
    with pytest.raises(lcc.ExpectError):
        lcc._parse_param_override(["WIDTH"])           # no '='
    with pytest.raises(lcc.ExpectError):
        lcc._parse_param_override(["WIDTH=abc"])       # non-int


# ── iverilog-INDEPENDENT: safe evaluator rejects non-arithmetic ──────────────
@pytest.mark.parametrize("bad", [
    "__import__('os').system('echo x')",
    "os.system",
    "W ** 2",          # power not allowed
    "W & 3",           # bit-op not allowed
    "foo(1)",          # call not allowed
    "1.5",             # float literal not allowed
    "W / 2",           # true-div not allowed (only //)
    "",                # empty
])
def test_safe_evaluator_rejects_non_arithmetic(bad):
    """The evaluator NEVER runs arbitrary code; every non-whitelisted form
    raises ExpectError."""
    with pytest.raises(lcc.ExpectError):
        lcc.safe_eval_arith(bad, {"W": 4})


def test_safe_evaluator_rejects_unknown_param():
    """A name that is neither a literal nor a known parameter raises (no silent
    0)."""
    with pytest.raises(lcc.ExpectError):
        lcc.safe_eval_arith("UNKNOWN+1", {"WIDTH": 8})


# ── iverilog-INDEPENDENT: shared port/param parse + reset polarity ───────────
def test_port_parse_uses_shared_helper():
    """Ports parse via the SHARED parse_module_ports (event/output found)."""
    ports = lcc.parse_module_ports(_RTL_CORRECT, "divider")
    names = [n for _d, _w, n in ports]
    assert "start" in names and "valid" in names and "clk" in names
    clk, resets, ev, out, others = lcc.classify_ports(
        ports, "start", "valid", None)
    assert clk is not None and clk.name == "clk"
    assert [r.name for r in resets] == ["rst_n"]
    assert ev is not None and ev.name == "start"
    assert out is not None and out.name == "valid"
    # the event is NOT in the constant-held others; the data inputs are
    assert "start" not in [o.name for o in others]
    assert set(o.name for o in others) == {"dividend", "divisor"}


def test_reset_polarity_autodetect():
    """Active-low reset spellings detected; active-high left high."""
    assert lcc._reset_is_active_low("rst_n") is True
    assert lcc._reset_is_active_low("resetn") is True
    assert lcc._reset_is_active_low("arst_n") is True
    assert lcc._reset_is_active_low("reset") is False
    assert lcc._reset_is_active_low("rst") is False


def test_missing_event_port_is_setup_error(tmp_path):
    """A missing --event port → clear error + rc 2 (not a crash, not a fake
    measurement)."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "no_such", "--output", "valid",
                             "--expect", "WIDTH+2"])
    assert rc == 2
    assert "not found" in err and "no_such" in err


def test_missing_output_port_is_setup_error(tmp_path):
    """A missing --output port → clear error + rc 2."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "no_such",
                             "--expect", "WIDTH+2"])
    assert rc == 2
    assert "no_such" in err


def test_bad_expect_via_cli_is_setup_error(tmp_path):
    """An --expect that is not safe arithmetic → rc 2 (the gate refuses, never
    evals)."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "__import__('os')"])
    assert rc == 2
    assert "--expect resolution failed" in err


# ── mode hook: only `latency` is wired; an unknown mode is a clean error ──────
def test_unimplemented_mode_is_clean_error(tmp_path):
    """The --mode hook is reserved for the timing-conformance family; only
    `latency` is implemented (argparse `choices` rejects others up front)."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "WIDTH+2", "--mode", "handshake"])
    # argparse choices rejects with rc 2 (usage error)
    assert rc == 2


# ── CANONICAL CONVENTION at the latency-0/1 boundary (the HIGH bug) ───────────
# A negedge-sampled TB mis-reads a REGISTERED latency-1 output as latency 0 and
# TIMEOUTs a combinational latency-0 output. These pin the corrected posedge-
# consistent convention against clean reference DUTs (no FSM): an N-stage shift
# register MUST measure exactly N; `assign out=start` MUST measure 0.
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
@pytest.mark.parametrize("body,top,n", [
    (_RTL_SR1, "sr1", 1),
    (_RTL_SR2, "sr2", 2),
    (_RTL_SR3, "sr3", 3),
])
def test_shift_register_measures_exactly_N(tmp_path, body, top, n):
    """An N-stage shift register `out` = `start` delayed N registered cycles
    measures EXACTLY N (PASS vs --expect N)."""
    rtl = _write_rtl_fixture(tmp_path, f"{top}.sv", body)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", top,
                             "--event", "start", "--output", "out",
                             "--expect", str(n)])
    assert rc == 0, (out, err)
    assert f"latency-conformance ok: measured={n} == spec {n}" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_sr1_latency1_mismatches_expect0(tmp_path):
    """The latency-1 shift reg measured against --expect 0 → MISMATCH measured=1
    (it is NOT mis-read as 0 — the negedge HIGH bug)."""
    rtl = _write_rtl_fixture(tmp_path, "sr1.sv", _RTL_SR1)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "sr1",
                             "--event", "start", "--output", "out",
                             "--expect", "0"])
    assert rc == 1, (out, err)
    assert "LATENCY-MISMATCH: measured=1 but spec 0=0" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_combinational_measures_zero(tmp_path):
    """A purely-combinational `assign out = start` measures 0 (PASS vs
    --expect 0 — it does NOT TIMEOUT, the negedge-drop comb bug)."""
    rtl = _write_rtl_fixture(tmp_path, "comb0.sv", _RTL_COMB0)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "comb0",
                             "--event", "start", "--output", "out",
                             "--expect", "0"])
    assert rc == 0, (out, err)
    assert "latency-conformance ok: measured=0 == spec 0" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_combinational_mismatches_expect1(tmp_path):
    """The latency-0 comb design vs --expect 1 → MISMATCH measured=0 (not a
    spurious 1)."""
    rtl = _write_rtl_fixture(tmp_path, "comb0.sv", _RTL_COMB0)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "comb0",
                             "--event", "start", "--output", "out",
                             "--expect", "1"])
    assert rc == 1, (out, err)
    assert "LATENCY-MISMATCH: measured=0 but spec 1=1" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_output_already_high_before_event_is_LATENCY_ERROR_rc2(tmp_path):
    """`out` HIGH out of reset (before the event) → rc 2 LATENCY-ERROR, NEVER a
    bogus measured=0 (the precondition guard)."""
    rtl = _write_rtl_fixture(tmp_path, "highreset.sv", _RTL_HIGHRESET)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "highreset",
                             "--event", "start", "--output", "out",
                             "--expect", "1"])
    assert rc == 2, (out, err)
    assert "LATENCY-ERROR" in err and "already asserted" in err, err
    # NEVER a fabricated latency-0 PASS/MISMATCH
    assert "measured=0" not in out and "ok" not in out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_width_divider_cases_still_9_and_10(tmp_path):
    """REGRESSION — the FSM divider WIDTH+1/WIDTH+2 cases still measure 9/10
    after the convention fix."""
    bad = _write_rtl_fixture(tmp_path, "bad.sv", _RTL_OFFBYONE)
    good = _write_rtl_fixture(tmp_path, "good.sv", _RTL_CORRECT)
    base = ["--top", "divider", "--event", "start", "--output", "valid",
            "--expect", "WIDTH+2"]
    rc_bad, out_bad, _ = _run_cli(["--rtl", str(bad), *base])
    rc_good, out_good, _ = _run_cli(["--rtl", str(good), *base])
    assert rc_bad == 1 and "measured=9 but spec WIDTH+2=10" in out_bad, out_bad
    assert rc_good == 0 and "measured=10 == spec WIDTH+2" in out_good, out_good


# ── MED DoS: a huge resolved --expect is rejected FAST (no sim stall) ─────────
def test_huge_expect_rejected_before_any_sim_rc2(tmp_path):
    """A huge resolved --expect (8*1000000) → rc 2, refused BEFORE simulating.

    This used to close with `assert elapsed < 10.0` — the clock standing in for
    the thing actually worth proving, that the ceiling is checked before the
    ~120 s sim rather than after it. A stopwatch cannot tell those apart: on a
    loaded host a correct early refusal blows the 10 s budget and the test
    reports a DoS-guard defect that is not there, while on a fast host a sim
    that really ran could come in under it.

    So ask the question directly. The ceiling guard sits ahead of the
    iverilog/vvp availability gate, so with NEITHER tool on PATH a guard that
    precedes the sim still refuses with rc 2, and one that had moved after it
    could only reach the tools-absent SKIP (rc 0) — it has nothing to simulate
    with. The verdict is now a statement about ORDER, which is what was meant,
    and it holds at any speed on any host."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    argv = ["--rtl", str(rtl), "--top", "divider", "--event", "start",
            "--output", "valid", "--expect", "8*1000000"]
    rc, out, err = _run_cli(argv)
    assert rc == 2, (out, err)
    assert "exceeds the sane latency ceiling" in err, err

    # The same refusal with no simulator reachable at all.
    bare = dict(os.environ, PATH=str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir(exist_ok=True)
    rc2, out2, err2 = _run_cli(argv, env=bare)
    assert rc2 == 2, (
        "with no iverilog/vvp on PATH the ceiling must STILL refuse: a guard "
        f"that ran after the sim could only reach the SKIP path. rc={rc2}\n"
        f"{out2}\n{err2}")
    assert "exceeds the sane latency ceiling" in err2, err2


def test_huge_expect_via_product_rejected(tmp_path):
    """`999999999*999999999` is rejected by the ceiling (not evaluated into a
    sim)."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "999999999*999999999"])
    assert rc == 2
    assert "exceeds the sane latency ceiling" in err, err


def test_max_cycles_clamped_to_ceiling(monkeypatch, tmp_path):
    """An explicit --max-cycles above the hard ceiling is CLAMPED (the DoS
    window guard). Driven through the real code path with shutil.which→None so
    the clamp is computed and recorded, then the run SKIPs before any sim — no
    iverilog needed, and the clamp can never emit a giant loop bound."""
    rtl = _write_rtl_fixture(tmp_path, "divider.sv", _RTL_CORRECT)
    monkeypatch.setattr(lcc.shutil, "which", lambda _x: None)
    rc, report = lcc.run_latency_conformance(
        rtl_path=rtl, top="divider", event="start", output="valid",
        expect="2", params_override={}, reset_override=None,
        reset_active_low_flag=None, input_const=-1,
        max_cycles_override=10 ** 9)
    assert report["max_cycles"] == lcc._MAX_CYCLES_CEILING
    assert report["max_cycles"] <= 200000


# ── chip-AGNOSTIC source guard covers this program ───────────────────────────
def test_source_is_chip_agnostic():
    """The deny-list guard passes over the whole plugin source (incl this new
    program)."""
    guard = _PROGRAMS / "source_chip_agnostic_check.py"
    plugin_root = _PROGRAMS.parent
    r = subprocess.run([sys.executable, str(guard), str(plugin_root)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
