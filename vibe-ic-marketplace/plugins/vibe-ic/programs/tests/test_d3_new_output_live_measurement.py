"""A new output needs a new normal-producer execution, not a rewritten capture."""


import phase3_one_shot_runner as runner
import test_matrix_d3_outputs_produced as d3
from test_issue2081_sta_architectural_residual_is_routed import _MET

OUTPUT = "reports/phase3/sta/architectural_residual.json"
INPUT = "phase3/stage3/sta/sta_mcorner_ocv.rpt"


def _new_entry(monkeypatch):
    monkeypatch.setattr(d3.F, "required_outputs", lambda sid: (OUTPUT,))
    monkeypatch.setattr(d3, "step_record", lambda sid: {"entries": {}})




def test_new_output_without_a_unique_declared_owner_remains_unmeasured(monkeypatch):
    _new_entry(monkeypatch)
    monkeypatch.setattr(d3.F, "gate_programs", lambda sid: ())
    missing, _, _ = d3.audit_step("23")
    assert missing and "no unique declared inline producer" in missing[0]


def test_removed_required_output_still_fails_manifest_drift(monkeypatch):
    monkeypatch.setattr(d3.F, "required_outputs", lambda sid: ())
    monkeypatch.setattr(d3, "step_record", lambda sid: {"entries": {OUTPUT: {}}})
    missing, _, _ = d3.audit_step("23")
    assert missing and "removed" in missing[0] and OUTPUT in missing[0]


def test_written_report_must_reach_the_real_consumer_path(monkeypatch):
    _new_entry(monkeypatch)
    monkeypatch.setattr(d3, "_GLOB_FIRST", lambda project, entry: [])
    with d3._probe_run_root("d3_new_consumer_") as (root, commit):
        target = root / INPUT
        target.parent.mkdir(parents=True)
        target.write_text(_MET)
        commit(INPUT)
        d3._probe_only(monkeypatch, "consumer-probe", root)
        missing, _, _ = d3.audit_step("23")
        assert missing and "did not write the declared regular file" in missing[0]


def test_two_inline_owners_do_not_authorize_an_ambiguous_measurement(monkeypatch):
    _new_entry(monkeypatch)
    owner = next(row for row in runner._DECLARED_SIGNOFF_GATES if row[2] == OUTPUT)
    monkeypatch.setattr(runner, "_DECLARED_SIGNOFF_GATES", (owner, owner))
    missing, _, _ = d3.audit_step("23")
    assert missing and "no unique declared inline producer" in missing[0]
