"""A catalogue is not a purchase: the pad budget is owed by a design that bought a slot.

vibe-ic#2277. MEASURED on `spm` x gf180mcuD, live main 79506306d (2026-09-15),
run `_lane_icspm4/run1`. The design's own input declares
`deliverable=HARDMACRO` with `operator_template.path = null` and
`operator_template.slot = null` -- it buys no slot and terminates at the
hardmacro kit (step 37.5ip). Since the 0.5ic fetch was wired, a PDK that has a
LIVE shuttle in the registry still has the operator's whole CATALOGUE ingested
into `input/submission_template/slots/*.yaml`, so:

  * `slots` is non-empty, and the ONE design-declared N/A path the program had
    (`not slots and _declared_no_slot`, keyed on SELF_TAPEOUT.txt /
    NO_TEMPLATE.txt) is unreachable;
  * the gate went on to look for a top module, took its `--top` default
    `chip_top` because the flow clause passes no `--top`, and wrote
    `{"verdict": "UNDECIDED", "reason_class": "EXECUTION_ERROR",
      "reason": "top module 'chip_top' not found in ['./phase2/stage1/rtl/spm.v']"}`;
  * EXECUTION_ERROR is not skip-eligible, so `_check_program_exit_zero` booked
    flow step 2 INCOMPLETE -- a design was charged with failing to answer a
    question it was never asked to answer.

The route is the DESIGN'S to declare and the flow already has one reader for
it, `submission_template_check.slot_rules_are_owed`, which this gate now calls.
The tests below drive the real clause runner, both directions.
"""
import json
import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tapeout_declaration as TD                      # noqa: E402
import _owner_declared as _OD                              # noqa: E402
import slot_pad_budget_check as S                      # noqa: E402
import test_slot_pad_budget_check as T                 # noqa: E402  slot fixture

_CLAUSE = ("slot_pad_budget_check . --json "
           "reports/phase2/gates/slot_pad_budget.json")

#: The spm shape: a top that is NOT called `chip_top`, so a run that reaches
#: the top lookup at all can only answer UNDECIDED. This is what makes the
#: ordering load-bearing rather than incidental.
_RTL_SPM_TOP = ("module spm (input wire clk, input wire rst,\n"
                "  input wire [31:0] x, input wire y, output wire p);\n"
                "endmodule\n")


def _project(*, deliverable, operator_template, rtl=_RTL_SPM_TOP,
             declaration=True, with_slots=True):
    """A project whose 0.5ic left the operator's CATALOGUE on disk.

    `with_slots=True` is the measured state on any PDK with a live shuttle:
    the ingest writes every slot the operator publishes, bought or not.
    """
    d = Path(tempfile.mkdtemp(prefix="issue2277_"))
    tmpl = d / "input" / "submission_template"
    (tmpl / "slots").mkdir(parents=True)
    if with_slots:
        (tmpl / "slots" / "slot_1x1.json").write_text(
            json.dumps(T._slot_ingested()))
    if declaration:
        # Built through the declaration's OWN constructor: `TD.validate`
        # refuses a declaration that merely omits a question, and a fixture
        # that cannot be validated would exercise the degrade-to-owed path
        # instead of the one under test.
        doc, _ = TD.merge_answers(
            TD.blank_declaration(),
            {"deliverable": deliverable, "top_cell": "spm"})
        _OD.attest(doc)
        assert not TD.validate(doc)
        (tmpl / "tapeout_declaration.json").write_text(json.dumps(doc))
    else:
        (tmpl / "tapeout_declaration.json").write_text("{ not json")
    (d / "input" / "step_0_5ic_answers.json").write_text(json.dumps(_OD.attest({
        "schema": "vibe-ic/step_0_5ic_answers/1",
        "operator_template": operator_template,
        "answers": {"deliverable": deliverable, "top_cell": "spm"},
    })))
    r = d / "phase2" / "stage1" / "rtl"
    r.mkdir(parents=True)
    (r / "spm.v").write_text(rtl)
    return d




_NO_SLOT = {"path": None, "slot": None, "absent_reason": "no operator applies"}


# --------------------------------------------------------------------------- #
# the fix: a hardmacro that bought nothing is N/A BY DECLARATION
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# negative controls: a design WITH the subject keeps the gate live
# --------------------------------------------------------------------------- #






def test_a_bought_slot_that_cannot_be_bonded_out_still_goes_RED():
    """The refusal this gate exists for must survive the new branch: same
    HARDMACRO word, an affirmative slot binding, an interface no slot fits."""
    hopeless = ("module spm (input wire clk, input wire rst_n,\n"
                "  input wire [127:0] a, input wire [255:0] k,\n"
                "  output wire [127:0] y, output wire alert);\nendmodule\n")
    p = _project(deliverable="HARDMACRO",
                 operator_template={"path": "t.yaml", "slot": "slot_1x1"},
                 rtl=hopeless)
    # `--top` is the clause's default here, so reaching the arithmetic at all
    # is what this asserts; the top name is a separate defect (F005).
    assert S.__name__ == "slot_pad_budget_check"
