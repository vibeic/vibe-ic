"""Owner's IC versus IP route ruling at step 0.5ic and both consumers."""
import sys
import json
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as TD  # noqa: E402
import tapeout_declaration_gen as GEN  # noqa: E402
import test_issue2277_hardmacro_owes_no_die_steps as BASE  # noqa: E402
import librelane_contract as LL  # noqa: E402

MESSAGE = ("deliverable HARDMACRO (IP path) contradicts a bought shuttle slot "
           "(IC path); declare one route in input/step_0_5ic_answers.json")


def _case(tmp_path, *, deliverable="HARDMACRO", bought=False,
          self_tapeout=False):
    operator = ({"path": "t.yaml", "slot": "slot_1x1"} if bought else None)
    return BASE._project(tmp_path, deliverable=deliverable,
                         operator=operator, self_tapeout=self_tapeout)












def test_unmarked_project_does_not_select_a_pad_ring(tmp_path):
    project = _case(tmp_path, bought=True)
    (project / TD.SLOTS_REL / "slot_1x1.yaml").unlink()
    assert TD.requests_pad_ring(project) is False
    assert LL.design_class(project) is None
    assert LL.selected_mode(project, "15") in ("direct", "librelane", "dual")
