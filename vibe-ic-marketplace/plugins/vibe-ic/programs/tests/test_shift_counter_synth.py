"""test_shift_counter_synth.py — the CVDP barrel-shift/rotate +
saturating/specialized-counter deterministic solver.

shift_counter_synth.solve(record) reads the module name from input.prompt/context
(via the bridge; never the OFF-LIMITS harness TOPLEVEL), reads the interface from
the PROMPT's own `### Inputs/Outputs` markdown list (never the golden RTL), PARSES
the direction + mode (shift family) or the bound + saturate-vs-wrap behaviour
(counter family), and emits deterministic RTL named per the stated name — else
SKIP (None) on ANY unstated governing fact.

POSITIVES (each SOLVES + is FUNCTIONALLY correct against its cocotb model, host-
verified via iverilog when the binary is present):
  * combinational barrel LOGICAL shift, direction read from a stated control-bit
    polarity (left=1 => <<, right=0 => >> masked);
  * clocked barrel ROTATE, direction read from a stated control-bit polarity
    (left rotate / right rotate, amount mod WIDTH), active-low reset clears;
  * a saturating up/down counter that CLAMPS at a stated max/min (no wrap);
  * a 24-hour split-nibble BCD wall-clock counter (stated 60/60/24 bounds).

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * a barrel shifter whose DIRECTION polarity is unstated;
  * a unit that can shift OR rotate (mode unstated/ambiguous between two ops);
  * a multi-mode menu (mask / XOR / arithmetic+rotate selectable) — not one emit;
  * a counter "up to a maximum" whose SATURATE-vs-WRAP behaviour is unstated;
  * a "modify the existing RTL" delta task (prior code in input.context).

CHIP-AGNOSTIC: the solver keys only on STRUCTURE words + role-conventional port
names, never on a design name. The SAME spec under three different prompt-stated
names solves identically and the emitted module is named per the stated name.

The iverilog functional checks are GATED on the iverilog binary; the structural /
SKIP / agnostic assertions run anywhere. The real-dataset records are used when the
CVDP jsonl is present on this host; otherwise faithful synthetic records stand in.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import shift_counter_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_IVERILOG = shutil.which("iverilog") and shutil.which("vvp")

# The real CVDP code-generation jsonl, if present on this host (functional cross-
# check uses the dataset records directly; absence falls back to synthetic twins).
_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# record builder (faithful to CVDP v1.1.0 record shape: input.prompt +
# input.context + output.context[<rtl path>] empty + harness.files .env TOPLEVEL).
# --------------------------------------------------------------------------- #
def _rec(top, prompt, *, input_context=None, rtl_path=None):
    # CVDP-COMPLIANT record: the module NAME must be recoverable from input.prompt
    # (the ONLY model-visible surface) WITHOUT the OFF-LIMITS harness. The dataset's
    # `### Module Name:` / bare-backtick naming forms are not always bridge-parseable,
    # so prepend a canonical `module `<top>`` designation whenever `toplevel_name`
    # cannot already recover the name from the prompt+context. The interface already
    # lives in the prompt's own `### Inputs/Outputs`. The harness `.env` TOPLEVEL is
    # retained for record-shape fidelity only; the refactored solver never reads it.
    import cvdp_atomic_bridge as _B
    if _B.toplevel_name({"input": {"prompt": prompt,
                                   "context": input_context or {}}}) != top:
        prompt = f"Design the Verilog module `{top}`.\n\n" + prompt
    rtl_path = rtl_path or f"rtl/{top}.sv"
    rec = {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": input_context or {}},
        "output": {"response": "", "context": {rtl_path: ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"TOPLEVEL        = {top}\n"),
        }},
    }
    return rec


def _dataset_record(rid):
    if not _DATASET.exists():
        return None
    for line in _DATASET.read_text().splitlines():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    return None


def _ensure_named(rec, top):
    """Re-state the module NAME — already present in the real CVDP prompt, but in a
    form the shipped bridge does not parse (e.g. `### Module Name:`, `Module `X``) —
    in a canonical, bridge-parseable `module `<top>`` designation, so
    `toplevel_name` recovers it from input.prompt WITHOUT the OFF-LIMITS harness.
    Purely relocates a model-visible fact the prompt already contains; a no-op when
    the name is already recoverable or when rec is None (dataset absent -> twin)."""
    if rec is None:
        return None
    import cvdp_atomic_bridge as _B
    if _B.toplevel_name(rec) != top:
        rec = json.loads(json.dumps(rec))
        rec["input"]["prompt"] = (
            f"Design the Verilog module `{top}`.\n\n"
            + (rec.get("input") or {}).get("prompt", ""))
    return rec


def _run_iverilog(rtl, tb, name):
    """Compile rtl+tb, run, return stdout. Skips if iverilog absent."""
    if not _IVERILOG:
        pytest.skip("iverilog/vvp not installed")
    with tempfile.TemporaryDirectory() as d:
        rp, tp, vp = (Path(d) / f"{name}.sv", Path(d) / f"{name}_tb.sv",
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
_BARREL_PROMPT = """Design an **8-bit barrel shifter** which can shift the bits of
an 8-bit input either to the left or to the right based on a control signal. The
operation must complete in **one clock cycle**.

### Module Name:
`barrel_shifter_8bit`

This design should be a **combinational logic**.

### Interface:

#### Inputs:
- **`data_in`** (8-bits, [7:0]): The 8-bit input data.
- **`shift_bits`** (3-bits, [2:0]): Determines how many bits to shift.
- **`left_right`** (1-bit): Decides the direction of the shift.
   - `left_right = 1`: Shift left.
   - `left_right = 0`: Shift right.

#### Output:
- **`data_out`** (8-bits, [7:0]): The result after shifting.

When `data_in` shifts right by `shift_bits`, zeros are inserted into the MSB
positions. When `data_in` shifts left, zeros are inserted into the LSB positions.
"""

_ROTATE_PROMPT = """Complete the parameterized **`adc_data_rotate`** module. The
module performs bitwise rotation of data. It operates synchronously with a clock.

### Parameterization
- `DATA_WIDTH`, with a default value of 8 bits.

### Inputs
- **`i_clk`** (logic): Clock signal.
- **`i_rst_n`** (logic): Active-low reset signal.
- **`i_adc_data_in`** (logic [`DATA_WIDTH`-1:0]): Input data to be rotated.
- **`i_shift_count`** (logic [3:0]): Number of bits to rotate.
- **`i_shift_direction`** (logic): Controls the rotation direction:
  - `0`: Left Rotate
  - `1`: Right Rotate

### Outputs
- **`o_processed_data`** (logic [`DATA_WIDTH`-1:0]): The rotated result.
- **`o_operation_status`** (logic): Operation status (1 when active).

On the rising edge of `i_clk` and when `i_rst_n = 1`, the module performs the
rotation. Bits shifted out from the left re-enter on the right (Left Rotate).
When reset, outputs reset to 0.
"""

_SAT_PROMPT = """Design a saturating up/down counter.

### Inputs:
- `clk`: Clock signal.
- `rst`: Active-high synchronous reset signal.
- **`up_down`** (1-bit): When 1 increment, when 0 decrement.

### Outputs:
- **`count`** (4-bits, [3:0]): The counter value.

The counter saturates: it holds at a maximum of 15 and stays at a minimum of 0.
It does not wrap. On reset the counter resets to 0.
"""


# =========================================================================== #
# POSITIVE — barrel logical shift (combinational, direction parsed)
# =========================================================================== #
def test_barrel_shift_solves_and_named_per_toplevel():
    rec = _ensure_named(_dataset_record("cvdp_copilot_barrel_shifter_0001"),
                        "barrel_shifter_8bit") or \
        _rec("barrel_shifter_8bit", _BARREL_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module barrel_shifter_8bit" in rtl
    assert S.family_of(rec) == "barrel_shift_rotate"
    # logical shift, NOT arithmetic, NOT rotate
    assert ">>>" not in rtl
    assert "<<" in rtl and ">>" in rtl


def test_barrel_shift_functionally_correct():
    rec = _ensure_named(_dataset_record("cvdp_copilot_barrel_shifter_0001"),
                        "barrel_shifter_8bit") or \
        _rec("barrel_shifter_8bit", _BARREL_PROMPT)
    rtl = S.solve(rec)
    # cocotb model: left = (din<<s)&0xFF, right = (din>>s)&0xFF
    checks = []
    for din in (0xCC, 0xFF, 0x01, 0x80, 0x55):
        for s in range(8):
            for lr in (0, 1):
                exp = ((din << s) & 0xFF) if lr == 1 else ((din >> s) & 0xFF)
                checks.append((din, s, lr, exp))
    tb = ["module tb; reg [7:0] data_in; reg [2:0] shift_bits; reg left_right;",
          " wire [7:0] data_out; integer errors=0;",
          "barrel_shifter_8bit dut(.data_in(data_in),.shift_bits(shift_bits),"
          ".left_right(left_right),.data_out(data_out)); initial begin"]
    for din, s, lr, exp in checks:
        tb.append(f"  data_in={din}; shift_bits={s}; left_right={lr}; #1;"
                  f" if(data_out!=={exp}) errors=errors+1;")
    tb.append(f'  if(errors==0) $display("ALL_PASS %0d",{len(checks)});'
              ' else $display("FAIL %0d",errors); $finish; end endmodule')
    out = _run_iverilog(rtl, "\n".join(tb), "barrel")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — barrel rotate (clocked, direction parsed, amount mod WIDTH)
# =========================================================================== #
def test_rotate_solves_clocked_with_reset():
    rec = _ensure_named(_dataset_record("cvdp_copilot_adc_data_rotate_0001"),
                        "adc_data_rotate") or \
        _rec("adc_data_rotate", _ROTATE_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module adc_data_rotate" in rtl
    assert S.family_of(rec) == "barrel_shift_rotate"
    assert "posedge i_clk" in rtl          # clocked
    assert "!i_rst_n" in rtl               # active-low reset parsed
    assert "% 8" in rtl                    # amount taken mod WIDTH for a rotate


def test_rotate_functionally_correct():
    rec = _ensure_named(_dataset_record("cvdp_copilot_adc_data_rotate_0001"),
                        "adc_data_rotate") or \
        _rec("adc_data_rotate", _ROTATE_PROMPT)
    rtl = S.solve(rec)

    def rotl(v, a, w=8):
        a %= w
        return ((v << a) | (v >> (w - a))) & ((1 << w) - 1) if a else v

    def rotr(v, a, w=8):
        a %= w
        return ((v >> a) | (v << (w - a))) & ((1 << w) - 1) if a else v

    # the dataset's own cocotb literals: 179 rot-by-3 left=157, right=118.
    assert rotl(179, 3) == 157 and rotr(179, 3) == 118
    checks = []
    for din in (179, 0xFF, 0x01, 0xA5):
        for s in range(16):
            for d in (0, 1):
                exp = rotl(din, s) if d == 0 else rotr(din, s)
                checks.append((din, s, d, exp))
    tb = ["module tb; reg i_clk,i_rst_n,i_shift_direction; reg [7:0] i_adc_data_in;",
          " reg [3:0] i_shift_count; wire [7:0] o_processed_data;",
          " wire o_operation_status; integer errors=0;",
          "adc_data_rotate dut(.i_clk(i_clk),.i_rst_n(i_rst_n),"
          ".i_adc_data_in(i_adc_data_in),.i_shift_count(i_shift_count),"
          ".i_shift_direction(i_shift_direction),.o_processed_data(o_processed_data),"
          ".o_operation_status(o_operation_status));",
          "initial i_clk=0; always #5 i_clk=~i_clk; initial begin",
          " i_rst_n=0; i_adc_data_in=0; i_shift_count=0; i_shift_direction=0;",
          " @(negedge i_clk); i_rst_n=1; @(posedge i_clk);"]
    for din, s, d, exp in checks:
        tb.append(f"  i_adc_data_in={din}; i_shift_count={s}; i_shift_direction={d};"
                  f" @(posedge i_clk); @(negedge i_clk);"
                  f" if(o_processed_data!=={exp}) errors=errors+1;"
                  f" if(o_operation_status!==1) errors=errors+1;")
    tb.append(f'  if(errors==0) $display("ALL_PASS %0d",{len(checks)});'
              ' else $display("FAIL %0d",errors); $finish; end endmodule')
    out = _run_iverilog(rtl, "\n".join(tb), "adcrot")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — saturating up/down counter (clamp at stated max/min, no wrap)
# =========================================================================== #
def test_saturating_counter_solves():
    rec = _rec("sat_counter", _SAT_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module sat_counter" in rtl
    assert S.family_of(rec) == "saturating_counter"
    # clamp bounds present, no wrap-to-0 statement emitted
    assert "< 15" in rtl and "> 0" in rtl


def test_saturating_counter_functionally_clamps():
    rtl = S.solve(_rec("sat_counter", _SAT_PROMPT))
    tb = ["module tb; reg clk,rst,up_down; wire [3:0] count;",
          " integer i,errors=0; reg [4:0] model;",
          "sat_counter dut(.clk(clk),.rst(rst),.up_down(up_down),.count(count));",
          "initial clk=0; always #5 clk=~clk; initial begin",
          " rst=1; up_down=1; @(posedge clk); @(posedge clk); model=0;",
          " @(negedge clk); rst=0;",
          # 20 ups: clamps at 15
          " for(i=0;i<20;i=i+1) begin @(posedge clk);",
          "   if(model<15) model=model+1; #1;",
          "   if(count!==model[3:0]) errors=errors+1; end",
          " up_down=0;",
          # 20 downs: clamps at 0
          " for(i=0;i<20;i=i+1) begin @(posedge clk);",
          "   if(model>0) model=model-1; #1;",
          "   if(count!==model[3:0]) errors=errors+1; end",
          ' if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);',
          " $finish; end endmodule"]
    out = _run_iverilog(rtl, "\n".join(tb), "satc")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# POSITIVE — 24-hour split-nibble BCD wall-clock counter (stated 60/60/24)
# =========================================================================== #
def test_bcd_clock_solves_and_functionally_rolls_over():
    rec = _dataset_record("cvdp_copilot_bcd_counter_0001")
    if rec is None:
        pytest.skip("bcd_counter dataset record not present on this host")
    rtl = S.solve(rec)
    assert rtl is not None
    assert "module bcd_counter" in rtl
    assert S.family_of(rec) == "bcd_clock_counter"
    # full-day behavioural sim mirroring the dataset cocotb test.
    tb = ["module tb; reg clk,rst;",
          " wire [3:0] ms_hr,ls_hr,ms_min,ls_min,ms_sec,ls_sec;",
          " integer i,errors=0;",
          "bcd_counter dut(.clk(clk),.rst(rst),.ms_hr(ms_hr),.ls_hr(ls_hr),"
          ".ms_min(ms_min),.ls_min(ls_min),.ms_sec(ms_sec),.ls_sec(ls_sec));",
          "initial clk=0; always #5 clk=~clk; initial begin",
          " rst=1; @(posedge clk); @(posedge clk); rst=0; @(posedge clk);",
          " for(i=0;i<86399;i=i+1) @(posedge clk);",
          " if(!(ms_hr==2&&ls_hr==3&&ms_min==5&&ls_min==9&&ms_sec==5&&ls_sec==9))"
          " errors=errors+1;",
          " @(posedge clk);",  # midnight rollover -> 00:00:00
          " if(!(ms_hr==0&&ls_hr==0&&ms_min==0&&ls_min==0&&ms_sec==0&&ls_sec==0))"
          " errors=errors+1;",
          " for(i=0;i<36610;i=i+1) @(posedge clk);",  # +10:10:10
          " if(!(ms_hr==1&&ls_hr==0&&ms_min==1&&ls_min==0&&ms_sec==1&&ls_sec==0))"
          " errors=errors+1;",
          ' if(errors==0) $display("ALL_PASS"); else $display("FAIL %0d",errors);',
          " $finish; end endmodule"]
    out = _run_iverilog(rtl, "\n".join(tb), "bcd")
    assert "ALL_PASS" in out, out


# =========================================================================== #
# §4.05 NEGATIVES — each MUST SKIP (return None)
# =========================================================================== #
def test_skip_unstated_shift_direction_polarity():
    # a barrel shifter whose left_right port exists but no 1/0 -> left/right map.
    p = """Design an 8-bit barrel shifter.
### Inputs:
- **`data_in`** (8-bits, [7:0]): input data.
- **`shift_bits`** (3-bits, [2:0]): shift amount.
- **`left_right`** (1-bit): direction control.
### Outputs:
- **`data_out`** (8-bits, [7:0]): result.
The unit shifts left or right. Combinational, one clock cycle.
"""
    assert S.solve(_rec("bs8", p)) is None


def test_skip_shift_or_rotate_ambiguous_mode():
    p = """Design a unit that can shift OR rotate the bits.
### Inputs:
- **`data_in`** (8-bits, [7:0])
- **`shift_bits`** (3-bits, [2:0])
- **`left_right`** (1-bit): `left_right = 1`: left. `left_right = 0`: right.
### Outputs:
- **`data_out`** (8-bits, [7:0])
It can shift the bits or rotate the bits left/right.
"""
    assert S.solve(_rec("u", p)) is None


def test_skip_multi_mode_menu():
    p = """Barrel shifter with a 3-bit mode `mode [2:0]`:
000 logical shift, 001 arithmetic shift, 010 rotate, 011 mask, 100 XOR.
### Inputs:
- **`data_in`** (8-bits, [7:0])
- **`shift_bits`** (3-bits, [2:0])
- **`left_right`** (1-bit): `left_right = 1`: left. `left_right = 0`: right.
- **`mode`** (3-bits, [2:0])
### Outputs:
- **`data_out`** (8-bits, [7:0])
"""
    assert S.solve(_rec("u", p)) is None


def test_skip_counter_saturate_vs_wrap_unstated():
    # "counts up to a maximum" with NO saturate/clamp/wrap statement -> ambiguous.
    p = """A counter.
### Inputs:
- `clk`: clock.
- `rst`: active-high reset.
### Outputs:
- **`count`** (4-bits, [3:0]): the value.
The counter counts up to a maximum of 9 and a minimum of 0.
"""
    assert S.solve(_rec("c", p)) is None


def test_skip_modify_existing_delta_task():
    # a "modify the existing RTL" task ships prior code in input.context.
    rec = _rec("barrel_shifter_8bit", _BARREL_PROMPT,
               input_context={"rtl/barrel_shifter_8bit.sv":
                              "module barrel_shifter_8bit(); endmodule"})
    assert S.solve(rec) is None


def test_skip_non_member_design():
    p = """Design a 4-bit ripple-carry adder.
### Inputs:
- **`a`** (4-bits, [3:0])
- **`b`** (4-bits, [3:0])
### Outputs:
- **`sum`** (5-bits, [4:0])
"""
    assert S.solve(_rec("adder", p)) is None


# =========================================================================== #
# NO-LEAK — the solver never reads the golden/reference RTL body
# =========================================================================== #
def test_never_reads_golden_rtl_body():
    # plant a WRONG body in output.context — the emit must be the parsed shifter,
    # never echo the planted logic.
    rec = _rec("barrel_shifter_8bit", _BARREL_PROMPT)
    rec["output"]["context"]["rtl/barrel_shifter_8bit.sv"] = (
        "module barrel_shifter_8bit; assign data_out = 8'hAB; endmodule")
    rtl = S.solve(rec)
    assert rtl is not None
    assert "8'hAB" not in rtl
    assert "<<" in rtl  # the real parsed shift, not the planted constant


# =========================================================================== #
# CHIP-AGNOSTIC — same prompt, different TOPLEVEL => named per TOPLEVEL
# =========================================================================== #
@pytest.mark.parametrize("top", ["FOO_999", "zztop", "my_block", "WIDGET"])
def test_chip_agnostic_module_named_per_toplevel(top):
    rtl = S.solve(_rec(top, _SAT_PROMPT))
    assert rtl is not None
    assert f"module {top}" in rtl


def test_chip_agnostic_solves_independent_of_design_name():
    # the SAME structure under two unrelated names solves identically (same family,
    # same emitted logic modulo the module name).
    a = S.solve(_rec("alpha", _SAT_PROMPT))
    b = S.solve(_rec("omega_block", _SAT_PROMPT))
    assert a and b
    assert a.replace("alpha", "X") == b.replace("omega_block", "X")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── polarity: a PROMPT states a retired parameter as readily as a live one ──
#
# Found by `prose_polarity_census`. `_param_defaults` reads a prompt -- natural
# language, written by a person -- and published a denied default as a stated
# one. It compounds with `setdefault`, which keeps the FIRST match: a retired
# value written before the live one took its place.

def _defaults(prompt):
    import shift_counter_synth as M
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
