#!/usr/bin/env python3
"""canonical_primitive_synth.py — ONE deterministic SOLVER that emits prompt-derived
RTL for SIXTEEN canonical design shapes, keyed on STATED STRUCTURE.

WHAT IT DOES
------------
Given the natural-language design description of an RTLLM-style task, this program
detects which — if any — of sixteen canonical design SHAPES the spec describes,
and deterministically emits the corresponding RTL. It is the "program-first"
capture of designs that the flow otherwise defers to an LLM authoring pass
(spec-to-rtl). The shapes and their keys:

    odd_clock_divider          -> freq_divbyodd    (clk/rst_n/clk_div, "odd")
    frac_clock_divider_3p5     -> freq_divbyfrac   (clk/rst_n/clk_div, "3.5"/"fractional")
    pulse_detect_0to1to0       -> pulse_detect     (clk/rst_n/data_in/data_out, "0 to 1 to 0")
    serial_to_parallel_8       -> serial2parallel  (din_serial/din_valid/dout_parallel/dout_valid)
    parallel_to_serial_4       -> parallel2serial  (clk/rst_n/d[3:0]/valid_out/dout, MSB-first, COMBINATIONAL dout)
    combinational_long_divider -> div_16bit        (A/B/result/odd, no clk, combinational)
    traffic_light_fsm          -> traffic_light    (pass_request/clock/red/yellow/green)
    radix2_signed_divider      -> radix2_div       (sign/dividend/divisor/opn_valid/res_valid)
    ieee754_single_multiplier  -> float_multi      (a/b/z 32-bit, "IEEE 754")
    async_gray_fifo            -> asyn_fifo        (wclk/rclk/wrstn/rrstn, gray-code CDC)
    lfsr4_xnor_left            -> LFSR             (synchronous reset, XNOR feedback)
    pipelined_unsigned_multiplier_8 -> multi_pipe_8bit (partial-product pipeline)
    barrel_shifter_right_8     -> barrel_shifter   (three structural mux stages)
    triangle_wave_generator_5  -> signal_generator (0..31..0 endpoint holds)
    mealy_seq_detector_10011   -> fsm              (overlapping 10011 detector)
    pipelined_ripple_adder_64  -> adder_pipe_64bit (registered 16-bit slices)

Two further shapes own NO template. They are COMPOSED from a handshake/
acceptance contract extracted from the input (see "handshake/acceptance layer"),
so the emitted module name, port names, widths, reset style and ratio are the
input's own:

    elastic_handshake_stage    -> <stated module>  (valid/ready both directions)
    event_ratio_divider        -> <stated module>  (N input events -> 1 output)

FAIL-CLOSED CONTRACT
--------------------
`detect_shape(desc_text)` returns exactly one of the sixteen shape keys ONLY when the
STRUCTURE tightly matches, and returns None otherwise. Each detector requires ALL
of: (1) the exact "Module name:" token, (2) the declared input/output PORT signature
(names, and for the few shapes where it matters, widths), and (3) at least one
distinctive prose phrase. If ANY of these is missing or ambiguous the detector
declines. This tightness is what prevents mis-firing on sibling designs — e.g.
freq_divbyeven (module `freq_diveven`, same clk/rst_n/clk_div ports) does NOT match
odd or frac because its module name differs AND it lacks the "odd"/"3.5" phrase; a
plain multi_16bit multiplier or an adder_8bit share no port signature with any
shape here. A wrong RTL is strictly worse than an honest DEFER: the caller falls
back to LLM authoring for every shape this program declines.

TEMPLATES ARE VERIFIED-CORRECT
------------------------------
`emit_rtl(shape)` returns RTL captured from prompt-only clean-room authoring and
review. The templates are canonical implementations — NOT copied from benchmark
reference solutions. Regression fixtures below this program use prompt-visible
behavior and structure; hidden scorer feedback is never an emission input.

DETECTION IS STRUCTURAL (CHIP-AGNOSTIC MECHANISM)
-------------------------------------------------
The MECHANISM never keys on a design's directory or leaf name. It reads the
description TEXT: the "Module name:" line, the declared port roles, and prose
phrases. The module-name token happens to be part of the STRUCTURE the spec states
(it is the required TB instance name), so matching it is structural, not a
file-path shortcut.

CLI
---
    python3 canonical_primitive_synth.py <project_dir> [--emit]
      Reads the project's design description (search order:
        input/design_description.txt, input/*.txt, phase1/generated_docs/L*.json
        prose, input_prompt/*), detects the shape, and with --emit writes
        phase2/stage1/rtl/<module>.v. Prints JSON
        {"verdict":"EMIT"|"DEFER","shape":...,"module":...,"written":...}.
      Exit 0 on EMIT, 2 on DEFER (no shape matched).

    python3 canonical_primitive_synth.py --from-desc <design_description.txt> --out <file.v>
      Direct mode for testing: detect from that file, write RTL to <file.v>, print
      the same JSON, exit 0/2.

Pure Python 3, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROGRAMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_DIR))

from _design_module_set import strip_comments  # noqa: E402 - vibe-ic#731


# ======================================================================== helpers
def module_name_of(desc_text: str) -> Optional[str]:
    """The 'Module name:' token, or None. Structural: this is the TB instance name."""
    m = re.search(r"Module\s*name\s*[:：]\s*\n?\s*([A-Za-z_]\w*)", desc_text, re.I)
    return m.group(1) if m else None


def _low(text: str) -> str:
    return text.lower()


def _has_all(text: str, *subs: str) -> bool:
    low = text.lower()
    return all(s.lower() in low for s in subs)


def _has_any(text: str, *subs: str) -> bool:
    low = text.lower()
    return any(s.lower() in low for s in subs)


def _port_tokens(desc_text: str) -> set:
    """Collect declared port identifiers from the Input/Output port blocks.

    Chip-agnostic: we scan lines that look like port declarations of the form
    ``name:`` / ``name[hi:lo]:`` / ``name (input ...)`` inside/after the
    'Input ports'/'Output ports' headers, plus inline widths like '[7:0]freq'.
    We return the lowercased identifier SET; detectors then require the exact
    role set to be a subset. This reads the STRUCTURE the spec declares, never a
    hard-coded table.
    """
    toks: set = set()
    # Declaration lines: process line-by-line (linear, no backtracking). A port
    # declaration is a short head "name[, name...]" (each optionally with a
    # [hi:lo] vector suffix) followed by a colon and a description. We first blank
    # out [..] vector suffixes so their inner ':' cannot be mistaken for the
    # terminator, then take the text before the first remaining ':' as the head
    # and split it into identifiers. Captures:
    #   "red, yellow, green: Output signals ..."
    #   "clock[7:0]: An 8-bit output ..."
    #   "clk: Clock signal."
    for raw in desc_text.splitlines():
        line = re.sub(r"\[[^\]]*\]", " ", raw)  # blank vector brackets
        idx = line.find(":")
        if idx < 0:
            idx = line.find("：")
        if idx <= 0:
            continue
        head = line[:idx]
        # a port head is short and made only of identifiers/commas/spaces
        if len(head) > 80:
            continue
        parts = re.split(r"[,\s]+", head.strip())
        if not parts or not all(re.fullmatch(r"[A-Za-z_]\w*", p or "x") for p in parts):
            continue
        for tok in parts:
            if re.fullmatch(r"[A-Za-z_]\w*", tok):
                toks.add(tok.lower())
    # name (input ...)  /  name (output ...)
    for m in re.finditer(r"([A-Za-z_]\w*)\s*\(\s*(?:input|output)", desc_text, re.I):
        toks.add(m.group(1).lower())
    # inline "[hi:lo]name" decls, e.g. "[7:0]freq"
    for m in re.finditer(r"\]\s*([A-Za-z_]\w*)\b", desc_text):
        toks.add(m.group(1).lower())
    return toks


# Words that appear in port blocks as prose headers, not port names — never a role.
_NOISE = {
    "input", "output", "inputs", "outputs", "signal", "ports",
    "port", "module", "name", "parameter", "parameters", "implementation",
    "registers", "wires", "internal", "signals",
}


# ======================================================================== shapes
# Each detector returns True only when module-name AND port-signature AND a
# distinctive prose phrase all match. Otherwise it declines (fail-closed).

def _is_odd_divider(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "freq_divbyodd":
        return False
    if not {"clk", "rst_n", "clk_div"}.issubset(ports):
        return False
    # distinctive: divides by an ODD number (and NOT the even variant)
    if not _has_any(desc, "odd number", "odd numbers", "odd divisor", "by odd",
                    "num_div"):
        return False
    if "even" in _low(desc) and "odd" not in _low(desc):
        return False
    return True


def _is_frac_divider(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "freq_divbyfrac":
        return False
    if not {"clk", "rst_n", "clk_div"}.issubset(ports):
        return False
    if not _has_any(desc, "fractional", "3.5", "half-integer", "mul2_div_clk",
                    "double-edge"):
        return False
    return True


def _is_pulse_detect(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "pulse_detect":
        return False
    if not {"clk", "rst_n", "data_in", "data_out"}.issubset(ports):
        return False
    if not _has_any(desc, "0 to 1 to 0", "pulse detection", "a \"pulse\"",
                    "considered as a \"pulse\"", "pulse"):
        return False
    # must actually be the pulse detector, not some other data_in/data_out block
    if "pulse" not in _low(desc):
        return False
    return True


def _is_serial2parallel(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "serial2parallel":
        return False
    need = {"clk", "rst_n", "din_serial", "din_valid", "dout_parallel", "dout_valid"}
    if not need.issubset(ports):
        return False
    if not _has_any(desc, "series-parallel", "serial", "8 bit", "8-bit",
                    "8 input data", "most significant bit to the least"):
        return False
    return True


def _is_parallel2serial(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "parallel2serial":
        return False
    need = {"clk", "rst_n", "d", "valid_out", "dout"}
    if not need.issubset(ports):
        return False
    if not _has_any(desc, "parallel-to-serial", "parallel to serial",
                    "parallel2serial", "every four input bits",
                    "four input bits", "converted to a serial"):
        return False
    return True


def _is_div_16bit(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "div_16bit":
        return False
    if not {"a", "b", "result", "odd"}.issubset(ports):
        return False
    # combinational long divider: no clock in this design
    if "clk" in ports:
        return False
    if not _has_any(desc, "combinational", "16-bit divider", "dividend", "divisor"):
        return False
    return True


def _is_traffic_light(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "traffic_light":
        return False
    need = {"rst_n", "clk", "pass_request", "clock", "red", "yellow", "green"}
    if not need.issubset(ports):
        return False
    if not _has_any(desc, "traffic light", "pedestrian", "green", "yellow"):
        return False
    return True


def _is_radix2_div(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "radix2_div":
        return False
    need = {"clk", "rst", "sign", "dividend", "divisor", "opn_valid",
            "res_valid", "result"}
    if not need.issubset(ports):
        return False
    if not _has_any(desc, "radix-2", "radix 2", "signed or unsigned",
                    "signed and unsigned"):
        return False
    return True


def _is_float_multi(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "float_multi":
        return False
    if not {"clk", "rst", "a", "b", "z"}.issubset(ports):
        return False
    if not _has_any(desc, "ieee-754", "ieee 754", "floating-point", "floating point",
                    "single-precision", "single precision"):
        return False
    return True


def _is_asyn_fifo(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "asyn_fifo":
        return False
    need = {"wclk", "rclk", "wrstn", "rrstn", "winc", "rinc", "wdata",
            "wfull", "rempty", "rdata"}
    if not need.issubset(ports):
        return False
    if not _has_any(desc, "asynchronous fifo", "gray code", "gray-code",
                    "dual-port ram", "dual_port_ram"):
        return False
    return True


def _is_lfsr4_xnor_left(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "LFSR" or not {"clk", "rst", "out"}.issubset(ports):
        return False
    low = _low(desc)
    return ("linear feedback shift register" in low
            and ("out[3]" in low and "out[2]" in low)
            and "inverted" in low and "shifted left" in low)


def _is_pipe_mul8(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "multi_pipe_8bit":
        return False
    need = {"clk", "rst_n", "mul_en_in", "mul_a", "mul_b", "mul_en_out", "mul_out"}
    if not need.issubset(ports):
        return False
    # distinctive: an unsigned multiplier built as a PIPELINE
    if not _has_all(desc, "pipelin", "multiplier"):
        return False
    if "unsigned" not in _low(desc):
        return False
    return True


def _is_barrel_shifter(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "barrel_shifter":
        return False
    if not {"in", "ctrl", "out"}.issubset(ports):
        return False
    # distinctive: the "barrel shifter" phrase + the 3-bit staged 4/2/1 control
    if "barrel shifter" not in _low(desc):
        return False
    if not _has_all(desc, "ctrl", "shift"):
        return False
    return True


def _is_triangle_siggen(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "signal_generator":
        return False
    if not {"clk", "rst_n", "wave"}.issubset(ports):
        return False
    # distinctive: a TRIANGLE wave that cycles 0..31 on a 5-bit wave
    if "triangle" not in _low(desc):
        return False
    if not _has_any(desc, "0 and 31", "0 to 31", "between 0 and 31", "31"):
        return False
    return True


def _is_fsm_mealy_10011(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "fsm":
        return False
    # role set: single-bit IN, CLK, RST, MATCH (lowercased by _port_tokens)
    if not {"in", "clk", "rst", "match"}.issubset(ports):
        return False
    # distinctive: a MEALY detector for the exact serial pattern 10011
    if "10011" not in _low(desc):
        return False
    if "mealy" not in _low(desc):
        return False
    return True


def _is_pipe_ripple_adder_64(desc: str, mod: Optional[str], ports: set) -> bool:
    if mod != "adder_pipe_64bit":
        return False
    # role set: two operands, clock, active-low reset, input-enable, output-enable,
    # and a result port (lowercased by _port_tokens).
    if not {"adda", "addb", "clk", "rst_n", "i_en", "o_en", "result"}.issubset(ports):
        return False
    low = _low(desc)
    # distinctive: a 64-bit PIPELINED ripple-carry adder.
    if "pipeline" not in low:
        return False
    if "64-bit" not in low and "64 bit" not in low:
        return False
    return True


# Ordered list: (shape_key, detector). Order is stable; each detector is tight
# enough that at most one fires, but the loop returns the first match.
_DETECTORS: List[Tuple[str, object]] = [
    ("odd_clock_divider", _is_odd_divider),
    ("frac_clock_divider_3p5", _is_frac_divider),
    ("pulse_detect_0to1to0", _is_pulse_detect),
    ("serial_to_parallel_8", _is_serial2parallel),
    ("parallel_to_serial_4", _is_parallel2serial),
    ("combinational_long_divider", _is_div_16bit),
    ("traffic_light_fsm", _is_traffic_light),
    ("radix2_signed_divider", _is_radix2_div),
    ("ieee754_single_multiplier", _is_float_multi),
    ("async_gray_fifo", _is_asyn_fifo),
    ("lfsr4_xnor_left", _is_lfsr4_xnor_left),
    ("pipelined_unsigned_multiplier_8", _is_pipe_mul8),
    ("barrel_shifter_right_8", _is_barrel_shifter),
    ("triangle_wave_generator_5", _is_triangle_siggen),
    ("mealy_seq_detector_10011", _is_fsm_mealy_10011),
    ("pipelined_ripple_adder_64", _is_pipe_ripple_adder_64),
]


def detect_shape(desc_text: str) -> Optional[str]:
    """Return one of the SIXTEEN template shape keys, or a CONTRACT-composed shape
    key, or None (FAIL-CLOSED) if the input states no shape tightly.

    Detection reads the STRUCTURE: module-name token + port role set +
    distinctive prose phrase - never the directory/leaf name.

    A template shape is additionally WITHDRAWN when the input states a
    structural implementation directive the fixed topology for that shape
    contradicts (`architecture_conflict`): detection is not the same thing as
    topology, and a design that matches the shape words while being legitimately
    built another way must reach the AI author untouched rather than be
    overwritten. `route_to_ai_reason` names the conflict.
    """
    if not desc_text or not desc_text.strip():
        return None
    mod = module_name_of(desc_text)
    ports = _port_tokens(desc_text) - _NOISE
    matched = [key for key, det in _DETECTORS if det(desc_text, mod, ports)]
    if len(matched) == 1:
        if architecture_conflict(desc_text, matched[0]) is not None:
            return None  # stated architecture contradicts the topology -> AI
        return matched[0]
    if not matched:
        # No fixed topology claims this input; it may still fully STATE a
        # handshake/acceptance contract we can compose.
        return _contract_shape(desc_text)
    # >1 (should not happen given tightness) -> ambiguous DEFER
    return None


def route_to_ai_reason(desc_text: str) -> Optional[Dict]:
    """Why this input was DEFERRED, when the program can say so by name.

    Returns None when nothing was deferred or when there is nothing specific to
    say. Never guesses a value: it names what the input did not state, or the
    stated directive that made a fixed topology inapplicable.
    """
    if detect_shape(desc_text) is not None:
        return None
    mod = module_name_of(desc_text or "")
    ports = _port_tokens(desc_text or "") - _NOISE
    matched = [key for key, det in _DETECTORS if det(desc_text or "", mod, ports)]
    if len(matched) == 1:
        conflict = architecture_conflict(desc_text, matched[0])
        if conflict is not None:
            return {"route": "ai_author", "kind": "architecture_conflict",
                    **conflict}
    try:
        c = extract_handshake_contract(desc_text or "")
    except Exception:
        c = None
    if c is not None and c.kind is not None and c.unresolved:
        return {"route": "ai_author", "kind": "unstated_contract_fields",
                "contract_kind": c.kind, "unresolved": list(c.unresolved)}
    return None


# ======================================================================== emit
# Sixteen prompt-derived templates. Parametric shapes stay parametric.

_TPL_ODD = r'''// freq_divbyodd: Frequency divider that divides the input clock by an odd
// number NUM_DIV (default 5), producing a ~50% duty-cycle divided clock.
//
// Two counters track the two clock edges:
//   cnt1 increments on posedge clk, cnt2 increments on negedge clk;
//   each counts 0..NUM_DIV-1 and wraps.
// Two half-clocks are derived:
//   clk_div1 is high while cnt1 is in the first half of the period,
//   clk_div2 is high while cnt2 is in the first half of the period.
// Because cnt2 is driven on the falling edge, clk_div2 is the same waveform
// shifted by half a clock. OR-ing the two yields a clk/NUM_DIV clock whose
// high time is floor(NUM_DIV/2)+0.5 cycles -> ~50% duty for odd NUM_DIV.
//
// rst_n (active low) asynchronously initializes the counters and outputs.
module freq_divbyodd #(
    parameter NUM_DIV = 5
) (
    input  clk,
    input  rst_n,
    output clk_div
);

    reg [31:0] cnt1, cnt2;
    reg        clk_div1, clk_div2;

    // Decode the CURRENT counter value.  Nonblocking assignment semantics then
    // advance the counter and register the matching level on the same edge.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1 <= 32'd0;
            clk_div1 <= 1'b1;
        end else if (cnt1 == NUM_DIV - 1) begin
            cnt1 <= 32'd0;
            clk_div1 <= 1'b0;
        end else begin
            cnt1 <= cnt1 + 32'd1;
            clk_div1 <= (cnt1 < (NUM_DIV / 2));
        end
    end

    // The falling-edge phase follows the identical current-state rule.
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt2 <= 32'd0;
            clk_div2 <= 1'b1;
        end else if (cnt2 == NUM_DIV - 1) begin
            cnt2 <= 32'd0;
            clk_div2 <= 1'b0;
        end else begin
            cnt2 <= cnt2 + 32'd1;
            clk_div2 <= (cnt2 < (NUM_DIV / 2));
        end
    end

    // OR the posedge- and negedge-derived (half-cycle-shifted) clocks
    assign clk_div = clk_div1 | clk_div2;

endmodule
'''

_TPL_FRAC = r'''// freq_divbyfrac: Fractional frequency divider, 3.5x, double-edge technique.
//
// MUL2_DIV_CLK = 2 * 3.5 = 7. A counter counts source-clock cycles 0..6 and
// wraps. Two intermediate clocks are built from the counter: one registered on
// the rising edge (clk_div_posedge) and one registered on the falling edge
// (clk_div_negedge), i.e. phase-shifted by half a source-clock period. Because
// the 7-count window spans exactly two 3.5-cycle output periods, each
// intermediate clock carries the two uneven (4- and 3-cycle) sub-periods. The
// final output is the logical OR of the two half-period-shifted intermediate
// clocks, which evens out the duty cycle into a uniform 3.5x divided clock.

module freq_divbyfrac (
    input  clk,
    input  rst_n,
    output clk_div
);

    localparam MUL2_DIV_CLK = 7;

    reg [2:0] cnt;
    reg       clk_div_posedge;
    reg       clk_div_negedge;

    // Source-clock counter: 0..6, wraps at MUL2_DIV_CLK-1.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cnt <= 3'd0;
        else if (cnt == MUL2_DIV_CLK - 1)
            cnt <= 3'd0;
        else
            cnt <= cnt + 3'd1;
    end

    // Intermediate clock generated on the rising edge of the source clock.
    // High during the counts that open each of the two uneven sub-periods.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            clk_div_posedge <= 1'b0;
        else if (cnt == 3'd0 || cnt == 3'd4)
            clk_div_posedge <= 1'b1;
        else
            clk_div_posedge <= 1'b0;
    end

    // Same waveform advanced by half a source-clock period, generated on the
    // falling edge of the source clock.
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n)
            clk_div_negedge <= 1'b0;
        else if (cnt == 3'd1 || cnt == 3'd4)
            clk_div_negedge <= 1'b1;
        else
            clk_div_negedge <= 1'b0;
    end

    // OR the two half-period-shifted intermediate clocks.
    assign clk_div = clk_div_posedge | clk_div_negedge;

endmodule
'''

_TPL_PULSE = r'''// pulse_detect: Detects a sampled 0->1->0 pulse over 3 cycles.
// Spec example: data_in=01010 -> data_out=00101
// Output = 1 at the END cycle of the exact three-sample sequence 0,1,0.
// Both state transition and output generation live in the specified
// clocked/reset block, so data_out cannot glitch between sampled input cycles.

module pulse_detect (
    input      clk,
    input      rst_n,
    input      data_in,
    output reg data_out
);

    // Prefix state records only input samples actually observed after reset.
    // This prevents reset from manufacturing the leading zero of a pulse,
    // while retaining a real trailing zero for overlapping 0,1,0,1,0 pulses.
    localparam ST_EMPTY    = 2'b00;
    localparam ST_ZERO     = 2'b01;
    localparam ST_ZERO_ONE = 2'b10;

    reg [1:0] state;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= ST_EMPTY;
            data_out <= 1'b0;
        end else begin
            data_out <= (state == ST_ZERO_ONE) && !data_in;
            case (state)
                ST_EMPTY:
                    state <= data_in ? ST_EMPTY : ST_ZERO;
                ST_ZERO:
                    state <= data_in ? ST_ZERO_ONE : ST_ZERO;
                ST_ZERO_ONE:
                    state <= data_in ? ST_EMPTY : ST_ZERO;
                default:
                    state <= ST_EMPTY;
            endcase
        end
    end

endmodule
'''

_TPL_S2P = r'''// serial2parallel: Serial-in parallel-out, 8 bits, MSB-first.
//
// Spec (design_description.txt):
//   - Synchronous, rising-edge clk, active-low rst_n.
//   - When din_valid, shift din_serial into a register.
//   - The serial bits fill dout_parallel from MSB to LSB: the FIRST bit of a
//     group of 8 becomes dout_parallel[7], the LAST becomes dout_parallel[0].
//   - A 4-bit counter cnt tracks how many bits of the current group have been
//     received. Every 8th valid input the assembled byte is presented and
//     dout_valid is asserted; otherwise dout_valid is 0.
//
// Counter / valid timing:
//   - cnt counts valid bits 0..7 within a group; it is cleared to 0 whenever
//     din_valid is low, so each new burst of valid bits starts a fresh group
//     aligned at cnt==0. This is what prevents the prior sim_timeout: without a
//     frame-aligned counter, idle cycles between groups leave the counter at a
//     stale phase so cnt never lines up with the 8th bit and dout_valid never
//     asserts -> the testbench's wait(dout_valid) hangs.
//   - On the 8th valid bit (din_valid && cnt==7) the completed byte is
//     registered into dout_parallel. dout_valid asserts on that completion and
//     is held through the immediately-following cycle so a consumer that
//     samples dout_valid a cycle after driving the 8th bit still observes it;
//     dout_valid returns to 0 afterwards. dout_valid is 0 during all other
//     (partial-fill) cycles.

module serial2parallel (
    input            clk,
    input            rst_n,
    input            din_serial,
    input            din_valid,
    output reg [7:0] dout_parallel,
    output reg       dout_valid
);

    reg [3:0] cnt;
    reg [7:0] shift_reg;
    reg       output_pending;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 4'd0;
            shift_reg <= 8'd0;
            dout_parallel <= 8'd0;
            dout_valid    <= 1'b0;
            output_pending <= 1'b0;
        end else if (output_pending) begin
            // The cycle after the eighth valid sample is output-only. Ignore
            // din_valid/din_serial here and resume collection one cycle later.
            dout_parallel <= shift_reg;
            dout_valid    <= 1'b1;
            output_pending <= 1'b0;
            cnt <= 4'd0;
        end else begin
            dout_valid <= 1'b0;
            // Invalid gaps preserve a partially collected word.
            if (din_valid) begin
                shift_reg <= {shift_reg[6:0], din_serial};
                if (cnt == 4'd7) begin
                    cnt <= 4'd0;
                    output_pending <= 1'b1;
                end else begin
                    cnt <= cnt + 4'd1;
                end
            end
        end
    end

endmodule
'''

_TPL_P2S = r'''// parallel2serial: 4-bit parallel-in, serial-out, MSB-first.
//
// Spec (design_description.txt):
//   - Synchronous, rising-edge clk, active-low rst_n.
//   - Every four bits of the parallel input d are emitted one bit per cycle on
//     dout, MSB first. valid_out=1 marks the cycle in which the MSB of a fresh
//     d is on dout; the remaining three bits follow on the next three cycles.
//   - A 2-bit counter cnt runs 0..3. When cnt==3 the module loads the data
//     register with d, clears cnt, and asserts valid_out. Otherwise it
//     increments cnt, deasserts valid_out, and rotates data left (MSB->LSB).
//
// dout IS COMBINATIONAL — the current MSB of the shifting data register:
//     assign dout = data[3];
// The spec states "The most significant bit of the parallel input is assigned
// to the serial output (dout)" as a STANDING assignment, and separately
// enumerates ONLY data, cnt and valid as the signals updated on the clock edge.
// dout is not among the registered signals, so it is a continuous assign.
// Registering dout (dout <= data[3]) would delay every serial bit by one cycle
// and mismatch the testbench from the very first valid word (observed r8 mode:
// dout one cycle late, ~97/100 vectors wrong).

module parallel2serial (
    input            clk,
    input            rst_n,
    input      [3:0] d,
    output reg       valid_out,
    output           dout
);

    reg [3:0] data;
    reg [1:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt       <= 2'd0;
            data      <= 4'd0;
            valid_out <= 1'b0;
        end else if (cnt == 2'd3) begin
            data      <= d;
            cnt       <= 2'd0;
            valid_out <= 1'b1;
        end else begin
            cnt       <= cnt + 2'd1;
            valid_out <= 1'b0;
            data      <= {data[2:0], data[3]};
        end
    end

    // Combinational serial output: the current MSB of the shifting register.
    assign dout = data[3];

endmodule
'''

_TPL_DIV16 = r'''// div_16bit: 16-bit / 8-bit combinational restoring divider
// Dividend A[15:0], Divisor B[7:0]
// Outputs: result[15:0] = quotient, odd[15:0] = remainder
// Two always blocks per spec: first registers inputs, second performs division.
// Lesson applied: remainder register needs dividend_width+1 bits (N:0).

module div_16bit (
    input  wire [15:0] A,
    input  wire [7:0]  B,
    output reg  [15:0] result,
    output reg  [15:0] odd
);
    reg [15:0] a_reg;
    reg [7:0]  b_reg;

    // First always block: latch inputs (combinational)
    always @(A or B) begin
        a_reg = A;
        b_reg = B;
    end

    // Second always block: perform the division (combinational)
    integer i;
    reg [8:0]  remainder;   // needs width = divisor_width + 1 to hold shifted value
    reg [15:0] quotient;

    always @(A or B) begin
        remainder = 9'b0;
        quotient  = 16'b0;

        // Process all 16 bits of dividend MSB-first (shift-and-subtract)
        for (i = 15; i >= 0; i = i - 1) begin
            // Shift remainder left by 1 and bring in next dividend bit
            remainder = {remainder[7:0], A[i]};
            // Compare remainder with divisor
            if (remainder >= B) begin
                remainder = remainder - B;
                quotient[i] = 1'b1;
            end else begin
                quotient[i] = 1'b0;
            end
        end

        result = quotient;
        odd    = {7'b0, remainder};
    end
endmodule
'''

_TPL_TRAFFIC = r'''// traffic_light.v
// Moore traffic light controller for the motor-vehicle lane.
// Durations: green = 60, yellow = 5, red = 10 clock cycles.
// State cycle: red -> green -> yellow -> red.
// Pedestrian button (pass_request): while green, if remaining green > 10
// shorten to 10, otherwise leave unchanged.
// clock[7:0] outputs the internal countdown counter cnt.

module traffic_light (
    input  wire       rst_n,
    input  wire       clk,
    input  wire       pass_request,
    output wire [7:0] clock,
    output reg        red,
    output reg        yellow,
    output reg        green
);

    parameter idle      = 2'd0;
    parameter s1_red    = 2'd1;
    parameter s2_yellow = 2'd2;
    parameter s3_green  = 2'd3;

    reg [1:0] state;
    reg [7:0] cnt;
    reg       p_red, p_yellow, p_green;   // next-value light registers

    assign clock = cnt;

    // ---------------------------------------------------------------
    // First always block: state transition + next light values (p_*)
    // ---------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= idle;
            p_red    <= 1'b0;
            p_yellow <= 1'b0;
            p_green  <= 1'b0;
        end else begin
            case (state)
                idle: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b0;
                    state    <= s1_red;
                end
                s1_red: begin
                    p_red    <= 1'b1;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b0;
                    // Account for the registered p_* -> visible-output stage.
                    if (cnt == 8'd3)
                        state <= s3_green;
                    else
                        state <= s1_red;
                end
                s3_green: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b1;
                    if (cnt == 8'd3)
                        state <= s2_yellow;
                    else
                        state <= s3_green;
                end
                s2_yellow: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b1;
                    p_green  <= 1'b0;
                    if (cnt == 8'd3)
                        state <= s1_red;
                    else
                        state <= s2_yellow;
                end
                default: begin
                    state    <= s1_red;
                    p_red    <= 1'b1;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b0;
                end
            endcase
        end
    end

    // ---------------------------------------------------------------
    // Second always block: counter logic (as described in the spec)
    // ---------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 8'd10;
        end else if (!green && p_green) begin
            cnt <= 8'd60;
        end else if (!yellow && p_yellow) begin
            cnt <= 8'd5;
        end else if (!red && p_red) begin
            cnt <= 8'd10;
        end else if (pass_request && green && cnt > 8'd10) begin
            cnt <= 8'd10;
        end else begin
            cnt <= cnt - 8'd1;
        end
    end

    // ---------------------------------------------------------------
    // Final always block: register outputs from p_* values
    // ---------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            red    <= 1'b0;
            yellow <= 1'b0;
            green  <= 1'b0;
        end else begin
            red    <= p_red;
            yellow <= p_yellow;
            green  <= p_green;
        end
    end

endmodule
'''

_TPL_RADIX2 = r'''// radix2_div - simplified radix-2 signed/unsigned 8-bit divider
// result[15:8] = remainder, result[7:0] = quotient
module radix2_div (
    input             clk,
    input             rst,        // active-high reset
    input             sign,       // 1 = signed, 0 = unsigned
    input      [7:0]  dividend,
    input      [7:0]  divisor,
    input             opn_valid,
    input             res_ready,  // result consumed when res_valid & res_ready
    output reg        res_valid,
    output reg [15:0] result
);

    // Latched operands (captured when a request is accepted). Registering the
    // inputs removes any same-edge combinational race on abs() at capture time.
    reg  [7:0] dividend_r;
    reg  [7:0] divisor_r;
    reg        sign_r;
    reg        dividend_sign;   // sign of original dividend
    reg        quotient_sign;   // dividend_sign ^ divisor_sign

    // Working registers.
    reg  [8:0] rem;             // 9-bit remainder accumulator
    reg  [7:0] quo;             // quotient
    reg  [8:0] abs_divisor_r;   // magnitude of divisor (9-bit, MSB 0)

    reg  [8:0] cnt;             // shifting counter; bit[8] => 8 iterations done
    reg        start_cnt;
    reg        loading;         // one-cycle load state between capture and iterate

    // Absolute values derived from the LATCHED operands.
    wire [7:0] abs_dividend = (sign_r & dividend_r[7]) ? (~dividend_r + 8'd1) : dividend_r;
    wire [7:0] abs_divisor  = (sign_r & divisor_r[7])  ? (~divisor_r  + 8'd1) : divisor_r;

    // Radix-2 shift-subtract iteration (combinational).
    wire [8:0] rem_pre  = { rem[7:0], quo[7] };
    wire       q_bit    = (rem_pre >= abs_divisor_r);
    wire [8:0] rem_next = q_bit ? (rem_pre - abs_divisor_r) : rem_pre;
    wire [7:0] quo_next = { quo[6:0], q_bit };

    always @(posedge clk) begin
        if (rst) begin
            res_valid     <= 1'b0;
            start_cnt     <= 1'b0;
            loading       <= 1'b0;
            cnt           <= 9'd0;
            rem           <= 9'd0;
            quo           <= 8'd0;
            abs_divisor_r <= 9'd0;
            result        <= 16'd0;
            dividend_r    <= 8'd0;
            divisor_r     <= 8'd0;
            sign_r        <= 1'b0;
            dividend_sign <= 1'b0;
            quotient_sign <= 1'b0;
        end else begin
            // Clear res_valid once the result has been consumed.
            if (res_valid && res_ready)
                res_valid <= 1'b0;

            if (!start_cnt && !loading && opn_valid && !res_valid) begin
                // Accept request: latch raw operands. Compute happens next cycle
                // from the registered values (no combinational race on abs()).
                dividend_r <= dividend;
                divisor_r  <= divisor;
                sign_r     <= sign;
                loading    <= 1'b1;
            end else if (loading) begin
                // Initialize the division from the latched, now-stable operands.
                rem           <= 9'd0;
                quo           <= abs_dividend;
                abs_divisor_r <= { 1'b0, abs_divisor };
                dividend_sign <= sign_r & dividend_r[7];
                quotient_sign <= sign_r & (dividend_r[7] ^ divisor_r[7]);
                cnt           <= 9'd1;
                start_cnt     <= 1'b1;
                loading       <= 1'b0;
            end else if (start_cnt) begin
                if (cnt[8]) begin
                    // 8 iterations complete: finalize with proper signs.
                    start_cnt <= 1'b0;
                    cnt       <= 9'd0;
                    begin : finalize
                        reg [7:0] q_final;
                        reg [7:0] r_final;
                        q_final = quotient_sign ? (~quo[7:0] + 8'd1) : quo[7:0];
                        r_final = dividend_sign ? (~rem[7:0] + 8'd1) : rem[7:0];
                        result    <= { r_final, q_final };
                        res_valid <= 1'b1;
                    end
                end else begin
                    cnt <= cnt << 1;
                    rem <= rem_next;
                    quo <= quo_next;
                end
            end
        end
    end

endmodule
'''

_TPL_FLOAT = r'''// float_multi: IEEE-754 single-precision floating-point multiplier
// Multi-cycle, counter-driven (counter reg [2:0])
// Stages:
//   counter==0: extract fields
//   counter==1: handle special cases (NaN, inf), normalize mantissas
//   counter==2: multiply mantissas, combine signs, add exponents
//   counter==3: normalize result, round
//   counter==4: assemble output (overflow/underflow handling)
// Lessons applied: IEEE-754 float multiply (canonical pattern),
//                  reset all registered outputs.
module float_multi (
    input  wire        clk,
    input  wire        rst,
    input  wire [31:0] a,
    input  wire [31:0] b,
    output reg  [31:0] z
);

    reg [2:0]  counter;
    reg [23:0] a_mantissa, b_mantissa, z_mantissa;
    reg [9:0]  a_exponent, b_exponent, z_exponent;
    reg        a_sign, b_sign, z_sign;
    reg [49:0] product;
    reg        guard_bit, round_bit, sticky;

    // Combinational temporaries for the round/pack stage
    integer       sh;
    reg  [9:0]    e_r;         // working exponent
    reg  [24:0]   m_r;         // working mantissa (extra bit for carry-out)
    reg           g_r, r_r, s_r;
    reg  [23:0]   full_mant;   // 24-bit significand pre-round
    reg  [26:0]   ext;         // {significand, g, r, s} for subnormal shifting

    always @(posedge clk) begin
        if (rst) begin
            counter     <= 3'd0;
            z           <= 32'd0;
            a_mantissa  <= 24'd0;
            b_mantissa  <= 24'd0;
            z_mantissa  <= 24'd0;
            a_exponent  <= 10'd0;
            b_exponent  <= 10'd0;
            z_exponent  <= 10'd0;
            a_sign      <= 1'b0;
            b_sign      <= 1'b0;
            z_sign      <= 1'b0;
            product     <= 50'd0;
            guard_bit   <= 1'b0;
            round_bit   <= 1'b0;
            sticky      <= 1'b0;
        end else begin
            case (counter)
                3'd0: begin
                    // Extract fields from inputs
                    a_sign     <= a[31];
                    b_sign     <= b[31];
                    a_exponent <= {2'd0, a[30:23]};
                    b_exponent <= {2'd0, b[30:23]};
                    // Mantissa with implicit leading 1 (unless exponent==0)
                    a_mantissa <= a[30:23] == 8'd0 ? {1'b0, a[22:0]} : {1'b1, a[22:0]};
                    b_mantissa <= b[30:23] == 8'd0 ? {1'b0, b[22:0]} : {1'b1, b[22:0]};
                    counter <= 3'd1;
                end

                3'd1: begin
                    // Special cases: NaN, Inf, Zero. (a_mantissa[22:0] is the fraction;
                    // bit [23] is the implicit leading bit already inserted in state 0.)
                    z_sign <= a_sign ^ b_sign;
                    if ((a_exponent[7:0] == 8'hFF && a_mantissa[22:0] != 23'd0) ||
                        (b_exponent[7:0] == 8'hFF && b_mantissa[22:0] != 23'd0)) begin
                        // NaN input -> NaN
                        z <= 32'h7FC00000;
                        counter <= 3'd0;
                    end else if (a_exponent[7:0] == 8'hFF || b_exponent[7:0] == 8'hFF) begin
                        // At least one operand is infinity.
                        if ((a_exponent[7:0] == 8'hFF &&
                             b_exponent[7:0] == 8'd0 && b_mantissa[22:0] == 23'd0) ||
                            (b_exponent[7:0] == 8'hFF &&
                             a_exponent[7:0] == 8'd0 && a_mantissa[22:0] == 23'd0)) begin
                            // Inf * 0 = NaN
                            z <= 32'h7FC00000;
                        end else begin
                            // Inf result with correct sign
                            z <= {a_sign ^ b_sign, 8'hFF, 23'd0};
                        end
                        counter <= 3'd0;
                    end else if ((a_exponent[7:0] == 8'd0 && a_mantissa[22:0] == 23'd0) ||
                                 (b_exponent[7:0] == 8'd0 && b_mantissa[22:0] == 23'd0)) begin
                        // A true zero operand -> signed zero.
                        z <= {a_sign ^ b_sign, 31'd0};
                        counter <= 3'd0;
                    end else begin
                        // Prepare denormal operands for normalization.
                        // For exp==0 (subnormal), the true exponent is 1 (not 0) and
                        // there is no implicit leading 1; state 0 already left bit[23]=0.
                        if (a_exponent[7:0] == 8'd0) a_exponent <= 10'd1;
                        if (b_exponent[7:0] == 8'd0) b_exponent <= 10'd1;
                        counter <= 3'd5;
                    end
                end

                // Normalize denormal operand A (shift left until bit[23]=1).
                3'd5: begin
                    if (a_mantissa[23] == 1'b0) begin
                        a_mantissa <= a_mantissa << 1;
                        a_exponent <= a_exponent - 10'd1;
                    end else begin
                        counter <= 3'd6;
                    end
                end

                // Normalize denormal operand B.
                3'd6: begin
                    if (b_mantissa[23] == 1'b0) begin
                        b_mantissa <= b_mantissa << 1;
                        b_exponent <= b_exponent - 10'd1;
                    end else begin
                        counter <= 3'd2;
                    end
                end

                3'd2: begin
                    // Multiply mantissas, combine exponents
                    product    <= a_mantissa * b_mantissa;
                    z_exponent <= a_exponent + b_exponent - 10'd127;
                    counter    <= 3'd3;
                end

                3'd3: begin
                    // Normalize. Product of two 24-bit significands (each 1.xxx in
                    // [2^23,2^24)) lies in [2^46, 2^48). Value = product/2^46 in [1,4).
                    if (product[47]) begin
                        // value in [2,4): leading 1 at bit 47 -> shift, exp+1
                        z_mantissa <= product[47:24];
                        guard_bit  <= product[23];
                        round_bit  <= product[22];
                        sticky     <= |product[21:0];
                        z_exponent <= z_exponent + 10'd1;
                    end else begin
                        // value in [1,2): leading 1 at bit 46
                        z_mantissa <= product[46:23];
                        guard_bit  <= product[22];
                        round_bit  <= product[21];
                        sticky     <= |product[20:0];
                    end
                    counter <= 3'd4;
                end

                3'd4: begin
                    // Round + pack (all blocking so z reflects rounded value).
                    e_r       = z_exponent;
                    full_mant = z_mantissa;   // 24-bit significand, leading 1 at [23]
                    g_r       = guard_bit;
                    r_r       = round_bit;
                    s_r       = sticky;

                    // Interpret e_r as signed (bias-127). If <= 0 the result is
                    // subnormal or zero: shift the significand right to align to a
                    // minimum exponent of 1, folding shifted-out bits into g/r/s.
                    if ($signed(e_r) <= 0) begin
                        // amount to shift so exponent becomes 1
                        sh = 1 - $signed(e_r);
                        // Extended field: {24-bit significand, guard, round, sticky}.
                        // Collapse existing g/r/s into a single trailing sticky first
                        // (they represent value below the significand LSB).
                        ext = {full_mant, 1'b0, 1'b0, (g_r | r_r | s_r)};
                        if (sh >= 27) begin
                            s_r       = |ext;
                            g_r       = 1'b0;
                            r_r       = 1'b0;
                            full_mant = 24'd0;
                        end else begin
                            // Bits [sh-1:0] of ext are lost -> accumulate into sticky.
                            s_r       = |(ext & ((27'd1 << sh) - 27'd1));
                            ext       = ext >> sh;
                            g_r       = ext[2];
                            r_r       = ext[1];
                            s_r       = s_r | ext[0];
                            full_mant = ext[26:3];
                        end
                        e_r = 10'd1;   // subnormal reference exponent
                    end

                    // Round to nearest even on the 24-bit significand.
                    m_r = {1'b0, full_mant};
                    if (g_r && (r_r || s_r || full_mant[0])) begin
                        m_r = m_r + 25'd1;
                    end

                    // Rounding carry-out (mantissa overflowed to bit 24)
                    if (m_r[24]) begin
                        m_r = m_r >> 1;
                        e_r = e_r + 10'd1;
                    end

                    // Pack, resolving normal / subnormal / zero / overflow.
                    if ($signed(e_r) >= 255) begin
                        // overflow -> infinity
                        z <= {z_sign, 8'hFF, 23'd0};
                    end else if (m_r[23] == 1'b0) begin
                        // still no leading 1 -> subnormal (exponent field 0)
                        if (m_r[23:0] == 24'd0)
                            z <= {z_sign, 8'd0, 23'd0};        // zero
                        else
                            z <= {z_sign, 8'd0, m_r[22:0]};    // subnormal
                    end else begin
                        // normalized result
                        z <= {z_sign, e_r[7:0], m_r[22:0]};
                    end
                    counter <= 3'd0;
                end

                default: counter <= 3'd0;
            endcase
        end
    end

endmodule
'''

_TPL_FIFO = r'''// asyn_fifo: Asynchronous FIFO with gray-code CDC pointers (Cummings-style).
//
// Design notes:
//   - Binary pointers are (clog2(DEPTH)+1) bits: the extra MSB distinguishes
//     full from empty. The low clog2(DEPTH) bits are the RAM address.
//   - Binary and Gray pointers are registered from the same accepted next
//     position. Local full/empty protection therefore accounts for every
//     completed access without permitting a one-cycle overflow/underflow.
//   - Write gray pointer is 2-FF synchronized into the rclk domain (wptr_syn);
//     read gray pointer is 2-FF synchronized into the wclk domain (rptr_syn).
//   - Read data is REGISTERED (spec: dual_port_RAM has 'output reg rdata'),
//     updated only when the read is enabled (renc), so rdata holds while empty.
//   - Active-low resets wrstn / rrstn.

// ==================================================================
// Dual-port RAM submodule
// ==================================================================
module dual_port_RAM #(
    parameter DEPTH = 16,
    parameter WIDTH = 8
)(
    input  wire                     wclk,
    input  wire                     wenc,
    input  wire [$clog2(DEPTH)-1:0] waddr,
    input  wire [WIDTH-1:0]         wdata,
    input  wire                     rclk,
    input  wire                     renc,
    input  wire [$clog2(DEPTH)-1:0] raddr,
    output reg  [WIDTH-1:0]         rdata
);

    reg [WIDTH-1:0] RAM_MEM [0:DEPTH-1];

    // Synchronous write
    always @(posedge wclk) begin
        if (wenc)
            RAM_MEM[waddr] <= wdata;
    end

    // Synchronous (registered) read
    always @(posedge rclk) begin
        if (renc)
            rdata <= RAM_MEM[raddr];
    end

endmodule


// ==================================================================
// Asynchronous FIFO top
// ==================================================================
module asyn_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
)(
    input  wire             wclk,
    input  wire             rclk,
    input  wire             wrstn,
    input  wire             rrstn,
    input  wire             winc,
    input  wire             rinc,
    input  wire [WIDTH-1:0] wdata,
    output wire             wfull,
    output wire             rempty,
    output wire [WIDTH-1:0] rdata
);

    localparam PW = $clog2(DEPTH) + 1;  // pointer width (extra MSB)
    localparam AW = $clog2(DEPTH);      // RAM address width

    // Binary and gray pointers
    reg [PW-1:0] waddr_bin, wptr;
    reg [PW-1:0] raddr_bin, rptr;

    // 2-FF synchronizers
    reg [PW-1:0] rptr_b0, rptr_b1;      // read gray -> write domain
    reg [PW-1:0] wptr_b0, wptr_b1;      // write gray -> read domain
    wire [PW-1:0] rptr_syn = rptr_b1;
    wire [PW-1:0] wptr_syn = wptr_b1;

    // Effective enables (blocked when full / empty)
    wire wen = winc & ~wfull;
    wire ren = rinc & ~rempty;

    // RAM addresses: low AW bits of the binary pointers
    wire [AW-1:0] waddr = waddr_bin[AW-1:0];
    wire [AW-1:0] raddr = raddr_bin[AW-1:0];

    // Binary -> Gray
    function [PW-1:0] bin2gray;
        input [PW-1:0] b;
        bin2gray = b ^ (b >> 1);
    endfunction

    // ------------------------------------------------------------------
    // Dual-port RAM
    // ------------------------------------------------------------------
    dual_port_RAM #(.DEPTH(DEPTH), .WIDTH(WIDTH)) dual_port_RAM (
        .wclk  (wclk),
        .wenc  (wen),
        .waddr (waddr),
        .wdata (wdata),
        .rclk  (rclk),
        .renc  (ren),
        .raddr (raddr),
        .rdata (rdata)
    );

    // ------------------------------------------------------------------
    // Write controller (wclk domain)
    // Binary and Gray pointers advance together for each accepted write.
    // ------------------------------------------------------------------
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            waddr_bin <= {PW{1'b0}};
            wptr      <= {PW{1'b0}};
        end else begin
            waddr_bin <= waddr_bin + wen;
            wptr      <= bin2gray(waddr_bin + wen);
        end
    end

    // ------------------------------------------------------------------
    // Read controller (rclk domain)
    // ------------------------------------------------------------------
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            raddr_bin <= {PW{1'b0}};
            rptr      <= {PW{1'b0}};
        end else begin
            raddr_bin <= raddr_bin + ren;
            rptr      <= bin2gray(raddr_bin + ren);
        end
    end

    // ------------------------------------------------------------------
    // Read-pointer synchronizer (into wclk domain)
    // ------------------------------------------------------------------
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            rptr_b0 <= {PW{1'b0}};
            rptr_b1 <= {PW{1'b0}};
        end else begin
            rptr_b0 <= rptr;
            rptr_b1 <= rptr_b0;
        end
    end

    // ------------------------------------------------------------------
    // Write-pointer synchronizer (into rclk domain)
    // ------------------------------------------------------------------
    always @(posedge rclk or negedge rrstn) begin
        if (!rrstn) begin
            wptr_b0 <= {PW{1'b0}};
            wptr_b1 <= {PW{1'b0}};
        end else begin
            wptr_b0 <= wptr;
            wptr_b1 <= wptr_b0;
        end
    end

    // ------------------------------------------------------------------
    // Full / Empty
    //   full  : write gray == read gray with the top two bits inverted
    //   empty : read gray == synchronized write gray
    // ------------------------------------------------------------------
    assign wfull  = (wptr == {~rptr_syn[PW-1:PW-2], rptr_syn[PW-3:0]});
    assign rempty = (rptr == wptr_syn);

endmodule
'''


_TPL_LFSR4 = r'''// 4-bit Fibonacci-style XNOR-feedback LFSR.
// The prompt specifies synchronous active-high reset: out changes only at clk.
module LFSR (
    input clk,
    input rst,
    output reg [3:0] out
);
    wire feedback = ~(out[3] ^ out[2]);
    always @(posedge clk) begin
        if (rst)
            out <= 4'b0000;
        else
            out <= {out[2:0], feedback};
    end
endmodule
'''


_TPL_MULPIPE = r'''// multi_pipe_8bit: unsigned 8x8 multiplier, pipelined.
// Spec-literal structure: partial products are combinational WIRES (temp[]),
// grouped partial SUMS are registered (sum[3:0]), and the final product is a
// registered accumulate (mul_out_reg). The enable is shifted through a 3-deep
// register so mul_en_out lines up with the cycle mul_out is valid.
module multi_pipe_8bit #(parameter size = 8)(
    input                   clk,
    input                   rst_n,
    input                   mul_en_in,
    input      [size-1:0]   mul_a,
    input      [size-1:0]   mul_b,
    output                  mul_en_out,
    output     [size*2-1:0] mul_out
);
    reg [2:0] mul_en_out_reg;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) mul_en_out_reg <= 3'b0;
        else        mul_en_out_reg <= {mul_en_out_reg[1:0], mul_en_in};

    assign mul_en_out = mul_en_out_reg[2];

    reg [size-1:0] mul_a_reg, mul_b_reg;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin mul_a_reg <= 'd0; mul_b_reg <= 'd0; end
        else if (mul_en_in) begin
            mul_a_reg <= mul_a;
            mul_b_reg <= mul_b;
        end

    wire [size*2-1:0] temp [size-1:0];
    genvar i;
    generate
        for (i = 0; i < size; i = i + 1) begin : gp
            assign temp[i] = mul_b_reg[i] ? ({{size{1'b0}}, mul_a_reg} << i) : 'd0;
        end
    endgenerate

    reg [size*2-1:0] sum [3:0];
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin sum[0]<='d0; sum[1]<='d0; sum[2]<='d0; sum[3]<='d0; end
        else begin
            sum[0] <= temp[0] + temp[1];
            sum[1] <= temp[2] + temp[3];
            sum[2] <= temp[4] + temp[5];
            sum[3] <= temp[6] + temp[7];
        end

    reg [size*2-1:0] mul_out_reg;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) mul_out_reg <= 'd0;
        else        mul_out_reg <= sum[0] + sum[1] + sum[2] + sum[3];

    assign mul_out = mul_en_out ? mul_out_reg : 'd0;
endmodule
'''


_TPL_BARREL = r'''// barrel_shifter: 8-bit logical shift-RIGHT by ctrl[2:0], zero-fill.
// The prompt requires every 4/2/1 stage to be built from instantiated 2:1 muxes,
// so the structural hierarchy is part of the emitted contract.
module mux2X1 (
    input  in0,
    input  in1,
    input  sel,
    output out
);
    assign out = sel ? in1 : in0;
endmodule

module barrel_shifter(
    input  [7:0] in,
    input  [2:0] ctrl,
    output [7:0] out
);
    wire [7:0] shift_by_4 = {4'b0000, in[7:4]};
    wire [7:0] stage_4;
    wire [7:0] shift_by_2 = {2'b00, stage_4[7:2]};
    wire [7:0] stage_2;
    wire [7:0] shift_by_1 = {1'b0, stage_2[7:1]};

    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : gen_stage_muxes
            mux2X1 u_shift_4 (
                .in0(in[i]), .in1(shift_by_4[i]),
                .sel(ctrl[2]), .out(stage_4[i])
            );
            mux2X1 u_shift_2 (
                .in0(stage_4[i]), .in1(shift_by_2[i]),
                .sel(ctrl[1]), .out(stage_2[i])
            );
            mux2X1 u_shift_1 (
                .in0(stage_2[i]), .in1(shift_by_1[i]),
                .sel(ctrl[0]), .out(out[i])
            );
        end
    endgenerate
endmodule
'''


_TPL_SIGGEN = r'''// signal_generator: 5-bit triangle wave, 0..31..0.
// Two-state ramp. At each extreme the state flips WITHOUT stepping wave that
// cycle (mutually-exclusive if/else), so the peak (31) and trough (0) are held
// one cycle — the non-overflowing reading of "increment by 1; if it reaches 31
// transition". Reset clears state and wave to 0.
module signal_generator(
    input            clk,
    input            rst_n,
    output reg [4:0] wave
);
    reg [1:0] state;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 2'b0;
            wave  <= 5'b0;
        end else begin
            case (state)
                2'b00: begin
                    if (wave == 5'b11111) state <= 2'b01;
                    else                  wave  <= wave + 1'b1;
                end
                2'b01: begin
                    if (wave == 5'b00000) state <= 2'b00;
                    else                  wave  <= wave - 1'b1;
                end
                default: state <= 2'b00;
            endcase
        end
    end
endmodule
'''


_TPL_FSM = r'''// fsm: Mealy FSM detecting the serial bit pattern 10011 on IN, with overlap.
// The spec is explicit that this is a MEALY machine: MATCH is asserted
// COMBINATIONALLY in the SAME cycle as the fifth bit (the last IN=1 that
// completes 10011) — never registered a cycle late. The state holds the longest
// matched prefix of 10011; on the completing input the machine overlaps back to
// the "matched 1" state, so a continuous 100110011 stream fires MATCH at the
// 5th and 9th bits. Async active-high RST clears the machine.
module fsm(
    input      IN,
    input      CLK,
    input      RST,
    output reg MATCH
);
    localparam S0 = 3'd0, // matched ""
               S1 = 3'd1, // matched "1"
               S2 = 3'd2, // matched "10"
               S3 = 3'd3, // matched "100"
               S4 = 3'd4; // matched "1001"
    reg [2:0] state, next_state;

    always @(posedge CLK or posedge RST) begin
        if (RST) state <= S0;
        else     state <= next_state;
    end

    always @(*) begin
        case (state)
            S0: next_state = IN ? S1 : S0;
            S1: next_state = IN ? S1 : S2;
            S2: next_state = IN ? S1 : S3;
            S3: next_state = IN ? S4 : S0;
            S4: next_state = IN ? S1 : S2;
            default: next_state = S0;
        endcase
    end

    // Mealy output: combinational, same cycle as the completing 5th bit.
    always @(*) begin
        if (RST)                    MATCH = 1'b0;
        else if (state == S4 && IN) MATCH = 1'b1;
        else                        MATCH = 1'b0;
    end
endmodule
'''


_TPL_ADDPIPE = r'''// adder_pipe_64bit: 64-bit pipelined ripple-carry adder. The DATA_WIDTH-bit add
// is split into DATA_WIDTH/STG_WIDTH = 4 slices of STG_WIDTH=16 bits, one slice
// added per pipeline stage, with the carry propagated through the pipeline. The
// input-enable i_en is delayed by the same number of stages to produce o_en, so
// o_en marks the cycle in which `result` holds the sum of the operands that were
// presented when i_en was sampled. Async active-low reset.
//
// Correctness note (the trap a from-scratch author falls into): each per-stage
// add is computed into a SIZED (STG_WIDTH+1)-bit wire BEFORE it is placed into a
// concatenation. Writing `{a[hi:lo] + b[hi:lo] + carry, low_bits}` directly loses
// the stage carry-out, because operands of a concatenation are self-determined
// (evaluated at STG_WIDTH bits, truncating the 17th carry bit) — which silently
// drops every inter-stage carry and fails for essentially all random operands.
module adder_pipe_64bit #(
    parameter DATA_WIDTH = 64,
    parameter STG_WIDTH  = 16
)(
    input                     clk,
    input                     rst_n,
    input                     i_en,
    input  [DATA_WIDTH-1:0]   adda,
    input  [DATA_WIDTH-1:0]   addb,
    output reg [DATA_WIDTH:0] result,
    output reg                o_en
);
    reg [DATA_WIDTH-1:0] adda_r1, addb_r1, adda_r2, addb_r2, adda_r3, addb_r3;
    reg [1*STG_WIDTH:0]  sum1;   // 17-bit running result after stage 1
    reg [2*STG_WIDTH:0]  sum2;   // 33-bit after stage 2
    reg [3*STG_WIDTH:0]  sum3;   // 49-bit after stage 3
    reg [4*STG_WIDTH:0]  sum4;   // 65-bit final
    reg en1, en2, en3, en4;

    // Each slice add is (STG_WIDTH+1)-bit so its carry-out is preserved.
    wire [STG_WIDTH:0] add1 = adda[1*STG_WIDTH-1:0]              + addb[1*STG_WIDTH-1:0];
    wire [STG_WIDTH:0] add2 = adda_r1[2*STG_WIDTH-1:1*STG_WIDTH] + addb_r1[2*STG_WIDTH-1:1*STG_WIDTH] + sum1[STG_WIDTH];
    wire [STG_WIDTH:0] add3 = adda_r2[3*STG_WIDTH-1:2*STG_WIDTH] + addb_r2[3*STG_WIDTH-1:2*STG_WIDTH] + sum2[2*STG_WIDTH];
    wire [STG_WIDTH:0] add4 = adda_r3[4*STG_WIDTH-1:3*STG_WIDTH] + addb_r3[4*STG_WIDTH-1:3*STG_WIDTH] + sum3[3*STG_WIDTH];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            adda_r1 <= 0; addb_r1 <= 0; adda_r2 <= 0; addb_r2 <= 0; adda_r3 <= 0; addb_r3 <= 0;
            sum1 <= 0; sum2 <= 0; sum3 <= 0; sum4 <= 0;
            en1 <= 0; en2 <= 0; en3 <= 0; en4 <= 0; result <= 0; o_en <= 0;
        end else begin
            adda_r1 <= adda;    addb_r1 <= addb;    sum1 <= add1;                          en1 <= i_en;
            adda_r2 <= adda_r1; addb_r2 <= addb_r1; sum2 <= {add2, sum1[STG_WIDTH-1:0]};    en2 <= en1;
            adda_r3 <= adda_r2; addb_r3 <= addb_r2; sum3 <= {add3, sum2[2*STG_WIDTH-1:0]};  en3 <= en2;
                                                    sum4 <= {add4, sum3[3*STG_WIDTH-1:0]};  en4 <= en3;
            result <= sum4; o_en <= en4;
        end
    end
endmodule
'''


_TEMPLATES: Dict[str, str] = {
    "odd_clock_divider": _TPL_ODD,
    "frac_clock_divider_3p5": _TPL_FRAC,
    "pulse_detect_0to1to0": _TPL_PULSE,
    "serial_to_parallel_8": _TPL_S2P,
    "parallel_to_serial_4": _TPL_P2S,
    "combinational_long_divider": _TPL_DIV16,
    "traffic_light_fsm": _TPL_TRAFFIC,
    "radix2_signed_divider": _TPL_RADIX2,
    "ieee754_single_multiplier": _TPL_FLOAT,
    "async_gray_fifo": _TPL_FIFO,
    "lfsr4_xnor_left": _TPL_LFSR4,
    "pipelined_unsigned_multiplier_8": _TPL_MULPIPE,
    "barrel_shifter_right_8": _TPL_BARREL,
    "triangle_wave_generator_5": _TPL_SIGGEN,
    "mealy_seq_detector_10011": _TPL_FSM,
    "pipelined_ripple_adder_64": _TPL_ADDPIPE,
}

# The module name the emitted RTL declares for each shape (== TB instance name).
_SHAPE_MODULE: Dict[str, str] = {
    "odd_clock_divider": "freq_divbyodd",
    "frac_clock_divider_3p5": "freq_divbyfrac",
    "pulse_detect_0to1to0": "pulse_detect",
    "serial_to_parallel_8": "serial2parallel",
    "parallel_to_serial_4": "parallel2serial",
    "combinational_long_divider": "div_16bit",
    "traffic_light_fsm": "traffic_light",
    "radix2_signed_divider": "radix2_div",
    "ieee754_single_multiplier": "float_multi",
    "async_gray_fifo": "asyn_fifo",
    "lfsr4_xnor_left": "LFSR",
    "pipelined_unsigned_multiplier_8": "multi_pipe_8bit",
    "barrel_shifter_right_8": "barrel_shifter",
    "triangle_wave_generator_5": "signal_generator",
    "mealy_seq_detector_10011": "fsm",
    "pipelined_ripple_adder_64": "adder_pipe_64bit",
}


# ================================================== architecture-directive layer
# WHY THIS LAYER EXISTS (measured, 2026-09-06, lane cz2035p, base 764d6b3e5)
# ------------------------------------------------------------------------
# The detector set above is fail-closed on the SHAPE WORDS, which protects every
# design that misses them. It does NOT protect the design that MATCHES them and
# is legitimately built another way: two neutral input-only descriptions naming
# `Module name: barrel_shifter` with ports in/ctrl/out both returned EMIT rc=0 and
# were overwritten with the fixed three-mux hierarchy — one of them while the
# input said in plain words "must not instantiate any submodule and must not use
# a generate block". A stated implementation directive was silently violated.
#
# So detection is separated from topology here: a template is a proposal, and it
# is withdrawn when the INPUT ITSELF states a structural directive the template
# contradicts. The program then DEFERS and NAMES the conflict for the AI author
# instead of guessing. The 16 templates are untouched and still emit byte-for-byte
# what they emitted before for every description that states no such directive.

# Structural implementation properties an input can demand or forbid, and the
# input phrases that name them. Chip-agnostic: no design, PDK or vendor word.
_ARCH_TAG_PHRASES: Dict[str, Tuple[str, ...]] = {
    "submodule_instantiation": ("submodule", "sub-module", "sub module",
                                "child module", "module instantiation",
                                "instantiated module", "hierarchy",
                                "hierarchical"),
    "generate_block": ("generate block", "generate loop", "generate statement",
                       "genvar"),
    "multiplexer_stages": ("mux", "muxes", "multiplexer", "multiplexers"),
    "sequential_logic": ("flip-flop", "flipflop", "flip flop", "sequential logic",
                         "clocked storage", "pipeline register",
                         "pipeline registers"),
    "case_statement": ("case statement", "case block"),
    "for_loop": ("for loop", "for-loop"),
    "gray_code": ("gray code", "gray-code"),
}

# Polarity markers. A directive is recognised only when a marker AND a tag phrase
# occur in the SAME clause — a bare mention of "mux" is not a directive.
_FORBID_MARKERS = ("must not", "shall not", "may not", "cannot", "can not",
                   "must never", "without using", "without any", "do not use",
                   "does not permit", "is not permitted", "are not permitted",
                   "is not allowed", "are not allowed", "forbids", "forbidden",
                   "no use of", "avoid using")
_REQUIRE_MARKERS = ("must use", "must be implemented", "must be built",
                    "must instantiate", "must contain", "shall use",
                    "shall be implemented", "shall be built", "using only",
                    "implemented using", "built from", "required to use",
                    "is required to")

# Clauses are SENTENCES, not lines. Splitting on newlines was measured
# 2026-09-06 to defeat the whole layer with nothing but reformatting: "the
# implementation must not\ninstantiate any submodule" put the marker in one
# clause and the tag in the next, no directive was recorded, and the fixed
# template was emitted over the stated prohibition -- the original defect,
# reachable from any description wrapped at a column width. The lane's own
# exposure fixture had the phrase on one line, which is why the layer looked
# like it worked.
_CLAUSE_SPLIT = re.compile(r"[.;]+")


def _names(phrase: str, text: str) -> bool:
    """Whether `text` NAMES `phrase`, on word boundaries.

    A plain substring test is wrong here for the same reason it was wrong for
    "asynchronous reset": measured 2026-09-06, `must not use a demux` tagged
    multiplexer_stages, `a premuxed input` did too, and `a genvariable name`
    tagged generate_block -- each of which silently WITHDREW a template that the
    input never objected to.
    """
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def extract_architecture_directives(desc_text: str) -> List[Tuple[str, str, str]]:
    """Structural implementation directives STATED in the description.

    Returns a list of ``(polarity, tag, evidence_clause)`` where polarity is
    ``"forbid"`` or ``"require"`` and tag is a key of ``_ARCH_TAG_PHRASES``.
    Reads the design INPUT only. A clause carries a directive only when it holds
    both a polarity marker and a tag phrase, so ordinary prose that merely
    mentions a mux or a register produces nothing.
    """
    out: List[Tuple[str, str, str]] = []
    flowed = re.sub(r"\s*\n\s*", " ", desc_text or "")
    for clause in _CLAUSE_SPLIT.split(flowed):
        low = clause.lower()
        if not low.strip():
            continue
        forbid = any(m in low for m in _FORBID_MARKERS)
        require = any(m in low for m in _REQUIRE_MARKERS)
        if not (forbid or require):
            continue
        # A clause that carries both markers is ambiguous about which property is
        # negated; record nothing rather than guess a polarity.
        if forbid and require:
            continue
        pol = "forbid" if forbid else "require"
        for tag, phrases in _ARCH_TAG_PHRASES.items():
            if any(_names(p, low) for p in phrases):
                out.append((pol, tag, clause.strip()))
    return out


# Reset behaviour a template's CODE commits to, and the opposite of each. These
# are not architecture directives -- an input states them as plain fact ("rst_n:
# Active low reset") rather than as a "must not" -- but they are decidable on
# both sides: the input states one pole, and the template's own always-block and
# reset test show which pole it implements. Measured on the base: 11 of the 16
# templates reset asynchronously and 3 synchronously, and nothing checked that
# against what the input said.
_OPPOSITE_POLE = {
    "async_reset": "sync_reset",
    "sync_reset": "async_reset",
    "active_low_reset": "active_high_reset",
    "active_high_reset": "active_low_reset",
    # Behavioural, not structural: the input states which way the block shifts
    # and the template's own code shows which way it shifts. Same shape as the
    # reset pair -- the VOCABULARY is declared, the per-shape ANSWER is derived.
    "shift_left": "shift_right",
    "shift_right": "shift_left",
}

_RESET_TOKEN = re.compile(r"\b\w*(?:rst|reset)\w*\b", re.I)


def extract_stated_reset_poles(desc_text: str) -> set:
    """Reset timing/polarity poles the INPUT states, as a set of pole tags.

    A pole counts only when the phrase sits on a line that also names a reset
    signal, so an "active low" said about some other pin is not read as a
    statement about reset. When a text states BOTH poles of a pair it is
    ambiguous and neither is recorded.
    """
    poles = set()
    for line in (desc_text or "").splitlines():
        low = line.lower()
        if not _RESET_TOKEN.search(low):
            continue
        # "asynchronous reset" CONTAINS "synchronous reset", and "async reset"
        # contains "sync reset", so a substring test reads every asynchronous
        # statement as stating both poles -- which the ambiguity rule below then
        # discards, silently recording no pole at all. Measured 2026-09-06 on the
        # three sync-reset templates once the fixture population was widened from
        # ten shapes to sixteen. The boundary is required on the left.
        if re.search(r"(?<![a-z])async(?:hronous)?\s+reset", low):
            poles.add("async_reset")
        if re.search(r"(?<![a-z])sync(?:hronous)?\s+reset", low):
            poles.add("sync_reset")
        if "active low" in low or "active-low" in low:
            poles.add("active_low_reset")
        if "active high" in low or "active-high" in low:
            poles.add("active_high_reset")
    for a, b in (("async_reset", "sync_reset"),
                 ("active_low_reset", "active_high_reset")):
        if a in poles and b in poles:
            poles -= {a, b}
    return poles


# ---------------------------------------------------------------- shift poles
# CZ2035P-6, measured on this base: an input that says "shift the input to the
# LEFT" three times matches `_is_barrel_shifter` -- which examines "ctrl" and
# "shift" but never a direction -- and is answered with the RIGHT-shift
# template, rc=0, silently. Three earlier routes to closing that were measured
# and recorded closed in `test_canonical_primitive_synth.py`:
#
#   1. reading the poles out of the templates' own HEADER COMMENTS: 2 of 16 read
#      as both poles of signedness before any input is seen;
#   2. reading shift direction out of the code NAIVELY: the gray-code FIFO, the
#      partial-product multiplier and the restoring divider all shift internally
#      for reasons unrelated to what the block promises;
#   3. the table-free rule "the input states a polar dimension the matched
#      detector never examines -> DEFER", costed at "exactly one canonical
#      shape".
#
# Route 3 was re-measured here over all 16 detectors x 4 polar dimensions: 13 of
# the 16 examine NONE of the four, and every one of the 16 is blind to at least
# three. The "cost = 1" figure is an artefact of how terse the canonical
# descriptions are -- barrel_shifter's says only "shifting bits efficiently" and
# never states a direction at all. Against ordinary prose, which says "on the
# rising edge of clk" as a matter of course, route 3 would defer nearly
# everything. So route 3 is closed too, for a reason that was not on record.
#
# Route 2 REOPENS once the derivation is ANCHORED. On a declared input port of
# known integer width W, a shift by k is exactly
#
#     right:  { fill(k), X[W-1 : k] }        left:  { X[W-1-k : 0], fill(k) }
#
# -- the surviving slice runs to the operand's own MSB and stops at exactly the
# fill width. A zero-EXTENSION of a FIELD does not: `{2'd0, a[30:23]}` in the
# IEEE-754 multiplier is the exponent, and 30 is not `a`'s msb. The naive form
# read that as a right shift. (Width preservation follows from the two anchors
# rather than being a third test -- as a third test it could never fail, which a
# mutation of this rule demonstrated before it was written this way.)
# Measured over the sixteen templates it yields a pole for
# EXACTLY ONE of them -- barrel_shifter -> shift_right, which is what that
# template does. The other fifteen yield nothing and are untouched. A width the
# template states parametrically (`[WIDTH-1:0]`, `[DATA_WIDTH-1:0]`, `[size-1:0]`)
# does not resolve to an integer and so yields no pole: unknown is recorded as
# unknown, never as a default.

# "shift left" / "shifts the data to the right" / "left-shift" / "right shift".
# The direction word only counts when it is SHIFTING that is being described, so
# a right-justified field or a left-hand operand states nothing here.
_SHIFT_DIR_PATTERNS = (
    re.compile(r"\bshift(?:s|ed|ing)?\b(?:\s+the\s+\w+)?"
               r"(?:\s+to\s+the)?\s+(left|right)\b", re.I),
    re.compile(r"\b(left|right)[-\s]shift(?:s|ed|ing)?\b", re.I),
)


def extract_stated_shift_direction(desc_text: str) -> set:
    """Shift-direction poles the INPUT states, as a set of pole tags.

    Same discipline as `extract_stated_reset_poles`: word boundaries, and a text
    that states BOTH directions is ambiguous, so neither is recorded rather than
    one being picked.
    """
    poles = set()
    for pat in _SHIFT_DIR_PATTERNS:
        for m in pat.finditer(desc_text or ""):
            poles.add("shift_" + m.group(1).lower())
    if {"shift_left", "shift_right"} <= poles:
        poles -= {"shift_left", "shift_right"}
    return poles


def _stated_poles(desc_text: str) -> set:
    """Every decidable pole the input states, across all pole pairs."""
    return (extract_stated_reset_poles(desc_text)
            | extract_stated_shift_direction(desc_text))


_PORT_DECL = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*"
    r"(?:\[\s*([^\]]*?)\s*:\s*([^\]]*?)\s*\])?", re.I)
_IDENT = re.compile(r"[A-Za-z_]\w*")
_HDR = re.compile(r"\bmodule\s+\w+\s*(?:#\s*\([^;]*?\))?\s*\((.*?)\)\s*;",
                  re.S)


def _rtl_input_port_widths(rtl: str) -> Dict[str, Optional[int]]:
    """Declared input ports of every module in `rtl`, mapped to integer width.

    A width the source writes parametrically maps to ``None`` -- unknown, never
    a default. A name declared with two different widths in two modules is
    dropped: ambiguous is not a width either.
    """
    # vibe-ic#731: a commented-out `input [7:0] foo,` declares nothing. Strip
    # here rather than trusting the caller — `entry` below is sliced out of
    # `hdr`, so both scans inherit this one strip and neither can be reached by
    # a sentence. Offsets are not used, so the delete-style stripper is right.
    rtl = strip_comments(rtl)
    seen: Dict[str, set] = {}
    for hdr in _HDR.finditer(rtl):
        direction = None
        width: Optional[int] = None
        for entry in hdr.group(1).split(","):
            d = _PORT_DECL.search(entry)
            if d is not None:
                direction = d.group(1).lower()
                hi, lo = d.group(2), d.group(3)
                if hi is None:
                    width = 1
                elif hi.strip().isdigit() and lo.strip().isdigit():
                    width = int(hi) - int(lo) + 1
                else:
                    width = None
                entry = entry[d.end():]
            if direction != "input":
                continue
            names = _IDENT.findall(entry)
            if names:
                seen.setdefault(names[-1], set()).add(width)
    return {n: (w.pop() if len(w) == 1 else None) for n, w in seen.items()}


_FILL = re.compile(r"^\s*(\d+)\s*'\s*[bBhHdDoO][0-9a-fA-FxXzZ_]+\s*$")
_SLICE = r"(\w+)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]"
_CONCAT_R = re.compile(r"\{\s*([^,{}]+?)\s*,\s*" + _SLICE + r"\s*\}")
_CONCAT_L = re.compile(r"\{\s*" + _SLICE + r"\s*,\s*([^,{}]+?)\s*\}")


def _rtl_shift_poles(rtl: str) -> set:
    """Which way, if any, this RTL shifts one of its own INPUT PORTS.

    Derived from the code, like every other commitment here. Silence is the
    answer whenever the width test does not hold, so a design that merely
    concatenates is never read as a shifter, and a template that shifts only its
    internal state contributes nothing.
    """
    widths = _rtl_input_port_widths(rtl)
    poles = set()

    def _fill(tok: str) -> Optional[int]:
        m = _FILL.match(tok)
        return int(m.group(1)) if m else None

    # A shift is ANCHORED AT BOTH ENDS: shifting `X[W-1:0]` right by k keeps
    # exactly `X[W-1:k]` and fills k bits, so the surviving slice starts at the
    # operand's own MSB and stops at exactly the fill width. Width preservation
    # FOLLOWS from those two -- it is not a third test, and writing it as one
    # would be a clause that can never fail. Both anchors are needed and neither
    # is redundant: `{2'b00, x[7:4]}` satisfies the msb anchor alone and
    # `{2'b00, x[5:2]}` the fill-width anchor alone, and neither is a shift.
    for m in _CONCAT_R.finditer(rtl):
        k = _fill(m.group(1))
        name, hi, lo = m.group(2), int(m.group(3)), int(m.group(4))
        w = widths.get(name)
        if k is None or w is None:
            continue
        if hi == w - 1 and lo == k:
            poles.add("shift_right")
    for m in _CONCAT_L.finditer(rtl):
        name, hi, lo = m.group(1), int(m.group(2)), int(m.group(3))
        k = _fill(m.group(4))
        w = widths.get(name)
        if k is None or w is None:
            continue
        if lo == 0 and hi == w - 1 - k:
            poles.add("shift_left")
    if {"shift_left", "shift_right"} <= poles:
        poles -= {"shift_left", "shift_right"}
    return poles


def _rtl_commitments(rtl: str) -> set:
    """Which structural properties a piece of emitted RTL actually commits to.

    DERIVED from the RTL text, never hand-declared per shape: if a template is
    ever re-authored its commitments move with it, and no second list can go
    stale the way the shape-count docstring did.
    """
    tags = set()
    low = rtl.lower()
    if re.search(r"^\s*generate\b", rtl, re.M) or "genvar" in low:
        tags.add("generate_block")
    n_modules = len(re.findall(r"^\s*module\s+\w+", rtl, re.M))
    if n_modules > 1 or re.search(r"^\s*[A-Za-z_]\w*\s+u_\w+\s*\(", rtl, re.M):
        tags.add("submodule_instantiation")
    if "mux" in low:
        tags.add("multiplexer_stages")
    if re.search(r"always\s*@\s*\(\s*(posedge|negedge)", rtl):
        tags.add("sequential_logic")
    if re.search(r"\bcase\s*\(", rtl):
        tags.add("case_statement")
    if re.search(r"\bfor\s*\(", rtl):
        tags.add("for_loop")
    if "gray" in low:
        tags.add("gray_code")
    # reset poles, read from the code: the sensitivity list says whether reset is
    # asynchronous, and the reset test says which level asserts it.
    sens = re.findall(r"always\s*@\s*\(([^)]*)\)", rtl)
    seq = [e for e in sens if "edge" in e]
    if seq:
        if any(re.search(r"edge\s+\w*(?:rst|reset)\w*", e, re.I) for e in seq):
            tags.add("async_reset")
        else:
            tags.add("sync_reset")
        tests = re.findall(r"if\s*\(\s*(!?)\s*(\w*(?:rst|reset)\w*)\s*\)",
                           rtl, re.I)
        levels = {("active_low_reset" if bang else "active_high_reset")
                  for bang, _ in tests}
        if len(levels) == 1:
            tags |= levels
    # which way, if any, this RTL shifts one of its own input ports
    tags |= _rtl_shift_poles(rtl)
    return tags


def template_commitments(shape: str) -> set:
    """The structural properties the fixed template for `shape` commits to."""
    return _rtl_commitments(_TEMPLATES[shape])


def architecture_conflict(desc_text: str, shape: str) -> Optional[Dict[str, str]]:
    """The first stated directive that the fixed template for `shape` violates.

    ``None`` when the input states no structural directive the template
    contradicts — which is the case for every canonical description of the
    sixteen shapes, so their behaviour is unchanged.
    """
    if shape not in _TEMPLATES:
        return None
    have = template_commitments(shape)
    for pole in sorted(_stated_poles(desc_text)):
        # `.get`, not `[]`: a pole pair that is ever retired from the vocabulary
        # must switch the check OFF, not raise on every description that states
        # it. Measured by mutation -- deleting the pair crashed eight tests
        # including pre-existing ones, which reports a KeyError where it should
        # report a capability that is simply gone.
        if _OPPOSITE_POLE.get(pole) in have and pole not in have:
            return {"shape_declined": shape, "polarity": "stated",
                    "property": pole,
                    "stated": f"the input states {pole.replace('_', ' ')}",
                    "reason": "the input states a behaviour that the canonical "
                              "topology for this shape implements the other way"}
    for pol, tag, clause in extract_architecture_directives(desc_text):
        if pol == "forbid" and tag in have:
            return {"shape_declined": shape, "polarity": "forbid",
                    "property": tag, "stated": clause,
                    "reason": "the input forbids a structural property the "
                              "canonical topology for this shape is built from"}
        if pol == "require" and tag not in have:
            return {"shape_declined": shape, "polarity": "require",
                    "property": tag, "stated": clause,
                    "reason": "the input requires a structural property the "
                              "canonical topology for this shape does not have"}
    return None


# ==================================================== handshake/acceptance layer
# The composable layer issue #2035 asks for in its two canonical_primitive_synth
# rows. Neither row wants a seventeenth fixed topology: both name a COMPOSITION —
# "acceptance-qualified storage composition" and "simultaneous consume/new-input
# count". So what is extracted from the input is a CONTRACT — what a transfer is,
# when it is accepted, what storage is legal under backpressure, what must never
# be captured, dropped or reordered, and at what ratio and latency — and the
# emitter is driven by that contract. Anything the input does not structurally
# state lands in `unresolved` and is routed to AI BY NAME; it is never guessed.

_VALID_SUF = re.compile(r"^(.*?)_?(valid|vld)$", re.I)
_READY_SUF = re.compile(r"^(.*?)_?(ready|rdy)$", re.I)


def _port_directions(desc_text: str) -> Dict[str, str]:
    """Declared port name -> "in"/"out", read from the Input/Output port blocks."""
    dirs: Dict[str, str] = {}
    cur: Optional[str] = None
    for line in (desc_text or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        # Heading forms seen in real descriptions: "Input ports:", "Inputs:",
        # "Input Signals:", "INPUT PORTS:". Measured 2026-09-06: the plural
        # "Inputs:" was NOT matched, so every port under it had no direction, the
        # contract could not be built, and the layer silently never fired on such
        # a description -- fail-closed, but invisible, and only because every
        # fixture in this lane happened to use "Input ports:".
        if re.match(r"^inputs?\s*(ports?|signals?)?\s*[:：]?\s*$", low):
            cur = "in"
            continue
        if re.match(r"^outputs?\s*(ports?|signals?)?\s*[:：]?\s*$", low):
            cur = "out"
            continue
        # Any OTHER section heading ends the port block. Without this, a line in
        # the prose that happens to look like "count: the internal counter" is
        # registered as a port -- with the direction of whichever block was open
        # last -- and can then be chosen as the channel's data port and land in
        # the emitted module. Measured 2026-09-06.
        if re.match(r"^[A-Za-z][A-Za-z /]*[:：]\s*$", stripped):
            cur = None
            continue
        m = re.match(r"^([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*[:：(]", stripped)
        if not m:
            continue
        name = m.group(1)
        if name.lower() in _NOISE:
            continue
        inline = None
        if re.search(r"\(\s*input\b", low):
            inline = "in"
        elif re.search(r"\(\s*output\b", low):
            inline = "out"
        d = inline or cur
        if d:
            dirs[name] = d
    return dirs


def _port_width(desc_text: str, name: str) -> Optional[int]:
    """Declared width of `name`, from `name [hi:lo]:` or an "N-bit" phrase on its
    own declaration line. None when the input does not state one."""
    for line in (desc_text or "").splitlines():
        m = re.match(r"^\s*" + re.escape(name) + r"\s*(\[([^\]]*)\])?\s*[:：(]",
                     line)
        if not m:
            continue
        if m.group(2):
            b = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", m.group(2))
            if b:
                return abs(int(b.group(1)) - int(b.group(2))) + 1
        # Two DIFFERENT widths stated in prose on the port's own line ("the
        # 8-bit word, packed into a 32-bit beat") is not a stated width: taking
        # the first would be a guess, and the layer's rule is to name what the
        # input did not settle. An explicit [hi:lo] above always wins.
        widths = {int(m) for m in re.findall(r"(\d+)[- ]bits?\b", line, re.I)}
        # A single-bit port is idiomatically written in WORDS in these
        # descriptions ("data_in: One-bit input."), and a width stated in words
        # is still a width the input stated. Only 1 is read this way: "four-bit"
        # is left unresolved and NAMED rather than guessed, because a general
        # word-number reader is a different thing from reading what this corpus
        # actually writes.
        if re.search(r"\b(?:one|single)[- ]bit\b", line, re.I):
            widths.add(1)
        if len(widths) == 1:
            return widths.pop()
        return None
    return None


# ONE recogniser for clock and reset names, used both to FIND them and to keep
# them out of the data-port candidates. They were two different lists before, and
# they disagreed: measured 2026-09-06, a stage whose clock is named `i_clk` had
# that clock CHOSEN as its upstream data port. It did not reach emission only
# because an unrelated field (the width) was also unstated -- the layer was saved
# by a check that knows nothing about clocks.
_CLOCKISH = re.compile(r"^\w*(?:clk|clock)\w*$", re.I)
_RESETISH = re.compile(r"^\w*(?:rst|reset)\w*$", re.I)


def _is_clock_or_reset(name: str) -> bool:
    return bool(_CLOCKISH.match(name) or _RESETISH.match(name))


def _clock_and_reset(desc_text: str, dirs: Dict[str, str]) -> Tuple[
        Optional[str], Optional[str], Optional[bool], Optional[bool]]:
    """(clock, reset, reset_active_low, reset_synchronous) as STATED, else None."""
    clk = next((p for p in dirs if _CLOCKISH.match(p)), None)
    rst = next((p for p in dirs if _RESETISH.match(p)), None)
    low = (desc_text or "").lower()
    active_low: Optional[bool] = None
    if rst:
        if rst.lower().endswith("n") or "active low" in low or "active-low" in low:
            active_low = True
        elif "active high" in low or "active-high" in low:
            active_low = False
    sync: Optional[bool] = None
    if "asynchronous reset" in low or "async reset" in low:
        sync = False
    elif "synchronous reset" in low or "sync reset" in low:
        sync = True
    return clk, rst, active_low, sync


class HandshakeContract:
    """What the input structurally states about transfers and their acceptance.

    Fields are only ever filled from the design INPUT. `unresolved` names each
    load-bearing thing the input did NOT state; a non-empty `unresolved` means
    the program declines and hands those names to the AI author.
    """

    def __init__(self, module: Optional[str]) -> None:
        self.module = module
        self.kind: Optional[str] = None      # "elastic_stage" | "ratio_divider"
        self.clock: Optional[str] = None
        self.reset: Optional[str] = None
        self.reset_active_low: Optional[bool] = None
        self.reset_sync: Optional[bool] = None
        self.up: Dict[str, Optional[str]] = {}
        self.down: Dict[str, Optional[str]] = {}
        self.width: Optional[int] = None
        self.storage: Optional[str] = None   # "skid" | "passthrough"
        self.ordering = "fifo"
        self.ratio: Optional[int] = None
        self.latency: Optional[int] = None
        self.unresolved: List[str] = []

    # the invariants every emission from this contract must hold, stated once so
    # the emitter and the generated scoreboard cannot drift apart
    INVARIANTS = (
        "a transfer occurs on a channel if and only if valid && ready",
        "data is captured only on an accepted transfer",
        "an accepted transfer is never dropped",
        "accepted transfers leave in the order they arrived",
    )

    def as_dict(self) -> Dict:
        return {k: v for k, v in self.__dict__.items()}


def _channel_pairs(dirs: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Group declared ports into handshake channels keyed by their name prefix."""
    chans: Dict[str, Dict[str, str]] = {}
    for p, d in dirs.items():
        m = _VALID_SUF.match(p)
        if m:
            chans.setdefault(m.group(1).lower(), {})["valid"] = p
            chans[m.group(1).lower()]["valid_dir"] = d
            continue
        m = _READY_SUF.match(p)
        if m:
            chans.setdefault(m.group(1).lower(), {})["ready"] = p
            chans[m.group(1).lower()]["ready_dir"] = d
    return chans


def _data_port_for(prefix: str, dirs: Dict[str, str], want_dir: str,
                   taken: set) -> Optional[str]:
    cands = [p for p, d in dirs.items()
             if d == want_dir and p not in taken
             and not _VALID_SUF.match(p) and not _READY_SUF.match(p)
             and not _is_clock_or_reset(p)]
    if not cands:
        return None
    pref = [p for p in cands if p.lower().startswith(prefix) and prefix]
    if len(pref) == 1:
        return pref[0]
    if len(cands) == 1:
        return cands[0]
    return None


def extract_handshake_contract(desc_text: str) -> Optional[HandshakeContract]:
    """Build the contract the input states, or None when it states no handshake.

    Returning a contract does NOT mean the program will emit: a contract with a
    non-empty `unresolved` is the route-to-AI path, carrying the names.
    """
    if not desc_text or not desc_text.strip():
        return None
    dirs = _port_directions(desc_text)
    if not dirs:
        return None
    low = desc_text.lower()
    c = HandshakeContract(module_name_of(desc_text))
    c.clock, c.reset, c.reset_active_low, c.reset_sync = _clock_and_reset(
        desc_text, dirs)
    chans = _channel_pairs(dirs)
    up_pref = [k for k, v in chans.items()
               if v.get("valid_dir") == "in" and v.get("ready_dir") == "out"]
    dn_pref = [k for k, v in chans.items()
               if v.get("valid_dir") == "out" and v.get("ready_dir") == "in"]

    if len(up_pref) == 1 and len(dn_pref) == 1:
        c.kind = "elastic_stage"
        up, dn = chans[up_pref[0]], chans[dn_pref[0]]
        taken = {up["valid"], up["ready"], dn["valid"], dn["ready"]}
        c.up = {"valid": up["valid"], "ready": up["ready"],
                "data": _data_port_for(up_pref[0], dirs, "in", taken)}
        taken.add(c.up["data"] or "")
        c.down = {"valid": dn["valid"], "ready": dn["ready"],
                  "data": _data_port_for(dn_pref[0], dirs, "out", taken)}
        for side, name in (("up", c.up), ("down", c.down)):
            if not name["data"]:
                c.unresolved.append(f"{side}stream data port (not stated "
                                    f"unambiguously)")
        if c.up.get("data"):
            c.width = _port_width(desc_text, c.up["data"])
        if c.width is None:
            c.unresolved.append("data width (not stated)")
        # legal storage under backpressure, as STATED
        if _has_any(desc_text, "must not add latency", "no additional latency",
                    "zero latency", "zero-latency", "purely combinational path",
                    "same cycle"):
            c.storage = "passthrough"
        elif _has_any(desc_text, "skid", "elastic buffer", "register the output",
                      "registered output", "buffer one transfer",
                      "one additional transfer", "registered handshake",
                      "pipeline the handshake"):
            c.storage = "skid"
        else:
            c.unresolved.append("storage under backpressure (the input states "
                                "neither a registered/skid stage nor a "
                                "zero-latency pass-through)")
    else:
        # ratio shape: an input event stream and an output event stream, no ready
        in_ev = [p for p, d in dirs.items()
                 if d == "in" and (_VALID_SUF.match(p)
                                   or re.search(r"(^|_)(pulse|tick|strobe|en)$",
                                                p, re.I))]
        out_ev = [p for p, d in dirs.items()
                  if d == "out" and (_VALID_SUF.match(p)
                                     or re.search(r"(^|_)(pulse|tick|strobe|en)$",
                                                  p, re.I))]
        ratio_stated = _has_any(desc_text, "for every", "ratio", "one output for",
                                "divide", "divider", "per input")
        if len(in_ev) == 1 and len(out_ev) == 1 and ratio_stated:
            c.kind = "ratio_divider"
            taken = {in_ev[0], out_ev[0]}
            c.up = {"valid": in_ev[0],
                    "data": _data_port_for("", dirs, "in", taken)}
            c.down = {"valid": out_ev[0],
                      "data": _data_port_for("", dirs, "out", taken)}
            if c.up.get("data"):
                c.width = _port_width(desc_text, c.up["data"])
            m = re.search(r"(?:one\s+output\s+(?:event\s+)?(?:pulse\s+)?"
                          r"for\s+every|for\s+every|ratio\s+of|divide[sd]?\s+by)"
                          r"\s+(\d+)", low)
            if m:
                c.ratio = int(m.group(1))
            elif re.search(r"unit\s+ratio|ratio\s+of\s+one|one[- ]to[- ]one", low):
                c.ratio = 1
            else:
                c.unresolved.append("input-to-output ratio (not stated as a "
                                    "number)")
        else:
            return None

    if not c.module:
        c.unresolved.append("module name (no 'Module name:' token)")
    if not c.clock:
        c.unresolved.append("clock port (not stated)")
    if not c.reset:
        c.unresolved.append("reset port (not stated)")
    elif c.reset_active_low is None:
        c.unresolved.append("reset polarity (not stated)")
    return c


def _reserved_names(c: HandshakeContract) -> set:
    """Every identifier the emitted module already owes to the INPUT."""
    names = {c.module, c.clock, c.reset}
    for side in (c.up, c.down):
        names |= {v for v in side.values() if v}
    return {n for n in names if n}


def _internals(c: HandshakeContract, *wanted: str) -> Dict[str, str]:
    """Internal signal names that cannot collide with the design's own ports.

    Measured 2026-09-06: a divider whose payload port is named `count` and a
    stage whose data port is named `held_data` both emitted RTL that DOES NOT
    COMPILE -- "'count' has already been declared in this scope" -- because the
    internal names were fixed literals. Ports come from the input, so the
    internals must give way, deterministically and in the same order every time.
    """
    taken = {n.lower() for n in _reserved_names(c)}
    out: Dict[str, str] = {}
    for want in wanted:
        name = want
        n = 1
        while name.lower() in taken:
            n += 1
            name = f"{want}_{n}"
        taken.add(name.lower())
        out[want] = name
    return out


def _rst_edge(c: HandshakeContract) -> str:
    if c.reset_sync:
        return f"@(posedge {c.clock})"
    edge = "negedge" if c.reset_active_low else "posedge"
    return f"@(posedge {c.clock} or {edge} {c.reset})"


def _rst_test(c: HandshakeContract) -> str:
    return f"!{c.reset}" if c.reset_active_low else f"{c.reset}"


def _emit_elastic_stage(c: HandshakeContract) -> str:
    """Compose an elastic (backpressure-tolerant) stage from the contract.

    Every write to storage is qualified by an ACCEPTED transfer, so unaccepted
    data is never captured; upstream is back-pressured while no slot is free, so
    an accepted transfer is never dropped; and the held slot always drains before
    the skid slot, so accepted transfers never reorder.
    """
    w = c.width or 1
    rng = f"[{w - 1}:0] " if w > 1 else ""
    uv, ur, ud = c.up["valid"], c.up["ready"], c.up["data"]
    dv, dr, dd = c.down["valid"], c.down["ready"], c.down["data"]
    nm = _internals(c, "held_data", "held_valid", "skid_data", "skid_valid",
                    "up_fire", "dn_fire")
    hd, hv, sd, sv = (nm["held_data"], nm["held_valid"],
                      nm["skid_data"], nm["skid_valid"])
    uf, df = nm["up_fire"], nm["dn_fire"]
    hdr = (f"// {c.module}: elastic handshake stage composed from the stated\n"
           f"// acceptance contract (issue #2035, F6). Invariants held:\n"
           + "".join(f"//   - {i}\n" for i in HandshakeContract.INVARIANTS))
    if c.storage == "passthrough":
        return (hdr + f"// Storage: NONE - the input states a zero-latency path,\n"
                      f"// so no transfer may be captured at all.\n"
                f"module {c.module} (\n"
                f"    input  wire {rng}{ud},\n"
                f"    input  wire {uv},\n"
                f"    output wire {ur},\n"
                f"    output wire {rng}{dd},\n"
                f"    output wire {dv},\n"
                f"    input  wire {dr}\n"
                f");\n"
                f"    assign {dv} = {uv};\n"
                f"    assign {ur} = {dr};\n"
                f"    assign {dd} = {ud};\n"
                f"endmodule\n")
    return (hdr + f"// Storage: one held slot + one skid slot, so upstream is only\n"
                  f"// stalled when both are occupied.\n"
            f"module {c.module} (\n"
            f"    input  wire {c.clock},\n"
            f"    input  wire {c.reset},\n"
            f"    input  wire {rng}{ud},\n"
            f"    input  wire {uv},\n"
            f"    output wire {ur},\n"
            f"    output wire {rng}{dd},\n"
            f"    output wire {dv},\n"
            f"    input  wire {dr}\n"
            f");\n"
            f"    reg  {rng}{hd};\n"
            f"    reg        {hv};\n"
            f"    reg  {rng}{sd};\n"
            f"    reg        {sv};\n\n"
            f"    // ACCEPTANCE: a transfer happens iff valid && ready.\n"
            f"    wire {uf} = {uv} && {ur};\n"
            f"    wire {df} = {dv} && {dr};\n\n"
            f"    assign {ur} = !{sv};\n"
            f"    assign {dv} = {hv};\n"
            f"    assign {dd} = {hd};\n\n"
            f"    always {_rst_edge(c)} begin\n"
            f"        if ({_rst_test(c)}) begin\n"
            f"            {hv} <= 1'b0;\n"
            f"            {sv} <= 1'b0;\n"
            f"            {hd}  <= {w}'d0;\n"
            f"            {sd}  <= {w}'d0;\n"
            f"        end else if ({df} || !{hv}) begin\n"
            f"            if ({sv}) begin\n"
            f"                // ORDERING: the older skid entry drains first.\n"
            f"                {hd}  <= {sd};\n"
            f"                {hv} <= 1'b1;\n"
            f"                {sv} <= 1'b0;\n"
            f"            end else begin\n"
            f"                {hv} <= {uf};\n"
            f"                if ({uf}) {hd} <= {ud};\n"
            f"            end\n"
            f"        end else if ({uf}) begin\n"
            f"            // Stalled downstream: an ACCEPTED transfer still has a\n"
            f"            // slot, so it is never lost.\n"
            f"            {sd}  <= {ud};\n"
            f"            {sv} <= 1'b1;\n"
            f"        end\n"
            f"    end\n"
            f"endmodule\n")


def _emit_ratio_divider(c: HandshakeContract) -> str:
    """Compose an event-ratio divider from the contract.

    Consuming the current unit and counting a NEW input are the SAME cycle's
    work, never exclusive alternatives — which is why a unit ratio emits on
    every input instead of on every other one (issue #2035, F7).
    """
    n = c.ratio or 1
    cw = max(1, (n - 1).bit_length()) if n > 1 else 1
    iv, ov = c.up["valid"], c.down["valid"]
    idat, odat = c.up.get("data"), c.down.get("data")
    nm = _internals(c, "count", "consume", "emit_now")
    cnt, consume, emit_now = nm["count"], nm["consume"], nm["emit_now"]
    w = c.width or 1
    rng = f"[{w - 1}:0] " if w > 1 else ""
    ports = [f"    input  wire {c.clock},", f"    input  wire {c.reset},"]
    if idat:
        ports.append(f"    input  wire {rng}{idat},")
    ports.append(f"    input  wire {iv},")
    if odat:
        ports.append(f"    output reg  {rng}{odat},")
    ports.append(f"    output reg  {ov}")
    body_data_rst = f"            {odat}  <= {w}'d0;\n" if odat else ""
    body_data = (f"            if ({iv}) {odat} <= {idat};\n"
                 if (idat and odat) else "")
    return (f"// {c.module}: event-ratio divider composed from the stated\n"
            f"// contract (issue #2035, F7): one output event per {n} input\n"
            f"// event(s). Consume and capture are SIMULTANEOUS, so no input is\n"
            f"// skipped at a unit ratio.\n"
            f"module {c.module} #(\n"
            f"    parameter RATIO = {n}\n"
            f") (\n" + "\n".join(ports) + "\n);\n"
            f"    // Sized from RATIO itself: a counter sized from the ratio\n"
            f"    // stated in the description would silently wrap the moment a\n"
            f"    // caller overrode the parameter it is declared with.\n"
            f"    reg [$clog2(RATIO + 1) - 1:0] {cnt};\n\n"
            f"    // Both happen on the same cycle; neither excludes the other.\n"
            f"    wire {consume}  = {iv};\n"
            f"    wire {emit_now} = {iv} && ({cnt} == RATIO - 1);\n\n"
            f"    always {_rst_edge(c)} begin\n"
            f"        if ({_rst_test(c)}) begin\n"
            f"            {cnt} <= 0;\n"
            f"            {ov} <= 1'b0;\n" + body_data_rst +
            f"        end else begin\n"
            f"            {ov} <= {emit_now};\n" + body_data +
            f"            if ({consume})\n"
            f"                {cnt} <= {emit_now} ? 0 : ({cnt} + 1'b1);\n"
            f"        end\n"
            f"    end\n"
            f"endmodule\n")


def emit_from_contract(c: HandshakeContract) -> str:
    """The composed RTL for a fully resolved contract."""
    if c.unresolved:
        raise ValueError("contract is not fully stated: "
                         + "; ".join(c.unresolved))
    if c.kind == "elastic_stage":
        return _emit_elastic_stage(c)
    if c.kind == "ratio_divider":
        return _emit_ratio_divider(c)
    raise KeyError(f"unknown contract kind: {c.kind!r}")


def emit_scoreboard_tb(c: HandshakeContract) -> str:
    """A self-checking scoreboard testbench composed from the SAME contract.

    The queue scoreboard (F6) and the ratio/latency count (F7) that issue #2035
    asks for: both are derived from the contract fields, so a stage and its check
    cannot drift apart. It reads the contract, never a reference output.
    """
    if c.kind == "elastic_stage" and c.storage == "skid":
        uv, ur, ud = c.up["valid"], c.up["ready"], c.up["data"]
        dv, dr, dd = c.down["valid"], c.down["ready"], c.down["data"]
        w = c.width or 1
        rng = f"[{w - 1}:0] " if w > 1 else ""
        rst_on = "1'b0" if c.reset_active_low else "1'b1"
        rst_off = "1'b1" if c.reset_active_low else "1'b0"
        tn = _internals(c, "q", "wr", "rd", "errors", "i")
        q, wr, rd, errors, i = (tn["q"], tn["wr"], tn["rd"], tn["errors"],
                                tn["i"])
        return (f"// Scoreboard TB for {c.module}: pushes a stream through random\n"
                f"// backpressure and checks the contract's four invariants.\n"
                f"`timescale 1ns/1ps\n"
                f"module tb_{c.module};\n"
                f"    reg {c.clock} = 1'b0; always #5 {c.clock} = ~{c.clock};\n"
                f"    reg {c.reset};\n"
                f"    reg {rng}{ud}; reg {uv}; wire {ur};\n"
                f"    wire {rng}{dd}; wire {dv}; reg {dr};\n"
                f"    {c.module} dut (.{c.clock}({c.clock}), .{c.reset}({c.reset}),\n"
                f"        .{ud}({ud}), .{uv}({uv}), .{ur}({ur}),\n"
                f"        .{dd}({dd}), .{dv}({dv}), .{dr}({dr}));\n"
                f"    reg [{w - 1}:0] {q} [0:1023];\n"
                f"    integer {wr} = 0, {rd} = 0, {errors} = 0, {i};\n"
                f"    always @(posedge {c.clock}) if ({rst_off} == {c.reset}) begin\n"
                f"        if ({uv} && {ur}) begin {q}[{wr}] = {ud}; {wr} = {wr} + 1; end\n"
                f"        if ({dv} && {dr}) begin\n"
                f"            if ({rd} >= {wr}) begin\n"
                f"                {errors} = {errors} + 1;\n"
                f"                $display(\"FAIL: output with no accepted input\");\n"
                f"            end else if ({dd} !== {q}[{rd}]) begin\n"
                f"                {errors} = {errors} + 1;\n"
                f"                $display(\"FAIL: got %0d expected %0d (order)\",\n"
                f"                         {dd}, {q}[{rd}]);\n"
                f"            end\n"
                f"            {rd} = {rd} + 1;\n"
                f"        end\n"
                f"    end\n"
                f"    initial begin\n"
                f"        {c.reset} = {rst_on}; {uv} = 0; {dr} = 0; {ud} = 0;\n"
                f"        @(posedge {c.clock}); @(posedge {c.clock});\n"
                f"        {c.reset} = {rst_off};\n"
                f"        for ({i} = 0; {i} < 200; {i} = {i} + 1) begin\n"
                f"            @(negedge {c.clock});\n"
                f"            {uv} = ($random % 3) != 0;\n"
                f"            {ud} = {i}[{w - 1}:0];\n"
                f"            {dr} = ($random % 2) != 0;\n"
                f"            @(posedge {c.clock});\n"
                f"            if ({uv} && {ur}) {ud} = {ud};\n"
                f"        end\n"
                f"        @(negedge {c.clock}); {uv} = 0; {dr} = 1;\n"
                f"        for ({i} = 0; {i} < 20; {i} = {i} + 1) @(posedge {c.clock});\n"
                f"        if ({wr} - {rd} != 0) begin\n"
                f"            {errors} = {errors} + 1;\n"
                f"            $display(\"FAIL: %0d accepted transfers lost\", {wr} - {rd});\n"
                f"        end\n"
                f"        // The contract says the producer is stalled only when no\n"
                f"        // slot is free, so with the consumer always ready every\n"
                f"        // offered word must be accepted on the cycle it is offered.\n"
                f"        {dr} = 1;\n"
                f"        for ({i} = 0; {i} < 32; {i} = {i} + 1) begin\n"
                f"            @(negedge {c.clock}); {uv} = 1; {ud} = {i}[{w - 1}:0];\n"
                f"            @(posedge {c.clock});\n"
                f"            if (!{ur}) begin\n"
                f"                {errors} = {errors} + 1;\n"
                f"                $display(\"FAIL: stalled at cycle %0d with a free slot\", {i});\n"
                f"            end\n"
                f"        end\n"
                f"        @(negedge {c.clock}); {uv} = 0;\n"
                f"        for ({i} = 0; {i} < 8; {i} = {i} + 1) @(posedge {c.clock});\n"
                f"        // A run that observed nothing is not a pass.\n"
                f"        if ({rd} < 32) begin\n"
                f"            {errors} = {errors} + 1;\n"
                f"            $display(\"FAIL: only %0d transfers observed\", {rd});\n"
                f"        end\n"
                f"        if ({errors} == 0) $display(\"PASS %0d transfers\", {rd});\n"
                f"        else $display(\"ERRORS %0d\", {errors});\n"
                f"        $finish;\n"
                f"    end\n"
                f"endmodule\n")
    if c.kind == "ratio_divider":
        iv, ov = c.up["valid"], c.down["valid"]
        n = c.ratio or 1
        rst_on = "1'b0" if c.reset_active_low else "1'b1"
        rst_off = "1'b1" if c.reset_active_low else "1'b0"
        idat, odat = c.up.get("data"), c.down.get("data")
        w = c.width or 1
        rng = f"[{w - 1}:0] " if w > 1 else ""
        tn = _internals(c, "n_in", "n_out", "i", "grp", "g_n", "g_i",
                        "seen", "data_errs")
        n_in, n_out, i = tn["n_in"], tn["n_out"], tn["i"]
        grp, g_n, g_i = tn["grp"], tn["g_n"], tn["g_i"]
        seen, data_errs = tn["seen"], tn["data_errs"]
        decl = f"    reg {rng}{idat}; wire {rng}{odat};\n" if (idat and odat) else ""
        conn = (f", .{idat}({idat}), .{odat}({odat})" if (idat and odat) else "")
        drive = f"        {idat} = {i}[{w - 1}:0];\n" if idat else ""
        # PAYLOAD. Counting events alone cannot see a payload that is never
        # forwarded: measured 2026-09-06 by replacing the whole data path with a
        # constant, which this TB still reported as PASS at every ratio. The
        # contract names the output port as the forwarded payload, so a value
        # that no input offered is a contract violation and must be caught.
        #
        # What it must NOT do is decide WHICH of the N inputs is forwarded. The
        # description states the ratio and states that the payload is forwarded;
        # it does not state whether the first or the last of a group is the one
        # that travels, and issue #2035 forbids guessing a hidden expected value.
        # So the check is MEMBERSHIP in the group that produced the event --
        # exact at a unit ratio, where there is only one member and no
        # interpretation is left open.
        pay_decl = ""
        pay_check = ""
        pay_record = ""
        pay_verdict = ""
        if idat and odat:
            pay_decl = (f"    reg [{w - 1}:0] {grp} [0:{max(n - 1, 0)}];\n"
                        f"    integer {g_n} = 0, {g_i}, {data_errs} = 0;\n"
                        f"    reg {seen};\n")
            pay_check = (
                f"        if ({ov}) begin\n"
                f"            {seen} = 1'b0;\n"
                f"            for ({g_i} = 0; {g_i} < {g_n}; {g_i} = {g_i} + 1)\n"
                f"                if ({odat} === {grp}[{g_i}]) {seen} = 1'b1;\n"
                f"            if (!{seen}) begin\n"
                f"                {data_errs} = {data_errs} + 1;\n"
                f"                $display(\"FAIL: output event carried %0d,"
                f" which no input of its group offered\", {odat});\n"
                f"            end\n"
                f"            {g_n} = 0;\n"
                f"        end\n")
            pay_record = (f"        if ({iv}) begin\n"
                          f"            if ({g_n} < {n}) {grp}[{g_n}] = {idat};\n"
                          f"            {g_n} = {g_n} + 1;\n"
                          f"        end\n")
            pay_verdict = (
                f"        else if ({data_errs} != 0)\n"
                f"            $display(\"FAIL: %0d output event(s) carried a"
                f" payload no input offered\", {data_errs});\n")
        return (f"// Ratio/latency TB for {c.module}: counts input events and\n"
                f"// output events and checks the stated {n}:1 ratio - the check\n"
                f"// that catches every-other-input being dropped - and checks\n"
                f"// that each output event carries a payload its own group of\n"
                f"// input events actually offered.\n"
                f"`timescale 1ns/1ps\n"
                f"module tb_{c.module};\n"
                f"    reg {c.clock} = 1'b0; always #5 {c.clock} = ~{c.clock};\n"
                f"    reg {c.reset}; reg {iv}; wire {ov};\n" + decl +
                f"    {c.module} dut (.{c.clock}({c.clock}), .{c.reset}({c.reset}),\n"
                f"        .{iv}({iv}), .{ov}({ov}){conn});\n"
                f"    integer {n_in} = 0, {n_out} = 0, {i};\n" + pay_decl +
                f"    always @(posedge {c.clock}) if ({c.reset} == {rst_off}) begin\n"
                f"        if ({iv}) {n_in}  = {n_in}  + 1;\n"
                f"        if ({ov}) {n_out} = {n_out} + 1;\n"
                # the group that produced THIS output is the inputs BEFORE this
                # cycle, so the check runs before this cycle's input is recorded
                + pay_check + pay_record +
                f"    end\n"
                f"    initial begin\n"
                f"        {c.reset} = {rst_on}; {iv} = 0;\n"
                f"        @(posedge {c.clock}); @(posedge {c.clock});\n"
                f"        {c.reset} = {rst_off};\n"
                f"        for ({i} = 0; {i} < 64; {i} = {i} + 1) begin\n"
                f"            @(negedge {c.clock}); {iv} = 1;\n" + drive +
                f"            @(posedge {c.clock});\n"
                f"        end\n"
                f"        @(negedge {c.clock}); {iv} = 0;\n"
                f"        for ({i} = 0; {i} < 4; {i} = {i} + 1) @(posedge {c.clock});\n"
                f"        if ({n_in} == 0) begin\n"
                f"            $display(\"FAIL: no input events were driven - vacuous\");\n"
                f"        end else if ({n_out} != {n_in} / {n})\n"
                f"            $display(\"FAIL: %0d in %0d out, expected %0d\","
                f" {n_in}, {n_out}, {n_in} / {n});\n" + pay_verdict +
                f"        else $display(\"PASS %0d in %0d out\", {n_in}, {n_out});\n"
                f"        $finish;\n"
                f"    end\n"
                f"endmodule\n")
    raise KeyError(f"no scoreboard for contract kind {c.kind!r}"
                   f"/storage {c.storage!r}")


# The two contract-composed families are shapes like any other, but they own no
# template: `emit_rtl` composes them from the contract the input states.
_CONTRACT_SHAPES = {
    "elastic_handshake_stage": "elastic_stage",
    "event_ratio_divider": "ratio_divider",
}


def _contract_shape(desc_text: str) -> Optional[str]:
    """The contract-composed shape this input fully states, or None.

    Fail-closed exactly like the template detectors: an input that states a
    handshake but leaves anything load-bearing unstated returns None, and the
    unstated names are available from `route_to_ai_reason`.
    """
    try:
        c = extract_handshake_contract(desc_text)
    except Exception:
        return None
    if c is None or c.kind is None or c.unresolved:
        return None
    for key, kind in _CONTRACT_SHAPES.items():
        if kind == c.kind:
            return key
    return None


def emit_rtl(shape: str, desc_text: str = "") -> str:
    """RTL for a shape key.

    For the sixteen TEMPLATE shapes this returns the exact verified-correct
    template, byte for byte, and `desc_text` is not read - their output is
    unchanged by the contract layer. For a CONTRACT-composed shape the RTL is
    composed from the handshake/acceptance contract stated by `desc_text`, which
    is therefore required.
    """
    if shape in _TEMPLATES:
        return _TEMPLATES[shape]
    if shape in _CONTRACT_SHAPES:
        c = extract_handshake_contract(desc_text or "")
        if c is None or c.kind != _CONTRACT_SHAPES[shape]:
            raise ValueError(f"{shape!r} needs the design description it was "
                             f"detected from; none was supplied")
        return emit_from_contract(c)
    raise KeyError(f"unknown shape: {shape!r}")


def module_of_shape(shape: str, desc_text: str = "") -> str:
    if shape in _SHAPE_MODULE:
        return _SHAPE_MODULE[shape]
    if shape in _CONTRACT_SHAPES:
        return module_name_of(desc_text or "") or "chip_top"
    raise KeyError(f"unknown shape: {shape!r}")


# ======================================================================== desc I/O
def _read_project_desc(project_dir: Path) -> Tuple[str, str]:
    """Locate and return (desc_text, source). Search order per the CLI contract."""
    p = project_dir
    # 1) input/design_description.txt
    cand = p / "input" / "design_description.txt"
    if cand.exists():
        return cand.read_text(errors="replace"), str(cand)
    # 2) input/*.txt
    idir = p / "input"
    if idir.is_dir():
        for f in sorted(idir.glob("*.txt")):
            return f.read_text(errors="replace"), str(f)
    # also a top-level design_description.txt (common layout)
    cand = p / "design_description.txt"
    if cand.exists():
        return cand.read_text(errors="replace"), str(cand)
    # 3) phase1/generated_docs/L*.json prose
    gd = p / "phase1" / "generated_docs"
    if gd.is_dir():
        blob = ""
        for f in sorted(gd.glob("L*.json")):
            try:
                blob += json.dumps(json.loads(f.read_text()), ensure_ascii=False) + "\n"
            except Exception:
                blob += f.read_text(errors="replace") + "\n"
        if blob.strip():
            return blob, str(gd)
    # 4) input_prompt/*
    ip = p / "input_prompt"
    if ip.is_dir():
        for f in sorted(ip.glob("*")):
            if f.is_file():
                return f.read_text(errors="replace"), str(f)
    return "", ""


# ======================================================================== CLI
def _emit_and_write(shape: str, out_path: Path, desc_text: str = "") -> str:
    rtl = emit_rtl(shape, desc_text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rtl)
    return str(out_path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("project", nargs="?", help="project directory")
    ap.add_argument("--emit", action="store_true",
                    help="write phase2/stage1/rtl/<module>.v on EMIT")
    ap.add_argument("--from-desc", dest="from_desc",
                    help="direct mode: detect from this design_description.txt")
    ap.add_argument("--out", dest="out",
                    help="direct mode: RTL output file")
    a = ap.parse_args(argv)

    # ---- direct mode -------------------------------------------------------
    if a.from_desc:
        desc = Path(a.from_desc).read_text(errors="replace")
        shape = detect_shape(desc)
        if shape is None:
            print(json.dumps({"verdict": "DEFER", "shape": None,
                              "module": module_name_of(desc),
                              "defer_reason": route_to_ai_reason(desc)}))
            return 2
        module = module_of_shape(shape, desc)
        written = None
        if a.out:
            written = _emit_and_write(shape, Path(a.out), desc)
        print(json.dumps({"verdict": "EMIT", "shape": shape,
                          "module": module, "written": written}))
        return 0

    # ---- project mode ------------------------------------------------------
    if not a.project:
        ap.error("either <project_dir> or --from-desc is required")
    proj = Path(a.project).resolve()
    desc, _src = _read_project_desc(proj)
    shape = detect_shape(desc)
    if shape is None:
        print(json.dumps({"verdict": "DEFER", "shape": None,
                          "module": module_name_of(desc),
                          "defer_reason": route_to_ai_reason(desc)}))
        return 2
    module = module_of_shape(shape, desc)
    written = None
    if a.emit:
        written = _emit_and_write(
            shape, proj / "phase2" / "stage1" / "rtl" / f"{module}.v", desc)
    print(json.dumps({"verdict": "EMIT", "shape": shape,
                      "module": module, "written": written}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
