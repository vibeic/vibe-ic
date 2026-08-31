#!/usr/bin/env python3
"""A guarded reference was reported as unconditional — the opposite of the truth.

MEASURED DEFECT
===============
`staged_rtl_closure_preflight._enclosing_case_label` requires the literal
keyword ``case`` in the preceding window, so the whole **if/else-generate**
form was invisible. A dangling reference inside ``if (P == V) begin : L`` fell
through to ``unconditional_dangling_ref``, described as::

    module 'X' is instantiated outside any generate conditional and is NOT in
    the staged closure - genuine hole.

Both clauses are false. Measured on OpenTitan `aes_sbox.sv`, whose reference
sits inside TWO nested generate conditionals, and whose missing module is
excluded from the corpus ON PURPOSE. The action that message implies is to
stage the module — i.e. to add masked-crypto RTL back into a build whose brief
declared masking disabled.

A wrong-kind classification that reads as confident is worse than silence:
silence makes an operator look; "genuine hole" makes them act, in the wrong
direction.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import staged_rtl_closure_preflight as PF  # noqa: E402

_PRESENT = "module sub_present (input logic a, output logic y); assign y = a; endmodule\n"


def _tree(tmp_path: Path, top: str) -> str:
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(top)
    (d / "sub_present.sv").write_text(_PRESENT)
    return str(d)


def _rules(target):
    return [f for f in PF.audit([target]).get("findings", [])]


IF_GEN = """module top #(parameter impl_e Impl = ImplB) (input logic a, output logic y);
  if (Impl == ImplA) begin : gen_a
    sub_present u (.a(a), .y(y));
  end else begin : gen_b
    sub_absent u (.a(a), .y(y));
  end
endmodule
"""

CASE_GEN = """module top #(parameter impl_e Impl = ImplB) (input logic a, output logic y);
  case (Impl)
    ImplA: begin : gen_a
      sub_present u (.a(a), .y(y));
    end
    ImplB: begin : gen_b
      sub_absent u (.a(a), .y(y));
    end
  endcase
endmodule
"""

FOR_GEN = """module top (input logic [3:0] a, output logic [3:0] y);
  for (genvar i = 0; i < 4; i++) begin : gen_loop
    sub_absent u (.a(a[i]), .y(y[i]));
  end
endmodule
"""


def test_an_if_else_generate_branch_is_classified_as_a_generate_branch(tmp_path):
    found = _rules(_tree(tmp_path, IF_GEN))
    kinds = {f["rule"] for f in found}
    assert "generate_branch_default" in kinds, (
        "an if/else-generate guard was reported as unconditional — the flow "
        "would tell the operator the reference sits outside any conditional")
    assert "unconditional_dangling_ref" not in kinds
    entry = [f for f in found if f["rule"] == "generate_branch_default"][0]
    assert entry["guard_label"] == "gen_b"
    assert "sub_present" in entry["in_closure_alternatives"]


def test_case_generate_still_reports_its_selecting_default(tmp_path):
    """The pre-existing case-generate path must not regress."""
    found = [f for f in _rules(_tree(tmp_path, CASE_GEN))
             if f["rule"] == "generate_branch_default"]
    assert len(found) == 1
    assert found[0]["selecting_param_defaults"] == ["Impl = ImplB"]


def test_a_for_generate_is_not_swept_up(tmp_path):
    """A loop body is not a conditional; it must keep its classification."""
    kinds = {f["rule"] for f in _rules(_tree(tmp_path, FOR_GEN))}
    assert kinds == {"unconditional_dangling_ref"}


def test_nothing_is_reported_when_the_module_is_present(tmp_path):
    ok = IF_GEN.replace("sub_absent", "sub_present")
    assert _rules(_tree(tmp_path, ok)) == []
