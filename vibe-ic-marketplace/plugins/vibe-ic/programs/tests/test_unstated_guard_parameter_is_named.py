#!/usr/bin/env python3
"""Two true facts that never met: the override applied, and the branch still dangling.

MEASURED DEFECT
===============
After an override is applied the synth FAIL could report ``SecMasking = 0
applied`` and, separately, ``aes_sbox_dom dangles in branch gen_sbox_dom``.
Both true; nothing connected them. The operator was left to discover unaided
that the branch is decided by a DIFFERENT parameter the input never mentioned.

The connection needs no design knowledge. The preflight already parses the
guard CONDITION, so it can report the parameters the guard DEPENDS ON — as
distinct from ``selecting_param_defaults``, the ones whose DEFAULT selects it.
Those two differ exactly when the deciding parameter's default does NOT select
the branch, which is the case where the name is most needed and least visible.

REPORTING, NOT INFERENCE
========================
The note NAMES the parameter and refuses to choose its value. A check that
picked one would be the guess #586 exists to refuse. A check that fires when it
has nothing to say is noise — so the silences are pinned here too.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import staged_rtl_closure_preflight as PF  # noqa: E402

TOP = """module top #(
  parameter bit SecMasking = 1,
  parameter sbox_impl_e SecSBoxImpl = SBoxImplLut
) (input logic a, output logic y);
  if (SecSBoxImpl == SBoxImplDom) begin : gen_sbox_dom
    sub_absent u (.a(a), .y(y));
  end else begin : gen_lut
    sub_present u (.a(a), .y(y));
  end
endmodule
"""
PRESENT = "module sub_present (input logic a, output logic y); assign y=a; endmodule\n"

FINDINGS = [{"module_ref": "sub_absent", "guard_label": "gen_sbox_dom",
             "guard_parameters": ["SecSBoxImpl"]}]


def test_the_preflight_reports_which_parameter_decides_the_branch(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "top.sv").write_text(TOP)
    (d / "sub_present.sv").write_text(PRESENT)

    gen = [f for f in PF.audit([str(d)])["findings"]
           if f["rule"] == "generate_branch_default"]

    assert gen, "the guarded reference was not classified as a generate branch"
    assert gen[0].get("guard_parameters") == ["SecSBoxImpl"], (
        "the report names no deciding parameter, so nothing downstream can "
        "tell the operator which knob they never set")
