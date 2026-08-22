"""test_accumulate_synth.py — the CVDP sequential ACCUMULATOR / running-op
deterministic solver.

accumulate_synth.solve(record) reads the module name from input.prompt +
input.context ONLY (via the bridge — the harness `.env` TOPLEVEL is an OFF-LIMITS
oracle), reads the interface from the PROMPT's own `### Inputs/Outputs` markdown list
(never the golden RTL), PARSES the reset polarity/sync + the data width + the
operation + (for a moving average) the window/divisor, and emits deterministic
SEQUENTIAL RTL named per the prompt — else SKIP (None) on ANY unstated/ambiguous
governing fact (including a module name absent from the prompt/context).

POSITIVES (each SOLVES + is FUNCTIONALLY correct against an iverilog clocked TB
driven by a sequence GENERATED HERE — not copied from any prompt table — so the
check proves FUNCTION, not table memorization; gated on the iverilog binary):
  * running accumulator (acc<=acc+data on enable, sync active-high reset -> 0);
  * integer MAC (acc<=acc+a*b on valid, sync active-low reset -> 0);
  * running maximum (max<=(data>max)?data:max on enable, reset -> 0);
  * power-of-2 moving average (last 8 samples, >>3) — the REAL CVDP
    cvdp_copilot_moving_average_0001 record when the dataset is on this host,
    verified against the harness's exact running model with a 1-cycle latency.

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * an accumulator whose RESET polarity/sync is unstated;
  * an accumulator whose DATA WIDTH is unstated;
  * a NON-power-of-2 moving average (a /10 average needs a real divider);
  * a GF / fixed-point accumulate (special algebra);
  * a windowed average whose window size is unstated;
  * a 2-stage / per-N pipelined MAC (not a single running MAC);
  * a composite / FSM-gated / protocol design;
  * a "modify / complete the existing RTL" DELTA task.

CHIP-AGNOSTIC: the solver keys only on operation/structure words + role-conventional
port names, never on a design name or a record id. The SAME prompt with any module
name solves identically and the emitted module is named per the prompt/context.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import accumulate_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_IVERILOG = bool(shutil.which("iverilog") and shutil.which("vvp"))

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# record builder (faithful to the CVDP v1.1.0 record shape).
# --------------------------------------------------------------------------- #
def _rec(top, prompt, *, input_context=None, rtl_path=None):
    rtl_path = rtl_path or f"rtl/{top}.sv"
    # The module name is a PROMPT fact (compliant source). The harness `.env`
    # TOPLEVEL is kept in the fixture but is an OFF-LIMITS oracle the solver must
    # never read — the name comes ONLY from input.prompt (via the bridge).
    named = f"Design the module `{top}`.\n\n{prompt}"
    return {
        "id": f"test_{top}",
        "input": {"prompt": named, "context": input_context or {}},
        "output": {"response": "", "context": {rtl_path: ""}},
        "harness": {"files": {"src/.env": (
            "SIM             = icarus\n"
            "TOPLEVEL_LANG   = verilog\n"
            f"TOPLEVEL        = {top}\n")}},
    }


def _dataset_record(rid):
    if not _DATASET.exists():
        return None
    for line in _DATASET.read_text().splitlines():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    return None


def _with_prompt_name(rec, top):
    """Clone `rec` and state the module name in input.prompt in a bridge-extractable
    form. The CVDP moving_average prompt already says 'the Module `moving_average`',
    but the bridge's name regex is case-sensitive; restating it as 'module `X`' keeps
    the name a PROMPT fact — NEVER the OFF-LIMITS harness `.env` TOPLEVEL — and lets
    the same record be re-bound to any name to prove prompt-name rename-invariance."""
    rec = json.loads(json.dumps(rec))
    rec.setdefault("input", {})
    rec["input"]["prompt"] = (
        f"Design the module `{top}`.\n\n{rec['input'].get('prompt', '')}")
    return rec


def _run_iverilog(rtl, tb, name):
    if not _IVERILOG:
        pytest.skip("iverilog/vvp not installed")
    with tempfile.TemporaryDirectory() as d:
        rp, tp, vp = (Path(d) / f"{name}.v", Path(d) / f"{name}_tb.v",
                      Path(d) / f"{name}.vvp")
        rp.write_text(rtl)
        tp.write_text(tb)
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vp), str(rp), str(tp)],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}"
        r = subprocess.run(["vvp", str(vp)], capture_output=True, text=True)
        return r.stdout


# =========================================================================== #
# fixture prompts (faithful to the CVDP dataset interface-section shape)
# =========================================================================== #
_ACC_PROMPT = """Design a running accumulator that maintains a running sum of an
incoming data stream.

### Inputs:
- **clk**: Clock signal.
- **rst**: Synchronous reset, active high.
- **en**: Enable. The accumulator updates only when high.
- **`data_in`** (8-bits, [7:0]): the input sample.

### Outputs:
- **`acc`** (16-bits, [15:0]): the running sum.

On each rising clock edge, when `en` is high, it accumulates the input:
`acc <= acc + data_in`. When `rst` is asserted the accumulator resets to 0.
"""

_MAC_PROMPT = """Design an integer multiply-accumulate (MAC) unit. It computes a
running multiply-accumulate of a streamed pair of operands.

### Inputs:
- **clk**: clock.
- **rst_n**: active-low synchronous reset.
- **valid**: input valid signal.
- **`a`** (8-bits, [7:0]): the multiplicand.
- **`b`** (8-bits, [7:0]): the multiplier.

### Outputs:
- **`acc`** (32-bits, [31:0]): the accumulated result.

It computes `acc <= acc + a*b` on every cycle that `valid` is high. On reset the
accumulator clears to 0.
"""

_MAX_PROMPT = """Design a running maximum tracker that keeps track of the maximum
value of an input stream.

### Inputs:
- **clk**: clock.
- **rst**: active-high synchronous reset.
- **en**: enable.
- **`data_in`** (8-bits, [7:0]): the input sample.

### Outputs:
- **`max_out`** (8-bits, [7:0]): the maximum value seen so far.

On each enabled clock edge it updates the running maximum of the stream. On reset
it resets to 0.
"""


# =========================================================================== #
# POSITIVE — running accumulator (sequential, reset/enable/width parsed)
# =========================================================================== #
def test_accumulator_solves_and_named_per_toplevel():
    rec = _rec("my_acc", _ACC_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module my_acc" in rtl
    assert S.family_of(rec) == "running_accumulator"
    assert "acc <= acc + data_in" in rtl
    assert "if (rst)" in rtl and "if (en)" in rtl   # active-high reset + enable guard


def test_accumulator_functionally_correct():
    rtl = S.solve(_rec("my_acc", _ACC_PROMPT))
    seq = [3, 0, 250, 1, 255, 255, 7, 100, 0, 42, 200, 13]
    # `acc` (a result register) is updated by `acc <= acc + x` on the edge that
    # consumes x, so the value visible AFTER that edge already INCLUDES x.
    post, m = [], 0
    for x in seq:
        m = (m + x) & 0xFFFF
        post.append(m)
    final = m & 0xFFFF
    tb = ["module tb; reg clk,rst,en; reg [7:0] data_in; wire [15:0] acc;",
          " integer errors=0;",
          " my_acc dut(.clk(clk),.rst(rst),.en(en),.data_in(data_in),.acc(acc));",
          " initial clk=0; always #5 clk=~clk; initial begin",
          "  rst=1; en=0; data_in=0; @(negedge clk); @(negedge clk); rst=0; en=1;"]
    for x, e in zip(seq, post):
        tb.append(f"  data_in={x}; @(posedge clk); #1; if(acc!=={e}) errors=errors+1;")
    # enable LOW must HOLD the accumulator state at the full running sum.
    tb.append("  en=0; data_in=99; @(posedge clk); @(posedge clk); #1;"
              f" if(acc!=={final}) errors=errors+1;")
    tb.append('  if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);')
    tb.append("  $finish; end endmodule")
    out = _run_iverilog(rtl, "\n".join(tb), "acc")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — integer MAC (acc<=acc+a*b on valid, active-low reset)
# =========================================================================== #
def test_mac_solves():
    rec = _rec("my_mac", _MAC_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module my_mac" in rtl
    assert S.family_of(rec) == "integer_mac"
    assert "acc + (a * b)" in rtl
    assert "if (!rst_n)" in rtl and "if (valid)" in rtl


def test_mac_functionally_correct():
    rtl = S.solve(_rec("my_mac", _MAC_PROMPT))
    pairs = [(3, 4), (0, 255), (255, 255), (7, 9), (100, 2), (1, 1), (200, 3), (5, 5)]
    # `acc <= acc + a*b` updates on the consuming edge -> the post-edge value
    # already includes the current product.
    post, m = [], 0
    for a, b in pairs:
        m = (m + a * b) & 0xFFFFFFFF
        post.append(m)
    tb = ["module tb; reg clk,rst_n,valid; reg [7:0] a,b; wire [31:0] acc;",
          " integer errors=0;",
          " my_mac dut(.clk(clk),.rst_n(rst_n),.valid(valid),.a(a),.b(b),.acc(acc));",
          " initial clk=0; always #5 clk=~clk; initial begin",
          "  rst_n=0; valid=0; a=0; b=0; @(negedge clk); @(negedge clk);"
          " rst_n=1; valid=1;"]
    for (a, b), e in zip(pairs, post):
        tb.append(f"  a={a}; b={b}; @(posedge clk); #1; if(acc!=={e}) errors=errors+1;")
    tb.append('  if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);')
    tb.append("  $finish; end endmodule")
    out = _run_iverilog(rtl, "\n".join(tb), "mac")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — running maximum (max<=(data>max)?data:max on enable)
# =========================================================================== #
def test_max_solves():
    rec = _rec("my_max", _MAX_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert S.family_of(rec) == "running_minmax"
    assert "data_in > max_out" in rtl


def test_max_functionally_correct():
    rtl = S.solve(_rec("my_max", _MAX_PROMPT))
    seq = [5, 3, 9, 9, 2, 200, 199, 200, 255, 0, 254]
    # max_out updates on the consuming edge -> the post-edge value already accounts
    # for the current sample.
    post, m = [], 0
    for x in seq:
        m = x if x > m else m
        post.append(m)
    tb = ["module tb; reg clk,rst,en; reg [7:0] data_in; wire [7:0] max_out;",
          " integer errors=0;",
          " my_max dut(.clk(clk),.rst(rst),.en(en),.data_in(data_in),.max_out(max_out));",
          " initial clk=0; always #5 clk=~clk; initial begin",
          "  rst=1; en=0; data_in=0; @(negedge clk); @(negedge clk); rst=0; en=1;"]
    for x, e in zip(seq, post):
        tb.append(f"  data_in={x}; @(posedge clk); #1; if(max_out!=={e}) errors=errors+1;")
    tb.append('  if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);')
    tb.append("  $finish; end endmodule")
    out = _run_iverilog(rtl, "\n".join(tb), "max")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — power-of-2 moving average — the REAL CVDP record
# =========================================================================== #
def test_moving_average_solves():
    rec = _dataset_record("cvdp_copilot_moving_average_0001")
    if rec is None:
        pytest.skip("moving_average dataset record not present on this host")
    rec = _with_prompt_name(rec, "moving_average")   # name from PROMPT, not harness
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module moving_average" in rtl
    assert S.family_of(rec) == "moving_average_pow2"
    assert "sum_next[14:3]" in rtl     # /8 == >>3 of the NEXT running sum (incl. this sample)
    assert "buffer [0:7]" in rtl       # last-8 ring buffer
    assert "if (reset)" in rtl         # sync active-high reset parsed


def _movavg_model(seq, window=8):
    """The EXACT harness model: queue of last `window`, current_sum, avg = sum//N.
    The DUT registers each sample on the edge it is applied and publishes, on that same
    edge, the average INCLUDING that sample (the official cocotb harness compares the
    DUT output against the average that folds in the just-applied input — verified against
    the design's own harness). The earlier 'publish the OLD avg' model lagged one cycle and
    FAILED the real harness (`Mismatch ... got 0`)."""
    q, s, out = [], 0, []
    for x in seq:
        if len(q) < window:
            q.append(x); s += x
        else:
            old = q.pop(0); s += x - old; q.append(x)
        out.append(s // window)   # avg including the current sample, published this edge
    return out


def test_moving_average_functionally_correct_self_generated_sequence():
    rec = _dataset_record("cvdp_copilot_moving_average_0001")
    if rec is None:
        pytest.skip("moving_average dataset record not present on this host")
    rec = _with_prompt_name(rec, "moving_average")   # name from PROMPT, not harness
    rtl = S.solve(rec)
    # a sequence GENERATED HERE (partial-fill phase, mid values, max, repeats) — NOT
    # copied from the prompt; proves the FUNCTION, not memorization of a table.
    seq = [5, 7, 9, 11, 13, 15, 17, 19, 100, 200, 300, 400,
           4095, 0, 1, 2, 3000, 3000, 3000, 3000, 8, 8, 8, 8]
    exp = _movavg_model(seq, 8)
    tb = ["module tb; reg clk,reset; reg [11:0] data_in; wire [11:0] data_out;",
          " integer errors=0;",
          " moving_average dut(.clk(clk),.reset(reset),.data_in(data_in),"
          ".data_out(data_out));",
          " initial clk=0; always #5 clk=~clk; initial begin",
          "  reset=1; data_in=0; @(negedge clk); @(negedge clk); reset=0;"]
    for x, e in zip(seq, exp):
        tb.append(f"  data_in={x}; @(posedge clk); #1; if(data_out!=={e}) errors=errors+1;")
    tb.append('  if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);')
    tb.append("  $finish; end endmodule")
    out = _run_iverilog(rtl, "\n".join(tb), "movavg")
    assert "ALL_PASS" in out, out


def test_moving_average_reset_clears_mid_stream():
    rec = _dataset_record("cvdp_copilot_moving_average_0001")
    if rec is None:
        pytest.skip("moving_average dataset record not present on this host")
    rec = _with_prompt_name(rec, "moving_average")   # name from PROMPT, not harness
    rtl = S.solve(rec)
    # drive, reset mid-stream, prove it restarts fresh (output back to 0 then rebuilds).
    tb = ["module tb; reg clk,reset; reg [11:0] data_in; wire [11:0] data_out;",
          " integer errors=0;",
          " moving_average dut(.clk(clk),.reset(reset),.data_in(data_in),"
          ".data_out(data_out));",
          " initial clk=0; always #5 clk=~clk; initial begin",
          "  reset=1; data_in=0; @(negedge clk); @(negedge clk); reset=0;",
          "  data_in=80; @(posedge clk); @(posedge clk); @(posedge clk);",
          "  reset=1; @(posedge clk); #1;",
          "  if(data_out!==0) errors=errors+1;",   # output cleared on reset
          "  @(posedge clk); #1; if(data_out!==0) errors=errors+1;",
          '  if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);',
          "  $finish; end endmodule"]
    out = _run_iverilog(rtl, "\n".join(tb), "movrst")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# DATASET — exactly one real record solves (M=1), and it is moving_average_0001
# =========================================================================== #
def test_dataset_emit_count_is_one_and_is_moving_average():
    if not _DATASET.exists():
        pytest.skip("CVDP dataset not present on this host")
    recs = [json.loads(l) for l in _DATASET.read_text().splitlines()]
    # Give EVERY record a bridge-extractable prompt name (so the precision is gated
    # by the FAMILY recognizer, not by which prompts happen to state the name in a
    # case the bridge parses) — still, exactly ONE record solves under accumulate.
    solved = [r["id"] for r in recs if S.solve(_with_prompt_name(r, "target_mod"))]
    assert solved == ["cvdp_copilot_moving_average_0001"], solved


# =========================================================================== #
# §4.05 NEGATIVES — each MUST SKIP (return None)
# =========================================================================== #
def test_skip_unstated_reset_polarity():
    p = """Design a running accumulator.
### Inputs:
- **clk**: clock.
- **rst**: reset signal.
- **`data_in`** (8-bits, [7:0]): input.
### Outputs:
- **`acc`** (16-bits, [15:0]): running sum.
It accumulates acc <= acc + data_in each cycle. On reset acc clears."""
    assert S.solve(_rec("acc_nopol", p)) is None   # polarity/sync not stated


def test_skip_unstated_width():
    p = """Design a running accumulator.
### Inputs:
- **clk**: clock.
- **rst**: active-high synchronous reset.
- **data_in**: the input sample.
### Outputs:
- **acc**: the running sum.
It accumulates acc <= acc + data_in. On reset acc resets to 0."""
    assert S.solve(_rec("acc_nowidth", p)) is None   # data/acc width not stated


def test_skip_non_power_of_2_moving_average():
    p = """Design a 10-sample moving average of a 12-bit data stream.
### Inputs:
- **clk**: clock.
- **reset**: synchronous reset, active high.
- **[11:0] data_in**: 12-bit input data.
### Outputs:
- **[11:0] data_out**: the average of the last 10 samples.
The output is the sum of the last 10 input samples divided by 10. On reset the
output clears to 0."""
    assert S.solve(_rec("ma10", p)) is None   # /10 needs a real divider


def test_skip_gf_accumulate():
    p = """Design a GF(2^8) multiply-accumulate over the irreducible polynomial.
### Inputs:
- **clk**: clock.
- **rst_n**: active-low synchronous reset.
- **`a`** (8-bits, [7:0]): operand.
- **`b`** (8-bits, [7:0]): operand.
### Outputs:
- **`acc`** (8-bits, [7:0]): the accumulated GF product.
It accumulates the Galois-field product each cycle."""
    assert S.solve(_rec("gfmac", p)) is None


def test_skip_fixed_point_accumulate():
    p = """Design a fixed-point Q4.4 running accumulator.
### Inputs:
- **clk**: clock.
- **rst**: active-high synchronous reset.
- **`data_in`** (8-bits, [7:0]): fixed-point input.
### Outputs:
- **`acc`** (16-bits, [15:0]): the running sum.
It accumulates the Q4.4 fixed-point values each cycle. Reset clears to 0."""
    assert S.solve(_rec("fxacc", p)) is None


def test_skip_unstated_window_average():
    p = """Design a moving average of a 12-bit data stream.
### Inputs:
- **clk**: clock.
- **reset**: synchronous reset, active high.
- **[11:0] data_in**: input data.
### Outputs:
- **[11:0] data_out**: the moving average.
The output is the average over a configurable window. On reset it clears to 0."""
    assert S.solve(_rec("ma", p)) is None   # window size not stated


def test_skip_pipelined_per_n_mac():
    p = """Design a 2-stage pipelined MAC. After N valid inputs the accumulated
result is output for one cycle.
### Inputs:
- **clk**: clock.
- **rst_n**: active-low synchronous reset.
- **valid_i**: input valid.
- **`multiplicand`** (8-bits, [7:0]): operand.
- **`multiplier`** (8-bits, [7:0]): operand.
### Outputs:
- **`acc`** (32-bits, [31:0]): accumulated result.
In the first stage multiplication takes 1 cycle, then accumulation in the second
stage takes 1 cycle. Every N cycles the result is output."""
    assert S.solve(_rec("pmac", p)) is None   # pipeline + per-N window


def test_skip_fsm_composite():
    p = """Design a packet controller with a finite state machine that accumulates
a checksum.
### Inputs:
- **clk**: clock.
- **rst**: active-high synchronous reset.
- **`data_in`** (8-bits, [7:0]): input byte.
### Outputs:
- **`sum`** (16-bits, [15:0]): the accumulated checksum.
The state machine receives packets and accumulates the byte sum."""
    assert S.solve(_rec("pkt", p)) is None   # FSM / packet composite


def test_skip_modify_existing_delta_task():
    p = """The original module `moving_average` calculates the 8-sample moving
average. Enhance it by adding an enable signal.
### Inputs:
- **clk**: clock.
- **reset**: synchronous reset, active high.
- **[11:0] data_in**: input data.
- **enable**: 1-bit enable.
### Outputs:
- **[11:0] data_out**: the moving average.
"""
    assert S.solve(_rec("moving_average", p)) is None   # "enhance the original" delta


def test_skip_delta_via_input_context():
    rec = _rec("my_acc", _ACC_PROMPT,
               input_context={"rtl/my_acc.sv": "module my_acc(); endmodule"})
    assert S.solve(rec) is None


def test_skip_non_member_combinational_adder():
    p = """Design a 4-bit ripple-carry adder.
### Inputs:
- **`a`** (4-bits, [3:0]): operand.
- **`b`** (4-bits, [3:0]): operand.
### Outputs:
- **`sum`** (5-bits, [4:0]): the sum.
"""
    assert S.solve(_rec("adder", p)) is None


# =========================================================================== #
# NO-LEAK — never reads the golden/reference RTL body
# =========================================================================== #
def test_never_reads_golden_rtl_body():
    rec = _rec("my_acc", _ACC_PROMPT)
    rec["output"]["context"]["rtl/my_acc.sv"] = (
        "module my_acc; assign acc = 16'hBEEF; endmodule")
    rtl = S.solve(rec)
    assert rtl is not None
    assert "BEEF" not in rtl
    assert "acc <= acc + data_in" in rtl   # the parsed datapath, not the planted body


# =========================================================================== #
# CHIP-AGNOSTIC — keyed on operation/structure, never a design name
# =========================================================================== #
@pytest.mark.parametrize("top", ["FOO_999", "zztop", "my_block", "WIDGET"])
def test_chip_agnostic_module_named_per_toplevel(top):
    rtl = S.solve(_rec(top, _ACC_PROMPT))
    assert rtl is not None
    assert f"module {top}" in rtl


def test_chip_agnostic_rename_invariant():
    a = S.solve(_rec("alpha", _MAC_PROMPT))
    b = S.solve(_rec("omega_block", _MAC_PROMPT))
    assert a and b
    assert a.replace("alpha", "X") == b.replace("omega_block", "X")


def test_real_moving_average_solves_under_any_prompt_name():
    """The REAL prompt re-bound (via input.prompt) to an unrelated module name still
    solves identically — proving recognition is on semantics (not the 'moving_average'
    name) AND that the emitted name comes from the PROMPT, never the harness TOPLEVEL."""
    rec = _dataset_record("cvdp_copilot_moving_average_0001")
    if rec is None:
        pytest.skip("moving_average dataset record not present on this host")
    rec2 = _with_prompt_name(rec, "zz_block")
    rtl = S.solve(rec2)
    assert rtl is not None
    assert "module zz_block" in rtl
    assert "buffer [0:7]" in rtl and "sum_next[14:3]" in rtl


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── polarity: a PROMPT states a retired parameter as readily as a live one ──
#
# Found by `prose_polarity_census`. `_param_defaults` reads a prompt -- natural
# language, written by a person -- and published a denied default as a stated
# one. It compounds with `setdefault`, which keeps the FIRST match: a retired
# value written before the live one took its place.

def _defaults(prompt):
    import accumulate_synth as M
    return M._param_defaults(prompt)


def test_a_retired_parameter_default_is_not_read_as_stated():
    assert _defaults("Do not use parameter WIDTH = 8.") == {}


def test_a_retired_value_does_not_displace_the_live_one():
    assert _defaults("parameter WIDTH = 8 is no longer used.\n"
                     "Use parameter WIDTH = 16.") == {"WIDTH": 16}


def test_a_denied_PROSE_default_is_not_read():
    """The first pattern is plain English -- `WIDTH ... default value of 5` --
    so this reader is prose first and Verilog second."""
    assert _defaults("WIDTH no longer has a default value of 5.") == {}


def test_a_plainly_stated_default_is_still_read():
    """The control arm: a fix that refused everything would pass the rest."""
    assert _defaults("Use parameter WIDTH = 8 for the datapath.") == {"WIDTH": 8}
    assert _defaults("WIDTH has a default value of 5.") == {"WIDTH": 5}
