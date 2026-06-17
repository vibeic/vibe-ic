"""ORGANIC #803 (extends #794) — _case_lhs_all_pre_assigned BAILED on ANY
control-construct token in the pre-case region, so it MISSED the ubiquitous
"priority-if-before-case" combinational-FSM idiom: statement-top defaults, then
`if (highest_priority) X; else case(...)` (forced by a "from ANY state" spec).
The leading flat defaults provably hold regardless of the intervening priority
if/else, so a correct latch-free FSM was hard-WARNed.

FIX: compute the unconditional pre-case default set from the LEADING FLAT
statement-top prefix (up to the first control token) instead of bailing.

§4.05 boundary: a case-LHS FIRST assigned only inside/after a conditional is NOT
in the flat prefix → body_lhs ⊄ uncond → hard WARN preserved (proven latch).
chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402


def _be(src):
    fs = [f for f in H.rule_case_coverage(src, "d.v")
          if f.rule == "case-no-default"]
    assert fs, "expected a case-no-default finding"
    return fs[0].block_eligible


# priority-if-before-case: both case-LHS flat-defaulted → advisory (no latch).
_POS = """\
module elevator(input [1:0] state, input overload, output reg [1:0] next_state,
                output reg [3:0] floor_next);
  always @(*) begin
    next_state = state;
    floor_next = 4'd0;
    if (overload) next_state = 2'd3;
    else case (state)
      2'd0: next_state = 2'd1;
      2'd1: begin next_state = 2'd2; floor_next = 4'd5; end
    endcase
  end
endmodule
"""

# §4.05: `floor` FIRST assigned only inside the priority-if (not flat) AND
# written in the case → not in flat prefix → hard WARN (real latch on floor).
_NEG_ONLY_IN_IF = """\
module m(input [1:0] state, input ov, output reg [1:0] next_state,
         output reg [3:0] floor);
  always @(*) begin
    next_state = state;
    if (ov) floor = 4'd9;
    else case (state)
      2'd0: begin next_state = 2'd1; floor = 4'd5; end
      2'd1: next_state = 2'd2;
    endcase
  end
endmodule
"""

# §4.05: no flat default at all → hard WARN.
_NEG_NO_FLAT = """\
module m(input [1:0] state, output reg [1:0] next_state);
  always @(*) begin
    case (state)
      2'd0: next_state = 2'd1;
      2'd1: next_state = 2'd2;
    endcase
  end
endmodule
"""

# back-compat (#794): pure flat prefix, no control token → still advisory.
_OK_PURE_FLAT = """\
module m(input [1:0] s, output reg [1:0] ns);
  always @(*) begin
    ns = s;
    case (s) 2'd0: ns = 2'd1; 2'd1: ns = 2'd2; endcase
  end
endmodule
"""


def test_803_priority_if_before_case_is_advisory():
    assert _be(_POS) is False


def test_803_noleak_case_lhs_only_in_priority_if_still_hard_warns():
    assert _be(_NEG_ONLY_IN_IF) is True


def test_803_noleak_no_flat_default_still_hard_warns():
    assert _be(_NEG_NO_FLAT) is True


def test_803_backcompat_pure_flat_still_advisory():
    assert _be(_OK_PURE_FLAT) is False


# ── Step-2.7 §4.05 — an output literally named `x`/`z` (legal identifiers that
#    VERILOG_KEYWORDS over-rejects) must NOT vanish from the coverage set. ──────
@pytest.mark.parametrize("nm", ["x", "z"])
def test_803_noleak_output_named_x_or_z_latch_still_hard_warns(nm):
    src = (f"module dut(input [1:0] sel, output reg y, output reg {nm});\n"
           " always @(*) begin\n   y = 1'b0;\n   case (sel)\n"
           f"     2'b00: begin y = 1'b1; {nm} = 1'b1; end\n"
           f"     2'b01: begin y = 1'b0; {nm} = 1'b0; end\n"
           "   endcase\n end\nendmodule")
    assert _be(src) is True   # genuine latch on x/z must stay block-eligible


def test_803_procedural_lhs_keeps_x_and_z_identifiers():
    assert H._procedural_assigned_lhs("z = 1; q = 2; x = 3;") == {"z", "q", "x"}


# ── END-STATE: the real rtl_hygiene_lint program downgrades the priority-if
#    latch-free FSM to advisory (rc=0), but a z-named latch still hard-blocks. ──
import subprocess  # noqa: E402


def test_803_endstate_priority_if_advisory_via_program(tmp_path):
    f = tmp_path / "el.v"
    f.write_text(_POS)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"), str(f)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout       # advisory, not a hard block


def test_803_endstate_z_named_latch_still_blocks_via_program(tmp_path):
    leak = ("module dut(input [1:0] sel, output reg y, output reg z);\n"
            " always @(*) begin\n   y = 1'b0;\n   case (sel)\n"
            "     2'b00: begin y = 1'b1; z = 1'b1; end\n"
            "     2'b01: begin y = 1'b0; z = 1'b0; end\n"
            "   endcase\n end\nendmodule")
    f = tmp_path / "leak.v"
    f.write_text(leak)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"), str(f)],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout       # genuine latch on z still blocks


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
