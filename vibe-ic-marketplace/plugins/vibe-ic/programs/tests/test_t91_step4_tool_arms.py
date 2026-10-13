#!/usr/bin/env python3
"""T91 step 4: the simulation tools answer, and a disagreement is a finding.

Three tool paths, each measured in the released image before it was relied on
(vibeic-eda 0.3.77):

1. LINE UNION. `verilator_coverage --write-info` merges line points across
   testbench instance paths (one `DA` per file:line); only `--write` (.dat)
   concatenates. Its union is recorded beside the h-stripped union, and a
   measured disagreement makes `check` refuse. The real .dat/.info files are
   the calibration pair in `programs/calibration/cov_union_*`.
2. SIMULATOR DIFFERENTIAL. The same cocotb bundle under Icarus and Verilator,
   compared per case. MEASURED: an unreset flop read by `int()` fails under
   Icarus (X) and passes under Verilator (2-state 0).
3. VECTOR POWER. OpenSTA 3.1.0 rejects `read_power_activities -vcd` with
   `default is not a mode object`, and `read_vcd` without `-scope` on a
   testbench VCD prints `Annotated 0 pin activities.`. The deck now reads the
   step-4 manifest's VCD at its verified scope with `read_vcd -scope`.

Each test drives the program's real code path; only the EDA tools' file
writes are faked. The controls use `getattr` so the pre-fix tree answers
wrongly instead of raising.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_CAL = _PROGRAMS / "calibration"

import verilator_coverage_measure as vcm  # noqa: E402


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, _PROGRAMS / name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. line union ─────────────────────────────────────────────────────────

def _fake_tools(dats_by_top, info_src):
    """exec_fn standing in for verilator/the sim binary/verilator_coverage:
    it writes the files those tools write, taken from real tool output."""
    def _exec(argv, cwd):
        argv = [str(a) for a in argv]
        if argv[0] == "verilator":
            top = argv[argv.index("--top-module") + 1]
            mdir = Path(argv[argv.index("-Mdir") + 1])
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / f"V{top}").write_text(top)
            return 0, "", ""
        if argv[0] == "verilator_coverage":
            shutil.copy(info_src, argv[argv.index("--write-info") + 1])
            return 0, "", ""
        top = Path(argv[0]).read_text()
        shutil.copy(dats_by_top[top], Path(cwd) / "coverage.dat")
        return 0, "", ""
    return _exec


def _suite(tmp_path, tops):
    rtl = tmp_path / "cov_cal.v"
    rtl.write_text("module cov_cal(); endmodule\n")
    tbs = []
    for top in tops:
        tb = tmp_path / f"{top}.v"
        tb.write_text(f"module {top}; endmodule\n")
        tbs.append(str(tb))
    dats = {"tb_cal_idle": _CAL / "cov_union_tb_idle.dat",
            "tb_cal_toggle": _CAL / "cov_union_tb_toggle.dat"}
    return vcm.measure_suite([str(rtl)], tbs, str(tmp_path / "build"),
                             exec_fn=_fake_tools(dats,
                                                 _CAL / "cov_union_suite_lcov.info"))


def test_the_suite_records_the_tools_line_union_and_it_agrees(tmp_path):
    res = _suite(tmp_path, ["tb_cal_idle", "tb_cal_toggle"])
    xc = res.get("line_union_cross_check") or {}
    assert xc.get("status") == "MEASURED", xc
    assert xc.get("agree") is True, xc
    assert xc["lcov_line_totals"] == {"covered": 6, "total": 6, "pct": 100.0}
    fields = vcm.suite_payload_fields(res)
    assert fields.get("line_union_cross_check") == xc


def test_a_member_missing_from_our_union_is_a_named_disagreement(tmp_path):
    """The tool's union covers both members; ours was built from one. Line 6
    is hit only by the toggle member, so the hit sets differ."""
    ours = vcm.union_line_map([str(_CAL / "cov_union_tb_idle.dat")])
    tool = vcm.parse_lcov_info((_CAL / "cov_union_suite_lcov.info").read_text())
    xc = vcm.cross_check_line_union(ours, tool, ["cov_cal.v"])
    assert xc["agree"] is False
    assert xc["mismatches"] == [{"file": "cov_cal.v", "kind": "hit_set",
                                 "only_h_stripped_union": [], "only_lcov": [6]}]


def test_an_else_points_span_line_is_counted(tmp_path):
    """An `else` point recorded at l=<if line> carries S=<its own line>; lcov
    writes a DA row for S. Reading `l` alone loses it."""
    lines = vcm.union_line_map([str(_CAL / "cov_union_tb_idle.dat")])
    tool = vcm.parse_lcov_info((_CAL / "cov_union_suite_lcov.info").read_text())
    assert set(lines["cov_cal.v"]) == set(tool["cov_cal.v"])


def test_check_refuses_a_measured_line_union_disagreement(tmp_path, capsys):
    base = {"tool": "verilator", "coverage_dat": str(_CAL / "cov_union_tb_idle.dat"),
            "totals": {k: {"covered": 9, "total": 9, "pct": 100.0}
                       for k in ("line", "toggle", "branch")},
            "per_file": {}, "format_detected": "v5"}
    # Use the producer's current record, including its native LCOV population.
    # The toggle member hits line 6; omitting it from ours is a real split.
    dats = [str(_CAL / "cov_union_tb_idle.dat"),
            str(_CAL / "cov_union_tb_toggle.dat")]
    tool = vcm.parse_lcov_info((_CAL / "cov_union_suite_lcov.info").read_text())
    agree = dict(base, line_union_cross_check=vcm.cross_check_line_union(
        vcm.union_line_map(dats), tool, ["cov_cal.v"]))
    split = dict(base, line_union_cross_check=vcm.cross_check_line_union(
        vcm.union_line_map(dats[:1]), tool, ["cov_cal.v"]))
    rcs = []
    for name, doc in (("agree", agree), ("split", split)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(doc))
        rcs.append(vcm.main(["check", "--coverage-json", str(p),
                             "--min-line", "0", "--min-toggle", "0",
                             "--min-branch", "0"]))
    assert rcs == [0, 1]
    assert "LINE_UNION_DISAGREES" in capsys.readouterr().out


# ── 2. simulator differential ────────────────────────────────────────────

def _compare(a, b, out):
    return subprocess.run([sys.executable, str(_PROGRAMS / "sim_dual_compare.py"),
                           "--a", str(a), "--b", str(b), "--json", str(out)],
                          capture_output=True, text=True)


def test_an_x_read_that_only_icarus_fails_is_a_named_disagreement(tmp_path):
    r = _compare(_CAL / "sim_dual_icarus_x_positive.xml",
                 _CAL / "sim_dual_verilator_x_positive.xml", tmp_path / "d.json")
    assert r.returncode == 1, r.stdout + r.stderr
    doc = json.loads((tmp_path / "d.json").read_text())
    assert doc["finding"] == "SIM_DIFFERENTIAL_DISAGREES"
    assert doc["disagreements"] == [{"case": "tb_xd.q_starts_low",
                                     "icarus": "FAIL", "verilator": "PASS"}]


def test_identical_outcomes_agree_and_a_missing_arm_is_not_measured(tmp_path):
    ok = _compare(_CAL / "sim_dual_icarus_negative.xml",
                  _CAL / "sim_dual_verilator_negative.xml", tmp_path / "a.json")
    missing = _compare(_CAL / "sim_dual_icarus_negative.xml",
                       tmp_path / "absent.xml", tmp_path / "b.json")
    assert (ok.returncode, missing.returncode) == (0, 2)


def _runner():
    return _load("design_one_shot_runner.py", "dosr_t91_step4")


def test_dual_mode_runs_the_verilator_arm_and_default_does_not(tmp_path,
                                                                monkeypatch):
    dosr = _runner()
    helper = getattr(dosr, "_professional_tb_sim_differential", None)
    out = tmp_path / "bundle"
    out.mkdir()
    shutil.copy(_CAL / "sim_dual_icarus_x_positive.xml", out / "results.xml")
    calls = []

    def _fake_run(argv, cwd=None, timeout=None):
        calls.append(argv)
        shutil.copy(_CAL / "sim_dual_verilator_x_positive.xml",
                    Path(cwd) / "results_verilator.xml")
        return 0, "", ""

    monkeypatch.setattr(dosr, "_run", _fake_run)
    default = helper(tmp_path, out, "", "host") if helper else "absent"
    (tmp_path / "phase3").mkdir()
    (tmp_path / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"4": "dual"}}))
    dual = helper(tmp_path, out, "", "host") if helper else {}
    assert default is None
    assert len(calls) == 1 and "SIM=verilator" in calls[0][-1]
    assert dual.get("finding") == "SIM_DIFFERENTIAL_DISAGREES"
    assert (out / "sim_differential.json").is_file()
    assert (out / "results.xml").read_bytes() == \
        (_CAL / "sim_dual_icarus_x_positive.xml").read_bytes()


# ── 3. DUT-scoped activity for vector power ──────────────────────────────

_VCD = ("$timescale 1ps $end\n$scope module tb_top $end\n"
        "$scope module u_core $end\n$var wire 1 ! clk $end\n$upscope $end\n"
        "$upscope $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n")


def test_the_dump_names_the_scope_it_found_in_the_vcd(tmp_path):
    sad = _load("sim_activity_dump.py", "sad_t91")
    rtl = tmp_path / "core.v"
    rtl.write_text("module core(input clk); endmodule\n")
    other = tmp_path / "tb_other.v"
    other.write_text("module tb_other; endmodule\n")
    tb = tmp_path / "tb_top.v"
    tb.write_text("module tb_top; reg clk; // core u_fake (\n"
                  "  core #(.W(2)) u_core (.clk(clk));\nendmodule\n")
    seen = []

    def _exec(argv, cwd):
        seen.append(argv)
        if argv[0] == "vvp":
            dumper = (Path(cwd) / "vibeic_vcd_dump.v").read_text()
            assert "$dumpvars(0, tb_top.u_core)" in dumper
            (Path(cwd) / "tb_top.vcd").write_text(_VCD)
        return 0, "", ""

    got = sad.dump([str(rtl)], [str(other), str(tb)], "core",
                   tmp_path / "activity", exec_fn=_exec)
    assert got["status"] == "PASS" and got["scope"] == "tb_top/u_core"
    assert got["scope_verified"] is True
    assert json.loads((tmp_path / "activity/activity.json").read_text()) == got
    assert "-s" in seen[0] and "vibeic_vcd_dump" in seen[0]


def test_a_vcd_without_the_scope_is_refused(tmp_path):
    sad = _load("sim_activity_dump.py", "sad_t91b")
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; core dut (.clk(c)); endmodule\n")

    def _exec(argv, cwd):
        if argv[0] == "vvp":
            (Path(cwd) / "tb.vcd").write_text(_VCD)
        return 0, "", ""

    got = sad.dump([str(tb)], [str(tb)], "core", tmp_path / "a", exec_fn=_exec)
    assert got["status"] == "FAIL" and "tb/dut" in got["reason"]


_P3 = None


def _p3():
    global _P3
    if _P3 is None:
        _P3 = _load("phase3_one_shot_runner.py", "p3_t91_step4")
    return _P3


def _power_deck(tmp_path, monkeypatch, manifest: bool):
    p3 = _p3()
    container = "test-container-no-such-container"
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, container, [])

    def _fake_exec(container, cmd, *a, **k):
        out = Path(cmd.rsplit(" > ", 1)[-1].split(" ", 1)[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("Total 2.0e-04 2.0e-05 2.0e-09 2.2e-04 100.0%\n" * 3)
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)
    (tmp_path / "phase2/stage2/synth").mkdir(parents=True)
    (tmp_path / "phase2/stage2/synth/dut_synth.v").write_text("module dut(); endmodule\n")
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    act = tmp_path / "phase2/stage1/sim/activity"
    act.mkdir(parents=True)
    (act / "tb_top.vcd").write_text(_VCD)
    if manifest:
        (act / "activity.json").write_text(json.dumps(
            {"vcd": str(act / "tb_top.vcd"), "scope": "tb_top/u_core",
             "scope_verified": True}))
    lib = tmp_path / "cellib_typ.lib"
    lib.write_text("library (l) { }\n")
    pdk = p3.PdkConfig(name="testpdk", liberty=str(lib),
                       tech_lef=str(tmp_path / "t.lef"),
                       cell_lef=str(tmp_path / "c.lef"), cell_gds=None,
                       site="unit", drc_deck=None)
    rpt = tmp_path / "reports/phase3/power.rpt"
    rpt.parent.mkdir(parents=True)
    p3._emit_power_report(tmp_path, "dut", pdk, container, rpt, [])
    return (rpt.parent / "power_dut.tcl").read_text()


def test_the_power_deck_reads_the_manifest_vcd_at_its_scope(tmp_path, monkeypatch):
    tcl = _power_deck(tmp_path, monkeypatch, manifest=True)
    assert "read_power_activities" not in tcl
    assert "read_vcd -scope tb_top/u_core " in tcl
    assert "POWER_ANALYSIS_MODE: vector_vcd" in tcl


def test_a_legacy_vcd_is_read_with_the_working_command_and_no_invented_scope(
        tmp_path, monkeypatch):
    tcl = _power_deck(tmp_path, monkeypatch, manifest=False)
    assert "read_power_activities" not in tcl
    assert "read_vcd " in tcl and "-scope" not in tcl
