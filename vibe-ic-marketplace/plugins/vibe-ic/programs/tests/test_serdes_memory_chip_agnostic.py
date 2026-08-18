"""§4.05 / chip-agnostic remediation for serdes_width_synth + memory_array_synth.

These solvers previously hard-coded packing/serialization DIRECTION and gated
recognition on the dataset's exact RTLLM PORT-NAME SETS. This suite pins the
remediation:

  H5  serdes width packing order is PARSED ("first word in lower/upper byte"),
      not fixed first-in-high. A "lower byte" prompt emits lower-first.
  H6  serializer bit-order is PARSED (MSB-first vs LSB-first), not presence-gated.
      An "LSB first" prompt emits LSB-first; UNSTATED -> SKIP.
  M1  RAM array depth comes from the STATED depth (not 2**WIDTH); LIFO stack
      direction / SP-reset, and instr_reg field-slice + fetch encoding are PARSED;
      an unstated field SKIPs.
  M2  recognition keys on STRUCTURE (operation + port directions/widths/roles),
      NOT on the exact RTLLM name set. Renaming ports to generic equivalents
      (push/pop/din/dout) must NOT change whether a shape fires.

Plus a VE-0-fire sweep: these NEW canonicals must fire 0 times on either
VerilogEval corpus.
"""
import glob
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import serdes_width_synth as S  # noqa: E402
import memory_array_synth as M  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


# ===================================================================== H6 serdes
_PARALLEL2SERIAL_MSB = """
Implement a module for parallel-to-serial conversion, where every four input bits
are converted to a serial one bit output (from MSB to LSB). valid_out is set to 1
to indicate the availability of valid serial output.

Module name:
    p2s

Input ports:
    clk: Clock signal.
    rst_n: Reset signal (active low).
    d: 4-bit parallel data input.

Output ports:
    valid_out: Valid signal.
    dout: Serial output.
"""

# Near-miss (b): identical structure but the bit-order is LSB-first.
_PARALLEL2SERIAL_LSB = _PARALLEL2SERIAL_MSB.replace(
    "(from MSB to LSB)", "(from LSB to MSB)")

# Unstated bit-order -> must SKIP.
_PARALLEL2SERIAL_UNSTATED = _PARALLEL2SERIAL_MSB.replace(
    " (from MSB to LSB)", "")


def test_h6_parallel2serial_msb_first():
    rtl = S.synth(_PARALLEL2SERIAL_MSB)
    assert rtl is not None
    # MSB-first: serial tap is the high bit; shift rotates MSB into the stream.
    assert "assign dout = data[3];" in rtl
    assert "{data[2:0], data[3]}" in rtl


def test_h6_parallel2serial_lsb_first_emits_lsb():
    """NEAR-MISS NEGATIVE (b): 'LSB first' serializer must emit LSB-first RTL."""
    rtl = S.synth(_PARALLEL2SERIAL_LSB)
    assert rtl is not None
    assert "assign dout = data[0];" in rtl       # low-bit tap, NOT data[3]
    assert "data[3]" not in rtl.split("assign dout")[1].split("\n")[0]
    assert "{data[0], data[3:1]}" in rtl


def test_h6_serializer_unstated_bit_order_skips():
    assert S.synth(_PARALLEL2SERIAL_UNSTATED) is None


# ===================================================================== H5 serdes
_WIDTH_FIRST_UPPER = """
Implement a data width conversion circuit that converts 8-bit data input to 16-bit
data output. The first arriving 8-bit data should be placed in the higher 8 bits of
the 16-bit data output.

Module name:
    w8to16

Input ports:
    clk: Clock signal.
    rst_n: Active-low reset.
    valid_in: Input valid.
    data_in: 8-bit input data.

Output ports:
    valid_out: Output valid.
    data_out: 16-bit output data.
"""

# Near-miss (a): first word in the LOWER byte.
_WIDTH_FIRST_LOWER = _WIDTH_FIRST_UPPER.replace(
    "placed in the higher 8 bits", "placed in the lower 8 bits")

# Unstated packing order -> must SKIP.
_WIDTH_UNSTATED = _WIDTH_FIRST_UPPER.replace(
    " The first arriving 8-bit data should be placed in the higher 8 bits of\nthe 16-bit data output.",
    "")


def test_h5_width_first_upper():
    rtl = S.synth(_WIDTH_FIRST_UPPER)
    assert rtl is not None
    # first word locked, second appended below -> {data_lock, data_in}
    assert "{data_lock, data_in}" in rtl


def test_h5_width_first_lower_emits_lower_first():
    """NEAR-MISS NEGATIVE (a): 'first word in lower byte' emits lower-first."""
    rtl = S.synth(_WIDTH_FIRST_LOWER)
    assert rtl is not None
    assert "{data_in, data_lock}" in rtl        # reversed order
    assert "{data_lock, data_in}" not in rtl


def test_h5_width_unstated_packing_skips():
    assert S.synth(_WIDTH_UNSTATED) is None


# ===================================================================== M2 serdes
# Renaming the serial-input ports to generic names must NOT change whether it fires.
_SERIAL2PARALLEL_RENAMED = """
Implement a serial-to-parallel conversion circuit. The serial input values are
sequentially placed from the most significant bit to the least significant bit.

Module name:
    s2p

Input ports:
    clk: Clock signal.
    rst_n: Reset (active low).
    sin: Serial input data.
    sin_vld: Validity signal for input data.

Output ports:
    pout: Parallel output data (8 bits wide).
    pout_vld: Validity signal for the output data.
"""


def test_m2_serdes_recognition_is_structural_not_name_keyed():
    rtl = S.synth(_SERIAL2PARALLEL_RENAMED)
    assert rtl is not None
    # fires on STRUCTURE; emitted RTL binds by the actual (renamed) port names.
    assert "sin" in rtl and "pout" in rtl and "sin_vld" in rtl
    assert "din_serial" not in rtl  # no leaked RTLLM-specific name


# ===================================================================== M1 RAM depth
_RAM_DEPTH8 = """
Implement a dual-port RAM with a depth of 8 and a bit width of 6 bits. When the
read_en signal is 1, the read_data of the corresponding position is read through
the read_addr signal and output via a synchronous read_data register on posedge.
When the write_en signal is 1, data is written through write_addr and write_data.

Module name:
    RAM

Input ports:
    clk: Clock signal.
    rst_n: Active-low reset.
    write_en: Write enable.
    write_addr: Address for the write operation.
    write_data: Data to be written.
    read_en: Read enable.
    read_addr: Address for the read operation.

Output ports:
    read_data: Data read from the RAM.

Parameter:
    WIDTH = 6;
    DEPTH = 8;
"""


def test_m1_ram_uses_stated_depth_not_2pow_width():
    """NEAR-MISS NEGATIVE (d): a RAM whose depth is STATED uses that depth (8),
    not 2**WIDTH (=64)."""
    rtl = M.synth(_RAM_DEPTH8)
    assert rtl is not None
    assert "RAM [0:7]" in rtl              # depth 8 -> indices 0..7
    assert "2**WIDTH" not in rtl           # the hard-coded form is gone
    assert "[0:63]" not in rtl             # NOT 2**6


# ===================================================================== M2 LIFO rename
_LIFO_RTLLM = """
A Last-In-First-Out (LIFO) buffer. This 4-bit wide buffer can hold up to 4 entries,
allowing push and pop operations controlled by read/write (RW) signals. On reset
the stack pointer is set to 4 (indicating an empty buffer). If RW is low (write
operation) and the buffer is not full, data from dataIn is pushed and the stack
pointer is decremented. If RW is high (read operation) and not empty, data is
popped and the stack pointer is incremented.

Module name:
    LIFObuffer

Input ports:
    dataIn [3:0]: 4-bit input data.
    RW: Read/Write control signal.
    EN: Enable signal.
    Rst: Active high reset.
    Clk: Clock signal.

Output ports:
    EMPTY: Empty flag.
    FULL: Full flag.
    dataOut [3:0]: 4-bit output data.
"""

# Same STACK with ports renamed to generic equivalents (din/dout/...).
_LIFO_RENAMED = """
A Last-In-First-Out (LIFO) buffer. This 4-bit wide buffer can hold up to 4 entries,
allowing push and pop operations controlled by read/write (rwn) signals. On reset
the stack pointer is set to 4 (indicating an empty buffer). If write operation and
the buffer is not full, data from din is pushed and the stack pointer is
decremented. If read operation and not empty, data is popped and the stack pointer
is incremented.

Module name:
    my_stack

Input ports:
    din [3:0]: 4-bit input data.
    rwn: Read/Write control signal.
    enable: Enable signal.
    reset: Active high reset.
    clock: Clock signal.

Output ports:
    empty: Empty flag.
    full: Full flag.
    dout [3:0]: 4-bit output data.
"""


def test_m2_lifo_fires_on_rtllm_names():
    assert M.synth(_LIFO_RTLLM) is not None


def test_m2_lifo_rename_still_fires_chip_agnostic():
    """NEAR-MISS NEGATIVE (c): renaming LIFO ports to push/pop/din/dout still
    fires — recognition is STRUCTURAL, not keyed on {dataIn,RW,EN,Rst,Clk}."""
    rtl = M.synth(_LIFO_RENAMED)
    assert rtl is not None
    # binds by the actual renamed names; no leaked RTLLM-specific name.
    assert "din" in rtl and "dout" in rtl and "rwn" in rtl
    assert "dataIn" not in rtl


def test_m1_lifo_unstated_direction_skips():
    no_dir = _LIFO_RTLLM.replace(
        "and the stack\npointer is decremented", "").replace(
        "and the stack pointer is incremented", "")
    # removing both direction statements -> push/pop direction unstated -> SKIP
    assert M.synth(no_dir) is None


# ===================================================================== M1 instr_reg
_INSTR_REG = """
An instruction register module. Based on the fetch signal: If fetch is 2'b01, the
instruction is fetched from the data input into ins_p1. If fetch is 2'b10, the
instruction is fetched from the data input into ins_p2.

Module name:
    instr_reg

Input ports:
    clk: Clock signal.
    rst: Active low reset.
    fetch [1:0]: Control signal (1 for register, 2 for RAM/ROM).
    data [7:0]: 8-bit data input.

Output ports:
    ins [2:0]: High 3 bits of the instruction.
    ad1 [4:0]: Low 5 bits of the instruction.
    ad2 [7:0]: The full 8-bit data.
"""


def test_m1_instr_reg_parses_field_layout_and_fetch_encoding():
    rtl = M.synth(_INSTR_REG)
    assert rtl is not None
    assert "2'b01: ins_p1 <= data;" in rtl    # fetch encoding PARSED, not swapped
    assert "2'b10: ins_p2 <= data;" in rtl
    assert "assign ins = ins_p1[7:5];" in rtl  # High 3 bits
    assert "assign ad1 = ins_p1[4:0];" in rtl  # Low 5 bits


def test_m1_instr_reg_unstated_field_layout_skips():
    no_slice = _INSTR_REG.replace("High 3 bits of the instruction",
                                  "part of the instruction").replace(
        "Low 5 bits of the instruction", "another part of the instruction")
    assert M.synth(no_slice) is None


# ===================================================================== VE 0-fire
_VE_DIRS = [
    str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")),
    str(corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")),
]


@pytest.mark.skipif(
    not any(os.path.isdir(d) for d in _VE_DIRS),
    reason="VerilogEval corpora not present on this host; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_ve_zero_fire_both_corpora():
    """Both NEW canonicals must fire 0 times on either VerilogEval corpus."""
    fired = []
    for d in _VE_DIRS:
        if not os.path.isdir(d):
            continue
        for p in sorted(glob.glob(os.path.join(d, "*_prompt.txt"))):
            text = open(p, errors="replace").read()
            ifc = p.replace("_prompt.txt", "_ifc.txt")
            if os.path.exists(ifc):
                text = open(ifc, errors="replace").read() + "\n" + text
            if S.synth(text) is not None:
                fired.append(("serdes", os.path.basename(p)))
            if M.synth(text) is not None:
                fired.append(("memory", os.path.basename(p)))
    assert fired == [], f"unexpected VE fires: {fired}"
