"""Output activations are stimulus; independent fault simulation decides credit."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import fault_output_activation as activation
from _tool_probes import skip_not_verified


def metadata():
    return {"faultPoints": [r"\\r.d", "q"], "sa0Covered": [],
            "sa1Covered": ["r.d", "q"], "ratio": .5,
            "sa0Uncovered": ["wrong"], "sa1Uncovered": ["wrong"]}


def test_target_uses_covered_sets_and_normalized_names_not_bad_native_complements():
    outputs = [{"name": r"\r.d", "from": 0, "to": 0},
               {"name": "q", "from": 0, "to": 0}]
    assert activation.activation_targets(metadata(), outputs) == [("q", 1), ("r.d", 1)]


@pytest.mark.parametrize("change", ["outside", "ratio", "empty"])
def test_inconsistent_native_population_refuses(change):
    record = metadata()
    if change == "outside":
        record["sa1Covered"].append("not_a_fault")
    elif change == "ratio":
        record["ratio"] = 1
    else:
        record["faultPoints"] = []
    with pytest.raises(ValueError):
        activation.fault_sets(record)


def test_transport_preserves_bus_bits_and_unsigned_multiword_stimulus(tmp_path):
    ports = [{"name": "a", "from": 66, "to": 0},
             {"name": "b", "from": 0, "to": 2}]
    values = activation.stimulus_values(
        {"vector": [["+", 3, 4], ["+", 6]], "coverage": {"sa0": ["fake"]}}, ports)
    assert values == [(4 << 64) + 3, 6]
    assert activation.emit_transport(tmp_path, ports, [values, values]) == 1
    bits = (tmp_path / "patterns.test").read_text().split(": ")[1].strip()
    assert int(bits[:67][::-1], 2) == values[0]
    assert int(bits[67:][::-1], 2) == 6
    assert "coverage" not in (tmp_path / "patterns.test").read_text()


@pytest.mark.parametrize("wave", ["x4", "z4", "=4"])
def test_undefined_sat_stimulus_has_no_credit(wave):
    with pytest.raises(ValueError):
        activation.wave_values({"signal": [{"name": "a", "wave": wave,
                                            "data": ["1x", ""]}]},
                               [{"name": "a", "from": 0, "to": 0}])


@pytest.mark.parametrize("mode", ["valid", "zero_patterns", "changed_input", "unobservable_branch"])
def test_real_sat_seed_must_survive_native_fault_regrading(tmp_path, mode):
    # Both tools are required for this selected acceptance, never silently
    # replaced by mocked detection counts. Without them the acceptance is
    # NOT_VERIFIED (disclosed; blocking under VIBEIC_REQUIRE_EDA_VERIFICATION=1),
    # not a red that names the host instead of the code.
    missing = [t for t in ("yosys", "fault", "iverilog") if not shutil.which(t)]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no native fault regrading can run here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_fault_output_activation.py")
    project = tmp_path / "project"
    project.mkdir()
    (project / "cut.v").write_text(
        "module core(clk,a,y);\ninput clk;\ninput a;\noutput y;\n"
        "BUF u(.A(a),.Y(y));\nendmodule\n")
    model = project / "cells.v"
    model.write_text("module BUF(A,Y);input A;output Y;assign Y=A;endmodule\n")
    liberty = project / "cells.lib"
    liberty.write_text('library(t) { cell(BUF) { pin(A) { direction: input; } '
                       'pin(Y) { direction: output; function: "A"; } } }\n')
    points = ["a", "y", "u.A", "u.Y"]
    baseline = {"faultPoints": points[:], "sa0Covered": [], "sa1Covered": points[:],
                "ratio": .5}
    if mode == "unobservable_branch":
        (project / "cut.v").write_text(
            "module core(clk,a,b,y);\ninput clk;\ninput a;\ninput b;\noutput y;\n"
            "wire dead;\nBUF u(.A(b),.Y(y));\nBUF u_dead(.A(a),.Y(dead));\nendmodule\n")
        baseline["faultPoints"] = ["a", "b", "y", "u.A", "u.Y", "u_dead.A", "u_dead.Y"]
        baseline["sa1Covered"] = ["b", "y", "u.A", "u.Y"]
        baseline["ratio"] = 4 / 14
    (project / "coverage.yml").write_text(yaml.safe_dump(baseline))
    ports = lambda n, d: {"name": n, "from": 0, "to": 0, "polarity": d, "ordinal": 0}
    schema = {
        "inputs": [ports("a", "input")], "outputs": [ports("y", "output")],
        "coverageList": [{"vector": [["+", 0]]}]}
    if mode == "unobservable_branch":
        schema["inputs"].append(ports("b", "input"))
        schema["inputs"][1]["ordinal"] = 1
        schema["coverageList"] = [{"vector": [["+", 1], ["+", 0]]}]
    (project / "tv.json").write_text(json.dumps(schema))
    original = (project / "coverage.yml").read_bytes()

    def execute(argv):
        assert len(argv) == 1  # _run_docker's shell-fragment contract
        if "fault atpg" in argv[0] and mode == "zero_patterns":
            for pattern in project.rglob("patterns.test"):
                pattern.write_text("1: 0\n")
        p = subprocess.run(["bash", "-c", argv[0]], cwd=project,
                           capture_output=True, text=True, timeout=45)
        if "fault atpg" in argv[0] and mode == "changed_input":
            with (project / "cut.v").open("a") as f:
                f.write("// concurrent input edit\n")
        return p.returncode, p.stdout, p.stderr

    def run():
        return activation.recover(
            project, cut_rel="cut.v", tv_rel="tv.json", coverage_rel="coverage.yml",
            liberty=str(liberty), cell_model=str(model), clock="clk", target=95,
            execute=execute, mounted_root=str(project))

    if mode == "changed_input":
        with pytest.raises(ValueError, match="input changed"):
            run()
        assert (project / "coverage.yml").read_bytes() == original
        return
    result = run()
    assert result["yosys_rc"] == result["fault_rc"] == 0, result
    if mode == "unobservable_branch":
        # The baseline stimulus activates dead=1. Prove by native simulation
        # that a stuck-at-0 there changes dead, but cannot reach output y.
        tb = project / "activation_tb.v"
        tb.write_text('module tb; reg a=1,b=0; wire y; core dut(.clk(1\'b0),.a(a),.b(b),.y(y)); '
                      'initial begin #1; if(dut.dead!==1 || y!==0) $fatal(1,"not activated"); '
                      'force dut.u_dead.Y=0; #1; if(dut.dead!==0 || y!==0) $fatal(1,"observable"); '
                      '$display("ACTIVATED_WITHOUT_OBSERVABILITY"); $finish; end endmodule\n')
        p = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(project / "activation.vvp"),
                            str(model), str(project / "cut.v"), str(tb)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        p = subprocess.run(["vvp", str(project / "activation.vvp")], capture_output=True, text=True)
        (project / "activation.log").write_text(p.stdout + p.stderr)
        assert p.returncode == 0 and "ACTIVATED_WITHOUT_OBSERVABILITY" in p.stdout
        work = Path(result["work_dir"])
        wave = json.loads(next(work.glob("vector_*.json")).read_text())
        assert activation.wave_values(wave, [{"name": "b"}]) == [1]
        _, covered = activation.fault_sets(yaml.safe_load(
            Path(result["coverage_path"]).read_text()))
        assert all(not {"u_dead.A", "u_dead.Y"} & c for c in covered)
        assert result["total_faults"] == 14
        assert result["detected_faults"] == 8
        assert result["verdict"] == "NOT_RECOVERED"
        assert (project / "coverage.yml").read_bytes() == original
        return
    assert result["total_faults"] == 8
    assert result["coverage_pct"] == (50 if mode == "zero_patterns" else 100), result
    assert result["verdict"] == ("NOT_RECOVERED" if mode == "zero_patterns" else "RECOVERED")
    assert (project / "coverage.yml").read_bytes() == original


def test_recovery_cannot_lower_foundry_target(tmp_path):
    with pytest.raises(ValueError, match=">=95%"):
        activation.recover(tmp_path, cut_rel="cut.v", tv_rel="tv.json",
                           coverage_rel="c.yml", liberty="x", cell_model="x",
                           clock="clk", target=94, execute=None)
