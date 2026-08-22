#!/usr/bin/env python3
"""An emitted analysis deck hard-coded the directory it was emitted in.

MEASURED DEFECT
===============
The flow emits the tool decks it drives, so a reviewer can re-run the
measurement. On one real run tree, `26 of 30` emitted scripts carried an
absolute path pointing back INTO the run directory they were written for:

    reports/phase3/power_<top>.tcl
        read_verilog /<host>/<run>/baseline/phase2/stage2/synth/<top>_synth.v

MEASURED, and this is the half that is not merely inconvenient. Copy such a
deck into a DIFFERENT run tree and run it there: it succeeds, and it measures
the ORIGINAL tree. Two trees whose routed netlists differ, same deck:

    the portable deck, sitting in tree B   -> clock leakage 1.59e-10  (tree B)
    the hard-coded deck, sitting in tree B -> clock leakage 6.32e-09  (tree A)

No error, no warning, a full report. The second consequence is the identity
one: two runs of a BYTE-IDENTICAL measurement configuration hash differently
purely because they ran in different directories, so a comparison requiring
"same analysis configuration" refuses two arms that are identically configured.

THE RULE
========
An absolute path INSIDE the run root is a finding; one OUTSIDE it is not. A
path inside names something this run produced and the run tree moves, so the
deck must reach it relatively. A path outside names the environment — the PDK,
the tool install — which is not this run's to relativise.

WHAT IS ASSERTED
================
The checker: it PASSES on a portable deck, goes RED on the real defect,
REFUSES (rc=2) rather than passing when there was nothing to look at, and
rc=3 on a bad invocation.

The emitter: the power deck spells its in-tree paths against `$RUN_ROOT`,
leaves the PDK path alone, falls back to absolute paths when the deck is not
in the run tree at all (where `$RUN_ROOT` cannot be resolved), and NOTES it
loudly if a run path ever reaches the deck again.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import emitted_script_portability_check as esp  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_portable", _PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

CONTAINER = "test-container-no-such-container"
TOP = "dut"

PORTABLE = """\
set RUN_ROOT [file normalize [file join [file dirname [info script]] .. ..]]
read_liberty /foss/pdks/somepdk/lib/cells_typ.lib
read_verilog $RUN_ROOT/phase3/stage3/pnr/dut_pnr.v
report_power
"""


def _run(project, *args):
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "emitted_script_portability_check.py"),
         str(project), *args],
        capture_output=True, text=True)


def _tree(tmp_path: Path, body: str, name="reports/phase3/power_dut.tcl"):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f


# ================================================================ POSITIVE ===
def test_a_portable_deck_passes(tmp_path):
    _tree(tmp_path, PORTABLE)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_a_pdk_path_outside_the_run_root_is_not_a_finding(tmp_path):
    """The rule's other half, and the reason it is this rule: a container-
    canonical PDK path is ALREADY portable across every host running the same
    image. Flagging it would make the check unpassable and therefore ignored."""
    _tree(tmp_path, "read_liberty /foss/pdks/somepdk/lib/cells_typ.lib\n"
                    "read_lef /usr/share/somepdk/tech.lef\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


# ================================================================ NEGATIVE ===
def test_the_real_defect_goes_red(tmp_path):
    """The deck as the flow used to emit it: an absolute path back into the
    run root it was written for."""
    _tree(tmp_path, f"read_verilog {tmp_path}/phase2/stage2/synth/dut_synth.v\n"
                    f"read_sdc {tmp_path}/phase3/stage3/pnr/constraint.sdc\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[FAIL]" in r.stdout
    assert "power_dut.tcl" in r.stdout
    assert "2 occurrence" in r.stdout


def test_one_bad_deck_among_good_ones_is_still_a_finding(tmp_path):
    _tree(tmp_path, PORTABLE, name="reports/phase3/a.tcl")
    _tree(tmp_path, PORTABLE, name="reports/phase3/b.tcl")
    _tree(tmp_path, f"read_verilog {tmp_path}/x.v\n", name="reports/phase3/c.tcl")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "1 of 3" in r.stdout, r.stdout


# ================================================================= VACUOUS ===
def test_no_script_in_scope_refuses_rather_than_passing(tmp_path):
    """rc=2, not rc=0. `I looked and it was clean` and `I could not look` must
    never produce the same answer — an empty tree is the single most likely
    way a path check silently certifies nothing."""
    (tmp_path / "phase3").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stdout
    assert "NO claim" in r.stdout


def test_staged_inputs_are_not_in_scope_and_alone_are_vacuous(tmp_path):
    """`input/` holds what the USER staged, not what this flow emitted, so a
    host path in there is not this check's business — and a tree holding only
    those has nothing in scope, which is a refusal, not a pass."""
    _tree(tmp_path, f"read_verilog {tmp_path}/x.v\n", name="input/vendor/run.tcl")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout


# ========================================================== BAD INVOCATION ===
def test_a_project_that_is_not_a_directory_is_rc3(tmp_path):
    r = _run(tmp_path / "no_such_tree")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "[BAD INVOCATION]" in r.stdout


def test_an_under_scope_that_does_not_exist_is_rc3_not_a_pass(tmp_path):
    _tree(tmp_path, PORTABLE)
    r = _run(tmp_path, "--under", "reports/phase3/nope.tcl")
    assert r.returncode == 3, r.stdout
    assert "[BAD INVOCATION]" in r.stdout


def test_scope_narrowing_works(tmp_path):
    _tree(tmp_path, PORTABLE, name="reports/phase3/good.tcl")
    _tree(tmp_path, f"read_verilog {tmp_path}/x.v\n", name="phase3/stage3/bad.tcl")
    assert _run(tmp_path).returncode == 1
    assert _run(tmp_path, "--under", "reports/phase3/good.tcl").returncode == 0
    assert _run(tmp_path, "--under", "phase3/stage3/bad.tcl").returncode == 1


def test_json_records_the_findings(tmp_path):
    import json
    _tree(tmp_path, f"read_verilog {tmp_path}/x.v\n")
    out = tmp_path / "out.json"
    _run(tmp_path, "--json", str(out))
    doc = json.loads(out.read_text())
    assert doc["rc"] == 1 and doc["findings"][0]["script"].endswith("power_dut.tcl")


# =============================================== THE EMITTER'S OWN BEHAVIOUR ==
def _mk_project(tmp_path: Path) -> Path:
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / f"{TOP}_synth.v").write_text(f"module {TOP}(); endmodule\n")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / f"{TOP}_pnr.v").write_text(f"module {TOP}(); endmodule\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / f"{TOP}.spef").write_text('*SPEF "IEEE 1481-1998"\n')
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    (libdir / "cellib_typ.lib").write_text("library (l) { }\n")
    return tmp_path


def _mk_pdk(tmp_path: Path):
    return p3.PdkConfig(
        name="testpdk",
        liberty="/foss/pdks/testpdk/lib/cellib_typ.lib",
        tech_lef=str(tmp_path / "tech.lef"), cell_lef=str(tmp_path / "cell.lef"),
        cell_gds=None, site="unit", drc_deck=None)


@pytest.fixture
def _no_docker(monkeypatch):
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])

    def _fake_exec(container, cmd, *a, **k):
        out = Path(cmd.rsplit(" > ", 1)[-1].split(" ", 1)[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "Group                  Internal  Switching    Leakage      Total\n"
            "Sequential             1.00e-04  1.00e-05   1.00e-09   1.10e-04\n"
            "Clock                  1.00e-04  1.00e-05   1.00e-09   1.10e-04\n"
            "Total                  2.00e-04  2.00e-05   2.00e-09   2.20e-04\n"
            "dynamic power / leakage power reported above\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


def _emit(proj: Path, rpt: Path):
    rpt.parent.mkdir(parents=True, exist_ok=True)
    notes: list = []
    p3._emit_power_report(proj, TOP, _mk_pdk(proj), CONTAINER, rpt, notes,
                          basis="post_pnr")
    return (rpt.parent / f"power_{TOP}.tcl").read_text(), notes


def test_the_power_deck_spells_in_tree_paths_against_run_root(tmp_path, _no_docker):
    """FAILS pre-fix, whose deck read `<abs run dir>/phase3/.../dut_pnr.v`."""
    proj = _mk_project(tmp_path)
    tcl, notes = _emit(proj, proj / "reports" / "phase3" / "power.rpt")
    assert "set RUN_ROOT [file normalize [file join [file dirname [info script]] .. ..]]" in tcl
    for cmd in ("read_verilog", "read_sdc", "read_spef"):
        line = [ln for ln in tcl.splitlines() if ln.startswith(cmd + " ")]
        assert line and line[0].split()[1].startswith("$RUN_ROOT/"), (cmd, line)
    # the PDK path is the environment's and is left exactly as it was
    assert "read_liberty /foss/pdks/testpdk/lib/cellib_typ.lib" in tcl
    # and the deck now satisfies the checker, in the tree it was emitted into
    assert esp.host_paths_in(tcl, proj) == []
    assert not [n for n in notes if "INTO the run root" in n], notes


def test_a_deck_written_outside_the_run_tree_keeps_absolute_paths(tmp_path, _no_docker):
    """`$RUN_ROOT` is resolved from the deck's OWN location, so a deck that is
    not in the run tree cannot resolve it. Emitting `$RUN_ROOT/...` there would
    make the tool read the empty string as a directory and measure the wrong
    thing silently. It falls back to absolute paths — the pre-fix behaviour,
    which is correct for a deck that is not part of the tree it measures."""
    proj = _mk_project(tmp_path / "run")
    outside = tmp_path / "elsewhere" / "power.rpt"
    outside.parent.mkdir(parents=True)
    tcl, _ = _emit(proj, outside)
    assert "RUN_ROOT" not in tcl
    assert f"read_verilog {proj}/phase3/stage3/pnr/{TOP}_pnr.v" in tcl


def test_a_run_path_reaching_the_deck_is_noted_loudly(tmp_path, monkeypatch,
                                                      _no_docker):
    """The guard at the point of emission. Break the path speller and the run
    says so in its own notes, instead of the defect surfacing later as an
    identity hash that quietly will not match."""
    proj = _mk_project(tmp_path)
    monkeypatch.setattr(p3, "_run_root_tcl_path",
                        lambda hp, project, container, script_path: str(hp))
    _, notes = _emit(proj, proj / "reports" / "phase3" / "power.rpt")
    assert any("absolute path(s) INTO the run root" in n for n in notes), notes
