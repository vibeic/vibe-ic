"""v1.1.85 — arithmetic_synth PARSES the stated completion latency / pipeline depth.

The sequential-multiplier (mult_seq_done / mult_seq_rdy) and pipelined
(mult_pipe_en / mult_pipe_plain / adder_pipe) shapes are no longer blanket-deferred:
recognize() now PARSES the cycle/stage count straight from the prose and the shape
FIRES when the count is stated, but stays an honest SKIP when it is genuinely unstated
(an indefinite 'several'/'multiple' quantifier). §4.05 parse-or-SKIP — never a
width-derived or constant guess.

  PARSE-and-fire:  multi_16bit (i<17, i==16->done=1, i==17->done=0),
                   multi_booth_8bit (ctr<16, ctr reaches 16 -> rdy=1; active-high rst),
                   multi_pipe_4bit (two levels of registers -> 2 stages).
  honest SKIP:     multi_pipe_8bit (depth unstated), adder_pipe_64bit ('several').

Host-verify is GATED on iverilog + the RTLLM dataset; the parse/SKIP assertions and
the near-miss NEGATIVE test run anywhere.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import arithmetic_synth as A  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_RT = corpus_path("_extbench/RTLLM")


# --------------------------------------------------------------------------- #
# NEAR-MISS NEGATIVE: a seq-multiplier prompt with NO stated cycle/stage count
# must SKIP (return None) — the latency is unstated, so emitting it would mean
# guessing the completion cycle. §4.05.
# --------------------------------------------------------------------------- #
_SEQ_NO_CYCLE = """
Please act as a professional verilog designer.

Implement a sequential unsigned multiplier that uses shift and accumulate
operations to produce the product (yout). It includes a clock (clk), an
active-low reset (rst_n), a start signal (start) and a done flag (done).

Module name:
    seqmul_unstated

Input ports:
    clk: Chip clock signal.
    rst_n: Active-low reset signal.
    start: enable signal to initiate the multiplication.
    ain: multiplicand, 16 bits.
    bin: multiplier, 16 bits.

Output ports:
    yout: product output, 32 bits.
    done: completion flag.

Implementation:
The module repeatedly shifts and accumulates over several clock cycles, then
raises the done flag once the multiplication has completed.
"""


def test_near_miss_seq_multiplier_no_cycle_skips():
    spec = A.recognize(_SEQ_NO_CYCLE)
    # the shape is recognized as a start/done sequential multiplier ...
    assert spec is not None and spec["op"] == "mult_seq_done"
    # ... but the completion cycle is NOT stated -> flagged unparsed -> SKIP.
    assert spec.get("raise_at") is None
    assert spec.get("_latency_unparsed") is True
    assert A.synth(_SEQ_NO_CYCLE, "seqmul_unstated") is None


def test_near_miss_adder_pipe_several_stages_skips():
    # 'several' is an indefinite quantifier, not a stated stage count -> SKIP.
    pipe = """
Implement a 64-bit ripple carry adder, which includes several registers to
enable the pipeline stages.
Module name:
    adder_pipe_unstated
Input ports:
    clk: Clock input
    rst_n: Active low reset signal
    i_en: Enable signal for addition operation
    adda: 64-bit input operand A
    addb: 64-bit input operand B
Output ports:
    result: 65-bit output representing the sum of adda and addb.
    o_en: Output enable signal.
"""
    spec = A.recognize(pipe)
    assert spec is not None and spec["op"] == "adder_pipe"
    assert spec.get("stages") is None
    assert spec.get("_latency_unparsed") is True
    assert A.synth(pipe, "adder_pipe_unstated") is None


# --------------------------------------------------------------------------- #
# PARSE-and-fire: the stated cycle/stage counts are read from the real prompts.
# --------------------------------------------------------------------------- #
def _read(sub):
    p = _RT / "Arithmetic" / sub / "design_description.txt"
    if not p.is_file():
        pytest.skip("RTLLM dataset not present")
    return p.read_text()


def test_multi_16bit_parses_done_cycles():
    spec = A.recognize(_read("Multiplier/multi_16bit"))
    assert spec["op"] == "mult_seq_done"
    assert spec["bound"] == 17       # 'i is less than 17'
    assert spec["raise_at"] == 16    # 'i==16 -> done=1'
    assert spec["clear_at"] == 17    # 'i==17 -> done=0'
    assert not spec.get("_latency_unparsed")


def test_multi_booth_parses_count_and_active_high_reset():
    spec = A.recognize(_read("Multiplier/multi_booth_8bit"))
    assert spec["op"] == "mult_seq_rdy"
    assert spec["raise_at"] == 16    # 'ctr reaches 16 -> rdy=1'
    assert spec["rst_active_high"] is True
    assert not spec.get("_latency_unparsed")


def test_multi_pipe_4bit_parses_two_levels():
    spec = A.recognize(_read("Multiplier/multi_pipe_4bit"))
    assert spec["op"] == "mult_pipe_plain"
    assert spec["stages"] == 2       # 'two levels of registers'
    assert not spec.get("_latency_unparsed")


def test_multi_pipe_8bit_unstated_depth_skips():
    spec = A.recognize(_read("Multiplier/multi_pipe_8bit"))
    assert spec["op"] == "mult_pipe_en"
    assert spec.get("stages") is None
    assert spec.get("_latency_unparsed") is True


def test_adder_pipe_64bit_unstated_depth_skips():
    spec = A.recognize(_read("Adder/adder_pipe_64bit"))
    assert spec["op"] == "adder_pipe"
    assert spec.get("stages") is None
    assert spec.get("_latency_unparsed") is True


# --------------------------------------------------------------------------- #
# HOST-VERIFY the parsed-latency shapes against the RTLLM testbench.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _HAVE_IV, reason="iverilog not installed")
@pytest.mark.parametrize("sub,top", [
    ("Multiplier/multi_16bit", "multi_16bit"),
    ("Multiplier/multi_booth_8bit", "multi_booth_8bit"),
    ("Multiplier/multi_pipe_4bit", "multi_pipe_4bit"),
])
def test_host_pass_parsed_latency(sub, top):
    d = _RT / "Arithmetic" / sub
    if not (d / "design_description.txt").is_file():
        pytest.skip("RTLLM dataset not present")
    rtl = A.synth((d / "design_description.txt").read_text(), top)
    assert rtl is not None, "parsed-latency shape must FIRE"
    with tempfile.TemporaryDirectory() as td:
        dut = Path(td) / f"{top}.v"
        dut.write_text(rtl)
        vvp = Path(td) / "a.vvp"
        ce = subprocess.run(
            ["iverilog", "-g2012", "-o", str(vvp), "testbench.v", str(dut)],
            capture_output=True, text=True, cwd=str(d))
        assert ce.returncode == 0, ce.stderr[:400]
        r = _pr.run(["vvp", str(vvp)], capture_output=True, text=True,
                           cwd=str(d))
        assert "your design passed" in (r.stdout + r.stderr).lower()
