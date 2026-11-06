"""FX_SPM_GATES_2 (2): the pad-ring route attestation is owed by a die only.

MEASURED on the same-RTL spm x gf180mcuD run (lane cmpb N5; deliverable
HARDMACRO, a core-only design with no pad ring): step 37 FAILED
`required_outputs missing: ['reports/phase3/pad_ring_route_evidence.json']`
(missing_artefact). Its only producer, `step_pad_ring_final_evidence`, runs
only under `_chip_path_requests_pad_ring(project)` -- step 15.5ic's condition
-- so the flow owed a HARDMACRO an artefact its producer correctly never
writes.

The rule: step 37 keeps declaring the attestation (every other reader --
matrix pins, the publisher, d4 grounding -- sees the step unchanged), and
`output_conditions` makes that ONE entry NOT_APPLICABLE when the step-15.5ic
route condition is false: an owner-declared hardmacro with no operator slot,
or no live slot/SELF_TAPEOUT route marker. A DIE on a live route still owes it.
"""
import sys
import yaml
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(HERE))

import pytest                                            # noqa: E402

import _tapeout_declaration as TD                        # noqa: E402
import test_issue2277_hardmacro_owes_no_die_steps as H   # noqa: E402
from _invocation_fixture import bind_invocation_top

EVIDENCE = "reports/phase3/pad_ring_route_evidence.json"
GDS = "phase3/stage4/gds/top.gds"


def _step37():
    return next(row for row in yaml.safe_load(H._FLOW.read_text(encoding="utf-8"))["steps"]
                if str(row["id"]) == "37")


def _mini_step():
    """Step 37's own declaration of the attestation and its output condition,
    with a gate that only asks for the GDS -- so the verdict is decided by
    the required_outputs rule under test, not by the real step's programs."""
    real = _step37()
    return {"id": "37", "name": real["name"], "stage": real["stage"],
            "required_outputs": ["phase3/stage4/gds/*.gds", EVIDENCE],
            "output_conditions": real.get("output_conditions"),
            "gate": {"all_of": [{"files_exist": ["phase3/stage4/gds/*.gds"]}]},
            "blocks_on": []}




def test_step_37_still_declares_it_with_the_die_steps_own_clause():
    step = _step37()
    die_step = next(row for row in yaml.safe_load(H._FLOW.read_text(encoding="utf-8"))["steps"]
                    if str(row["id"]) == "15.5ic")
    assert EVIDENCE in step["required_outputs"]
    cond = (step.get("output_conditions") or {}).get(EVIDENCE)
    assert cond, "step 37 declares no condition for the attestation"
    assert cond["delivery_declares"] == \
        die_step["condition"]["delivery_declares"]
    assert cond == die_step["condition"]
