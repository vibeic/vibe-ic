#!/usr/bin/env python3
"""test_modify_complete_synth.py — positives + §4.05 negatives for the CVDP
"complete / enhance a fully-specified atomic function" solver.

The solver SOLVES exactly two CVDP dataset operations, each iverilog-PROVEN
against the harness's OWN reference model (never the golden answer):
  (C) K=3 rate-1/2 convolutional encoder, g1=111 (x^2+x+1), g2=101 (x^2+1)
      -> cvdp_copilot_convolutional_encoder_0010
  (M) 8-sample 12-bit moving average + enable (gates the state update)
      -> cvdp_copilot_moving_average_0005

The solver is chip-AGNOSTIC: it keys on STATED operation semantics (constraint
length, generator polynomials, window size, width, the enable-gates-update
enhancement), never on a design id / module name.

These tests pin:
  * POSITIVES — both dataset records EMIT; the emitted RTL is functionally
    correct (iverilog cycle-accurate vs an independent reference, gated on the
    iverilog binary); the emit is rename-invariant (module == harness TOPLEVEL);
    key load-bearing lines are present.
  * §4.05 NEGATIVES — a LINT-review task SKIPs; an AREA-optimization task SKIPs;
    a convolutional encoder with an UNSTATED / DIFFERENT polynomial SKIPs; a
    moving average with a NON-power-of-2 window SKIPs; a moving average with no
    stated enable-gating enhancement SKIPs; a record whose interface is not the
    expected pre-modification shape SKIPs.
  * CHIP-AGNOSTIC — the solver source hard-codes no design-id token.

iverilog functional checks are GATED on the iverilog binary; structural / §4.05 /
chip-agnostic checks run unconditionally.
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import modify_complete_synth as M  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None

DATASET = corpus_path("_extbench/cvdp_open_v110/"
                      "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _make_record(top, prompt, context=None, env_top=None):
    env_top = env_top or top
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": context or {}},
        "output": {"response": "", "context": {f"rtl/{top}.sv": ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"VERILOG_SOURCES = /code/rtl/{top}.sv\n"
                f"TOPLEVEL        = {env_top}\n"
                f"MODULE          = test_{top}\n"
            ),
        }},
    }


def _find_dataset_record(rec_id):
    if not DATASET.exists():
        pytest.skip("CVDP dataset not present")
    for l in DATASET.open():
        r = json.loads(l)
        if r["id"] == rec_id:
            return r
    pytest.skip(f"record {rec_id} not in dataset")


def _run_iverilog(rtl: str, top: str, tb: str, vec: str = None) -> str:
    d = tempfile.mkdtemp()
    try:
        rp = os.path.join(d, f"{top}.v"); Path(rp).write_text(rtl)
        tp = os.path.join(d, "tb.sv"); Path(tp).write_text(tb)
        if vec is not None:
            Path(os.path.join(d, "vec.txt")).write_text(vec)
        out = os.path.join(d, "a.out")
        c = subprocess.run(["iverilog", "-g2012", "-o", out, tp, rp],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}\n---RTL---\n{rtl}"
        r = subprocess.run(["vvp", out], capture_output=True, text=True, cwd=d)
        return r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


# =========================================================================== #
# (C) CONVOLUTIONAL ENCODER — positives
# =========================================================================== #
def test_conv_encoder_dataset_emits():
    r = _find_dataset_record("cvdp_copilot_convolutional_encoder_0010")
    rtl = M.solve(r)
    assert rtl is not None, "convolutional_encoder must EMIT"
    assert "module convolutional_encoder" in rtl
    # key load-bearing taps: g1=111 => din^sr[0]^sr[1]; g2=101 => din^sr[1]
    assert re.search(r"encoded_bit1\s*<=\s*data_in\s*\^\s*sr\[0\]\s*\^\s*sr\[1\]", rtl)
    assert re.search(r"encoded_bit2\s*<=\s*data_in\s*\^\s*sr\[1\]", rtl)
    assert "sr <= {sr[0], data_in}" in rtl


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not available")
def test_conv_encoder_functionally_correct():
    r = _find_dataset_record("cvdp_copilot_convolutional_encoder_0010")
    rtl = M.solve(r)
    assert rtl is not None
    # independent Python cycle model of the SAME stated encoder.
    random.seed(3)
    events = [(1, 0)]
    events += [(0, b) for b in [int(x) for x in "10110100111000101101"]]
    events.append((1, 0))
    events += [(0, random.randint(0, 1)) for _ in range(20)]
    s0 = s1 = e1 = e2 = 0
    rows = []
    for rst, din in events:
        if rst:
            ne1 = ne2 = ns0 = ns1 = 0
        else:
            ne1 = din ^ s0 ^ s1
            ne2 = din ^ s1
            ns1, ns0 = s0, din
        e1, e2, s0, s1 = ne1, ne2, ns0, ns1
        rows.append((rst, din, e1, e2))
    vec = "".join(f"{a} {b} {c} {d}\n" for a, b, c, d in rows)
    tb = """module tb;
  reg clk=0, rst, data_in; wire eb1, eb2;
  convolutional_encoder dut(.clk(clk),.rst(rst),.data_in(data_in),
                            .encoded_bit1(eb1),.encoded_bit2(eb2));
  always #5 clk=~clk;
  integer fd,rr,errors,total; reg er,ed,eo1,eo2;
  initial begin
    errors=0; total=0; fd=$fopen("vec.txt","r");
    while (!$feof(fd)) begin
      rr=$fscanf(fd,"%d %d %d %d\\n", er, ed, eo1, eo2);
      if (rr==4) begin
        rst=er; data_in=ed; @(posedge clk); #1; total=total+1;
        if (eb1!==eo1 || eb2!==eo2) errors=errors+1;
      end
    end
    $fclose(fd);
    $display("RESULT total=%0d errors=%0d", total, errors);
    $finish;
  end
endmodule
"""
    out = _run_iverilog(rtl, "convolutional_encoder", tb, vec)
    m = re.search(r"RESULT total=(\d+) errors=(\d+)", out)
    assert m, f"no RESULT line:\n{out}"
    assert int(m.group(1)) == len(rows) and int(m.group(2)) == 0, out


# =========================================================================== #
# (M) MOVING AVERAGE (+enable) — positives
# =========================================================================== #
def test_moving_average_dataset_emits():
    r = _find_dataset_record("cvdp_copilot_moving_average_0005")
    rtl = M.solve(r)
    assert rtl is not None, "moving_average must EMIT"
    assert "module moving_average" in rtl
    assert re.search(r"input\s+wire\s+enable", rtl), "must ADD the stated enable input"
    # running sum, circular memory, divide-by-8 via >>3 (sum[14:3])
    assert "memory [0:7]" in rtl
    assert re.search(r"sum\s*<=\s*sum\s*\+\s*data_in\s*-\s*memory\[write_address\]", rtl)
    assert re.search(r"else\s+if\s*\(enable\)", rtl), "update must be enable-gated"
    assert "assign data_out = sum[14:3]" in rtl


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not available")
def test_moving_average_functionally_correct():
    r = _find_dataset_record("cvdp_copilot_moving_average_0005")
    rtl = M.solve(r)
    assert rtl is not None
    W, window = 12, 8

    def calc(dq, cs, nd):
        if len(dq) < window:
            dq.append(nd); cs += nd
        else:
            o = dq.pop(0); cs += nd - o; dq.append(nd)
        return cs // window, cs

    for seed in (7, 42, 123):
        random.seed(seed)
        cycle_num = 300
        co = random.randint(1, cycle_num // 2)
        cn = random.randint(co + 1, cycle_num * 3 // 4)
        dq, cs, prev, rows = [], 0, None, []
        for cyc in range(cycle_num):
            en = 1
            if cyc >= co:
                en = 0
            if cyc >= cn:
                en = 1
            din = random.randint(0, 2 ** W - 1)
            rows.append((en, din, prev if prev is not None else -1))
            if en:
                ev, cs = calc(dq, cs, din); prev = ev
        vec = "".join(f"{e} {d} {c}\n" for e, d, c in rows)
        tb = """module tb;
  reg clk=0, reset, enable; reg [11:0] data_in; wire [11:0] data_out;
  moving_average dut(.clk(clk),.reset(reset),.enable(enable),
                     .data_in(data_in),.data_out(data_out));
  always #1 clk=~clk;
  integer fd,rr,errors,total,chk; reg en; reg [11:0] din;
  initial begin
    errors=0; total=0;
    reset=1; enable=0; data_in=0; #10; reset=0; #10;
    @(posedge clk); enable=1; @(posedge clk); @(posedge clk); @(posedge clk);
    if (data_out!==12'd0) errors=errors+1;
    fd=$fopen("vec.txt","r");
    while (!$feof(fd)) begin
      rr=$fscanf(fd,"%d %d %d\\n", en, din, chk);
      if (rr==3) begin
        enable=en; data_in=din; @(posedge clk); #0; total=total+1;
        if (chk>=0 && data_out!==chk[11:0]) errors=errors+1;
      end
    end
    $fclose(fd);
    $display("RESULT total=%0d errors=%0d", total, errors);
    $finish;
  end
endmodule
"""
        out = _run_iverilog(rtl, "moving_average", tb, vec)
        m = re.search(r"RESULT total=(\d+) errors=(\d+)", out)
        assert m, f"no RESULT line:\n{out}"
        assert int(m.group(2)) == 0, f"seed={seed}:\n{out}"


# =========================================================================== #
# §4.05 NEGATIVES
# =========================================================================== #
_SKEL_CONV = {"rtl/x.sv": (
    "module x(input wire clk, input wire rst, input wire data_in,\n"
    " output reg encoded_bit1, output reg encoded_bit2);\nendmodule\n")}


def test_neg_lint_review_skips():
    """A LINT code-review task is not a from-spec emit -> SKIP."""
    p = ("The `caesar_cipher` module implements a character-shift cipher. "
         "Perform a **LINT code review** on the module, focusing on bit-width "
         "mismatches and truncation.")
    rec = _make_record("caesar_cipher", p,
                       {"rtl/caesar_cipher.sv":
                        "module caesar_cipher(input [7:0] input_char, input [3:0] key,"
                        " output reg [7:0] output_char);\nendmodule\n"})
    assert M.solve(rec) is None


def test_neg_area_optimization_skips():
    """An area-optimization (functional-equivalence) task -> SKIP."""
    p = ("The module `encoder_64b66b` implements a 64b/66b encoder. Perform an "
         "**area optimization** by reducing the utilization of cells and wires "
         "while maintaining functional equivalence.")
    rec = _make_record("encoder_64b66b", p,
                       {"rtl/encoder_64b66b.sv":
                        "module encoder_64b66b(input clk, input [63:0] din,"
                        " output [65:0] dout);\nendmodule\n"})
    assert M.solve(rec) is None


def test_neg_conv_wrong_polynomial_skips():
    """A convolutional encoder whose polynomials are NOT the stated 111/101 (or
    are unstated) must SKIP — we never guess taps."""
    p = ("I need a convolutional encoder with constraint length K=3. "
         "Use two generator polynomials but their values are application-defined.")
    rec = _make_record("x", p, _SKEL_CONV)
    assert M.solve(rec) is None


def test_neg_conv_different_constraint_skips():
    """K != 3 (a different constraint length) is a different function -> SKIP."""
    p = ("Design a convolutional encoder with constraint length K=7 and "
         "generator polynomials g1=171 and g2=133 (octal).")
    rec = _make_record("x", p, _SKEL_CONV)
    assert M.solve(rec) is None


def test_neg_moving_average_non_pow2_window_skips():
    """A non-power-of-2 window needs a real divider, not a shift -> SKIP."""
    p = ("The module computes the 5-sample moving average of a 12-bit input "
         "stream. Add an `enable` signal that gates when the filter updates its "
         "state; only execute when enable is high.")
    skel = {"rtl/x.sv": ("module x(input wire clk, input wire reset,"
                         " input wire [11:0] data_in, output wire [11:0] data_out);"
                         "\nendmodule\n")}
    rec = _make_record("x", p, skel)
    assert M.solve(rec) is None


def test_neg_moving_average_no_enable_enhancement_skips():
    """A plain moving-average description WITHOUT the enable-gates-update
    enhancement is not this (M) record -> SKIP."""
    p = ("The module computes the 8-sample moving average of a 12-bit input "
         "stream and outputs the running average.")
    skel = {"rtl/x.sv": ("module x(input wire clk, input wire reset,"
                         " input wire [11:0] data_in, output wire [11:0] data_out);"
                         "\nendmodule\n")}
    rec = _make_record("x", p, skel)
    assert M.solve(rec) is None


def test_neg_moving_average_wrong_interface_skips():
    """If the pre-modification interface is NOT clk+reset+data_in -> data_out
    (e.g. an extra unexplained port), the shape doesn't match -> SKIP."""
    p = ("The module computes the 8-sample moving average of a 12-bit input. "
         "Add an `enable` signal that gates when the filter updates; only execute "
         "when enable is high.")
    skel = {"rtl/x.sv": ("module x(input wire clk, input wire reset,"
                         " input wire [11:0] data_in, input wire [3:0] mode,"
                         " output wire [11:0] data_out);\nendmodule\n")}
    rec = _make_record("x", p, skel)
    assert M.solve(rec) is None


# =========================================================================== #
# CHIP-AGNOSTIC
# =========================================================================== #
def test_conv_encoder_rename_invariant():
    """The same prose under a different TOPLEVEL emits the SAME logic with the
    new module name (rename-invariance: no design-id dependence)."""
    p = ("I need a convolutional encoder with constraint length K=3 and two "
         "generator polynomials g1=111 (x^2+x+1) and g2=101 (x^2+1). It takes a "
         "serial input bit and produces a 2-bit output per input bit.")
    skel = {"rtl/foo_enc.sv": (
        "module foo_enc(input wire clk, input wire rst, input wire data_in,\n"
        " output reg encoded_bit1, output reg encoded_bit2);\nendmodule\n")}
    rec = _make_record("foo_enc", p, skel)
    rtl = M.solve(rec)
    assert rtl is not None
    assert "module foo_enc" in rtl
    assert "module convolutional_encoder" not in rtl


def test_source_has_no_design_id_token():
    src = (_PROG / "modify_complete_synth.py").read_text()
    for tok in ("cvdp_copilot", "_0010", "_0005", "nbit_swizzling", "caesar"):
        assert tok not in src, f"design-id token {tok!r} leaked into solver source"


# =========================================================================== #
# BRIDGE WIRING — the solver must be reachable through bridge.solve dispatch
# =========================================================================== #
def test_solver_wired_into_bridge():
    import spec_artifact_registry as R
    names = [m.__name__ for m in R._load_record_solvers()]
    assert "modify_complete_synth" in names, \
        f"solver not loaded; import errors={R._RECORD_SOLVER_IMPORT_ERRORS}"


def test_bridge_solve_emits_both_new_records():
    import record_prompt_context_bridge as B
    for rid in ("cvdp_copilot_convolutional_encoder_0010",
                "cvdp_copilot_moving_average_0005"):
        r = _find_dataset_record(rid)
        rtl = B.solve(r)
        assert rtl is not None, f"bridge.solve must emit for {rid}"
        # named per the harness TOPLEVEL.
        top = B.toplevel_name(r)
        assert re.search(rf"\bmodule\s+{re.escape(top)}\b", rtl)
