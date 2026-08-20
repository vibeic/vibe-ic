#!/usr/bin/env python3
"""Die-wide dummy fill: the fill frame must be the DIE, not the layout bbox.

WHAT THIS DEFENDS, and where the bar comes from
-----------------------------------------------
Not this repo's opinion. The shuttle operator's own precheck container
(`ghcr.io/wafer-space/gf180mcu-precheck`, image digest
sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f), run
2026-08-20 against a sealed gf180mcuD 0.5x0.5-slot die this flow produced,
returned rc=1 with 8 KLayout density errors — DCF.1b, PL.8, M1.4, M2.4, M3.4,
M4.4, M5.4, MT.3 — every one reported against the whole die polygon
(0,0;1936,2531).

The fill was not missing. The flow's own `cmp_fill_emit.json` for that run reads
`metal2 0.0036 -> 0.4330, "reached": true`, and its `metal_density.json` reads
`"die_area_um2": 1732693` — which is the CORE bbox, 35.4 % of the 4900016 um2
die. Measured over the DIE instead, the same layers were COMP 3.04 %, Poly2
0.12 %, Metal1 8.26 %, Metal2 18.21 %, Metal3 17.97 %, Metal4 18.45 %,
Metal5 18.48 %, against floors of 25/14/30/30/30/30/30 in the PDK's own
`density.rb`. The fill was scoped to the wrong rectangle and nothing measured
the right one.

Running the PDK's OWN generator (`libs.tech/klayout/tech/scripts/fill_all.rb`)
over the sealed die took those to 26.38 / 29.35 / 31.97 / 41.92 / 48.10 /
48.28 / 37.46 % and the precheck's density stage to `{"total": 0}`.

Every test below breaks something the change defends and requires the failure:

  * the generator filled a frame that does not cover the die -> FAIL, naming
    the fraction it did cover, NOT a fill reported as die-wide
  * the generator exited 0 having written nothing            -> FAIL (this
    PDK's sibling `sealring.py` was measured doing exactly that)
  * the generator wrote a layout that gained no area         -> FAIL
  * the PDK ships no density filler                          -> DISCLOSED SKIP,
                                                                rc 2, naming
                                                                every location
                                                                searched
  * the step is not wired into both stream-out paths, or runs before the seal
    ring                                                     -> the ordering
                                                                assertions redden
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import die_density_fill_gen as DDF                            # noqa: E402

_RUNNER = _PROGRAMS / "phase3_one_shot_runner.py"
_DRIVER = _PROGRAMS / "density_fill" / "pdk_fill_driver.rb"
_MEASURE = _PROGRAMS / "density_fill" / "die_density_measure.py"


# ── the engines this program ships beside itself ────────────────────────────

def test_the_two_engines_exist_and_are_what_the_program_names():
    assert _DRIVER.is_file() and _MEASURE.is_file()
    assert DDF._DRIVER_REL == "density_fill/pdk_fill_driver.rb"
    assert DDF._MEASURE_REL == "density_fill/die_density_measure.py"


def test_the_driver_loads_the_pdk_script_and_carries_no_fill_geometry():
    """The driver's whole job is to give the PDK script's globals their types.

    If it ever grows a fill cell, a pitch or a keep-out, the flow has started
    reimplementing foundry data instead of calling the foundry's generator —
    and the fill would then be this repo's opinion about a design manual it has
    never read.
    """
    rb = _DRIVER.read_text()
    assert "load script" in rb
    assert "$input" in rb and "$output" in rb and "$threads" in rb
    for reimplementation in ("fill_region", "row_step", "column_step",
                             "DBox::new", "TilingProcessor"):
        assert reimplementation not in rb, reimplementation


def test_the_measurement_applies_no_floor_and_writes_no_layer_number():
    """Which layer must reach what coverage is the PDK density deck's to say.

    A second, independently-written floor here would be a second opinion about
    foundry data — and the one that silently disagreed would be believed.
    """
    src = _MEASURE.read_text()
    assert "over_die" in src and "over_bbox" in src
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    # No bare density threshold and no GDS layer number in the logic.
    for literal in ("0.30", "0.25", "0.14", "34, 0", "81, 0", "22, 4"):
        assert literal not in body, literal


# ── resolution: an absence must NAME where it looked ────────────────────────

def test_absent_generator_is_a_disclosed_skip_that_names_every_location(tmp_path, monkeypatch):
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    monkeypatch.delenv(DDF._ENV_SCRIPT, raising=False)
    script, src, tried = DDF.resolve_script(tmp_path, None, None, None)
    assert script is None and src == ""
    assert any(DDF._BRIDGE_KEY in t for t in tried)
    assert any(DDF._ENV_SCRIPT in t for t in tried)
    assert any(DDF._PDK_SCRIPT_REL in t for t in tried)


def test_resolution_order_is_explicit_then_bridge_then_env_then_convention(tmp_path, monkeypatch):
    assert DDF.resolve_script(tmp_path, "/x/explicit.rb", None, None)[0] == "/x/explicit.rb"
    bridge = tmp_path / DDF._BRIDGE_CFG
    bridge.parent.mkdir(parents=True, exist_ok=True)
    bridge.write_text(json.dumps({DDF._BRIDGE_KEY: {"script": "/x/bridge.rb"}}))
    assert DDF.resolve_script(tmp_path, None, None, None)[0] == "/x/bridge.rb"
    bridge.write_text("{}")
    monkeypatch.setenv(DDF._ENV_SCRIPT, "/x/env.rb")
    assert DDF.resolve_script(tmp_path, None, None, None)[0] == "/x/env.rb"
    monkeypatch.delenv(DDF._ENV_SCRIPT)
    got, src, _ = DDF.resolve_script(tmp_path, None, "/pdks", "somepdk")
    assert got == "/pdks/somepdk/" + DDF._PDK_SCRIPT_REL
    assert src.startswith("$PDK_ROOT/$PDK/")


# ── the fake runner: everything below drives the real control flow ──────────

class _FakeRunner:
    """A KLayout runner whose measurements and fill are scripted by the test.

    `measurements` is consumed one per `die_density_measure` invocation, so a
    test states the BEFORE and AFTER layout as data. `fill` decides what the
    generator does to the output path.
    """

    kind = "fake"
    detail = "fake"

    def __init__(self, measurements, fill="write", rc=0, output=""):
        self._m = list(measurements)
        self._fill = fill
        self._rc = rc
        self._out = output

    def cpath(self, p):
        return str(p)

    def covers(self, p):
        return True

    def exists(self, p):
        return True

    def run(self, script, env, *, path_keys=(), timeout=1800):
        if Path(str(script)).name == "die_density_measure.py":
            Path(env["DENS_OUT"]).write_text(json.dumps(self._m.pop(0)))
            return 0, "", ""
        # the fill driver
        if self._fill == "write":
            Path(env["VIBEIC_FILL_OUT"]).write_bytes(b"filled")
        return self._rc, self._out, ""

    def run_argv(self, argv, env, *, timeout=1800):
        raise AssertionError("not used")


def _measurement(bbox, die, layers_area):
    die_area = (die[2] - die[0]) * (die[3] - die[1])
    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    eps = 0.001
    return {
        "bbox_um": bbox,
        "bbox_area_um2": bbox_area,
        "die_um": die,
        "die_area_um2": die_area,
        "bbox_covers_die": (bbox[0] <= die[0] + eps and bbox[1] <= die[1] + eps
                            and bbox[2] >= die[2] - eps and bbox[3] >= die[3] - eps),
        "bbox_area_over_die_area": bbox_area / die_area,
        "by_layer": {
            str(l): {"area_um2": a, "datatypes": [0, 4],
                     "over_die": a / die_area, "over_bbox": a / bbox_area}
            for l, a in layers_area.items()},
        "by_layer_datatype": {},
    }


def _project(tmp_path):
    gds = tmp_path / "phase3" / "stage3" / "pnr" / "spm.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_bytes(b"unfilled")
    return gds


DIE = [0.0, 0.0, 1936.0, 2531.0]
CORE = [441.97, 442.0, 1494.0, 2089.0]


def test_a_fill_whose_frame_does_not_cover_the_die_is_a_named_failure(tmp_path, monkeypatch):
    """THE DEFECT THIS CHANGE EXISTS FOR.

    The PDK generator's fill frame is `$ly.top_cell().dbbox()`. Given a layout
    that spans only the routed core, it fills the core, exits 0, and every
    per-layer number it produces is a true statement about the core and a false
    one about the die. The step must refuse the DIE-WIDE claim while keeping the
    fill it did deposit, and it must say what fraction of the die it reached —
    a reader who is only told "partial" cannot tell 99 % from 35 %.
    """
    gds = _project(tmp_path)
    before = _measurement(CORE, DIE, {34: 100.0})
    after = _measurement(CORE, DIE, {34: 700000.0})
    monkeypatch.setattr(DDF._kl, "find_runner",
                        lambda *a, **k: _FakeRunner([before, after]))
    res = DDF.run(tmp_path, str(gds), "/pdk/fill_all.rb", None, "somepdk",
                  1936, 2531, "spm", 8, False, None, True, None, 60)
    fill = res["fill"]
    assert fill["state"] == "FAIL", fill
    assert fill["bbox_covers_die"] is False
    assert "35.4 %" in fill["reason"], fill["reason"]
    assert "does NOT cover the declared die" in fill["reason"]
    # The fill that WAS deposited is kept — refusing the claim must not throw
    # away legitimate foundry fill.
    assert gds.read_bytes() == b"filled"


def test_the_same_fill_on_a_sealed_die_passes(tmp_path, monkeypatch):
    """The other side of the same gate: identical program, identical generator,
    a layout whose bounding box IS the die. Without this the test above would
    be satisfied by a step that always fails."""
    gds = _project(tmp_path)
    before = _measurement(DIE, DIE, {34: 404500.0})
    after = _measurement(DIE, DIE, {34: 1566500.0})
    monkeypatch.setattr(DDF._kl, "find_runner",
                        lambda *a, **k: _FakeRunner([before, after]))
    res = DDF.run(tmp_path, str(gds), "/pdk/fill_all.rb", None, "somepdk",
                  1936, 2531, "spm", 8, False, None, True, None, 60)
    fill = res["fill"]
    assert fill["state"] == "PASS", fill
    assert fill["bbox_covers_die"] is True
    assert fill["layers_gained_fill"] == [34]
    cov = fill["coverage_over_die"]["34"]
    assert cov["over_die_before"] < 0.10 < 0.30 < cov["over_die_after"]


def test_a_generator_that_exits_zero_writing_nothing_is_a_failure(tmp_path, monkeypatch):
    """MEASURED on this PDK's sibling generator: `sealring.py` ends a failed
    import with a bare `sys.exit()`, which exits 0 and writes no file. Reading
    the exit code would have recorded a fill that does not exist."""
    gds = _project(tmp_path)
    before = _measurement(DIE, DIE, {34: 404500.0})
    monkeypatch.setattr(
        DDF._kl, "find_runner",
        lambda *a, **k: _FakeRunner([before], fill="nothing", rc=0,
                                    output="Error: Couldn't load the fill library."))
    res = DDF.run(tmp_path, str(gds), "/pdk/fill_all.rb", None, "somepdk",
                  1936, 2531, "spm", 8, False, None, True, None, 60)
    fill = res["fill"]
    assert fill["state"] == "FAIL"
    assert fill["generator_rc"] == 0
    assert "produced no output layout" in fill["reason"]
    assert "Couldn't load the fill library" in fill["reason"]
    assert gds.read_bytes() == b"unfilled"                    # untouched


def test_a_generator_that_deposits_no_area_is_a_failure(tmp_path, monkeypatch):
    gds = _project(tmp_path)
    same = {34: 404500.0}
    monkeypatch.setattr(
        DDF._kl, "find_runner",
        lambda *a, **k: _FakeRunner([_measurement(DIE, DIE, same),
                                     _measurement(DIE, DIE, same)]))
    res = DDF.run(tmp_path, str(gds), "/pdk/fill_all.rb", None, "somepdk",
                  1936, 2531, "spm", 8, False, None, True, None, 60)
    assert res["fill"]["state"] == "FAIL"
    assert "not one layer gained area" in res["fill"]["reason"]
    assert gds.read_bytes() == b"unfilled"


def test_no_klayout_is_a_disclosed_skip_not_a_pass(tmp_path, monkeypatch):
    gds = _project(tmp_path)
    monkeypatch.setattr(DDF._kl, "find_runner", lambda *a, **k: None)
    res = DDF.run(tmp_path, str(gds), "/pdk/fill_all.rb", None, "somepdk",
                  1936, 2531, "spm", 8, False, None, True, None, 60)
    assert res["fill"]["state"] == "DISCLOSED_SKIP"


def test_the_cli_maps_states_to_exit_codes_and_marks_a_skip_vacuous(tmp_path, monkeypatch, capsys):
    gds = _project(tmp_path)
    monkeypatch.setattr(DDF._kl, "find_runner", lambda *a, **k: None)
    rc = DDF.main([str(tmp_path), "--gds", str(gds), "--in-place",
                   "--script", "/pdk/fill_all.rb", "--pdk", "somepdk",
                   "--die-width", "1936", "--die-height", "2531"])
    assert rc == DDF.SKIP
    assert capsys.readouterr().out.startswith("VACUOUS_PASS: ")


# ── the wiring: the step must run, in both paths, AFTER the seal ring ───────

def test_the_step_is_wired_into_both_streamout_paths_after_the_seal_ring():
    """ORDER IS PART OF THE FIX. The PDK generator's frame is the layout
    bounding box and its scribe keep-out is measured inward from that frame, so
    it can only fill the die once the seal ring has made the bounding box the
    die. Running it before the ring would fill the core and — by the gate above
    — fail, correctly but pointlessly."""
    src = _RUNNER.read_text()
    assert "def _die_density_fill(" in src
    calls = [i for i, l in enumerate(src.splitlines())
             if "_die_density_fill(project" in l and "def " not in l]
    seals = [i for i, l in enumerate(src.splitlines())
             if "_die_finishing(project" in l and "def " not in l]
    assert len(calls) == 2, calls                             # both streamout paths
    assert len(seals) == 2, seals
    for seal, call in zip(seals, calls):
        assert seal < call, (seal, call)


def test_the_step_reports_its_outcome_in_both_paths_extras():
    src = _RUNNER.read_text()
    assert src.count('"die_density_fill": ddfill_ok,') == 2
    assert src.count('"die_density_fill_note": ddfill_note,') == 2


def test_the_report_name_cannot_be_eaten_by_the_metal_density_check():
    """`metal_layer_density_check` rglobs `*metal*density*.json` project-wide
    and would ingest this report as if it were a per-layer density measurement.
    The name is load-bearing, so it is asserted rather than assumed."""
    import fnmatch
    name = Path(DDF._REPORT_REL).name
    assert not fnmatch.fnmatch(name, "*metal*density*.json"), name


def test_the_program_is_pdk_agnostic():
    """No foundry, PDK, vendor, design or layer literal in the producer."""
    body = "\n".join(
        l for l in (_PROGRAMS / "die_density_fill_gen.py").read_text().splitlines()
        if not l.lstrip().startswith("#"))
    head, _, body = body.partition('"""')
    _, _, body = body.partition('"""')                        # drop the docstring
    for literal in ("gf180", "sky130", "ihp-", "Metal1", "spm", "1936"):
        assert literal not in body, literal


def test_the_program_runs_standalone_and_refuses_without_a_project():
    cp = subprocess.run([sys.executable,
                         str(_PROGRAMS / "die_density_fill_gen.py")],
                        capture_output=True, text=True, timeout=120)
    assert cp.returncode != 0
