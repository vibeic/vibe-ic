"""The two dispatcher gates must agree, measured through the gates themselves.

`test_v1_15_67_opcode_dispatch_predicate.py` imports the extracted predicate
module directly, which makes it a fine test of the rule but a WEAK negative
control: against a tree that does not have the module yet it raises
`ModuleNotFoundError` at collection, and an import error proves only that a file
is absent — not that anything behaves wrongly.

This module imports ONLY the two CALLERS, both of which exist on either tree, so
it collects everywhere and fails on a behavioural disagreement:

    packet_length_check_present._is_dispatcher   — the copy that WAS corrected
    dispatcher_awake_gate_check._find_dispatcher — the copy that was NOT

MEASURED on opentitan_aes: `aes_ctrl_reg_shadowed.sv` is an enum decode over a
bare `op` and carries no command protocol at all. The corrected copy says "not a
dispatcher"; the uncorrected copy matched `case (op)` and demanded an awake
register of it. Two gates over one artefact cannot disagree about what that
artefact IS.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dispatcher_awake_gate_check as D  # noqa: E402
import packet_length_check_present as L  # noqa: E402

# An enum decode over a bare `op` — the measured false positive, reduced.
ENUM_DECODE = """
module aes_ctrl_reg_shadowed;
  typedef enum logic { AES_ENC, AES_DEC } aes_op_e;
  aes_op_e op;
  always_comb begin
    unique case (op)
      AES_ENC: mode = 1'b0;
      AES_DEC: mode = 1'b1;
      default: mode = 1'b0;
    endcase
  end
endmodule
"""

# The same ambiguous selector, CORROBORATED by byte-opcode literals.
REAL_DISPATCH = """
module rx;
  always_comb begin
    case (op)
      8'h01: r = 1;
      8'hA5: r = 2;
      default: r = 0;
    endcase
  end
endmodule
"""


def _tree(tmp_path: Path, name: str, text: str) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / name).write_text(text)
    return proj


def test_the_two_gates_agree_that_an_enum_decode_is_not_a_dispatcher(tmp_path):
    """THE FALSIFIER. Red wherever the two copies have diverged."""
    proj = _tree(tmp_path, "aes_ctrl_reg_shadowed.sv", ENUM_DECODE)
    packet_says = L._is_dispatcher(ENUM_DECODE)
    awake_says = D._find_dispatcher(proj) is not None
    assert packet_says is False, "the corrected copy should already say this"
    assert awake_says == packet_says, (
        "the two dispatcher gates disagree about the SAME artefact: "
        f"packet_length_check_present._is_dispatcher={packet_says}, "
        f"dispatcher_awake_gate_check._find_dispatcher(...) is not None={awake_says}. "
        "There must be ONE rule, not two copies of which only one was corrected."
    )


def test_the_two_gates_agree_that_a_real_dispatch_is_a_dispatcher(tmp_path):
    """DIRECTIONAL CONTROL — passes in BOTH trees, and must.

    Agreement is trivially satisfiable by a rule that answers False to
    everything, so the pair is also pinned where the answer is True.
    """
    proj = _tree(tmp_path, "rx.sv", REAL_DISPATCH)
    packet_says = L._is_dispatcher(REAL_DISPATCH)
    awake_says = D._find_dispatcher(proj) is not None
    assert packet_says is True
    assert awake_says == packet_says


def test_neither_gate_invents_a_dispatcher_in_an_empty_tree(tmp_path):
    """Control: no RTL, no dispatcher, from either gate. Passes in both trees."""
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    assert D._find_dispatcher(proj) is None
    assert L._is_dispatcher("") is False
