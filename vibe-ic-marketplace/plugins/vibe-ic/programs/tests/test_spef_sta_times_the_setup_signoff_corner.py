#!/usr/bin/env python3
"""The declared post-route SIGN-OFF artefact was timed at the NOMINAL corner.

MEASURED DEFECT
===============
`_emit_spef_sta` builds the SPEF-annotated post-route STA and its report is
copied verbatim to `phase3/stage3/sta/post_route_timing.rpt` — the ONE STA
artefact Step 23, "Post-route STA (multi-corner multi-mode SIGN-OFF)", names in
`required_outputs`.

It read `pdk.liberty`: the NOMINAL/typical process library. So on a design that
closes at TT and violates at SS, the artefact the sign-off step declares stamps
a clean summary. Measured on one real routed design (the PDK is not named here,
and nothing in this fix or test depends on which PDK it was):

    phase3/stage3/sta/post_route_timing.rpt   (read_liberty <stem>_typ.lib)
        Startpoint: address[1]  (input port)
        Endpoint:   read_data[1] (output port)
        Path Group: clk ... No paths found.
        tns max 0.00 / wns max 0.00 / worst slack max 5.24 (MET)

    the SAME routed netlist + the SAME SPEF at the slow corner
        worst slack max  -0.93   slack (VIOLATED)
        and with the lifetime aging derate:  -1.46   slack (VIOLATED)

The nominal corner did not merely under-report the margin — it reported a
different QUESTION: with no reg-to-reg path violating at TT, the worst path it
could find was an I/O path through the register read mux, and it published
`wns max 0.00` for a design whose worst setup slack is -0.93 ns.

WHY IT HAS NOT BLOWN UP YET, AND WHY THAT IS NOT SAFETY
-------------------------------------------------------
Step 23's gate (`sta_report_check . --mode sta --json <out>`) declares no
`--under`, so its discovery is project-wide and it happens to sweep up a
different, slow-corner report elsewhere in the tree and fail on that. The gate
is accidentally load-bearing. Scope it to the artefact the step declares — the
way steps 21 and 31 already correctly do for DRC — and the SIGN-OFF gate
returns **exit 0** on a design that misses setup by 0.93 ns. That was measured
directly, before this fix:

    $ sta_report_check . --mode sta \
          --under phase3/stage3/sta/post_route_timing.rpt --json out.json
    EXIT=0        "passed": true, "real_violation_found": false

So the two defects mask each other, and fixing the scoping alone — the obvious
next cleanup, and the one this repo already applied to the DRC pair — converts
a true FAIL into a false PASS. This test pins the corner so that cleanup is
safe to make.

WHAT IS ASSERTED
================
1. FORWARD (fails against the byte-identical pre-fix file): when the PDK
   exposes a distinct slow (SS) process library, the emitted TCL reads THAT
   library, not the nominal one.
2. STAMP (fails pre-fix): the report records which corner it timed, as every
   sibling STA emitter in this runner already does.
3. REVERSE (must STILL pass, pre-fix AND post-fix): a PDK that exposes only a
   single, uncorner-classified liberty keeps the pre-fix behaviour — the TCL
   reads that liberty and the emitter still succeeds. The fix must not tighten
   corner selection until single-liberty PDKs (the sky130A / gf180mcuD
   reality) stop being timed at all.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_spefsta",
    _PROGRAMS / "phase3_one_shot_runner.py",
)
p3 = importlib.util.module_from_spec(_SPEC)
# Register BEFORE exec: the module defines @dataclass types, and dataclasses
# resolves annotations via sys.modules[cls.__module__], which is None for a
# module that is still executing and unregistered.
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

CONTAINER = "test-container-no-such-container"


def _mk_project(tmp_path: Path, liberty_names):
    """A minimal routed project: pnr netlist + sdc + non-empty SPEF, and a
    staged `input/pdk/liberty` holding exactly `liberty_names`."""
    top = "dut"
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / f"{top}_pnr.v").write_text(f"module {top}(); endmodule\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")

    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    spef = ext / f"{top}.spef"
    spef.write_text("*SPEF \"IEEE 1481-1998\"\n")

    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    for n in liberty_names:
        (libdir / n).write_text("library (l) { }\n")

    return top, spef


def _mk_pdk(tmp_path: Path, nominal_lib_name: str):
    libdir = tmp_path / "input" / "pdk" / "liberty"
    return p3.PdkConfig(
        name="testpdk",
        liberty=str(libdir / nominal_lib_name),
        tech_lef=str(tmp_path / "tech.lef"),
        cell_lef=str(tmp_path / "cell.lef"),
        cell_gds=None,
        site="unit",
        drc_deck=None,
    )


@pytest.fixture(autouse=True)
def _no_docker(monkeypatch):
    """No container on the test host: pin mounts to empty (so
    `_to_container_path` is identity) and make the tool run a no-op that
    produces a plausible report, so `_emit_spef_sta` reaches its return."""
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])
    monkeypatch.setattr(p3, "_discover_aocv_table", lambda *a, **k: None)

    def _fake_exec(container, cmd, *a, **k):
        for out in (k.get("outputs") or []):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text("worst slack max 1.00\ntns max 0.00\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


def _emit(tmp_path, liberty_names, nominal):
    top, spef = _mk_project(tmp_path, liberty_names)
    pdk = _mk_pdk(tmp_path, nominal)
    rpt = tmp_path / "phase3" / "stage3" / "sta" / "sta_spef_based.rpt"
    notes: list = []
    ok = p3._emit_spef_sta(tmp_path, top, pdk, CONTAINER, spef, rpt, notes)
    tcl = (rpt.parent / "sta_spef_based.tcl").read_text()
    return ok, tcl, notes


def _read_liberty_lines(tcl: str):
    return [ln.strip() for ln in tcl.splitlines()
            if ln.strip().startswith("read_liberty ")]


# ---------------------------------------------------------------- FORWARD ---
def test_spef_sta_reads_the_slow_corner_liberty_not_the_nominal_one(tmp_path):
    """FAILS against the pre-fix file, which reads `pdk.liberty` (the typ lib)."""
    ok, tcl, _ = _emit(
        tmp_path,
        ["cellib_ss.lib", "cellib_typ.lib", "cellib_ff.lib"],
        nominal="cellib_typ.lib",
    )
    assert ok is True

    libs = _read_liberty_lines(tcl)
    assert libs, f"no read_liberty in emitted TCL:\n{tcl}"
    first = libs[0]

    assert first.endswith("cellib_ss.lib"), (
        "Step 23's declared sign-off artefact is timed at the wrong process "
        "corner. The PDK exposes a distinct slow (SS) library, but the emitted "
        f"TCL reads:\n    {first}\n"
        "A nominal-corner report publishes `wns max 0.00` on a design that can "
        "violate at the slow corner, and it is the ONLY STA artefact Step 23 "
        "declares."
    )
    assert "cellib_typ.lib" not in first


# ------------------------------------------------------------------ STAMP ---
def test_report_states_which_corner_it_timed(tmp_path):
    """FAILS pre-fix: the pre-fix report carried no basis/corner stamp at all,
    so a single-corner nominal run was indistinguishable from sign-off."""
    _, tcl, _ = _emit(
        tmp_path,
        ["cellib_ss.lib", "cellib_typ.lib"],
        nominal="cellib_typ.lib",
    )
    assert "STA_BASIS: POST_ROUTE_SPEF" in tcl
    assert "STA_SIGNOFF_CORNER: SS" in tcl
    assert "STA_SIGNOFF_CORNER_COUNT: 1" in tcl, (
        "a one-corner report must say so; Step 23 is declared MULTI-corner "
        "sign-off and must not be certifiable by a single corner"
    )


# ---------------------------------------------------------------- REVERSE ---
# Must pass BOTH before and after the fix. This is the control against
# "tighten the corner filter until it selects nothing": a PDK with a single,
# uncorner-classified liberty must keep being timed exactly as before.
def test_single_liberty_pdk_is_still_timed_with_that_liberty(tmp_path):
    ok, tcl, _ = _emit(tmp_path, ["cellib.lib"], nominal="cellib.lib")

    assert ok is True, (
        "a PDK exposing one uncorner-classified liberty must still produce a "
        "post-route STA — this is the sky130A / gf180mcuD reality and the fix "
        "must not drop it"
    )
    libs = _read_liberty_lines(tcl)
    assert libs and libs[0].endswith("cellib.lib"), (
        f"single-liberty PDK must still be read; got:\n{libs}"
    )
    # and the run must still reach the reporting commands
    assert "report_checks" in tcl and "read_spef" in tcl


def test_single_liberty_pdk_discloses_that_it_is_not_a_signoff_corner(tmp_path):
    """The degraded case must degrade LOUDLY: post-fix it is stamped NOMINAL
    and disclosed in notes, instead of silently looking like sign-off."""
    _, tcl, notes = _emit(tmp_path, ["cellib.lib"], nominal="cellib.lib")
    assert "STA_SIGNOFF_CORNER: NOMINAL" in tcl
    assert any("NOMINAL corner" in n for n in notes), notes
