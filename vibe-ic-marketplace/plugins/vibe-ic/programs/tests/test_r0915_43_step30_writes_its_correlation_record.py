"""R-0915-43: the current Step-30 producer publishes its declared record.

The producer now delegates to path_spice_tool.run_current_step30. Measure the
same nine obligations through the actual producer/consumer boundary, rather
than pinning the old inline writer's spelling. Native processes are replaced
by the existing SOURCE_FIXTURE_ONLY fixture; this is software-contract proof,
never a measured SPICE or whole-IC qualification.
"""
import json

import pytest
import _path_layout as _pl
import spice_correlation_check as SCC
import phase3_one_shot_runner as R
import test_default_si_spice_power as fixture
import test_step30_r4_current_failures as r4


DECLARED = ("phase3/stage3/spice/correlation.json",
            "reports/phase3/spice_correlation.json")


def _read(project, relative):
    return json.loads((project / relative).read_text())


def _refusing_project(tmp_path, monkeypatch):
    project, folder, lib = fixture.project(tmp_path)
    def refuse(*args, **kwargs):
        raise fixture.LC.Refusal("LL_IMAGE_ABSENT", "SOURCE_FIXTURE_ONLY absent image")
    monkeypatch.setattr(fixture.LC, "resolve_image", refuse)
    return project, lib


def test_the_driver_writes_the_path_the_step_declares(tmp_path, monkeypatch):
    project, folder, lib = fixture.project(tmp_path)
    result = fixture.spice_produce(project, folder, lib, monkeypatch)
    assert result["status"] == "RAN", result
    for path in DECLARED:
        assert _read(project, path) == result["report"]
    assert SCC.main([str(project), "--json", str(project / "gate.json")]) == 0
    # The ordinary runner actually consumes the same boundary and names the
    # declared outputs. A helper-only positive would not prove this obligation.
    written, notes = [], []
    assert R._step30_tool_arm(project, fixture.pdk(lib), written, notes)
    assert all(str(project / path) in written for path in DECLARED)


def test_it_is_the_same_dict_and_never_a_second_summary(tmp_path, monkeypatch):
    project, folder, lib = fixture.project(tmp_path)
    result = fixture.spice_produce(project, folder, lib, monkeypatch)
    assert result["status"] == "RAN", result
    assert (project / DECLARED[0]).read_bytes() == (project / DECLARED[1]).read_bytes()
    # Disagreement in the projection must invalidate the strict consumer.
    fixture.put(project / DECLARED[0], {**result["report"], "verdict": "FAIL"})
    assert SCC.main([str(project), "--json", str(project / "gate.json")]) == 1
    assert _read(project, "gate.json")["summary"]["current_binding"] == "REFUSED"


def test_the_declared_path_is_the_first_one_this_modules_loader_reads(tmp_path):
    project = tmp_path / "p"
    declared = _pl.spice_dir(project) / "correlation.json"
    declared.parent.mkdir(parents=True)
    declared.write_text(json.dumps({"correlation": {"verdict": "PASS"}}))
    fixture.put(project / DECLARED[1], {"correlation": {"verdict": "FAIL"}})
    got = SCC._check_spice_correlation_json(project)
    assert got is not None and got["correlation"]["verdict"] == "PASS"


def test_the_record_carries_what_was_correlated_the_numbers_and_a_verdict(tmp_path, monkeypatch):
    project, folder, lib = fixture.project(tmp_path)
    r4.correlation_tool(project, folder, lib, monkeypatch)
    result = SCC.run_installed_pdk_path_correlation(project, str(lib))
    assert result["status"] == "RAN", result
    report = _read(project, DECLARED[0])
    row = report["detail"]["ngspice"]["base"]["paths"][0]
    assert (row["startpoint"], row["endpoint"]) == ("launch", "capture")
    assert row["sta_ns"] == 1.0 and row["spice_ns"] == 1.15
    assert row["error_pct"] == pytest.approx(15.0)
    assert row["tolerance_pct"] == 10.0 and row["verdict"] == "MISMATCH"
    assert report["verdict"] == "FAIL"
    assert report["current_subject"]["stage"] == "post_route_extracted"
    gate = SCC.run_audit(project)
    assert not gate.passed and gate.summary["measurement"] == "MEASURED"
    assert gate.summary["verdict"] == "FAIL"


def test_the_runner_writes_a_named_refusal_at_the_declared_path(tmp_path, monkeypatch):
    project, lib = _refusing_project(tmp_path, monkeypatch)
    written, notes = [], []
    assert not R._step30_tool_arm(project, fixture.pdk(lib), written, notes)
    assert all(str(project / path) in written for path in DECLARED)
    assert str(project / "reports/phase2/gates/spice_correlation.json") in written
    gate = _read(project, "reports/phase2/gates/spice_correlation.json")
    assert gate["passed"] is False
    assert gate["summary"]["current_binding"] == "REFUSED"


def test_the_refusal_and_the_disclosure_are_the_same_payload(tmp_path, monkeypatch):
    project, lib = _refusing_project(tmp_path, monkeypatch)
    result = SCC.run_installed_pdk_path_correlation(project, str(lib))
    assert result["status"] == "ERROR", result
    assert (project / DECLARED[0]).read_bytes() == (project / DECLARED[1]).read_bytes()
    assert _read(project, DECLARED[0])["reason"] == result["reason"]


def test_the_refusal_carries_a_verdict_and_a_reason(tmp_path, monkeypatch):
    project, lib = _refusing_project(tmp_path, monkeypatch)
    result = SCC.run_installed_pdk_path_correlation(project, str(lib))
    report = _read(project, DECLARED[0])
    assert report["verdict"] == "NOT_MEASURED"
    assert report["reason"] == result["reason"] and "LL_IMAGE_ABSENT" in report["reason"]
    assert report["correlation_ran"] is False
    assert report["reason_class"] == "EXECUTION_ERROR"
    assert SCC.main([str(project), "--json", str(project / "gate.json")]) == 1


def test_a_record_the_run_already_produced_is_left_alone(tmp_path, monkeypatch):
    project, folder, lib = fixture.project(tmp_path)
    result = fixture.spice_produce(project, folder, lib, monkeypatch, verdict="FAIL")
    assert result["status"] == "RAN"
    before = {path: (project / path).read_bytes() for path in DECLARED}
    SCC._persist_declared_refusal(project, {"status": "ERROR", "reason": "companion failed"})
    assert {path: (project / path).read_bytes() for path in DECLARED} == before
    gate = SCC.run_audit(project)
    assert not gate.passed and gate.summary["verdict"] == "FAIL"
    assert gate.summary["measurement"] == "MEASURED"


def test_the_declared_refusal_is_only_written_when_the_correlation_did_not_run(tmp_path, monkeypatch):
    project, folder, lib = fixture.project(tmp_path)
    assert fixture.spice_produce(project, folder, lib, monkeypatch)["status"] == "RAN"
    def forbidden(*args, **kwargs):
        pytest.fail("the successful current producer must not publish a refusal")
    monkeypatch.setattr(SCC, "_persist_declared_refusal", forbidden)
    written, notes = [], []
    assert R._step30_tool_arm(project, fixture.pdk(lib), written, notes)
    for path in DECLARED:
        assert _read(project, path)["verdict"] == "PASS"
    assert not (project / "phase3/stage3/spice/spice_correlation_not_run.json").exists()


@pytest.mark.parametrize("reached", ["empty", "spef_only", "sta_only", "refusal", "receipt", "products"])
def test_upstream_skip_never_hides_a_reached_step30(tmp_path, reached):
    project = tmp_path / "p"
    project.mkdir()
    if reached == "spef_only":
        fixture.write(project / "phase3/stage3/extracted/p.spef", '*SPEF "IEEE 1481-1998"\n')
    elif reached == "sta_only":
        fixture.write(project / "phase3/stage3/sta/post_route.rpt", "reached STA\n")
    elif reached in ("refusal", "receipt"):
        relative = DECLARED[0] if reached == "refusal" else "reports/phase3/spice_correlation.current.json"
        fixture.put(project / relative, {"verdict": "NOT_MEASURED"})
    elif reached == "products":
        fixture.write(project / "phase3/tool_arms/30/ngspice/base/path.log", "failed native execution\n")
    result = SCC.run_audit(project)
    if reached in ("empty", "spef_only"):
        assert result.passed and result.summary["skipped"] is True
        assert result.summary["current_binding"] == "NOT_REACHED"
        assert SCC.main([str(project), "--json", str(project / "gate.json")]) == 2
    else:
        assert not result.passed and result.summary["skipped"] is False
        assert result.summary["current_binding"] == "REFUSED"
        assert SCC.main([str(project), "--json", str(project / "gate.json")]) == 1
