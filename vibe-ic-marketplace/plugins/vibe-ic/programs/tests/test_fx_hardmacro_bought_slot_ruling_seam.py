"""Owner's IC versus IP route ruling at step 0.5ic and both consumers."""
import sys
import json
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as TD  # noqa: E402
import flow_compliance_check as F  # noqa: E402
import tapeout_declaration_check as CHECK  # noqa: E402
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


def test_four_routes_share_one_predicate_and_refuse_the_contradiction(tmp_path):
    """The three valid routes keep their outputs; the fourth selects neither."""
    valid = []
    for name, opts, owed, ring in (
        ("ip", {}, False, False),
        ("shuttle_die", {"deliverable": "DIE", "bought": True}, True, True),
        ("self_die", {"deliverable": "DIE", "self_tapeout": True}, True, True),
    ):
        project = _case(tmp_path / name, **opts)
        valid.append((project, owed))
        assert TD.requests_pad_ring(project) is ring
        for sid in ("15.5ic", "26.5ic", "37.5ic"):
            assert F._check_condition(
                project, BASE._steps()[sid]["condition"]) is owed
        assert F._check_condition(
            project, BASE._steps()["37.5ip"]["condition"]) is (not owed)

    bought = _case(tmp_path / "contradiction", bought=True)
    refusal = None
    try:
        TD.requests_pad_ring(bought)
    except ValueError as exc:
        refusal = str(exc)
    assert refusal == MESSAGE
    for sid in ("15.5ic", "26.5ic", "37.5ic"):
        with pytest.raises(ValueError,
                           match="HARDMACRO.*bought shuttle slot"):
            F._check_condition(bought, BASE._steps()[sid]["condition"])
    for project, owed in valid:
        assert TD.die_outputs_owed(project) is owed




def test_direct_route_producer_and_gate_refuse_by_name(tmp_path, capsys):
    project = _case(tmp_path, bought=True)
    assert GEN.main([str(project)]) == 1
    assert MESSAGE in capsys.readouterr().err
    rec = CHECK.evaluate(project)
    assert any(r["rule"] == "HARDMACRO_BOUGHT_SLOT_CONTRADICTION"
               and r["message"] == MESSAGE
               for r in rec["refusals"])


def test_compliance_records_route_contradiction_on_condition_and_output(tmp_path):
    project = _case(tmp_path, bought=True)
    steps = BASE._steps()
    for sid in ("15.5ic", "37"):
        row = F.check_step(project, steps[sid], {})
        assert row.status == "FAIL", sid
        assert MESSAGE in " ".join(row.reasons), sid


def test_stage3_compliance_writes_a_report_for_a_contradictory_route(tmp_path):
    project = _case(tmp_path, bought=True)
    report = tmp_path / "stage3.json"
    rc = F.main([str(project), "--stage", "3", "--json", str(report)])
    assert rc != 0
    data = json.loads(report.read_text())
    rows = {str(row["id"]): row for row in data["steps"]}
    assert "15.5ic" in rows
    assert rows["15.5ic"]["status"] == "FAIL"
    assert MESSAGE in str(rows["15.5ic"])


def test_unmarked_project_does_not_select_a_pad_ring(tmp_path):
    project = _case(tmp_path, bought=True)
    (project / TD.SLOTS_REL / "slot_1x1.yaml").unlink()
    assert TD.requests_pad_ring(project) is False
    assert LL.design_class(project) is None
    assert LL.selected_mode(project, "15") in ("direct", "librelane", "dual")
