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
import inspect
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
from _hostpaths import corpus_path, require_repo  # noqa: E402

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


# =========================================================================== #
# issue #2035 — the SUPPLIED CONTRACT layer (families F1 and F5)
#
# F1  Supplied clocked arithmetic stages and literal tables must NOT be
#     flattened or replaced with conventional meanings.
# F5  Word-boundary transfers must take byte masks, response mode and the
#     prealigned store lane from the input's own statement.
#
# Every record below is NEUTRAL, INPUT-ONLY material authored for these tests:
# a prompt plus a context module HEADER. No dataset record, no design id, no
# benchmark name, no golden/reference body is read (§4.05).
# =========================================================================== #
_BASE_SHA = "764d6b3e5ced4a90adfa1fae8e5e318be000f195"
_REPO_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/modify_complete_synth.py"


def _neutral_record(top, ctx_ports, prompt):
    """Build a neutral record: a prompt plus a context module HEADER only."""
    hdr = "module %s (\n    %s\n);\nendmodule\n" % (top, ",\n    ".join(ctx_ports))
    return {"id": "neutral-fixture",
            "input": {"prompt": prompt, "context": {"rtl/%s.v" % top: hdr}}}


@pytest.fixture()
def solve_as(monkeypatch):
    """Call M.solve() with the harness TOPLEVEL pinned to the fixture's module
    name. Nothing here reads a dataset or a reference implementation."""
    def _run(top, record, notes=None):
        monkeypatch.setattr(M, "_toplevel", lambda r, _t=top: _t)
        return M.solve(record, notes)
    return _run


# --- the F1 fixture: a design that supplies its OWN clocked stages ---------- #
_F1_PORTS = ["input  wire clk", "input  wire reset",
             "input  wire [11:0] data_in", "output wire [11:0] data_out"]

_F1_SUPPLIED = """Complete the 8-sample moving average module.
It is a 12-bit design. Add an `enable` input; the enable gates the state update.

This design supplies its own arithmetic pipeline. Each stage is registered on the
rising edge of clk.

  Stage 1: acc[14:0] = data_in + acc
  Stage 2: data_out = acc >> 3
"""

# The SAME conventional words with NO supplied stages. This is the
# ALTERNATIVE-ARCHITECTURE CONTROL for F1: a different but entirely legitimate
# way to build "an 8-sample 12-bit moving average with an enable", namely the
# circular-buffer-and-running-sum architecture. It must stay GREEN.
_F1_CONVENTIONAL = """Complete the 8-sample moving average module.
It is a 12-bit design. Add an `enable` input; the enable gates the state update.
"""


def test_f2035_f1_supplied_stages_are_not_replaced_by_convention(solve_as):
    """F1, NEW behaviour: the design's own stages govern the emission."""
    rtl = solve_as("staged_avg", _neutral_record("staged_avg", _F1_PORTS, _F1_SUPPLIED))
    assert rtl is not None, "the supplied stages are structurally complete; expected an emit"
    assert "acc <= data_in + acc;" in rtl
    assert "data_out <= acc >> 3;" in rtl
    # and the conventional reading has NOT been imposed on top of them
    assert "write_address" not in rtl
    assert "memory[" not in rtl
    # the design never asked for an enable port; convention must not add one
    assert not re.search(r"\benable\b", rtl)


def test_f2035_f1_base_program_replaced_the_supplied_stages(solve_as, tmp_path):
    """F1, the OLD WRONG behaviour, pinned. On this SAME neutral record the
    pre-fix program discarded the two supplied stages and emitted the textbook
    circular-buffer moving average instead — including an `enable` port the
    design never supplied. This test is what stops the precedence regressing."""
    root = _PROG.parent
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    if not (root / ".git").exists():
        pytest.skip("NOT_MEASURED: no git checkout to read the pre-fix source from")
    try:
        old_src = subprocess.run(["git", "show", "%s:%s" % (_BASE_SHA, _REPO_REL)],
                                 cwd=str(root), capture_output=True, text=True)
    except OSError:
        pytest.skip("NOT_MEASURED: git unavailable")
    if old_src.returncode != 0:
        pytest.skip("NOT_MEASURED: base blob %s not present in this checkout" % _BASE_SHA)
    mod_path = tmp_path / "old_modify_complete_synth.py"
    mod_path.write_text(old_src.stdout)
    sys.path.insert(0, str(tmp_path))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("old_mcs", str(mod_path))
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        old._toplevel = lambda r: "staged_avg"
        old_rtl = old.solve(_neutral_record("staged_avg", _F1_PORTS, _F1_SUPPLIED))
    finally:
        sys.path.remove(str(tmp_path))
    assert old_rtl is not None
    # the defect, stated as an assertion: the supplied stages are ABSENT ...
    assert "acc <= data_in + acc;" not in old_rtl
    assert "data_out <= acc >> 3;" not in old_rtl
    # ... and the conventional meaning was emitted in their place.
    assert "write_address" in old_rtl and "memory[" in old_rtl


def test_f2035_f1_alternative_architecture_control_stays_green(solve_as):
    """F1 ALTERNATIVE-ARCHITECTURE CONTROL. With no supplied stages, the
    conventional circular-buffer architecture is a legitimate answer to the same
    words and must still be emitted, unchanged by the contract layer."""
    ports = _F1_PORTS
    rtl = solve_as("plain_avg", _neutral_record("plain_avg", ports, _F1_CONVENTIONAL))
    assert rtl is not None, "the conventional path must not be disturbed by the contract"
    assert "write_address" in rtl and "memory[" in rtl
    assert "enable" in rtl


def test_f2035_f1_unstated_intermediate_width_is_routed_to_ai_by_name(solve_as):
    """`acc` is not an interface port, so how many bits it holds is a decision
    the input must make. Reusing the data width would silently flatten a
    supplied accumulator, which is family F1 one level down. Refuse and NAME."""
    prompt = _F1_SUPPLIED.replace("acc[14:0] =", "acc =")
    notes = []
    rtl = solve_as("staged_avg",
                   _neutral_record("staged_avg", _F1_PORTS, prompt), notes)
    # A refusal must be a refusal, not a quiet substitution: pin the CONTENT, so
    # an implementation that guessed and emitted the conventional design fails
    # here on what it produced rather than on a bare None sentinel.
    emitted = rtl or ""
    conventional = [tok for tok in ("write_address", "memory[") if tok in emitted]
    assert conventional == [], (conventional, emitted[:400])
    assert rtl is None, emitted[:400]
    named = [n.split(":")[0] for n in notes]
    assert named == ["stage_width"], named


def test_f2035_f1_unstated_stage_clock_is_routed_to_ai_by_name(solve_as):
    """A program that silently picks the conventional meaning when the input is
    silent is the defect one level up. Here the stages are supplied but the
    input never says what clocks them: refuse, and NAME the decision."""
    prompt = _F1_SUPPLIED.replace(
        "Each stage is registered on the\nrising edge of clk.", "")
    notes = []
    rtl = solve_as("staged_avg",
                   _neutral_record("staged_avg", _F1_PORTS, prompt), notes)
    # as above: the refusal must not have fallen through to the conventional
    # solver, and that is pinned on the emitted CONTENT, not on None alone.
    emitted = rtl or ""
    conventional = [tok for tok in ("write_address", "memory[") if tok in emitted]
    assert conventional == [], (conventional, emitted[:400])
    assert rtl is None, emitted[:400]
    named = [n.split(":")[0] for n in notes]
    assert named == ["stage_clock"], named


# --- the F1 literal-table fixture ------------------------------------------ #
_TBL_PORTS = ["input  wire clk", "input  wire rst_n",
              "input  wire [1:0] code", "output wire [7:0] level"]

_TBL_PROMPT = """Complete the level selector.
The module maps `code` to `level` using the table supplied below. This table is
the design's own definition and is not a standard one-hot decode.

| code | level |
|---|---|
| 2'd0 | 8'h3C |
| 2'd1 | 8'h0F |
| 2'd2 | 8'hA5 |
| 2'd3 | 8'h81 |

Each stage is registered on the rising edge of clk.
"""


def test_f2035_f1_supplied_literal_table_overrides_convention(solve_as):
    rtl = solve_as("sel_map", _neutral_record("sel_map", _TBL_PORTS, _TBL_PROMPT))
    assert rtl is not None
    for k, v in ((0, 0x3C), (1, 0x0F), (2, 0xA5), (3, 0x81)):
        assert "2'd%d: level = 8'd%d;" % (k, v) in rtl, rtl
    # a one-hot decode is the conventional reading of these words; the supplied
    # table outranks it, so none of its values may appear.
    assert "8'd1;" not in rtl and "8'd2;" not in rtl and "8'd4;" not in rtl


def test_f2035_f1_incomplete_table_is_routed_to_ai_by_name(solve_as):
    prompt = _TBL_PROMPT.replace("| 2'd3 | 8'h81 |\n", "")
    notes = []
    rtl = solve_as("sel_map", _neutral_record("sel_map", _TBL_PORTS, prompt), notes)
    assert rtl is None
    assert any(n.startswith("literal_table[code->level]:") and "3 of 4" in n
               for n in notes), notes


def test_f2035_f1_table_contract_is_marked_as_overriding(solve_as):
    ins = [("clk", 1), ("rst_n", 1), ("code", 2)]
    outs = [("level", 8)]
    c = M.extract_contract(
        _neutral_record("sel_map", _TBL_PORTS, _TBL_PROMPT), ins, outs)
    assert c.supplies_own_behaviour()
    assert len(c.tables) == 1 and c.tables[0].overrides_conventional is True
    assert c.tables[0].complete and c.unresolved == []


# --- F5: the per-beat transaction model ------------------------------------ #
_F5_PORTS = ["input  wire clk", "input  wire rst_n",
             "input  wire [31:0] wdata", "input  wire [3:0] sel",
             "output wire [31:0] rdata"]

_F5_STATED = """Complete the word-boundary store unit.
The data bus is 32-bit and one beat is transferred per cycle.
`sel` is the byte mask. A mask bit that is set selects that byte.
Unselected bytes are preserved.
Transfers must be word-aligned. The response is forwarded raw.
The store lane is pre-aligned by the initiator.
"""

# F5 ALTERNATIVE-ARCHITECTURE CONTROL: the same transfer built the other
# legitimate way — an active-LOW mask whose unselected bytes are ZEROED, with a
# decoded response and a target-aligned lane. Equally correct; must stay GREEN
# and must emit the architecture the input actually states.
_F5_ALT = """Complete the word-boundary store unit.
The data bus is 32-bit and one beat is transferred per cycle.
`sel` is the byte mask. A mask bit that is 0 selects that byte.
Unselected bytes are zeroed.
Transfers must be word-aligned. The response is decoded.
The store lane is aligned by the target.
"""


def test_f2035_f5_beat_model_is_emitted_from_the_stated_facts(solve_as):
    rtl = solve_as("wb_beat_store",
                   _neutral_record("wb_beat_store", _F5_PORTS, _F5_STATED))
    assert rtl is not None
    for i in range(4):
        hi, lo = 8 * i + 7, 8 * i
        assert ("rdata[%d:%d] <= sel[%d] ? wdata[%d:%d] : rdata[%d:%d];"
                % (hi, lo, i, hi, lo, hi, lo)) in rtl, rtl
    assert "active-high" in rtl and "unselected bytes preserved" in rtl
    assert "raw response" in rtl and "pre-aligned by the initiator" in rtl


def test_f2035_f5_alternative_architecture_control_stays_green(solve_as):
    rtl = solve_as("wb_beat_store",
                   _neutral_record("wb_beat_store", _F5_PORTS, _F5_ALT))
    assert rtl is not None, "an active-low/zeroing mask is legitimate, not a defect"
    for i in range(4):
        hi, lo = 8 * i + 7, 8 * i
        assert ("rdata[%d:%d] <= ~sel[%d] ? wdata[%d:%d] : 8'h00;"
                % (hi, lo, i, hi, lo)) in rtl, rtl
    assert "active-low" in rtl and "unselected bytes zeroed" in rtl
    assert "decoded response" in rtl and "pre-aligned by the target" in rtl


def test_f2035_f5_understated_beat_is_routed_to_ai_by_name(solve_as):
    """The exact case the issue requires: the input names a byte mask but never
    settles its polarity or its write semantics, and mentions a response without
    saying whether it is raw. The program must refuse and NAME all three, not
    quietly supply the conventional answer."""
    prompt = """Complete the word-boundary store unit.
The data bus is 32-bit and one beat is transferred per cycle.
`sel` is the byte mask.
Transfers must be word-aligned. A response is returned.
"""
    notes = []
    rtl = solve_as("wb_beat_store",
                   _neutral_record("wb_beat_store", _F5_PORTS, prompt), notes)
    assert rtl is None
    named = {n.split(":")[0] for n in notes}
    assert {"byte_mask_polarity", "byte_mask_write_semantics",
            "response_mode"} <= named, notes


def _load_base_solver(tmp_path):
    """Load the pre-fix module from the base commit, or skip saying so."""
    root = _PROG.parent
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    if not (root / ".git").exists():
        pytest.skip("NOT_MEASURED: no git checkout to read the pre-fix source from")
    try:
        got = subprocess.run(["git", "show", "%s:%s" % (_BASE_SHA, _REPO_REL)],
                             cwd=str(root), capture_output=True, text=True)
    except OSError:
        pytest.skip("NOT_MEASURED: git unavailable")
    if got.returncode != 0:
        pytest.skip("NOT_MEASURED: base blob %s not present in this checkout" % _BASE_SHA)
    mod_path = tmp_path / "old_modify_complete_synth.py"
    mod_path.write_text(got.stdout)
    import importlib.util
    spec = importlib.util.spec_from_file_location("old_mcs_f5", str(mod_path))
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    return old


def test_f2035_f5_base_program_could_not_tell_unspecified_from_unsupported(
        tmp_path, monkeypatch):
    """F5, the OLD WRONG behaviour, measured rather than asserted.

    The pre-fix program had no per-beat model at all. On these two neutral
    records — one stating every fact the transfer needs, one leaving three of
    them open — it returns the SAME answer, None, and exposes no API by which a
    caller could learn which decisions were unresolved. Silence that cannot
    distinguish "I have all the facts" from "I am missing three of them" is what
    lets the conventional reading be applied downstream unchallenged."""
    old = _load_base_solver(tmp_path)
    old._toplevel = lambda r: "wb_beat_store"
    stated = _neutral_record("wb_beat_store", _F5_PORTS, _F5_STATED)
    understated = _neutral_record("wb_beat_store", _F5_PORTS, """Complete the word-boundary store unit.
The data bus is 32-bit and one beat is transferred per cycle.
`sel` is the byte mask.
Transfers must be word-aligned. A response is returned.
""")
    assert old.solve(stated) is None
    assert old.solve(understated) is None          # indistinguishable
    # and there was no way to ask WHY: no contract, no unresolved, no notes arg
    assert not [n for n in dir(old)
                if "contract" in n.lower() or "unresolved" in n.lower()]
    assert "notes" not in inspect.signature(old.solve).parameters

    # AFTER the fix the two records are no longer indistinguishable: the fully
    # stated one emits, and the under-stated one names what it is missing.
    monkeypatch.setattr(M, "_toplevel", lambda r: "wb_beat_store")
    notes = []
    assert M.solve(stated, notes) is not None
    assert notes == []
    notes = []
    assert M.solve(understated, notes) is None
    assert len(notes) == 3, notes


# --- F5 sequencing: the FSM half of "per-beat transaction model and FSM
# emission". A handshake is what makes a transfer a SEQUENCE; without one there
# is nothing to step through and a state machine would be one the input never
# asked for. ------------------------------------------------------------- #
_SEQ_PORTS = ["input  wire clk", "input  wire rst_n",
              "input  wire [31:0] wdata", "input  wire [3:0] sel",
              "input  wire s_valid", "input  wire s_ready",
              "output wire [31:0] rdata"]

_SEQ = """Complete the word-boundary burst store unit.
The data bus is 32-bit and one beat is transferred per cycle.
`sel` is the byte mask. A mask bit that is set selects that byte.
Unselected bytes are preserved.
Transfers must be word-aligned. The response is forwarded raw.
The store lane is pre-aligned by the initiator.
A beat is accepted when `s_valid` and `s_ready` are both high.
Bursts of 4 beats.
"""


def test_f2035_f5_stated_handshake_emits_a_real_state_machine(solve_as):
    rtl = solve_as("burst_store", _neutral_record("burst_store", _SEQ_PORTS, _SEQ))
    assert rtl is not None
    assert "localparam S_IDLE = 2'd0, S_BEAT = 2'd1, S_RESP = 2'd2;" in rtl
    assert "reg [1:0] state;" in rtl and "reg [1:0] beat_index;" in rtl
    assert "case (state)" in rtl and "endcase" in rtl
    # beats are ACCEPTED on the stated handshake, not taken every cycle
    assert rtl.count("if (s_valid && s_ready) begin") == 2, rtl
    # the 4-beat burst terminates on the stated count
    assert "if (beat_index == 2'd3) begin" in rtl
    # the response phase exists because a response mode was stated
    assert "S_RESP: begin" in rtl and "// raw response, as stated" in rtl


def test_f2035_f5_unsequenced_transfer_gets_no_state_machine(solve_as):
    """ALTERNATIVE-ARCHITECTURE CONTROL for the sequencing work. The same
    byte-mask semantics with NO handshake stated is a legitimate design — one
    beat per cycle — and must NOT acquire a state machine the input never asked
    for. Adding states unconditionally would be the F1 defect in F5's clothing:
    imposing a conventional shape over what the input actually said."""
    rtl = solve_as("wb_beat_store",
                   _neutral_record("wb_beat_store", _F5_PORTS, _F5_STATED))
    assert rtl is not None
    assert "localparam S_IDLE" not in rtl
    assert "case (state)" not in rtl
    assert "beat_index" not in rtl
    assert "unsequenced: one beat per cycle, no handshake stated" in rtl


def test_f2035_f5_partial_handshake_is_routed_to_ai_by_name(solve_as):
    prompt = _SEQ.replace("A beat is accepted when `s_valid` and `s_ready` are "
                          "both high.\n",
                          "A beat is accepted when `s_valid` is high.\n")
    notes = []
    rtl = solve_as("burst_store",
                   _neutral_record("burst_store", _SEQ_PORTS, prompt), notes)
    emitted = rtl or ""
    conventional = [t for t in ("S_BEAT", "beat_index") if t in emitted]
    assert conventional == [], (conventional, emitted[:400])
    assert rtl is None, emitted[:400]
    assert [n.split(":")[0] for n in notes] == ["handshake_incomplete"], notes


def test_f2035_f5_burst_without_a_stated_length_is_routed_to_ai_by_name(solve_as):
    prompt = _SEQ.replace("Bursts of 4 beats.\n", "The transfer is a burst.\n")
    notes = []
    rtl = solve_as("burst_store",
                   _neutral_record("burst_store", _SEQ_PORTS, prompt), notes)
    assert rtl is None, (rtl or "")[:400]
    assert [n.split(":")[0] for n in notes] == ["burst_length"], notes


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not available")
def test_f2035_f5_sequenced_fsm_takes_a_beat_ONLY_when_handshaken(solve_as, tmp_path):
    """The substance of an acceptance-qualified transfer: a beat presented while
    the handshake is not complete must NOT be captured. This is what separates
    the sequenced FSM from the unsequenced form, so it is run, not inspected."""
    rtl = solve_as("burst_store", _neutral_record("burst_store", _SEQ_PORTS, _SEQ))
    assert rtl is not None
    tb = """
`timescale 1ns/1ps
module tb;
  reg clk=0, rst_n=0, s_valid=0, s_ready=0;
  reg [31:0] wdata=0; reg [3:0] sel=4'b1111; wire [31:0] rdata;
  burst_store dut(.clk(clk), .rst_n(rst_n), .wdata(wdata), .sel(sel),
                  .s_valid(s_valid), .s_ready(s_ready), .rdata(rdata));
  initial begin
    @(negedge clk); rst_n=0; @(negedge clk); rst_n=1;
    // present a beat with NO handshake -> must be ignored
    wdata=32'hDEADBEEF; s_valid=0; s_ready=0;
    @(posedge clk); #1; $display("S %0h", rdata);
    // valid alone -> still not accepted
    @(negedge clk); s_valid=1; s_ready=0;
    @(posedge clk); #1; $display("S %0h", rdata);
    // full handshake -> accepted
    @(negedge clk); s_valid=1; s_ready=1;
    @(posedge clk); #1; $display("S %0h", rdata);
    $finish;
  end
  always #5 clk = ~clk;
endmodule
"""
    got = [g.split()[1].lower() for g in _run_iverilog(rtl, "burst_store", tb, tmp_path)]
    assert got[0] == "0", got          # no handshake: nothing captured
    assert got[1] == "0", got          # valid alone: still nothing
    assert got[2] == "deadbeef", got   # valid && ready: the beat lands


def test_f2035_f5_contradictory_beat_width_is_not_a_vote(solve_as):
    prompt = _F5_STATED.replace("one beat is transferred per cycle.",
                                "one beat is transferred per cycle. "
                                "The data word is 64-bit.")
    notes = []
    rtl = solve_as("wb_beat_store",
                   _neutral_record("wb_beat_store", _F5_PORTS, prompt), notes)
    emitted = rtl or ""
    assert rtl is None, emitted[:400]
    named = [n.split(":")[0] for n in notes]
    assert named == ["beat_width"], named
    assert "different beat widths [32, 64]" in notes[0], notes


# --- the EXECUTABLE SEQUENTIAL REFERENCE ------------------------------------ #
def _run_iverilog(rtl, top, tb, tmp_path):
    (tmp_path / "dut.v").write_text(rtl)
    (tmp_path / "tb.v").write_text(tb)
    build = subprocess.run(["iverilog", "-g2005", "-o", str(tmp_path / "a.out"),
                            str(tmp_path / "tb.v"), str(tmp_path / "dut.v")],
                           capture_output=True, text=True, cwd=str(tmp_path))
    assert build.returncode == 0, build.stderr
    run = subprocess.run(["vvp", str(tmp_path / "a.out")],
                         capture_output=True, text=True, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    return [l.strip() for l in run.stdout.splitlines() if l.strip().startswith("S ")]


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not available")
def test_f2035_f1_emitted_rtl_matches_the_executable_reference(solve_as, tmp_path):
    """The issue asks for an EXECUTABLE sequential reference — one that can be
    RUN against a candidate, not only compared as text. Here the contract is run
    in Python and the emitted RTL is run in iverilog, cycle for cycle."""
    rec = _neutral_record("staged_avg", _F1_PORTS, _F1_SUPPLIED)
    rtl = solve_as("staged_avg", rec)
    assert rtl is not None
    ins = [("clk", 1), ("reset", 1), ("data_in", 12)]
    outs = [("data_out", 12)]
    c = M.extract_contract(rec, ins, outs)
    assert c.unresolved == []
    stim = [7, 40, 4095, 1, 0, 900, 123, 4000, 55, 2]
    expected = c.run([{"data_in": v} for v in stim])
    tb = """
`timescale 1ns/1ps
module tb;
  reg clk=0, reset=1; reg [11:0] data_in=0; wire [11:0] data_out;
  integer i;
  reg [11:0] stim [0:%d];
  staged_avg dut(.clk(clk), .reset(reset), .data_in(data_in), .data_out(data_out));
  initial begin
%s
    @(negedge clk); reset=1; @(negedge clk); reset=0;
    for (i=0; i<%d; i=i+1) begin
      data_in = stim[i];
      @(posedge clk); #1;
      $display("S %%0d", data_out);
      @(negedge clk);
    end
    $finish;
  end
  always #5 clk = ~clk;
endmodule
""" % (len(stim) - 1,
       "\n".join("    stim[%d]=%d;" % (i, v) for i, v in enumerate(stim)),
       len(stim))
    got = _run_iverilog(rtl, "staged_avg", tb, tmp_path)
    assert len(got) == len(expected), (got, expected)
    for k, (g, e) in enumerate(zip(got, expected)):
        assert int(g.split()[1]) == e["data_out"] & 0xFFF, \
            "cycle %d: RTL=%s reference=%d" % (k, g, e["data_out"] & 0xFFF)


@pytest.mark.skipif(not HAVE_IVERILOG, reason="iverilog/vvp not available")
def test_f2035_f5_emitted_beat_fsm_honours_the_stated_mask(solve_as, tmp_path):
    """The per-beat model, run. Bytes whose mask bit is set take the new data;
    bytes whose mask bit is clear are PRESERVED, because that is what this input
    states — not because it is the usual answer."""
    rtl = solve_as("wb_beat_store",
                   _neutral_record("wb_beat_store", _F5_PORTS, _F5_STATED))
    assert rtl is not None
    tb = """
`timescale 1ns/1ps
module tb;
  reg clk=0, rst_n=0; reg [31:0] wdata=0; reg [3:0] sel=0; wire [31:0] rdata;
  wb_beat_store dut(.clk(clk), .rst_n(rst_n), .wdata(wdata), .sel(sel), .rdata(rdata));
  initial begin
    @(negedge clk); rst_n=0; @(negedge clk); rst_n=1;
    wdata=32'hAABBCCDD; sel=4'b1111; @(posedge clk); #1; $display("S %0h", rdata);
    @(negedge clk); wdata=32'h11223344; sel=4'b0101; @(posedge clk); #1; $display("S %0h", rdata);
    @(negedge clk); wdata=32'hFFFFFFFF; sel=4'b0000; @(posedge clk); #1; $display("S %0h", rdata);
    $finish;
  end
  always #5 clk = ~clk;
endmodule
"""
    got = [g.split()[1].lower() for g in _run_iverilog(rtl, "wb_beat_store", tb, tmp_path)]
    # all four bytes selected -> the whole word lands
    assert got[0] == "aabbccdd", got
    # bytes 0 and 2 selected -> those two replaced, bytes 1 and 3 PRESERVED
    assert got[1] == "aa22cc44", got
    # no byte selected -> the word is preserved entirely
    assert got[2] == "aa22cc44", got


def test_f2035_a_decline_discloses_without_the_caller_knowing_to_ask(solve_as,
                                                                    monkeypatch):
    """DEGRADE LOUDLY (flow-change-acceptance §6). `solve()` names its unresolved
    decisions only when the caller passes `notes`, and the default is silent — a
    decline that discloses nothing reads downstream as "nothing needed doing".
    `explain()` is the channel that does not require the caller to know to ask."""
    monkeypatch.setattr(M, "_toplevel", lambda r: "wb_beat_store")
    understated = _neutral_record("wb_beat_store", _F5_PORTS, """Complete the word-boundary store unit.
The data bus is 32-bit and one beat is transferred per cycle.
`sel` is the byte mask.
Transfers must be word-aligned. A response is returned.
""")
    why = M.explain(understated)
    assert why["emitted"] is False
    assert [n.split(":")[0] for n in why["unresolved"]] == [
        "byte_mask_polarity", "byte_mask_write_semantics", "response_mode"]
    assert "named in `unresolved`" in why["reason"]

    # a record this layer simply has no claim on says SO, rather than looking
    # identical to a record it refused
    monkeypatch.setattr(M, "_toplevel", lambda r: "sel_map")
    quiet = M.explain(_neutral_record("sel_map", _TBL_PORTS,
                                      "Complete the level selector."))
    assert quiet["emitted"] is False
    assert quiet["unresolved"] == []
    assert quiet["supplies_own_behaviour"] is False
    assert "claims nothing" in quiet["reason"]
    assert quiet["reason"] != why["reason"]

    # and a record the CONVENTIONAL solver answers is distinguishable from both:
    # the contract claimed nothing, yet RTL was emitted
    monkeypatch.setattr(M, "_toplevel", lambda r: "plain_avg")
    conv = M.explain(_neutral_record("plain_avg", _F1_PORTS, _F1_CONVENTIONAL))
    assert conv["emitted"] is True
    assert conv["supplies_own_behaviour"] is False and conv["unresolved"] == []
    assert len({why["reason"], quiet["reason"], conv["reason"]}) == 3


def test_f2035_contract_claims_nothing_on_real_in_repo_designs():
    """CORPUS SWEEP (flow-change-acceptance §2): zero false positives.

    The contract layer is consulted on EVERY record reaching `solve()`, so an
    extractor that hallucinates a contract would make `solve()` refuse designs it
    used to emit. This sweeps every checked-in Verilog artefact in the repo —
    real designs, not fixtures authored alongside this change — and feeds each
    one's WHOLE SOURCE in as the prompt, which is hostile input for a prose
    extractor because it is full of `=` assignments and bracketed ranges.

    None of them supplies stages, a literal table or a per-beat model, so the
    contract must claim NOTHING on all of them. A gate that fires on a
    legitimately-complete design is a bug in the gate, not a finding."""
    root = require_repo("vibe-ic-marketplace").parent      # the monorepo root
    files = sorted(f for f in list(root.rglob("*.v")) + list(root.rglob("*.sv"))
                   if ".git" not in f.parts)
    swept, claimed = 0, []
    for f in files:
        try:
            src = f.read_text(errors="replace")
        except OSError:
            continue
        mm = re.search(r"\bmodule\s+(\w+)", src)
        if not mm:
            continue
        top = mm.group(1)
        rec = {"id": str(f), "input": {"prompt": src, "context": {f.name: src}}}
        iface = M._context_header_ports(rec, top)
        if iface is None:
            continue
        ins, outs, _ = iface
        swept += 1
        c = M.extract_contract(rec, ins, outs)
        if c.supplies_own_behaviour() or c.beat is not None or c.unresolved:
            claimed.append((str(f), top, len(c.stages), len(c.tables),
                            c.beat is not None, c.unresolved[:2]))
    if swept == 0:
        pytest.skip("NOT_MEASURED: no parseable in-repo module header to sweep")
    assert claimed == [], claimed
    # state the population, so a sweep that silently shrinks to nothing is visible
    assert swept >= 15, "corpus sweep population collapsed to %d" % swept


def test_f2035_contract_layer_is_chip_agnostic():
    """The contract layer must key on STRUCTURE, never on an identity. No design
    id, prompt hash, benchmark-name dispatch or answer lookup."""
    src = (_PROG / "modify_complete_synth.py").read_text()
    for bad in ("cvdp_copilot_", "sha256", "md5", "prompt_hash",
                "benchmark_name", "ANSWER_LOOKUP"):
        assert bad not in src, "forbidden dispatch token %r in the solver" % bad
