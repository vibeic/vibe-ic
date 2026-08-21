"""v1.1.78 — the PROGRAM half of the AI-extracts / program-emits hybrid for
behavioral-prose Moore FSMs. The AI produces a COMPLETE canonical FSM table; this
program is the §4.05 GATE — it validates the table is complete + matches the real
interface, then deterministically EMITS the RTL (or SKIPs). These tests pin the
gate (negatives MUST SKIP) and a host-verified positive (the real Prob127_lemmings1
shape, AI-extractable, emitted 0-mismatch).
"""
import shutil
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))
import moore_fsm_table_emit as M           # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

# the real Prob127_lemmings1 interface (bullet form, verbatim shape)
_LEM1_PROMPT = """\
 - input  clk
 - input  areset
 - input  bump_left
 - input  bump_right
 - output walk_left
 - output walk_right

Moore state machine, two states, areset positive edge triggered asynchronous
resetting to walk left.
"""

_LEM1_TABLE = """\
STATES: LEFT RIGHT
INPUTS: bump_left bump_right
OUTPUTS: walk_left walk_right
RESET: LEFT async active_high
TRANS: LEFT 00 -> LEFT
TRANS: LEFT 01 -> LEFT
TRANS: LEFT 10 -> RIGHT
TRANS: LEFT 11 -> RIGHT
TRANS: RIGHT 00 -> RIGHT
TRANS: RIGHT 01 -> LEFT
TRANS: RIGHT 10 -> RIGHT
TRANS: RIGHT 11 -> LEFT
OUT: LEFT walk_left=1 walk_right=0
OUT: RIGHT walk_left=0 walk_right=1
"""


def test_complete_table_emits():
    rtl = M.synth(_LEM1_PROMPT, _LEM1_TABLE, "TopModule")
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "input bump_left" in rtl and "output reg walk_left" in rtl
    assert "posedge clk or posedge areset" in rtl       # async active-high
    assert "if (areset) state <= S_LEFT;" in rtl
    # both Moore outputs decoded from state
    assert "S_LEFT: walk_left = 1'b1;" in rtl and "S_RIGHT: walk_right = 1'b1;" in rtl


def _drop(table, line_substr):
    return "\n".join(l for l in table.splitlines() if line_substr not in l) + "\n"


def test_skip_incomplete_transitions():
    # drop one input-combo row -> not every state x combo covered -> SKIP
    bad = _drop(_LEM1_TABLE, "TRANS: LEFT 11")
    assert M.synth(_LEM1_PROMPT, bad, "TopModule") is None


def test_skip_unknown_next_state():
    bad = _LEM1_TABLE.replace("TRANS: LEFT 10 -> RIGHT", "TRANS: LEFT 10 -> NOWHERE")
    assert M.synth(_LEM1_PROMPT, bad, "TopModule") is None


def test_skip_hallucinated_input_port():
    # the table names an input that is NOT a declared port -> SKIP (no hallucination)
    bad = _LEM1_TABLE.replace("INPUTS: bump_left bump_right",
                              "INPUTS: bump_left ghost_input")
    assert M.synth(_LEM1_PROMPT, bad, "TopModule") is None


def test_skip_output_set_mismatch():
    # the table's OUTPUTS must equal the declared 1-bit outputs exactly
    bad = _LEM1_TABLE.replace("OUTPUTS: walk_left walk_right", "OUTPUTS: walk_left")
    assert M.synth(_LEM1_PROMPT, bad, "TopModule") is None


def test_skip_missing_output_def_for_a_state():
    bad = _drop(_LEM1_TABLE, "OUT: RIGHT")
    assert M.synth(_LEM1_PROMPT, bad, "TopModule") is None


def test_skip_unknown_reset_state():
    bad = _LEM1_TABLE.replace("RESET: LEFT async active_high",
                              "RESET: MIDDLE async active_high")
    assert M.synth(_LEM1_PROMPT, bad, "TopModule") is None


def test_skip_malformed_table():
    assert M.synth(_LEM1_PROMPT, "this is not a table\n", "TopModule") is None
    assert M.synth(_LEM1_PROMPT, "", "TopModule") is None


# a FSM that branches on ONE bit of a wide input bus (PS/2 in[3]) — the bit-select
# extension. The interface declares `in (8 bits)`; the table keys on in[3].
_PS2_PROMPT = """\
 - input  clk
 - input  reset
 - input  in (8 bits)
 - output done

PS/2 byte-boundary FSM. Reset should be active high synchronous.
"""

_PS2_TABLE = """\
STATES: BYTE1 BYTE2 BYTE3 DONE
INPUTS: in[3]
OUTPUTS: done
RESET: BYTE1 sync active_high
TRANS: BYTE1 0 -> BYTE1
TRANS: BYTE1 1 -> BYTE2
TRANS: BYTE2 0 -> BYTE3
TRANS: BYTE2 1 -> BYTE3
TRANS: BYTE3 0 -> DONE
TRANS: BYTE3 1 -> DONE
TRANS: DONE 0 -> BYTE1
TRANS: DONE 1 -> BYTE2
OUT: BYTE1 done=0
OUT: BYTE2 done=0
OUT: BYTE3 done=0
OUT: DONE done=1
"""


def test_bus_bitselect_input_emits():
    rtl = M.synth(_PS2_PROMPT, _PS2_TABLE, "TopModule")
    assert rtl is not None
    assert "input [7:0] in" in rtl                  # the bus declared once at full width
    assert "case ({in[3]})" in rtl                  # case keys on the bit-select
    assert "S_DONE: done = 1'b1;" in rtl


def test_skip_bitselect_out_of_range():
    # in[9] is out of range for an 8-bit `in` -> SKIP (no hallucination)
    bad = _PS2_TABLE.replace("INPUTS: in[3]", "INPUTS: in[9]") \
                    .replace("TRANS: BYTE1 0", "TRANS: BYTE1 0")  # table shape unchanged
    assert M.synth(_PS2_PROMPT, bad, "TopModule") is None


def test_host_score_ps2_bitselect_hybrid():
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        import pytest
        pytest.skip("iverilog/vvp absent")
    DS = require_corpus("_extbench/verilog-eval/dataset_spec-to-rtl")
    pr, ref, tb = (DS / "Prob128_fsm_ps2_prompt.txt",
                   DS / "Prob128_fsm_ps2_ref.sv", DS / "Prob128_fsm_ps2_test.sv")
    if not (pr.exists() and ref.exists() and tb.exists()):
        import pytest
        pytest.skip("dataset not present")
    rtl = M.synth(pr.read_text(errors="replace"), _PS2_TABLE, "TopModule")
    assert rtl is not None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(rtl)
        vvp = Path(d) / "a.vvp"
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(tb)],
                           capture_output=True, text=True)
        assert c.returncode == 0, c.stderr
        r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, cwd=d)
        assert "mismatched samples is 0" in r.stdout, r.stdout[-300:]


def test_host_score_lemmings1_hybrid():
    # the load-bearing proof: the AI-extractable table for the REAL Prob127 emits
    # RTL that host-scores 0-mismatch against the official ref+test.
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        import pytest
        pytest.skip("iverilog/vvp absent")
    DS = require_corpus("_extbench/verilog-eval/dataset_spec-to-rtl")
    pr, ref, tb = (DS / "Prob127_lemmings1_prompt.txt",
                   DS / "Prob127_lemmings1_ref.sv", DS / "Prob127_lemmings1_test.sv")
    if not (pr.exists() and ref.exists() and tb.exists()):
        import pytest
        pytest.skip("dataset not present")
    rtl = M.synth(pr.read_text(errors="replace"), _LEM1_TABLE, "TopModule")
    assert rtl is not None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(rtl)
        vvp = Path(d) / "a.vvp"
        c = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(tb)],
                           capture_output=True, text=True)
        assert c.returncode == 0, c.stderr
        r = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True, cwd=d)
        assert "mismatched samples is 0" in r.stdout, r.stdout[-300:]
