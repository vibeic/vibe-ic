"""A bounded Phase-3 continuation refreshes its selected output attribution."""

import json
from pathlib import Path
from types import SimpleNamespace

import phase3_one_shot_runner as p3


def test_window_publishes_fresh_step32_write_record_before_gate_audit(
        tmp_path, monkeypatch):
    project = tmp_path / "spm"
    output = project / "phase3/stage3/postroute_timing_repair"
    output.mkdir(parents=True)
    # The front-door run left a write record before this continuation's
    # decision existed. The bounded run must replace that selected record.
    prior = p3._pl.emit_steps_view(
        project, p3.PROGRAMS_DIR, runner="phase3_one_shot_runner",
        only_steps={"32"})
    assert prior["status"] == "OK"
    steps_root = project / "steps"
    prior_index = json.loads((steps_root / "index.json").read_text())
    prior_row, = (row for row in prior_index["steps"] if row["id"] == "32")
    prior_folder = steps_root / prior_row["folder"]

    def current_write_record():
        # Versions are retained; glob order can select the old empty record.
        # The published index, rather than time or directory order, owns
        # which version the gate must consume.
        index = json.loads((steps_root / "index.json").read_text())
        row, = (row for row in index["steps"] if row["id"] == "32")
        folder = steps_root / row["folder"]
        assert folder != prior_folder
        written = json.loads((folder / "written.json").read_text())
        assert any(row["rel"].endswith("postroute_timing_repair_decision.json")
                   for row in written["produced"])
        return folder

    gate_audit = p3._phase3_window_full_gate_audit
    audited_folders = []

    def audit_after_publication(subject, step_ids):
        assert subject == project
        assert step_ids == {"32"}
        audited_folders.append(current_write_record())
        return gate_audit(subject, step_ids)

    def eda_writes(isolated, _copy, _cmd):
        target = isolated / "phase3/stage3/postroute_timing_repair"
        target.mkdir(parents=True, exist_ok=True)
        (target / "postroute_timing_repair_decision.json").write_text(
            json.dumps({"repair_needed": True, "action": "input_route_kept"}) + "\n")
        (target / "repair_log.json").write_text(
            json.dumps({"changes": [], "re_verified": False}) + "\n")
        report = p3._pl.report_path(isolated, "phase3_one_shot.json")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"verdict": "FAIL"}) + "\n")
        return SimpleNamespace(rc=1, stalled=False, out="", err="residual fanout",
                               elapsed_s=1.0, outcome="natural"), Path("eda.stderr")

    monkeypatch.setattr(p3, "_phase3_enclosing_supervised", eda_writes)
    monkeypatch.setattr(p3, "_phase3_window_full_gate_audit", audit_after_publication)
    args = SimpleNamespace(entry_step="32", exit_step="32", container="")
    assert p3._run_phase3_window(
        project, "spm", SimpleNamespace(name="gf180mcuD"), args,
        ["enclosing_phase3"]) == 1

    assert audited_folders == [current_write_record()]
    assert json.loads((prior_folder / "written.json").read_text())["produced"] == []
    # The failed physical decision remains failed; attribution cannot turn
    # residual fanout into a passing design verdict.
    # The window's audit is its own record, beside the whole-flow one.
    audit = json.loads(next((project / "reports/audit/windows").glob(
        "*/phase23_completion_audit.json")).read_text())
    assert audit["declared_gate_checks"]["32"]["status"] == "FAIL"
