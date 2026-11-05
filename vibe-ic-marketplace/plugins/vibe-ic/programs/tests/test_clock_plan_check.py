#!/usr/bin/env python3
"""Tests for clock_plan_check.py — Step 16 (Clock planning) substance gate.

Pins the anti-fabrication contract: the checker parses the real
``clock_plan.json`` artefact and verifies SUBSTANCE — >= 1 clock, each with a
positive period and a source pin/port, and no SDC create_clock dropped from
the plan. It must FAIL honestly on absent / empty / unparseable / empty-plan /
period-less artefacts and must NEVER pass on absence.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from _hostpaths import require_repo
from _clock_plan_fixture import current_fixture

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "clock_plan_check.py"

_spec = importlib.util.spec_from_file_location("clock_plan_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# fixture builders
# ----------------------------------------------------------------------
def _cts_dir(project: Path) -> Path:
    d = project / "phase3" / "stage3" / "cts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_plan(project: Path, doc) -> Path:
    d = _cts_dir(project)
    p = d / "clock_plan.json"
    if isinstance(doc, str):
        p.write_text(doc)
    else:
        p.write_text(json.dumps(doc))
    return p


def _write_sdc(project: Path, text: str, rel="phase3/stage3/pnr/constraint.sdc") -> Path:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _run(project: Path, tmp_path: Path):
    out = tmp_path / "report.json"
    rc = mod.main([str(project), "--json", str(out)])
    report = json.loads(out.read_text()) if out.is_file() else None
    return rc, report


# ----------------------------------------------------------------------
# PASS fixtures (good substance)
# ----------------------------------------------------------------------
def test_pass_explicit_clocks_array(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "tool": "openroad",
        "clocks": [
            {"name": "clk", "period_ns": 10.0, "source_port": "clk"},
            {"name": "clk_div2", "period_ns": 20.0, "source_pin": "u_div/Q"},
        ],
    })
    current_fixture(monkeypatch, project,
                    "create_clock -name clk -period 10 [get_ports clk]\n"
                    "create_clock -name clk_div2 -period 20 [get_pins u_div/Q]\n")
    rc, report = _run(project, tmp_path)
    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["num_clocks"] == 2


def test_pass_frequency_mhz_instead_of_period(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "frequency_mhz": 100.0, "port": "clk"}],
    })
    current_fixture(monkeypatch, project,
                    "create_clock -name clk -period 10 [get_ports clk]\n")
    rc, report = _run(project, tmp_path)
    assert rc == 0
    assert report["verdict"] == "PASS"
    # 100 MHz -> 10 ns
    assert abs(report["clocks"][0]["period_ns"] - 10.0) < 1e-6


def test_pass_minimal_single_clock_shape(tmp_path, monkeypatch):
    """A non-array plan that supplies primary_clock + top-level period + source."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "tool": "openroad",
        "primary_clock": "clk",
        "period_ns": 20.0,
        "source_port": "clk",
    })
    current_fixture(monkeypatch, project,
                    "create_clock -name clk -period 20 [get_ports clk]\n")
    rc, report = _run(project, tmp_path)
    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["num_clocks"] == 1


def test_two_sdc_names_on_one_physical_clock_share_the_observed_root(tmp_path, monkeypatch):
    """Current ASIC constraint aliases may share one real input and CTS root."""
    project = tmp_path / "aliases"
    _write_sdc(project,
               "create_clock -name core_clk -period 20 [get_ports clk_in]\n")
    _write_sdc(project,
               "create_clock -name prototype_clk -period 20 "
               "[get_ports clk_in]\n",
               "input/constraints/aliases.sdc")
    _write_plan(project, {"clocks": [
        {"name": "core_clk", "period_ns": 20, "source": "clk_in"},
        {"name": "prototype_clk", "period_ns": 20, "source": "clk_in"},
    ]})
    config = project / "phase3/librelane/19-config/OpenROAD.CTS.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"CLOCK_PORT": "core_clk",
                                  "CLOCK_NET": None,
                                  "meta": {"step": "OpenROAD.CTS"}}))
    (_cts_dir(project) / "clock_tree.rpt").write_text(
        '[INFO CTS-0007] Net "clk_in" found for clock "core_clk".\n')
    current_fixture(monkeypatch, project,
                    "create_clock -name core_clk -period 20 [get_ports clk_in]\n")

    rc, report = _run(project, tmp_path)
    rules = {f["rule"] for f in report["findings"]}
    assert rc == 0, rules
    assert "LIBRELANE_CLOCKS_MATCH_SDC" in rules
    assert "CTS_CLOCKS_SEEN" in rules


def test_a_different_clock_source_still_requires_its_own_root(tmp_path):
    project = tmp_path / "two_roots"
    _write_sdc(project,
               "create_clock -name core_clk -period 20 [get_ports clk_in]\n"
               "create_clock -name aux_clk -period 20 [get_ports aux_in]\n")
    _write_plan(project, {"clocks": [
        {"name": "core_clk", "period_ns": 20, "source": "clk_in"},
        {"name": "aux_clk", "period_ns": 20, "source": "aux_in"},
    ]})
    config = project / "phase3/librelane/19-config/OpenROAD.CTS.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"CLOCK_PORT": "core_clk",
                                  "CLOCK_NET": None,
                                  "meta": {"step": "OpenROAD.CTS"}}))
    (_cts_dir(project) / "clock_tree.rpt").write_text(
        '[INFO CTS-0007] Net "clk_in" found for clock "core_clk".\n')

    rc, report = _run(project, tmp_path)
    rules = {f["rule"] for f in report["findings"]}
    assert rc == 1
    assert "LIBRELANE_CLOCK_MISSING" in rules
    assert "CTS_CLOCK_MISSING" in rules


def test_unbraced_silicon_port_and_braced_fpga_alias_are_one_clock(tmp_path, monkeypatch):
    """Preserve the historical braced/unbraced alias regression on current
    ASIC inputs. The extra alias is explicitly declared in input/constraints;
    a separate FPGA prototype deck no longer supplies the ASIC clock plan.
    Reading `[get_ports i_clk]` as `i_clk]` made the alias look like a second,
    missing clock (LIBRELANE_CLOCK_MISSING on a single-clock die)."""
    project = tmp_path / "die"
    _write_sdc(project,
               "create_clock -name clk -period 20.0 [get_ports i_clk]\n",
               "phase2/stage2/constraints/top.asic.sdc")
    _write_sdc(project,
               "create_clock -name i_clk -period 20 [get_ports {i_clk}]\n",
               "input/constraints/aliases.sdc")
    _write_plan(project, {"clocks": [
        {"name": "clk", "period_ns": 20, "source": "i_clk"},
        {"name": "i_clk", "period_ns": 20, "source": "i_clk"},
    ]})
    config = project / "phase3/librelane/19-config/OpenROAD.CTS.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"CLOCK_PORT": "clk", "CLOCK_NET": None,
                                  "meta": {"step": "OpenROAD.CTS"}}))
    (_cts_dir(project) / "clock_tree.rpt").write_text(
        '[INFO CTS-0007] Net "i_clk" found for clock "clk".\n')

    assert mod._sdc_primary_clock_sources(
        [project / "phase2/stage2/constraints/top.asic.sdc"]) == {"clk": "i_clk"}
    current_fixture(monkeypatch, project,
                    "create_clock -name clk -period 20 [get_ports i_clk]\n")
    rc, report = _run(project, tmp_path)
    rules = {f["rule"] for f in report["findings"]}
    assert "LIBRELANE_CLOCK_MISSING" not in rules, report["findings"]
    assert "LIBRELANE_CLOCKS_MATCH_SDC" in rules
    assert rc == 0, rules


def test_checked_in_silicon_sdc_source_excludes_tcl_closing_bracket():
    sdc = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "stage3_on_pass_review", "accept_subservient", "phase3",
        "stage3", "pnr", "constraint.sdc")
    assert mod._sdc_primary_clock_sources([sdc]) == {"clk": "clk"}


def test_pass_sdc_clock_present_in_plan(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "period_ns": 20.0, "source_port": "clk"}],
    })
    _write_sdc(project, "create_clock -name clk -period 20.0 [get_ports clk]\n")
    current_fixture(monkeypatch, project,
                    "create_clock -name clk -period 20 [get_ports clk]\n")
    rc, report = _run(project, tmp_path)
    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["sdc_files_checked"]  # the SDC was actually parsed


# ----------------------------------------------------------------------
# FAIL fixtures (the real backend failures this guards)
# ----------------------------------------------------------------------
def test_fail_empty_plan_no_clocks(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {"tool": "openroad", "clocks": []})
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert any(f["rule"] == "NO_CLOCK_DEFINED" for f in report["findings"])


def test_fail_clock_with_no_period(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "source_port": "clk"}],  # no period/frequency
    })
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert any(f["rule"] == "CLOCK_NO_PERIOD" for f in report["findings"])


def test_fail_clock_with_nonpositive_period(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "period_ns": 0.0, "source_port": "clk"}],
    })
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert any(f["rule"] == "CLOCK_NO_PERIOD" for f in report["findings"])


def test_fail_clock_with_no_source(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "period_ns": 10.0}],  # no source pin/port
    })
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert any(f["rule"] == "CLOCK_NO_SOURCE" for f in report["findings"])


def test_fail_sdc_clock_dropped_from_plan(tmp_path):
    """The real multi-clock-domain failure: SDC declares two clocks, plan has one."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "period_ns": 20.0, "source_port": "clk"}],
    })
    _write_sdc(
        project,
        "create_clock -name clk      -period 20.0 [get_ports clk]\n"
        "create_clock -name clk_jtag -period 50.0 [get_ports tck]\n",
    )
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert any(f["rule"] in ("SDC_CLOCK_DROPPED", "SDC_CLOCK_COUNT_MISMATCH")
               for f in report["findings"])


def test_fail_runner_minimal_plan_has_no_period(tmp_path):
    """Guards the ACTUAL current runner output: the heuristic clock_plan.json
    names primary_clock + buf_strategy but supplies NO period and NO source —
    exactly the under-specified plan the old files_exist gate let through."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "tool": "openroad",
        "source_log": "phase3/stage3/pnr/openroad.log",
        "primary_clock": "clk",
        "buf_strategy": "clkbuf chain (heuristic)",
    })
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    # primary 'clk' is recognised as a clock but lacks period + source.
    rules = {f["rule"] for f in report["findings"]}
    assert "CLOCK_NO_PERIOD" in rules
    assert "CLOCK_NO_SOURCE" in rules


# ----------------------------------------------------------------------
# missing / garbage honesty
# ----------------------------------------------------------------------
def test_fail_missing_plan_file(tmp_path):
    project = tmp_path / "proj"
    (project / "phase3" / "stage3" / "cts").mkdir(parents=True)
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert any(f["rule"] == "CLOCK_PLAN_MISSING" for f in report["findings"])


def test_fail_empty_plan_file(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, "")
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert any(f["rule"] == "CLOCK_PLAN_EMPTY" for f in report["findings"])


def test_fail_garbage_unparseable_plan(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, "{ this is not : valid json ]]]")
    rc, report = _run(project, tmp_path)
    assert rc == 1
    assert any(f["rule"] == "CLOCK_PLAN_UNPARSEABLE" for f in report["findings"])


def test_skip_when_project_dir_absent(tmp_path):
    missing = tmp_path / "does_not_exist"
    rc = mod.main([str(missing)])
    assert rc == 2  # SKIP, not a vacuous pass


def test_waiver_passes_when_recorded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "waivers.json").write_text(json.dumps({
        "waived_steps": [{"id": "clock_plan", "ticket": "WAIVE-16",
                          "reason": "non-production smoke run"}],
    }))
    # No clock_plan.json present.
    rc, report = _run(project, tmp_path)
    assert rc == 0
    assert report["verdict"] == "WAIVED"


def test_cli_contract_matches_siblings(tmp_path):
    """`python3 clock_plan_check.py <project_dir> [--json <out>]`,
    main(argv)->int, JSON report has gate/verdict/findings keys."""
    project = tmp_path / "proj"
    project.mkdir()
    _write_plan(project, {
        "clocks": [{"name": "clk", "period_ns": 10.0, "source_port": "clk"}],
    })
    out = tmp_path / "r.json"
    rc = mod.main([str(project), "--json", str(out)])
    assert isinstance(rc, int)
    report = json.loads(out.read_text())
    for key in ("gate", "verdict", "findings"):
        assert key in report
    assert report["gate"] == "clock_plan_check"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
