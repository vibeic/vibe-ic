import json
from pathlib import Path

import pytest

import tapeout_declaration_gen as declaration
import tapeout_precheck as precheck


def measured(top="unit", box=(0, 0, 100, 100)):
    return {"verdict": "PASS", "exit_code": 0, "measurement": {
        "tool": "KLayout", "top_cell": top, "database_unit_um": .001,
        "bbox_um": list(box), "width_um": box[2] - box[0],
        "height_um": box[3] - box[1], "polygon_count": 2,
        "zero_area_polygon_count": 0}}


@pytest.mark.parametrize("top,box,status", [
    ("unit", (0, 0, 100, 100), "PASS"),
    ("other", (0, 0, 100, 100), "FAIL"),
    ("unit", (0, 0, 120, 100), "FAIL"),
])
def test_current_native_stream_needs_no_retired_component_reports(
        tmp_path, monkeypatch, top, box, status):
    gds = tmp_path / "final.gds"
    calls = []

    def read(project, stream=None, **kwargs):
        calls.append(stream)
        return measured(top, box)

    monkeypatch.setattr(declaration, "measure_final", read)
    config = {"DESIGN_NAME": "unit", "DIE_AREA": [0, 0, 100, 100]}
    result = precheck.execute(tmp_path, gds=gds, config=config,
                              directory=tmp_path / "native")
    assert calls == [gds]
    assert result["verdict"] == status
    assert result["measurement"]["polygon_count"] == 2
    assert not any("flow109/components" in json.dumps(check)
                   for check in result["checks"])
    assert "context_sha256" not in result
    assert config["DIE_AREA"] == [0, 0, 100, 100]


def test_declaration_bounds_are_not_replaced_with_native_config(tmp_path, monkeypatch):
    report = measured()
    report["declared_contract"] = {"answers": {
        "deliverable": "DIE", "top_cell": "unit", "database_unit_um": .001,
        "die_origin_um": [0, 0], "die_area_um": [0, 0, 200, 200]}}
    monkeypatch.setattr(declaration, "measure_final", lambda *args, **kwargs: report)
    result = precheck.execute(tmp_path, config={
        "DESIGN_NAME": "unit", "DIE_AREA": [0, 0, 100, 100]})
    assert result["verdict"] == "FAIL"
    assert report["declared_contract"]["answers"]["die_area_um"] == [0, 0, 200, 200]


def test_provider_without_native_report_stays_unmeasured(tmp_path, monkeypatch):
    target = tmp_path / "input/submission_template/provider_target.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"provider": "declared-provider"}))
    monkeypatch.setattr(declaration, "measure_final", lambda *args, **kwargs: measured())
    result = precheck.execute(tmp_path, config={
        "DESIGN_NAME": "unit", "DIE_AREA": [0, 0, 100, 100]})
    assert result["verdict"] == "NOT_MEASURED"
    assert any(check["check"] == "operator_precheck"
               and check["status"] == "NOT_MEASURED" for check in result["checks"])


def test_native_reader_failure_remains_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(declaration.subprocess, "run", lambda *args, **kwargs:
                        type("Completed", (), {"returncode": 1})())
    gds = tmp_path / "final.gds"
    gds.write_bytes(b"broken stream")
    report = declaration.measure_final(tmp_path, gds)
    assert report["verdict"] == "FAIL"
    assert report["exit_code"] == 1
    assert "gds_sha256" not in report


def test_absent_stream_did_not_run(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("KLayout must not be invoked without its input")

    monkeypatch.setattr(declaration.subprocess, "run", unexpected)
    report = declaration.measure_final(tmp_path, Path("missing.gds"))
    assert report["verdict"] == "NOT_MEASURED"
    assert "exit_code" not in report
