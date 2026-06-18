"""ORGANIC-20260618 — PROPER barrel_shifter absorption: a §4.05-safe shift-vs-
rotate EMIT-BLOCK on the Shape-B SOLE EMIT PATH (`shape_b_sample_export.py`),
plus the baseline-false-fire fix in `spec_conformance_check._spec_describes_
plain_shifter`.

PATTERN
-------
The RTLLM `barrel_shifter` round-20 sample implements a logical shift AS a
ROTATE (`{in[3:0], in[7:4]}` …). The spec ("shifts or rotates") binds to a
LOGICAL shift with zero-fill (lessons corpus), so the sample FAILS the hidden TB
(logical 255>>7 == 1 vs rotate == 255). The Shape-C path already gates this
(`shift-implemented-as-rotate`, #784/#790/#20), but the gate was NEVER wired into
the Shape-B sole emit path — a gate that never fires on the emit path is dead
(#529 class). Naively wiring it in was §4.05-UNSAFE: the BASELINE
`_spec_describes_plain_shifter` WRONGLY ARMED on two CORRECT RTLLM designs whose
specs legitimately describe a CYCLIC / WRAP-AROUND behaviour —
  • ring_counter      — "cyclic state sequences … wraps around to the LSB,
                         creating a cyclic sequence" (golden `{state[6:0],
                         state[7]}`)
  • parallel2serial   — "the most significant bit shifted to the least
                         significant bit" (golden `{data[2:0], data[3]}`)
Both PASS their own hidden TBs → CORRECT → must NOT be blocked.

FIX (two §4.05-safe parts)
--------------------------
Part A — `spec_conformance_check`: widen the rotate/cyclic DISARM vocabulary
  (bare cyclic/circular/rotational/ring-counter + "wrap(s)? around", and the
  STRUCTURAL MSB↔LSB-wrap prose signature) so a cyclic/wrap-around spec DISARMS
  `_spec_describes_plain_shifter`. A plain-shifter spec stays ARMED; a "shift OR
  rotate" disjunction spec (barrel_shifter) keeps `both_offered=True` → STAYS
  ARMED (the #784/#790/#20 behaviour is byte-for-byte preserved).
Part B — `shape_b_sample_export`: wire the (now §4.05-safe) shift-vs-rotate
  emit-block into `export()`, reusing the detectors VERBATIM, reading ONLY the
  spec/prompt prose + the RTL (NEVER the hidden testbench).

POSITIVE — barrel_shifter rotate-as-shift sample → emit-BLOCKED.
§4.05 NEGATIVES (zero false-block):
  * barrel_shifter logical-shift GOLDEN → EMIT.
  * ring_counter / parallel2serial (cyclic specs, rotate-concat RTL) → EMIT,
    on BOTH the Shape-B emit path AND the Shape-C gate.
  * a genuine plain `right_shifter` spec stays ARMED (the gate is not declawed).
  * a dual-mode `shift OR rotate` mux design (logical-shift + rotate branches) →
    EMIT (the disjunction carve-out).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import shape_b_sample_export as sbx  # noqa: E402
import spec_conformance_check as scc  # noqa: E402


# ── real repro fixtures (verbatim shapes from the corpus) ───────────────────
SPEC_BARREL = """Module name: barrel_shifter
Function:
    A barrel shifter for rotating bits efficiently. This 8-bit barrel shifter
    takes an 8-bit input and shifts or rotates the bits based on a 3-bit
    control signal.
"""
SPEC_RING = """Implement a module of an 8-bit ring counter for cyclic state sequences.
Cycling Behavior: On each rising edge of the clock signal, the 1 shifts to the
next bit in the sequence, and after reaching the most significant bit (MSB), it
wraps around to the LSB, creating a cyclic sequence.
"""
SPEC_P2S = """Implement a module for parallel-to-serial conversion (MSB to LSB).
Otherwise, the module increments the counter, sets valid to 0, and shifts the
data register one bit to the left, with the most significant bit shifted to the
least significant bit.
"""
SPEC_RIGHT = """Implement a right shifter. On each rising edge the module shifts
the contents of the q register to the right by one bit and inserts the new input
bit d into the most significant position of the register.
"""

RTL_BARREL_ROTATE = """module barrel_shifter (
    input  wire [7:0] in, input wire [2:0] ctrl, output wire [7:0] out);
    wire [7:0] s4, s2;
    assign s4  = ctrl[2] ? {in[3:0],  in[7:4]} : in;
    assign s2  = ctrl[1] ? {s4[1:0],  s4[7:2]} : s4;
    assign out = ctrl[0] ? {s2[0],    s2[7:1]} : s2;
endmodule
"""
RTL_BARREL_SHIFT = """module barrel_shifter (
    input  wire [7:0] in, input wire [2:0] ctrl, output wire [7:0] out);
    wire [7:0] s4, s2;
    assign s4  = ctrl[2] ? {4'b0, in[7:4]}        : in;
    assign s2  = ctrl[1] ? {2'b0, s4[7:2]}        : s4;
    assign out = ctrl[0] ? {1'b0, s2[7:1]}        : s2;
endmodule
"""
RTL_RING = """module ring_counter (
    input wire clk, input wire reset, output reg [7:0] out);
    always @(posedge clk or posedge reset)
        if (reset) out <= 8'b0000_0001;
        else       out <= {out[6:0], out[7]};
endmodule
"""
RTL_P2S = """module parallel2serial (
    input wire clk, input wire rst_n, input wire [3:0] d,
    output wire valid_out, output wire dout);
    reg [3:0] data; reg [1:0] cnt; reg valid;
    assign dout = data[3]; assign valid_out = valid;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin data<=0; cnt<=0; valid<=0; end
        else if (cnt==2'd3) begin data<=d; cnt<=0; valid<=1; end
        else begin cnt<=cnt+1; valid<=0; data <= {data[2:0], data[3]}; end
endmodule
"""
# dual-mode: a genuine shift OR rotate mux (logical-shift branch + rotate branch)
RTL_BARREL_DUAL = """module barrel_shifter (
    input  wire [7:0] in, input wire [2:0] ctrl, input wire mode,
    output wire [7:0] out);
    wire [7:0] rot = {in[0], in[7:1]};
    wire [7:0] shf = in >> 1;
    assign out = mode ? rot : shf;
endmodule
"""


# ─────────────────────────── Part A unit tests ─────────────────────────────
def test_partA_plain_shifter_stays_armed():
    # a "shift OR rotate" disjunction spec stays ARMED (both_offered).
    assert scc._spec_describes_plain_shifter(SPEC_BARREL) is True
    # a genuine plain right-shifter spec stays ARMED — the gate is not declawed.
    assert scc._spec_describes_plain_shifter(SPEC_RIGHT) is True


def test_partA_cyclic_specs_disarm():
    # ring_counter / parallel2serial cyclic / wrap-around specs DISARM (the
    # baseline false-fire fix).
    assert scc._spec_describes_plain_shifter(SPEC_RING) is False
    assert scc._spec_describes_plain_shifter(SPEC_P2S) is False


def test_partA_disarm_predicate():
    assert scc._spec_describes_rotate_or_cyclic(SPEC_RING) is True
    assert scc._spec_describes_rotate_or_cyclic(SPEC_P2S) is True
    assert scc._spec_describes_rotate_or_cyclic(SPEC_RIGHT) is False


def test_partA_shapeC_gate_blocks_rotate_as_shift():
    # barrel rotate-as-shift sample → Shape-C gate FAILs.
    rc, findings = _run_shapeC(SPEC_BARREL, RTL_BARREL_ROTATE)
    assert rc == 1
    assert any(f.rule == "shift-implemented-as-rotate" for f in findings)


def test_partA_shapeC_gate_emits_correct_designs():
    # the §4.05 negatives — every correct design PASSes the Shape-C gate.
    for spec, rtl in ((SPEC_BARREL, RTL_BARREL_SHIFT),
                      (SPEC_RING, RTL_RING),
                      (SPEC_P2S, RTL_P2S),
                      (SPEC_BARREL, RTL_BARREL_DUAL)):
        rc, findings = _run_shapeC(spec, rtl)
        assert not any(f.rule == "shift-implemented-as-rotate" for f in findings)
        assert rc == 0


# ─────────────────────────── Part B unit tests ─────────────────────────────
def test_partB_emit_block_positive():
    # barrel rotate-as-shift sample → emit-BLOCK.
    reason = sbx.shift_rotate_emit_block(SPEC_BARREL, RTL_BARREL_ROTATE,
                                         "barrel_shifter")
    assert reason is not None
    assert "shift-implemented-as-rotate" in reason


def test_partB_emit_block_negatives_emit():
    # every correct design EMITs (None == no block).
    assert sbx.shift_rotate_emit_block(SPEC_BARREL, RTL_BARREL_SHIFT,
                                       "barrel_shifter") is None
    assert sbx.shift_rotate_emit_block(SPEC_RING, RTL_RING,
                                       "ring_counter") is None
    assert sbx.shift_rotate_emit_block(SPEC_P2S, RTL_P2S,
                                       "parallel2serial") is None
    # dual-mode shift OR rotate mux → EMIT (the disjunction carve-out).
    assert sbx.shift_rotate_emit_block(SPEC_BARREL, RTL_BARREL_DUAL,
                                       "barrel_shifter") is None


def test_partB_emit_block_failsafe_no_spec():
    # no prompt → fail-safe EMIT (the emit-block stays disarmed).
    assert sbx.shift_rotate_emit_block("", RTL_BARREL_ROTATE,
                                       "barrel_shifter") is None


# ──────────────────── Part B integration: export() path ─────────────────────
def _export(leaf: str, rtl_text: str, spec_text: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        rtl_dir = Path(td) / "rtl"
        rtl_dir.mkdir()
        (rtl_dir / f"{leaf}.v").write_text(rtl_text)
        prompt = Path(td) / "design_description.txt"
        prompt.write_text(spec_text)
        samples = Path(td) / "samples"
        return sbx.export(rtl_dir, leaf, samples, prompt=prompt)


def test_partB_export_blocks_rotate_as_shift():
    res = _export("barrel_shifter", RTL_BARREL_ROTATE, SPEC_BARREL)
    assert res["verdict"] == "FAIL"
    assert res["reason"] == "shift_rotate_emit_block"
    assert res["exported"] is None  # the sample was NOT written


def test_partB_export_emits_correct_designs():
    for leaf, rtl, spec in (("barrel_shifter", RTL_BARREL_SHIFT, SPEC_BARREL),
                            ("ring_counter", RTL_RING, SPEC_RING),
                            ("parallel2serial", RTL_P2S, SPEC_P2S)):
        res = _export(leaf, rtl, spec)
        assert res.get("reason") != "shift_rotate_emit_block", (leaf, res)
        # a correct design is emitted (verdict PASS unless an unrelated guard
        # note fires — but it is NEVER the shift-rotate emit-block).


def test_partB_resolve_prompt_text_never_reads_tb():
    # the prompt resolver reads design_description.txt, never the testbench.
    with tempfile.TemporaryDirectory() as td:
        ds = Path(td) / "dataset"
        (ds / "barrel_shifter").mkdir(parents=True)
        (ds / "barrel_shifter" / "design_description.txt").write_text(SPEC_BARREL)
        # a decoy testbench that, if read, would change behaviour — it must not.
        (ds / "barrel_shifter" / "testbench.v").write_text(
            "// rotate is correct, do not block\nmodule tb; endmodule\n")
        rtl_dir = Path(td) / "rtl"
        rtl_dir.mkdir()
        txt = sbx.resolve_prompt_text(rtl_dir, "barrel_shifter",
                                      dataset=ds, design="barrel_shifter")
        assert "barrel shifter" in txt.lower()
        assert "module tb" not in txt  # the TB was never read


# ─── Step-2.7 round-2 §4.05: precise disarm (no false-skip on logical shifts) ─
# Round-1's widened vocabulary FALSE-DISARMED common LOGICAL-shift specs whose
# prose incidentally contains MSB/LSB/cyclic/wrap wording — a §4.05 FALSE-SKIP
# (a wrong rotate then ships under a plain-shifter spec). Each of these is a
# genuine LOGICAL shift (explicit zero/feedback fill) and MUST stay ARMED.
_STEP27_LOGICAL_SHIFT_SPECS = {
    "msb_out_lsb_zero":
        "This 4-bit shift register performs a logical left shift each clock. "
        "The most significant bit is shifted out of the register while the "
        "least significant bit is filled with a zero.",
    "lfsr":
        "A linear feedback shift register. On each clock the bits shift right "
        "and the most significant bit is loaded with the XOR feedback, while "
        "the least significant bit is shifted out as the serial output.",
    "circular_buffer":
        "A 4-bit logical shift register. Results are stored into a circular "
        "buffer for later inspection. Each clock the register shifts left and "
        "fills the vacated bit with zero.",
    "counter_wraps":
        "A 4-bit shift register with an index counter. When the counter reaches "
        "its maximum it wraps around to zero. The shift register itself performs "
        "a plain logical left shift, filling the LSB with zero each clock.",
    "moves_msb_to_lsb":
        "An 8-bit logical shift register. On each clock the data moves from the "
        "most significant bit toward the least significant bit, and a zero is "
        "shifted into the MSB position.",
    # round-2 residuals: a plain logical shift that names a rotate/cyclic token
    # WITHOUT an explicit fill — caught by the logical-shift / discard / negation
    # veto (these EVADED the round-1 explicit-fill-only veto).
    "unlike_ring_counter":
        "Design an 8-bit logical right shift register. Unlike a ring counter, "
        "the shifted-out bit is discarded rather than recirculated.",
    "left_shift_travel":
        "A shift register performing a logical left shift each clock, where the "
        "least significant bit is shifted into the most significant bit across "
        "successive clocks.",
    "circular_buffer_pointer_wrap":
        "A 4-bit logical left shift register feeding a circular buffer; the "
        "buffer pointer wraps around to bit 0 after the last entry.",
    # round-3 residual: a cross-register MSB->LSB side-feed (to a DIFFERENT
    # register) is not a self-wrap; zero-fill phrased as "set to 0".
    "crc_cross_register_sidefeed":
        "An 8-bit shift register; bits shift left and the LSB is set to 0. The "
        "most significant bit is carried to the least significant bit of the "
        "CRC register.",
    # round-4: a CONTROL-PATH pointer/counter "wraps back" while the DATA path is
    # an explicit zero-fill logical shift — must stay ARMED (the bare wrap-back
    # arm was removed).
    "buffer_pointer_wraps_back":
        "A logical shift register feeding a circular buffer whose write pointer "
        "wraps back to index zero; the data word itself is shifted with zero "
        "fill.",
    "fifo_addr_loops_back":
        "An 8-bit logical right shift with zero fill; a separate FIFO address "
        "counter loops back to zero after the last slot.",
    # round-5: a plain SIPO whose MSB and LSB go to DIFFERENT destinations
    # across a clause boundary ("...into the output register AND the least
    # significant bit is loaded with d") is NOT a self-wrap — the tempered
    # to/into destination gap (stops at and/or/clause) keeps it ARMED.
    "sipo_msb_lsb_different_dests":
        "Module shifter: an 8-bit shift register. The most significant bit is "
        "shifted into the output register and the least significant bit is "
        "loaded with d. The register shifts left by one each clock.",
    "sipo_serial_dests":
        "On each clock the most significant bit is shifted into serial_out, and "
        "the least significant bit receives serial_in.",
}

# round-3: genuine rotate/cyclic designs whose prose contains discard/negation/
# logical-shift tokens must STILL DISARM (the polarity-blind round-3 veto wrongly
# false-fired and emit-blocked these CORRECT ring counters / recirculators).
_STEP27_GENUINE_ROTATE_SPECS = {
    "ring_counter_nothing_dropped":
        "An 8-bit ring counter: each clock it shifts and the last bit feeds the "
        "first; nothing is dropped.",
    "ring_counter_logical_wrap":
        "A ring counter implemented as a logical shift of a one-hot vector that "
        "wraps the MSB back to the LSB.",
    "serializer_recirculated":
        "A serializer where the most significant bit is shifted to the least "
        "significant bit, not discarded but recirculated.",
    # round-4: a contrastive intro whose negation targets a DIFFERENT device must
    # NOT suppress the ring-counter disarm (adjacency-anchored polarity).
    "unlike_lfsr_ring":
        "Unlike a LFSR, the ring counter shifts the hot bit around the register "
        "each clock.",
    "rather_than_binary_ring":
        "Rather than a binary counter, a ring counter shifts a one-hot token "
        "around its bits.",
    "no_decoder_ring":
        "No decoder is needed: the ring counter shifts the active bit "
        "cyclically each clock.",
}


@pytest.mark.parametrize("key", list(_STEP27_GENUINE_ROTATE_SPECS))
def test_partA_step27_genuine_rotate_with_neg_tokens_disarms_no_false_fire(key):
    assert scc._spec_describes_plain_shifter(
        _STEP27_GENUINE_ROTATE_SPECS[key]) is False


@pytest.mark.parametrize("key", list(_STEP27_LOGICAL_SHIFT_SPECS))
def test_partA_step27_logical_shift_prose_stays_armed_no_leak(key):
    assert scc._spec_describes_plain_shifter(
        _STEP27_LOGICAL_SHIFT_SPECS[key]) is True


def test_partA_step27_gate_fires_on_rotate_under_logical_shift_spec():
    # end-to-end: a rotate RTL under a logical-shift spec is still BLOCKED.
    rtl = ("module m(input [7:0] din, output [7:0] dout);\n"
           "  assign dout = {din[6:0], din[7]};\n"
           "endmodule\n")
    rc, findings = _run_shapeC(_STEP27_LOGICAL_SHIFT_SPECS["lfsr"], rtl)
    assert rc == 1
    assert any(f.rule == "shift-implemented-as-rotate" for f in findings)


# ─── Step-2.7 round-2: Part B integration + blindness ────────────────────────
def test_partB_step27_project_only_invocation_blocks(tmp_path):
    # integration HIGH: the DOCUMENTED --project-only invocation (no
    # --prompt/--dataset) must resolve the runner-staged prompt
    # (input/phase1_prompt.md) so the gate FIRES — else it is a dead #529 gate.
    project = tmp_path / "work" / "shifter"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "shifter.v").write_text(
        "module shifter(input [7:0] din, input [2:0] shamt, output [7:0] dout);\n"
        "  assign dout = (din >> shamt) | (din << (8-shamt));\n"
        "endmodule\n")
    (project / "input").mkdir()
    (project / "input" / "phase1_prompt.md").write_text(
        "Design module shifter that performs a logical right shift of the 8-bit "
        "input din by shamt bits. The shifted-in bits are zero.\n")
    samples = tmp_path / "samples"
    res = sbx.export(rtl_dir, "shifter", samples, spec_module="shifter",
                     project=project)
    assert res["verdict"] == "FAIL"
    assert res["reason"] == "shift_rotate_emit_block"
    assert not (samples / "shifter.v").exists()


def test_partB_step27_readme_not_read_blindness():
    # blindness MED: README.md (too generic — may carry TB/golden text) is no
    # longer read; the runner-staged prompt names ARE read.
    assert "README.md" not in sbx._PROMPT_FILENAMES
    assert "phase1_prompt.md" in sbx._PROMPT_FILENAMES
    assert "design_description.md" in sbx._PROMPT_FILENAMES


# ─────────────────────────────── helpers ───────────────────────────────────
def _run_shapeC(spec_text: str, rtl_text: str):
    """Drive the Shape-C `spec_conformance_check.check` on a spec/RTL pair and
    return (exit-code-equivalent, findings)."""
    from _specrtl_common import (classify_rtl_resets, parse_rtl_ports,
                                 strip_comments, extract_spec_contract)
    src = strip_comments(rtl_text)
    name, ports = parse_rtl_ports(src, None)
    spec = extract_spec_contract(spec_text, is_json=False)
    resets = classify_rtl_resets(src)
    findings = scc.check(spec, name, ports, resets,
                         scc._rtl_output_is_registered(src, ports),
                         "<rtl>", rtl_body=src, spec_text=spec_text)
    rc = 1 if any(f.severity == "ERROR" for f in findings) else 0
    return rc, findings


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
