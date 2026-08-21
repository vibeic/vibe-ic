"""v1.0.93 #784 — program-first escalation of two prose "MANDATORY pre-emit
self-TB" discriminators into DETERMINISTIC emit-asserts.

ORGANIC-20260617-escalate-prose-mandatory-discriminator-selftbs-to-deterministic-
emit-gates (program-first escalation of #718/#733/#741/#776). The lessons corpus
already PRESCRIBES the discriminators, but a fresh clean-room author reads the
lesson, cites it, then overrides it via §4-E round after round — advisory prose
cannot reach zero. This mechanizes the two discriminators the lessons name as
deterministic emit-asserts the author cannot override:

  (1) shift-implemented-as-rotate  — spec describes a SHIFTER (not explicitly
      rotate-only) but the RTL is an unambiguous barrel-ROTATE wrap. The prose
      "'shifts or rotates' is NOT rotate-only → logical shift" + the mandatory
      all-ones>>max self-TB were prose-only.
  (2) waveform-peak-hold-dropped   — spec requires a triangle/ramp peak-HOLD but
      the RTL drops it (immediate direction toggle at the extreme, no
      hold/dwell state). The prose "keep peak-hold unless spec forbids" was
      prose-only.

ZERO-FALSE-FIRE is the binding constraint (these BLOCK emit; a false block
breaks a CORRECT sample). Every §4.05 negative is pinned below. Both rule names
are asserted present in gates_atomic._BLOCKING_CONFORMANCE_RULES.

chip-AGNOSTIC: fixtures use generic TopModule / din / dout / wave shapes only.
"""
import json
import shutil
import pytest
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import (extract_spec_contract, parse_rtl_ports,  # noqa: E402
                             strip_comments)

#: The repo's existing tool gate. Without it this module raises
#: FileNotFoundError on a host that lacks the tool, instead of
#: disclosing a skip. The crash is NOT in this module — it is inside
#: `benchmark/score_iverilog_tb.py`, which these tests invoke — so
#: the gate names the tool the CALL CHAIN needs, not a binary this
#: file mentions.
_HAVE_TOOLS = bool(shutil.which("iverilog"))

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"
PROGRAM = Path(__file__).resolve().parent.parent / "spec_conformance_check.py"

RULE_SHIFT = "shift-implemented-as-rotate"
RULE_HOLD = "waveform-peak-hold-dropped"


def _findings(spec_text: str, rtl: str, rule: str = None):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if (rule is None or f.rule == rule)]


# ===========================================================================
# (1) shift-implemented-as-rotate
# ===========================================================================
_SHIFT_SPEC = ("Build an 8-bit barrel SHIFTER. The shift amount arrives on "
               "ctrl; shift the input by ctrl positions.\n\n"
               " - input  [7:0] din\n - input  [2:0] ctrl\n"
               " - output [7:0] dout\n")

# unambiguous wrap-around rotate via OR of two OPPOSITE shifts of one signal
_ROTATE_OR_RTL = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
                  "                 output [7:0] dout);\n"
                  "  assign dout = (din >> ctrl) | (din << (8-ctrl));\n"
                  "endmodule\n")
# unambiguous wrap-around rotate via a fill-free same-vector concat
_ROTATE_CONCAT_RTL = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
                      "                 output reg [7:0] dout);\n"
                      "  always @* dout = {din[0], din[7:1]};\n"
                      "endmodule\n")
# correct LOGICAL shift (zero-fill) — must NEVER fire
_LOGICAL_SHIFT_RTL = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
                      "                 output [7:0] dout);\n"
                      "  assign dout = din >> ctrl;\n"
                      "endmodule\n")
# correct logical shift expressed as a ZERO-fill concat — must NEVER fire
_ZEROFILL_CONCAT_RTL = ("module TopModule(input [7:0] din,\n"
                        "                 output reg [7:0] dout);\n"
                        "  always @* dout = {din[6:0], 1'b0};\n"
                        "endmodule\n")


def test_shift_rule_fires_on_or_rotate_under_shift_spec():
    fs = _findings(_SHIFT_SPEC, _ROTATE_OR_RTL, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs
    assert "ROTATE" in fs[0].message
    assert "all-ones" in fs[0].message  # the named mandatory self-TB


def test_shift_rule_fires_on_concat_rotate_under_shift_spec():
    fs = _findings(_SHIFT_SPEC, _ROTATE_CONCAT_RTL, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


# §4.05 negatives — must NOT fire
def test_shift_rule_silent_on_correct_logical_shift():
    assert _findings(_SHIFT_SPEC, _LOGICAL_SHIFT_RTL, RULE_SHIFT) == []


def test_shift_rule_silent_on_zerofill_concat_shift():
    assert _findings(_SHIFT_SPEC, _ZEROFILL_CONCAT_RTL, RULE_SHIFT) == []


def test_shift_rule_silent_on_explicit_rotate_only_spec():
    # §4.05: a genuine rotate-only spec + rotate RTL is CORRECT — disarmed
    rot_spec = ("Build an 8-bit barrel ROTATOR: rotate the input left by ctrl "
                "positions (a circular shift — the bits wrap around).\n\n"
                " - input  [7:0] din\n - input  [2:0] ctrl\n"
                " - output [7:0] dout\n")
    assert _findings(rot_spec, _ROTATE_OR_RTL, RULE_SHIFT) == []
    assert _findings(rot_spec, _ROTATE_CONCAT_RTL, RULE_SHIFT) == []


def test_shift_or_rotates_disjunction_spec_BLOCKS_rotate_rtl():
    # ORGANIC-20260618 (RTLLM round-19 barrel_shifter): a spec that OFFERS BOTH
    # operations in a disjunction ("shifts or rotates") is NOT rotate-only — the
    # lessons corpus binds it to a LOGICAL shift with zero-fill. A rotate RTL
    # under such a spec is WRONG and MUST be blocked. (Supersedes the prior
    # conservative under-firing pin, which let the wrong rotate design pass the
    # hidden right-shift TB.)
    spec = _SHIFT_SPEC.replace("Build an 8-bit barrel SHIFTER",
                               "Build an 8-bit unit that shifts or rotates")
    fs = _findings(spec, _ROTATE_OR_RTL, RULE_SHIFT)
    assert any(f.rule == "shift-implemented-as-rotate" for f in fs), fs


def test_shift_rule_still_silent_on_rotate_ONLY_spec_no_leak():
    # §4.05 NO-LEAK: a GENUINE rotate-only spec (rotate / circular present, NO
    # shift-or-rotate disjunction) still disarms — a correct rotate design must
    # NOT be false-blocked.
    rot_only = ("Build an 8-bit barrel ROTATOR: rotate the input left by ctrl "
                "positions (a circular shift — the bits wrap around).\n\n"
                " - input  [7:0] din\n - input  [2:0] ctrl\n"
                " - output [7:0] dout\n")
    assert _findings(rot_only, _ROTATE_OR_RTL, RULE_SHIFT) == []


def test_shift_or_rotates_disjunction_silent_on_correct_logical_shift():
    # §4.05 NO-FALSE-BLOCK: the SAME "shifts or rotates" spec with a CORRECT
    # logical-shift RTL (zero-fill) must stay silent — only the rotate form fires.
    spec = _SHIFT_SPEC.replace("Build an 8-bit barrel SHIFTER",
                               "Build an 8-bit unit that shifts or rotates")
    good = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
            "                 output [7:0] dout);\n"
            "  assign dout = din >> ctrl;\n"
            "endmodule\n")
    assert _findings(spec, good, RULE_SHIFT) == []


def test_shift_rule_silent_on_or_with_nonshift_mask():
    # logical shift OR-ed with a non-shift operand is NOT a wrap rotate
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
           "                 input [7:0] mask, output [7:0] dout);\n"
           "  assign dout = (din << ctrl) | mask;\n"
           "endmodule\n")
    assert _findings(_SHIFT_SPEC, rtl, RULE_SHIFT) == []


def test_shift_rule_silent_on_same_direction_or():
    # two SAME-direction shifts OR-ed (a funnel build) is NOT a rotate
    rtl = ("module TopModule(input [7:0] a, input [7:0] b,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = (a << 2) | (b << 4);\n"
           "endmodule\n")
    assert _findings(_SHIFT_SPEC, rtl, RULE_SHIFT) == []


# ---------------------------------------------------------------------------
# §4.05 false-fire fix (ORGANIC-20260618 round-2 — Step-2.7 on the re-arm PR):
# a "shift OR rotate" spec describes a MODE-SELECTABLE unit; its CORRECT
# implementation co-presents a logical-shift branch AND a rotate branch, mux-
# selected. The re-arm must NOT false-block that dual-mode design — only a
# rotate-ONLY RTL (no co-present logical-shift mux) under the disjunction fires.
# ---------------------------------------------------------------------------
_BOTH_OFFERED_SPEC = _SHIFT_SPEC.replace(
    "Build an 8-bit barrel SHIFTER",
    "Build an 8-bit unit that shifts or rotates, selected by op_mode")

# CORRECT dual-mode barrel shifter: op_mode picks logical-shift vs left-rotate.
# (iverilog-verified shape from the reviewer: shift branch `din >> ctrl`, rotate
# branch `(din >> ctrl) | (din << (8-ctrl))`, ternary-muxed by op_mode.)
_DUAL_MODE_TERNARY_RTL = (
    "module TopModule(input [7:0] din, input [2:0] ctrl, input op_mode,\n"
    "                 output [7:0] dout);\n"
    "  wire [7:0] shifted = din >> ctrl;\n"
    "  wire [7:0] rotated = (din >> ctrl) | (din << (8 - ctrl));\n"
    "  assign dout = op_mode ? rotated : shifted;\n"
    "endmodule\n")

# same dual-mode design expressed with a case mux instead of a ternary
_DUAL_MODE_CASE_RTL = (
    "module TopModule(input [7:0] din, input [2:0] ctrl, input op_mode,\n"
    "                 output reg [7:0] dout);\n"
    "  wire [7:0] shifted = din << ctrl;\n"
    "  wire [7:0] rotated = (din << ctrl) | (din >> (8 - ctrl));\n"
    "  always @* case (op_mode)\n"
    "    1'b0: dout = shifted;\n"
    "    default: dout = rotated;\n"
    "  endcase\n"
    "endmodule\n")


def test_disjunction_silent_on_correct_DUAL_MODE_ternary_no_false_block():
    # §4.05 NO-FALSE-BLOCK (Step-2.7 HIGH #1): a CORRECT mode-selectable barrel
    # shifter (shift in one mode, rotate in another, op_mode select) MUST NOT be
    # blocked — its rotate branch is legitimate, not a shifter-mis-as-rotate.
    assert _findings(_BOTH_OFFERED_SPEC, _DUAL_MODE_TERNARY_RTL, RULE_SHIFT) == []


def test_disjunction_silent_on_correct_DUAL_MODE_case_no_false_block():
    # §4.05 NO-FALSE-BLOCK (Step-2.7 HIGH #2): the same dual-mode design with a
    # `case` mux (not a ternary) must also stay silent.
    assert _findings(_BOTH_OFFERED_SPEC, _DUAL_MODE_CASE_RTL, RULE_SHIFT) == []


def test_disjunction_STILL_fires_on_rotate_only_no_leak():
    # §4.05 NO-LEAK: the dual-mode SKIP must not disarm the wrong case — a
    # rotate-ONLY RTL (no co-present logical-shift mux) under the SAME "shifts
    # or rotates" spec is still WRONG and MUST fire.
    fs = _findings(_BOTH_OFFERED_SPEC, _ROTATE_OR_RTL, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_dead_shift_wire_without_mux_still_fires_no_launder():
    # §4.05 NO-LAUNDER: a dead logical-shift wire that never reaches a mux does
    # NOT make a rotate-only output a dual-mode design — without a select
    # construct the gate still fires (the skip needs BOTH a plain-shift datapath
    # AND a ternary/case mux).
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
           "                 output [7:0] dout);\n"
           "  wire [7:0] dead = din << ctrl;\n"     # dead, no mux
           "  assign dout = (din >> ctrl) | (din << (8 - ctrl));\n"
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_decoy_ternary_rotate_vs_zero_still_fires_no_launder():
    # §4.05 NO-LAUNDER (branch-aware): a dead shift wire PLUS a decoy ternary
    # whose branches are rotate-vs-ZERO (the shift wire is never a mux branch)
    # is a rotate-ONLY output and MUST still fire — the skip requires the SELECT
    # to genuinely pick a shift branch against a rotate branch.
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl, input en,\n"
           "                 output [7:0] dout);\n"
           "  wire [7:0] dead = din << ctrl;\n"                 # decoy, unused by mux
           "  assign dout = en ? ((din >> ctrl) | (din << (8 - ctrl))) : 8'b0;\n"
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_output_aware_decoy_mux_dead_wire_still_fires_no_launder():
    # §4.05 NO-LAUNDER round-3 (Step-2.7 re-review HIGH#1): a rotate-ONLY OUTPUT
    # plus a dead decoy mux on an UNUSED wire (genuine shift-vs-rotate branches,
    # but driving `junk`, not the output) must STILL fire — the skip is now
    # OUTPUT-AWARE: only the output's OWN driving mux can suppress the finding.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt, input mode,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = (din << shamt) | (din >> (8 - shamt));\n"   # rotate-ONLY BUG
           "  wire [7:0] junk;\n"
           "  assign junk = mode ? (din << shamt)\n"                    # dead decoy mux
           "                     : ((din >> shamt) | (din << (8 - shamt)));\n"
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_output_aware_both_branches_rotate_split_wire_still_fires_no_leak():
    # §4.05 NO-LEAK round-3 (Step-2.7 re-review HIGH#2): the output mux selects
    # between TWO rotates — `sh` is a split-wire LEFT ROTATE ((din<<n)|wrap with
    # wrap=din>>(8-n)); no mode ever does the spec's logical shift. Full
    # recursive resolution must read `sh` as a rotate, so the gate STILL fires.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt, input mode,\n"
           "                 output [7:0] dout);\n"
           "  wire [7:0] wrap = din >> (8 - shamt);\n"
           "  wire [7:0] sh   = (din << shamt) | wrap;\n"        # actually a rotate
           "  wire [7:0] rot  = (din >> shamt) | (din << (8 - shamt));\n"
           "  assign dout = mode ? sh : rot;\n"                  # BOTH modes rotate
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_output_aware_decoy_case_dead_reg_still_fires_no_launder():
    # §4.05 NO-LAUNDER round-3 (Step-2.7 re-review HIGH#3): the case variant — a
    # dead reg `junk` driven by a shift-item + rotate-item case must NOT suppress
    # the rotate-ONLY live combinational output. Confirms output-awareness holds
    # across BOTH the ternary and case paths.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt, input [1:0] op,\n"
           "                 output [7:0] dout);\n"
           "  reg [7:0] junk;\n"
           "  always @(*) begin\n"
           "    case (op)\n"
           "      2'd0: junk = din << shamt;\n"
           "      2'd1: junk = (din >> shamt) | (din << (8 - shamt));\n"
           "      default: junk = din;\n"
           "    endcase\n"
           "  end\n"
           "  assign dout = (din << shamt) | (din >> (8 - shamt));\n"   # rotate-ONLY BUG
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_dead_blocking_overwrite_still_fires_no_launder():
    # §4.05 NO-LAUNDER round-4 (Step-2.7 re-review HIGH): a sequential blocking
    # assignment where a decoy logical-shift is immediately OVERWRITTEN by the
    # real rotate (last-write-wins → functionally rotate-ONLY) must STILL fire.
    # A leaf is only taken from a genuine LIVE mux, never a bare unconditional
    # assign, so the dead first write cannot fake dual-mode.
    rtl = ("module TopModule(input [7:0] din, input [2:0] sh,\n"
           "                 output reg [7:0] dout);\n"
           "  always @(*) begin\n"
           "    dout = din >> sh;\n"                              # DEAD (overwritten)
           "    dout = (din >> sh) | (din << (8 - sh));\n"        # live ROTATE wins
           "  end\n"
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_constant_selector_case_still_fires_no_launder():
    # §4.05 NO-LAUNDER round-4 (Step-2.7 re-review HIGH, case variant): a CONSTANT
    # case selector (`case(1'b1)`) is not a runtime mux — the dead 1'b0 shift
    # label never executes, the live 1'b1 rotate label drives the output. Must
    # fire; a constant-selector case cannot fake dual-mode.
    rtl = ("module TopModule(input [7:0] din, input [2:0] sh,\n"
           "                 output reg [7:0] dout);\n"
           "  always @(*) begin\n"
           "    case (1'b1)\n"
           "      1'b0: dout = din >> sh;\n"                      # dead label
           "      1'b1: dout = (din >> sh) | (din << (8 - sh));\n"  # live rotate
           "      default: dout = din;\n"
           "    endcase\n"
           "  end\n"
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_disjunction_silent_on_correct_DUAL_MODE_ifelse_no_false_block():
    # §4.05 NO-FALSE-BLOCK round-4: a CORRECT mode-selectable shifter expressed
    # as a simple `if(mode) rotate; else shift;` in an always block is a genuine
    # live mux and must stay silent (not re-introduce the round-1 false-block).
    rtl = ("module TopModule(input [7:0] din, input [2:0] sh, input mode,\n"
           "                 output reg [7:0] dout);\n"
           "  always @(*)\n"
           "    if (mode) dout = (din >> sh) | (din << (8 - sh));\n"
           "    else dout = din >> sh;\n"
           "endmodule\n")
    assert _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT) == []


def test_doubled_vector_rotate_fires_under_plain_shift_spec():
    # §4.05 round-4 (Step-2.7): an inline DOUBLED-vector rotate `{din,din} >> k`
    # is a genuine rotate (the duplication supplies the wrap bits) — it must
    # BLOCK under a plain shifter spec, closing the _rtl_rotate_signatures blind
    # spot. (Split-wire resolution is exercised by the dual-mode launder test.)
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = {din, din} >> ctrl;\n"
           "endmodule\n")
    fs = _findings(_SHIFT_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_or_rotate_no_space_parenthesised_amount_fires():
    # §4.05 round-4 (Step-2.7): the OR-of-opposite-shifts rotate with NO spaces
    # and a PARENTHESISED shift amount `(din>>shamt)|(din<<(8-shamt))` must be
    # detected — the old amount pattern excluded parens and dropped the whole
    # signature, letting a functionally rotate-ONLY design pass a shifter spec.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt,\n"
           "                 output [7:0] dout);\n"
           "  assign dout=(din>>shamt)|(din<<(8-shamt));\n"
           "endmodule\n")
    fs = _findings(_SHIFT_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_doubled_vector_replication_rotate_fires_under_plain_shift_spec():
    # §4.05 round-4: the replication form `{2{din}} >> k` is the same rotate.
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = {2{din}} >> ctrl;\n"
           "endmodule\n")
    fs = _findings(_SHIFT_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_doubled_vector_rotate_does_not_launder_dual_mode_no_leak():
    # §4.05 NO-LAUNDER round-4 (Step-2.7 re-review HIGH): a ternary muxing an
    # OR-rotate leaf against a DOUBLED-vector rotate leaf (`{din,din} >> k`) is
    # functionally rotate-ONLY in every mode (no logical zero-fill shift). The
    # doubled-vector leaf must now classify as 'rotate', so the mux is NOT
    # dual-mode and the gate STILL fires.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt, input mode,\n"
           "                 output [7:0] dout);\n"
           "  wire [7:0]  rA  = (din >> shamt) | (din << (8 - shamt));\n"
           "  wire [15:0] dbl = {din, din};\n"
           "  wire [7:0]  rB  = dbl >> shamt;\n"
           "  assign dout = mode ? rA : rB;\n"   # both leaves rotate (mode is decoy)
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_zerofill_concat_not_misread_as_doubled_rotate():
    # §4.05 ZERO-FALSE-FIRE round-4: a {bit-select, literal} zero-fill shift and
    # a {x, y} two-different-vector funnel must NOT match the doubled-vector
    # rotate signature — they stay silent under a shifter spec.
    zerofill = ("module TopModule(input [7:0] din, output [7:0] dout);\n"
                "  assign dout = {din[6:0], 1'b0};\n"
                "endmodule\n")
    funnel = ("module TopModule(input [7:0] a, input [7:0] b, input [2:0] k,\n"
              "                 output [7:0] dout);\n"
              "  assign dout = {a, b} >> k;\n"   # two DIFFERENT vectors → funnel
              "endmodule\n")
    assert _findings(_SHIFT_SPEC, zerofill, RULE_SHIFT) == []
    assert _findings(_SHIFT_SPEC, funnel, RULE_SHIFT) == []


def test_xor_form_rotate_fires_under_plain_shift_spec():
    # §4.05 round-5 (Step-2.7): the XOR-form rotate `(din<<(8-s))^(din>>s)` is
    # identically the OR-form rotate when the two halves are bit-disjoint
    # (a+b==W) — it must BLOCK under a plain shifter spec, closing the
    # _rtl_rotate_signatures `|`-only blind spot.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = (din << (8 - shamt)) ^ (din >> shamt);\n"
           "endmodule\n")
    fs = _findings(_SHIFT_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_xor_form_rotate_does_not_launder_dual_mode_no_leak():
    # §4.05 NO-LAUNDER round-5 (Step-2.7 re-review LOW): a ternary muxing an
    # OR-rotate leaf against an XOR-form rotate leaf is functionally rotate-ONLY
    # in every mode. The XOR leaf must now classify as 'rotate', so the mux is
    # NOT dual-mode and the gate STILL fires.
    rtl = ("module TopModule(input [7:0] din, input [2:0] shamt, input mode,\n"
           "                 output [7:0] dout);\n"
           "  wire [7:0] rot_or  = (din >> shamt) | (din << (8 - shamt));\n"
           "  wire [7:0] rot_xor = (din << (8 - shamt)) ^ (din >> shamt);\n"
           "  assign dout = mode ? rot_or : rot_xor;\n"   # both leaves rotate
           "endmodule\n")
    fs = _findings(_BOTH_OFFERED_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


def test_xor_of_different_signals_not_misread_as_rotate():
    # §4.05 ZERO-FALSE-FIRE round-5: XOR of shifts of DIFFERENT signals (or same
    # direction) is NOT a rotate — must stay silent under a shifter spec.
    diff_sig = ("module TopModule(input [7:0] a, input [7:0] b, input [2:0] k,\n"
                "                 output [7:0] dout);\n"
                "  assign dout = (a << k) ^ (b >> k);\n"   # different signals
                "endmodule\n")
    assert _findings(_SHIFT_SPEC, diff_sig, RULE_SHIFT) == []


def test_plain_shifter_spec_unaffected_by_dual_mode_skip():
    # §4.05 REGRESSION: the dual-mode skip is gated on the disjunction; a plain
    # 'shifter' spec (no "shift or rotate") with a rotate RTL — even one that
    # happens to carry a ternary — still fires, original gate preserved.
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl, input s,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = s ? ((din >> ctrl) | (din << (8 - ctrl)))\n"
           "                  : ((din >> ctrl) | (din << (8 - ctrl)));\n"
           "endmodule\n")
    fs = _findings(_SHIFT_SPEC, rtl, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


# ===========================================================================
# (2) waveform-peak-hold-dropped
# ===========================================================================
_TRI_HOLD_SPEC = ("Build a triangle waveform generator. The output ramps up to "
                  "the maximum, then HOLDS the peak for 4 cycles, then ramps "
                  "down to the minimum and repeats.\n\n"
                  " - input  clk\n - input  rst\n - output [7:0] wave\n")

# drops the hold: direction toggles the instant the extreme is hit, no dwell
_NO_HOLD_RTL = ("module TopModule(input clk, input rst,\n"
                "                 output reg [7:0] wave);\n"
                "  reg dir;\n"
                "  always @(posedge clk) begin\n"
                "    if (rst) begin wave <= 0; dir <= 1; end\n"
                "    else begin\n"
                "      if (wave == 8'd255) dir <= ~dir;\n"
                "      else if (wave == 8'd0) dir <= ~dir;\n"
                "      wave <= dir ? wave + 1 : wave - 1;\n"
                "    end\n"
                "  end\n"
                "endmodule\n")

# correct peak-hold: carries a dwell counter — must NEVER fire
_PEAK_HOLD_RTL = ("module TopModule(input clk, input rst,\n"
                  "                 output reg [7:0] wave);\n"
                  "  reg dir; reg [1:0] hold_cnt;\n"
                  "  always @(posedge clk) begin\n"
                  "    if (rst) begin wave <= 0; dir <= 1; hold_cnt <= 0; end\n"
                  "    else if (wave == 8'd255 && hold_cnt < 3)\n"
                  "      hold_cnt <= hold_cnt + 1;\n"
                  "    else if (wave == 8'd255) begin\n"
                  "      dir <= ~dir; hold_cnt <= 0;\n"
                  "    end else wave <= dir ? wave + 1 : wave - 1;\n"
                  "  end\n"
                  "endmodule\n")


def test_hold_rule_fires_on_dropped_hold_under_hold_spec():
    fs = _findings(_TRI_HOLD_SPEC, _NO_HOLD_RTL, RULE_HOLD)
    assert [f.severity for f in fs] == ["ERROR"], fs
    assert fs[0].symbol == "dir"
    assert "hold" in fs[0].message.lower()


# §4.05 negatives — must NOT fire
def test_hold_rule_silent_on_correct_peak_hold_rtl():
    assert _findings(_TRI_HOLD_SPEC, _PEAK_HOLD_RTL, RULE_HOLD) == []


def test_hold_rule_silent_on_explicit_no_hold_spec():
    # §4.05: a spec that EXPLICITLY forbids the hold must not fire
    spec = ("Build a triangle waveform generator. Ramp up to the maximum then "
            "immediately reverse — do NOT hold the peak.\n\n"
            " - input  clk\n - input  rst\n - output [7:0] wave\n")
    assert _findings(spec, _NO_HOLD_RTL, RULE_HOLD) == []


def test_hold_rule_silent_on_plain_sawtooth_spec():
    # a plain sawtooth / no explicit hold spec must not fire
    spec = ("Build a sawtooth ramp generator: the output ramps up to the "
            "maximum then resets to zero and repeats.\n\n"
            " - input  clk\n - output [7:0] wave\n")
    assert _findings(spec, _NO_HOLD_RTL, RULE_HOLD) == []


def test_hold_rule_silent_on_plain_triangle_no_hold_clause_spec():
    # a triangle spec with NO explicit hold clause must not fire (under-fire)
    spec = ("Build a triangle waveform generator. The output ramps up to the "
            "maximum then ramps back down to the minimum, repeating.\n\n"
            " - input  clk\n - output [7:0] wave\n")
    assert _findings(spec, _NO_HOLD_RTL, RULE_HOLD) == []


# ===========================================================================
# cross-rule: an unrelated (non-shifter / non-waveform) design fires NEITHER
# ===========================================================================
def test_unrelated_design_fires_neither_rule():
    spec = ("Build a 4-bit binary up counter that increments every clock.\n\n"
            " - input  clk\n - output [3:0] cnt\n")
    rtl = ("module TopModule(input clk, output reg [3:0] cnt);\n"
           "  always @(posedge clk) cnt <= cnt + 1;\n"
           "endmodule\n")
    fs = _findings(spec, rtl)
    assert [f for f in fs if f.rule in (RULE_SHIFT, RULE_HOLD)] == []


# ===========================================================================
# subprocess CLI: returncode + JSON shape
# ===========================================================================
def _run_cli(tmp_path, spec_text, rtl, suffix=".md"):
    spec_f = tmp_path / ("spec" + suffix)
    spec_f.write_text(spec_text)
    rtl_f = tmp_path / "dut.v"
    rtl_f.write_text(rtl)
    out_json = tmp_path / "findings.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--spec", str(spec_f),
         "--top", "TopModule", "--json", str(out_json), str(rtl_f)],
        capture_output=True, text=True, timeout=60)
    findings = json.loads(out_json.read_text()) if out_json.is_file() else []
    return r, findings


def test_cli_shift_rotate_fails_with_error(tmp_path):
    r, fnd = _run_cli(tmp_path, _SHIFT_SPEC, _ROTATE_OR_RTL)
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(f["rule"] == RULE_SHIFT and f["severity"] == "ERROR"
               for f in fnd), fnd


def test_cli_logical_shift_passes(tmp_path):
    r, fnd = _run_cli(tmp_path, _SHIFT_SPEC, _LOGICAL_SHIFT_RTL)
    assert not any(f["rule"] == RULE_SHIFT for f in fnd), fnd


def test_cli_dropped_hold_fails_with_error(tmp_path):
    r, fnd = _run_cli(tmp_path, _TRI_HOLD_SPEC, _NO_HOLD_RTL)
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(f["rule"] == RULE_HOLD and f["severity"] == "ERROR"
               for f in fnd), fnd


def test_cli_correct_hold_passes(tmp_path):
    r, fnd = _run_cli(tmp_path, _TRI_HOLD_SPEC, _PEAK_HOLD_RTL)
    assert not any(f["rule"] == RULE_HOLD for f in fnd), fnd


# ===========================================================================
# both rule names are wired into the emit-blocking set
# ===========================================================================
def test_both_rules_are_emit_blocking():
    src = GATES.read_text()
    # _BLOCKING_CONFORMANCE_RULES is a module-local set; assert by source.
    import re
    m = re.search(r"_BLOCKING_CONFORMANCE_RULES\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "could not locate _BLOCKING_CONFORMANCE_RULES set"
    block_src = m.group(1)
    assert RULE_SHIFT in block_src, block_src
    assert RULE_HOLD in block_src, block_src


# ===========================================================================
# gates_atomic end-to-end: BLOCK the anti-patterns, EMIT the correct designs
# ===========================================================================
def _stage(tmp_path, prompt_text, sample_body):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbP_prompt.txt").write_text(prompt_text)
    wd = tmp_path / "run" / "work" / "ProbP"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (wd / "sample.sv").write_text(sample_body)
    return ds, tmp_path / "run"


def _run_gate(ds, run):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbP",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=60)


def _block_rules(run):
    gates = json.loads((run / "work" / "ProbP" / "gates.json").read_text())
    blk = gates["steps"].get("structural_emit_block", {})
    return gates, {f["rule"] for f in blk.get("findings", [])}


def test_gate_blocks_rotate_under_shift_spec(tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    ds, run = _stage(tmp_path, _SHIFT_SPEC, _ROTATE_OR_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE_SHIFT in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_emits_logical_shift(tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    ds, run = _stage(tmp_path, _SHIFT_SPEC, _LOGICAL_SHIFT_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert RULE_SHIFT not in rules
    assert (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_blocks_dropped_hold_under_hold_spec(tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    ds, run = _stage(tmp_path, _TRI_HOLD_SPEC, _NO_HOLD_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE_HOLD in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_emits_correct_peak_hold(tmp_path):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    ds, run = _stage(tmp_path, _TRI_HOLD_SPEC, _PEAK_HOLD_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert RULE_HOLD not in rules
    assert (run / "samples" / "ProbP_sample01.sv").exists()
