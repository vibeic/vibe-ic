#!/usr/bin/env python3
"""ORGANIC #770 round-2 — Part C: latency_conformance_check.py arbiter one-hot.

THE RESIDUAL FP (bus_arbiter_0004)
==================================
The canonical latency TB drives EVERY non-event data input to the same all-active
constant (all-ones by default). For a bus ARBITER that is wrong: the global
all-ones constant pins the COMPETING request `req1=1` AND the SELECT
`dynamic_priority=1`, so a spec-correct dynamic-priority arbiter grants Master1
and the MEASURED grant (`grant0`) is structurally UNREACHABLE → a false
LATENCY-TIMEOUT (rc 1) on correct RTL. Proven a convention FP: `--input-const 0`
(req1=0, dp=0) measures latency 1 → PASS. The latency is genuinely 1 cycle for
both masters; the verdict flips only on the global data constant ignoring
mutual-exclusion semantics.

THE FIX
=======
Detect the arbiter-class structural signature (the measured event is a
request*-named input, the measured output is a grant*-named output — or the
design has grant outputs — AND at least one OTHER competing request input
exists). When (and ONLY when) that all-active stimulus makes the measured grant
unreachable (a TIMEOUT), RETRY with a ONE-HOT request stimulus: drive ONLY the
measured request (the event) active and hold the COMPETING requests INACTIVE, so
the measured grant is reachable and the genuine per-master latency is read.

§4.05 NO-LEAK (load-bearing)
===========================
The relaxation is STRICTLY a TIMEOUT→measurement on the arbiter signature:
  * a genuinely 2-cycle arbiter grant vs spec=1 → the retry MEASURES 2 → still
    BLOCKs (rc 1). The retry never masks a real timing miss.
  * a NON-arbiter measured-latency mismatch is unchanged (the retry is
    structurally dead: empty competing-request set).
  * the one-hot retry fires ONLY on a TIMEOUT — a measured-but-wrong latency
    (MISMATCH) is never retried.
  * an arbiter whose measured grant is GENUINELY unreachable (a real bug, grant
    hardwired off) → the one-hot retry STILL times out → the original TIMEOUT
    stands (rc 1).

chip-AGNOSTIC: structural multi-request/multi-grant signature, no chip/SKU
literal (enforced by source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
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


# ── faithful bus_arbiter_0004 fixture ────────────────────────────────────────
# Dynamic-priority arbiter. 2 masters: req0/req1 request, grant0/grant1 grant.
# `dynamic_priority` selects the winner on contention. Each grant is registered
# ONE cycle after its request is the chosen winner — genuine latency 1 for BOTH
# masters IN ISOLATION. Under the all-ones constant (req0=1, req1=1, dp=1)
# Master1 preempts so grant0 is UNREACHABLE → a false TIMEOUT.
_RTL_ARBITER = """\
module bus_arbiter (
    input  clk,
    input  rst_n,
    input  req0,
    input  req1,
    input  dynamic_priority,
    output reg grant0,
    output reg grant1
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            grant0 <= 1'b0;
            grant1 <= 1'b0;
        end else begin
            if (dynamic_priority) begin
                grant1 <= req1;
                grant0 <= req0 & ~req1;
            end else begin
                grant0 <= req0;
                grant1 <= req1 & ~req0;
            end
        end
    end
endmodule
"""

# A GENUINELY 2-cycle arbiter (an extra pipeline register): even under the
# one-hot retry the measured latency is 2. vs spec=1 it must still MISMATCH.
_RTL_ARBITER_2CYC = """\
module bus_arbiter2 (
    input  clk,
    input  rst_n,
    input  req0,
    input  req1,
    input  dynamic_priority,
    output reg grant0,
    output reg grant1
);
    reg g0_d, g1_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            g0_d <= 1'b0; g1_d <= 1'b0; grant0 <= 1'b0; grant1 <= 1'b0;
        end else begin
            if (dynamic_priority) begin
                g1_d <= req1;            g0_d <= req0 & ~req1;
            end else begin
                g0_d <= req0;            g1_d <= req1 & ~req0;
            end
            grant0 <= g0_d;
            grant1 <= g1_d;
        end
    end
endmodule
"""

# An arbiter where the MEASURED grant is GENUINELY unreachable (a real bug:
# grant0 is hardwired LOW). Even the one-hot retry cannot reach it → still BLOCK.
_RTL_ARBITER_DEAD = """\
module bus_arbiter_dead (
    input  clk,
    input  rst_n,
    input  req0,
    input  req1,
    input  dynamic_priority,
    output reg grant0,
    output reg grant1
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin grant0 <= 1'b0; grant1 <= 1'b0; end
        else begin
            grant0 <= 1'b0;   // BUG: never granted to the measured master
            grant1 <= dynamic_priority ? req1 : (req1 & ~req0);
        end
    end
endmodule
"""

# A NON-arbiter parameterised divider with an OFF-BY-ONE latency (the canonical
# #705 fixture shape). Its measured latency is WIDTH+1 vs spec WIDTH+2 → MISMATCH
# must be UNCHANGED (the arbiter retry must be structurally dead for it).
_RTL_DIV_OFFBYONE = """\
module divider #(parameter WIDTH = 8) (
    input clk, input rst_n, input start,
    input [WIDTH-1:0] dividend, input [WIDTH-1:0] divisor,
    output reg [WIDTH-1:0] quotient, output reg valid);
    localparam IDLE=2'd0, BUSY=2'd1, DONE=2'd2;
    reg [1:0] state; reg [$clog2(WIDTH+2)-1:0] cnt;
    always @(posedge clk or negedge rst_n)
      if(!rst_n) begin state<=IDLE;cnt<=0;valid<=0;quotient<=0; end
      else begin valid<=0; case(state)
        IDLE: if(start) begin state<=BUSY;cnt<=0; end
        BUSY: if(cnt==WIDTH-2) state<=DONE; else cnt<=cnt+1'b1;
        DONE: begin valid<=1; quotient<=dividend; state<=IDLE; end
      endcase end
endmodule
"""


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def _run_cli(args):
    r = subprocess.run([sys.executable, str(_PROG), *args],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


# ── iverilog-INDEPENDENT: the name-anchored signature ────────────────────────
def test_request_name_anchored_no_false_fire():
    """`_looks_like_request` matches genuine req*/request* tokens but NOT an
    ordinary data input that merely embeds the letters (frequency, prequel)."""
    assert lcc._looks_like_request("req")
    assert lcc._looks_like_request("req0")
    assert lcc._looks_like_request("request_i")
    assert lcc._looks_like_request("m0_req")
    assert lcc._looks_like_request("bus_request_2")
    # narrow: no mid-word fire
    assert not lcc._looks_like_request("frequency")
    assert not lcc._looks_like_request("prequel")
    assert not lcc._looks_like_request("data")
    assert not lcc._looks_like_request("dividend")


def test_grant_name_anchored_no_false_fire():
    """`_looks_like_grant` matches grant*/gnt* tokens but NOT an embedding."""
    assert lcc._looks_like_grant("grant")
    assert lcc._looks_like_grant("grant1")
    assert lcc._looks_like_grant("m1_gnt")
    assert lcc._looks_like_grant("gnt_o")
    assert not lcc._looks_like_grant("fragment")
    assert not lcc._looks_like_grant("integrand")
    assert not lcc._looks_like_grant("valid")


# ── FP-NOW-PASSES (the bus_arbiter_0004 case) ────────────────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_fp_arbiter_grant0_now_passes_under_default_constant(tmp_path):
    """bus_arbiter_0004 — measuring grant0 under the DEFAULT all-ones constant
    formerly TIMED OUT (req1=1, dp=1 pin Master1 → grant0 unreachable). The
    arbiter one-hot retry holds req1 inactive → grant0 reachable → measured 1 →
    rc 0. (The historical control was `--input-const 0`; the fix makes the
    DEFAULT stimulus correct.)"""
    rtl = _write(tmp_path, "bus_arbiter.sv", _RTL_ARBITER)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter",
                             "--event", "req0", "--output", "grant0",
                             "--expect", "1"])
    assert rc == 0, (out, err)
    assert "latency-conformance ok: measured=1" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_fp_arbiter_other_master_also_passes(tmp_path):
    """Symmetric: measuring grant1 via the req1 event (Master1) also passes at
    latency 1 under the default constant (one-hot holds req0 inactive)."""
    rtl = _write(tmp_path, "bus_arbiter.sv", _RTL_ARBITER)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter",
                             "--event", "req1", "--output", "grant1",
                             "--expect", "1"])
    assert rc == 0, (out, err)
    assert "measured=1" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_fp_arbiter_retry_diagnostics_in_report(tmp_path):
    """The JSON report records the arbiter classification + the one-hot retry it
    performed (auditability — the relaxation is never silent)."""
    rtl = _write(tmp_path, "bus_arbiter.sv", _RTL_ARBITER)
    out_json = tmp_path / "rep.json"
    rc, _o, _e = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter",
                           "--event", "req0", "--output", "grant0",
                           "--expect", "1", "--json", str(out_json)])
    assert rc == 0
    rep = json.loads(out_json.read_text())
    assert rep["arbiter_class"] is True
    assert rep["competing_requests_held_inactive_on_retry"] == ["req1"]
    retry = rep["arbiter_onehot_retry"]
    assert retry["retry_status"] == "ok"
    assert retry["retry_measured_latency"] == 1
    assert rep.get("measured_under_one_hot_arbitration") is True
    assert rep["verdict"] == "PASS"


# ── §4.05 NO-LEAK (the load-bearing half) ────────────────────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_noleak_genuine_2cycle_arbiter_vs_spec1_still_blocks(tmp_path):
    """NO-LEAK: a GENUINELY 2-cycle arbiter grant vs spec=1 → the one-hot retry
    MEASURES 2 (it does not mask the real latency) → LATENCY-MISMATCH rc 1."""
    rtl = _write(tmp_path, "bus_arbiter2.sv", _RTL_ARBITER_2CYC)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter2",
                             "--event", "req0", "--output", "grant0",
                             "--expect", "1"])
    assert rc == 1, (out, err)
    assert "LATENCY-MISMATCH: measured=2 but spec 1=1" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_noleak_2cycle_arbiter_correct_spec_passes(tmp_path):
    """Confirms the 2-cycle retry MEASURES the real latency: the same arbiter
    with the CORRECT spec=2 passes (rc 0) — proving #..._still_blocks above is a
    genuine measurement, not a blanket retry-failure."""
    rtl = _write(tmp_path, "bus_arbiter2.sv", _RTL_ARBITER_2CYC)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter2",
                             "--event", "req0", "--output", "grant0",
                             "--expect", "2"])
    assert rc == 0, (out, err)
    assert "measured=2 == spec 2" in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_noleak_genuinely_unreachable_grant_still_blocks(tmp_path):
    """NO-LEAK: an arbiter where the measured grant is GENUINELY unreachable (a
    real bug — grant0 hardwired LOW) → even the one-hot retry STILL times out →
    the original LATENCY-TIMEOUT stands (rc 1). The retry can only relax a
    structural-contention timeout to a measurement, never invent a pass."""
    rtl = _write(tmp_path, "bus_arbiter_dead.sv", _RTL_ARBITER_DEAD)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter_dead",
                             "--event", "req0", "--output", "grant0",
                             "--expect", "1"])
    assert rc == 1, (out, err)
    assert "LATENCY-TIMEOUT" in out and "never asserted" in out, out
    assert "ok" not in out, out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_noleak_nonarbiter_mismatch_unchanged(tmp_path):
    """NO-LEAK: a NON-arbiter off-by-one divider still MISMATCHes (rc 1) — the
    arbiter retry is structurally dead for it (no request/grant signature → empty
    competing-request set). Behaviour byte-for-byte unchanged from #705."""
    rtl = _write(tmp_path, "divider.sv", _RTL_DIV_OFFBYONE)
    out_json = tmp_path / "rep.json"
    rc, out, err = _run_cli(["--rtl", str(rtl), "--top", "divider",
                             "--event", "start", "--output", "valid",
                             "--expect", "WIDTH+2", "--json", str(out_json)])
    assert rc == 1, (out, err)
    assert "LATENCY-MISMATCH: measured=9 but spec WIDTH+2=10" in out, out
    rep = json.loads(out_json.read_text())
    assert rep["arbiter_class"] is False
    assert "arbiter_onehot_retry" not in rep


def test_noleak_nonarbiter_classification_is_false_no_sim(tmp_path):
    """iverilog-INDEPENDENT structural proof: the divider is NOT arbiter-class
    and the retry plumbing is never engaged. Driven through the library entry
    with iverilog monkeypatched absent so the classification is asserted on the
    parse alone (the SKIP report still carries the arbiter flag)."""
    rtl = _write(tmp_path, "divider.sv", _RTL_DIV_OFFBYONE)
    # use a tiny local monkeypatch (no pytest fixture import order dependency)
    orig_which = lcc.shutil.which
    try:
        lcc.shutil.which = lambda _x: None
        rc, rep = lcc.run_latency_conformance(
            rtl_path=rtl, top="divider", event="start", output="valid",
            expect="WIDTH+2", params_override={}, reset_override=None,
            reset_active_low_flag=None, input_const=-1,
            max_cycles_override=None)
    finally:
        lcc.shutil.which = orig_which
    assert rc == 0 and rep["verdict"] == "SKIP"
    assert rep["arbiter_class"] is False


# ── #478 END-STATE — direct-write artifact + real subprocess returncode ──────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_478_endstate_fp_passes_via_subprocess(tmp_path):
    """#478 END-STATE: DIRECT-write the arbiter RTL to a tmp_path artifact and
    invoke the REAL program via subprocess; assert the returncode is 0 (the FP no
    longer hard-blocks) and the JSON end-state records the one-hot retry."""
    rtl = tmp_path / "bus_arbiter.sv"
    rtl.write_text(_RTL_ARBITER)           # direct artifact write
    out_json = tmp_path / "endstate.json"
    proc = subprocess.run(
        [sys.executable, str(_PROG), "--rtl", str(rtl), "--top", "bus_arbiter",
         "--event", "req0", "--output", "grant0", "--expect", "1",
         "--json", str(out_json)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    rep = json.loads(out_json.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["measured_latency"] == 1
    assert rep["measured_under_one_hot_arbitration"] is True


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_478_endstate_unreachable_still_blocks_via_subprocess(tmp_path):
    """#478 END-STATE (no-leak companion): DIRECT-write the genuinely-broken
    arbiter and invoke the REAL program via subprocess; assert returncode 1 (the
    one-hot retry does NOT rescue a real bug)."""
    rtl = tmp_path / "bus_arbiter_dead.sv"
    rtl.write_text(_RTL_ARBITER_DEAD)
    proc = subprocess.run(
        [sys.executable, str(_PROG), "--rtl", str(rtl), "--top",
         "bus_arbiter_dead", "--event", "req0", "--output", "grant0",
         "--expect", "1"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "LATENCY-TIMEOUT" in proc.stdout, proc.stdout


# ── Step-2.7 adversarial-review remediation (findings #8, #9) ────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_770r2_review_no_other_grant_keeps_timeout(tmp_path):
    """Finding #9 §4.05: an arbiter that grants NO master under the all-active
    stimulus (a real no-grant bug) must keep its TIMEOUT — the mutex-artifact
    proof fails (no other grant asserts), so the one-hot retry is NOT adopted and
    the real defect is not masked."""
    rtl = _write(tmp_path, "nogrant.sv", _RTL_ARBITER_NOGRANT)
    rc, out, _err = _run_cli(["--rtl", str(rtl), "--top", "bus_arbiter",
                              "--event", "req0", "--output", "grant0",
                              "--expect", "1", "--json", str(tmp_path / "r.json")])
    import json
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rc == 1, out
    assert rep.get("arbiter_mutex_artifact_confirmed") is False, rep


def test_770r2_review_measured_output_must_be_grant_for_arbiter_retry():
    """Finding #8: the arbiter one-hot retry is arbiter-class ONLY when the
    MEASURED output is itself a grant (the `any_grant_output` disjunct was
    dropped) — a non-grant measured output never triggers the request-suppression
    retry. Verified via the grant/request name classifiers."""
    assert lcc._looks_like_grant("grant0")
    assert not lcc._looks_like_grant("status_done")


_RTL_ARBITER_NOGRANT = """\
module bus_arbiter (
    input clk, input rst_n, input req0, input req1, input dynamic_priority,
    output reg grant0, output reg grant1
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin grant0 <= 1'b0; grant1 <= 1'b0; end
        else begin grant0 <= 1'b0; grant1 <= 1'b0; end
    end
endmodule
"""
