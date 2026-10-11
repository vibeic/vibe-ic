"""A Phase-3 window dispatches one real runner site without disturbing inputs."""
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import phase3_one_shot_runner as p3


def _window_record(project: Path, category: str, name: str) -> Path:
    matches = list((project / "reports" / category / "windows").glob(f"*/{name}"))
    assert len(matches) == 1, matches
    return matches[0]



def _retained_step37_files(project):
    index = json.loads((project / 'steps/index.json').read_text())
    assert {str(row['id']) for row in index['steps']} == {'37'}
    row = index['steps'][0]
    assert re.fullmatch(r'phase3/stage4/37_gdsii_output_after_routed_layout_pre_stream_admi_\d{8}T\d{6}_\d{6}Z', row['folder'])
    folder = project / 'steps' / row['folder']
    record = json.loads((folder / 'outputs.json').read_text())
    assert record['id'] == '37' and record['observation_only'] is True
    allowed = {str((folder / name).relative_to(project)) for name in ('outputs.json', 'written.json')}
    for output in record['outputs']:
        source = project / output['rel']
        snapshot = folder / output['snapshot']
        assert snapshot.is_file() and not snapshot.is_symlink()
        assert snapshot.read_bytes() == source.read_bytes()
        allowed.add(str(snapshot.relative_to(project)))
    return allowed


def test_real_runner_cli_exposes_window():
    proc = subprocess.run([sys.executable, str(Path(p3.__file__)), "--help"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "--entry-step" in proc.stdout and "--exit-step" in proc.stdout


def test_front_door_refusal_does_not_write_into_window_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "input.txt").write_text("unadmitted project")
    before = p3._phase3_file_manifest(project)
    cp = subprocess.run(
        [sys.executable, str(Path(p3.__file__)), str(project),
         "--entry-step", "37.4", "--exit-step", "37.4"],
        capture_output=True, text=True, check=False)
    assert cp.returncode != 0
    assert "REFUSED" in cp.stderr
    assert p3._phase3_file_manifest(project) == before


def test_gds_window_preserves_outside_files_and_marks_downstream(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import _pdk
    project = tmp_path / "project"
    pnr = p3._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    (project / "phase3" / "synth").mkdir(parents=True)
    (pnr / "top.def").write_text("supplied route\n")
    (pnr / "routed.def").write_text("supplied route\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10\n")
    netlist = project / "phase2/stage2/synth/top_synth.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module top(); endmodule\n")
    (project / "phase3" / "synth" / "top_synth.v").write_text("supplied netlist\n")
    (project / "reports" / "phase3").mkdir(parents=True)
    (project / "reports" / "phase3" / "drc.rpt").write_text("old DRC\n")
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "bounded37")
    whole_report = project / "reports/orchestrator/phase3_one_shot.json"
    whole_audit = project / "reports/audit/phase23_completion_audit.json"
    whole_report.parent.mkdir(parents=True)
    whole_audit.parent.mkdir(parents=True)
    whole_report.write_text('{"verdict":"PASS","whole_flow":true}\n')
    whole_audit.write_text('{"verdict":"PASS","scope":{"whole_flow":true}}\n')
    whole_report_bytes = whole_report.read_bytes()
    whole_audit_bytes = whole_audit.read_bytes()
    pdk = _pdk(project)
    basis, error = p3._layout_basis(project, "top", pdk, "")
    assert not error, error
    (project / "reports/phase3/prestream_gate.json").write_text(
        json.dumps({"verdict": "PASS", "layout_digest": basis}))
    before = p3._phase3_file_manifest(project)

    # This is the EDA container's stream-out write.  Dispatch, preflight,
    # manifest comparison, stale marking and report publication are real.
    def streamout(project_, top, pdk, container):
        out = p3._pl.pnr_dir(project_) / f"{top}.gds"
        out.write_bytes(b"new layout")
        return p3.StepResult("gds", "PASS", 0.0, "streamed", [str(out)])

    monkeypatch.setattr(p3, "step_gds", streamout)
    args = SimpleNamespace(entry_step="37", exit_step="37", container="")
    selected = p3._phase3_window_sites("37", "37")
    assert selected == ["gds"]
    assert p3._run_phase3_window(project, "top", pdk, args, selected) == 1

    assert whole_report.read_bytes() == whole_report_bytes
    assert whole_audit.read_bytes() == whole_audit_bytes
    assert (project / "reports/orchestrator/windows/bounded37/phase3_one_shot.json").is_file()
    assert (project / "reports/audit/windows/bounded37/phase23_completion_audit.json").is_file()

    after = p3._phase3_file_manifest(project)
    changed = {name for name in set(before) | set(after)
               if before.get(name) != after.get(name)}
    allowed_reports = {
        "reports/audit/windows/bounded37/phase23_completion_audit.json",
        # R-0929-DRV-IDENTITY / review wave 58: a window is a run; it records
        # its own run identity and claims the DRV stage receipts it binds.
        "reports/phase3/drv_run_identity.json",
        "reports/phase3/drv_stages/run.json",
        # a14cafaa2: the selected steps' view is refreshed in the project.
        "reports/audit/steps_view.json",
        "reports/audit/windows/bounded37/steps_view.json",
        "reports/audit/windows/bounded37/publication.json",
        "reports/orchestrator/windows/bounded37/phase3_one_shot.json",
        "reports/phase3/gds_admission.json",
        "reports/write_ledger.json",
        "steps/index.json",
    }
    assert set(changed) <= allowed_reports | _retained_step37_files(project) | {
        "phase3/stage3/pnr/top.gds", "phase3/stage4/gds/top.gds"}, changed
    assert after["phase3/stage3/pnr/top.def"] == before["phase3/stage3/pnr/top.def"]
    assert after["phase3/synth/top_synth.v"] == before["phase3/synth/top_synth.v"]
    assert after["reports/phase3/drc.rpt"] == before["reports/phase3/drc.rpt"]
    assert "phase3/stage3/pnr/top.gds" in after
    assert after["phase3/stage4/gds/top.gds"] == after["phase3/stage3/pnr/top.gds"]
    assert p3._ga.admitted_gds(project, pnr / "top.gds", basis)
    report = json.loads(_window_record(project, "orchestrator",
                                       "phase3_one_shot.json").read_text())
    assert report["bounded"] is True
    assert report["steps_view"]["status"] == "OK"
    assert report["audit_verdict"] == "FAIL"
    assert report["verdict"] == "FAIL"
    audit = json.loads(_window_record(project, "audit",
                                      "phase23_completion_audit.json").read_text())
    assert audit["scope"]["whole_flow"] is False
    assert audit["audit_kind"] == "bounded_full_declared_gates"
    assert audit["declared_gate_checks"]["37"]["status"] == "FAIL"
    assert any("GATE EVIDENCE" in reason
               for reason in audit["declared_gate_checks"]["37"]["reasons"])
    assert "gate_verdict" not in audit["declared_output_checks"]["37"]
    assert audit["declared_output_checks"]["37"]["missing_outputs"]
    assert report["stale_downstream"]["drc"]["status"] == "NOT_MEASURED"
    assert "gds" in report["stale_downstream"]["drc"]["reason"]
    assert report["stale_downstream"]["lvs"]["status"] == "NOT_MEASURED"
    window_bytes = _window_record(project, "orchestrator",
                                  "phase3_one_shot.json").read_bytes()
    assert p3._run_phase3_window(project, "top", pdk, args, selected) == 2
    assert _window_record(project, "orchestrator",
                          "phase3_one_shot.json").read_bytes() == window_bytes


def test_publication_uses_enclosing_window_id_when_clock_advances(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    calls = []

    def advancing_id():
        calls.append(None)
        return "started" if len(calls) == 1 else "later"

    def metric_writer(isolated):
        for rel in ("phase3/final/metrics.json",
                    "reports/phase3/signoff_metrics_aggregate.json"):
            out = isolated / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text('{"verdict":"PASS"}\n')
        return p3.StepResult("signoff_metrics_aggregate", "PASS", 0.0,
                             "wrote metrics", [])

    monkeypatch.setattr(p3, "_phase3_window_run_id", advancing_id)
    monkeypatch.setattr(p3, "step_signoff_metrics_aggregate", metric_writer)
    args = SimpleNamespace(entry_step="37.4", exit_step="37.4", container="")
    p3._run_phase3_window(project, "top", object(), args,
                          ["signoff_metrics_aggregate"])

    report = project / "reports/orchestrator/windows/started/phase3_one_shot.json"
    publication = project / "reports/audit/windows/started/publication.json"
    assert len(calls) == 1
    assert report.is_file()
    assert publication.is_file()
    receipt = json.loads(publication.read_text())
    assert receipt["status"] == "PUBLISHED"
    assert receipt["window_run_id"] == "started"


def test_every_canonical_phase3_step_is_accepted_from_yaml():
    import yaml
    import flow_compliance_check as fcc
    flow = yaml.safe_load(fcc.DEFAULT_FLOW_DEF.read_text())
    ids = [str(step["id"]) for step in flow["steps"]
           if step.get("stage") in ("stage3", "stage4")]
    assert ids
    for sid in ids:
        assert p3._phase3_window_sites(sid, sid), sid
    assert p3._phase3_window_sites("18", "18") == ["default_pnr"]
    assert p3._phase3_window_sites("15.5ic", "15.5ic") == ["default_pnr"]
    assert p3._phase3_window_sites("24", "24") == ["default_backend"]
    assert p3._phase3_window_sites("37.4", "37.4") == [
        "signoff_metrics_aggregate"]
    assert p3._phase3_window_sites("37", "37") == ["gds"]
    assert p3._phase3_window_sites("31", "31") == ["drc", "lvs"]
    assert p3._phase3_window_sites("36", "36") == ["tapeout_checklist"]
    assert p3._phase3_window_sites("37.3", "37.3") == ["gds_xor"]
    assert p3._phase3_window_sites("38", "38") == ["foundry_handoff"]


def test_changed_route_cannot_sign_off_old_gds(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "phase3" / "synth").mkdir(parents=True)
    (project / "phase3" / "pnr").mkdir(parents=True)
    (project / "phase3" / "synth" / "top_synth.v").write_text("netlist")
    (project / "phase3" / "pnr" / "top.gds").write_bytes(b"old GDS")
    (project / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (project / "phase2" / "stage2" / "synth" /
     "post_dft_netlist.v").write_text("netlist")
    # The route must actually run before this test can exercise invalidation.
    constraints = project / "phase2/stage2/constraints"
    constraints.mkdir(parents=True)
    (constraints / "top.sdc").write_text(
        "create_clock -name clk -period 10 [get_ports clk]\n")

    def route(project_, top, pdk, container, **kwargs):
        out = project_ / "phase3" / "pnr" / f"{top}.def"
        out.write_text("new route")
        canonical = project_ / "phase3" / "stage3" / "pnr" / "routed.def"
        canonical.parent.mkdir(parents=True)
        canonical.write_text("new route")
        return p3.StepResult("pnr", "PASS", 0.0, "routed", [str(out)])

    def should_not_run(*args, **kwargs):
        raise AssertionError("PV consumed the old GDS")

    monkeypatch.setattr(p3, "step_pnr", route)
    monkeypatch.setattr(p3, "step_drc", should_not_run)
    monkeypatch.setattr(p3, "step_lvs", should_not_run)
    args = SimpleNamespace(entry_step="15", exit_step="31", container="fake-eda",
                           die_um="auto", util=0.3, spare_density=0.02)
    # Explicitly exercise dependency blocking inside the dispatch loop: the
    # public selector now chooses the enclosing unit for this mixed span.
    selected = ["pnr", "drc", "lvs"]
    assert p3._run_phase3_window(project, "top", object(), args, selected) == 1
    report = json.loads(_window_record(project, "orchestrator",
                                       "phase3_one_shot.json").read_text())
    assert report["steps"][-1]["name"] == "drc"
    assert report["steps"][-1]["status"] == "NOT_MEASURED"
    assert "gds is outside this window" in report["steps"][-1]["detail"]
    assert (project / "phase3" / "pnr" / "top.gds").read_bytes() == b"old GDS"


def test_real_gds_step_with_container_write_keeps_other_stage_files(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import _pdk
    project = tmp_path / "project"
    # This fixture exercises the existing direct KLayout recipe publisher.
    # Select that tool explicitly, rather than asking the synthetic test PDK
    # to provide a LibreLane fill handoff it has never produced.
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({"steps": {"34": "direct", "37": "direct"}}))
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "realgds")
    pnr = project / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "top.def").write_text("DESIGN top ;\nEND DESIGN\n")
    (pnr / "routed.def").write_text("DESIGN top ;\nEND DESIGN\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10\n")
    netlist = project / "phase2/stage2/synth/top_synth.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module top(); endmodule\n")
    (project / "phase3" / "synth").mkdir()
    (project / "phase3" / "synth" / "top_synth.v").write_text("netlist")
    (project / "reports" / "phase3").mkdir(parents=True)
    (project / "reports" / "phase3" / "drc.rpt").write_text("prior DRC")
    # The real step_gds builds its script and reports. Only the container's
    # stream-out file write is faked; no Phase-3 dispatch function is replaced.
    monkeypatch.setattr(p3, "_magic_def_to_gds",
                        lambda *a, **k: (False, "unavailable"))

    calls = []

    def container(_name, _cmd, *args, **kwargs):
        from test_gds_substance_check import _real_gds
        calls.append(_cmd)
        for output in kwargs.get("outputs", []):
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(_real_gds(n_cells=20, n_boundaries=200))
        return 0, "streamed", ""

    monkeypatch.setattr(p3, "_docker_exec", container)
    pdk = _pdk(project)
    basis, error = p3._layout_basis(project, "top", pdk, "")
    assert not error, error
    gate = project / "reports/phase3/prestream_gate.json"
    gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": basis}))
    before = p3._phase3_file_manifest(project)
    args = SimpleNamespace(entry_step="37", exit_step="37", container="")
    p3._run_phase3_window(project, "top", pdk, args, ["gds"])
    after = p3._phase3_file_manifest(project)
    changed = {name for name in set(before) | set(after)
               if before.get(name) != after.get(name)}
    allowed_reports = {
        "reports/audit/windows/realgds/phase23_completion_audit.json",
        # R-0929-DRV-IDENTITY / review wave 58: a window is a run; it records
        # its own run identity and claims the DRV stage receipts it binds.
        "reports/phase3/drv_run_identity.json",
        "reports/phase3/drv_stages/run.json",
        # a14cafaa2: the selected steps' view is refreshed in the project.
        "reports/audit/steps_view.json",
        "reports/audit/windows/realgds/steps_view.json",
        "reports/audit/windows/realgds/publication.json",
        "reports/orchestrator/windows/realgds/phase3_one_shot.json",
        "reports/phase3/gds_admission.json",
        "reports/write_ledger.json",
        "steps/index.json",
    }
    # Step 37's own declared outputs: the stream, its transcript, and the
    # record plus recipe that step 37.3 re-streams from.
    assert set(changed) <= allowed_reports | _retained_step37_files(project) | {
        "phase3/stage3/pnr/top.gds", "phase3/stage3/pnr/stream_out.log",
        "phase3/stage3/pnr/top.stream_inputs.json",
        "phase3/stage3/pnr/stream_out.py",
        "phase3/stage4/gds/top.gds"}, sorted(changed)
    assert "phase3/stage3/pnr/stream_out.py" in after, (
        "the stream-input record pins the recipe bytes, so the bounded-window "
        "publisher must carry that exact recipe with the record"
    )
    assert calls, "the real GDS step never reached the container"
    assert p3._ga.admitted_gds(project, pnr / "top.gds", basis)
    assert any(name.endswith(".gds") for name in after)
    assert after["phase3/stage3/pnr/top.def"] == before["phase3/stage3/pnr/top.def"]
    assert after["phase3/synth/top_synth.v"] == before["phase3/synth/top_synth.v"]
    assert after["reports/phase3/drc.rpt"] == before["reports/phase3/drc.rpt"]


def test_gds_window_without_pass_gate_returns_named_refusal(tmp_path):
    from test_phase3_postpnr_disclosure_and_gds_guard import _pdk
    project = tmp_path / "project"
    pnr = p3._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    for name, data in (("top.def", "DESIGN top ;\nEND DESIGN\n"),
                       ("routed.def", "DESIGN top ;\nEND DESIGN\n"),
                       ("constraint.sdc", "create_clock -period 10\n")):
        (pnr / name).write_text(data)
    netlist = project / "phase2/stage2/synth/top_synth.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module top(); endmodule\n")
    row = p3.step_gds(project, "top", _pdk(project), "")
    assert row.status == "NOT_MEASURED"
    assert row.reason_class == p3._V.ReasonClass.UPSTREAM_FAILED.value
    assert "pre-stream gate refused" in row.detail
    assert not (pnr / "top.gds").exists()


def test_post_pnr_window_refuses_a_stale_gds_before_drc(tmp_path, monkeypatch):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _pdk, TOP, NEW_DIE, NEW_UTIL,
    )
    project = _project(tmp_path / "project", cached_die=NEW_DIE,
                       cached_util=NEW_UTIL)
    receipt = p3._ga.admission_path(project)
    record = json.loads(receipt.read_text())
    record["layout_digest"] = "0" * 64
    receipt.write_text(json.dumps(record))

    def wrong_consumer(*args, **kwargs):
        raise AssertionError("DRC consumed an unadmitted GDS")

    monkeypatch.setattr(p3, "step_drc", wrong_consumer)
    args = SimpleNamespace(entry_step="31", exit_step="31", container="",
                           die_um=NEW_DIE, util=NEW_UTIL, spare_density=0.02)
    p3._run_phase3_window(project, TOP, _pdk(project), args, ["drc", "lvs"])
    report = json.loads(_window_record(project, "orchestrator",
                                       "phase3_one_shot.json").read_text())
    assert report["steps"][0]["name"] == "drc"
    assert report["steps"][0]["status"] == "NOT_MEASURED"
    assert "unadmitted routed GDS" in report["steps"][0]["detail"]
