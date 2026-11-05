#!/usr/bin/env python3
"""Tests for canonical_primitive_synth.py.

POSITIVE: for each of the 9 dataset design_description.txt files, detect_shape
must return the expected shape, and --from-desc emit must produce RTL whose
declared module name matches the spec's 'Module name:' token.

NEGATIVE: a handful of OTHER RTLLM specs (adder_8bit, freq_divbyeven,
synchronizer, multi_16bit) must detect_shape -> None (no mis-fire).
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import os
import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent                         # .../programs
PROG = PROGRAMS / "canonical_primitive_synth.py"
# Resolved from the environment, not hardcoded: a personal home path in
# shipped source is unresolvable for every other user, and
# `shipped_path_portability_check` blocks on it. The dataset-backed tests
# already skip when the corpus is absent, so an unset var simply skips.
# Reintroduced twice by stacked PRs authored against an older base — hence
# the gate, and hence this comment sitting where the literal used to be.
RTLLM = Path(os.environ.get("VIBEIC_RTLLM_CORPUS",
                            Path.home() / "_bench_rtllm2_scratch/RTLLM"))
# The dataset-backed tests only run where the RTLLM corpus is checked out locally;
# in CI it is absent, so they skip. The self-contained inline tests below prove
# the detection contract with NO external dataset (they always run).
_need_dataset = pytest.mark.skipif(
    not RTLLM.exists(), reason="RTLLM dataset not present on this host")

sys.path.insert(0, str(PROGRAMS))
import canonical_primitive_synth as rcs  # noqa: E402


def _request_admission_desc(module="radix2_div", protocol=""):
    return f"""Module name:
{module}
Implement an 8-bit radix-2 divider for signed or unsigned operands.
Input ports:
clk: rising-edge clock.
rst: synchronous active-high reset.
sign: signed operation when high.
dividend: 8-bit numerator.
divisor: 8-bit nonzero denominator.
opn_valid: request valid.
res_ready: consume the current result.
Output ports:
res_valid: result valid.
result: 16-bit packed remainder in bits 15:8 and quotient in bits 7:0.
Capture and initialize a request whenever opn_valid && !res_valid.
Each accepted request replaces the previous operation with its new operands.
{protocol}
"""


def _request_admission_native(tmp_path, rtl, module, scenario, delay=0):
    """Independent language /,% values; no generated scoreboard or external data."""
    body = {
        "restart": f"""
            request(201, 13, 0);
            if ({delay} > 0) begin
                @(negedge clk); opn_valid=0;
                repeat ({delay}) begin @(posedge clk); #1; end
            end
            request(-93, 11, 1);
            @(negedge clk); opn_valid=0;
            answer(-93, 11, 1);
        """,
        "normal": """
            for (integer s=0; s<2; s=s+1)
                for (integer a=17; a<253; a=a+29)
                    for (integer b=3; b<35; b=b+7) begin
                        request(a, b, s);
                        @(negedge clk); opn_valid=0;
                        answer(a, b, s);
                        consume;
                    end
        """,
        "backpressure": """
            request(181, 9, 0);
            @(negedge clk); opn_valid=0;
            answer(181, 9, 0);
            repeat (4) begin
                request(77, 6, 0);
                if (!res_valid || result !== expected(181,9,0))
                    $fatal(1,"held result changed under backpressure");
            end
            res_ready=1;
            @(posedge clk); #1;
            if (res_valid) $fatal(1,"result did not clear on consumption");
            @(negedge clk); opn_valid=0; res_ready=0;
            repeat (12) begin @(posedge clk); #1;
                if (res_valid) $fatal(1,"request accepted while result valid");
            end
            request(77,6,0);
            @(negedge clk); opn_valid=0;
            answer(77,6,0);
        """,
        "reset": """
            request(201,13,0);
            @(negedge clk); opn_valid=0;
            repeat (3) @(posedge clk);
            @(negedge clk); rst=1;
            @(posedge clk); #1;
            if (res_valid || result !== 0) $fatal(1,"reset did not clear result");
            @(negedge clk); rst=0;
            repeat (12) begin @(posedge clk); #1;
                if (res_valid) $fatal(1,"cancelled operation survived reset");
            end
            request(119,8,0);
            @(negedge clk); opn_valid=0;
            answer(119,8,0);
        """,
        "serialized": """
            request(201,13,0);
            request(77,6,0);
            @(negedge clk); opn_valid=0;
            repeat (3) @(posedge clk);
            request(119,8,0);
            @(negedge clk); opn_valid=0;
            answer(201,13,0);
        """,
    }[scenario]
    tb = f"""module request_monitor;
        reg clk=0, rst=1, sign=0, opn_valid=0, res_ready=0;
        reg [7:0] dividend=0, divisor=1;
        wire res_valid;
        wire [15:0] result;
        integer checks=0;
        {module} dut(.*);
        always #5 clk=~clk;
        function [15:0] expected(input integer a,b,s);
            integer x,y,q,r;
            begin
                x=a & 255; y=b & 255;
                if (s && x>=128) x=x-256;
                if (s && y>=128) y=y-256;
                q=x/y; r=x%y;
                expected=((r & 255)<<8) | (q & 255);
            end
        endfunction
        task request(input integer a,b,s);
            begin
                @(negedge clk); dividend=a; divisor=b; sign=s; opn_valid=1;
                @(posedge clk); #1;
            end
        endtask
        task answer(input integer a,b,s);
            integer timeout;
            begin
                timeout=0;
                while (!res_valid && timeout<16) begin
                    @(posedge clk); #1; timeout=timeout+1;
                end
                if (!res_valid || result !== expected(a,b,s))
                    $fatal(1,"VALUE request result got=%h expected=%h valid=%b",
                           result,expected(a,b,s),res_valid);
                checks=checks+1;
            end
        endtask
        task consume;
            begin
                @(negedge clk); res_ready=1;
                @(posedge clk); #1;
                @(negedge clk); res_ready=0;
            end
        endtask
        initial begin
            repeat (2) @(posedge clk);
            @(negedge clk); rst=0;
            {body}
            $display("PASS checks=%0d",checks);
            $finish;
        end
        initial begin #200000; $fatal(1,"monitor timeout"); end
    endmodule
    """
    (tmp_path / "request_dut.v").write_text(rtl)
    (tmp_path / "request_monitor.v").write_text(tb)
    compiled = subprocess.run([
        "iverilog", "-g2012", "-s", "request_monitor", "-o", str(tmp_path / "sim"),
        str(tmp_path / "request_dut.v"), str(tmp_path / "request_monitor.v")],
        capture_output=True, text=True, timeout=45)
    (tmp_path / "compile.log").write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    result = subprocess.run(["vvp", str(tmp_path / "sim")],
                            capture_output=True, text=True, timeout=45)
    (tmp_path / "native.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS checks=" in result.stdout, result.stdout


@pytest.mark.parametrize("delay", [0, 1, 4, 9],
                         ids=["loading", "first_iteration", "inflight", "completion_edge"])
def test_radix_request_replaces_operation_native(tmp_path, delay):
    desc = _request_admission_desc()
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    _request_admission_native(tmp_path, rtl, "radix2_div", "restart", delay)


@pytest.mark.parametrize("scenario", ["normal", "backpressure", "reset"])
def test_radix_request_existing_protocol_native(tmp_path, scenario):
    desc = _request_admission_desc()
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    _request_admission_native(tmp_path, rtl, "radix2_div", scenario)


@pytest.mark.parametrize("protocol,serialized", [
    ("Requests are accepted only when idle.", True),
    ("Requests are ignored while busy.", True),
    ("Requests are not accepted while busy.", True),
    ("Requests must not be accepted while busy.", True),
    ("Requests are only accepted when not busy.", True),
    ("Ignore requests while busy.", True),
    ("Requests are accepted\nonly when idle.", True),
    ("Requests are not ignored while busy.", False),
    ("No requests are ignored while busy.", False),
    ("Do not ignore requests while busy.", False),
    ("Do not ever ignore requests while busy.", False),
    ("The status monitor is busy while requests are accepted.", False),
], ids=["only_idle", "ignore_busy", "not_accept_busy", "must_not_be_accepted", "only_not_busy",
        "ignore_requests_busy", "wrapped_idle", "not_ignore_busy",
        "no_ignored_requests", "do_not_ignore", "do_not_ever_ignore", "other_busy_signal"])
def test_radix_request_busy_restriction_is_source_bound_native(tmp_path, protocol, serialized):
    desc = _request_admission_desc(protocol=protocol)
    if serialized:
        desc = desc.replace("whenever opn_valid && !res_valid",
                            "when idle and opn_valid && !res_valid")
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    _request_admission_native(tmp_path, rtl, "radix2_div",
                              "serialized" if serialized else "restart")


def test_radix_request_renamed_ordinary_project_consumer_native(tmp_path):
    desc = _request_admission_desc("arithmetic_capture_unit")
    project = _mk_project(tmp_path / "project", desc)
    result = _load_runner().step_rtl_gen(project, "digital_arithmetic_primitive")
    assert result.status == "PASS", result
    assert result.extras["deterministic_generator"] == "canonical_primitive_synth"
    outputs = list((project / "phase2/stage1/rtl").glob("*.v"))
    assert len(outputs) == 1
    _request_admission_native(tmp_path, outputs[0].read_text(),
                              "arithmetic_capture_unit", "restart", 9)


def test_radix_request_admission_lesson_reaches_digest(tmp_path):
    from _hostpaths import require_repo
    import _lesson_digest
    expert = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "agents", "ic-expert-agent.md")
    assert _lesson_digest.render_lesson_digest(tmp_path, expert) > 0
    digest = (tmp_path / "lessons.md").read_text()
    assert "Request admission follows the declared condition" in digest
    assert "loading" in digest and "restart" in digest


@pytest.mark.parametrize("change", ["missing_ready", "other_algorithm", "wrong_width",
                                    "wrong_direction", "extra_port", "vector_control"])
def test_radix_request_renamed_shape_requires_complete_interface_and_algorithm(change):
    desc = _request_admission_desc("independent_arithmetic_unit")
    if change == "missing_ready":
        desc = desc.replace("res_ready: consume the current result.\n", "")
    elif change == "other_algorithm":
        desc = desc.replace("radix-2 divider", "multiplier")
    elif change == "wrong_width":
        desc = desc.replace("dividend: 8-bit", "dividend: 12-bit")
    elif change == "wrong_direction":
        desc = desc.replace("divisor: 8-bit nonzero denominator.\n", "")
        desc = desc.replace("Output ports:\n", "Output ports:\ndivisor: 8-bit denominator.\n")
    elif change == "extra_port":
        desc = desc.replace("Input ports:\n", "Input ports:\nextra_mode: mode input.\n")
    else:
        desc = desc.replace("sign: signed", "sign: 2-bit signed")
    assert rcs.detect_shape(desc) is None

# spec-dir (relative to RTLLM) -> (expected_shape, expected_module)
POSITIVE = {
    "Miscellaneous/Frequency divider/freq_divbyodd":
        ("odd_clock_divider", "freq_divbyodd"),
    "Miscellaneous/Frequency divider/freq_divbyfrac":
        ("frac_clock_divider_3p5", "freq_divbyfrac"),
    "Miscellaneous/Others/pulse_detect":
        ("pulse_detect_0to1to0", "pulse_detect"),
    "Miscellaneous/Others/serial2parallel":
        ("serial_to_parallel_8", "serial2parallel"),
    "Miscellaneous/Others/parallel2serial":
        ("parallel_to_serial_4", "parallel2serial"),
    "Arithmetic/Divider/div_16bit":
        ("combinational_long_divider", "div_16bit"),
    "Miscellaneous/Others/traffic_light":
        ("traffic_light_fsm", "traffic_light"),
    "Arithmetic/Divider/radix2_div":
        ("radix2_signed_divider", "radix2_div"),
    "Arithmetic/Other/float_multi":
        ("ieee754_single_multiplier", "float_multi"),
    "Memory/FIFO/asyn_fifo":
        ("async_gray_fifo", "asyn_fifo"),
    "Arithmetic/Multiplier/multi_pipe_8bit":
        ("pipelined_unsigned_multiplier_8", "multi_pipe_8bit"),
    "Memory/Shifter/barrel_shifter":
        ("barrel_shifter_right_8", "barrel_shifter"),
    "Miscellaneous/Signal generation/signal_generator":
        ("triangle_wave_generator_5", "signal_generator"),
    "Control/Finite State Machine/fsm":
        ("mealy_seq_detector_10011", "fsm"),
    "Arithmetic/Adder/adder_pipe_64bit":
        ("pipelined_ripple_adder_64", "adder_pipe_64bit"),
}

NEGATIVE = [
    "Arithmetic/Adder/adder_8bit",
    "Miscellaneous/Frequency divider/freq_divbyeven",
    "Miscellaneous/Others/synchronizer",
    "Arithmetic/Multiplier/multi_16bit",
]


def _desc(reldir: str) -> str:
    return (RTLLM / reldir / "design_description.txt").read_text(errors="replace")


def _module_decl(rtl: str) -> str:
    # top module: for asyn_fifo the top is asyn_fifo (dual_port_RAM is a submodule).
    mods = re.findall(r"(?m)^\s*module\s+([A-Za-z_]\w*)", rtl)
    return mods[-1] if mods else ""


@_need_dataset
@pytest.mark.parametrize("reldir,expected", POSITIVE.items())
def test_detect_positive(reldir, expected):
    shape, module = expected
    desc = _desc(reldir)
    assert rcs.detect_shape(desc) == shape


@_need_dataset
@pytest.mark.parametrize("reldir,expected", POSITIVE.items())
def test_emit_from_desc(reldir, expected, tmp_path):
    shape, module = expected
    spec = RTLLM / reldir / "design_description.txt"
    out = tmp_path / f"{module}.v"
    r = subprocess.run(
        [sys.executable, str(PROG), "--from-desc", str(spec), "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    j = json.loads(r.stdout)
    assert j["verdict"] == "EMIT"
    assert j["shape"] == shape
    assert j["module"] == module
    rtl = out.read_text()
    # emitted RTL declares a module whose (top) name matches the spec module name
    assert re.search(r"(?m)^\s*module\s+" + re.escape(module) + r"\b", rtl)
    # and the spec's own Module name token equals that module
    assert rcs.module_name_of(_desc(reldir)) == module


@_need_dataset
@pytest.mark.parametrize("reldir", NEGATIVE)
def test_detect_negative(reldir):
    desc = _desc(reldir)
    assert rcs.detect_shape(desc) is None, f"mis-fired on {reldir}"


def test_emit_covers_all_nine():
    shapes = {s for s, _ in POSITIVE.values()}
    for s in shapes:
        rtl = rcs.emit_rtl(s)
        assert "module" in rtl and "endmodule" in rtl


# ============================================================================
# Self-contained inline tests — NO external dataset, always run (incl. CI).
# These pin the STRUCTURAL detection contract with synthetic descriptions that
# reproduce each shape's signature, and prove fail-closed DEFER on near-misses.
# ============================================================================
_INLINE_POS = {
    "odd_clock_divider": (
        "Module name:\n    freq_divbyodd\n"
        "A frequency divider that divides the input clock by odd numbers.\n"
        "Input ports:\n clk: Input clock.\n rst_n: Active low reset.\n"
        "Output ports:\n clk_div: Divided clock output.\n"
        "The parameter NUM_DIV defaults to 5.\n"),
    "frac_clock_divider_3p5": (
        "Module name:\n    freq_divbyfrac\n"
        "A fractional frequency divider (3.5x) using the double-edge clocking "
        "technique. MUL2_DIV_CLK = 7.\n"
        "Input ports:\n clk: Input clock.\n rst_n: Active low reset.\n"
        "Output ports:\n clk_div: Fractionally divided clock output.\n"),
    "pulse_detect_0to1to0": (
        "Module name:\n    pulse_detect\n"
        "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.\n"
        "Input ports:\n clk: Clock.\n rst_n: Reset.\n data_in: One-bit input.\n"
        "Output ports:\n data_out: pulse indicator.\n"),
    "combinational_long_divider": (
        "Module name:\n    div_16bit\n"
        "Implement a 16-bit divider in combinational logic. The dividend is "
        "16-bit and the divisor is 8-bit.\n"
        "Input ports:\n A: 16-bit dividend.\n B: 8-bit divisor.\n"
        "Output ports:\n result: 16-bit quotient.\n odd: 16-bit remainder.\n"),
    "pipelined_unsigned_multiplier_8": (
        "Module name:\n    multi_pipe_8bit\n"
        "Implement an unsigned 8bit multiplier based on pipelining processing.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active-low reset.\n"
        " mul_en_in: Input enable.\n mul_a: 8-bit multiplicand.\n"
        " mul_b: 8-bit multiplier.\n"
        "Output ports:\n mul_en_out: Output enable.\n mul_out: 16-bit product.\n"),
    "barrel_shifter_right_8": (
        "Module name:\n    barrel_shifter\n"
        "A barrel shifter for shifting bits efficiently, controlled by ctrl.\n"
        "Input ports:\n in: 8-bit input to be shifted.\n ctrl: 3-bit shift amount.\n"
        "Output ports:\n out: 8-bit shifted output.\n"),
    "triangle_wave_generator_5": (
        "Module name:\n    signal_generator\n"
        "Implement a Triangle Wave generator whose 5-bit wave cycles between "
        "0 and 31.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active-low reset.\n"
        "Output ports:\n wave: 5-bit output waveform.\n"),
    "mealy_seq_detector_10011": (
        "Module name:\n    fsm\n"
        "Implement a Mealy FSM detection circuit that detects a single-bit input "
        "IN. When the input is 10011, output MATCH is 1.\n"
        "Input ports:\n IN: Input signal.\n CLK: Clock.\n RST: Reset.\n"
        "Output ports:\n MATCH: match indicator.\n"),
    "pipelined_ripple_adder_64": (
        "Module name:\n    adder_pipe_64bit\n"
        "Implement a 64-bit ripple carry adder with several registers to enable "
        "the pipeline stages.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n i_en: Enable.\n"
        " adda: 64-bit A.\n addb: 64-bit B.\n"
        "Output ports:\n result: 65-bit sum.\n o_en: Output enable.\n"),
    "parallel_to_serial_4": (
        "Module name:\n    parallel2serial\n"
        "Implement a module for parallel-to-serial conversion, where every four "
        "input bits are converted to a serial one bit output (from MSB to LSB).\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " d: 4-bit parallel data input.\n"
        "Output ports:\n valid_out: Valid signal.\n dout: Serial output.\n"),
    # The remaining SIX shapes, added when an audit showed the inline population
    # was 10 of 16: every claim this module makes about "the canonical
    # descriptions" was measured on ten of the sixteen, and the dataset-backed
    # tests that would have covered the rest SKIP wherever the corpus is absent.
    "serial_to_parallel_8": (
        "Module name:\n    serial2parallel\n"
        "Implement a series-parallel conversion: eight serial input bits are\n"
        "assembled into one 8-bit word, from the most significant bit to the "
        "least.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " din_serial: Serial input bit.\n din_valid: High when din_serial is "
        "valid.\n"
        "Output ports:\n dout_parallel: 8-bit assembled word.\n"
        " dout_valid: High when dout_parallel is complete.\n"),
    "traffic_light_fsm": (
        "Module name:\n    traffic_light\n"
        "Implement a traffic light controller with a pedestrian pass_request.\n"
        "Input ports:\n rst_n: Active low reset.\n clk: Clock.\n"
        " clock: Clock signal.\n pass_request: Pedestrian request.\n"
        "Output ports:\n red: Red lamp.\n yellow: Yellow lamp.\n"
        " green: Green lamp.\n"),
    "radix2_signed_divider": (
        "Module name:\n    radix2_div\n"
        "Implement a radix-2 divider that handles signed or unsigned operands\n"
        "according to the sign input.\n"
        "Input ports:\n clk: Clock.\n rst: Reset.\n sign: 1 for signed "
        "operands.\n"
        " dividend: 8-bit dividend.\n divisor: 8-bit divisor.\n"
        " opn_valid: Operands are valid.\n"
        " res_ready: Result consumption handshake.\n"
        "Output ports:\n res_valid: Result is valid.\n result: 16-bit "
        "result.\n"),
    "ieee754_single_multiplier": (
        "Module name:\n    float_multi\n"
        "Implement an IEEE 754 single-precision floating-point multiplier.\n"
        "Input ports:\n clk: Clock.\n rst: Reset.\n a: 32-bit operand.\n"
        " b: 32-bit operand.\n"
        "Output ports:\n z: 32-bit product.\n"),
    "async_gray_fifo": (
        "Module name:\n    asyn_fifo\n"
        "Implement an asynchronous FIFO whose pointers cross the clock domains\n"
        "as gray code.\n"
        "Input ports:\n wclk: Write clock.\n rclk: Read clock.\n"
        " wrstn: Write-domain active low reset.\n rrstn: Read-domain reset.\n"
        " winc: Write enable.\n rinc: Read enable.\n wdata: Write data.\n"
        "Output ports:\n wfull: FIFO full.\n rempty: FIFO empty.\n"
        " rdata: Read data.\n"),
    "lfsr4_xnor_left": (
        "Module name:\n    LFSR\n"
        "Implement a 4-bit linear feedback shift register. Each cycle the\n"
        "register is shifted left and the new low bit is out[3] xor out[2],\n"
        "inverted.\n"
        "Input ports:\n clk: Clock.\n rst: Reset.\n"
        "Output ports:\n out: 4-bit register value.\n"),
    "unsigned_iterative_restoring_divider": (
        "Design an unsigned iterative arithmetic unit using the restoring division "
        "algorithm.\n"
        "Module name: unsigned_ratio_unit\n"
        "Parameter WIDTH has a default value of 9.\n"
        "Input ports:\n"
        "clk: posedge clock.\n"
        "rst: active-low asynchronous reset.\n"
        "start: one-cycle request.\n"
        "dividend[WIDTH-1:0]: unsigned dividend.\n"
        "divisor[WIDTH-1:0]: unsigned divisor.\n"
        "Output ports:\n"
        "quotient[WIDTH-1:0]: unsigned quotient.\n"
        "remainder[WIDTH-1:0]: unsigned remainder.\n"
        "valid: one-cycle completion.\n"
        "Both operands are nonzero, and dividend is at least divisor.\n"
        "On reset all outputs clear. New inputs are accepted after the previous "
        "result.\n"
        "At each restoring iteration append the next dividend bit to the shifted "
        "partial remainder and subtract the divisor; a negative trial restores "
        "the shifted partial remainder and produces quotient bit zero.\n"
        "Completion takes WIDTH cycles for power-of-two WIDTH and WIDTH+1 cycles "
        "otherwise; no extra input-only cycle.\n"),
}

# Near-miss descriptions that MUST fail-closed to None (no template mis-fire).
_INLINE_NEG = [
    # even divider — same clk/rst_n/clk_div ports, but "even" not "odd"/"3.5".
    ("Module name:\n    freq_divbyeven\n"
     "A frequency divider that divides by even numbers.\n"
     "Input ports:\n clk\n rst_n\n Output ports:\n clk_div\n"),
    # a plain 8-bit adder — no matching shape.
    ("Module name:\n    adder_8bit\n"
     "An 8-bit adder.\n Input ports:\n a\n b\n Output ports:\n sum\n"),
    # right port names but wrong function word (a *multiplier*, not divider).
    ("Module name:\n    mul_16bit\n"
     "A 16-bit multiplier in combinational logic.\n"
     "Input ports:\n A: 16-bit.\n B: 8-bit.\n Output ports:\n result\n odd\n"),
    # a Mealy FSM with the fsm ports but a DIFFERENT pattern (1011, not 10011) —
    # the mealy_seq_detector_10011 shape must fail-closed on a foreign pattern.
    ("Module name:\n    fsm\n"
     "Implement a Mealy FSM that detects the input pattern 1011.\n"
     "Input ports:\n IN\n CLK\n RST\n Output ports:\n MATCH\n"),
    # the sibling sequence_detector — an FSM, but NOT module `fsm`, so no misfire.
    ("Module name:\n    sequence_detector\n"
     "A finite state machine detecting the 1001 sequence via states.\n"
     "Input ports:\n clk\n reset_n\n data_in\n Output ports:\n detected\n"),
    # a plain combinational 64-bit adder with the adda/addb ports but NO pipeline —
    # pipelined_ripple_adder_64 must fail-closed without the "pipeline" structure.
    ("Module name:\n    adder_pipe_64bit\n"
     "A 64-bit ripple carry adder, purely combinational.\n"
     "Input ports:\n clk\n rst_n\n i_en\n adda\n addb\n Output ports:\n result\n o_en\n"),
    # a pipelined adder of a DIFFERENT width (32-bit), wrong module name — no misfire.
    ("Module name:\n    adder_pipe_32bit\n"
     "A 32-bit pipelined ripple carry adder.\n"
     "Input ports:\n clk\n rst_n\n i_en\n adda\n addb\n Output ports:\n result\n o_en\n"),
    # right module name + ports for parallel2serial but NO parallel-to-serial
    # phrase — the detector must fail-closed rather than key on ports alone.
    ("Module name:\n    parallel2serial\n"
     "A generic 4-bit register block.\n"
     "Input ports:\n clk\n rst_n\n d\n Output ports:\n valid_out\n dout\n"),
]


@pytest.mark.parametrize("shape,desc", _INLINE_POS.items())
def test_inline_detect_positive(shape, desc):
    assert rcs.detect_shape(desc) == shape


@pytest.mark.parametrize("desc", _INLINE_NEG)
def test_inline_detect_negative_failclosed(desc):
    assert rcs.detect_shape(desc) is None


def test_module_name_extraction():
    assert rcs.module_name_of("Module name:\n    freq_divbyodd\n") == "freq_divbyodd"


def test_unsigned_divider_cli_emits_source_bound_contract(tmp_path):
    desc = tmp_path / "unsigned_ratio_unit_description.txt"
    desc.write_text(_INLINE_POS["unsigned_iterative_restoring_divider"])
    out = tmp_path / "unsigned_ratio_unit.sv"
    run = subprocess.run([sys.executable, str(PROG), "--from-desc", str(desc),
                          "--out", str(out)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["shape"] == "unsigned_iterative_restoring_divider"
    assert result["module"] == "unsigned_ratio_unit"
    assert result["contract"]["domain"] == (
        "unsigned_nonzero_dividend_ge_divisor")
    assert result["contract"]["latency"] == {
        "power_of_two_cycles": "WIDTH", "otherwise_cycles": "WIDTH+1",
        "resolved_cycles": 10,
        "no_input_only_cycle": True}
    rtl = out.read_text()
    assert "module unsigned_ratio_unit" in rtl
    assert result["source_sha256"] in rtl
    occupied = subprocess.run(
        [sys.executable, str(PROG), "--from-desc", str(desc), "--out", str(out)],
        capture_output=True, text=True)
    assert occupied.returncode == 2
    assert json.loads(occupied.stdout)["verdict"] == "REFUSED"
    assert out.read_text() == rtl


def test_unsigned_divider_supports_renamed_ports_and_refuses_unsupported_domains():
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "unsigned_ratio_unit", "renamed_div").replace("clk:", "clock_i:") \
        .replace("rst:", "reset_n:").replace("start:", "go_i:") \
        .replace("dividend[", "numerator_i[").replace("divisor[", "denominator_i[") \
        .replace("quotient[", "quot_o[").replace("remainder[", "rem_o[") \
        .replace("valid:", "done_o:")
    assert rcs.detect_shape(desc) == "unsigned_iterative_restoring_divider"
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    for name in ("clock_i", "reset_n", "go_i", "numerator_i", "denominator_i",
                 "quot_o", "rem_o", "done_o"):
        assert name in rtl
    signed = desc.replace("unsigned iterative", "signed iterative") \
        .replace("unsigned dividend", "signed dividend") \
        .replace("unsigned divisor", "signed divisor")
    assert rcs.detect_shape(signed) is None
    assert rcs.route_to_ai_reason(signed)["kind"] == (
        "unsupported_unsigned_iterative_divider")
    zero = desc.replace("Both operands are nonzero, and dividend is at least divisor.",
                        "The divisor may be zero.")
    assert rcs.detect_shape(zero) is None
    assert rcs.route_to_ai_reason(zero)["kind"] == (
        "unsupported_unsigned_iterative_divider")


@pytest.mark.parametrize("domain", [
    # Exact R3 blocker: ordering does not ground divisor != 0.
    "The dividend is nonzero, and dividend is at least divisor.",
    # Relational-only and a one-operand claim remain insufficient.
    "The dividend is at least divisor.",
    "The dividend is nonzero; the divisor is unspecified.",
    # Modal and negated claims are not positive grounding.
    "The divisor may be nonzero, and dividend is at least divisor.",
    "Do not assume the divisor is nonzero; dividend is at least divisor.",
    "The divisor is not nonzero, and dividend is at least divisor.",
], ids=[
    "exact_dividend_only",
    "relational_only",
    "divisor_unspecified",
    "divisor_modal",
    "divisor_negated_assumption",
    "divisor_negated",
])
def test_unsigned_divider_requires_explicit_divisor_nonzero_grounding(domain):
    """The template may emit only with explicit divisor nonzero grounding."""
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.", domain)
    reason = rcs.route_to_ai_reason(desc)
    assert rcs.detect_shape(desc) is None
    assert reason is not None and reason["kind"] == (
        "unsupported_unsigned_iterative_divider")
    assert "nonzero operand domain" in reason["unresolved"]


@pytest.mark.parametrize("domain", [
    "The divisor is nonzero, and dividend is at least divisor.",
    "The dividend is at least divisor, and the divisor is nonzero.",
    "Both operands are nonzero, and dividend is at least divisor.",
    "Both operands must be nonzero; dividend >= divisor.",
], ids=[
    "divisor_before_relation",
    "divisor_after_relation",
    "both_operands_are",
    "both_operands_must_be",
])
def test_unsigned_divider_accepts_explicit_divisor_or_both_operand_grounding(domain):
    """Positive grounding survives word order and both-operand wording."""
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.", domain)
    assert rcs.detect_shape(desc) == "unsigned_iterative_restoring_divider"
    assert rcs.route_to_ai_reason(desc) is None


@pytest.mark.parametrize("domain,emit", [
    ('If the divisor is nonzero, the operation is supported.', False),
    ('For example, "the divisor is nonzero" describes one valid case.', False),
    ('The divisor is positive.', True),
], ids=["conditional", "quoted_example", "explicit_positive"])
def test_unsigned_divider_r4_exact_router_regression(domain, emit, tmp_path):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.",
        domain + "\nDividend is at least divisor.")
    expected = "unsigned_iterative_restoring_divider" if emit else None
    assert rcs.detect_shape(desc) == expected
    if not emit:
        assert "nonzero operand domain" in rcs.route_to_ai_reason(desc)["unresolved"]
    source, out = tmp_path / "description.txt", tmp_path / "unit.sv"
    source.write_text(desc)
    run = subprocess.run([sys.executable, str(PROG), "--from-desc", str(source),
                          "--out", str(out)], capture_output=True, text=True)
    assert run.returncode == (0 if emit else 2), run.stdout + run.stderr
    assert json.loads(run.stdout)["verdict"] == ("EMIT" if emit else "DEFER")
    assert out.exists() == emit


@pytest.mark.parametrize("subject,verb", [
    ("The divisor", "is"), ("The denominator", "is"),
    ("Both operands", "are"), ("The operands", "are"),
    ("Dividend and divisor", "are"), ("Divisor and dividend", "are"),
    ("The dividend and the divisor", "are"),
    ("Numerator and denominator", "are"),
    ("Both dividend and divisor", "are"),
    ("Denominator and numerator", "are"),
])
@pytest.mark.parametrize("predicate", [
    "{verb} nonzero", "must be nonzero", "shall be nonzero",
    "{verb} positive", "must be positive", "shall be positive",
    "{verb} greater than zero", "> 0",
    "{verb} non-zero",
])
def test_unsigned_divider_r4_unconditional_positive_forms(subject, verb, predicate):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.",
        subject + " " + predicate.format(verb=verb) + ".\nDividend >= divisor.")
    assert rcs.detect_shape(desc) == "unsigned_iterative_restoring_divider"
    assert rcs.route_to_ai_reason(desc) is None


@pytest.mark.parametrize("domain", [
    "If the divisor is nonzero, the operation is supported.",
    "When the divisor is nonzero, the operation is supported.",
    "Provided the divisor is positive, the operation is supported.",
    "Assuming the divisor is nonzero, the operation is supported.",
    "Suppose the divisor is positive.",
    "Unless the divisor is positive, the operation is unsupported.",
    "In case the divisor is nonzero, the operation is supported.",
    "The divisor is nonzero if a restricted mode is selected.",
    "For example, the divisor is nonzero.",
    "The divisor is nonzero as an example.",
    "The divisor is positive?",
    "E.g. the divisor is nonzero.",
    "Such as the divisor is nonzero.",
    "Consider that the divisor is positive.",
    '"The divisor is nonzero."', "'The divisor is nonzero.'",
    "“The divisor is positive.”", "`The divisor is nonzero.`",
    "```text\nThe divisor is nonzero.\n```",
    "~~~\nThe divisor is positive.\n~~~",
    "    The divisor is nonzero.",
    "> The divisor is nonzero.",
    "# The divisor is nonzero",
    "Domain: the divisor is nonzero.",
    "The divisor may be nonzero.", "The divisor might be positive.",
    "The divisor could be positive.", "The divisor can be nonzero.",
    "The divisor is not guaranteed nonzero.",
    "The divisor is not necessarily positive.",
    "There is no requirement that the divisor be positive.",
    "Do not assume the divisor is nonzero.",
    "The divisor is nonzero (not guaranteed).",
    "The divisor is positive, but this only describes a restricted case.",
    "Previously the divisor is nonzero.",
    "The divisor is nonzero, historically.",
    "The divisor is positive in a previous requirement.",
    "The divisor is positive, yet this is only an example.",
    "The old requirement says the divisor is nonzero.",
    "The divisor is nonzero; this rule is superseded.",
    "The dividend is positive.", "The dividend > 0.",
    "The quotient is nonzero.", "The remainder is positive.",
    "The divisor and quotient are nonzero.",
    "The quotient reports the divisor is positive.",
    "The quotient and the divisor is nonzero.",
    "If " + "a restricted mode is selected and " * 15 + "the divisor is positive.",
    "The dividend is nonzero, and dividend is at least divisor.",
])
def test_unsigned_divider_r4_context_and_role_scopes_defer(domain):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.",
        domain + "\nDividend is at least divisor.")
    assert rcs.detect_shape(desc) is None
    assert "nonzero operand domain" in rcs.route_to_ai_reason(desc)["unresolved"]


@pytest.mark.parametrize("allowance", [
    "The divisor may be zero.", "The denominator might be zero.",
    "The divisor could be zero.", "The divisor can be zero.",
    "The divisor is not guaranteed nonzero.",
    "The divisor is not necessarily positive.",
    "No requirement that divisor be positive.",
    "There is no requirement that the denominator be nonzero.",
    "Both operands may be zero.", "The dividend may be zero.",
    "The divisor is zero.", "The divisor is not positive.",
])
@pytest.mark.parametrize("position", ["before", "after"])
def test_unsigned_divider_r4_contradiction_overrides_separate_positive(allowance, position):
    positive = "The divisor is positive.\nDividend is at least divisor."
    domain = (allowance + "\n" + positive if position == "before"
              else positive + "\n" + allowance)
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.", domain)
    assert rcs.detect_shape(desc) is None
    assert "nonzero operand domain" in rcs.route_to_ai_reason(desc)["unresolved"]


@pytest.mark.parametrize("domain", [
    "If the quotient is nonzero, it is retained.\nThe divisor is positive.",
    "The old quotation is superseded.\nThe divisor is positive.",
    "The divisor is positive.\nFor example, the quotient may be zero.",
    "For example, the quotient may be zero.\nThe divisor is positive.",
    "For example, the divisor is nonzero.\nThe divisor is positive.",
    '"The divisor is nonzero."\nThe divisor is positive.',
    "The divisor is\npositive.",
    "The divisor is positive!\nThe quotient may be zero.",
])
def test_unsigned_divider_r4_sentence_boundaries_preserve_positive(domain):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.",
        domain + "\nDividend is at least divisor.")
    assert rcs.detect_shape(desc) == "unsigned_iterative_restoring_divider"


@pytest.mark.parametrize("prefix", [
    'Note: "the divisor is nonzero".',
    "The divisor is nonzero.",
])
def test_unsigned_divider_r4_port_description_cannot_ground_domain(prefix):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.",
        "Dividend is at least divisor.").replace(
            "dividend[WIDTH-1:0]: unsigned dividend.",
            "dividend[WIDTH-1:0]: unsigned dividend. " + prefix)
    assert rcs.detect_shape(desc) is None


@pytest.mark.parametrize("allowance", [
    "The divisor may be zero.",
    "The divisor is not guaranteed nonzero.",
    "No requirement that divisor be positive.",
])
def test_unsigned_divider_r4_port_allowance_overrides_positive(allowance):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "divisor[WIDTH-1:0]: unsigned divisor.",
        "divisor[WIDTH-1:0]: unsigned divisor. " + allowance)
    assert rcs.detect_shape(desc) is None
    assert "nonzero operand domain" in rcs.route_to_ai_reason(desc)["unresolved"]


@pytest.mark.parametrize("ordering", [
    "If dividend is at least divisor, the operation is supported.",
    'For example, "dividend >= divisor" describes one case.',
    "Do not assume dividend is at least divisor.",
    "Dividend may be at least divisor.",
])
def test_unsigned_divider_r4_ordering_must_be_unconditional(ordering):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.",
        "The divisor is positive.\n" + ordering)
    assert rcs.detect_shape(desc) is None
    assert "dividend >= divisor domain" in rcs.route_to_ai_reason(desc)["unresolved"]


def _r5_domain_description(domain):
    return _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "Both operands are nonzero, and dividend is at least divisor.", domain)


def _r5_assert_publication(domain, emit, tmp_path):
    """Check the detector, publishing CLI and the existing normal consumer."""
    description = _r5_domain_description(domain)
    source, output = tmp_path / "description.txt", tmp_path / "unit.sv"
    source.write_text(description)
    run = subprocess.run([sys.executable, str(PROG), "--from-desc", str(source),
                          "--out", str(output)], capture_output=True, text=True)
    response = json.loads(run.stdout)
    assert response["verdict"] == ("EMIT" if emit else "DEFER")
    assert run.returncode == (0 if emit else 2), run.stdout + run.stderr
    assert output.exists() == emit
    if not emit:
        assert response["defer_reason"]["unresolved"]
    observed = rcs.detect_shape(description)
    assert observed == ("unsigned_iterative_restoring_divider" if emit else None)
    reason = rcs.route_to_ai_reason(description)
    assert (reason is None) == emit
    import design_one_shot_runner as runner
    project = tmp_path / "project"
    input_file = project / "phase1/input_doc/design_description.txt"
    input_file.parent.mkdir(parents=True)
    input_file.write_text(description)
    result = runner._try_canonical_primitive_rtl(project, time.time())
    files = list(project.glob("phase2/stage1/rtl/*.v"))
    assert bool(files) == emit
    assert (result is not None and result.status == "PASS") == emit


@pytest.mark.parametrize("withdrawal", [
    "That statement does not apply to this design.",
    "This guarantee is waived.",
    "The preceding requirement is obsolete.",
    "That requirement was removed.",
    "This is optional, not an input requirement.",
    "This property belongs to the reference model; the target accepts zero.",
    "Zero is also permitted as a divisor.",
    "A divisor of zero is a valid input.",
], ids=["frozen_retraction", "waived", "obsolete", "removed", "optional",
        "owner_reassigned", "zero_permitted", "zero_valid"])
def test_unsigned_divider_r5_resolves_target_retractions(withdrawal, tmp_path):
    _r5_assert_publication("The divisor is nonzero. " + withdrawal +
                           " Dividend is at least divisor.", False, tmp_path)


@pytest.mark.parametrize("withdrawal", [
    "That ordering constraint does not apply to this design.",
    "Dividend may be less than divisor.",
    "Dividend is less than divisor.",
])
def test_unsigned_divider_r5_resolves_ordering_retractions(withdrawal, tmp_path):
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + withdrawal, False, tmp_path)


@pytest.mark.parametrize("assertion", [
    "The divisor is nonzero in the reference model; this design permits zero.",
    "The divisor is nonzero in the reference model. This design permits zero.",
    "The divisor is positive in the comparison implementation; this unit accepts zero.",
    "The divisor is nonzero on the diagnostic channel; functional requests permit zero.",
    "The divisor is nonzero only in diagnostic mode; ordinary requests permit zero.",
    "The divisor is nonzero as long as the optional guard is enabled.",
    "The divisor is nonzero (a sample trace only).",
    "The divisor is nonzero (only in diagnostic mode).",
    "The divisor is nonzero, probably.",
    "The divisor is nonzero, presumably.",
    "The divisor is nonzero, according to the obsolete reference.",
    "The divisor is nonzero; this guarantee is waived.",
    "The divisor is nonzero; this constraint is optional.",
])
def test_unsigned_divider_r5_requires_target_proposition_owner(assertion, tmp_path):
    _r5_assert_publication(assertion + " Dividend is at least divisor.", False, tmp_path)


@pytest.mark.parametrize("heading", [
    "Examples:", "Reference model only:", "Hypothetical mode:",
    "If an optional guard is installed:", "Is the following true?",
    "## Examples", "## Reference model", "## Hypothetical mode",
    "## Examples\n### Input constraints",
    "## Reference model\n### Input constraints",
    "## Examples\nInput constraints:",
])
@pytest.mark.parametrize("marker", ["-", "*", "1."])
def test_unsigned_divider_r5_carries_list_and_section_framing(heading, marker, tmp_path):
    _r5_assert_publication(heading + "\n" + marker + " The divisor is nonzero.\n"
                           + marker + " Dividend is at least divisor.", False, tmp_path)


@pytest.mark.parametrize("other", [
    'A rejected example says "the divisor may be zero".',
    'The reference manual says "the denominator may be zero"; that refers to another design.',
    'A rejected example says “the divisor may be zero”.',
    'A rejected example says «the divisor may be zero».',
    'A rejected example says ‘the divisor may be zero’.',
    "The reference model's divisor may be zero.",
    "The divisor may be zero in the reference model.",
    "For example, the divisor may be zero in another design.",
    "If the divisor were zero, the request would be invalid.",
    "The divisor cannot be zero.",
    "The output is not saturated.",
    "\n> That statement does not apply to this design.\n",
    "\n## Rejected examples\n- That statement does not apply to this design.\n## Target constraints\n",
    "The divisor may be zero in another design. That statement is obsolete.",
])
def test_unsigned_divider_r5_scopes_contradictory_evidence(other, tmp_path):
    _r5_assert_publication("The divisor is nonzero. " + other +
                           " Dividend is at least divisor.", True, tmp_path)


@pytest.mark.parametrize("allowance", [
    "The divisor may be zero.", "The denominator is zero.",
    "Zero is permitted as a divisor.", "A divisor of zero is a valid input.",
])
def test_unsigned_divider_r5_keeps_target_zero_allowance_refusal(allowance, tmp_path):
    _r5_assert_publication("The divisor is nonzero. " + allowance +
                           " Dividend is at least divisor.", False, tmp_path)


@pytest.mark.parametrize("domain", [
    "The divisor is nonzero. The output is not saturated. Dividend is at least divisor.",
    "The divisor is nonzero, and the output is not saturated. Dividend is at least divisor.",
    "- The divisor is nonzero.\n- Dividend is at least divisor.",
    "* The divisor is nonzero.\n* Dividend is at least divisor.",
    "1. The divisor is nonzero.\n2. Dividend is at least divisor.",
    "Input constraints:\n- The divisor is nonzero.\n- Dividend is at least divisor.",
    "The divisor is nonzero (a required input constraint). Dividend is at least divisor.",
    "The divisor is nonzero in this design. Dividend is at least divisor.",
    "## Examples\n- The divisor may be zero.\n## Target input constraints\n"
    "- The divisor is nonzero.\n- Dividend is at least divisor.",
])
def test_unsigned_divider_r5_preserves_target_assertions(domain, tmp_path):
    _r5_assert_publication(domain, True, tmp_path)


def test_unsigned_divider_r5_port_zero_allowance_is_target_evidence(tmp_path):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"].replace(
        "divisor[WIDTH-1:0]: unsigned divisor.",
        "divisor[WIDTH-1:0]: unsigned divisor; zero is a permitted value.")
    assert rcs.detect_shape(desc) is None
    assert "nonzero operand domain" in rcs.route_to_ai_reason(desc)["unresolved"]


def test_unsigned_divider_r5_loads_by_path_outside_programs(tmp_path):
    source = tmp_path / "description.txt"
    source.write_text(_INLINE_POS["unsigned_iterative_restoring_divider"])
    script = (
        "import importlib.util, pathlib, sys\n"
        "spec = importlib.util.spec_from_file_location('independent_producer', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = module\n"
        "spec.loader.exec_module(module)\n"
        "text = pathlib.Path(sys.argv[2]).read_text()\n"
        "assert module.detect_shape(text) == 'unsigned_iterative_restoring_divider'\n"
        "assert module.emit_rtl(module.detect_shape(text), text)\n")
    run = subprocess.run([sys.executable, "-I", "-c", script, str(PROG), str(source)],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr



@pytest.mark.parametrize("heading", [
    "Reference model only:", "Examples:", "If an optional guard is installed:",
], ids=["reference", "example", "conditional"])
@pytest.mark.parametrize("layout", ["blank", "nested", "deep_numbered", "nested_blank" ])
def test_unsigned_divider_r6_inherits_list_frames(heading, layout, tmp_path):
    if layout == "blank":
        domain = heading + "\n\n- The divisor is nonzero.\n\n- Dividend is at least divisor."
    elif layout == "deep_numbered":
        domain = "1. " + heading + "\n  1. Input constraints:\n    1. The divisor is nonzero.\n    2. Dividend is at least divisor."
    else:
        gap = "\n" if layout == "nested_blank" else ""
        domain = "- " + heading + "\n" + gap + "  - The divisor is nonzero.\n" + gap + "  - Dividend is at least divisor."
    _r5_assert_publication(domain, False, tmp_path)


@pytest.mark.parametrize("domain", [
    "- The divisor is nonzero.\n\n- Dividend is at least divisor.",
    "- Target constraints:\n\n  - The divisor is nonzero.\n  - Dividend is at least divisor.",
    "- Reference model only:\n  - The divisor may be zero.\n- Target constraints:\n  - The divisor is nonzero.\n  - Dividend is at least divisor.",
    "- Examples:\n  - If a guard is installed:\n    - The divisor may be zero.\n\n- The divisor is nonzero.\n- Dividend is at least divisor.",
    "Reference model only:\n\n- The divisor may be zero.\nTarget constraints:\n- The divisor is nonzero.\n- Dividend is at least divisor.",
    "Reference model only:\n\n- The divisor may be zero.\nThe divisor is nonzero. Dividend is at least divisor.",
], ids=["ordinary_blank", "target_parent", "sibling_target", "dedent_two_levels",
        "heading_switch", "paragraph_switch"])
def test_unsigned_divider_r6_closes_list_frames(domain, tmp_path):
    _r5_assert_publication(domain, True, tmp_path)


@pytest.mark.parametrize("withdrawal", [
    "The nonzero constraint does not apply to this design.",
    "This divisor requirement does not apply to this design.",
    "The denominator constraint is waived.",
    "The nonzero requirement was removed.",
    "The preceding requirement is cancelled.",
    "That requirement has been retracted.",
], ids=["named_nonzero", "named_divisor", "denominator", "named_removed",
        "preceding_cancelled", "retracted"])
def test_unsigned_divider_r6_retracts_nonzero_domain(withdrawal, tmp_path):
    _r5_assert_publication("The divisor is nonzero. " + withdrawal +
                           " Dividend is at least divisor.", False, tmp_path)


@pytest.mark.parametrize("withdrawal", [
    "The ordering constraint does not apply to this design.",
    "This ordering requirement is cancelled.",
    "The ordering constraint was removed.",
], ids=["named_ordering", "ordering_cancelled", "ordering_removed"])
def test_unsigned_divider_r6_retracts_ordering_domain(withdrawal, tmp_path):
    _r5_assert_publication("Dividend is at least divisor. The divisor is nonzero. "
                           + withdrawal, False, tmp_path)


@pytest.mark.parametrize("other", [
    "The output requirement is cancelled.",
    "The ordering constraint is not waived.",
    "The nonzero constraint does not apply to the reference model.",
    'A rejected example says "the nonzero constraint does not apply to this design".',
    "\n- Reference model only:\n  - The nonzero constraint is cancelled.\n",
], ids=["unrelated_domain", "other_domain_preserved", "external_owner", "quotation",
        "nested_external"])
def test_unsigned_divider_r6_scopes_named_withdrawals(other, tmp_path):
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + other, True, tmp_path)


@pytest.mark.parametrize("preservation", [
    "That requirement is not waived.",
    "That requirement was not removed.",
    "That statement is not obsolete.",
    "That constraint is not optional.",
    "That statement has not been retracted.",
    "The preceding requirement is not cancelled.",
    "This divisor requirement has never been removed.",
    "The nonzero constraint is not waived.",
    "That statement still applies to this design.",
], ids=["not_waived", "not_removed", "not_obsolete", "not_optional", "not_retracted",
        "not_cancelled", "never_removed", "named_not_waived", "still_applies"])
def test_unsigned_divider_r6_preserves_negated_withdrawals(preservation, tmp_path):
    _r5_assert_publication("The divisor is nonzero. " + preservation +
                           " Dividend is at least divisor.", True, tmp_path)


@pytest.mark.parametrize("preservation", [
    "That ordering constraint is not waived.",
    "The ordering requirement was not removed.",
    "That ordering constraint has not been retracted.",
], ids=["ordering_not_waived", "ordering_not_removed", "ordering_not_retracted"])
def test_unsigned_divider_r6_preserves_negated_ordering_withdrawals(preservation, tmp_path):
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + preservation, True, tmp_path)


def test_unsigned_divider_r6_preserved_referent_can_be_withdrawn(tmp_path):
    _r5_assert_publication("The divisor is nonzero. That requirement is not waived. "
                           "That requirement was removed. Dividend is at least divisor.",
                           False, tmp_path)



@pytest.mark.parametrize("heading", [
    "Reference model only:", "Examples:", "If an optional guard is installed:",
], ids=["reference", "example", "conditional"])
@pytest.mark.parametrize("layout", ["tight", "blank", "mixed", "deep", "tab"])
def test_unsigned_divider_r7_f1_nested_colon_scope(heading, layout, tmp_path):
    indent = "\t" if layout == "tab" else "  "
    gap = "\n" if layout == "blank" else ""
    child = indent + "Input constraints:\n"
    if layout == "deep":
        child += indent + "  Operand constraints:\n"
        indent += "  "
    first, second = ("1.", "*") if layout == "mixed" else ("-", "-")
    domain = (heading + "\n" + gap + child + gap + indent + first +
              " The divisor is nonzero.\n" + indent + second +
              " Dividend is at least divisor.")
    _r5_assert_publication(domain, False, tmp_path)


@pytest.mark.parametrize("heading", [
    "Reference model only:", "Examples:", "If an optional guard is installed:",
], ids=["reference", "example", "conditional"])
def test_unsigned_divider_r7_f1_dedent_target(heading, tmp_path):
    _r5_assert_publication(heading + "\n  Input constraints:\n"
                           "  - The divisor may be zero.\nTarget constraints:\n"
                           "- The divisor is nonzero.\n- Dividend is at least divisor.",
                           True, tmp_path)


@pytest.mark.parametrize("domain", [
    "Target constraints:\n  Operand constraints:\n  - The divisor is nonzero.\n  - Dividend is at least divisor.",
    "- Reference model only:\n  Input constraints:\n  - The divisor may be zero.\n- Target constraints:\n  Input constraints:\n  - The divisor is nonzero.\n  - Dividend is at least divisor.",
    "Reference model only:\n  Input constraints:\n  - The divisor may be zero.\nThe divisor is nonzero. Dividend is at least divisor.",
    'Reference model only:\n"Discarded note"\n\n  Input constraints:\n  - The divisor is nonzero.\n  - Dividend is at least divisor.',
], ids=["target_child", "bullet_sibling", "paragraph_boundary", "quote_blank"])
def test_unsigned_divider_r7_f1_scope_boundaries(domain, tmp_path):
    _r5_assert_publication(domain, not domain.startswith('Reference model only:\n"'), tmp_path)


@pytest.mark.parametrize("withdrawal", [
    "The nonzero constraints are waived.",
    "The divisor requirements are removed.",
    "The denominator constraints are retracted.",
    "The ordering requirements are cancelled.",
    "These requirements are removed.",
    "Those constraints no longer apply to this design.",
    "THE NONZERO CONSTRAINTS ARE WAIVED.",
    "The preceding requirements were removed.",
    "These properties have been retracted.",
    "Those statements are obsolete.",
    "The non-zero guarantees are waived.",
    "These rules are optional.",
], ids=["nonzero", "divisor", "denominator", "ordering", "these", "those",
        "uppercase", "preceding", "properties", "statements", "hyphen", "rules"])
def test_unsigned_divider_r7_f2_plural_withdrawals(withdrawal, tmp_path):
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + withdrawal, False, tmp_path)


@pytest.mark.parametrize("other", [
    "The nonzero constraints are not waived.",
    "The ordering requirements were not removed.",
    "These requirements are not optional.",
    "Those constraints have never been retracted.",
    "The output requirements are waived.",
    "The nonzero constraints are waived in the reference model.",
    'A discarded example says "these requirements were removed".',
    "If a diagnostic guard is installed, these requirements are removed.",
], ids=["not_waived", "not_removed", "not_optional", "never", "unrelated",
        "external", "quoted", "conditional"])
def test_unsigned_divider_r7_f2_plural_preservation(other, tmp_path):
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + other, True, tmp_path)


@pytest.mark.parametrize("withdrawal,emit", [
    ("The nonzero requirement was not waived but was removed.", False),
    ("The ordering constraint is not obsolete but is cancelled.", False),
    ("That requirement is not waived but was removed.", False),
    ("Those requirements are not waived but were removed.", False),
    ("The nonzero requirement was not waived, but was removed.", False),
    ("The nonzero requirement was not waived yet was obsolete.", False),
    ("The nonzero requirement was not waived and was removed.", False),
    ("The nonzero requirement was waived but was not removed.", False),
    ("The ordering requirement is not optional but no longer applies to this design.", False),
    ("The nonzero requirement was not waived but was not removed.", True),
    ("The nonzero requirement was not waived, and was not removed.", True),
    ("The nonzero requirement was not waived but the output requirements were removed.", True),
    ("The nonzero requirement was not waived but was removed in the reference model.", True),
    ('A discarded example says "the nonzero requirement was not waived but was removed".', True),
    ("If a diagnostic guard is installed, the requirement is not waived but is removed.", True),
], ids=["removed", "cancelled", "unnamed", "plural", "comma", "yet", "and",
        "first_positive", "no_longer", "both_denied", "comma_denied", "other_subject",
        "external", "quoted", "conditional"])
def test_unsigned_divider_r7_f3_mixed_predicates(withdrawal, emit, tmp_path):
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + withdrawal, emit, tmp_path)


_R7_INTERFACE_CASES = [
    ("neutral", {"dividend": "numerator_i"}, 3),
    ("review_dividend", {"dividend": "dividend_reg"}, 3),
    ("review_divisor", {"divisor": "divisor_reg"}, 3),
    ("review_quotient", {"quotient": "quotient_reg"}, 3),
    ("review_valid", {"valid": "busy"}, 3),
    ("review_start", {"start": "finish_pending"}, 3),
] + [("internal_" + name, {"dividend": name}, 3) for name in (
    "COUNT_WIDTH", "EXTRA_FINAL_CYCLE", "dividend_reg", "divisor_reg",
    "quotient_reg", "partial_remainder", "count", "busy", "finish_pending",
    "shifted_remainder", "trial_ge_divisor", "iteration_remainder",
    "start_shifted_remainder", "start_ge_divisor", "start_remainder",
)] + [
    ("combined_suffix_chain", {
        "clk": "COUNT_WIDTH", "rst": "EXTRA_FINAL_CYCLE",
        "start": "finish_pending", "dividend": "dividend_reg",
        "divisor": "dividend_reg_2", "quotient": "quotient_reg",
        "remainder": "partial_remainder", "valid": "busy",
    }, 6),
    ("case_sensitive_control", {"dividend": "DIVIDEND_REG", "valid": "Busy"}, 8),
]


@pytest.mark.parametrize("label,renames,width", _R7_INTERFACE_CASES,
                         ids=[row[0] for row in _R7_INTERFACE_CASES])
def test_unsigned_divider_r7_f4_interface_compiles_and_behaves(label, renames, width, tmp_path):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("NOT_VERIFIED: iverilog/vvp unavailable for interface evidence")
    description = _INLINE_POS["unsigned_iterative_restoring_divider"]
    for before, after in renames.items():
        description = re.sub(r"\b" + before + r"(?=\[|:)", after, description)
    source, rtl = tmp_path / "description.txt", tmp_path / "unit.v"
    source.write_text(description)
    run = subprocess.run([sys.executable, str(PROG), "--from-desc", str(source),
                          "--out", str(rtl)], capture_output=True, text=True)
    assert json.loads(run.stdout)["verdict"] == "EMIT"
    assert run.returncode == 0, run.stdout + run.stderr
    import design_one_shot_runner as runner
    project = tmp_path / "project"
    prompt = project / "phase1/input_doc/design_description.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(description)
    step = runner._try_canonical_primitive_rtl(project, time.time())
    assert step is not None and step.status == "PASS"
    consumer_rtl = list(project.glob("phase2/stage1/rtl/*.v"))
    assert len(consumer_rtl) == 1
    assert consumer_rtl[0].read_bytes() == rtl.read_bytes()
    vectors = _native_divider_vectors(width, exhaustive=width == 6)
    tb_text = _native_divider_tb(width, vectors)
    for before, after in renames.items():
        tb_text = tb_text.replace("." + before + "(", "." + after + "(")
    tb, sim = tmp_path / "tb.v", tmp_path / "sim"
    tb.write_text(tb_text)
    compile_run = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(sim),
                                  str(rtl), str(tb)], capture_output=True, text=True)
    assert compile_run.returncode == 0, compile_run.stdout + compile_run.stderr
    native = subprocess.run(["vvp", str(sim)], capture_output=True, text=True, timeout=45)
    assert native.returncode == 0, native.stdout + native.stderr
    assert f"PASS width={width}" in native.stdout, native.stdout + native.stderr
    print(f"INTERFACE_NATIVE_PASS case={label} width={width} vectors={len(vectors)}")


@pytest.mark.parametrize("modal", ["may", "can", "could", "might"])
@pytest.mark.parametrize("synonyms", [False, True], ids=["roles", "synonyms"])
def test_unsigned_divider_r7_f5_modal_ordering_allowance(modal, synonyms, tmp_path):
    lhs, rhs = ("numerator", "denominator") if synonyms else ("dividend", "divisor")
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           f"The {lhs} {modal} be less than the {rhs}.", False, tmp_path)


@pytest.mark.parametrize("modal", ["could", "might"])
@pytest.mark.parametrize("scope", ["denied", "quoted", "reference", "conditional"])
def test_unsigned_divider_r7_f5_scoped_allowance(modal, scope, tmp_path):
    if scope == "denied":
        allowance = f"The dividend {modal} not be less than divisor."
    elif scope == "quoted":
        allowance = f'A discarded example says "the dividend {modal} be less than divisor".'
    elif scope == "reference":
        allowance = f"The dividend {modal} be less than divisor in the reference model."
    else:
        allowance = f"If a diagnostic guard is installed, dividend {modal} be less than divisor."
    _r5_assert_publication("The divisor is nonzero. Dividend is at least divisor. "
                           + allowance, True, tmp_path)


def _r2_unsigned_divider_variants():
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    return [
        ("valid_hold_until_request",
         desc.replace("valid: one-cycle completion.",
                      "valid: remains asserted until next request."),
         "one-cycle valid"),
        ("zero_divisor_uncertain",
         desc.replace(
             "Both operands are nonzero, and dividend is at least divisor.",
             "Do not assume nonzero; the divisor may be zero."),
         "zero divisor"),
        ("reset_not_active_low_async",
         desc.replace("rst: active-low asynchronous reset.",
                      "rst: reset is not active-low asynchronous."),
         "reset"),
        ("reset_active_low_not_async",
         desc.replace("rst: active-low asynchronous reset.",
                      "rst: active-low reset is not asynchronous."),
         "reset"),
        ("request_not_one_cycle",
         desc.replace("start: one-cycle request.",
                      "start: request is not one-cycle."),
         "one-cycle request"),
        ("latency_width_plus_two",
         desc.replace("WIDTH+1 cycles otherwise", "WIDTH+2 cycles otherwise"),
         "latency"),
        ("unsigned_not_explicit",
         desc.replace("Design an unsigned iterative", "Design an iterative")
         .replace("unsigned dividend", "dividend")
         .replace("unsigned divisor", "divisor")
         .replace("unsigned quotient", "quotient")
         .replace("unsigned remainder", "remainder"),
         "explicit unsigned"),
        ("zero_divisor_exact_supplement",
         desc.replace(
             "Both operands are nonzero, and dividend is at least divisor.",
             "The dividend is nonzero, and the divisor may be zero."),
         "zero divisor"),
        ("conflicting_module_declarations",
         desc.replace("Module name: unsigned_ratio_unit",
                      "Module name: unsigned_ratio_unit\n"
                      "Module name: other_ratio_unit"),
         "conflicting module"),
        ("extra_enable_port",
         desc.replace("start: one-cycle request.",
                      "start: one-cycle request.\n"
                      "enable: one-cycle enable."),
         "unsupported extra"),
        ("vector_clock",
         desc.replace("clk: posedge clock.",
                      "clk[1:0]: posedge clock."),
         "clock control"),
        ("vector_reset",
         desc.replace("rst: active-low asynchronous reset.",
                      "rst[1:0]: active-low asynchronous reset."),
         "reset control"),
        ("vector_request",
         desc.replace("start: one-cycle request.",
                      "start[1:0]: one-cycle request."),
         "start control"),
        ("vector_valid",
         desc.replace("valid: one-cycle completion.",
                      "valid[1:0]: one-cycle completion."),
         "valid control"),
        ("lowercase_width_parameter",
         desc.replace("Parameter WIDTH", "Parameter width")
         .replace("[WIDTH-1:0]", "[width-1:0]"),
         "uppercase WIDTH"),
        ("one_operand_two_roles",
         desc.replace(
             "dividend[WIDTH-1:0]: unsigned dividend.\n"
             "divisor[WIDTH-1:0]: unsigned divisor.",
             "operand[WIDTH-1:0]: unsigned operand used as both dividend "
             "and divisor."),
         "distinct ports"),
    ]


@pytest.mark.parametrize("label,desc,needle", _r2_unsigned_divider_variants())
def test_unsigned_divider_r2_adversarial_contracts_defer(label, desc, needle):
    reason = rcs.route_to_ai_reason(desc)
    assert rcs.detect_shape(desc) is None, label
    assert reason is not None and reason["kind"] == (
        "unsupported_unsigned_iterative_divider"), label
    assert any(needle.lower() in item.lower()
               for item in reason["unresolved"]), (label, reason)


def _native_divider_vectors(width, exhaustive=False):
    """Independent legal operands and Python's mathematical / and % oracle."""
    limit = (1 << width) - 1
    if width <= 4 or exhaustive:
        pairs = [(a, b) for b in range(1, limit + 1)
                 for a in range(b, limit + 1)]
    else:
        edges = [(b, b) for b in (1, 2, limit // 2, limit - 1, limit)]
        edges += [(limit, 1), (limit, limit // 2), (limit - 1, 3)]
        # Deterministic bounded samples keep WIDTH=8/9/12 practical while
        # preserving the source-declared nonzero a>=b domain.
        samples = []
        state = 0x2851 + width
        for _ in range(32):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            b = 1 + (state % limit)
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            a = b + (state % (limit - b + 1))
            samples.append((a, b))
        pairs = edges + samples
    return [(a, b, a // b, a % b) for a, b in pairs]


def _native_divider_tb(width, vectors):
    checks = "\n".join(
        f"        check_div({a}, {b}, {q}, {r});"
        for a, b, q, r in vectors)
    first_a, first_b, first_q, first_r = vectors[0]
    second_a, second_b, second_q, second_r = vectors[min(1, len(vectors) - 1)]
    reset_a = max(2, (1 << width) - 1)
    reset_b = 1
    return f'''`timescale 1ns/1ps
module tb;
    localparam integer WIDTH = {width};
    localparam integer EXPECTED_LATENCY = ((WIDTH & (WIDTH - 1)) == 0)
        ? WIDTH : WIDTH + 1;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;
    reg start = 1'b0;
    reg [WIDTH-1:0] dividend = '0;
    reg [WIDTH-1:0] divisor = '0;
    wire [WIDTH-1:0] quotient;
    wire [WIDTH-1:0] remainder;
    wire valid;
    integer failures = 0;
    integer checks = 0;

    unsigned_ratio_unit #(.WIDTH(WIDTH)) dut (
        .clk(clk), .rst(rst), .start(start), .dividend(dividend),
        .divisor(divisor), .quotient(quotient), .remainder(remainder),
        .valid(valid));

    task automatic fail(input [1023:0] why);
        begin
            failures = failures + 1;
            $display("FAIL width=%0d %0s", WIDTH, why);
        end
    endtask

    task automatic check_div(input integer a_i, input integer b_i,
                             input integer q_i, input integer r_i);
        integer cycles;
        begin
            @(negedge clk);
            dividend = a_i;
            divisor = b_i;
            start = 1'b1;
            @(posedge clk); #1;
            start = 1'b0;
            // The DUT must use its latched operands after the request edge.
            dividend = '0;
            divisor = '0;
            cycles = 1;
            while (!valid && cycles <= WIDTH + 2) begin
                @(posedge clk); #1;
                cycles = cycles + 1;
            end
            checks = checks + 1;
            if (!valid)
                fail("valid never asserted");
            else if (cycles != EXPECTED_LATENCY)
                begin
                    fail("latency mismatch");
                    $display("DETAIL width=%0d got=%0d expected=%0d",
                             WIDTH, cycles, EXPECTED_LATENCY);
                end
            else if (quotient !== q_i || remainder !== r_i)
                fail("independent quotient/remainder oracle mismatch");
            @(posedge clk); #1;
            if (valid)
                fail("valid was wider than one cycle");
        end
    endtask

    task automatic check_back_to_back(
        input integer a1_i, input integer b1_i, input integer q1_i,
        input integer r1_i, input integer a2_i, input integer b2_i,
        input integer q2_i, input integer r2_i);
        integer cycles;
        begin
            // The second request is presented on the first falling edge after
            // the first result pulse, so its rising edge is the earliest
            // legal acceptance edge for both latency conventions.
            @(negedge clk);
            dividend = a1_i;
            divisor = b1_i;
            start = 1'b1;
            @(posedge clk); #1;
            start = 1'b0;
            dividend = '0;
            divisor = '0;
            cycles = 1;
            while (!valid && cycles <= WIDTH + 2) begin
                @(posedge clk); #1;
                cycles = cycles + 1;
            end
            checks = checks + 1;
            if (!valid || cycles != EXPECTED_LATENCY ||
                quotient !== q1_i || remainder !== r1_i)
                fail("back-to-back first result mismatch");

            @(negedge clk);
            dividend = a2_i;
            divisor = b2_i;
            start = 1'b1;
            @(posedge clk); #1;
            start = 1'b0;
            dividend = '0;
            divisor = '0;
            cycles = 1;
            while (!valid && cycles <= WIDTH + 2) begin
                @(posedge clk); #1;
                cycles = cycles + 1;
            end
            checks = checks + 1;
            if (!valid || cycles != EXPECTED_LATENCY ||
                quotient !== q2_i || remainder !== r2_i)
                fail("back-to-back second result mismatch");
            @(posedge clk); #1;
            if (valid)
                fail("back-to-back valid was wider than one cycle");
        end
    endtask

    initial begin
        #1;
        rst = 1'b0;
        #1;
        if (valid !== 1'b0 || quotient !== '0 || remainder !== '0)
            fail("initial active-low reset did not clear outputs");
        rst = 1'b1;

        // Assert reset between edges while a multi-cycle request is busy.
        if (WIDTH >= 2) begin
            @(negedge clk);
            dividend = {reset_a};
            divisor = {reset_b};
            start = 1'b1;
            @(posedge clk); #1;
            start = 1'b0;
            #2;
            rst = 1'b0;
            #1;
            if (valid !== 1'b0 || quotient !== '0 || remainder !== '0)
                fail("asynchronous reset did not clear busy result");
            @(negedge clk);
            rst = 1'b1;
        end

{checks}
        check_back_to_back({first_a}, {first_b}, {first_q}, {first_r},
                           {second_a}, {second_b}, {second_q}, {second_r});
        if (failures != 0)
            $fatal(1, "native divider checks failed: %0d", failures);
        $display("PASS width=%0d checks=%0d latency=%0d", WIDTH, checks,
                 EXPECTED_LATENCY);
        $finish;
    end
endmodule
'''


def _run_native_divider_case(root, rtl_text, width, vectors):
    rtl = root / f"divider_{width}.v"
    tb = root / f"tb_{width}.v"
    sim = root / f"sim_{width}"
    rtl.write_text(rtl_text)
    tb.write_text(_native_divider_tb(width, vectors))
    compile_run = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(sim),
         str(rtl), str(tb)], capture_output=True, text=True)
    assert compile_run.returncode == 0, compile_run.stdout + compile_run.stderr
    return subprocess.run(["vvp", str(sim)], capture_output=True, text=True,
                          timeout=45)


def test_unsigned_divider_native_oracle_latency_reset_back_to_back_and_reverse():
    """Compile the emitted RTL and use unchanged independent / and % checks.

    The final run uses the same generated testbench and oracle against a
    restoration mutation; a mutation that returns the pre-shift remainder must
    redden rather than receiving a source-string-only pass.
    """
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("NOT_MEASURED: iverilog/vvp unavailable in canonical image")
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    rtl = rcs.emit_rtl("unsigned_iterative_restoring_divider", desc)
    work = Path(tempfile.mkdtemp(prefix="issue2851-native-"))
    try:
        vectors_by_width = {
            width: _native_divider_vectors(width)
            for width in (1, 2, 3, 4, 8, 9, 12)
        }
        for width, vectors in vectors_by_width.items():
            run = _run_native_divider_case(work, rtl, width, vectors)
            assert run.returncode == 0, run.stdout + run.stderr
            assert f"PASS width={width}" in run.stdout, run.stdout + run.stderr
            print(f"NATIVE_PASS width={width} vectors={len(vectors)}")

        mutation = rtl.replace(
            "        : shifted_remainder;\n",
            "        : partial_remainder;\n", 1)
        assert mutation != rtl
        reverse = _run_native_divider_case(
            work, mutation, 3, vectors_by_width[3])
        assert reverse.returncode != 0, reverse.stdout + reverse.stderr
        assert "FAIL width=3" in reverse.stdout, reverse.stdout + reverse.stderr
        print("REVERSE_PASS mutation=restore_shifted_remainder caught=oracle")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _native_width_gap_case(width, include_restore_reverse=True):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    rtl = rcs.emit_rtl("unsigned_iterative_restoring_divider", desc)
    vectors = _native_divider_vectors(width, exhaustive=True)
    work = Path(tempfile.mkdtemp(prefix=f"issue2851-native-w{width}-"))
    try:
        run = _run_native_divider_case(work, rtl, width, vectors)
        assert run.returncode == 0, run.stdout + run.stderr
        assert f"PASS width={width}" in run.stdout, run.stdout + run.stderr
        print(f"NATIVE_PASS width={width} vectors={len(vectors)} latched_operands=PASS")

        if include_restore_reverse:
            restore = rtl.replace(
                "        : shifted_remainder;\n",
                "        : partial_remainder;\n", 1)
            assert restore != rtl
            reverse_restore = _run_native_divider_case(
                work, restore, width, vectors)
            assert reverse_restore.returncode != 0
            assert "FAIL width=" + str(width) in reverse_restore.stdout
            print(f"REVERSE_PASS width={width} mutation=restore_shifted_remainder")

        # Reverse the request-edge trial into a real input-only cycle. The
        # internal operands are still latched, but every legal result arrives
        # one edge later, so the unchanged latency/oracle assertions must redden.
        input_only = rtl
        input_only = input_only.replace(
            "if (count == WIDTH - 2) begin",
            "if (count == WIDTH - 1) begin", 1)
        input_only = input_only.replace(
            "dividend_reg      <= dividend << 1;",
            "dividend_reg      <= dividend;", 1)
        input_only = input_only.replace(
            "quotient_reg      <= start_ge_divisor;",
            "quotient_reg      <= {WIDTH{1'b0}};", 1)
        input_only = input_only.replace(
            "partial_remainder <= start_remainder;",
            "partial_remainder <= {(WIDTH + 1){1'b0}};", 1)
        assert input_only != rtl
        reverse_input = _run_native_divider_case(
            work, input_only, width, vectors)
        assert reverse_input.returncode != 0
        assert "latency mismatch" in reverse_input.stdout
        print(f"REVERSE_PASS width={width} mutation=input_only_cycle")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_unsigned_divider_native_width6_latched_and_reverse_gap():
    _native_width_gap_case(6)


def test_unsigned_divider_native_width8_exhaustive_latched_and_reverse_gap():
    _native_width_gap_case(8, include_restore_reverse=False)


def test_parallel2serial_dout_is_combinational():
    """The load-bearing property: the parallel2serial template must drive dout
    with a CONTINUOUS assign (combinational MSB of the shift register), never a
    registered `dout <=`. Registering it delays every serial bit one cycle — the
    exact r8 failure this shape was added to fold in. This test FAILS if a future
    edit registers dout."""
    rtl = rcs.emit_rtl("parallel_to_serial_4")
    # strip // comments so the explanatory prose can't satisfy/trip the checks
    code = "\n".join(re.sub(r"//.*$", "", ln) for ln in rtl.splitlines())
    assert re.search(r"assign\s+dout\s*=", code), "dout must be a continuous assign"
    assert not re.search(r"\bdout\s*<=", code), "dout must NOT be registered"
    # dout is a plain wire output (not `output reg`)
    assert re.search(r"output\s+dout\b", code), "dout must be a wire output, not reg"


# ============================================================================
# Runner-integration: the step_rtl_gen hook _try_canonical_primitive_rtl must
# fire on a project whose phase1/input_doc description states a canonical shape,
# emit RTL to phase2/stage1/rtl/, and DEFER (None) on a non-matching project.
# Self-contained (inline description); no external dataset.
# ============================================================================
def _load_runner():
    sys.path.insert(0, str(PROGRAMS))
    import design_one_shot_runner as mod  # noqa: E402
    return mod


def _mk_project(tmp_path, desc_text):
    idoc = tmp_path / "phase1" / "input_doc"
    idoc.mkdir(parents=True)
    (idoc / "design_description.txt").write_text(desc_text)
    return tmp_path


def test_hook_fires_and_emits(tmp_path):
    R = _load_runner()
    proj = _mk_project(tmp_path, _INLINE_POS["pulse_detect_0to1to0"])
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras.get("deterministic_generator") == "canonical_primitive_synth"
    assert res.extras.get("shape") == "pulse_detect_0to1to0"
    emitted = list((proj / "phase2" / "stage1" / "rtl").glob("*.v"))
    assert [p.name for p in emitted] == ["pulse_detect.v"]
    assert "module pulse_detect" in emitted[0].read_text()


def test_hook_defers_on_nonmatching(tmp_path):
    R = _load_runner()
    proj = _mk_project(tmp_path, _INLINE_NEG[1])   # a plain 8-bit adder
    assert R._try_canonical_primitive_rtl(proj, 0.0) is None


def test_hook_author_guard_never_overwrites(tmp_path):
    R = _load_runner()
    proj = _mk_project(tmp_path, _INLINE_POS["pulse_detect_0to1to0"])
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "existing.v").write_text("module existing(); endmodule\n")
    # RTL already present → the guard must DEFER (never clobber the design's own).
    assert R._try_canonical_primitive_rtl(proj, 0.0) is None


def test_unsigned_divider_normal_consumer_emits_and_preserves_occupied_output(tmp_path):
    R = _load_runner()
    proj = _mk_project(
        tmp_path / "project", _INLINE_POS["unsigned_iterative_restoring_divider"])
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    output = proj / "phase2" / "stage1" / "rtl" / "unsigned_ratio_unit.v"
    assert output.is_file()
    before = output.read_text()
    assert "module unsigned_ratio_unit" in before
    assert R._try_canonical_primitive_rtl(proj, 0.0) is None
    assert output.read_text() == before


@pytest.mark.parametrize("mode", ["project", "direct"])
@pytest.mark.parametrize("occupied", ["file", "symlink", "dangling_symlink"])
def test_unsigned_divider_cli_preserves_occupied_output(tmp_path, mode, occupied):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    proj = _mk_project(tmp_path / "project", desc)
    # Use the explicit INPUT location read by the existing project CLI.
    input_dir = proj / "input"
    input_dir.mkdir()
    source = input_dir / "design_description.txt"
    source.write_text(desc)
    output = proj / "phase2" / "stage1" / "rtl" / "unsigned_ratio_unit.v"
    output.parent.mkdir(parents=True)
    author_bytes = b"// author's supplied RTL\nmodule authored; endmodule\n"
    target = tmp_path / "author.v"
    if occupied == "file":
        output.write_bytes(author_bytes)
    else:
        if occupied == "symlink":
            target.write_bytes(author_bytes)
        output.symlink_to(target)
    link_before = os.readlink(output) if output.is_symlink() else None
    argv = ([str(proj), "--emit"] if mode == "project" else
            ["--from-desc", str(source), "--out", str(output)])
    run = subprocess.run([sys.executable, str(PROG), *argv],
                         capture_output=True, text=True)
    result = json.loads(run.stdout)
    preserved = (output.read_bytes() == author_bytes if occupied == "file"
                 else output.is_symlink() and os.readlink(output) == link_before
                 and (target.read_bytes() == author_bytes if occupied == "symlink"
                      else not target.exists()))
    print(json.dumps({"id": f"occupied_{mode}_{occupied}", "rc": run.returncode,
                      "verdict": result["verdict"], "preserved": preserved}))
    assert run.returncode == 2, run.stdout + run.stderr
    assert result["verdict"] == "REFUSED"
    assert result["reason"] == "occupied output preserved"
    assert preserved


def test_unsigned_divider_project_cli_emits_fresh_source_bound_output(tmp_path):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    proj = _mk_project(tmp_path / "project", desc)
    input_dir = proj / "input"
    input_dir.mkdir()
    (input_dir / "design_description.txt").write_text(desc)
    run = subprocess.run([sys.executable, str(PROG), str(proj), "--emit"],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    output = proj / "phase2" / "stage1" / "rtl" / "unsigned_ratio_unit.v"
    assert result["verdict"] == "EMIT"
    assert result["written"] == str(output)
    assert output.read_text() == rcs.emit_rtl(rcs._UNSIGNED_DIVISION_SHAPE, desc)
    assert result["source_sha256"] in output.read_text()


@pytest.mark.parametrize("ancestor", ["phase2", "phase2/stage1/rtl"])
def test_unsigned_divider_project_cli_refuses_ancestor_symlink(
        tmp_path, ancestor, capsys):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    proj = _mk_project(tmp_path / "project", desc)
    source = proj / "input" / "design_description.txt"
    source.parent.mkdir(parents=True)
    source.write_text(desc)
    external = tmp_path / "external"
    external.mkdir()
    link = proj / ancestor
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(external, target_is_directory=True)

    rc = rcs.main([str(proj), "--emit"])
    result = json.loads(capsys.readouterr().out)
    assert (rc, result["verdict"]) == (2, "REFUSED")
    assert "SOURCE_BOUND_PROJECT_REFUSED" in result["reason"]
    assert link.is_symlink() and link.resolve() == external
    assert not list(external.iterdir())


def test_unsigned_divider_project_cli_refuses_source_mutation_before_commit(
        tmp_path, monkeypatch, capsys):
    desc = _INLINE_POS["unsigned_iterative_restoring_divider"]
    proj = _mk_project(tmp_path / "project", desc)
    source = proj / "input" / "design_description.txt"
    source.parent.mkdir(parents=True)
    source.write_text(desc)
    changed = desc.replace("default value of 9", "default value of 12")
    original_emit = rcs.emit_rtl

    def mutate_live_source(shape, source_text):
        source.write_text(changed)
        return original_emit(shape, source_text)

    monkeypatch.setattr(rcs, "emit_rtl", mutate_live_source)
    rc = rcs.main([str(proj), "--emit"])
    result = json.loads(capsys.readouterr().out)
    assert (rc, result["verdict"]) == (2, "REFUSED")
    assert "SOURCE_BOUND_PROJECT_REFUSED" in result["reason"]
    assert "held project" in result["reason"]
    assert not list((proj / "phase2").rglob("*.v"))
    assert "default value of 12" in source.read_text()


# ============================================================================
# issue #2035, families F6 + F7, and the architecture question underneath them.
#
# MEASURED FIRST (base 764d6b3e5, host 8HD-8): two neutral input-only
# descriptions naming `Module name: barrel_shifter` with ports in/ctrl/out both
# returned EMIT rc=0 and were overwritten with the fixed three-mux hierarchy --
# one of them while the input said in plain words that no submodule and no
# generate block may be used. Detection was doing duty as topology selection,
# which is why an ALTERNATIVE-ARCHITECTURE CONTROL could not be satisfied at all.
#
# These tests pin, in order: the sixteen templates do not move; a stated
# structural directive withdraws a template and is NAMED for the AI author; and
# F6/F7 are COMPOSED from the acceptance contract the input states rather than
# from a seventeenth and eighteenth fixed template.
# ============================================================================

_ARCH_CONFLICT_DESC = (
    "Module name:\n    barrel_shifter\n"
    "A barrel shifter for shifting bits efficiently, controlled by ctrl.\n"
    "Input ports:\n in: 8-bit input to be shifted.\n ctrl: 3-bit shift amount.\n"
    "Output ports:\n out: 8-bit shifted output.\n"
    "This block is delivered as a single leaf cell: the implementation must not\n"
    "instantiate any submodule and must not use a generate block.\n")

_F6_DESC = (
    "Module name:\n    elastic_stage\n"
    "An elastic pipeline stage between a producer and a consumer.\n"
    "Input ports:\n clk: Clock signal.\n rst_n: Active low reset signal.\n"
    " up_data [7:0]: The 8-bit word offered by the producer.\n"
    " up_valid: High when the producer is offering up_data.\n"
    " dn_ready: High when the consumer can take a word this cycle.\n"
    "Output ports:\n up_ready: High when this stage can take a word.\n"
    " dn_data [7:0]: The word offered to the consumer.\n"
    " dn_valid: High when dn_data is being offered.\n"
    "Implementation:\n"
    "A transfer happens when that interface's valid and ready are both high.\n"
    "The stage must register the output and buffer one additional transfer so\n"
    "the producer is only stalled when no slot is free. No word that was not\n"
    "accepted may be captured, no accepted word may be lost under backpressure,\n"
    "and accepted words must leave in the order they arrived.\n")

# Same shape, same words, a DIFFERENT legitimate architecture: zero added
# latency. This is the alternative-architecture control for the contract layer.
_F6_STORAGE_SENTENCE = (
    "The stage must register the output and buffer one additional transfer so\n"
    "the producer is only stalled when no slot is free. ")
assert _F6_STORAGE_SENTENCE in _F6_DESC, "fixture drifted"

_F6_ALT_DESC = _F6_DESC.replace(
    _F6_STORAGE_SENTENCE,
    "This stage must not add latency: the offered word is seen by the consumer\n"
    "in the same cycle it is offered. ")

# Same shape with the storage policy simply NOT STATED: must route to AI by name.
_F6_UNSTATED_DESC = _F6_DESC.replace(_F6_STORAGE_SENTENCE, "")

_F7_DESC = (
    "Module name:\n    pulse_divider\n"
    "An event ratio divider.\n"
    "Input ports:\n clk: Clock signal.\n rst_n: Active low reset signal.\n"
    " in_data [7:0]: The 8-bit payload accompanying an input event.\n"
    " in_valid: Pulses high for one cycle on each input event.\n"
    "Output ports:\n out_data [7:0]: The forwarded payload.\n"
    " out_valid: Pulses high for one cycle on each output event.\n"
    "Implementation:\n"
    "The divider emits one output event for every 1 input events. Counting an\n"
    "input event and emitting the output event are the same cycle's work.\n")


def test_templates_are_byte_identical_to_their_own_text():
    """The contract layer must not re-author a working emitter: every template
    shape still emits exactly its `_TEMPLATES` entry, and `desc_text` is ignored
    for them. Compared by MEMBERSHIP of the shape-key set, not by count."""
    assert set(rcs._TEMPLATES) <= {k for k, _ in rcs._DETECTORS}
    for shape, text in rcs._TEMPLATES.items():
        assert rcs.emit_rtl(shape) == text
        assert rcs.emit_rtl(shape, _F6_DESC) == text


def test_stated_directive_withdraws_the_fixed_topology():
    """OLD WRONG BEHAVIOUR, on input-only material: this description matches the
    barrel-shifter detector while forbidding the very structure the template is
    built from, and used to be answered with that template anyway."""
    assert rcs._is_barrel_shifter(
        _ARCH_CONFLICT_DESC, rcs.module_name_of(_ARCH_CONFLICT_DESC),
        rcs._port_tokens(_ARCH_CONFLICT_DESC) - rcs._NOISE) is True
    conflict = rcs.architecture_conflict(
        _ARCH_CONFLICT_DESC, "barrel_shifter_right_8")
    assert conflict is not None
    assert conflict["polarity"] == "forbid"
    assert conflict["property"] in {"submodule_instantiation", "generate_block"}
    assert rcs.detect_shape(_ARCH_CONFLICT_DESC) is None


def test_withdrawn_topology_is_routed_to_ai_by_name():
    """No hidden DEFER: the program says WHICH stated directive it could not
    honour, so the AI author is handed the decision rather than guessing it."""
    why = rcs.route_to_ai_reason(_ARCH_CONFLICT_DESC)
    assert why is not None and why["route"] == "ai_author"
    assert why["kind"] == "architecture_conflict"
    assert why["shape_declined"] == "barrel_shifter_right_8"
    assert "must not" in why["stated"].lower()


@pytest.mark.parametrize("shape,desc", _INLINE_POS.items())
def test_canonical_descriptions_state_no_conflicting_directive(shape, desc):
    """The withdrawal must not fire on ordinary prose: every canonical
    description still detects its own shape, i.e. the DEFER population grew only
    for inputs that really do state a contradicting directive."""
    assert rcs.architecture_conflict(desc, shape) is None
    assert rcs.detect_shape(desc) == shape


def test_template_commitments_are_derived_from_the_template_text():
    """Commitments are read out of the emitted RTL, so a re-authored template
    cannot leave a hand-written second list behind, stale."""
    barrel = rcs.template_commitments("barrel_shifter_right_8")
    assert {"submodule_instantiation", "generate_block"} <= barrel
    assert "gray_code" not in barrel
    assert "gray_code" in rcs.template_commitments("async_gray_fifo")


def test_f6_contract_is_extracted_from_the_input():
    c = rcs.extract_handshake_contract(_F6_DESC)
    assert c is not None and c.kind == "elastic_stage"
    assert c.unresolved == []
    assert (c.up["valid"], c.up["ready"], c.up["data"]) == (
        "up_valid", "up_ready", "up_data")
    assert (c.down["valid"], c.down["ready"], c.down["data"]) == (
        "dn_valid", "dn_ready", "dn_data")
    assert c.width == 8 and c.storage == "skid" and c.ordering == "fifo"
    assert c.clock == "clk" and c.reset == "rst_n" and c.reset_active_low is True


def test_f6_is_composed_not_templated():
    """F6 is a consumer of the contract layer: no `_TPL_` exists for it, and the
    emitted module carries the INPUT's own module and port names."""
    assert "elastic_handshake_stage" not in rcs._TEMPLATES
    shape = rcs.detect_shape(_F6_DESC)
    assert shape == "elastic_handshake_stage"
    rtl = rcs.emit_rtl(shape, _F6_DESC)
    assert "module elastic_stage (" in rtl
    for port in ("up_valid", "up_ready", "up_data",
                 "dn_valid", "dn_ready", "dn_data"):
        assert port in rtl
    # acceptance-qualified storage: every capture is gated by an ACCEPTED
    # transfer, never by valid alone.
    assert "wire up_fire = up_valid && up_ready;" in rtl
    assert "if (up_fire) held_data <= up_data;" in rtl
    assert "skid_data  <= up_data;" in rtl
    assert "assign up_ready = !skid_valid;" in rtl


def test_f6_alternative_architecture_control_stays_green():
    """THE CONTROL. Same shape words, a legitimately different architecture
    (zero added latency). It must NOT be answered with the buffered stage."""
    c = rcs.extract_handshake_contract(_F6_ALT_DESC)
    assert c is not None and c.unresolved == [] and c.storage == "passthrough"
    rtl = rcs.emit_rtl(rcs.detect_shape(_F6_ALT_DESC), _F6_ALT_DESC)
    assert "assign dn_valid = up_valid;" in rtl
    assert "assign up_ready = dn_ready;" in rtl
    assert "always" not in rtl and "skid" not in rtl
    assert rtl != rcs.emit_rtl(rcs.detect_shape(_F6_DESC), _F6_DESC)


def test_f6_unstated_storage_is_routed_to_ai_by_name_not_guessed():
    assert rcs.detect_shape(_F6_UNSTATED_DESC) is None
    why = rcs.route_to_ai_reason(_F6_UNSTATED_DESC)
    assert why is not None and why["kind"] == "unstated_contract_fields"
    assert why["contract_kind"] == "elastic_stage"
    assert any("storage under backpressure" in u for u in why["unresolved"])


def test_f7_unit_ratio_consume_and_capture_are_simultaneous():
    """F7's defect is that consume and capture are exclusive, which drops every
    other input at a unit ratio. The composed emitter does both in one cycle."""
    c = rcs.extract_handshake_contract(_F7_DESC)
    assert c is not None and c.kind == "ratio_divider"
    assert c.ratio == 1 and c.unresolved == []
    assert "event_ratio_divider" not in rcs._TEMPLATES
    rtl = rcs.emit_rtl(rcs.detect_shape(_F7_DESC), _F7_DESC)
    assert "module pulse_divider #(" in rtl
    assert "wire consume  = in_valid;" in rtl
    assert "wire emit_now = in_valid && (count == RATIO - 1);" in rtl
    # the two are separate concurrent facts about the same cycle, never an
    # if/else between consuming and capturing
    assert "out_valid <= emit_now;" in rtl
    assert "if (in_valid) out_data <= in_data;" in rtl
    assert "else if" not in rtl.split("end else begin")[1]


def test_generated_scoreboards_come_from_the_same_contract():
    """The queue scoreboard (F6) and the ratio/latency count (F7) that #2035 asks
    for are composed from the contract fields, so a stage and its check cannot
    drift apart."""
    tb6 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F6_DESC))
    assert "module tb_elastic_stage;" in tb6
    assert "if (up_valid && up_ready) begin q[wr]" in tb6
    assert "accepted transfers lost" in tb6
    tb7 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F7_DESC))
    assert "module tb_pulse_divider;" in tb7
    assert "if (n_out != n_in / 1)" in tb7
    for tb in (tb6, tb7):
        assert tb.isascii()


def test_contract_shapes_refuse_to_emit_without_their_input():
    """A composed shape has no fixed answer to fall back on: asked to emit with
    no description, it raises rather than inventing a topology."""
    for shape in rcs._CONTRACT_SHAPES:
        with pytest.raises((ValueError, KeyError)):
            rcs.emit_rtl(shape)


@pytest.mark.parametrize("desc", _INLINE_NEG)
def test_contract_layer_does_not_mis_fire_on_near_misses(desc):
    """Fail-closed is preserved: the contract layer is consulted only when no
    template claimed the input, and it declines everything that states no
    handshake."""
    assert rcs.detect_shape(desc) is None


# ============================================================================
# The second half of the same exposure: a STATED BEHAVIOUR, not a stated
# architecture. An input that matches a shape's words while stating the other
# reset behaviour used to be answered with the template anyway.
#
# Measured on the base, independently of the program (a raw scan of the sixteen
# template texts): 11 templates reset ASYNCHRONOUSLY, 3 SYNCHRONOUSLY, and 2 are
# combinational -- and nothing compared that with what the description said.
# Both sides are decidable here, which is why this dimension is closed and the
# shift-direction one (see the lane's LAND.md) is not: the pole is read out of
# the template's own always-block and reset test, never out of its prose.
# ============================================================================

_ASYNC_TEMPLATES = {
    "async_gray_fifo", "frac_clock_divider_3p5", "mealy_seq_detector_10011",
    "odd_clock_divider", "parallel_to_serial_4", "pipelined_ripple_adder_64",
    "pipelined_unsigned_multiplier_8", "pulse_detect_0to1to0",
    "serial_to_parallel_8", "traffic_light_fsm", "triangle_wave_generator_5",
}
_SYNC_TEMPLATES = {
    "ieee754_single_multiplier", "lfsr4_xnor_left", "radix2_signed_divider",
}
_COMBINATIONAL_TEMPLATES = {
    "barrel_shifter_right_8", "combinational_long_divider",
}


def test_reset_poles_are_derived_from_the_template_code():
    """Compared by MEMBERSHIP against a partition established by reading the
    template texts directly, so a template that is re-authored to reset the
    other way moves its own commitment with it."""
    derived_async = {k for k in rcs._TEMPLATES
                     if "async_reset" in rcs.template_commitments(k)}
    derived_sync = {k for k in rcs._TEMPLATES
                    if "sync_reset" in rcs.template_commitments(k)}
    derived_none = {k for k in rcs._TEMPLATES
                    if not {"async_reset", "sync_reset"}
                    & rcs.template_commitments(k)}
    assert derived_async == _ASYNC_TEMPLATES
    assert derived_sync == _SYNC_TEMPLATES
    assert derived_none == _COMBINATIONAL_TEMPLATES
    assert "active_low_reset" in rcs.template_commitments("odd_clock_divider")
    assert "active_high_reset" in rcs.template_commitments("lfsr4_xnor_left")


def test_no_canonical_description_conflicts_with_its_own_template():
    """Zero false positives on the population that must never move, and NOT
    vacuous: several of these descriptions really do state a pole, and it
    agrees."""
    stated = 0
    for shape, desc in _INLINE_POS.items():
        poles = rcs.extract_stated_reset_poles(desc)
        stated += bool(poles)
        assert rcs.architecture_conflict(desc, shape) is None, shape
        assert rcs.detect_shape(desc) == shape
    assert stated >= 6


def _flip_reset_pole(desc, pole):
    """Rewrite a description to state the OPPOSITE pole of `pole`."""
    if pole == "active_low_reset":
        return re.sub(r"[Aa]ctive[- ]low", "Active high", desc)
    if pole == "active_high_reset":
        flipped = re.sub(r"[Aa]ctive[- ]high", "Active low", desc)
        return flipped if flipped != desc else desc + "rst: Active low reset.\n"
    if pole == "async_reset":
        return desc + "The reset is a synchronous reset.\n"
    return desc + "The reset is an asynchronous reset.\n"


_POLE_CASES = [(shape, pole)
               for shape, desc in _INLINE_POS.items()
               if shape in rcs._TEMPLATES
               for pole in sorted(p for p in rcs.template_commitments(shape)
                                  if p.endswith("_reset"))
               if _flip_reset_pole(desc, pole) != desc]


@pytest.mark.parametrize("shape,pole", _POLE_CASES)
def test_stating_the_opposite_reset_pole_withdraws_the_template(shape, pole):
    """The other direction, per shape: state the pole the template does NOT
    implement and the template is withdrawn and the pole is NAMED."""
    flipped = _flip_reset_pole(_INLINE_POS[shape], pole)
    conflict = rcs.architecture_conflict(flipped, shape)
    assert conflict is not None and conflict["polarity"] == "stated"
    assert conflict["property"] == rcs._OPPOSITE_POLE[pole]
    assert rcs.detect_shape(flipped) is None
    why = rcs.route_to_ai_reason(flipped)
    assert why is not None and why["property"] == rcs._OPPOSITE_POLE[pole]


def test_a_description_stating_both_poles_records_neither():
    """Contradictory input is not a licence to pick: when both poles of a pair
    are stated the program records no pole and keeps its previous behaviour."""
    both = (_INLINE_POS["odd_clock_divider"]
            + "rst_n: Active high reset.\n")
    assert "active low" in both.lower() and "active high" in both.lower()
    assert rcs.extract_stated_reset_poles(both) == set()
    assert rcs.detect_shape(both) == "odd_clock_divider"


def test_a_pole_said_about_another_signal_is_not_a_reset_statement():
    """`active low` on a non-reset pin must not be read as a reset statement."""
    desc = (_INLINE_POS["odd_clock_divider"]
            + " enable_n: An active high enable that gates the divider.\n")
    assert rcs.extract_stated_reset_poles(desc) == {"active_low_reset"}
    assert rcs.detect_shape(desc) == "odd_clock_divider"


# ============================================================================
# The composed check has to SHIP, or a human has to remember to run it. When the
# runner composes a contract shape it now publishes the scoreboard the same
# contract produced, next to the RTL, under the author guard.
# ============================================================================

def _mk_contract_project(tmp_path, desc_text):
    idoc = tmp_path / "phase1" / "input_doc"
    idoc.mkdir(parents=True)
    (idoc / "design_description.txt").write_text(desc_text)
    return tmp_path


def test_composed_shape_publishes_its_scoreboard(tmp_path):
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p", _F6_DESC)
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras["shape"] == "elastic_handshake_stage"
    tb = proj / "phase2" / "stage1" / "tb" / "tb_elastic_stage.v"
    assert tb.is_file()
    assert res.extras["scoreboard_tb"] == str(tb)
    assert str(tb) in res.output_files
    body = tb.read_text()
    assert "module tb_elastic_stage;" in body
    assert "accepted transfers lost" in body


def test_scoreboard_never_overwrites_an_authors_testbench(tmp_path):
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p", _F6_DESC)
    tb = proj / "phase2" / "stage1" / "tb" / "tb_elastic_stage.v"
    tb.parent.mkdir(parents=True)
    tb.write_text("// an author's own testbench\n")
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert tb.read_text() == "// an author's own testbench\n"
    assert "kept the existing" in res.extras["scoreboard_tb"]
    assert str(tb) not in res.output_files


def test_template_shapes_publish_no_scoreboard(tmp_path):
    """The sixteen fixed templates own no contract, so nothing new appears next
    to them: this wiring is additive for the composed shapes only."""
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p",
                                _INLINE_POS["pulse_detect_0to1to0"])
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras["shape"] == "pulse_detect_0to1to0"
    assert res.extras.get("scoreboard_tb") is None
    assert not (proj / "phase2" / "stage1" / "tb").exists()
    assert res.output_files == [
        str(proj / "phase2" / "stage1" / "rtl" / "pulse_detect.v")]


# ============================================================================
# The published scoreboard lands in phase2/stage1/tb/, which `l12_tb_coverage_
# check` READS. Measured on a composed project: that gate goes from rc=2 ("TB
# dir not found" -- it measured nothing) to rc=1 (it measured, and the design is
# genuinely short of the L12 sequences). That is the honest direction, but the
# property that must never rot is that a generic scoreboard is not mistaken for
# coverage of a named behavioural sequence.
# ============================================================================

def _run_l12(project):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "l12_tb_coverage_check.py"), str(project)],
        capture_output=True, text=True)


def _composed_project_with_l12(tmp_path, sequence_ids):
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p", _F6_DESC)
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L12_BEHAVIORAL_SEQUENCES.json").write_text(json.dumps(
        {"sequences": [{"id": s, "description": s.lower()} for s in sequence_ids]}))
    return proj


def test_scoreboard_is_not_mistaken_for_l12_sequence_coverage(tmp_path):
    proj = _composed_project_with_l12(
        tmp_path, ["BACKPRESSURE_STALL_RECOVERY", "RESET_MID_TRANSFER"])
    run = _run_l12(proj)
    assert run.returncode == 1, run.stdout + run.stderr
    report = json.loads(
        (proj / "reports" / "phase2" / "gates" / "l12_tb_coverage.json").read_text())
    assert report["tb_dir"].endswith("phase2/stage1/tb")
    assert report["total_sequences"] == 2
    assert report["covered_sequences"] == 0


def test_the_l12_gate_really_can_see_that_directory(tmp_path):
    """The control for the test above: if the gate could not read the published
    scoreboard at all, 'zero coverage' would prove nothing. A sequence whose id
    the scoreboard does contain IS reported covered."""
    proj = _composed_project_with_l12(tmp_path, ["TB_ELASTIC_STAGE"])
    tb = proj / "phase2" / "stage1" / "tb" / "tb_elastic_stage.v"
    assert "tb_elastic_stage" in tb.read_text()
    run = _run_l12(proj)
    report = json.loads(
        (proj / "reports" / "phase2" / "gates" / "l12_tb_coverage.json").read_text())
    assert report["covered_sequences"] == 1, run.stdout + run.stderr
    assert run.returncode == 0


# ============================================================================
# WHAT A DETECTOR NEVER LOOKS AT, IT CANNOT REFUSE.
#
# `barrel_left` -- an input matching the barrel-shifter detector while asking for
# a shift in the other direction -- is still answered with the right-shift
# template, and three attempts to close that measured why it is not free:
#
#   1. prose-derived behavioural poles are unreliable: scanning the sixteen
#      templates' own header comments for six polar pairs, ieee754 reads as
#      "left shift"/"signed" from incidental mantissa wording and two more read
#      as BOTH poles of signedness -- 2 of 16 misleading before any input;
#   2. code-derived shift direction is an IMPLEMENTATION detail, not the block's
#      behaviour: of the five templates that yield an unambiguous pole from
#      their code, three (gray-code FIFO, partial-product multiplier, restoring
#      divider) shift internally for reasons unrelated to what they promise;
#   3. the general table-free rule -- "if the input states a polar dimension the
#      matched detector never examines, DEFER" -- costs exactly one canonical
#      shape: parallel_to_serial_4's description states MSB-first and its
#      detector examines conversion wording, not bit order.
#
# That price is a decision, not a defect, so nothing here changes behaviour. What
# this test DOES do is stop the blindness growing silently: a new shape, or an
# edited detector, that leaves a stated polar dimension unexamined fails here and
# has to be looked at by a person.
# ============================================================================

_POLAR_DIMENSIONS = {
    "shift_direction": ("left", "right"),
    "bit_order": ("msb", "lsb", "most significant", "least significant"),
    "signedness": ("signed", "unsigned"),
    "clock_edge": ("rising edge", "falling edge", "posedge", "negedge",
                   "double-edge"),
}

# The one known blind spot, named rather than tolerated silently. Its template IS
# MSB-first, so today's answer is right; nothing checks that it stays right.
_KNOWN_UNEXAMINED = {("parallel_to_serial_4", "bit_order")}


def _detector_literals(shape):
    """Every string literal the detector for `shape` tests, read from source.

    Introspection, not a hand-maintained list: an edited detector moves this on
    its own.  The unsigned divider detector delegates its source contract to a
    parser helper, so include that helper's literals in the same audit."""
    import ast as _ast
    fn_name = dict(rcs._DETECTORS)[shape].__name__
    names = {fn_name}
    if shape == "unsigned_iterative_restoring_divider":
        names.add("_unsigned_division_observation")
    src = (PROGRAMS / "canonical_primitive_synth.py").read_text()
    found = set()
    literals = set()
    for node in _ast.parse(src).body:
        if isinstance(node, _ast.FunctionDef) and node.name in names:
            found.add(node.name)
            literals.update(n.value.lower() for n in _ast.walk(node)
                            if isinstance(n, _ast.Constant) and isinstance(n.value, str))
    if found == names:
        return literals
    raise AssertionError(f"detector source for {shape} not found")


def _names_word(phrase, text):
    """Word-boundary containment. `"signed" in "unsigned"` and `"mux" in "demux"`
    are both true and both wrong, so this module asks the same question the
    program now asks."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


@pytest.mark.parametrize("shape,desc", _INLINE_POS.items())
def test_a_stated_polar_dimension_is_one_the_detector_examines(shape, desc):
    examined = " | ".join(sorted(_detector_literals(shape)))
    low = desc.lower()
    for dim, words in _POLAR_DIMENSIONS.items():
        if not any(_names_word(w, low) for w in words):
            continue                      # the input states nothing here
        if (shape, dim) in _KNOWN_UNEXAMINED:
            continue                      # the recorded exception, above
        assert any(_names_word(w, examined) for w in words), (
            f"{shape} answers a description that states {dim}, but its detector "
            f"never examines that dimension: an input stating the other pole "
            f"would get this template anyway")


def test_the_known_blind_spot_is_still_exactly_one():
    """If this fails, a shape has been added or a detector edited so that the
    blindness above grew. That is the moment to take the decision, not later."""
    blind = set()
    for shape, desc in _INLINE_POS.items():
        examined = " | ".join(sorted(_detector_literals(shape)))
        low = desc.lower()
        for dim, words in _POLAR_DIMENSIONS.items():
            if (any(_names_word(w, low) for w in words)
                    and not any(_names_word(w, examined) for w in words)):
                blind.add((shape, dim))
    assert blind == _KNOWN_UNEXAMINED


# ============================================================================
# A CHECK THAT CANNOT FAIL IS NOT A CHECK. Measured by mutating the composed RTL
# 13 valid ways and running each against the generated scoreboard: the first
# version killed 9 and let three through, of which two were real holes --
#   * a stage that back-pressures when it does not have to passed at reduced
#     throughput (59 transfers instead of 82): correctness was checked, the
#     contract's "stalled only when no slot is free" clause was not;
#   * a stage whose reset never clears passed with ZERO transfers observed --
#     a vacuous pass, the checker reporting success on a run that did nothing.
# (The third, an unconditional capture inside the branch where up_ready is
# already high, survives CORRECTLY -- and the claim is bounded-PROVED rather than
# argued: yosys `miter -equiv` + `sat -seq 24 -set-init-zero -prove-asserts`
# reports SUCCESS on the OBSERVABLE interface {up_ready, dn_valid, dn_data
# qualified by dn_valid}. The unqualified comparison does NOT prove -- dn_data
# genuinely differs while dn_valid is low -- so "equivalent" here means
# observationally equivalent, not bit-identical. The same harness FAILS on the
# m6 stall mutant, so it is not a proof that proves anything.)
# Both holes are closed in the generator, so every composed design gets the
# stronger check; the kill rate is now 12 of 13. Evidence: the lane's killtest/.
# ============================================================================

def test_the_elastic_scoreboard_checks_the_no_needless_stall_clause():
    tb = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F6_DESC))
    assert "stalled at cycle" in tb
    assert "if (!up_ready) begin" in tb


def test_neither_scoreboard_can_pass_vacuously():
    tb6 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F6_DESC))
    assert "if (rd < 32) begin" in tb6
    assert "only %0d transfers observed" in tb6
    tb7 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F7_DESC))
    assert "if (n_in == 0) begin" in tb7
    assert "vacuous" in tb7


# ============================================================================
# The near-miss control above uses descriptions that are FAR from any handshake,
# so no plausible loosening of the contract layer can make it fire -- a control
# that cannot fail. These sit on the layer's actual boundary instead: each states
# almost a contract, and each must still DEFER, naming what it did not state.
# ============================================================================

_BOUNDARY_NEAR_MISSES = {
    "ratio with no ratio stated": (
        "Module name:\n    event_thinner\n"
        "A block that forwards some input events to the output.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " in_valid: Pulses on an input event.\n"
        "Output ports:\n out_valid: Pulses on an output event.\n"
        "Implementation:\nIt divides the event stream.\n"),
    "elastic with no clock stated": (
        "Module name:\n    no_clock_stage\n"
        "A stage between a producer and a consumer.\n"
        "Input ports:\n up_data [7:0]: The word offered.\n up_valid: Offered.\n"
        " dn_ready: The consumer can take a word.\n"
        "Output ports:\n up_ready: This stage can take a word.\n"
        " dn_data [7:0]: The word offered on.\n dn_valid: Offered.\n"
        "Implementation:\nThe stage must register the output and buffer one\n"
        "additional transfer.\n"),
    "half a handshake": (
        "Module name:\n    sink_only\n"
        "A block that consumes a stream and reports a total.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " up_data [7:0]: The word offered.\n up_valid: Offered.\n"
        "Output ports:\n up_ready: This block can take a word.\n"
        " total [15:0]: The running sum.\n"
        "Implementation:\nA transfer happens when up_valid and up_ready are\n"
        "both high; there is no downstream interface.\n"),
}


@pytest.mark.parametrize("label,desc", _BOUNDARY_NEAR_MISSES.items())
def test_contract_layer_declines_on_its_own_boundary(label, desc):
    assert rcs.detect_shape(desc) is None, label


def test_the_boundary_cases_say_what_was_missing_where_they_can():
    """Not merely a DEFER: for the two that DO state a handshake, the program
    names the unstated field rather than guessing it."""
    why = rcs.route_to_ai_reason(_BOUNDARY_NEAR_MISSES["ratio with no ratio stated"])
    assert why is not None and any("ratio" in u for u in why["unresolved"])
    why = rcs.route_to_ai_reason(_BOUNDARY_NEAR_MISSES["elastic with no clock stated"])
    assert why is not None and any("clock" in u for u in why["unresolved"])


def test_asynchronous_is_not_read_as_synchronous():
    """"asynchronous reset" CONTAINS "synchronous reset". A substring test reads
    it as stating both poles, the ambiguity rule then discards both, and an input
    asking for an asynchronous reset against a synchronous template is answered
    anyway -- exactly the silent wrong answer this layer exists to stop.

    Found only when the inline population was widened from ten shapes to sixteen:
    none of the original ten says "asynchronous reset"."""
    assert rcs.extract_stated_reset_poles(
        "The reset is an asynchronous reset.") == {"async_reset"}
    assert rcs.extract_stated_reset_poles(
        "The reset is a synchronous reset.") == {"sync_reset"}
    assert rcs.extract_stated_reset_poles("rst: async reset.") == {"async_reset"}
    assert rcs.extract_stated_reset_poles("rst: sync reset.") == {"sync_reset"}
    # a text that really does state both is still ambiguous, and records neither
    assert rcs.extract_stated_reset_poles(
        "An asynchronous reset and a synchronous reset.") == set()
    # and the consequence: a sync-reset template is withdrawn from an input that
    # asks for an asynchronous one
    desc = _INLINE_POS["lfsr4_xnor_left"] + "The reset is an asynchronous reset.\n"
    assert "sync_reset" in rcs.template_commitments("lfsr4_xnor_left")
    assert rcs.detect_shape(desc) is None
    assert rcs.route_to_ai_reason(desc)["property"] == "async_reset"


def test_the_inline_population_is_every_shape():
    """The claim "no canonical description conflicts with its own template" is
    only worth what its population is worth. It was ten of sixteen, and the
    dataset-backed tests that would have covered the rest SKIP wherever the
    corpus is absent -- which is where the bug above was hiding."""
    assert set(_INLINE_POS) == {shape for shape, _ in rcs._DETECTORS}


def test_a_word_that_merely_contains_a_tag_is_not_a_directive():
    """The async/sync substring bug was one instance of a class, so the class was
    swept. Measured before the fix: `must not use a demux` and `a premuxed input`
    both tagged multiplexer_stages and `a genvariable name` tagged generate_block,
    and each silently WITHDREW a template the input never objected to."""
    for text in ("The implementation must not use a demux for the select.",
                 "The design must not use a premuxed input.",
                 "The implementation must not use a genvariable name."):
        assert rcs.extract_architecture_directives(text) == [], text
    # the real words still register, including the plural forms
    for text, tag in (("The implementation must not use a mux.",
                       "multiplexer_stages"),
                      ("The implementation must not use any muxes.",
                       "multiplexer_stages"),
                      ("The implementation must not use a generate block.",
                       "generate_block"),
                      ("This must not instantiate any submodule.",
                       "submodule_instantiation")):
        found = rcs.extract_architecture_directives(text)
        assert [t for _, t, _ in found] == [tag], text
    # and the end-to-end consequence: an unrelated constraint no longer costs a
    # canonical design its template
    desc = (_INLINE_POS["barrel_shifter_right_8"]
            + "The implementation must not use a demux for the select.\n")
    assert rcs.detect_shape(desc) == "barrel_shifter_right_8"


_WRAPPED_DIRECTIVES = {
    "wrapped mid-phrase": "The implementation must not\ninstantiate any "
                          "submodule.\n",
    "wrapped before the tag": "This block is a single leaf cell: the "
                              "implementation must not use a\ngenerate block.\n",
    "wrapped after the marker": "The design must not\nuse any muxes at all.\n",
    "on one line": "The implementation must not instantiate any submodule.\n",
}


@pytest.mark.parametrize("label,text", _WRAPPED_DIRECTIVES.items())
def test_a_directive_survives_the_line_it_is_wrapped_on(label, text):
    """Clauses are SENTENCES, not lines.

    Measured before this: the identical prohibition, wrapped across two lines the
    way any 72-column description wraps, recorded NO directive -- the marker
    landed in one clause and the tag in the next -- and the fixed template was
    emitted over it. The whole architecture layer was defeated by reformatting,
    and this lane's own exposure fixture happened to keep the phrase on one line,
    which is exactly why it looked like it worked."""
    assert rcs.extract_architecture_directives(text), label
    desc = _INLINE_POS["barrel_shifter_right_8"] + text
    assert rcs.detect_shape(desc) is None, label
    assert rcs.route_to_ai_reason(desc)["kind"] == "architecture_conflict"


def test_flowing_lines_together_invents_no_directive():
    """The control for the fix: joining lines could pair a marker in one sentence
    with a tag in another. Over the whole canonical population it does not."""
    for shape, desc in _INLINE_POS.items():
        assert rcs.architecture_conflict(desc, shape) is None, shape
        assert rcs.detect_shape(desc) == shape, shape
    # and a marker and a tag in DIFFERENT sentences still make no directive
    assert rcs.extract_architecture_directives(
        "The core must not stall. A mux selects the output.") == []


_HEADING_FORMS = [("Input ports:", "Output ports:"),
                  ("Inputs:", "Outputs:"),
                  ("Input Signals:", "Output Signals:"),
                  ("INPUT PORTS:", "OUTPUT PORTS:")]


@pytest.mark.parametrize("heading,out", _HEADING_FORMS)
def test_the_port_blocks_are_found_under_every_ordinary_heading(heading, out):
    """Measured before this: "Inputs:" was not matched, so every port under it
    had no direction, no contract could be built, and the layer silently never
    fired -- fail-closed, but invisible, and only because every fixture in this
    lane happened to use "Input ports:"."""
    desc = (
        "Module name:\n    stage\n" + heading + "\n"
        " clk: Clock.\n rst_n: Active low reset.\n"
        " up_data [7:0]: The word offered.\n up_valid: Offered.\n"
        " dn_ready: The consumer can take a word.\n" + out + "\n"
        " up_ready: This stage can take a word.\n"
        " dn_data [7:0]: The word offered on.\n dn_valid: Offered.\n"
        "Implementation:\n"
        "The stage must register the output and buffer one additional "
        "transfer.\n")
    c = rcs.extract_handshake_contract(desc)
    assert c is not None and c.kind == "elastic_stage", heading
    assert c.unresolved == [], (heading, c.unresolved)


def test_two_different_stated_widths_are_not_a_stated_width():
    """Taking the first would be a guess. An explicit [hi:lo] still wins, and a
    line that says the same width twice is not ambiguous."""
    def w(line):
        return rcs._port_width(
            "Module name:\n    x\nInput ports:\n " + line + "\n", "up_data")
    assert w("up_data: the 8-bit word, packed into a 32-bit beat.") is None
    assert w("up_data: an 8-bit word; the bus is 8 bits wide.") == 8
    assert w("up_data [7:0]: the 32-bit accumulator's low byte.") == 8
    assert w("up_data: the 8-bit data word.") == 8


def test_prose_after_the_port_blocks_is_not_read_as_ports():
    """A line in the prose that looks like "name: description" must not become a
    port of whichever block was open last -- it can otherwise be chosen as a
    channel's data port and end up in the emitted module."""
    desc = _F6_DESC + (
        "Implementation:\n"
        " counter: an internal counter, not a port.\n"
        " state: the internal state register.\n")
    dirs = rcs._port_directions(desc)
    assert "counter" not in dirs and "state" not in dirs
    c = rcs.extract_handshake_contract(desc)
    assert c is not None and c.unresolved == []
    assert c.up["data"] == "up_data" and c.down["data"] == "dn_data"
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    # on word boundaries: "state" is inside "stage", and this assertion failed
    # for exactly that reason before -- the same trap the program was fixed for
    assert not _names_word("counter", rtl) and not _names_word("state", rtl)


def test_a_clock_is_never_chosen_as_a_data_port():
    """Measured before this: a stage whose clock is named `i_clk` had that clock
    CHOSEN as its upstream data port. It did not reach emission only because the
    width was also unstated -- the layer was saved by a check that knows nothing
    about clocks. Finding a clock and excluding it from the data candidates were
    two different name lists, and they disagreed."""
    desc = ("Module name:\n    stage\nInput ports:\n i_clk: Clock.\n"
            " up_valid: The producer is offering a word.\n"
            " dn_ready: The consumer can take a word.\n"
            "Output ports:\n up_ready: This stage can take a word.\n"
            " dn_data [7:0]: The word offered on.\n dn_valid: Offered.\n"
            "Implementation:\nThe stage must register the output and buffer one "
            "additional transfer.\n")
    c = rcs.extract_handshake_contract(desc)
    assert c is not None and c.clock == "i_clk"
    assert c.up["data"] is None
    assert any("data port" in u for u in c.unresolved)
    assert rcs.detect_shape(desc) is None


@pytest.mark.parametrize("clk,rst", [("clk", "rst_n"), ("i_clk", "i_rst_n"),
                                     ("clk_i", "rst_ni"), ("CLK", "RESET_N")])
def test_ordinary_clock_and_reset_spellings_are_recognised(clk, rst):
    """One recogniser, so a spelling that is found as a clock is also kept out of
    the data candidates -- and a reset spelled `i_rst_n` no longer leaves the
    contract unresolved."""
    desc = ("Module name:\n    stage\nInput ports:\n"
            f" {clk}: Clock.\n {rst}: Active low reset.\n"
            " up_data [7:0]: The word offered.\n up_valid: Offered.\n"
            " dn_ready: The consumer can take a word.\n"
            "Output ports:\n up_ready: This stage can take a word.\n"
            " dn_data [7:0]: The word offered on.\n dn_valid: Offered.\n"
            "Implementation:\nThe stage must register the output and buffer one "
            "additional transfer.\n")
    c = rcs.extract_handshake_contract(desc)
    assert c is not None and c.unresolved == [], (clk, rst, c.unresolved)
    assert c.clock == clk and c.reset == rst
    assert c.up["data"] == "up_data"
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    assert f"input  wire {clk}," in rtl and f"input  wire {rst}," in rtl


def test_the_ratio_check_does_not_fail_a_ratio_that_divides_unevenly():
    """The generated ratio check compared n_out * RATIO with n_in, which is only
    true when the stimulus count is a multiple of RATIO. Measured: a composed
    divider at ratio 3 driven with 64 events reported
    `FAIL: 64 in 21 out, expected 21` -- the checker contradicting itself in its
    own message, and a correct DUT failing. Integer division is the right
    comparison."""
    tb = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(
        _F7_DESC.replace("for every 1 input events", "for every 3 input events")))
    assert "n_out != n_in / 3" in tb
    assert "n_out * 3" not in tb


def test_the_ratio_counter_is_sized_from_its_own_parameter():
    """`RATIO` is a parameter, so a caller may override it. The counter used to be
    sized from the ratio STATED IN THE DESCRIPTION, so a module composed for 2 and
    instantiated at 8 counted to 1 and emitted NOTHING -- measured, 0 outputs for
    64 inputs. A parameter that cannot be overridden is not a parameter."""
    for stated in (1, 2, 4):
        rtl = rcs.emit_from_contract(rcs.extract_handshake_contract(
            _F7_DESC.replace("for every 1 input events",
                             f"for every {stated} input events")))
        assert f"parameter RATIO = {stated}" in rtl
        assert "reg [$clog2(RATIO + 1) - 1:0] count;" in rtl
        # no width literal derived from the stated ratio survives in the counter
        assert "count <= 0;" in rtl


_ELASTIC_MATRIX_RESETS = [
    ("rst_n", "Active low reset.", "", True, None),
    ("rst", "Active high reset.", "", False, None),
    ("rst", "Active high reset.", " The reset is a synchronous reset.", False, True),
    ("rst_n", "Active low reset.", " The reset is a synchronous reset.", True, True),
]


def _elastic_desc(rst_name, rst_line, extra, width_phrase):
    return ("Module name:\n    elastic_stage\nAn elastic pipeline stage.\n"
            "Input ports:\n clk: Clock.\n"
            f" {rst_name}: {rst_line}\n"
            f" up_data{width_phrase}: The word offered by the producer.\n"
            " up_valid: Offered.\n"
            " dn_ready: The consumer can take a word.\n"
            "Output ports:\n up_ready: This stage can take a word.\n"
            f" dn_data{width_phrase}: The word offered on.\n dn_valid: Offered.\n"
            "Implementation:\nA transfer happens when valid and ready are both "
            "high. The stage must register the output and buffer one additional "
            "transfer so the producer is only stalled when no slot is free. No "
            "word that was not accepted may be captured, no accepted word may be "
            "lost, and accepted words must leave in the order they arrived."
            + extra + "\n")


@pytest.mark.parametrize("rst_name,rst_line,extra,low,sync",
                         _ELASTIC_MATRIX_RESETS)
@pytest.mark.parametrize("width_phrase,width", [(" [7:0]", 8), (" [31:0]", 32)])
def test_the_elastic_stage_composes_across_reset_styles_and_widths(
        rst_name, rst_line, extra, low, sync, width_phrase, width):
    """Everything in this branch had composed ONE combination: 8 bits, active-low
    asynchronous reset. Synchronous and active-high resets had never been
    emitted, let alone simulated."""
    desc = _elastic_desc(rst_name, rst_line, extra, width_phrase)
    c = rcs.extract_handshake_contract(desc)
    assert c is not None and c.unresolved == []
    assert (c.reset, c.reset_active_low, c.reset_sync) == (rst_name, low, sync)
    assert c.width == width
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    if sync:
        assert f"always @(posedge {c.clock}) begin" in rtl
        assert "negedge" not in rtl and "or posedge" not in rtl
    else:
        edge = "negedge" if low else "posedge"
        assert f"always @(posedge {c.clock} or {edge} {rst_name}) begin" in rtl
    assert f"if ({'!' if low else ''}{rst_name}) begin" in rtl
    assert f"[{width - 1}:0] " in rtl


def test_a_one_bit_width_stated_in_words_is_a_stated_width():
    """A single-bit port is idiomatically written in WORDS here ("data_in:
    One-bit input."), and that is still a width the input stated. Measured: it
    was previously unresolved, so no single-bit elastic stage could compose."""
    desc = _elastic_desc("rst_n", "Active low reset.", "", "").replace(
        "up_data: The word", "up_data: One-bit word").replace(
        "dn_data: The word", "dn_data: One-bit word")
    c = rcs.extract_handshake_contract(desc)
    assert c is not None and c.unresolved == [] and c.width == 1
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    assert "input  wire up_data," in rtl and "[0:0]" not in rtl
    # a width written in words that this reader does NOT parse stays unresolved
    # and is NAMED -- it is not guessed
    four = _elastic_desc("rst_n", "Active low reset.", "", "").replace(
        "up_data: The word", "up_data: Four-bit word")
    c4 = rcs.extract_handshake_contract(four)
    assert c4.width is None and any("width" in u for u in c4.unresolved)


_COLLIDING_PORTS = {
    "a divider whose payload port is named count": (
        "Module name:\n    pulse_divider\nAn event ratio divider.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " count [7:0]: The 8-bit payload accompanying an input event.\n"
        " in_valid: Pulses on each input event.\n"
        "Output ports:\n out_data [7:0]: The forwarded payload.\n"
        " out_valid: Pulses on each output event.\n"
        "Implementation:\nThe divider emits one output event for every 1 input "
        "events.\n", "count"),
    "a stage whose data ports are named held_data / skid_data": (
        "Module name:\n    elastic_stage\nAn elastic pipeline stage.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " held_data [7:0]: The word offered by the producer.\n"
        " up_valid: Offered.\n dn_ready: The consumer can take a word.\n"
        "Output ports:\n up_ready: This stage can take a word.\n"
        " skid_data [7:0]: The word offered on.\n dn_valid: Offered.\n"
        "Implementation:\nA transfer happens when valid and ready are both high. "
        "The stage must register the output and buffer one additional transfer "
        "so the producer is only stalled when no slot is free.\n", "held_data"),
}


@pytest.mark.parametrize("label,case", _COLLIDING_PORTS.items())
def test_internal_names_give_way_to_the_designs_own_port_names(label, case):
    """Ports come from the INPUT; internal signals are the generator's choice, so
    the internals must give way. Measured before this: a divider whose payload is
    named `count` and a stage whose data is named `held_data` both emitted RTL
    that DOES NOT COMPILE -- "'count' has already been declared in this scope"
    -- because the internal names were fixed literals."""
    desc, port = case
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    # the port keeps its name, declared exactly once
    assert len(re.findall(r"\b" + port + r"\b\s*[,;)]", rtl)) >= 1
    decls = re.findall(r"^\s*(?:input|output|reg|wire)[^;\n]*\b" + port
                       + r"\b", rtl, re.M)
    assert len(decls) == 1, (label, decls)
    # and every generated identifier that would have collided was renamed
    for taken in ("count", "held_data", "skid_data", "up_fire", "dn_fire"):
        if taken == port:
            assert f"{taken}_2" in rtl or taken not in _INTERNAL_OF(rtl)


def _INTERNAL_OF(rtl):
    """Identifiers this module DECLARES (as reg/wire), for the check above."""
    return set(re.findall(r"^\s*(?:reg|wire)[^;\n]*?(\w+)\s*[;=\[]", rtl, re.M))


def test_the_scoreboard_locals_also_give_way():
    """The generated TB declares q/wr/rd/errors/i and n_in/n_out/i; a design with
    a port of one of those names would make the TB uncompilable too."""
    desc = _F7_DESC.replace("in_data", "n_in").replace("out_data", "n_out")
    c = rcs.extract_handshake_contract(desc)
    tb = rcs.emit_scoreboard_tb(c)
    assert "integer n_in_2 = 0, n_out_2 = 0, i;" in tb


# ============================================================================
# CZ2035P-6 -- WHAT A DETECTOR NEVER LOOKS AT, IT CANNOT REFUSE (closed, for the
# one dimension where the template's own pole is soundly derivable).
#
# The block above records three routes measured closed. Route 3 was re-measured
# on this base over all 16 detectors x 4 polar dimensions: 13 of 16 examine NONE
# of the four and all 16 are blind to at least three, so its "cost = exactly one
# canonical shape" is an artefact of how terse the canonical descriptions are,
# not a property of the rule -- against ordinary prose it would defer nearly
# everything. Route 2 reopens under a WIDTH test: a shift preserves the
# operand's width, a zero-extension does not. Anchored on a declared input port
# of known integer width it yields a pole for exactly one of the sixteen
# templates, and that pole is right.
#
# The seam was already there: `detect_shape` withdraws a template through
# `architecture_conflict` and `route_to_ai_reason` names the withdrawal. Only
# the POLE VOCABULARY is new.
# ============================================================================

# Neutral, input-only. Matches `_is_barrel_shifter` (module-name token, ports
# in/ctrl/out, the phrase "barrel shifter", "ctrl" and "shift") while asking for
# the other direction.
_BARREL_LEFT_DESC = (
    "Module name:\n    barrel_shifter\n"
    "A barrel shifter that performs a logical shift left on an 8-bit input, "
    "controlled by ctrl.\n"
    "Input ports:\n in: Data to be shifted.\n ctrl: Shift amount.\n"
    "Output ports:\n out: Shifted result.\n"
    "The barrel shifter shall shift the input to the left by the number of bit "
    "positions given by ctrl, filling the vacated low-order bits with zero.\n")

_BARREL_RIGHT_DESC = _BARREL_LEFT_DESC.replace("shift left", "shift right") \
    .replace("to the left", "to the right").replace("low-order", "high-order")


def test_a_stated_opposite_shift_direction_withdraws_the_template():
    """OLD WRONG BEHAVIOUR, on input-only material. Measured on the base before
    this layer: this description matched `barrel_shifter_right_8` and was
    answered EMIT, rc=0, with `{4'b0000, in[7:4]}` -- a RIGHT shifter for an
    input that says left three times, silently. The detector still matches it;
    the fixed topology is now WITHDRAWN and the pole is NAMED."""
    assert rcs._is_barrel_shifter(
        _BARREL_LEFT_DESC, rcs.module_name_of(_BARREL_LEFT_DESC),
        rcs._port_tokens(_BARREL_LEFT_DESC) - rcs._NOISE), (
        "the fixture must still MATCH the detector, or it proves nothing")
    # These two lines come FIRST on purpose. They read only APIs the base
    # already had, so swapping the base program back in makes this test fail by
    # ASSERTION on the old behaviour -- not by AttributeError on a layer that is
    # simply absent, which would be no evidence of anything.
    assert rcs.detect_shape(_BARREL_LEFT_DESC) is None
    conflict = rcs.architecture_conflict(_BARREL_LEFT_DESC,
                                         "barrel_shifter_right_8")
    assert conflict is not None and conflict["polarity"] == "stated"
    assert conflict["property"] == "shift_left"
    assert rcs.extract_stated_shift_direction(_BARREL_LEFT_DESC) == {"shift_left"}
    why = rcs.route_to_ai_reason(_BARREL_LEFT_DESC)
    assert why["route"] == "ai_author"
    assert why["kind"] == "architecture_conflict"
    assert why["shape_declined"] == "barrel_shifter_right_8"
    assert why["property"] == "shift_left"


def test_the_alternative_architecture_control_stays_green():
    """THE CONTROL. A withdrawal that fires on the agreeing input too would be a
    regression wearing a fix's clothes: it would cost the shape its template for
    saying what the template already does. An input stating the SAME direction
    still gets it, and an input that states no direction is untouched."""
    assert rcs.extract_stated_shift_direction(_BARREL_RIGHT_DESC) == {"shift_right"}
    assert rcs.architecture_conflict(_BARREL_RIGHT_DESC,
                                     "barrel_shifter_right_8") is None
    assert rcs.detect_shape(_BARREL_RIGHT_DESC) == "barrel_shifter_right_8"
    assert rcs.emit_rtl(rcs.detect_shape(_BARREL_RIGHT_DESC),
                        _BARREL_RIGHT_DESC) == rcs._TEMPLATES[
                            "barrel_shifter_right_8"]
    silent = _INLINE_POS["barrel_shifter_right_8"]
    assert rcs.extract_stated_shift_direction(silent) == set()
    assert rcs.detect_shape(silent) == "barrel_shifter_right_8"


def test_shift_poles_are_derived_from_the_template_code():
    """Derived, never hand-declared -- a re-authored template moves its own pole.
    Exactly ONE of the sixteen yields one, and it says what that template does.
    Compared by MEMBERSHIP of the shape set, not by count."""
    poled = {s for s in rcs._TEMPLATES
             if any(p.startswith("shift_") for p in rcs.template_commitments(s))}
    assert poled == {"barrel_shifter_right_8"}
    assert "shift_right" in rcs.template_commitments("barrel_shifter_right_8")
    assert "shift_left" not in rcs.template_commitments("barrel_shifter_right_8")


def test_the_shift_derivation_can_report_either_pole():
    """A rule that can only ever say one thing is not a rule. Feed it the same
    template with its one port-anchored concatenation reversed and it must say
    the other pole -- and then the SAME description conflicts the other way."""
    left_rtl = rcs._TEMPLATES["barrel_shifter_right_8"].replace(
        "{4'b0000, in[7:4]}", "{in[3:0], 4'b0000}")
    assert left_rtl != rcs._TEMPLATES["barrel_shifter_right_8"]
    assert "shift_left" in rcs._rtl_commitments(left_rtl)
    assert "shift_right" not in rcs._rtl_commitments(left_rtl)


def test_a_zero_extension_is_not_read_as_a_shift():
    """The measurement that reopened this route. Reading the code NAIVELY, the
    IEEE-754 multiplier's `{2'd0, a[30:23]}` looks like a right shift. It is a
    zero-EXTENSION of the exponent FIELD: bit 30 is not `a`'s msb, so the slice
    is not anchored where a shift's would be."""
    tpl = rcs._TEMPLATES["ieee754_single_multiplier"]
    assert "{2'd0, a[30:23]}" in tpl, "fixture drifted from the template"
    widths = rcs._rtl_input_port_widths(tpl)
    assert widths["a"] == 32 and widths["b"] == 32
    assert rcs._rtl_shift_poles(tpl) == set()


_ANCHOR_MODULE = ("module m(input [7:0] x, output [7:0] y);\n"
                  "    wire [7:0] t = %s;\n"
                  "    assign y = t;\n"
                  "endmodule\n")


@pytest.mark.parametrize("expr,pole", [
    ("{4'b0000, x[7:4]}", "shift_right"),   # a real right shift by 4
    ("{x[3:0], 4'b0000}", "shift_left"),    # a real left shift by 4
])
def test_the_anchored_forms_are_recognised(expr, pole):
    assert rcs._rtl_shift_poles(_ANCHOR_MODULE % expr) == {pole}


@pytest.mark.parametrize("expr,violates", [
    # msb anchor alone is satisfied, fill-width anchor is not: the TOP nibble
    # zero-extended to six bits. Not a shift.
    ("{2'b00, x[7:4]}", "fill-width anchor"),
    # fill-width anchor alone is satisfied, msb anchor is not: a middle field.
    ("{2'b00, x[5:2]}", "msb anchor"),
    # the same two, mirrored, for the left form
    ("{x[6:0], 3'b000}", "left msb anchor"),
    ("{x[4:1], 3'b000}", "left low anchor"),
])
def test_each_anchor_is_load_bearing_on_its_own(expr, violates):
    """NEITHER anchor is redundant. Each of these satisfies exactly one of the
    two and is not a shift; dropping the anchor it violates would make the rule
    call it one. Written after a mutation of an earlier formulation SURVIVED:
    that version also tested width preservation, which the two anchors already
    imply, so the clause could not fail and proved nothing."""
    assert rcs._rtl_shift_poles(_ANCHOR_MODULE % expr) == set(), violates


def test_a_parametric_port_width_yields_no_pole_rather_than_a_default():
    """Unknown is recorded as unknown. A width the source writes parametrically
    does not resolve to an integer, so the width test cannot be applied and no
    pole is claimed -- never a guessed default."""
    widths = rcs._rtl_input_port_widths(rcs._TEMPLATES["async_gray_fifo"])
    assert "wdata" in widths and widths["wdata"] is None
    assert widths["wclk"] == 1
    for shape in ("async_gray_fifo", "pipelined_ripple_adder_64",
                  "pipelined_unsigned_multiplier_8"):
        assert rcs._rtl_shift_poles(rcs._TEMPLATES[shape]) == set()


def test_a_description_stating_both_shift_directions_records_neither():
    """The same ambiguity rule the reset poles use: contradictory input is not a
    licence to pick."""
    both = _BARREL_LEFT_DESC + "In an alternative mode it may shift right.\n"
    assert rcs.extract_stated_shift_direction(both) == set()
    assert rcs.detect_shape(both) == "barrel_shifter_right_8"


@pytest.mark.parametrize("text", [
    "The output field is right-justified within the word.",
    "The left-hand operand is registered before the adder.",
    "Any data left over from the previous frame is discarded.",
    "A right-angle turn in the layout is not permitted.",
])
def test_a_direction_word_not_about_shifting_states_nothing(text):
    """`left` and `right` are ordinary English. The pole counts only where it is
    SHIFTING that is being described, or the layer withdraws templates from
    descriptions that never objected to them -- the same class of defect as
    `demux` once forging a mux directive."""
    assert rcs.extract_stated_shift_direction(text) == set()
    assert rcs.detect_shape(
        _INLINE_POS["barrel_shifter_right_8"] + text
    ) == "barrel_shifter_right_8"


def test_the_sixteen_canonical_descriptions_still_emit_their_own_bytes():
    """The end-to-end guard, pinned in the suite so no human has to remember to
    run it: every canonical description still detects as its own shape and emits
    its template byte for byte. Membership first, then bytes."""
    assert set(_INLINE_POS) == {k for k, _ in rcs._DETECTORS}
    for shape, desc in _INLINE_POS.items():
        assert rcs.detect_shape(desc) == shape
        rtl = rcs.emit_rtl(shape, desc)
        if shape == "unsigned_iterative_restoring_divider":
            assert "module unsigned_ratio_unit" in rtl
            assert rcs._unsigned_division_observation(desc)[0]["source_sha256"] in rtl
        else:
            assert rtl == rcs._TEMPLATES[shape]


def test_the_lfsr_states_a_direction_and_keeps_its_template():
    """The population's own witness that the width test is load-bearing. The
    LFSR's canonical description says "the register is shifted left" -- a real
    stated pole, in the shipped corpus, not a constructed one. Its template
    shifts an internal register, not an input port, so no pole is derived from
    it and the shape is untouched. The blunter rule measured closed above (defer
    whenever the input states a dimension the detector ignores) would have taken
    this template away for saying something true about itself."""
    desc = _INLINE_POS["lfsr4_xnor_left"]
    assert rcs.extract_stated_shift_direction(desc) == {"shift_left"}
    assert rcs._rtl_shift_poles(rcs._TEMPLATES["lfsr4_xnor_left"]) == set()
    assert rcs.architecture_conflict(desc, "lfsr4_xnor_left") is None
    assert rcs.detect_shape(desc) == "lfsr4_xnor_left"
    assert rcs.emit_rtl("lfsr4_xnor_left", desc) == rcs._TEMPLATES["lfsr4_xnor_left"]


def test_the_front_door_defers_the_contradicted_shape(tmp_path):
    """NO HUMAN HAS TO REMEMBER THIS. The withdrawal is on the path the runner
    already takes for every ordinary design: `_try_canonical_primitive_rtl`
    returns None, the step falls through to the AI author, and -- the part that
    matters -- NO RTL is written. Before this layer the same project got a
    right-shift `barrel_shifter.v` on disk and a PASS."""
    R = _load_runner()
    proj = _mk_project(tmp_path, _BARREL_LEFT_DESC)
    assert R._try_canonical_primitive_rtl(proj, 0.0) is None
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    assert not rtl_dir.is_dir() or list(rtl_dir.rglob("*.v")) == []


def test_the_front_door_still_emits_the_agreeing_shape(tmp_path):
    """The control, on the same path: an input that states the direction the
    template implements is still answered program-first, byte for byte."""
    R = _load_runner()
    proj = _mk_project(tmp_path, _BARREL_RIGHT_DESC)
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras.get("shape") == "barrel_shifter_right_8"
    emitted = sorted((proj / "phase2" / "stage1" / "rtl").glob("*.v"))
    assert [p.name for p in emitted] == ["barrel_shifter.v"]
    assert emitted[0].read_text() == rcs._TEMPLATES["barrel_shifter_right_8"]


# ============================================================================
# COUNTING EVENTS CANNOT SEE A PAYLOAD THAT IS NEVER FORWARDED.
#
# Measured 2026-09-06 on v1.17.83, by composing F7 at four ratios and mutating
# the composed RTL eight ways: five mutants were killed and one was NOT --
# replacing the WHOLE payload path with a constant (`out_data <= 8'd0`) still
# reported `PASS 64 in 21 out` at every ratio. The generated ratio TB declared
# `out_data` and wired it to the DUT and then never compared it, so every
# payload defect in the family was invisible to the check that ships beside it.
#
# (Two other survivors of that sweep were MY mutants and not holes: an
# unconditional capture where `held_valid` is being cleared anyway, and a
# `skid_valid && !up_fire` guard that is dead because `up_ready = !skid_valid`.
# Both are PROVED EQUIVALENT on the observable interface by yosys
# `miter -equiv` + `sat -seq 24 -set-init-zero -prove-asserts`, with a mutant
# that genuinely loses a transfer as the control that correctly does NOT prove.)
#
# The check does NOT decide WHICH of the N inputs travels. The description
# states the ratio and states that the payload is forwarded; it does not say
# whether the first or the last of a group is the one that arrives, and issue
# #2035 forbids guessing a hidden expected value. So it checks MEMBERSHIP in the
# group that produced the event -- which is exact at a unit ratio, where the
# group has one member and nothing is left open.
# ============================================================================

# `ORACLE_MISSING` is `_sim_tools`' name for the (iverilog, vvp) pair -- the two
# binaries a test needs to COMPILE AND RUN something. It has nothing to do with
# reading an oracle output, which the read-only-input rule forbids and which nothing here does:
# every value compared below is generated from the design INPUT.
import _sim_tools  # noqa: E402

_NEEDS_VVP = pytest.mark.skipif(
    bool(_sim_tools.ORACLE_MISSING),
    reason="this check COMPILES AND RUNS the generated scoreboard; missing on "
           "this host: " + ", ".join(_sim_tools.ORACLE_MISSING or ("-",)))


def _ratio_desc(n):
    return _F7_DESC.replace("for every 1 input events", f"for every {n} input events")


def _simulate(workdir, rtl, tb):
    """Compile and run one composed design against its own generated scoreboard."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "dut.v").write_text(rtl)
    (workdir / "tb.v").write_text(tb)
    c = subprocess.run(["iverilog", "-g2012", "-o", str(workdir / "a.vvp"),
                        str(workdir / "dut.v"), str(workdir / "tb.v")],
                       capture_output=True, text=True)
    assert c.returncode == 0, f"the GENERATED sources must compile:\n{c.stderr}"
    r = subprocess.run(["vvp", str(workdir / "a.vvp")], capture_output=True,
                       text=True)
    return r.stdout + r.stderr


@_NEEDS_VVP
@pytest.mark.parametrize("ratio", [1, 3])
def test_the_ratio_scoreboard_catches_a_payload_no_input_offered(tmp_path, ratio):
    """THE KILL, both directions. The correct design must PASS -- a check that
    reddens on everything is no better than one that reddens on nothing -- and
    the constant-payload design must go RED."""
    desc = _ratio_desc(ratio)
    c = rcs.extract_handshake_contract(desc)
    rtl = rcs.emit_rtl(rcs.detect_shape(desc), desc)
    tb = rcs.emit_scoreboard_tb(c)

    good = _simulate(tmp_path / "good", rtl, tb)
    assert "PASS" in good and "FAIL" not in good, good

    broken = rtl.replace("if (in_valid) out_data <= in_data;",
                         "out_data <= 8'd0;")
    assert broken != rtl, "the payload mutation did not apply"
    bad = _simulate(tmp_path / "bad", broken, tb)
    assert "FAIL" in bad and "PASS" not in bad, bad


@_NEEDS_VVP
def test_the_ratio_scoreboard_still_passes_every_ratio_it_composes(tmp_path):
    """The control for the check above: adding a payload check must not cost the
    family the ratios it already served. Compared by MEMBERSHIP of the ratio set."""
    served = set()
    for ratio in (1, 2, 3, 5):
        desc = _ratio_desc(ratio)
        c = rcs.extract_handshake_contract(desc)
        out = _simulate(tmp_path / f"r{ratio}",
                        rcs.emit_rtl(rcs.detect_shape(desc), desc),
                        rcs.emit_scoreboard_tb(c))
        if "PASS" in out and "FAIL" not in out:
            served.add(ratio)
    assert served == {1, 2, 3, 5}


def test_the_ratio_scoreboard_compares_the_output_payload_at_all(tmp_path):
    """Runs everywhere, simulator or not. Before this layer `out_data` appeared
    in the generated TB exactly twice -- a declaration and a port connection --
    and in no comparison, which is precisely how a payload defect stayed
    invisible. It must now be READ, and the summary must not be able to print
    PASS while a payload error stands."""
    tb = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_ratio_desc(3)))
    assert "out_data ===" in tb
    assert "grp[" in tb
    # the PASS line must come AFTER the payload branch, so it cannot be reached
    # while data errors stand
    assert tb.index("carried a payload no input offered") < tb.index("$display(\"PASS")


def test_the_payload_check_is_absent_when_the_contract_declares_no_data_port():
    """Fail-closed the other way: a ratio contract with no data ports must not
    grow a check for a payload that does not exist."""
    desc = _ratio_desc(2)
    for line in (" in_data [7:0]: The 8-bit payload accompanying an input event.\n",
                 " out_data [7:0]: The forwarded payload.\n"):
        desc = desc.replace(line, "")
    c = rcs.extract_handshake_contract(desc)
    if c is None or c.kind != "ratio_divider":
        pytest.skip("the trimmed description no longer states a ratio contract")
    tb = rcs.emit_scoreboard_tb(c)
    assert "grp[" not in tb and "===" not in tb


# Exact independent R7 inputs retained verbatim for R8.
_R8_SPEC = '''Design an unsigned iterative arithmetic unit using the restoring division algorithm.
Module name: extra_scope_unit
Parameter WIDTH has a default value of 9.
Input ports:
clk: posedge clock.
rst: active-low asynchronous reset.
start: one-cycle request.
{ports}
Output ports:
quotient[WIDTH-1:0]: unsigned quotient.
remainder[WIDTH-1:0]: unsigned remainder.
valid: one-cycle completion.
{domain}
On reset all outputs clear. New inputs are accepted after the previous result.
At each restoring iteration append the next dividend bit to the shifted partial remainder and subtract the divisor; a negative trial restores the shifted partial remainder and produces quotient bit zero.
Completion takes WIDTH cycles for power-of-two WIDTH and WIDTH+1 cycles otherwise; no extra input-only cycle.
'''
_R8_CASES = [('source_port_WIDTH',
  True,
  'The divisor is nonzero. Dividend is at least divisor. Target input guarantees remain unconditional.',
  'WIDTH[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('coord_and_also',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived and '
  'also removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('coord_repeated_subject',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived but the '
  'nonzero requirement was removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('coord_repeated_subject_yet',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived, yet '
  'the nonzero requirement was removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('coord_semicolon_elided',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived; was '
  'removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('coord_comma_elided',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived, was '
  'removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('named_dividend',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The dividend requirements are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('named_numerator',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The numerator constraints are waived.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('named_operands',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The operand requirements are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('named_both_operands',
  False,
  'The divisor is nonzero. Dividend is at least divisor. Both operand requirements are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('unnamed_all',
  False,
  'The divisor is nonzero. Dividend is at least divisor. All requirements are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('unnamed_both',
  False,
  'The divisor is nonzero. Dividend is at least divisor. Both requirements are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('unnamed_above',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The above requirements are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('plural_after_unrelated_target',
  False,
  'The divisor is nonzero. Dividend is at least divisor. The quotient may be zero. These requirements '
  'are removed.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('ordering_could_possibly',
  False,
  'The divisor is nonzero. Dividend is at least divisor. Dividend could possibly be less than divisor.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('ordering_might_sometimes',
  False,
  'The divisor is nonzero. Dividend is at least divisor. Dividend might sometimes be less than divisor.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.'),
 ('ordering_could_be',
  False,
  'The divisor is nonzero. Dividend is at least divisor. Dividend could be smaller than divisor.',
  'dividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.')]


@pytest.mark.parametrize("case,emit,domain,ports", _R8_CASES,
                         ids=[row[0] for row in _R8_CASES])
def test_unsigned_divider_r8_exact_independent(case, emit, domain, ports, tmp_path):
    description = _R8_SPEC.format(ports=ports, domain=domain)
    source, rtl = tmp_path / "description.txt", tmp_path / "candidate.v"
    source.write_text(description)
    command = subprocess.run([sys.executable, str(PROGRAMS / "canonical_primitive_synth.py"),
                              "--from-desc", str(source), "--out", str(rtl)],
                             capture_output=True, text=True)
    response = json.loads(command.stdout)
    expected = "EMIT" if emit else "DEFER"
    assert response["verdict"] == expected, response
    assert command.returncode == (0 if emit else 2), command.stderr
    assert rtl.is_file() == emit
    project = tmp_path / "project"
    input_doc = project / "phase1/input_doc/design_description.txt"
    input_doc.parent.mkdir(parents=True)
    input_doc.write_text(description)
    consumer = _load_runner()._try_canonical_primitive_rtl(project, time.time())
    outputs = list(project.glob("phase2/stage1/rtl/*.v"))
    actual = "EMIT" if consumer is not None and consumer.status == "PASS" and outputs else "DEFER"
    assert actual == expected
    assert bool(outputs) == emit
    if emit:
        assert len(outputs) == 1 and outputs[0].read_bytes() == rtl.read_bytes()
        # Same Icarus standard and options as the sealed independent probe.
        compile_run = subprocess.run(["iverilog", "-g2012", "-s", "extra_scope_unit",
                                      "-o", str(tmp_path / "sim.out"), str(rtl)],
                                     capture_output=True, text=True)
        assert compile_run.returncode == 0, compile_run.stdout + compile_run.stderr


# Exact independent R8 review inputs retained verbatim for R9.
_R9_SPEC = 'Design an unsigned iterative arithmetic unit using the restoring division algorithm.\nModule name: extra_scope_unit\nParameter WIDTH has a default value of 9.\n{interface}\n{domain}\nOn reset all outputs clear. New inputs are accepted after the previous result.\nAt each restoring iteration append the next dividend bit to the shifted partial remainder and subtract the divisor; a negative trial restores the shifted partial remainder and produces quotient bit zero.\nCompletion takes WIDTH cycles for power-of-two WIDTH and WIDTH+1 cycles otherwise; no extra input-only cycle.\n'
_R9_CASES = [('semicolon_also_removed',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived; '
  'also removed.',
  '0eb8d6c785656421432e2a361537b55d29e443b12029715eb3845f68498fe4c7'),
 ('comma_also_was_removed',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived, '
  'and also was removed.',
  '7ac6bd4f1c1fe7c124564dda4a05f17a260e6583fc63dcaeb3a19c4a8de28639'),
 ('semicolon_and_was_removed',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived; '
  'and was removed.',
  '28944bd6ed0eb3993312f38b9e584842825db36d29a15b4fc7b18e3ca51f3b4e'),
 ('elided_later_removed',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived '
  'and later removed.',
  '448409f7c13682be4f45695d2e58989a77bdd6e84a9393b8a0e4f022ad12aff3'),
 ('elided_then_removed',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived '
  'but then removed.',
  '3330411a1eadf2b9608c74bccc815f185d3c20e58d62c2f3a40268e1359bf0de'),
 ('elided_nevertheless_removed',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived; '
  'has nevertheless been removed.',
  'a6229489aea70f09bc5bb8f1102e8e1e168f130d7b5d6408618ae25dbd032b6f'),
 ('named_dividend_and_divisor',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The dividend and divisor requirements are '
  'removed.',
  'f79137bb13c5da17f544945f7533f3a2ece1b0e2d866e2614cbaea589d39d470'),
 ('named_both_operands_plural',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Both operands requirements are removed.',
  'f4efb99f2b6a2273d87b236d641d44ca0e237b6f1c062e37a57b6cc5afa0fef1'),
 ('all_above_requirements',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. All above requirements are removed.',
  '43a8642f79e5c71fd4d9a1198e9d80bcca64e6514769d04cf7f3c0607aea78bf'),
 ('plural_after_unrelated_paragraph',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The quotient may be zero.\n'
  '\n'
  'These requirements are removed.',
  'e5da1f049c2194c17a06222bfc32d90e3d29fe869c011b48ef56f8118147f123'),
 ('withdrawal_next_paragraph',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. \n\nBoth requirements are removed.',
  '7c2420b340a9e3bd60f15832847d02f824c43be9abf2d6ff65466d3d3bd952a4'),
 ('withdrawal_unicode_stop',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. These requirements are not waived。They '
  'are removed.',
  'd3a44d22ee576356f788601b1ff9eeb14af5d98b5409f4b6bd2659cf66bdff32'),
 ('modal_might_occasional',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Dividend might occasionally be less than '
  'divisor.',
  '954788a469fa13dc48f4fbc633b15c46da8d587d012df13af7c1619382b21044'),
 ('modal_could_well',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Dividend could well be smaller than '
  'divisor.',
  '478f75744cd8a4fb113538fc25224f898591f11593c83de8762d2ccb7fd66bf5'),
 ('modal_can_sometimes',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Dividend can sometimes be smaller than '
  'divisor.',
  '7d4ce535238502442ce80a78d52d61f11612d19f252187f14f0a5457c32c9b0e'),
 ('modal_may_possibly',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Dividend may possibly be less than '
  'divisor.',
  'abeafe9e29f7f8cfb28c6ade8865e8e0622deba3c5d06933c07a40d92b660c7b'),
 ('modal_could_possible_zero',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The divisor could possibly be zero.',
  '11820d3e382dec101a36cf7641e7da199b70be66c4ffbc085b1dd308668a5f9b'),
 ('modal_can_possible_zero',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The divisor can possibly be zero.',
  'ba29bc7a3e565ff5ba5d587f8cb9c9c50f6bbbc92fa831b4f11fce563b636076'),
 ('modal_might_sometimes_zero',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The divisor might sometimes be zero.',
  'a868bbba5d182b4ffe080f06e928ec73c4ede29d797291c5bd8650dc2e3276ba'),
 ('mixed_output_subject',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement is not waived, '
  'and the quotient requirement is removed; the ordering requirement is removed.',
  '5277c00f5a1291e35b44e302384fc3c16050c27ba60a2d2606e0b3887cdda125'),
 ('withdrawal_heading',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. \n'
  'Target input constraints:\n'
  '- The divisor requirements are removed.',
  '97c3553f18db786e6a4307d6268104fef826d338fe09a5bfac67946c8480bfdf'),
 ('both_operand_negated',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Both operand requirements are not waived.',
  'e8e943f5c13bb5cc81962de7d37b883f7f857bf08dac4de1935e9c033b8c3b5c'),
 ('both_negated_predicates',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived '
  'and also not removed.',
  'e795fabfaa363916226834776f8674f20ed976dbde8fd52de6a9c78f04d0c1bd'),
 ('semicolon_negated_predicate',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement was not waived; '
  'was not removed.',
  'ad4c7f73970fb19f424f6baa54b8347c5056240b9940ce465378f744187644b2'),
 ('unrelated_output_withdrawal',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The quotient requirements are removed.',
  '88251123788f7749877cc1c491025704fede9205a2d35a86298763249d3eae93'),
 ('unrelated_after_named_predicate',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The nonzero requirement is not waived and '
  'the quotient requirement is removed.',
  '75786e88505a256b82b7e411f41fe9253e1f6ec51e95d659e034bcd0c95f12d4'),
 ('unrelated_elided_output',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The quotient requirement was not waived; '
  'was removed.',
  '858aa4defa22699a4748d69bccc5dfd9d18e59aedff7cd00183128c5cef0bcb2'),
 ('external_operand_removal',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The reference model dividend requirements '
  'are removed.',
  '127a70b5450c449f249e3f045cc6c446cf0fe9096ffa39e3b99aa64841f0ac59'),
 ('quoted_plural_removal',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. A discarded note says "Both requirements '
  'are removed".',
  '8e2b057bca352d4e9a04dbbcece6186d4038783ac258abae9692b9c9679fc921'),
 ('conditional_plural_removal',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. If another design is used, both '
  'requirements are removed.',
  'a656e05747582b8b430b0d776d8ced165552a253858d22b0c39a18715f707030'),
 ('negated_modal_less',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Dividend cannot be less than divisor.',
  '057e54132f772d6531780767a04bc6e728e32834eef30558dea0a992012b1d51'),
 ('negated_possible_less',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. Dividend could not possibly be less than '
  'divisor.',
  '2f1ec2c189d8b8ba941549559d4a029857cfb118f4eec048f9dca734f7810b6e'),
 ('negated_possible_zero',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The divisor could not possibly be zero.',
  '45f2003275c4b6350af6dcbcdff5f555a4b7601770cf415296a1fc5117b97c27'),
 ('unrelated_requirements_plural',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The output timing requirement is '
  'retained. These requirements are removed.',
  '36ad317fa31e02a81e810ea4214ce528fe07cc02f05e96c24dd701031136f425'),
 ('unrelated_rules_plural',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The output timing rules are described '
  'below. Those rules are removed.',
  '43025fcf3a056901636804ee0b8a23d55b92fb80e60c5001766294b69be26218'),
 ('unrelated_negation_same_clause',
  'DEFER',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor. The quotient is not negative and dividend '
  'could be smaller than divisor.',
  'fd99fbe6c641ffb117ee4abace8ff722a04e7751231fd03ce4cabe79c4214616'),
 ('dividend_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'WIDTH[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '18ce9c8e10defe4c2c0a149b01dff9240a9150fbf92166b46b3d92f40d2d7a0e'),
 ('dividend_identifier_WIDTH_1',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'WIDTH_1[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '8da527263ac10933203d188f12f790ba7539132fc9ac5fc511cec15a0bf8e92f'),
 ('dividend_identifier_COUNT_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'COUNT_WIDTH[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '2822932314fae60a34e15266854a3a79a1107ae01bdfb2ef75b789a9f671055c'),
 ('dividend_identifier_EXTRA_FINAL_CYCLE',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'EXTRA_FINAL_CYCLE[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '4f74e7d9405dcdc724d4eae21dd1a9fd235a5841c35133dcf85b437478043096'),
 ('dividend_identifier_busy',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'busy[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '753ce19fdf5218e1408a537c064f1a318aa64425b1d8081c9a0f9b0d8fa122de'),
 ('dividend_identifier_count',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'count[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '3611c576d813879b6f6e9c48e9de9a6edec060a0f3a52067e9d9111efba79d6e'),
 ('dividend_identifier_finish_pending',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'finish_pending[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '998549376ec92f11ef37ba7159318ce25355d5e6af32f39d59fca58985842774'),
 ('dividend_identifier_shifted_remainder',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'shifted_remainder[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '0898306390a6fd4b83c4d4559c9163e800845852b1405cc7e355ef2a0e625aa9'),
 ('dividend_identifier_start_remainder',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'start_remainder[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '5d91ac827a1230776cfeb64412d757537d3976b52e52c86bafec1739633a9bb0'),
 ('divisor_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'WIDTH[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  'cd8d8c1974fa6d5774bef87d3c2b01e3514c7ea602bff2072842cd266e43c7db'),
 ('quotient_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'WIDTH[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  'a96ea5985729fd99e86d487b3de5bb0ca53376b3b884e77e793416b4ce212d5e'),
 ('remainder_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'WIDTH[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  'bfe74e31823afcbc29b7fd5df4633940272ed9399615f6e9c4789deb31cad022'),
 ('valid_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'WIDTH: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '514cc020d908c987142a46c182696b20cb6d36717bc38d416347c444eea88310'),
 ('start_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'WIDTH: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '4af4e819dc5932d9e67060ac477361a86b6575d1d601edb098000d7bf57bacc6'),
 ('rst_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'WIDTH: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '044140116fcf4a86b3eaa573167c538535cbb1dde6e9044a2fe9ad526ba92d36'),
 ('clk_identifier_WIDTH',
  'EMIT',
  'Input ports:\n'
  'WIDTH: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '1fcb2d08c79b35926da08b7fc99ae9dc7e81d8d1377b8da88d12b08f2a7c2303'),
 ('ordinary_BASE',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero. Dividend is at least divisor.',
  '4b013241290b48968bb24105c9d16ea8f846fcadcbd1dddc942d93224d32335b'),
 ('ordinary_bullet_domains',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  '- The divisor is nonzero.\n- Dividend is at least divisor.',
  'd584c11aac3ecc2c649d58134930552d3a3ab3e6062a8ab743045d1daa3d187a'),
 ('ordinary_paragraph_domains',
  'EMIT',
  'Input ports:\n'
  'clk: posedge clock.\n'
  'rst: active-low asynchronous reset.\n'
  'start: one-cycle request.\n'
  'dividend[WIDTH-1:0]: unsigned dividend.\n'
  'divisor[WIDTH-1:0]: unsigned divisor.\n'
  'Output ports:\n'
  'quotient[WIDTH-1:0]: unsigned quotient.\n'
  'remainder[WIDTH-1:0]: unsigned remainder.\n'
  'valid: one-cycle completion.',
  'The divisor is nonzero.\n\nDividend is at least divisor.',
  '2c1202af82a2aab9d696059a3bd97fbc52e886d632e5b48960eb105752570a57')]


@pytest.mark.parametrize("case,expected,interface,domain,source_sha256", _R9_CASES,
                         ids=[row[0] for row in _R9_CASES])
def test_unsigned_divider_r9_exact_independent(case, expected, interface, domain,
                                              source_sha256, tmp_path):
    import hashlib
    description = _R9_SPEC.format(interface=interface, domain=domain)
    assert hashlib.sha256(description.encode()).hexdigest() == source_sha256
    source, rtl = tmp_path / "description.txt", tmp_path / "candidate.v"
    source.write_text(description)
    command = subprocess.run([sys.executable, str(PROGRAMS / "canonical_primitive_synth.py"),
                              "--from-desc", str(source), "--out", str(rtl)],
                             capture_output=True, text=True)
    response = json.loads(command.stdout)
    assert response["verdict"] == expected, response
    emit = expected == "EMIT"
    assert command.returncode == (0 if emit else 2), command.stderr
    assert rtl.is_file() == emit
    project = tmp_path / "project"
    input_doc = project / "phase1/input_doc/design_description.txt"
    input_doc.parent.mkdir(parents=True)
    input_doc.write_bytes(source.read_bytes())
    consumer = _load_runner()._try_canonical_primitive_rtl(project, time.time())
    outputs = list(project.glob("phase2/stage1/rtl/*.v"))
    actual = "EMIT" if consumer is not None and consumer.status == "PASS" and outputs else "DEFER"
    assert actual == expected, {"observed": actual, "expected": expected, "case": case}
    assert bool(outputs) == emit
    if emit:
        assert len(outputs) == 1 and outputs[0].read_bytes() == rtl.read_bytes()
        compiler = subprocess.run(["iverilog", "-g2012", "-s", "extra_scope_unit",
                                   "-o", str(tmp_path / "sim.out"), str(rtl)],
                                  capture_output=True, text=True)
        assert compiler.returncode == 0, compiler.stdout + compiler.stderr


# R10: explicit target-domain permissions/withdrawals must survive neither
# the publishing CLI nor the normal production consumer. Each review input
# has a stable product ID; the broader cases exercise grammar, not string lookup.
_R10_CONTRADICTIONS = [
    ("compound_divisor_first", "The divisor and dividend requirements are removed", "nonzero operand domain"),
    ("all_of_above", "All of the above requirements are removed", "nonzero operand domain"),
    ("divisor_input_zero", "The divisor input may be zero", "nonzero operand domain"),
    ("zero_allowed_for_divisor", "Zero is allowed for the divisor", "nonzero operand domain"),
    ("divisor_allowed_zero", "The divisor is allowed to be zero", "nonzero operand domain"),
    ("embedded_ordering_removed", "The requirement that dividend is at least divisor has been removed", "dividend >= divisor domain"),
    ("ordering_no_longer_required", "Dividend is no longer required to be at least divisor", "dividend >= divisor domain"),
    ("divisor_need_not_nonzero", "The divisor need not be nonzero", "nonzero operand domain"),
    ("divisor_values_occasional_zero", "Divisor values may occasionally be zero", "nonzero operand domain"),
]
_R10_DOMAIN = "The divisor is nonzero. Dividend is at least divisor. "


@pytest.mark.parametrize("case,clause,unresolved", _R10_CONTRADICTIONS,
                         ids=[row[0] for row in _R10_CONTRADICTIONS])
def test_unsigned_divider_r10_review_contradictions(case, clause, unresolved, tmp_path):
    domain = _R10_DOMAIN + clause + "."
    _r5_assert_publication(domain, False, tmp_path)
    assert unresolved in rcs.route_to_ai_reason(_r5_domain_description(domain))["unresolved"]


_R10_VARIANTS = [
    ("synonym_compound", "The denominator and numerator constraints are waived."),
    ("input_requirement", "The divisor input requirement is retracted."),
    ("all_of_preceding", "All of the preceding guarantees have been cancelled."),
    ("zero_permitted_for", "Zero is permitted for the denominator."),
    ("zero_valid_input", "Zero is a valid divisor input."),
    ("denominator_permitted_zero", "The denominator value is permitted to be zero."),
    ("denominator_could_zero", "The denominator inputs could sometimes be zero."),
    ("embedded_nonzero_removed", "The requirement that divisor is nonzero is removed."),
    ("embedded_symbol_ordering", "The constraint that numerator >= denominator is waived."),
    ("embedded_ordering_inapplicable", "The guarantee that dividend is at least divisor does not apply."),
    ("nonzero_no_longer_required", "Divisor is no longer required to be positive."),
    ("nonzero_not_required", "The divisor is not required to be nonzero."),
    ("ordering_need_not", "Dividend need not be at least divisor."),
    ("ordering_not_required", "The dividend is not required to be at least the divisor."),
    ("embedded_not_required", "The requirement that dividend is at least divisor is no longer required."),
]


@pytest.mark.parametrize("case,clause", _R10_VARIANTS, ids=[row[0] for row in _R10_VARIANTS])
def test_unsigned_divider_r10_semantic_variants(case, clause, tmp_path):
    _r5_assert_publication(_R10_DOMAIN + clause, False, tmp_path)


_R10_CONTROLS = [
    ("ordinary", ""),
    ("output_permission", "The quotient output may occasionally be zero."),
    ("reset_permission", "The reset input is allowed to be zero."),
    ("unrelated_requirement", "The output requirements are removed."),
    ("unrelated_embedded_requirement", "The requirement that quotient is at least zero has been removed."),
    ("unrelated_operand_property", "The divisor input bit-width requirements are removed."),
    ("negated_compound_withdrawal", "The divisor and dividend requirements are not removed."),
    ("negated_global_withdrawal", "All of the above requirements have not been removed."),
    ("negated_embedded_withdrawal", "The requirement that dividend is at least divisor has not been removed."),
    ("negated_zero_permission", "The divisor input may not be zero."),
    ("negated_allowed_zero", "The divisor is not allowed to be zero."),
    ("negated_zero_for", "Zero is not allowed for the divisor."),
    ("required_nonzero", "The divisor is required to be nonzero."),
    ("required_ordering", "Dividend is still required to be at least divisor."),
    ("reference_permission", "The reference model divisor input may be zero."),
    ("reference_withdrawal", "Another design: The divisor and dividend requirements are removed."),
    ("quoted_permission", 'The manual quotes "The divisor is allowed to be zero".'),
    ("conditional_permission", "If test mode is active, the divisor input may be zero."),
    ("example_permission", "Examples:\n- The divisor input may be zero."),
    ("unrelated_zero_context", "The quotient is allowed to be zero for the divisor."),
    ("dividend_zero_denial", "The dividend input may not be zero."),
]


@pytest.mark.parametrize("case,clause", _R10_CONTROLS, ids=[row[0] for row in _R10_CONTROLS])
def test_unsigned_divider_r10_unrelated_controls(case, clause, tmp_path):
    import hashlib
    _r5_assert_publication(_R10_DOMAIN + "\n" + clause, True, tmp_path)
    rtl = tmp_path / "unit.sv"
    ordinary = rcs.emit_rtl("unsigned_iterative_restoring_divider",
                            _r5_domain_description(_R10_DOMAIN))
    # Prose changes its provenance hash, while leaving every RTL byte intact.
    digest = hashlib.sha256((tmp_path / "description.txt").read_bytes()).hexdigest()
    ordinary = re.sub(r"(?m)^// Input contract SHA-256: [0-9a-f]{64}$",
                      "// Input contract SHA-256: " + digest, ordinary)
    assert rtl.read_text() == ordinary
    compiler = subprocess.run(["iverilog", "-g2012", "-s", "unsigned_ratio_unit",
                               "-o", str(tmp_path / "sim.out"), str(rtl)],
                              capture_output=True, text=True)
    assert compiler.returncode == 0, compiler.stdout + compiler.stderr


# R11: exact independent INPUTs and a bounded cross-product of the supported
# operand/predicate grammar. Both public paths run before any verdict assertion.
_R11_SPEC = 'Design an unsigned iterative arithmetic unit using the restoring division algorithm.\nModule name: review_ratio_unit\nParameter WIDTH has a default value of 8.\nInput ports:\nclk: posedge clock.\nrst: active-low asynchronous reset.\nstart: one-cycle request.\ndividend[WIDTH-1:0]: unsigned dividend.\ndivisor[WIDTH-1:0]: unsigned divisor.\nOutput ports:\nquotient[WIDTH-1:0]: unsigned quotient.\nremainder[WIDTH-1:0]: unsigned remainder.\nvalid: one-cycle completion.\nThe divisor is nonzero. Dividend is at least divisor.\n{clause}\nOn reset all outputs clear. New inputs are accepted after the previous result.\nAt each restoring iteration append the next dividend bit to the shifted partial remainder and subtract the divisor; a negative trial restores the shifted partial remainder and produces quotient bit zero.\nCompletion takes WIDTH cycles for power-of-two WIDTH and WIDTH+1 cycles otherwise; no extra input-only cycle.\n'

_R11_CASES = [('both_determined_operands',
  'Both the divisor and the dividend requirements are removed.',
  'f1170823b8a8daabbf8fba2409b8abe536514e3bc28f7553fe0e7feb5c4abd45'),
 ('all_those_requirements',
  'All of those requirements are removed.',
  '395a59cafcde795207d33f11d8319e4598a993714d8b56ae749ef820ccd82dce'),
 ('requirements_for_operands',
  'The requirements for divisor and dividend are removed.',
  'b858d7b8abd6a6421290e0e3cd9bfd52c74580da5a39531a3410af87c4b511d7'),
 ('embedded_input_nonzero',
  'The requirement that the divisor input is nonzero has been removed.',
  '0beeb5995d552533df0eb39a306d165e262951851c04e92759a2d3bc55758f54'),
 ('embedded_value_nonzero',
  'The requirement that the denominator value is nonzero is waived.',
  '3ffa10f6c84151a1db93646d70b39798b0c375c1aa0cc99194d545e06e01ebf2'),
 ('embedded_qualified_ordering',
  'The requirement that dividend input is at least divisor has been removed.',
  'e205580850ca53e51d7325b85413ada23299584352a1dbded0df2b97b456771f'),
 ('embedded_compound_nonzero_first',
  'The requirement that divisor is nonzero and dividend is at least divisor has been removed.',
  '63343bef2e6c217df10b4accd26c02e9d59481b388779f47eccac0d0050270e8'),
 ('embedded_compound_order_first',
  'The requirement that dividend is at least divisor and divisor is nonzero has been removed.',
  'cf3522363d4bbe0b1be3d460543cc5c7cbf87170424ae8e6134d0d2114e42cc8'),
 ('relaxed_symbolic_order',
  'Dividend is not required to be >= divisor.',
  '7d900f834aafe07d7c1b2bfa3c335e3fd090f7cf2d03d21711ae85a31d1f6a08'),
 ('relaxed_unicode_order',
  'Dividend is no longer required to be ≥ divisor.',
  '2d1fb6050f66af134bbeff82795f5047b15484e9e8a510624f939ef0ebf9f5ae'),
 ('zero_dividend_reverse',
  'Zero is allowed for the dividend.',
  'cde5a2f3e4fb88658d7abc3a46ae0f196c3010640b939e3dbd36174c86e33844'),
 ('zero_numerator_reverse',
  'Zero is permitted for the numerator.',
  '3d9ea82462d68f0aa59e09a576bd01a639e7dd7021ec8259f6fab866ac50ddb7'),
 ('ordering_dividend_input',
  'Dividend input may be less than divisor.',
  'b5e7ba8e9adf88fb118d48059ba05ef87bdb72c1cbabe9bb9f7a180dec20afea'),
 ('ordering_numerator_values',
  'Numerator values can sometimes be smaller than denominator.',
  'e2d91d3432266cb10c583c0379bbee2c3fb5bd44e6146674558d5686d7a43a85'),
 ('zero_equal_permission',
  'The divisor is allowed to equal zero.',
  '0540d020b08797503fafb6ed23b14ea1b92638f83724ce94ba57ad6a33be428a'),
 ('zero_accept_permission',
  'The divisor input accepts zero.',
  '4db8923672d64a472916900a796570b50fdfe8d784ed3f99dfcc666e5de3b359')]

_R11_POSITIVES = [('plain', '', 'e52cbee96c946d4190b4edaab9ee3d068d573ad77e3e324794d49b3ec40088b8'),
 ('quotient_zero',
  'The quotient output may occasionally be zero.',
  '43cbc6526b0fe6eca9c037243c9640fe721e3f307b1f01a26acbe75dbe6bc7b9'),
 ('reset_zero',
  'The reset input is allowed to be zero.',
  'e12c1b3c7c79c3f58dc994928ee42028b4f6f49fc2d25e01e2e384f40be3109f'),
 ('output_withdraw',
  'The output requirements are removed.',
  '20aba95e1e33e4290f91750cb09b3fcc3790b65a180ce30477217d47060298b4'),
 ('width_withdraw',
  'The divisor input bit-width requirements are removed.',
  '4e1f9ce191529f4bf4f9b3876f11052d1b75615c5fd0f4c462d0d52395927315'),
 ('embedded_quotient_withdraw',
  'The requirement that quotient is at least zero has been removed.',
  '8f3581a9ec80de543dc383eea6ac5b9cc6c32edd2de165437a4e477c833be59b'),
 ('embedded_reset_withdraw',
  'The requirement that reset is nonzero has been removed.',
  '0929343cc9e03b4795e73ff1b1f3404141280688bbdd0f0369a083187fb65113'),
 ('not_required_zero',
  'The divisor is not required to be zero.',
  'd621d4e1b955552d9019775b33672001b909f24dff170a3d38d94effbd333aa8'),
 ('need_not_zero',
  'The divisor need not be zero.',
  '81e3076674b5de4e1de6c5a3029f23ba17339255bad27cb32cfb9f1e5590c719'),
 ('never_removed',
  'The divisor and dividend requirements have never been removed.',
  '5de575ab57c171fffd64f5a0d0f2b05ac3e63445783fe9a7aec3933767f6200c'),
 ('not_waived',
  'The divisor and dividend requirements are not waived.',
  'e6b51f4bff07cc95c3d938957d0daa81ce2c8409ab7a4de47079e7bc7b68e3c5'),
 ('not_compound_removed',
  'The divisor and the dividend requirements have not been removed.',
  '6c3d2ab1c9b450cae9a770f352a607a6d2467227b047fbbba1551ce4a72c6c44'),
 ('not_all_removed',
  'All of the above requirements have not been removed.',
  '0d2570bb50c70bf6b8dd13d3166a791e7b3f6b4eda2f7db2f0b85ff34c0a0df9'),
 ('embedded_not_removed',
  'The requirement that dividend is at least divisor has not been removed.',
  '8cad4e88e4e7acd683ff14113cd7102ea2ccae1f428c38d1508674e0796aba54'),
 ('embedded_not_optional',
  'The requirement that divisor is nonzero is not optional.',
  'e0398d6115365256ee62ea38fa8b1424cddc131b60a9163593a9e821cd2ac15a'),
 ('input_may_not_zero',
  'The divisor input may not be zero.',
  '8fe58e4bcba3fd0c2d780ab3e07d48b73b8934547354f79e418783a7f5c45877'),
 ('values_cannot_zero',
  'Divisor values cannot occasionally be zero.',
  '7e84946fe5a3a7a0de4dee560aa665adae2f6fc35009b22091ed679ab280b8c0'),
 ('not_allowed_zero',
  'The divisor is not allowed to be zero.',
  'd59c11ff7caebfd4479adff80e16e6cc9aaeb8f2ba866dcac878aa389aceb248'),
 ('zero_not_for_divisor',
  'Zero is not allowed for the divisor.',
  'b1e969f26b8ef28fde2cf2cdc386831ced2fbc2962104154c9485d6fa9dac12f'),
 ('positive_retained',
  'The divisor is still required to be positive.',
  '58ef00fabf8664f4348ba9b6054c6e584266661d33a54a119fa0d32210eba57e'),
 ('order_retained',
  'Dividend is still required to be at least divisor.',
  '928a602d1a5b7ff0ec8d1fd7328c1d51391dff80e8b038912af264984f8f2fba'),
 ('external_forward',
  'The reference model divisor input may be zero.',
  'e8d84e4130c3a93df339e23149e2ca582402841d64d936aefec08b1670309390'),
 ('external_withdraw',
  'Another design: The divisor and dividend requirements are removed.',
  '03ca0cbf80cefa81bd1ec8bf736461b8e4b5296e36ce2917f2549800301fe06a'),
 ('conditional_forward',
  'If test mode is active, the divisor input may be zero.',
  'e49285f867b517f8a04e187777f2560a0cd64bef861464a56829a468310189dc'),
 ('example_forward',
  'Examples:\n- The divisor input may be zero.',
  'd00579af65390f7dad440391e31ec31940991613c36bbec3636adb899434f4d8'),
 ('quote_forward',
  'The manual quotes "The divisor is allowed to be zero".',
  '2eebc314b084c373edc27cedf731e8254679e1fdeac72b48f9bb07200cd125f1'),
 ('curly_quote_embedded',
  'The manual quotes “The requirement that dividend is at least divisor has been removed”.',
  '30babed7ca98870afc69693672664e0b7369f4fcd09b0031601f72366280da58'),
 ('code_quote_zero',
  'The manual quotes `Zero is allowed for the divisor`.',
  '61f0b5c9a1564a4e241c85f206a95ef0ad4c73e95b3f9284c7d93fc930bfe19d'),
 ('unrelated_mixed_not_zero',
  'The quotient may be zero, but divisor input may not be zero.',
  '25aec762e960a384771747f8aa2553de787ad52fbc7bd3fc8cad0c2cf36209a0'),
 ('output_nonzero_withdraw',
  'The quotient is no longer required to be nonzero.',
  '95a9a8792bfcc06fb72a8ec84d7226d7fe287d12c8826bbc686162f115ddcacd'),
 ('negated_mixed',
  'All of the above requirements are not removed and the output may be zero.',
  '1dbec743dbd18d8aef4a3bda436e2e59eba6bb9228e84ebbae76c227da16fcc8'),
 ('denied_forward_both',
  'The divisor is not allowed to be zero and the dividend is not allowed to be zero.',
  '14e82eac68978e84101521c76c325bcb2af56e97f063764db8103c52b7766a14'),
 ('unrelated_prefix',
  'The output is not valid and the divisor is still required to be nonzero.',
  'b410686fd3c6cd88139ebbcb79e71e2ca9c203db38c23a333b767d19a100ff06'),
 ('unrelated_permission_reverse',
  'Zero is allowed for the quotient.',
  'ffa238505022daa8863e365f157de9fc7794418aefe66c0334ed4165a3b39be3'),
 ('unrelated_reset_reverse',
  'Zero is permitted for the reset input.',
  '5fbe6fd9f99f639bfed329cdf5b9e2f859f984617d711126045b53d23e5eab32'),
 ('quoted_output_next',
  'The manual quotes "The divisor is allowed to be zero". The quotient may be zero.',
  '167de12c7e44c7ef6dfb40e0adc9bac92066a03b18a400d3505a98ee8c962530'),
 ('same_sentence_output_denial',
  'The quotient is not always positive and divisor input may not be zero.',
  '5b5dba623954685ebc10e483f0fbcb9bcad3934c2fad69b6c9ec3e6a54f14599'),
 ('compound_divisor_first-quoted',
  'The manual quotes "The divisor and dividend requirements are removed".',
  '2b2f89b2389a4046b8bf4eff866e0f7aefea01051674c1da9f5a2c76fc4b68e9'),
 ('compound_divisor_first-external',
  'The reference design states: The divisor and dividend requirements are removed.',
  '4313acc834cdb38820d32bf4fc41e6c7b42583e63cefe4779228dfdd32b889a1'),
 ('compound_divisor_first-example',
  'Examples:\n- The divisor and dividend requirements are removed.',
  '935a560d589268bafb9397080b773831c90cd1cc6301aebe555b4b8266985422'),
 ('all_of_above-quoted',
  'The manual quotes "All of the above requirements are removed".',
  'bc8f4e41506a3034917dca553d9c02a87ebc7f775f0f22abe6ca3cf77a40a6f2'),
 ('all_of_above-external',
  'The reference design states: All of the above requirements are removed.',
  'c75f58a0bf33dbd8b6de5d29b0d1e745f4d45a36373564d5e3a1f5b195bb05f4'),
 ('all_of_above-example',
  'Examples:\n- All of the above requirements are removed.',
  '095c5aaa89ae2d7ac97a6af001ac4b6f42ff818a7fe5e5acb457181a5154ebbc'),
 ('divisor_input_zero-quoted',
  'The manual quotes "The divisor input may be zero".',
  '7eb1b716325309a520d1a34a2fe17d173a18cb76bfdf3ef47bb20e4d9673b01a'),
 ('divisor_input_zero-external',
  'The reference design states: The divisor input may be zero.',
  '24da4ff2554cca033ae401bae5c190c0346d07fcb2a2607fde77eb4af8cb361a'),
 ('divisor_input_zero-example',
  'Examples:\n- The divisor input may be zero.',
  'd00579af65390f7dad440391e31ec31940991613c36bbec3636adb899434f4d8'),
 ('zero_allowed_for_divisor-quoted',
  'The manual quotes "Zero is allowed for the divisor".',
  '13ba2a66c3b921999f2b4573cf9970e19d1015d44fcffcdd4f4d31d87f4e52e7'),
 ('zero_allowed_for_divisor-external',
  'The reference design states: Zero is allowed for the divisor.',
  'eaf09d3e5a2afa8b706f51c1aad292e8698be1eb7118d811272debaeb6ab78cd'),
 ('zero_allowed_for_divisor-example',
  'Examples:\n- Zero is allowed for the divisor.',
  '3d06d045d1832b6a05f736ef635479d1fa5c4f09f23aeb1c2cf0246ee8fc77ef'),
 ('divisor_allowed_zero-quoted',
  'The manual quotes "The divisor is allowed to be zero".',
  '2eebc314b084c373edc27cedf731e8254679e1fdeac72b48f9bb07200cd125f1'),
 ('divisor_allowed_zero-external',
  'The reference design states: The divisor is allowed to be zero.',
  '901d8a4f55bde97266dd4fdc1f8d5fe397f313b8afcbb7f190c155323b1ba45d'),
 ('divisor_allowed_zero-example',
  'Examples:\n- The divisor is allowed to be zero.',
  'cb672d9fc5e40248befe82dc3b306f47654662838e91cac93b3f2df46168dde5'),
 ('embedded_ordering_removed-quoted',
  'The manual quotes "The requirement that dividend is at least divisor has been removed".',
  'b0a635c0fe0a63ba3c3b01d561e3df8af02bdc5a9e934c6b9c00baad638a3ca9'),
 ('embedded_ordering_removed-external',
  'The reference design states: The requirement that dividend is at least divisor has been removed.',
  '267b0f1349a66a2b1f233939b26c158c605750e1348a9b1c16235e4fde09dfe9'),
 ('embedded_ordering_removed-example',
  'Examples:\n- The requirement that dividend is at least divisor has been removed.',
  '2e6ca2926dacf0dd8967a9b1a4cbdbc9236345b705d293f14d87789ec5176b3f'),
 ('ordering_no_longer_required-quoted',
  'The manual quotes "Dividend is no longer required to be at least divisor".',
  '2877347e3575958ffdca8b28946b73cfbd9d5e3701d1693b7186db7442f0afb4'),
 ('ordering_no_longer_required-external',
  'The reference design states: Dividend is no longer required to be at least divisor.',
  '850de0434644cc89b8a953138b25b3557af4da4ebe92bb598a1c695e8c4e7424'),
 ('ordering_no_longer_required-example',
  'Examples:\n- Dividend is no longer required to be at least divisor.',
  'f1dc1ec118104722fb1fd03584a0e12ba52ab23d11da84f44816846c72750747'),
 ('divisor_need_not_nonzero-quoted',
  'The manual quotes "The divisor need not be nonzero".',
  '5011aa34037a21511b8d3f382b5bdd7dd5fe4705f2be99a62e9f33670213b7dc'),
 ('divisor_need_not_nonzero-external',
  'The reference design states: The divisor need not be nonzero.',
  'bf07ad9c67b6256a5763c1b9d7f048952f71ecc26c8de52d61056cccb96f5669'),
 ('divisor_need_not_nonzero-example',
  'Examples:\n- The divisor need not be nonzero.',
  '88be78cf7923efdba2af4b18e07e78211ac0a699a01891bc00b3cbb26ea2bd3b'),
 ('divisor_values_occasional_zero-quoted',
  'The manual quotes "Divisor values may occasionally be zero".',
  'ba616494ac2b52a492707289b707a91e7ad37df121ae9497c63b539544dfe696'),
 ('divisor_values_occasional_zero-external',
  'The reference design states: Divisor values may occasionally be zero.',
  'f93cbf23fed1f93c98343a6eb5160e9c807ec1c152e60fd12d943ed512553617'),
 ('divisor_values_occasional_zero-example',
  'Examples:\n- Divisor values may occasionally be zero.',
  'afb19d9f0a8a2de12390d3c107667bda93d7dff28bfdea46e5c318641e9e9500')]

_R11_RTL_HASHES = {'all_of_above-example': '3661da86f15a6cfb4d056465b9c4d82b52ecd2d1e80a854dc6bd1c7e8651c8cc',
 'all_of_above-external': '6d8f906ac781c9fd249429362ab721566f5eadb8177fbfee87452574b773f0e4',
 'all_of_above-quoted': 'bc1ea347e8ad922aaa3daad233ccc68acd905ca82bd41d282c92d83d9d2bfc47',
 'code_quote_zero': '52a9ea9150aacaed1cbce00f73afe3dbbee6eee82908fb1a92a857cac4789a55',
 'compound_divisor_first-example': '38d2742efb3a942c85de87a7b8c42f71130b916af9e740210b1cda74e96147ef',
 'compound_divisor_first-external': '78f9dbfc2d3d7f6071bcbe12fb3218d426b6d3df7a040b27c77c68eadda3f918',
 'compound_divisor_first-quoted': 'a99b692579066f684f0d86574fea231a06c395fea6f67337a8b9c2ad0347be2f',
 'conditional_forward': 'c4fbabdfeb537ff756d79f7d04fd347cdd291b7072691f00aaf0ddb03e139fe6',
 'curly_quote_embedded': 'fe7431669869d6b1cfafd49977bf183840790ff8993680eaf4980c72518b5fde',
 'denied_forward_both': 'e2a8f22279b97153d57a6c117ed9e02a80188deec11f14e7ae181c963794156f',
 'divisor_allowed_zero-example': '3cae98cd57028057e16d6f496de5d41c6469c6f400110ffaef9655d1329cce72',
 'divisor_allowed_zero-external': '3d0c85ce29aac90f2c3cc3727e3959380b4ad58c9f0ae70459164a44520b329f',
 'divisor_allowed_zero-quoted': '16f9f1b76e0b0ebf01a4199e3e0b374840b038566782ed678f5c760a1dcb6a04',
 'divisor_input_zero-example': '759d3e2cc128bfe61de7a0a1f0d4e347c5f95fd02db3eac264741a3bfd517b11',
 'divisor_input_zero-external': '1055bc45ef516bb22b25f65d79a5630ef35f870628b700c3dad85170c11701f4',
 'divisor_input_zero-quoted': 'd6b7d7282b4870f1daafab45c0c8195dd3ccc76c3c7ae7f08afe26e2a9b72250',
 'divisor_need_not_nonzero-example': 'bb5118f1a07e1ab0906e6fae61e0d6fc3e7073853839d86b2717a531b1b0d9bb',
 'divisor_need_not_nonzero-external': 'a5a2a604dd901189cda55812de9a6c72b5bf677de483b34487c195f8d1332e92',
 'divisor_need_not_nonzero-quoted': 'c7dc0f11bf48c5df5c3c0dcc4cbe7ba7ddc2b5c72fa6a57b28874b2023c3f814',
 'divisor_values_occasional_zero-example': '5a9a3119b96ea525732fe3073a094bce0c57a992b66f0cb4ac78277730a55842',
 'divisor_values_occasional_zero-external': '37b0ad0a13db06d91c3710891c13257e56b5bc9eef2123a37a036cf0951da4ea',
 'divisor_values_occasional_zero-quoted': '602571809d0d3502068c651814d1f915e8c56d4275f5aab0704f450337df7a63',
 'embedded_not_optional': 'c7817e461a335d43f4d290d83da8c4e931923c514bfd06a47518c79f5dac1b40',
 'embedded_not_removed': 'b05d63edd2af3ae398948f44e5293790ce164fa094b0164369a2531ccd98c491',
 'embedded_ordering_removed-example': 'f20caad2054c01c88aacb6e1cbda12a43daafa602cce758d7f0b0ef261dd07d1',
 'embedded_ordering_removed-external': '64d1c4cb6d975d3b27b791e0655bdc23f80ae2308c0e1d6cb46815076cce34e3',
 'embedded_ordering_removed-quoted': 'a1dbc2cf38996306c1dc83b0723a98dd3fecc9df3871d7078ab5940ad932a0c9',
 'embedded_quotient_withdraw': '2277a457a62fbea1b74ffb4cc375f0ef7a822e38a04a5a1ab2a5e13100b8fe90',
 'embedded_reset_withdraw': '47a6c6fc23b36ad305f5c3fd493d9fe0786e5b89a581c995befd610d507d16b0',
 'example_forward': '759d3e2cc128bfe61de7a0a1f0d4e347c5f95fd02db3eac264741a3bfd517b11',
 'external_forward': '7d79665eb8e844f358404892a6b7a70e743f4be8ff9142912dc5ef28dc9529b3',
 'external_withdraw': '47dd4da6a8e2356f9f135d5c5bec0cc1455fc662bfaadb1d7738f40146e26c2b',
 'input_may_not_zero': '06b7cbe57eeafcb040b9b9f44262d7fe679ad9ec04275d715fc5ca6d1c20a0fd',
 'need_not_zero': '417c7391cbc213cee9556feb360cc9ba958d28ec21d4158015db4933732ad90d',
 'negated_mixed': 'd5152cb9ace0b600e2d93adca4b31bfed29fb2415ff4a623b782d6b0e30a5d80',
 'never_removed': 'e9f3c34366fbe6cd186d183be5e3a4961cc59f64d1691043328e7a08d5e45221',
 'not_all_removed': '3ff9eccd3695e7c42201366f021e0be89c45b95219d84ccbaacc6356c9359327',
 'not_allowed_zero': 'e9a24dcc91681068a9fbe865e5d1f2f8f0c6feea2f5f81640e646134a2b7c19c',
 'not_compound_removed': '1de712ac21c85c5d83f3fba01f34f373ed475a4d543f31a29601272e443b7b74',
 'not_required_zero': '04e4e2dad81056e73253d263391469b9b1068d17ff5de217d7eb17c2a94aab34',
 'not_waived': '31aa027e693904493235cffb6e367c61456ca740999cb76ecd5f0269a5965802',
 'order_retained': 'ff767cc7b25507bf9ca7315c2fb4f604f3b4382e979a14f913cf71a672c67964',
 'ordering_no_longer_required-example': 'cf287eaff29e4801327f4081932352ddaeb23a6904a97d49aafcd78a3b3554df',
 'ordering_no_longer_required-external': '90fac0fb3e334f47611b4bc3e75ca21c570559ccb56b76db928fca5316d32180',
 'ordering_no_longer_required-quoted': '242fbdeb322d7c2e287d38c3f3d9b67ddedfb43d7199f1c4ed438d20cad4bae9',
 'output_nonzero_withdraw': '3f4e539a8148b389db7709bf6cad0abc37330e42fe4be0a85ac893d4e4d5bc29',
 'output_withdraw': 'd19917dc6f52fea2ea7dfb88b553ebbdea45a2da52a1c6ffe3224bfffb4c135c',
 'plain': 'f9055e8be6c1e1cb8b1e94784c414b9da205c4ad1bab344ec7504d16c2954e39',
 'positive_retained': '5f023faa93830b023508c66341c180d2e1e85e843cec8ac4ce0833342416dc3c',
 'quote_forward': '16f9f1b76e0b0ebf01a4199e3e0b374840b038566782ed678f5c760a1dcb6a04',
 'quoted_output_next': '1eb57f2fd1d671680a6ff1d61406f5d44d4277cef95f9a5a2cf79e5b36171e47',
 'quotient_zero': 'c3bf9e230f1d0598e98c9287f07df0b87140e4a252789afb2edb7733d6cd5906',
 'reset_zero': '5945257ce2134c7a1500cd2ff5d305868e16052e84711221869b1c16f56c5ce9',
 'same_sentence_output_denial': 'b941324a17941bc4aa2ab60d13113c1e7a4e355453f91f430428eddf07dd9073',
 'unrelated_mixed_not_zero': '211b152ba72c5363dd97d1c0c13e2b7f18bfa9b07cbf18bd45819895bfb913fc',
 'unrelated_permission_reverse': '3118c82fc31d0e72e43f27aa2289e2d90f74e2eada7013beb64372ba8f3866f0',
 'unrelated_prefix': '3ac66aaf51027ad04807bafa2b29958e3f2fcf60706bbcddb396a95c8f64ac8f',
 'unrelated_reset_reverse': '2b9bff00f0022ecd9eadca27840c1aee7241e117c20fec3ba73ea9fbe8827c68',
 'values_cannot_zero': '2270319648aa569536f1806eb5439b0e92910e03a7d7845ec0ccaf1a6fb18d5d',
 'width_withdraw': '4cdf1bb4990b72a6777fd96cef44245e00e5c0819f0ab0681d86628d539abda7',
 'zero_allowed_for_divisor-example': 'fbaac2a46f0a3599b6b2cf6794dff72657984a2af2d38b44a00964570071f853',
 'zero_allowed_for_divisor-external': '2076489dc365af5db266da0070df954b2809f18b1aa0251c58fa67bea56a9807',
 'zero_allowed_for_divisor-quoted': '802635cfdbadbf44abb9a5e0a27ab95e3e4f93032be175987c7be4e12f131119',
 'zero_not_for_divisor': 'e60695a1936adec269e85a51363e45bc2de2889c6308a14c79d720f07b4b016b'}


def _r11_public_paths(description, expected, tmp_path, rtl_sha256=None):
    import hashlib
    source, rtl = tmp_path / "description.txt", tmp_path / "candidate.v"
    source.write_text(description)
    cli = subprocess.run([sys.executable, str(PROG), "--from-desc", str(source),
                          "--out", str(rtl)], capture_output=True, text=True)
    payload = json.loads(cli.stdout)
    project = tmp_path / "project"
    doc = project / "phase1/input_doc/design_description.txt"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(source.read_bytes())
    result = _load_runner()._try_canonical_primitive_rtl(project, time.time())
    outputs = list(project.rglob("*.v")) + list(project.rglob("*.sv"))
    assert payload["verdict"] == expected, payload
    assert cli.returncode == (0 if expected == "EMIT" else 2), cli.stderr
    assert rtl.exists() == (expected == "EMIT")
    if expected == "DEFER":
        assert payload["defer_reason"]["kind"] == "unsupported_unsigned_iterative_divider"
        assert result is None
        assert outputs == []
    else:
        assert result is not None and result.status == "PASS"
        assert len(outputs) == 1
        assert outputs[0].read_bytes() == rtl.read_bytes()
        if rtl_sha256 is not None:
            assert hashlib.sha256(rtl.read_bytes()).hexdigest() == rtl_sha256
        compiler = subprocess.run(["iverilog", "-g2012", "-s", "review_ratio_unit",
                                   "-o", str(tmp_path / "sim.out"), str(rtl)],
                                  capture_output=True, text=True)
        assert compiler.returncode == 0, compiler.stdout + compiler.stderr


@pytest.mark.parametrize("case,clause,source_sha256", _R11_CASES, ids=[x[0] for x in _R11_CASES])
def test_unsigned_divider_r11_exact_review(case, clause, source_sha256, tmp_path):
    import hashlib
    description = _R11_SPEC.format(clause=clause)
    assert hashlib.sha256(description.encode()).hexdigest() == source_sha256
    _r11_public_paths(description, "DEFER", tmp_path)


@pytest.mark.parametrize("case,clause,source_sha256", _R11_POSITIVES, ids=[x[0] for x in _R11_POSITIVES])
def test_unsigned_divider_r11_positive_boundary(case, clause, source_sha256, tmp_path):
    import hashlib
    description = _R11_SPEC.format(clause=clause)
    assert hashlib.sha256(description.encode()).hexdigest() == source_sha256
    _r11_public_paths(description, "EMIT", tmp_path, _R11_RTL_HASHES[case])


def _r11_grammar_cases():
    rows = []
    qualifiers = ("", " input", " value", " values")
    for dividend, divisor in (("dividend", "divisor"), ("numerator", "denominator")):
        for qualifier in qualifiers:
            left, right = dividend + qualifier, divisor + qualifier
            for comparison in ("at least", ">=", "≥"):
                stem = f"{left}-{comparison}-{right}"
                positive = f"The {right} is nonzero. The {left} is {comparison} {right}."
                rows.append((stem + "-required", positive, "EMIT", True))
                rows.append((stem + "-relaxed", f"The {left} is not required to be {comparison} {right}.", "DEFER", False))
                rows.append((stem + "-smaller", f"The {left} can sometimes be smaller than {right}.", "DEFER", False))
            predicates = (f"{right} is nonzero", f"{left} is at least {right}")
            for order in (predicates, predicates[::-1]):
                clause = "The requirement that " + " and ".join(order) + " has been removed."
                rows.append((stem + "-complement-" + order[0], clause, "DEFER", False))
    for role in ("divisor", "denominator", "dividend", "numerator"):
        for qualifier in qualifiers:
            operand = role + qualifier
            for verb in ("allowed to equal", "accepts"):
                clause = f"The {operand} is {verb} zero." if verb != "accepts" else f"The {operand} accepts zero."
                rows.append((operand + "-" + verb, clause, "DEFER", False))
            rows.append((operand + "-reverse", f"Zero is permitted for the {operand}.", "DEFER", False))
            rows.append((operand + "-reverse-denied", f"Zero is not permitted for the {operand}.", "EMIT", False))
    rows.extend([
        ("unknown-complement", "The requirement that divisor has an unspecified admissible range has been removed.", "DEFER", False),
        ("unknown-modal-predicate", "The divisor input may be outside an unspecified range.", "DEFER", False),
    ])
    return rows


_R11_GRAMMAR = _r11_grammar_cases()


@pytest.mark.parametrize("case,clause,expected,replace_domain", _R11_GRAMMAR,
                         ids=[x[0] for x in _R11_GRAMMAR])
def test_unsigned_divider_r11_bounded_grammar(case, clause, expected, replace_domain, tmp_path):
    description = _R11_SPEC.format(clause=clause)
    if replace_domain:
        description = description.replace("The divisor is nonzero. Dividend is at least divisor.\n", "")
    _r11_public_paths(description, expected, tmp_path)


# R12: exact six reviewer inputs under both ordinary module/WIDTH identities.
_R12_CASES = [('coordinated_comma',
  'The guarantee that divisor input is nonzero, and dividend input is ≥ divisor input is cancelled.',
  'review_ratio_unit',
  8,
  'DEFER',
  '33942f5657eeb1b34678158dfb309387fe6346e0e51f496300a52cd546ed3bee'),
 ('unknown_complement_not_removed',
  'The requirement that the divisor input has an unspecified admissible range has not been removed.',
  'review_ratio_unit',
  8,
  'DEFER',
  '2f4c71fc6b76ec4e2326dd3514a932df9dbb5d65e1e46e460d8aebab8dce3e75'),
 ('output_mentions_divisor',
  'The requirement that quotient is at least divisor has been removed.',
  'review_ratio_unit',
  8,
  'EMIT',
  'f74bac29d6fce704ecd3e5d3dd14dff0d3949a3cc0df0397ceb39ee272bd96d9'),
 ('output_mentions_dividend',
  'The requirement that quotient output is nonzero for dividend has been removed.',
  'review_ratio_unit',
  8,
  'EMIT',
  '8d7a94d90d68d0ff3aabee7f0dde1e60a137862610efbae981300b1a50b3c68b'),
 ('plural_negation_then_withdraw',
  'Both the divisor and the dividend requirements are not waived but are removed.',
  'review_ratio_unit',
  8,
  'DEFER',
  '55af61a0ceee73182328e092ef0f726bed51330a59fddac09419a8f274f87e76'),
 ('demonstrative_negation_then_withdraw',
  'All of those requirements are not waived but are removed.',
  'review_ratio_unit',
  8,
  'DEFER',
  '20438df50475350becba19703e463c6ee635f9795647d6d9f7a01e061f54e506'),
 ('coordinated_comma-width9',
  'The guarantee that divisor input is nonzero, and dividend input is ≥ divisor input is cancelled.',
  'confirmation_ratio_unit',
  9,
  'DEFER',
  '6d5a11c5651cbe46b337856f28fed5d05f0cbc3918f1780329f4b6b12fc3dc1a'),
 ('unknown_complement_not_removed-width9',
  'The requirement that the divisor input has an unspecified admissible range has not been removed.',
  'confirmation_ratio_unit',
  9,
  'DEFER',
  'c96c1aae01ed5dd3e991e785b609fdeceb14e2512c4bd14f5ae0490ba9933751'),
 ('output_mentions_divisor-width9',
  'The requirement that quotient is at least divisor has been removed.',
  'confirmation_ratio_unit',
  9,
  'EMIT',
  '68fcca82a29e80705730e02def634dfefe5d25bf86f73dafd07455e55ff56b6e'),
 ('output_mentions_dividend-width9',
  'The requirement that quotient output is nonzero for dividend has been removed.',
  'confirmation_ratio_unit',
  9,
  'EMIT',
  '466c8ed64a8ac7b2dc4448f4f2670fb775e05eace533799e8f81a8135e21acc9'),
 ('plural_negation_then_withdraw-width9',
  'Both the divisor and the dividend requirements are not waived but are removed.',
  'confirmation_ratio_unit',
  9,
  'DEFER',
  '827cd5761865d05a32aad4a9a75864f8d747ae4a87b7fbedf93de07d4c59491e'),
 ('demonstrative_negation_then_withdraw-width9',
  'All of those requirements are not waived but are removed.',
  'confirmation_ratio_unit',
  9,
  'DEFER',
  '644e0bc3553130019309498587becb31d59de978e0b572abcab7bd3657c93935')]


@pytest.mark.parametrize("case,clause,module,width,expected,source_sha256", _R12_CASES,
                         ids=[row[0] for row in _R12_CASES])
def test_unsigned_divider_r12_exact_review(case, clause, module, width, expected, source_sha256, tmp_path):
    import hashlib
    description = _R11_SPEC.format(clause=clause).replace("review_ratio_unit", module)
    description = description.replace("default value of 8.", f"default value of {width}.")
    assert hashlib.sha256(description.encode()).hexdigest() == source_sha256
    source, rtl = tmp_path / "description.txt", tmp_path / "candidate.v"
    source.write_text(description)
    cli = subprocess.run([sys.executable, str(PROG), "--from-desc", str(source),
                          "--out", str(rtl)], capture_output=True, text=True)
    payload = json.loads(cli.stdout)
    project = tmp_path / "project"
    doc = project / "phase1/input_doc/design_description.txt"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(source.read_bytes())
    result = _load_runner()._try_canonical_primitive_rtl(project, time.time())
    outputs = list(project.rglob("*.v")) + list(project.rglob("*.sv"))
    # Both public paths have executed before any observed verdict is asserted.
    assert payload["verdict"] == expected, payload
    assert cli.returncode == (0 if expected == "EMIT" else 2), cli.stderr
    assert rtl.exists() == (expected == "EMIT")
    if expected == "DEFER":
        assert payload["defer_reason"]["kind"] == "unsupported_unsigned_iterative_divider"
        assert result is None
        assert outputs == []
    else:
        assert result is not None and result.status == "PASS"
        assert len(outputs) == 1
        assert outputs[0].read_bytes() == rtl.read_bytes()
        compiler = subprocess.run(["iverilog", "-g2012", "-s", module,
                                   "-o", str(tmp_path / "sim.out"), str(rtl)],
                                  capture_output=True, text=True)
        assert compiler.returncode == 0, compiler.stdout + compiler.stderr
