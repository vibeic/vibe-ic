"""RTLLM capture: a legacy .v testbench keeps its Verilog dialect.

The fallback is deliberately scorer-side and narrow.  It is allowed only for a
syntax diagnostic owned by the benchmark testbench; the candidate still has to
compile and make the official simulation print its pass marker.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[2]
SCORER = PLUGIN / "benchmark" / "score_iverilog_tb.py"
REAL_FIXTURES = Path(__file__).parent / "fixtures" / "real_benchmark"


@pytest.fixture(scope="module")
def scorer():
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("iverilog + vvp are required")
    spec = importlib.util.spec_from_file_location("_rtllm_dialect_scorer", SCORER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _candidate(path: Path, broken: bool = False):
    path.write_text(
        "module dut(output y);\n"
        + ("assign y = ;\n" if broken else "assign y = 1'b1;\n")
        + "endmodule\n")


def _legacy_tb(path: Path, marker: str = "OFFICIAL PASS"):
    # `checker` is a legal Verilog-2005 instance name and a SystemVerilog
    # reserved keyword.  This reproduces RTLLM freq_divbyeven without carrying
    # a chip/design-specific branch in the scorer.
    shape = (REAL_FIXTURES /
             "legacy_verilog_reserved_instance_testbench.v").read_text()
    path.write_text(shape.replace("__MARKER__", marker))


def test_tb_owned_reserved_word_retries_g2005_and_requires_marker(
        scorer, tmp_path):
    dut = tmp_path / "dut.v"
    tb = tmp_path / "testbench.v"
    binp = tmp_path / "sim.vvp"
    _candidate(dut)
    _legacy_tb(tb)

    cp, dialect = scorer._compile_with_tb_dialect([dut, tb], tb, str(binp))
    assert cp.returncode == 0, cp.stderr
    assert dialect == "g2005"
    run = subprocess.run(["vvp", str(binp)], capture_output=True, text=True,
                         timeout=30)
    assert "OFFICIAL PASS" in run.stdout + run.stderr


def test_candidate_syntax_error_never_downgrades(scorer, tmp_path):
    dut = tmp_path / "dut.v"
    tb = tmp_path / "testbench.v"
    _candidate(dut, broken=True)
    _legacy_tb(tb)

    cp, dialect = scorer._compile_with_tb_dialect(
        [dut, tb], tb, str(tmp_path / "sim.vvp"))
    assert cp.returncode != 0
    assert dialect == "g2012"


def test_systemverilog_source_never_downgrades(scorer, tmp_path):
    dut = tmp_path / "dut.sv"
    tb = tmp_path / "testbench.v"
    _candidate(dut)
    _legacy_tb(tb)

    cp, dialect = scorer._compile_with_tb_dialect(
        [dut, tb], tb, str(tmp_path / "sim.vvp"))
    assert cp.returncode != 0
    assert dialect == "g2012"


def test_fallback_compile_without_pass_marker_stays_functional_fail(
        scorer, tmp_path):
    dataset = tmp_path / "dataset"
    design_dir = dataset / "case"
    samples = tmp_path / "samples"
    design_dir.mkdir(parents=True)
    samples.mkdir()
    (design_dir / "design_description.txt").write_text("Module name: dut\n")
    _legacy_tb(design_dir / "testbench.v", marker="NOT THE MARKER")
    _candidate(samples / "case.v")
    layout = {
        "prompt_filename": "design_description.txt",
        "tb_filename": "testbench.v",
        "ref_glob": "verified_*.v",
    }
    args = {
        "pass_regex": r"OFFICIAL PASS",
        "fail_regex": r"OFFICIAL FAIL",
        "cwd_design_dir": True,
    }

    res = scorer._score_shape_b_impl("case", samples, dataset, layout, args)
    assert res["verdict"] == "FAIL"
    assert res["reason"].startswith("no_pass_marker")
    assert res["tool"] == "iverilog-g2005"


def test_golden_compile_audit_uses_same_legacy_dialect(scorer, tmp_path):
    dataset = tmp_path / "dataset"
    design_dir = dataset / "case"
    design_dir.mkdir(parents=True)
    (design_dir / "design_description.txt").write_text("Module name: dut\n")
    _legacy_tb(design_dir / "testbench.v")
    _candidate(design_dir / "verified_case.v")
    layout = {
        "prompt_filename": "design_description.txt",
        "tb_filename": "testbench.v",
        "ref_glob": "verified_*.v",
    }

    compiles, ports = scorer._golden_ref_compiles_with_tb_shape_b(
        "case", dataset, layout)
    assert compiles is True
    assert ports == {"y"}
