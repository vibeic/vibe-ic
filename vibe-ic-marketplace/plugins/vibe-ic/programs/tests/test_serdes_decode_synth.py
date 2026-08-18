"""test_serdes_decode_synth.py — the CVDP serial-converter (PISO/SIPO) +
address/range-decoder deterministic solver.

serdes_decode_synth.solve(record) reads the module name from input.prompt/context
(via the bridge; never the OFF-LIMITS harness TOPLEVEL), reads the interface from
the PROMPT's own `### Inputs/Outputs` markdown list / port table (or a reference
docs/*.md, never the golden RTL), PARSES the bit-order/shift-direction (serial
family) or the map/range + out-of-range default (decoder family), and emits
deterministic RTL named per the stated name — else SKIP (None) on ANY unstated
governing fact / non-member / delta task.

POSITIVES (each SOLVES + is FUNCTIONALLY correct against its cocotb model, host-
verified via iverilog when the binary is present):
  * a SIPO 8-bit shift register — MSB-first feed rebuilds the word (shift-left);
  * a PISO shift register — parallel data LOADED then shifted out MSB-first;
  * a SEQUENTIAL (clocked) binary->one-hot decoder, out-of-range -> 0;
  * an address-RANGE -> region decoder with a stated default.

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * a free-running PISO pattern GENERATOR with no parallel data input (piso_8bit);
  * a serializer with a valid/ready handshake FSM (data_serializer delta task);
  * a UART/RS-232 / SPI / sync-serial PROTOCOL controller;
  * an LFSR/PRBS generator, a convolutional/Manchester/8b10b line coder;
  * a multi-module composite (SIPO+ECC / SIPO+CRC);
  * the plain COMBINATIONAL binary->one-hot (already solved elsewhere -> not ours);
  * a priority/first-set-bit encoder; an APB/AXI register-file peripheral;
  * a SIPO whose bit-order/shift-direction is genuinely UNSTATED;
  * a PISO whose bit-order is UNSTATED, or with no LOAD control;
  * a range decoder whose out-of-range DEFAULT is unstated;
  * a "modify the existing RTL" delta/debug/lint task (prior rtl/*.sv in context).

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

import serdes_decode_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_IVERILOG = shutil.which("iverilog") and shutil.which("vvp")

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# record builder (faithful to the CVDP v1.1.0 record shape).
# --------------------------------------------------------------------------- #
def _rec(top, prompt, *, input_context=None):
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
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": input_context or {}},
        "output": {"response": "", "context": {f"rtl/{top}.sv": ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"TOPLEVEL        = {top}\n"),
        }},
    }


def _dataset_record(rid):
    if not _DATASET.exists():
        return None
    for line in _DATASET.read_text().splitlines():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    return None


def _run_iverilog(rtl, tb, name):
    if not _IVERILOG:
        pytest.skip("iverilog/vvp not installed")
    with tempfile.TemporaryDirectory() as d:
        rp, tp, vp = (Path(d) / f"{name}.sv", Path(d) / f"{name}_tb.sv",
                      Path(d) / f"{name}.vvp")
        rp.write_text(rtl)
        tp.write_text(tb)
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vp), str(rp), str(tp)],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed:\n{c.stderr}\nRTL:\n{rtl}"
        r = subprocess.run(["vvp", str(vp)], capture_output=True, text=True)
        return r.stdout


# =========================================================================== #
# fixture prompts (faithful to the CVDP dataset interface-section shape)
# =========================================================================== #
_SIPO_PROMPT = """Design an **8-bit Serial In Parallel Out (SIPO) shift register**
that captures one bit of serial data on each rising edge of the clock and shifts
it into an 8-bit parallel output register (a shift-left register).

### Module Name:
`sipo8`

The most significant bit (MSB) will be shifted out, and new data will shift in
from the LSB.

### Inputs:
- **`clock`** (1-bit): clock; shifts on the positive edge.
- **`serial_in`** (1-bit): serial input bit.

### Output:
- **`parallel_out`** (8-bits, [7:0]): the 8-bit parallel output.
"""

_PISO_PROMPT = """Design a **Parallel In Serial Out (PISO)** shift register that
loads an 8-bit parallel word and shifts it out one bit per clock, **MSB-first**
(most significant bit first).

### Module Name:
`piso8`

### Inputs:
- **`clk`** (1-bit): clock.
- **`rst`** (1-bit): synchronous active-high reset.
- **`load`** (1-bit): when high, capture the parallel data into the register.
- **`data_in`** (8-bits, [7:0]): the 8-bit parallel data input.

### Output:
- **`serial_out`** (1-bit): the serial output, MSB-first.
"""

_SEQ_DEC_PROMPT = """Design a parameterized binary-to-one-hot decoder named
`seqdec` using **sequential logic**, synchronized with a clock.

## Module Parameters
1. **`BINARY_WIDTH`**: Default: `BINARY_WIDTH=5`.
2. **`OUTPUT_WIDTH`**: Default: `OUTPUT_WIDTH=32`.

## Inputs and Outputs
- **Inputs**:
  - `i_binary_in` (`BINARY_WIDTH` bits) — Binary input signal, sampled on the
    rising edge of `i_clk`.
  - `i_clk` (`1-bit`) — Clock (active on the rising edge).
  - `i_rstb` (`1-bit`) — Asynchronous reset (active low).
- **Output**:
  - `o_one_hot_out` (`OUTPUT_WIDTH` bits) — one-hot output; the bit at index
    `i_binary_in` is set on the rising edge; if the index is out of range the
    output is 0; reset clears it.
"""

_RANGE_PROMPT = """Design an address range decoder `addrdec` that maps an address
to a region according to the memory map below.

### Inputs:
- **`addr`** (4-bits, [3:0]): the address.

### Output:
- **`region`** (2-bits, [1:0]): the selected region.

| Range | Region |
|-------|--------|
| 0x0 - 0x3 | Region 1 |
| 0x8 - 0xB | Region 2 |

Any out-of-range / unmapped address defaults to region 0.
"""


# =========================================================================== #
# POSITIVE — structural emits
# =========================================================================== #
def test_sipo_emits_module_named_per_toplevel():
    rtl = S.solve(_rec("sipo8", _SIPO_PROMPT))
    assert rtl is not None
    assert re.search(r"\bmodule\s+sipo8\b", rtl)
    assert "parallel_out" in rtl and "serial_in" in rtl
    assert S.family_of(_rec("sipo8", _SIPO_PROMPT)) == "sipo_serial_converter"


def test_piso_emits_with_load_and_msb_first():
    rtl = S.solve(_rec("piso8", _PISO_PROMPT))
    assert rtl is not None
    assert re.search(r"\bmodule\s+piso8\b", rtl)
    assert "shift_reg <= data_in" in rtl          # load path
    assert "shift_reg[7]" in rtl                   # MSB-first serial bit
    assert S.family_of(_rec("piso8", _PISO_PROMPT)) == "piso_serial_converter"


def test_seq_decoder_emits_clocked_with_reset_and_range_guard():
    rtl = S.solve(_rec("seqdec", _SEQ_DEC_PROMPT))
    assert rtl is not None
    assert "always @(posedge i_clk" in rtl
    assert "negedge i_rstb" in rtl                 # async active-low reset
    assert "i_binary_in < OUTPUT_WIDTH" in rtl     # out-of-range guard
    assert "BINARY_WIDTH" in rtl and "OUTPUT_WIDTH" in rtl  # re-parameterized
    assert S.family_of(_rec("seqdec", _SEQ_DEC_PROMPT)) == "sequential_onehot_decoder"


def test_range_decoder_emits_branches_and_default():
    rtl = S.solve(_rec("addrdec", _RANGE_PROMPT))
    assert rtl is not None
    assert "region = 2'd0;" in rtl                 # stated default first
    assert "addr >= 4'h0 && addr <= 4'h3" in rtl
    assert "addr >= 4'h8 && addr <= 4'hb" in rtl
    assert S.family_of(_rec("addrdec", _RANGE_PROMPT)) == "address_range_decoder"


# =========================================================================== #
# POSITIVE — iverilog functional (gated on the binary)
# =========================================================================== #
def test_sipo_functional():
    rtl = S.solve(_rec("sipo8", _SIPO_PROMPT))
    tb = r"""
module sipo8_tb;
  reg clock=0; reg serial_in; wire [7:0] parallel_out;
  sipo8 dut(.clock(clock), .serial_in(serial_in), .parallel_out(parallel_out));
  integer i,k,fails=0; reg [7:0] data;
  always #5 clock=~clock;
  initial begin
    for (k=0;k<6;k=k+1) begin
      data=$random;
      for (i=0;i<8;i=i+1) begin serial_in=(data>>(7-i))&1'b1; @(negedge clock); end
      if (parallel_out!==data) fails=fails+1;
    end
    if(fails==0) $display("OK"); else $display("BAD=%0d",fails); $finish;
  end
endmodule
"""
    out = _run_iverilog(rtl, tb, "sipo8")
    assert "OK" in out, out


def test_piso_functional():
    rtl = S.solve(_rec("piso8", _PISO_PROMPT))
    tb = r"""
module piso8_tb;
  reg clk=0,rst,load; reg [7:0] data_in; wire serial_out;
  piso8 dut(.clk(clk),.rst(rst),.load(load),.data_in(data_in),.serial_out(serial_out));
  integer i,k,fails=0; reg [7:0] data,coll;
  always #5 clk=~clk;
  initial begin
    rst=1; load=0; data_in=0; @(negedge clk); rst=0;
    for (k=0;k<5;k=k+1) begin
      data=$random; data_in=data; load=1; @(negedge clk); load=0; coll=0;
      for (i=0;i<8;i=i+1) begin coll={coll[6:0],serial_out}; @(negedge clk); end
      if (coll!==data) fails=fails+1;
    end
    if(fails==0) $display("OK"); else $display("BAD=%0d",fails); $finish;
  end
endmodule
"""
    out = _run_iverilog(rtl, tb, "piso8")
    assert "OK" in out, out


def test_seq_decoder_functional():
    rtl = S.solve(_rec("seqdec", _SEQ_DEC_PROMPT))
    tb = r"""
module seqdec_tb;
  reg i_clk=0; reg i_rstb; reg [4:0] i_binary_in; wire [31:0] o_one_hot_out;
  seqdec dut(.i_clk(i_clk),.i_rstb(i_rstb),.i_binary_in(i_binary_in),.o_one_hot_out(o_one_hot_out));
  integer v,fails=0;
  always #5 i_clk=~i_clk;
  initial begin
    i_rstb=0; i_binary_in=0; @(negedge i_clk); i_rstb=1; @(posedge i_clk);
    @(negedge i_clk); i_binary_in=0; @(negedge i_clk);
    if (o_one_hot_out!==(1<<0)) fails=fails+1;
    for (v=1;v<16;v=v+1) begin
      i_binary_in=v; @(negedge i_clk);
      if (o_one_hot_out!==(1<<v)) fails=fails+1;
    end
    i_rstb=0; @(negedge i_clk);
    if (o_one_hot_out!==0) fails=fails+1;
    if(fails==0) $display("OK"); else $display("BAD=%0d",fails); $finish;
  end
endmodule
"""
    out = _run_iverilog(rtl, tb, "seqdec")
    assert "OK" in out, out


def test_range_decoder_functional():
    rtl = S.solve(_rec("addrdec", _RANGE_PROMPT))
    tb = r"""
module addrdec_tb;
  reg [3:0] addr; wire [1:0] region; integer a,fails=0; reg [1:0] exp;
  addrdec dut(.addr(addr),.region(region));
  initial begin
    for (a=0;a<16;a=a+1) begin
      addr=a; #1;
      exp=(a<=3)?2'd1:((a>=8&&a<=11)?2'd2:2'd0);
      if (region!==exp) fails=fails+1;
    end
    if(fails==0) $display("OK"); else $display("BAD=%0d",fails); $finish;
  end
endmodule
"""
    out = _run_iverilog(rtl, tb, "addrdec")
    assert "OK" in out, out


# =========================================================================== #
# §4.05 / NO-CHEAT NEGATIVES — each MUST SKIP (None)
# =========================================================================== #
def test_skip_sipo_unstated_bit_order():
    # a SIPO with NO stated shift direction / bit-order -> SKIP (never guess).
    p = """Design an 8-bit Serial In Parallel Out (SIPO) shift register `s8`.
### Inputs:
- **`clock`** (1-bit): clock.
- **`serial_in`** (1-bit): serial input.
### Output:
- **`parallel_out`** (8-bits, [7:0]): parallel output."""
    assert S.solve(_rec("s8", p)) is None


def test_skip_piso_no_parallel_data_input():
    # a free-running PISO pattern GENERATOR (no parallel data input bus) -> SKIP.
    p = """Design an 8-bit PISO that generates an incrementing pattern, MSB-first.
### Inputs:
- **`clk`** (1-bit): clock.
- **`rst`** (1-bit): asynchronous active-low reset.
### Output:
- **`serial_out`** (1-bit): the serial output."""
    assert S.solve(_rec("gen8", p)) is None


def test_skip_piso_unstated_bit_order():
    p = _PISO_PROMPT.replace("**MSB-first**\n(most significant bit first)", "out")
    p = re.sub(r",?\s*MSB-first", "", p)
    p = p.replace("**MSB-first**", "").replace("most significant bit first", "")
    assert "MSB" not in p
    assert S.solve(_rec("piso8", p)) is None


def test_skip_piso_no_load_control():
    p = re.sub(r"- \*\*`load`\*\*.*\n", "", _PISO_PROMPT)
    assert "`load`" not in p                       # the load PORT bullet is gone
    assert S.solve(_rec("piso8", p)) is None        # no load control -> SKIP


def test_skip_uart_protocol():
    p = """Design a UART transmitter `uart_tx` with start bit, 8 data bits LSB-first,
and a stop bit, driven by a baud generator.
### Inputs:
- **`clk`** (1-bit): clock.
- **`data_in`** (8-bits, [7:0]): the byte to transmit.
- **`load`** (1-bit): load.
### Output:
- **`serial_out`** (1-bit): UART serial line."""
    assert S.solve(_rec("uart_tx", p)) is None


def test_skip_spi_and_lfsr_and_composite():
    spi = """Design an SPI master `spi_m` that shifts MSB-first on MOSI per SPI mode 0.
### Inputs:
- **`clk`** (1-bit): clock.
- **`data_in`** (8-bits, [7:0]): tx data.
- **`load`** (1-bit): load.
### Output:
- **`serial_out`** (1-bit): MOSI."""
    assert S.solve(_rec("spi_m", spi)) is None
    lfsr = """Design an 8-bit LFSR `lf8` (serial output) MSB-first.
### Inputs:
- **`clk`** (1-bit): clock.
- **`load`** (1-bit): load.
- **`data_in`** (8-bits, [7:0]): seed.
### Output:
- **`serial_out`** (1-bit): output bit."""
    assert S.solve(_rec("lf8", lfsr)) is None


def test_skip_combinational_onehot_decoder():
    # the plain COMBINATIONAL binary->one-hot is solved elsewhere -> NOT ours.
    p = """Design a parameterized binary to one-hot decoder `cdec` (purely
combinational, no clock).
## Module Parameters
- **`BINARY_WIDTH`**: Default: `BINARY_WIDTH=5`.
- **`OUTPUT_WIDTH`**: Default: `OUTPUT_WIDTH=32`.
## Inputs and Outputs
- **Input**: `binary_in` (`BINARY_WIDTH` bits) — binary input.
- **Output**: `one_hot_out` (`OUTPUT_WIDTH` bits) — one-hot; out-of-range -> 0."""
    assert S.solve(_rec("cdec", p)) is None


def test_skip_range_decoder_unstated_default():
    p = re.sub(r"Any out-of-range.*region 0\.", "", _RANGE_PROMPT)
    assert "default" not in p.lower()
    assert S.solve(_rec("addrdec", p)) is None


def test_skip_delta_task_prior_rtl():
    rtl_ctx = {"rtl/piso8.sv": "module piso8(input clk); endmodule"}
    assert S.solve(_rec("piso8", _PISO_PROMPT, input_context=rtl_ctx)) is None


def test_docs_md_context_is_not_a_delta_task():
    # a docs/*.md reference (not prior RTL) must NOT trip the delta-task SKIP.
    docs_ctx = {"docs/Documentation.md": "# Reference doc\nA shift-left SIPO register."}
    assert S.solve(_rec("sipo8", _SIPO_PROMPT, input_context=docs_ctx)) is not None


# =========================================================================== #
# CHIP-AGNOSTIC — same spec under three TOPLEVELs solves identically (renamed)
# =========================================================================== #
@pytest.mark.parametrize("prompt,top_field", [
    (_SIPO_PROMPT, "sipo8"),
    (_SEQ_DEC_PROMPT, "seqdec"),
])
def test_chip_agnostic_rename(prompt, top_field):
    a = S.solve(_rec("alpha_top", prompt.replace(top_field, "alpha_top")))
    b = S.solve(_rec("beta_top", prompt.replace(top_field, "beta_top")))
    c = S.solve(_rec("gamma_chip", prompt.replace(top_field, "gamma_chip")))
    assert a and b and c
    assert re.search(r"\bmodule\s+alpha_top\b", a)
    assert re.search(r"\bmodule\s+beta_top\b", b)
    assert re.search(r"\bmodule\s+gamma_chip\b", c)
    # body identical modulo the module name.
    assert a.replace("alpha_top", "X") == b.replace("beta_top", "X")
    assert b.replace("beta_top", "X") == c.replace("gamma_chip", "X")


def test_no_design_name_keys_in_source():
    # the solver must never key on a specific design name (chip-AGNOSTIC).
    src = (PROG / "serdes_decode_synth.py").read_text()
    for token in ("sipo_8bit", "piso_8bit", "serial_in_parallel_out_8bit",
                  "binary_to_one_hot_decoder_sequential", "cvdp_copilot"):
        assert token not in src, f"design-name key leaked: {token}"


# =========================================================================== #
# REAL DATASET records (used when the CVDP jsonl is present)
# =========================================================================== #
@pytest.mark.parametrize("rid,family", [
    ("cvdp_copilot_serial_in_parallel_out_0004", "sipo_serial_converter"),
    ("cvdp_copilot_sequencial_binary_to_one_hot_decoder_0001",
     "sequential_onehot_decoder"),
])
def test_real_dataset_positive(rid, family):
    rec = _dataset_record(rid)
    if rec is None:
        pytest.skip("CVDP dataset not present on this host")
    rtl = S.solve(rec)
    assert rtl is not None, f"{rid} should SOLVE"
    top = S._toplevel(rec)
    assert re.search(rf"\bmodule\s+{re.escape(top)}\b", rtl)
    assert S.family_of(rec) == family


@pytest.mark.parametrize("rid", [
    "cvdp_copilot_piso_0001",                       # pattern generator, no data_in
    "cvdp_copilot_data_serializer_0001",            # handshake FSM + delta
    "cvdp_copilot_serial_in_parallel_out_0011",     # SIPO+ECC composite + delta
    "cvdp_copilot_serial_in_parallel_out_0014",     # SIPO+ECC+CRC composite + delta
    "cvdp_copilot_rs_232_0001",                     # RS-232 UART
    "cvdp_copilot_simple_spi_0001",                 # SPI FSM
    "cvdp_copilot_sync_serial_communication_0001",  # sync-serial protocol
    "cvdp_copilot_lfsr_0007",                       # LFSR generator + delta
    "cvdp_copilot_binary_to_one_hot_decoder_0001",  # combinational (solved elsewhere)
    "cvdp_copilot_one_hot_address_0001",            # lint/debug delta
    "cvdp_copilot_decode_firstbit_0001",            # priority encoder
    "cvdp_copilot_unpacker_one_hot_0001",           # composite unpacker
    "cvdp_copilot_fan_controller_0001",             # APB + PWM composite
    "cvdp_copilot_axi_register_0001",               # AXI register-file
    "cvdp_copilot_64b66b_decoder_0001",             # line decoder
])
def test_real_dataset_skip(rid):
    rec = _dataset_record(rid)
    if rec is None:
        pytest.skip("CVDP dataset not present on this host")
    assert S.solve(rec) is None, f"{rid} should SKIP (§4.05/non-member)"


def test_real_dataset_no_overlap_and_count():
    # on the real dataset the solver SOLVES exactly the 2 members and 0 others;
    # and never collides with what the registry bridge already solves.
    if not _DATASET.exists():
        pytest.skip("CVDP dataset not present on this host")
    recs = [json.loads(l) for l in _DATASET.read_text().splitlines()]
    solved = [r["id"] for r in recs if S.solve(r)]
    assert set(solved) == {
        "cvdp_copilot_serial_in_parallel_out_0004",
        "cvdp_copilot_sequencial_binary_to_one_hot_decoder_0001",
    }, solved
    try:
        import cvdp_atomic_bridge as B
        import copy
        bridge = {r["id"] for r in recs if B.solve(copy.deepcopy(r))}
        assert not (set(solved) & bridge), "must be net-new vs the bridge"
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
