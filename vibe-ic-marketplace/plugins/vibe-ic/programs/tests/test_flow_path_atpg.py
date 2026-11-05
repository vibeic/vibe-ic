"""Native path-delay inputs, result limits and incomplete SAT output handling."""

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
import path_delay_fault_atpg_run as pdf


@pytest.mark.parametrize("code,verdict,coverage,expected", [
    (0, "PASS", 100, "PASS"), (0, "PASS", 70, "FAIL"),
    (1, "ERROR", None, "FAIL"), (0, "NOT_APPLICABLE", None, "NOT_MEASURED"),
    (2, "NOT_MEASURED", None, "NOT_MEASURED"),
])
def test_path_row_reads_native_result(tmp_path, monkeypatch, code, verdict, coverage, expected):
    netlist, sdc, spef, library = [tmp_path / name for name in ("core.v", "clock.sdc", "core.spef", "cells.lib")]
    for path in (netlist, sdc, spef, library):
        path.write_text("")
    calls = []

    def run(project, **kwargs):
        calls.append(kwargs)
        assert kwargs["sta_netlist"] == "core.v" and kwargs["spef"] == "core.spef"
        assert kwargs["k"] == pdf.DEFAULT_K and kwargs["floor"] == pdf.PDF_FLOOR_DEFAULT
        assert kwargs["timing_fraction"] == pdf.TIMING_FRACTION_DEFAULT
        assert kwargs["timing_source"] == {"corner": "nom_tt", "liberties": [str(library)]}
        assert "native_" in kwargs["flat_rel"]
        return code, {"verdict": verdict, "pdf_sensitised_coverage_pct": coverage}

    monkeypatch.setattr(pdf, "run_pdf_atpg", run)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"] if row["name"] == "path_delay_atpg")
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", row["tool"], {},
        state={"nl": str(netlist), "sdc": str(sdc), "spef": {"nom_*": str(spef)}},
        config={"DESIGN_NAME": "core", "CLOCK_PORT": "clk", "DEFAULT_CORNER": "nom_tt",
                "LIB": {"*_tt": [str(library)]}}))
    assert len(calls) == 1
    checks = [{**check, "limit": {"min": 80}} for check in row["checks"]]
    measured = engine.measure(checks, native.metrics, {}, {"requires_path_atpg": True})
    assert engine.evaluate(native, measured) == expected


def test_generated_sta_script_uses_local_input_paths(tmp_path, monkeypatch):
    library = tmp_path / "cells.lib"
    library.write_text("")
    monkeypatch.setattr(pdf._tdf._CE, "no_container_route", lambda: True)

    def run(project, command, **kwargs):
        text = (project / "phase2/stage2/dft/pdf/_pdf_sta.tcl").read_text()
        assert "/work/" not in text
        assert str(project / "routed.v") in text
        (project / "phase2/stage2/dft/pdf/sta_paths.rpt").write_text("Startpoint: ff0\n")
        return 0, "", ""

    monkeypatch.setattr(pdf._tdf, "_run_in_docker", run)
    assert pdf._run_opensta_paths(tmp_path, "routed.v", "clock.sdc", "routed.spef",
        str(library), "core", 32, None, 1800)[0]


@pytest.mark.parametrize("complete,code,expected", [(True, 0, 0), (False, 0, 2), (True, 1, 1)])
def test_pdf_requires_native_grades_before_reporting_coverage(tmp_path, monkeypatch, complete, code, expected):
    for name in ("netlist.v", "clock.sdc", "routed.spef", "flat.v"):
        (tmp_path / name).write_text("create_clock -period 20 [get_ports clk]\n")
    monkeypatch.setattr(pdf._tdf, "_liberty_structure_text", lambda *a, **k: ("", "unit"))
    monkeypatch.setattr(pdf._tdf, "_ensure_cut", lambda *a, **k: (True, "unit"))
    monkeypatch.setattr(pdf._tdf, "parse_cut_ports", lambda *a: ("core", [("a", 1)], [("z", 1)], [("ff0", "d", "q")]))
    monkeypatch.setattr(pdf, "_run_opensta_paths", lambda *a, **k: (True, "", "unit"))
    monkeypatch.setattr(pdf, "parse_sta_paths", lambda *a: [{"startpoint": "ff0", "endpoint": "z",
        "start_kind": "ff", "start_edge": "^", "end_kind": "po", "end_edge": "^", "arrival": 8,
        "slack": 12, "required": 20, "hops": []}])
    monkeypatch.setattr(pdf, "build_pdf_miter", lambda *a: "module unit; endmodule\n")
    monkeypatch.setattr(pdf._tdf, "_detect_sat_solver", lambda *a, **k: "")
    monkeypatch.setattr(pdf._tdf, "_run_in_docker", lambda *a, **k: (code, "unit SAT output", ""))
    grades = {("0", "nr"): "DET", **({("0", "r"): "DET"} if complete else {})}
    monkeypatch.setattr(pdf, "_parse_pdf_batch_log", lambda *a: (grades, {}))
    rc, result = pdf.run_pdf_atpg(tmp_path, "netlist.v", "cut.v", "flat.v", "netlist.v",
        "clock.sdc", "routed.spef", "cells.lib", "core", "clk", None, 16, 80, .3, None)
    assert rc == expected
    if expected:
        assert "pdf_sensitised_coverage_pct" not in result
    else:
        assert result["pdf_sensitised_coverage_pct"] == 100


@pytest.mark.parametrize("code,verdict,coverage,expected", [
    (0, "PASS", 100, "PASS"), (0, "PASS", 70, "FAIL"),
    (1, "ERROR", None, "FAIL"), (0, "NOT_APPLICABLE", None, "NOT_MEASURED"),
])
def test_sdd_row_reads_native_weighted_grade(tmp_path, monkeypatch, code, verdict, coverage, expected):
    import sdd_atpg_run as sdd

    source = tmp_path / "reports/phase2/dft/path_delay_coverage.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}")
    calls = []

    def run(project, args, pdk_dir):
        calls.append(args)
        assert args.dt2_json == str(source)
        assert args.margin_fraction == sdd.SDD_MARGIN_FRACTION_DEFAULT
        assert args.no_run_dt1 and args.margin_ns is None
        return code, {"verdict": verdict, "sdd_slack_weighted_coverage_pct": coverage,
                      "sdd_binary_strong_coverage_pct": 0}

    monkeypatch.setattr(sdd, "run_sdd_atpg", run)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"] if row["name"] == "small_delay_defect_atpg")
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", row["tool"], {},
        config={"DESIGN_NAME": "core", "CLOCK_PORT": "clk"}))
    assert len(calls) == 1
    checks = [{**check, "limit": {"min": 80}} for check in row["checks"]]
    measured = engine.measure(checks, native.metrics, {}, {"requires_sdd": True})
    assert engine.evaluate(native, measured) == expected
    if coverage is not None:
        assert native.metrics["sdd_graded_fault_coverage"] == coverage


def test_sdd_missing_upstream_measurement_is_unmeasured(tmp_path, monkeypatch):
    import sdd_atpg_run as sdd

    monkeypatch.setattr(sdd, "run_sdd_atpg", lambda *args: pytest.fail("No native timing report exists"))
    row = next(row for row in engine.read_json(engine.TABLE)["steps"] if row["name"] == "small_delay_defect_atpg")
    result = adapters.execute(tmp_path, tmp_path / "step", row["tool"], {},
                              config={"DESIGN_NAME": "core", "CLOCK_PORT": "clk"})
    assert not result["ran"]
