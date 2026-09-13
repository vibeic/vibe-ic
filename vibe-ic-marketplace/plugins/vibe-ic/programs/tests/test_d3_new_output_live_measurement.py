"""A new output needs a new normal-producer execution, not a rewritten capture."""
import json

import pytest

import phase3_one_shot_runner as runner
import test_matrix_d3_outputs_produced as d3
from test_issue2081_sta_architectural_residual_is_routed import _ARCH, _MET

OUTPUT = "reports/phase3/sta/architectural_residual.json"
INPUT = "phase3/stage3/sta/sta_mcorner_ocv.rpt"


def _new_entry(monkeypatch):
    monkeypatch.setattr(d3.F, "required_outputs", lambda sid: (OUTPUT,))
    monkeypatch.setattr(d3, "step_record", lambda sid: {"entries": {}})


@pytest.mark.parametrize("case,produced,status", [
    ("met", True, "PASS"), ("violated", True, "FAIL"),
    ("missing", False, "BLOCKED"), ("prelayout", False, "BLOCKED"),
    ("untracked", False, "BLOCKED"), ("already_captured", False, None),
])
def test_new_output_requires_real_measured_production(monkeypatch, case, produced, status):
    _new_entry(monkeypatch)
    calls = []
    actual = runner._run_declared_signoff_gate

    def observe(project, name, program, out_rel, extra_argv=()):
        assert not (project / out_rel).exists()
        row = actual(project, name, program, out_rel, extra_argv)
        calls.append(row)
        return row

    monkeypatch.setattr(runner, "_run_declared_signoff_gate", observe)
    with d3._probe_run_root("d3_new_measured_") as (root, commit):
        (root / "tracked.txt").write_text("tracked input population\n")
        commit("tracked.txt")
        if case != "missing":
            target = root / INPUT
            target.parent.mkdir(parents=True)
            body = _ARCH if case == "violated" else _MET
            if case == "prelayout":
                body = body.replace("POST_ROUTE_SPEF", "PRE_LAYOUT_ESTIMATE")
            target.write_text(body)
            if case != "untracked":
                commit(INPUT)
        if case == "already_captured":
            old = root / OUTPUT
            old.parent.mkdir(parents=True)
            old.write_text('{"verdict":"PASS","historical":true}\n')
            commit(OUTPUT)
        d3._probe_only(monkeypatch, "tracked-probe", root)
        missing, details, _unmeasured = d3.audit_step("23")
        assert (not missing) is produced, (missing, details)
        if status is None:
            assert calls == []
        else:
            assert len(calls) == 1 and calls[0].status == status
        if produced:
            assert "FRESH_PRODUCER" in details[0]
            assert "historical capture remains NOT_MEASURED" in details[0]
            assert f"design verdict={status}" in details[0]
        # No live execution may modify the original run/capture.
        assert (root / OUTPUT).exists() is (case == "already_captured")
        if case == "already_captured":
            assert json.loads((root / OUTPUT).read_text())["historical"] is True


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
