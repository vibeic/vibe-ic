"""Transition ATPG uses native views and grades the requested population."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
import transition_fault_atpg_run as tdf


@pytest.mark.parametrize("code,coverage,expected", [(0, 95, "PASS"), (1, 80, "FAIL"),
                                                  (2, None, "NOT_MEASURED")])
def test_selected_transition_adapter_reads_native_coverage(tmp_path, monkeypatch, code, coverage, expected):
    def run(self, argv, **kwargs):
        argv = list(map(str, argv))
        assert "--netlist" in argv and "--liberty" in argv
        report = Path(argv[argv.index("--json") + 1])
        data = {"verdict": "NOT_MEASURED" if code == 2 else "FAIL" if code else "PASS",
                "tdf_faults_total": 10, "tdf_faults_graded": 10}
        if coverage is not None:
            data.update(tdf_test_coverage_pct=coverage, tdf_fault_coverage_pct=50)
        report.write_text(json.dumps(data))
        self.records.append({"exit_code": code, "log": str(self.directory / "native.log")})
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(adapters.Commands, "run", run)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"] if row["name"] == "early_transition_atpg")
    result = adapters.execute(tmp_path, tmp_path / "step", row["tool"], {},
        state={"nl": str(tmp_path / "native.v")}, config={"CLOCK_PORT": "clk", "CLOCK_PERIOD": 20,
        "DESIGN_NAME": "core", "DEFAULT_CORNER": "nom", "LIB": {"*": [str(tmp_path / "native.lib")]}})
    native = engine.ToolResult(**result)
    checks = engine.measure([{**row["checks"][0], "limit": {"min": 90}}],
                             native.metrics, {}, {"early_atpg": True})
    assert engine.evaluate(native, checks) == expected
    if coverage is not None:
        assert native.metrics["early_fault_coverage"] == coverage
        assert native.metrics["tdf_fault_coverage_pct"] == 50


@pytest.mark.parametrize("maximum,stop_after,expected", [(0, None, "PASS"), (2, None, "PASS"),
                                                        (0, 1, "NOT_MEASURED")])
def test_fault_request_is_not_reduced_to_a_time_budget(tmp_path, monkeypatch, maximum, stop_after, expected):
    flat = ("module core(d,f0,q,\\f0.d );\ninput d;\ninput f0;\noutput q;\noutput \\f0.d ;\n"
            "wire n0;\nwire n1;\nwire n2;\nassign q=f0;\nassign \\f0.d =d;\nendmodule\n")
    (tmp_path / "mapped.v").write_text("module core;endmodule\n")
    monkeypatch.setattr(tdf, "_ensure_cut", lambda *a, **k: (True, "native cut"))
    monkeypatch.setattr(tdf, "_liberty_structure_text", lambda *a, **k: ("", "test library"))
    monkeypatch.setattr(tdf, "_detect_sat_solver", lambda *a, **k: "")

    def flatten(project, cut, liberty, top, output, *args, **kwargs):
        path = project / output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(flat)
        return True, "native flatten"

    batches = []

    def run(project, command, **kwargs):
        script = project / command.split("/work/", 1)[1]
        text = script.read_text()
        import re
        faults = re.findall(r"log VIBEICTDF (\S+) (STR|STF)", text)
        batches.append(faults)
        log = tdf._SETUP_MARKER + "\n"
        for net, kind in faults[:stop_after]:
            log += f"VIBEICTDF {net} {kind}\nSAT proof finished - model found: FAIL!\n"
        return 0, log, ""

    monkeypatch.setattr(tdf, "_gate_levelise", flatten)
    monkeypatch.setattr(tdf, "_run_in_docker", run)
    code, report = tdf.run_tdf_atpg(tmp_path, "mapped.v", "cut.v", "native.lib",
                                   "core", "clk", None, 90, maximum, None)
    assert report["verdict"] == expected
    assert report["tdf_faults_total"] == 6
    assert len(batches) == 1
    assert len(batches[0]) == (maximum or 6)
    if expected == "NOT_MEASURED":
        assert code == 2 and "tdf_test_coverage_pct" not in report
    else:
        assert code == 0 and report["tdf_faults_graded"] == (maximum or 6)


def test_generated_script_uses_local_files_in_native_yosys(tmp_path, monkeypatch):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    (tmp_path / "cut.v").write_text("module core(input a,output y);BUF cell0(.A(a),.Y(y));endmodule\n")
    library = tmp_path / "native.lib"
    library.write_text('library(unit){cell(BUF){area:1;pin(A){direction:input;}pin(Y){direction:output;function:"A";}}}')
    monkeypatch.setattr(tdf._CE, "no_container_route", lambda: True)

    def run(project, command, **kwargs):
        command = tdf._CE.localise_mounted_paths(command, [("/work", str(project))])
        process = subprocess.run(shlex.split(command), cwd=tmp_path, capture_output=True, text=True)
        return process.returncode, process.stdout, process.stderr

    monkeypatch.setattr(tdf, "_run_in_docker", run)
    okay, detail = tdf._gate_levelise(tmp_path, "cut.v", str(library), "core", "flat.v", None, 1800)
    assert okay, detail
    assert (tmp_path / "flat.v").is_file()
