"""R6-FIX-5 — an FPGA-vendor primitive inside a dead `ifdef arm is not evidence
that the file is an FPGA board wrapper.

THE DEFECT. `_is_fpga_board_wrapper` Signal 2 grepped the whole
comment-stripped body for an FPGA-vendor primitive instantiation. A module
written the standard portable way —

    `ifdef SIMULATION
       ... behavioural model ...
    `elsif FPGA_TARGET
       altsyncram #( .operation_mode("ROM"), ... )      <- matched HERE
    `endif

— was therefore classified an FPGA / board integration wrapper and DROPPED from
`_select_asic_rtl_sources`. The ASIC flow compiles with `-DSYNTHESIS -DYOSYS` /
`-DSIMULATION` and never defines the FPGA macro, so the matched text is dead
code on that target.

WHAT IT COST, measured on a real run whose top instantiates the dropped module:
16 of 17 staged RTL files reached yosys; the 17th was the one the top needed.

    yosys    ERROR: Module '\\otp_mem' referenced in module ... in cell
             '\\u_otp' is not part of the design      -> synth FAIL
             -> no netlist.v -> dft_lec_chain SKIP -> steps 11/12/13/DT1
                DEFERRED-BY-UPSTREAM
    iverilog Unknown module type: otp_mem ... referenced 4 times
             -> reference_tb FAIL -> rtl_repair_retry -> FAIL_RTL_REPAIR_INERT
                (byte-identical RTL, because the RTL was never the problem)

THE RULE AND WHY. Signal 2 now fires only on an UNCONDITIONAL match. This is an
asymmetry argument, not a preference: wrongly EXCLUDING a module the top
instantiates is a hard elaboration failure, while wrongly INCLUDING an FPGA
wrapper is benign because `synth -top <asic_top>` prunes what the top does not
reach. The tests below pin BOTH directions, so the fix cannot degrade into
"never exclude anything".
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as D  # noqa: E402


def _w(tmp_path, name, src):
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return p


def _is_wrapper(tmp_path, name, src, siblings=None):
    p = _w(tmp_path, name, src)
    return D._is_fpga_board_wrapper(p, siblings or {name})


# ───────────────── the capability must NOT be blinded ─────────────────

def test_unconditional_vendor_primitive_is_still_a_wrapper(tmp_path):
    """The whole point of Signal 2. A board wrapper instantiates its vendor
    primitives in live code."""
    assert _is_wrapper(tmp_path, "board.sv",
                       "module board;\n"
                       "  altsyncram #(.operation_mode(\"ROM\")) u0 (.a(a));\n"
                       "endmodule\n") is True


def test_primitive_after_endif_is_live_code_and_still_a_wrapper(tmp_path):
    """The masker must TERMINATE at `endif — otherwise the fix would blind
    Signal 2 for every file that contains any `ifdef at all."""
    assert _is_wrapper(tmp_path, "board.sv",
                       "module board;\n"
                       "`ifdef SIMULATION\n  reg r;\n`endif\n"
                       "  altsyncram u0 (.a(a));\n"
                       "endmodule\n") is True


def test_vendor_prefix_family_unconditional_is_still_a_wrapper(tmp_path):
    """Signal 2's PREFIX arm (RAMB*/DSP48*/PLLE*/…) is masked by the same
    helper, so it needs its own live-code control."""
    assert _is_wrapper(tmp_path, "board.sv",
                       "module board;\n"
                       "  RAMB36E1 #(.x(1)) u0 (.a(a));\n"
                       "endmodule\n") is True


# ─────────────── a dead conditional arm is not evidence ───────────────

def test_primitive_in_ifdef_arm_is_not_a_wrapper(tmp_path):
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n"
                       "`ifdef FPGA_TARGET\n"
                       "  altsyncram #(.x(1)) u0 (.a(a));\n"
                       "`endif\n"
                       "endmodule\n") is False


def test_primitive_in_elsif_arm_is_not_a_wrapper(tmp_path):
    """The exact shape that broke the real run: an ASIC/behavioural arm first,
    the FPGA primitive in the `elsif."""
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n"
                       "`ifdef SIMULATION\n"
                       "  always @(posedge clk) q <= d;\n"
                       "`elsif FPGA_TARGET\n"
                       "  altsyncram #(.operation_mode(\"ROM\")) u0 (.a(a));\n"
                       "`endif\n"
                       "endmodule\n") is False


def test_primitive_in_nested_conditional_is_not_a_wrapper(tmp_path):
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n"
                       "`ifdef A\n`ifdef B\n"
                       "  altsyncram u0 (.a(a));\n"
                       "`endif\n`endif\n"
                       "endmodule\n") is False


def test_primitive_in_else_arm_is_not_a_wrapper(tmp_path):
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n"
                       "`ifdef ASIC\n  reg r;\n`else\n"
                       "  altsyncram u0 (.a(a));\n"
                       "`endif\n"
                       "endmodule\n") is False


# ───────────────────── masker edge cases, fail-safe ─────────────────────

def test_unterminated_ifdef_masks_to_end_of_file(tmp_path):
    """Conservative direction: an unbalanced `ifdef must not leave the tail
    looking like live code, because excluding a needed module is the costly
    error."""
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n`ifdef FPGA\n"
                       "  altsyncram u0 (.a(a));\n"
                       "endmodule\n") is False


def test_stray_endif_at_depth_zero_does_not_corrupt_masking(tmp_path):
    """A stray `endif must not push depth negative and then mask live code."""
    assert _is_wrapper(tmp_path, "board.sv",
                       "module board;\n`endif\n"
                       "  altsyncram u0 (.a(a));\n"
                       "endmodule\n") is True


def test_stray_endif_then_a_real_ifdef_arm_still_masks(tmp_path):
    """ISOLATES THE depth CLAMP. `test_stray_endif_at_depth_zero...` above
    cannot: with an unclamped depth a stray `endif` leaves depth at -1, and
    with nothing after it `depth > 0` is False either way, so that test passes
    under the mutation. Here the stray `endif` is FOLLOWED by a genuine `ifdef
    arm — unclamped, depth walks -1 -> 0 and the primitive inside the arm reads
    as live code."""
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n`endif\n"
                       "`ifdef FPGA_TARGET\n"
                       "  altsyncram u0 (.a(a));\n"
                       "`endif\n"
                       "endmodule\n") is False


def test_mask_preserves_length_so_caller_offsets_still_align(tmp_path):
    body = ("module m;\n`ifdef X\n  altsyncram u0 (.a(a));\n`endif\n"
            "endmodule\n")
    masked = D._mask_conditional_arms(body)
    assert len(masked) == len(body)
    assert masked.count("\n") == body.count("\n")
    assert "altsyncram" not in masked
    assert "module m;" in masked          # live code untouched
    assert "endmodule" in masked


def test_commented_out_primitive_is_still_not_a_wrapper(tmp_path):
    """Pre-existing behaviour (comment stripping) must survive the change."""
    assert _is_wrapper(tmp_path, "mem.sv",
                       "module mem;\n"
                       "  // altsyncram u0 (.a(a));\n"
                       "  /* altsyncram u1 (.a(a)); */\n"
                       "endmodule\n") is False


# ───────────── the selector-level consequence, end to end ─────────────

def test_a_module_the_top_instantiates_is_not_dropped(tmp_path):
    """The defect as the flow experienced it: the selector must hand the top's
    dependency to synthesis."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _w(rtl, "top.sv",
       "module top;\n  mem u_mem (.clk(clk));\nendmodule\n")
    _w(rtl, "mem.sv",
       "module mem;\n"
       "`ifdef SIMULATION\n  reg r;\n"
       "`elsif FPGA_TARGET\n  altsyncram #(.x(1)) u0 (.a(a));\n"
       "`endif\n"
       "endmodule\n")
    names = [p.name for p in D._select_asic_rtl_sources(rtl)]
    assert "mem.sv" in names, (
        "the module the top instantiates was dropped from the ASIC source "
        f"list; selector returned {names}")
    assert "top.sv" in names


def test_a_real_board_wrapper_is_still_dropped(tmp_path):
    """The other direction, so the fix is not 'never exclude anything'."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    _w(rtl, "asic_top.sv", "module asic_top;\nendmodule\n")
    _w(rtl, "board_top.sv",
       "module board_top;\n  altpll u_pll (.inclk0(clk));\nendmodule\n")
    names = [p.name for p in D._select_asic_rtl_sources(rtl)]
    assert "board_top.sv" not in names, (
        f"a live-code FPGA board wrapper survived the filter: {names}")
    assert "asic_top.sv" in names
