"""Tests for benchmark_shape_classify.py (open-benchmark-methodology § 2)."""
from __future__ import annotations

import benchmark_shape_classify as mod


def _module(name: str) -> str:
    return f"module {name}(input a, output b); assign b = a; endmodule\n"


def test_full_ic_shape_a(tmp_path):
    d = tmp_path / "full_ic"
    d.mkdir()
    (d / "core.v").write_text(_module("core"))
    (d / "top.v").write_text(_module("top"))
    (d / "config.json").write_text('{"PDK": "sky130A"}')
    res = mod.classify(d, None, False)
    assert res["shape"] == "A"


def test_substantial_standalone_shape_b(tmp_path):
    d = tmp_path / "standalone"
    d.mkdir()
    (d / "fifo.v").write_text(_module("fifo"))
    (d / "design_description.txt").write_text("A FIFO.\n" * 10)
    res = mod.classify(d, None, False)
    assert res["shape"] == "B"


def test_atomic_microproblems_shape_c(tmp_path):
    d = tmp_path / "micro"
    d.mkdir()
    for i in range(120):
        (d / f"Prob{i:03d}_prompt.txt").write_text("Implement a 2-input AND gate.\n")
    res = mod.classify(d, None, False)
    assert res["shape"] == "C"


def test_microproblem_count_override_shape_c(tmp_path):
    # Few files on disk, but caller knows the dataset is 156 problems.
    d = tmp_path / "micro2"
    d.mkdir()
    (d / "Prob001_prompt.txt").write_text("AND gate.\n")
    res = mod.classify(d, 156, False)
    assert res["shape"] == "C"


def test_agentic_cocotb_shape_d(tmp_path):
    d = tmp_path / "agentic"
    d.mkdir()
    (d / "core.v").write_text(_module("core"))
    (d / "top.v").write_text(_module("top"))
    (d / "config.json").write_text('{"PDK": "sky130A"}')
    (d / "test_dut.py").write_text("import cocotb\n@cocotb.test()\nasync def t(dut): pass\n")
    res = mod.classify(d, None, False)
    assert res["shape"] == "D"  # cocotb wins over A


def test_oracle_gated_shape_e(tmp_path):
    d = tmp_path / "gated"
    d.mkdir()
    (d / "core.v").write_text(_module("core"))
    res = mod.classify(d, None, True)
    assert res["shape"] == "E"


def test_empty_dir_shape_e(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    res = mod.classify(d, None, False)
    assert res["shape"] == "E"
    assert res["reason"] == "no_scorable_content"


def test_not_a_directory_usage_error(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x")
    rc = mod.main([str(f)])
    assert rc == 2


def test_main_exit_codes(tmp_path):
    # Runnable shape → rc 0.
    d = tmp_path / "standalone"
    d.mkdir()
    (d / "fifo.v").write_text(_module("fifo"))
    assert mod.main([str(d)]) == 0
    # E → rc 1.
    e = tmp_path / "empty"
    e.mkdir()
    assert mod.main([str(e)]) == 1


def test_json_report(tmp_path):
    d = tmp_path / "full_ic"
    d.mkdir()
    (d / "core.v").write_text(_module("core"))
    (d / "top.v").write_text(_module("top"))
    (d / "design.sdc").write_text("create_clock\n")
    out = tmp_path / "r.json"
    rc = mod.main([str(d), "--json", str(out)])
    assert rc == 0
    import json
    rep = json.loads(out.read_text())
    assert rep["shape"] == "A"
    assert rep["facts"]["module_count"] == 2
