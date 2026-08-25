"""ORGANIC #536 — eda_image_preflight: the scoring sim image must match the
official Dockerfile.sim tool spec (iverilog 13 / yosys 0.40 / cocotb 2.0.1 /
verilator 5.038) or scoring is REFUSED.

Field evidence: a self-built image with Yosys 0.62 silently false-FAILed
every synth-gate problem (stat format drift → harness KeyError) across three
scoring rounds.

NEGATIVE no-leak: patch/build-string tolerance — an icarus devel build
suffix must not false-refuse.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "benchmark"))
import eda_image_preflight as E  # noqa: E402

OFFICIAL = """Icarus Verilog version 13.0 (devel) (s20221226-568-g62b00ee6d)
---
Yosys 0.40 (git sha1 a1bb0255d65, clang 14.0)
---
Verilator 5.038 2025-01-01 rev v5.038
---
2.0.1
"""

YOSYS_DRIFT = OFFICIAL.replace("Yosys 0.40 (git sha1 a1bb0255d65, clang 14.0)",
                               "Yosys 0.62+42 (git sha1 deadbeef)")


def test_official_spec_image_passes():
    results, deviations = E.check_versions(OFFICIAL)
    assert deviations == [], deviations
    assert all(r["ok"] for r in results)


def test_yosys_062_refused_with_named_deviation():
    # the EXACT field shape: yosys 0.62 vs official 0.40.
    results, deviations = E.check_versions(YOSYS_DRIFT)
    assert any("yosys" in d and "0.62" in d and "0.40" in d
               for d in deviations), deviations
    bad = [r for r in results if r["tool"] == "yosys"][0]
    assert bad["ok"] is False and bad["found"] == "0.62"


def test_negative_devel_build_suffix_tolerated():
    # NEGATIVE no-leak: icarus 13.0 devel suffix / verilator rev string /
    # yosys git sha — none may false-refuse (major/tag-level comparison).
    noisy = ("Icarus Verilog version 13.1 (stable) (v13_1)\n---\n"
             "Yosys 0.40+148 (git sha1 c0ffee)\n---\n"
             "Verilator 5.038 2024-06-06 rev UNKNOWN\n---\n"
             "2.0.1+local\n")
    _, deviations = E.check_versions(noisy)
    assert deviations == [], deviations


def test_missing_tool_is_a_deviation():
    broken = OFFICIAL.replace(
        "Yosys 0.40 (git sha1 a1bb0255d65, clang 14.0)",
        "sh: yosys: not found")
    _, deviations = E.check_versions(broken)
    assert any("yosys" in d for d in deviations)


def test_cli_refuses_on_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(E.shutil, "which", lambda *_: "/usr/bin/docker")
    monkeypatch.setattr(E, "probe_image",
                        lambda image, runner=None: (0, YOSYS_DRIFT))
    rc = E.main(["--image", "self-built:latest",
                 "--json", str(tmp_path / "v.json")])
    assert rc == 1
    v = json.loads((tmp_path / "v.json").read_text())
    assert v["verdict"] == "REFUSE"


def test_cli_passes_on_official(tmp_path, monkeypatch):
    monkeypatch.setattr(E.shutil, "which", lambda *_: "/usr/bin/docker")
    monkeypatch.setattr(E, "probe_image",
                        lambda image, runner=None: (0, OFFICIAL))
    rc = E.main(["--image", "official:latest"])
    assert rc == 0


def test_cli_no_docker_is_input_error(monkeypatch):
    monkeypatch.setattr(E.shutil, "which", lambda *_: None)
    rc = E.main(["--image", "x"])
    assert rc == 2
