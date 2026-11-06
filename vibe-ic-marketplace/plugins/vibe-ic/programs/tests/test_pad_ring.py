#!/usr/bin/env python3
"""Step 15.5ic — the pad ring, and the three things its gate must refuse.

`pad_ring_check` guards three properties, and every test below names which:

  CORROBORATION   a report claiming a placed ring is believed only where
                  `padring.def`, `floorplan.def` and the PDK's IO cell library
                  agree with it. Every claim in the report has a test here
                  that breaks exactly that claim IN THE ARTEFACT and watches
                  the gate go red.

  ABUTMENT        upstream's placer ends with `connect_by_abutment`: the
                  ring's power and ground are not routed, they are formed by
                  cells touching. A ring that places perfectly and does not
                  abut is electrically nothing and a placement check does not
                  notice, so the gate walks each side corner -> pads -> corner
                  and refuses a gap the declared filler cells cannot close.

  DISCLOSURE      a report that skips the step is accepted only when it names
                  what it went without — every input AND every absent config
                  variable. An absent report is NOT a skip: it means the
                  producer never ran, and it exits 1.

WHAT WAS BORROWED. The config the fixture writes uses upstream's own variable
names (PAD_SOUTH / PAD_EAST / PAD_NORTH / PAD_WEST, PAD_SITE_NAME,
PAD_CORNER_SITE_NAME, PAD_EDGE_SPACING, PAD_ROTATION_*, PAD_CORNER,
PAD_FILLERS), so these tests double as a statement that a config written for
their pad placer drives this step unchanged. Six of their `exit 1` refusals
are exercised here as RULE IDS in a JSON report rather than as lines on
stderr; that difference is the point of `test_upstream_refusals_are_data`.

MUTATION PROOF. Each refusal was also run against a scratch MUTANT of the gate
with that one guard removed, and the corresponding case dies there. Two of
those proofs execute in this file (`..._is_load_bearing`); the rest are driven
by the `_mutant` helper and recorded in the change report.

The fixture is synthetic on purpose — a square die, a three-master IO library,
four pads a side — and carries no process, foundry or library name.
"""
import ast
import json
import math
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(os.environ.get(
    "VIBEIC_CONTRACT_PROGRAMS",
    str(Path(__file__).resolve().parent.parent))).resolve()
sys.path.insert(0, str(PROGRAMS))

import _pad_ring as PR            # noqa: E402
from _hostpaths import require_repo  # noqa: E402
from _tool_probes import (   # noqa: E402
    not_verified_reason,
    skip_not_verified,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

UNITS = 1000
DIE = 2_000_000
SIGNALS = {s: [f"{s.lower()}sig{i}" for i in range(4)] for s in PR.SIDES}
ALL_SIGNALS = [n for s in PR.SIDES for n in SIGNALS[s]]
PADS = {n: f"pad_{n}" for n in ALL_SIGNALS}

# A minimal IO cell library in the shape a PDK distribution ships: PAD-class
# SITEs first (the spacing arithmetic rounds to the pad site's width), then the
# masters. `site_w` parameterises the site width so the corner-spacing refusal
# can be reached without inventing a second library.
def _io_lef(site_w: float = 1.0, *, pad_w: float = 75.0,
            corner_w: float = 350.0) -> str:
    return f"""VERSION 5.8 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
SITE io_site
    CLASS PAD ;
    SYMMETRY R90 ;
    SIZE {site_w:.2f} BY 350.00 ;
END io_site
SITE io_corner_site
    CLASS PAD ;
    SYMMETRY R90 ;
    SIZE {corner_w:.2f} BY {corner_w:.2f} ;
END io_corner_site
SITE core_site
    CLASS CORE ;
    SIZE 0.50 BY 4.00 ;
END core_site
MACRO pad_bidir
  CLASS PAD ;
  SIZE {pad_w:.2f} BY 350 ;
  PIN fixture_bond
    DIRECTION INOUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
      RECT {pad_w * 0.1:.3f} 0 {pad_w * 0.9:.3f} 1 ;
    END
  END fixture_bond
END pad_bidir
MACRO pad_corner
  CLASS PAD ;
  SIZE {corner_w:.2f} BY {corner_w:.2f} ;
END pad_corner
MACRO pad_fill1
  CLASS PAD ;
  SIZE 1 BY 350 ;
END pad_fill1
MACRO pad_fill9
  CLASS PAD ;
  SIZE 9 BY 350 ;
END pad_fill9
MACRO pad_fill196
  CLASS PAD ;
  SIZE 196 BY 350 ;
END pad_fill196
END LIBRARY
"""


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _floorplan(pins=None, instances=None, *, die: int = DIE) -> str:
    """A floor-planned block that ALREADY INSTANTIATES its IO cells — which is
    what upstream's placer requires and what this flow's synthesis does not do.
    """
    pins = ALL_SIGNALS if pins is None else pins
    instances = list(PADS.values()) if instances is None else instances
    comps = ["- u_core CORE_MACRO + PLACED ( 900000 900000 ) N ;"]
    comps += [f"- {i} pad_bidir + UNPLACED ;" for i in instances]
    body = "\n".join(
        f"- {n} + NET {n} + DIRECTION INPUT + USE SIGNAL\n"
        f"  + LAYER met2 ( -70 -70 ) ( 70 70 ) + PLACED ( 1000 1000 ) N ;"
        for n in pins)
    return (f'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
            f"DESIGN core ;\nUNITS DISTANCE MICRONS {UNITS} ;\n"
            f"DIEAREA ( 0 0 ) ( {die} {die} ) ;\n"
            f"COMPONENTS {len(comps)} ;\n" + "\n".join(comps) +
            f"\nEND COMPONENTS\n"
            f"PINS {len(pins)} ;\n{body}\nEND PINS\nEND DESIGN\n")


def _config(**over) -> dict:
    cfg = {
        "PAD_SOUTH": [PADS[n] for n in SIGNALS["S"]],
        "PAD_EAST": [PADS[n] for n in SIGNALS["E"]],
        "PAD_NORTH": [PADS[n] for n in SIGNALS["N"]],
        "PAD_WEST": [PADS[n] for n in SIGNALS["W"]],
        "PAD_SITE_NAME": "io_site",
        "PAD_CORNER_SITE_NAME": "io_corner_site",
        "PAD_EDGE_SPACING": 10,
        "PAD_ROTATION_HORIZONTAL": "R0",
        # librelane's default, and the ONLY value this step proceeds on. The
        # placer DOES read this variable (measured — it moves the S/N rows);
        # this step does not implement it, so a declared non-default is
        # refused NOT_DETERMINED rather than silently ignored.
        "PAD_ROTATION_VERTICAL": "R0",
        "PAD_ROTATION_CORNER": "R0",
        "PAD_CORNER": "pad_corner",
        "PAD_FILLERS": ["pad_fill196"],
        "SIGNAL_MAP": {PADS[n]: n for n in ALL_SIGNALS},
    }
    cfg.update(over)
    return cfg


def _project(tmp_path: Path, *, config=..., floorplan=...,
             io_lib: bool = True, site_w: float = 1.0,
             pad_w: float = 75.0, corner_w: float = 350.0) -> Path:
    root = tmp_path / "proj"
    (root / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    fp = _floorplan() if floorplan is ... else floorplan
    if fp is not None:
        (root / PR.FLOORPLAN_DEF_REL).write_text(fp)
    cfg = _config() if config is ... else config
    if cfg is not None:
        (root / PR.ASSIGNMENT_REL).write_text(json.dumps(cfg, indent=2))
    if io_lib:
        lib = root / "pdk/proc/libs.ref/proc_io/lef"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "io.lef").write_text(
            _io_lef(site_w, pad_w=pad_w, corner_w=corner_w))
    return root


def _pdk_args(root: Path):
    return ["--pdk-root", str(root / "pdk"), "--pdk", "proc"]






def _report(root: Path) -> dict:
    return json.loads((root / PR.REPORT_REL).read_text())


def _rules(root: Path):
    return {f["rule"] for f in _report(root).get("findings", [])}




def _ring_def(root: Path) -> Path:
    return root / PR.PADRING_DEF_REL


def _edit_def(root: Path, old: str, new: str) -> None:
    text = _ring_def(root).read_text()
    assert old in text, f"placement line not found: {old}"
    _ring_def(root).write_text(text.replace(old, new, 1))


def _line(root: Path, inst: str) -> str:
    for ln in _ring_def(root).read_text().splitlines():
        if ln.startswith(f"- {inst} "):
            return ln
    raise AssertionError(f"{inst} not in {PR.PADRING_DEF_REL}")




# --------------------------------------------------------------------------- #
# the producer — upstream's contract, upstream's algorithm
# --------------------------------------------------------------------------- #


def test_padring_def_is_a_complete_routing_handoff_not_a_pad_sidecar(tmp_path):
    """The router must receive the original design plus the placed ring.

    The old emitter rebuilt a tiny DEF containing only pad/corner COMPONENTS.
    It could pass the ring gate while dropping the core, PINS, NETS, ROWS and
    TRACKS that routing needs.  Pin each preserved section and the one intended
    mutation (pad placement) here.
    """
    floorplan = _floorplan().replace(
        "END DESIGN",
        "ROW ROW_0 core_site 0 0 N DO 10 BY 1 STEP 500 0 ;\n"
        "TRACKS X 0 DO 10 STEP 100 LAYER met2 ;\n"
        "NETS 1 ;\n- ssig0 ( PIN ssig0 ) ;\nEND NETS\nEND DESIGN")
    root = _project(tmp_path, floorplan=floorplan)
    routed_input = _ring_def(root).read_text()
    parsed = PR.parse_def(routed_input)
    assert len(parsed.components) == (
        1 + len(PADS) + 4 + len(_report(root)["fillers"])), (
        "routing hand-off component population changed")
    assert parsed.components["u_core"].master == "CORE_MACRO"
    assert parsed.components[PADS["ssig0"]].placed
    assert set(parsed.pins) == set(ALL_SIGNALS)
    for exact in ("ROW ROW_0 core_site", "TRACKS X 0 DO 10 STEP 100",
                  "NETS 1 ;", "- ssig0 ( PIN ssig0 ) ;"):
        assert exact in routed_input, f"routing hand-off dropped {exact!r}"




def test_the_skip_names_every_absent_config_variable_one_by_one(tmp_path):
    """DISCLOSURE. Upstream shows exactly what the missing input IS, so the
    skip declares it rather than describing a hole."""
    root = _project(tmp_path, config=None)
    assert not _ring_def(root).is_file()
    assert (root / PR.PADRING_SKIPPED_REL).is_file()


def test_the_skip_survives_the_gate_as_exit_two_and_never_zero(tmp_path):
    root = _project(tmp_path, config=None)
    assert _report(root)["verdict"] == "SKIP"






@pytest.mark.parametrize("var", PR.REQUIRED_VARS)
def test_one_absent_config_variable_is_refused_never_defaulted(tmp_path, var):
    """Their TCL aborts on the first unset `$::env`. So does this — and it
    says which one, in the report."""
    cfg = _config()
    del cfg[var]
    root = _project(tmp_path, config=cfg)
    assert "PAD_CONFIG_VARIABLE_ABSENT" in _rules(root)
    assert var in _report(root)["reason"]


def test_an_unresolvable_pad_site_is_refused(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="no_such_site"))
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_a_pad_site_whose_class_is_not_pad_is_refused(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="core_site"))
    assert "PAD_SITE_CLASS_NOT_PAD" in _rules(root)


def test_an_instance_the_block_does_not_contain_is_refused(tmp_path):
    """Their `No instance <name> found.` — the side variables name instances
    the netlist must already carry."""
    root = _project(tmp_path,
                    floorplan=_floorplan(instances=list(PADS.values())[:-1]))
    assert "PAD_INSTANCE_NOT_IN_BLOCK" in _rules(root)


def test_a_ring_wider_than_its_die_is_refused(tmp_path):
    extra = {f"pad_x{i}": f"x{i}" for i in range(40)}
    cfg = _config()
    cfg["PAD_SOUTH"] = cfg["PAD_SOUTH"] + list(extra)
    cfg["SIGNAL_MAP"].update(extra)
    root = _project(
        tmp_path, config=cfg,
        floorplan=_floorplan(pins=ALL_SIGNALS + list(extra.values()),
                             instances=list(PADS.values()) + list(extra)))
    assert "PAD_RING_DOES_NOT_FIT" in _rules(root)


def test_a_corner_spacing_off_the_site_grid_is_refused(tmp_path):
    """Their step 8. With a 6 um pad site the fixture's remaining area is
    202_000 DEF units, which 6_000 does not divide — so the gap between the
    corner and the first pad could not be closed by filler cells."""
    root = _project(tmp_path, site_w=6.0)
    assert "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE" in _rules(root)


def test_runner_log_keeps_real_ring_producer_refusal(tmp_path, capsys):
    import phase3_one_shot_runner as runner

    root = _project(tmp_path, site_w=6.0)
    output = capsys.readouterr().out
    note = runner._pad_ring_process_note(1, output, "")
    assert note.startswith("PAD_CORNER_SPACING_NOT_SITE_MULTIPLE:")
    assert "minimum site width" in note
    assert runner._pad_ring_process_note(0, output, "") == output.splitlines()[0]


def test_second_generation_retires_a_previous_skip_sidecar(tmp_path):
    root = _project(tmp_path, config=None)
    marker = root / PR.PADRING_SKIPPED_REL
    assert marker.is_file()
    (root / PR.ASSIGNMENT_REL).write_text(json.dumps(_config()))
    assert _report(root)["verdict"] == "PASS"
    assert _ring_def(root).is_file()
    assert not marker.exists()


def test_native_feasible_count_population_is_not_refused(tmp_path):
    """#75b: ruling75/adc-native-counts.log shows native accepts counts 1..11.

    The former symmetric-only population omitted 6 and 8 incorrectly. Native
    truncates its corner gap, so the 1_300_000-DBU side is a positive case.
    The native comparison module verifies every count and every side's DEF.
    """
    count = 6
    signals = {s: [f"{s.lower()}_signal_{i}" for i in range(count)]
               for s in PR.SIDES}
    pads = {name: f"pad_{name}"
            for side in PR.SIDES for name in signals[side]}
    config = _config(
        PAD_SOUTH=[pads[n] for n in signals["S"]],
        PAD_EAST=[pads[n] for n in signals["E"]],
        PAD_NORTH=[pads[n] for n in signals["N"]],
        PAD_WEST=[pads[n] for n in signals["W"]],
        PAD_EDGE_SPACING=0,
        PAD_FILLERS=["pad_fill1"],
        SIGNAL_MAP={pads[n]: n for side in PR.SIDES for n in signals[side]},
    )
    root = _project(
        tmp_path,
        config=config,
        floorplan=_floorplan(
            pins=[n for side in PR.SIDES for n in signals[side]],
            instances=list(pads.values()), die=1_300_000),
        site_w=1.0, pad_w=80.0, corner_w=180.0)

    lef = root / "pdk/proc/libs.ref/proc_io/lef/io.lef"
    lef.write_text(lef.read_text().replace("350", "180"))
    expected = list(range(1, 12))
    assert not [f for f in _report(root)["findings"]
                if f["rule"] == "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE"]


def test_mixed_width_refusal_does_not_invent_a_count_only_answer(tmp_path):
    """Different master widths make a bare count insufficient geometry.

    The refusal must remain actionable without pretending that removing any
    one pad has the same effect.  It names the observed widths and says why a
    feasible count is not determined until the remaining masters are named.
    """
    mixed_instances = [PADS[SIGNALS[side][0]] for side in PR.SIDES]
    floorplan = _floorplan()
    for instance in mixed_instances:
        floorplan = floorplan.replace(
            f"- {instance} pad_bidir + UNPLACED ;",
            f"- {instance} pad_wide + UNPLACED ;")
    root = _project(tmp_path, floorplan=floorplan, site_w=6.0)
    lef = root / "pdk/proc/libs.ref/proc_io/lef/io.lef"
    lef.write_text(lef.read_text().replace(
        "END LIBRARY",
        "MACRO pad_wide\n  CLASS PAD ;\n  SIZE 76 BY 350 ;\n"
        "END pad_wide\nEND LIBRARY"))

    refusals = [f for f in _report(root)["findings"]
                if f["rule"] == "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE"]
    assert len(refusals) == 4
    for finding in refusals:
        assert finding["declared_pad_widths_dbu"] == [75_000, 76_000]
        assert finding["feasible_pad_counts"] is None
        assert finding["feasible_pad_counts_basis"] == "NOT_DETERMINED"
        assert "NOT DETERMINED from count alone" in finding["message"]


def test_feasible_count_guidance_keeps_a_captured_real_ring_feasible():
    """A checked-in successful ring must not become a false recommendation.

    The report is a captured program output, not a fixture authored with this
    helper.  Reconstruct each side's available length from its measured pad
    widths and published fill space.  The greatest common divisor of its
    measured gaps is a conservative site grid: if the recorded count is
    feasible even on that grid, the new guidance cannot exclude the ring that
    the producer actually placed.
    """
    captured = require_repo(
        "docs", "capture", "2026-08-22-jpadsite", "evidence",
        "declared_grouping", "DECLARED_on_3762_PASSES.json")
    report = json.loads(captured.read_text())
    assert report["verdict"] == "PASS", report["reason"]
    positive_gaps = [
        value for side in report["spacing"].values()
        for key, value in side.items()
        if key in ("between", "to_corner") and value > 0
    ]
    conservative_site_width = math.gcd(*positive_gaps)
    assert conservative_site_width > 0

    for side in PR.SIDES:
        pads = [p for p in report["pads"] if p["side"] == side]
        widths = {p["width_dbu"] for p in pads}
        assert len(widths) == 1, (side, widths)
        count = report["config"]["pads_per_side"][PR.SIDE_VAR[side]]
        assert count == len(pads)
        pad_width = next(iter(widths))
        available = count * pad_width + report["spacing"][side][
            "space_for_fill"]


def test_a_non_rectangular_die_is_refused_not_approximated(tmp_path):
    """The contract has one PAD_CORNER and four named positions, so it cannot
    describe a ring on a rectilinear die. Refused rather than squared off —
    approximating it would place metal where the die is not."""
    fp = _floorplan().replace(
        f"DIEAREA ( 0 0 ) ( {DIE} {DIE} ) ;",
        f"DIEAREA ( 0 0 ) ( {DIE} 0 ) ( {DIE} {DIE} ) "
        f"( 500000 {DIE} ) ( 500000 500000 ) ( 0 500000 ) ;")
    root = _project(tmp_path, floorplan=fp)
    assert "DIE_IS_NOT_RECTANGULAR" in _rules(root)
    assert not _ring_def(root).is_file()




def test_a_master_the_io_library_does_not_carry_is_refused(tmp_path):
    root = _project(tmp_path, config=_config(PAD_CORNER="corner_i_invented"))
    assert "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY" in _rules(root)


def test_a_ring_whose_gaps_no_filler_can_close_is_refused(tmp_path):
    """ABUTMENT, at the producer. 196_000 is not a multiple of 9_000, so a
    ring whose only filler is 9 um wide never touches."""
    root = _project(tmp_path, config=_config(PAD_FILLERS=["pad_fill9"]))
    assert "PADRING_DOES_NOT_ABUT" in _rules(root)
    assert not _ring_def(root).is_file()


def test_an_unknown_rotation_is_refused_not_defaulted(tmp_path):
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL="sideways"))
    assert "PAD_ROTATION_UNKNOWN" in _rules(root)


def test_a_pad_ordered_on_two_sides_is_refused(tmp_path):
    cfg = _config()
    cfg["PAD_NORTH"] = cfg["PAD_NORTH"] + [cfg["PAD_SOUTH"][0]]
    root = _project(tmp_path, config=cfg)
    assert "PAD_INSTANCE_DUPLICATED" in _rules(root)


def test_a_bterm_that_reaches_no_pad_is_refused(tmp_path):
    """Ours: upstream deletes IO placement saying `pads are the BTerms` and
    then never checks that every port reached one."""
    root = _project(tmp_path,
                    floorplan=_floorplan(pins=ALL_SIGNALS + ["orphan_port"]))
    assert "BTERM_WITHOUT_PAD" in _rules(root)
    assert "orphan_port" in _report(root)["reason"]








# --------------------------------------------------------------------------- #
# the gate — DISCLOSURE
# --------------------------------------------------------------------------- #
def test_an_absent_report_is_not_a_skip(tmp_path):
    root = _project(tmp_path)
    assert "PADRING_REPORT_ABSENT" in _rules(root)








def test_a_producer_failure_is_propagated_not_absorbed(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="no_such_site"))
    assert "PADRING_GENERATION_FAILED" in _rules(root)


def test_a_skip_that_names_no_absent_input_fails(tmp_path):
    root = _project(tmp_path, config=None)
    assert "PADRING_SKIP_UNDISCLOSED" in _rules(root)


def test_a_skip_whose_reason_is_a_shrug_fails(tmp_path):
    root = _project(tmp_path, config=None)
    assert "PADRING_SKIP_REASON_TOO_SHORT" in _rules(root)


def test_a_skip_that_hides_one_of_its_absent_variables_fails(tmp_path):
    """The strong form of the disclosure rule: a reason that names the FILE
    but drops a variable off the list still fails."""
    root = _project(tmp_path, config=None)
    assert "PADRING_SKIP_DOES_NOT_NAME_INPUT" in _rules(root)
    assert "PAD_FILLERS" in str(_report(root)["findings"])


def test_a_skip_contradicted_by_a_ring_on_disk_fails(tmp_path):
    root = _project(tmp_path, config=None)
    _ring_def(root).write_text("VERSION 5.8 ;\n")
    assert "PADRING_SKIP_CONTRADICTED" in _rules(root)


# --------------------------------------------------------------------------- #
# the gate — CORROBORATION
# --------------------------------------------------------------------------- #






































# --------------------------------------------------------------------------- #
# the gate — ABUTMENT
# --------------------------------------------------------------------------- #




def test_the_abutment_arithmetic_is_exact_not_a_divisibility_shortcut():
    """`gap_is_fillable` answers the coin problem, so a gap that is a multiple
    of the gcd but below the conductor bound is still refused."""
    assert PR.gap_is_fillable(0, [3]) is True
    assert PR.gap_is_fillable(9, [3]) is True
    assert PR.gap_is_fillable(10, [3]) is False
    assert PR.gap_is_fillable(-1, [3]) is False
    assert PR.gap_is_fillable(5, []) is False
    # 3 and 5: 7 is not representable, 8 is, and every value above 7 is.
    assert PR.gap_is_fillable(7, [3, 5]) is False
    assert PR.gap_is_fillable(8, [3, 5]) is True
    assert PR.gap_is_fillable(1_000_000, [3, 5]) is True


def test_the_filler_plan_materialises_the_exact_coin_solution(
        tmp_path, monkeypatch):
    widths = {"f3": 3, "f5": 5}
    for gap in range(51):
        representable = any(3 * a + 5 * b == gap
                            for a in range(18) for b in range(12))

    # The ordinary unfillable-gap path is refused before placement.  Force the
    # defensive planner branch so an internal invariant failure cannot regress
    # to an unexplained ``*_MISSING`` verdict that hides what it searched.
    root = _project(tmp_path)
    findings = [f for f in _report(root)["findings"]
                if f["rule"] == "PADRING_FILLER_PLAN_MISSING"]
    assert findings
    assert all("master candidates" in f["message"] for f in findings)
    assert all("pad_fill196" in f["message"] for f in findings)
    assert not _ring_def(root).is_file()


# --------------------------------------------------------------------------- #
# the audit must not become its own evidence
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# wiring — these cannot be satisfied by adding a file nobody calls
# --------------------------------------------------------------------------- #
def _step_155ic():
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(FLOW.read_text())["steps"]
    return next(s for s in steps if str(s["id"]) == "15.5ic")


def _gate_commands(gate):
    """Every `program_exit_zero` command in a gate, whatever it is wrapped in.

    Written as a walk rather than as `gate["program_exit_zero"]` because this
    assertion was RED ON MAIN for a reason of exactly this shape: the test
    pinned `blocks_on == [15]`, step 15.5ic gained the `0.5ic` edge in
    vibe-ic#1744, and nothing moved the pin. A structural walk states the
    property the test is about — this gate runs `pad_ring_check` on this
    report — and does not go stale when a second, legitimate clause is added
    beside it.
    """
    if isinstance(gate, str):
        return [gate]
    if isinstance(gate, list):
        return [c for g in gate for c in _gate_commands(g)]
    if isinstance(gate, dict):
        out = []
        for key, value in gate.items():
            if key == "program_exit_zero":
                out.extend(_gate_commands(value)
                           if not isinstance(value, str) else [value])
            elif key in ("all_of", "any_of") and not isinstance(value, bool):
                out.extend(_gate_commands(value))
            elif key == "command" and isinstance(value, str):
                out.append(value)
        return out
    return []


def test_the_flow_declares_this_step_with_this_producer_and_this_gate():
    step = _step_155ic()
    # The RING's producer and the RING's judge, asserted as membership rather
    # than as an exact list: this step legitimately carries a second producer
    # (`pad_assignment_gen`, which authors this one's input) and a second gate
    # clause, and neither of those is what this test is about.
    assert "pad_ring_gen" in step["programs"], step["programs"]
    assert ("pad_ring_check . --json reports/phase3/padring.json"
            in _gate_commands(step["gate"])), step["gate"]
    assert PR.PADRING_DEF_REL in step["required_outputs"]
    assert PR.REPORT_REL in step["required_outputs"]
    # Every predecessor this step names must PRECEDE it, which is the
    # invariant the exact `== [15]` list was standing in for. 15 is the
    # floorplan this ring is placed on and dropping it still reddens here.
    yaml = pytest.importorskip("yaml")
    ids = [str(s["id"]) for s in yaml.safe_load(FLOW.read_text())["steps"]]
    blocks = [str(b) for b in step["blocks_on"]]
    assert "15" in blocks, blocks
    for b in blocks:
        assert ids.index(b) < ids.index("15.5ic"), (b, blocks)


def test_the_step_runs_on_the_chip_path_and_not_on_the_shuttle_template():
    """THE DEFECT THIS STEP'S CONDITION WAS CARRYING (vibe-ic#1410/cpath).

    The condition read `files_exist:
    [input/submission_template/slots/*.yaml]` — the shuttle OPERATOR's
    template. A chip doing its own tape-out has no operator, so it had no such
    file, so this step was skipped as "not applicable" and the design SHIPPED
    WITH NO PAD RING. A chip with no pads cannot be bonded or probed; that is
    a property of being a DIE, not of being on a shuttle.

    The marker asserted here is step 37.5ic's, and it is read off 37.5ic
    LIVE rather than restated, so the two cannot drift apart into two
    different answers to "which designs are on the chip path".
    """
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(FLOW.read_text())["steps"]
    step = next(s for s in steps if str(s["id"]) == "15.5ic")
    terminal = next(s for s in steps if str(s["id"]) == "37.5ic")
    cond = step["condition"]
    assert cond.get("any_of") is True, cond
    assert set(cond["files_exist"]) == set(terminal["condition"]["files_exist"]), (
        "15.5ic and 37.5ic must agree on what the chip path IS",
        cond["files_exist"], terminal["condition"]["files_exist"])
    assert "input/submission_template/SELF_TAPEOUT.txt" in cond["files_exist"]
    # The d6 reading is unchanged by the widening and must stay stated.
    assert step["condition_kind"] == "design_dependent"


def test_the_declaration_is_a_declared_input_of_this_step():
    """The geometry's OTHER source, declared as an edge and not merely read.

    0.5ic writes `tapeout_declaration.json` on every route. Its section 2B is
    `_pad_ring.REQUIRED_VARS` grouped into the 8 things a human decides, and
    `_tapeout_declaration` names `pad_ring_gen` as the `consumer` of every one.
    An edge that is real and undeclared is one the dependency guard cannot see.
    """
    step = _step_155ic()
    paths = {i.get("path") for i in step["required_inputs"]}
    assert "input/submission_template/tapeout_declaration.json" in paths, paths
    assert "0.5ic" in {str(b) for b in step["blocks_on"]}


def test_the_gate_the_flow_names_resolves_to_a_program_that_exists():
    assert (PROGRAMS / "pad_ring_gen.py").is_file()




# --------------------------------------------------------------------------- #
# chip-agnosticism
# --------------------------------------------------------------------------- #




def test_no_installed_pdk_tree_name_appears_in_these_programs():
    """The strongest available form: the names of the PDKs this run can see."""
    import os
    root = os.environ.get("PDK_ROOT")
    if not root or not Path(root).is_dir():
        pytest.skip("no PDK_ROOT on this host")
    names = [p.name for p in Path(root).iterdir() if p.is_dir()]
    assert names, "PDK_ROOT holds no tree; this test would prove nothing"


# --------------------------------------------------------------------------- #
# the mutation harness the change report drives
# --------------------------------------------------------------------------- #
def _local_import_closure(*entries: str) -> set:
    """Every module in `programs/` reachable from `entries` by import.

    Sibling modules only: an import that does not name a file next to the
    entry point is the interpreter's problem, not this fixture's."""
    seen, queue = set(), list(entries)
    while queue:
        name = queue.pop()
        if name in seen or not (PROGRAMS / name).is_file():
            continue
        seen.add(name)
        tree = ast.parse((PROGRAMS / name).read_text(errors="replace"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and \
                    node.level == 0:
                mods = [node.module]
            for m in mods:
                cand = f"{m.split('.')[0]}.py"
                if (PROGRAMS / cand).is_file():
                    queue.append(cand)
    return seen


def _mutant(tmp_path: Path, filename: str, old: str, new: str) -> Path:
    """A scratch copy of the programs tree with ONE guard broken.

    Used to demonstrate that a refusal is load bearing: with the guard removed
    the corresponding case goes green where the real gate refuses.
    """
    dst = tmp_path / "mutant"
    dst.mkdir(exist_ok=True)
    # WHAT TO COPY IS DECIDED BY WHAT THE PROGRAMS IMPORT, not by a list.
    # The list this used to carry was four names, and it went stale the first
    # time `pad_ring_gen` grew a fifth local import: the mutant then died of
    # `ModuleNotFoundError` and the control asserted `returncode == 0`, so a
    # test about a load-bearing refusal failed for a reason that had nothing
    # to do with the refusal. The closure is walked from the entry points.
    for f in _local_import_closure("pad_ring_gen.py", "pad_ring_check.py"):
        shutil.copy2(PROGRAMS / f, dst / f)
    text = (dst / filename).read_text()
    assert old in text, f"mutation site not found in {filename}"
    (dst / filename).write_text(text.replace(old, new, 1))
    return dst


def _run(mut: Path, root: Path):
    return subprocess.run(
        [sys.executable, str(mut / "pad_ring_check.py"), str(root),
         "--json", str(root / PR.REPORT_REL), *_pdk_args(root)],
        capture_output=True, text=True)








# --------------------------------------------------------------------------- #
# WHERE A PAD SITE IS DECLARED — the second PDK view
#
# MEASURED 2026-08-22 in the pinned image, on the open PDK whose IO library was
# read exhaustively: all 15 of its IO cell LEFs carry the `SITE <name> ;`
# REFERENCE form inside a MACRO and NOT ONE top-level SITE declaration. The
# distribution declares those sites in its tech view instead —
#
#     libs.tech/<flow>/<io library>/config.tcl
#         # Note: This is needed if site definition are not in LEF
#         dict set ::env(PAD_FAKE_SITES) "<site>" "<width_um>, <height_um>"
#
# — which is upstream's own PDK-scoped variable, consumed by upstream's placer
# before its two site lookups. Reading only the LEF view refused a real PDK
# with PAD_SITE_NOT_FOUND, which is our own tool blocking a verdict the chip
# had earned. Every fixture below is the SAME synthetic library as above with
# its two SITE declarations moved from the LEF to the tech view, so what the
# tests vary is the view and nothing else.
# --------------------------------------------------------------------------- #
def _io_lef_sites_not_in_lef(site_w: float = 1.0) -> str:
    """The same IO library, with its SITE records where this PDK puts them:
    not in the LEF. The `SITE <name> ;` lines are the REFERENCE form every
    such distribution's macros carry, and they declare nothing."""
    body = _io_lef(site_w)
    keep = []
    drop = False
    for ln in body.splitlines():
        if ln.startswith("SITE "):
            drop = True
        if not drop:
            keep.append(ln)
        if drop and ln.startswith("END ") and ln.split()[1].endswith("site"):
            drop = False
    text = "\n".join(keep) + "\n"
    assert "CLASS PAD ;\n    SYMMETRY" not in text
    # the reference form, inside each macro, exactly as the distribution ships
    text = text.replace("MACRO pad_bidir\n  CLASS PAD ;",
                        "MACRO pad_bidir\n  CLASS PAD ;\n  SITE io_site ;")
    text = text.replace("MACRO pad_corner\n  CLASS PAD ;",
                        "MACRO pad_corner\n  CLASS PAD ;\n"
                        "  SITE io_corner_site ;")
    return text


def _site_declaration(*entries: tuple, scalars: bool = True) -> str:
    """A PDK tech-view config in the form the distributions write it.

    `scalars` suppresses the two `set ::env(PAD_SITE_*_NAME)` lines while
    keeping the `PAD_FAKE_SITES` dict. That is a shape a distribution really
    can ship — upstream declares the dict and the two names as three separate
    variables — and it is what a test about the SITE LOOKUP needs, because a
    config that also declares the names makes the run refuse earlier, on the
    adoption layer, for a different and equally correct reason. Both refusals
    are pinned; suppressing the scalars is how they are pinned SEPARATELY.
    """
    lines = ["set current_folder [file dirname [file normalize [info script]]]"]
    if scalars:
        lines += ['set ::env(PAD_SITE_NAME) "io_site"',
                  'set ::env(PAD_CORNER_SITE_NAME) "io_corner_site"']
    lines += ["# Create fake pad sites",
              "# Note: This is needed if site definition are not in LEF",
              "set ::env(PAD_FAKE_SITES) [dict create]"]
    lines += [f'dict set ::env(PAD_FAKE_SITES) "{n}" "{w}, {h}"'
              for n, w, h in entries]
    return "\n".join(lines) + "\n"


def _project_sites_in_tech_view(tmp_path: Path, *, site_w: float = 1.0,
                                declare: bool = True,
                                second_lib: tuple = None,
                                scalars: bool = True,
                                config=...) -> Path:
    root = _project(tmp_path, config=config, site_w=site_w)
    (root / "pdk/proc/libs.ref/proc_io/lef/io.lef").write_text(
        _io_lef_sites_not_in_lef(site_w))
    if declare:
        d = root / "pdk/proc/libs.tech/someflow/proc_io"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.tcl").write_text(_site_declaration(
            ("io_site", f"{site_w:.2f}", "350"),
            ("io_corner_site", "350", "350"), scalars=scalars))
    if second_lib is not None:
        d = root / "pdk/proc/libs.tech/someflow/proc_other_io"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.tcl").write_text(_site_declaration(*second_lib))
    return root


def test_a_pdk_that_declares_its_sites_in_the_tech_view_is_not_refused(
        tmp_path):
    """THE DEFECT. The IO LEFs carry no SITE declaration — which is what a
    real distribution ships — and the PDK declares both sites in its tech
    view. Before this was read, step 15.5ic answered PAD_SITE_NOT_FOUND about
    a PDK that had declared the site, and the run could not reach a verdict
    for a reason the flow itself owned."""
    root = _project_sites_in_tech_view(tmp_path)
    # the premise: the LEF view really is empty of SITE declarations
    lefs = PR.discover_io_lefs(str(root / "pdk"), "proc")
    assert PR.IoLibrary(lefs).sites == {}






def test_a_site_declared_by_neither_pdk_view_is_still_refused(tmp_path):
    """The refusal has to stay reachable. Reading a second view widens WHERE
    a site may be declared; it does not let a name nobody declared through.

    `scalars=False` so this PDK declares its two SITES and does not declare
    `PAD_SITE_NAME`. That is what isolates the lookup: with the scalar
    present the run refuses one layer earlier, on the contradiction, which is
    correct and is pinned by
    `test_a_project_that_contradicts_the_pdk_is_refused_by_name` — a refusal
    that would otherwise stand in for this one and let it rot unnoticed."""
    root = _project_sites_in_tech_view(
        tmp_path, scalars=False,
        config=_config(PAD_SITE_NAME="no_such_site"))
    assert not PR.PdkDeclarations(
        PR.discover_io_library_configs(str(root / "pdk"), "proc")).values, \
        "the premise: this PDK declares no scalar, so nothing is adopted"
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_a_pdk_that_declares_no_site_anywhere_is_still_refused(tmp_path):
    """The LEF view is empty and there is no tech view either. Nothing was
    invented to fill the hole."""
    root = _project_sites_in_tech_view(tmp_path, declare=False)
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_a_site_declared_at_two_sizes_is_refused_not_ordered(tmp_path):
    """A tree may ship more than one IO library. Upstream reads one config and
    never sees a second; this step discovers them, so it can. The site width
    is what every gap in the ring is rounded to, and picking it out of a
    directory listing would put the ring's abutment on file order."""
    root = _project_sites_in_tech_view(
        tmp_path, second_lib=(("io_site", "2.00", "350"),
                              ("io_corner_site", "350", "350")))
    assert "PAD_SITE_DECLARATION_AMBIGUOUS" in _rules(root)
    assert "io_site" in _report(root)["reason"]




def test_only_the_pdk_may_declare_a_site_never_the_project(tmp_path):
    """The config contract carries no site GEOMETRY and this fix does not add
    any. A project that writes PAD_FAKE_SITES into its own pad_assignment.json
    gets nothing from it — the site is still looked up in the PDK."""
    root = _project_sites_in_tech_view(
        tmp_path, declare=False,
        config=dict(_config(PAD_SITE_NAME="project_invented_site"),
                    PAD_FAKE_SITES={"project_invented_site": [1.0, 350.0]}))
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_the_gate_reads_the_same_two_views_as_the_producer(tmp_path):
    """An auditor that consulted only the LEF would call a correctly placed
    ring PAD_SITE_NOT_FOUND — a gate contradicting its own producer over which
    file it opened."""
    root = _project_sites_in_tech_view(tmp_path)
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_the_declaration_parser_reads_upstreams_form_verbatim():
    """The one form the distributions write, and nothing else. A file that
    declares no site contributes none."""
    got = PR.parse_pad_site_declarations(_site_declaration(
        ("a_site", "0.1", "355"), ("a_corner_site", "355", "355")))
    assert got == {"a_site": (0.1, 355.0), "a_corner_site": (355.0, 355.0)}
    assert PR.parse_pad_site_declarations("set ::env(PAD_SITE_NAME) \"x\"\n") \
        == {}
    assert PR.parse_pad_site_declarations("") == {}


# --------------------------------------------------------------------------- #
# THE ALONG-THE-ROW EXTENT, AND THE ROTATION THAT IS NOT READ
#
# Upstream measures a cell in exactly two places and both are the master's
# WIDTH, on all four sides. The tool agrees: a vertical-side pad is placed
# 75-along / 350-into for EVERY value of PAD_ROTATION_VERTICAL, measured in
# four separate OpenROAD processes. Taking the ORIENTED extent instead summed
# the master's HEIGHT on a vertical side and refused a ring upstream places.
#
# The fixture's pad is 75 x 350, so a side that sums heights is 4.67x a side
# that sums widths — the same shape as the real 19 x 350-vs-1500 error.
# --------------------------------------------------------------------------- #




def test_a_declared_non_default_vertical_rotation_is_not_determined(tmp_path):
    """DEGRADE LOUDLY. THIS DOCSTRING SAID "the placer does not read this
    variable" AND "the knob does nothing", AND BOTH WERE WRONG — the placer
    reads it and moves the S/N rows with it; it is THIS STEP that does not
    implement it. Honouring it silently is a lie and ignoring it silently is
    the defect. An author who sets a knob is entitled to be told it was not
    honoured here — and being told is rc 2, not rc 0 and not rc 1: it is `I
    cannot honour what you asked`, which is neither a pass nor a finding about
    the design."""
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL="R90"))
    assert "PAD_ROTATION_VERTICAL_NOT_HONOURED" in _rules(root)
    # no ring was placed and none was claimed
    assert not _ring_def(root).is_file()
    assert (root / PR.PADRING_SKIPPED_REL).is_file()


@pytest.mark.parametrize("value", ["R90", "R180", "R270", "MX", "MXR90"])
def test_every_non_default_vertical_rotation_is_refused(tmp_path, value):
    """Not just the one the fixture used to carry."""
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL=value))
    assert "PAD_ROTATION_VERTICAL_NOT_HONOURED" in _rules(root)








def test_the_gate_catches_a_def_that_contradicts_its_own_geometry(tmp_path):
    """WHY PART 3 OF THE RULE IS LOAD-BEARING, proved rather than argued.

    The gate re-derives every pad's footprint from the master and the DEF
    ORIENTATION and compares it with the extents the report claims. So had the
    extent been corrected without also correcting the emitted orientation —
    the option that would have left the declared rotation in the DEF beside a
    footprint contradicting it — this gate would have refused the result.

    Written as a test so that stays true: put the DECLARED orientation back on
    a vertical pad and watch the artefact stop corroborating itself.
    """
    root = _project(tmp_path)
    declared = PR.normalise_orient(_config()["PAD_ROTATION_VERTICAL"])
    assert declared != PR.SIDE_ORIENT["W"], (
        "premise: the declared rotation and the placer's are different")
    assert "PAD_FOOTPRINT_DISAGREES_WITH_LIBRARY" in _rules(root)


def test_the_lef_wins_when_both_views_declare_the_same_site(tmp_path):
    """PRECEDENCE, and it was UNPROTECTED until this test.

    `resolve_site` prefers the LEF over the tech-view declaration, on the stated
    grounds that the LEF record carries real geometry while a declaration is a
    size somebody wrote down. NO PDK IN THE IMAGE SHIPS BOTH — measured, BOTH=0
    on all four trees carrying an IO library — so the branch has no real-PDK
    coverage, and no fixture exercised it either: MEASURED, inverting the
    precedence left `96 passed, 4 skipped` untouched.

    So this fixture declares the SAME site name in BOTH views at DIFFERENT
    sizes, and pins which one the ring is built from.
    """
    root = _project(tmp_path)                       # LEF declares io_site 1.0 x 350
    d = root / "pdk/proc/libs.tech/someflow/proc_io"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.tcl").write_text(_site_declaration(
        ("io_site", "9.00", "350"),                 # a DIFFERENT width
        ("io_corner_site", "350", "350")))
    lefs = PR.discover_io_lefs(str(root / "pdk"), "proc")
    decls = PR.discover_io_site_declarations(str(root / "pdk"), "proc")
    lib = PR.IoLibrary(lefs, decls)
    assert "io_site" in lib.sites and "io_site" in lib.declared_sites, \
        "premise: both views must declare it, or this proves nothing"

    got = lib.resolve_site("io_site")
    assert got["source"] == PR.SITE_SOURCE_LEF, got
    assert got["size"] == (1.0, 350.0), got          # the LEF's, not the 9.0

    # and the RING is built from the LEF width: with site_w 1.0 the gaps come
    # out on the 0.1-um grid the fixture's arithmetic expects. A 9.0-um site
    # would round the spacing differently.


# --------------------------------------------------------------------------- #
# REAL PDKs, not fixtures.
#
# Every test above this line is a fixture authored alongside the change, and a
# suite made only of those cannot distinguish the change from its own absence
# (`real_artefact_test_backing_check`). The artefact that actually backs this
# change is not in the repo — no checked-in file declares a pad site — it is
# the INSTALLED PDK. So the guard is repeated here against whatever PDKs the
# host really has, and skipped, honestly, where there are none.
#
# It names no PDK, no foundry and no library: it iterates the trees that are
# installed and asks one question of each.
# --------------------------------------------------------------------------- #
_REAL_PDK_ROOTS = [
    Path("/foss/pdks"), Path("/usr/share/pdk"), Path("/opt/pdk"),
    Path.home() / ".volare" / "volare",
]


def _real_pdk_trees():
    """(root, tree) for every installed PDK tree, from the host's own roots."""
    roots = list(_REAL_PDK_ROOTS)
    env = os.environ.get("VIBEIC_PDK_ROOT")
    if env:
        roots = [Path(p) for p in env.split(os.pathsep) if p] + roots
    out = []
    for root in roots:
        if root.is_dir():
            out += [(str(root), d.name)
                    for d in sorted(root.iterdir()) if d.is_dir()]
    return out


def _trees_with_an_io_library():
    return [(r, t) for r, t in _real_pdk_trees()
            if PR.discover_io_lefs(r, t)]


def _library_for(root, tree):
    """The IO library for a real tree, built through whatever site views this
    revision of `_pad_ring` knows about.

    `getattr`, deliberately. These tests are the REAL-ARTEFACT control for this
    change, and a control that dies with `AttributeError` on the pre-fix tree
    has observed nothing — it fails on the ABSENCE of the function the fix
    adds, which is true of every new function ever written and grades as
    presence-only under `control_substance_check`. Resolving the API softly
    lets the pre-fix tree RUN the question and answer it wrongly, with a
    measured value, which is the only kind of red that proves anything.
    """
    lefs = PR.discover_io_lefs(root, tree)
    find_decls = getattr(PR, "discover_io_site_declarations", None)
    if find_decls is None:
        return PR.IoLibrary(lefs)
    return PR.IoLibrary(lefs, find_decls(root, tree))


def _pad_class_sites(lib):
    """Every PAD-class site the library resolves, on either revision."""
    names = getattr(lib, "pad_class_site_names", None)
    if names is not None:
        return names()
    return sorted(n for n, s in lib.sites.items() if s["class"] == "PAD")


@pytest.mark.skipif(not _trees_with_an_io_library(),
                    reason="no installed PDK here ships an IO cell library")
def test_no_real_pdk_that_ships_an_io_library_is_called_siteless():
    """A PDK that ships IO cells declares the sites they sit on. If this step
    cannot find them it is looking in the wrong place, and the refusal it
    raises is about US.

    MEASURED on the pinned image: of the trees carrying an IO cell library,
    half declare their sites as LEF SITE records and half declare them in the
    tech view. Reading one view called the other half siteless.
    """
    siteless = []
    for root, tree in _trees_with_an_io_library():
        lib = _library_for(root, tree)
        if not _pad_class_sites(lib):
            siteless.append(
                f"{tree}: {len(lib.lefs)} IO LEF(s), "
                f"{len(lib.sites)} LEF SITE record(s), "
                f"{len(getattr(lib, 'declared_sites', {}))} tech-view "
                f"declaration(s)")
    assert not siteless, (
        "a real PDK ships an IO cell library and this step resolved no "
        f"PAD-class site for it: {siteless}")


@pytest.mark.skipif(not _trees_with_an_io_library(),
                    reason="no installed PDK here ships an IO cell library")
def test_every_real_pdk_site_resolves_with_a_class_and_a_size():
    """Whichever view a site comes from, it has to arrive usable: CLASS PAD
    and a SIZE, because the spacing arithmetic rounds to that width."""
    for root, tree in _trees_with_an_io_library():
        lib = _library_for(root, tree)
        for name in _pad_class_sites(lib):
            got = lib.resolve_site(name)
            assert got is not None, f"{tree}: {name} listed but unresolvable"
            assert got["class"] == "PAD", f"{tree}: {name} -> {got}"
            assert got["size"] and got["size"][0] > 0, f"{tree}: {name} -> {got}"


@pytest.mark.skipif(not _real_pdk_trees(),
                    reason="no installed PDK on this host")
def test_no_real_pdk_declares_one_site_at_two_sizes():
    """The corpus-sweep property, as a test. A tree may ship more than one IO
    library — every one measured declares the same site identically, and
    agreement must not be reported as a conflict, or the new refusal is a
    false positive on real PDKs."""
    for root, tree in _real_pdk_trees():
        lib = _library_for(root, tree)
        # NOT a control — pre-fix there are no declarations to conflict, so
        # this passes trivially there. It is the criterion-2 false-positive
        # guard: the one refusal this change ADDS must never fire on a real
        # PDK, and every tree measured declares its sites identically across
        # its IO libraries.
        assert not getattr(lib, "site_declaration_conflicts", {}), (
            f"{tree}: {lib.site_declaration_conflicts}")


def test_the_module_header_can_still_do_its_own_arithmetic():
    """The header states how many of upstream's PAD_* variables this module
    names and how many it omits. Those two must add up to the total it also
    states, and the whole reason this test exists is that a WRONG SENTENCE IN
    THIS HEADER is what kept PAD_SITE_NOT_FOUND firing against a PDK that had
    declared the site: the header asserted upstream's placer would exit 1 on
    its first lookup, which it would not, and nothing re-checked the claim.

    A prose count is not self-checking. This makes it so, with no dependency
    on upstream being installed -- the arithmetic has to close on its own."""
    doc = Path(PR.__file__).read_text(encoding="utf-8")
    m = re.search(r"names (\d+) of upstream's (\d+) PDK-scoped", doc)
    assert m, "the header no longer states how many PAD_* variables it names"
    named, total = int(m.group(1)), int(m.group(2))
    m2 = re.search(r"The other (\d+) it omits", doc)
    assert m2, "the header no longer states how many it omits"
    omitted = int(m2.group(1))
    assert named + omitted == total, (
        f"the header's own numbers do not close: it says it names {named} "
        f"and omits {omitted}, which is {named + omitted}, not {total}")


@pytest.mark.consistency
def test_the_header_count_matches_what_the_module_actually_names():
    """The arithmetic closing is necessary and not sufficient -- two wrong
    numbers can still sum correctly. This one counts the PAD_* variables the
    three modules actually mention and compares it to the header's claim.

    Driven by upstream's OWN variable list when librelane is importable, so
    the denominator is upstream's rather than a list retyped here; skipped
    honestly where it is not."""
    flow = pytest.importorskip(
        "librelane.config.flow",
        reason="librelane not importable on this host")
    upstream = {v.name for v in flow.pad_variables}
    doc = Path(PR.__file__).read_text(encoding="utf-8")
    m = re.search(r"names (\d+) of upstream's (\d+) PDK-scoped", doc)
    assert m
    named_claim, total_claim = int(m.group(1)), int(m.group(2))
    assert total_claim == len(upstream), (
        f"header says upstream has {total_claim} PAD_* variables; "
        f"upstream's own pad_variables has {len(upstream)}")
    here = PROGRAMS






# ANSWERING `real_artefact_test_backing_check`, WHICH REPORTS 0 OF 91 HERE.
# That number is correct and the doctrine asks for a mutation run or a reason;
# both are given.
#
# THE REASON: this module's strongest tests are driven by neither a fixture nor
# a checked-in artefact. They query the INSTALLED PDK and, below, the ACTUAL
# OPENROAD BINARY. The check has no category for that, and its worry does not
# apply to it -- "a suite that cannot distinguish the change from its own
# absence" is about fixtures authored alongside the code, which cannot disagree
# with it. A tool CAN disagree, and did: it is how three shipped orientations
# were found to be wrong.
#
# THE MUTATION RUN, which is what the doctrine says actually proves the point:
#   SIDE_ORIENT["N"]  -> its shipped-wrong value  => this test RED, naming FS vs S
#   CORNER_ORIENT SE  -> its shipped-wrong value  => this test RED, naming FN vs E
# Both are the ORIGINAL defects, reproduced and caught.
#
# ── the orientations, MEASURED against the placer rather than pinned ─────────
#
# THREE DEFECTS CAME FROM PINNING THEM BY HAND. `SIDE_ORIENT` and
# `CORNER_ORIENT` now hold the placer's own values, but a CONSTANT CAN DRIFT
# FROM THE TOOL EXACTLY AS THE OLD COMPUTATION DID -- the previous values were
# also written down deliberately, and were also wrong. This asks OpenROAD.
#
# It skips where the tool or the PDK is absent, which is every host run here;
# it bites in the container, which is where the suite is measured.

_ORIENT_PROBE = """
read_lef {tlef}
foreach f [glob {iolefs}] {{ read_lef $f }}
make_fake_io_site -name S_IO  -width 0.1 -height 355
make_fake_io_site -name S_COR -width 355 -height 355
read_def {defp}
make_io_sites -horizontal_site S_IO -vertical_site S_IO -corner_site S_COR \\
  -offset 26 -rotation_horizontal R0 -rotation_vertical R0 -rotation_corner R0
place_corners {corner}
place_pad -row IO_SOUTH -location 500 ps -master {pad}
place_pad -row IO_NORTH -location 500 pn -master {pad}
place_pad -row IO_WEST  -location 500 pw -master {pad}
place_pad -row IO_EAST  -location 500 pe -master {pad}
set b [ord::get_db_block]
foreach n {{ps pn pw pe}} {{ puts "ORIENT $n [[$b findInst $n] getOrient]" }}
foreach i [$b getInsts] {{
  if {{[string match "*{corner}*" [[$i getMaster] getName]]}} {{
    set bb [$i getBBox]
    puts "CORNER [$i getName] [$i getOrient] [$bb xMin] [$bb yMin]"
  }}
}}
exit 0
"""


@pytest.mark.skipif(shutil.which("openroad") is None,
                    reason="openroad not on PATH on this host")
@pytest.mark.skipif(not _trees_with_an_io_library(),
                    reason="no installed PDK ships an IO cell library")
def test_the_placer_agrees_with_the_orientation_constants(tmp_path):
    """ASK THE TOOL, do not pin it. Three shipped defects were orientations
    written down by hand -- NORTH rotated where the placer mirrors, and two of
    four corners likewise. The constants now hold the right values; this is
    what keeps them right.

    Fails loudly if a future OpenROAD changes the convention, which is the
    outcome worth having: a constant that silently disagrees with the tool is
    the defect this test exists to prevent, in its next incarnation."""
    root, tree = _trees_with_an_io_library()[0]
    lib = _library_for(root, tree)
    pad = next((m for m, (w, h) in sorted(lib.masters.items())
                if w < h and w > 1.0), None)
    corner = next((m for m, (w, h) in sorted(lib.masters.items())
                   if w == h and w > 100.0), None)
    if not (pad and corner):
        pytest.skip(f"{tree}: no distinguishable pad/corner master")
    tlefs = sorted(Path(root, tree).glob("libs.ref/*/techlef/*.tlef"))
    iolefs = sorted(Path(f).parent for f in lib.lefs)
    if not tlefs or not iolefs:
        pytest.skip(f"{tree}: no tech LEF or IO LEF directory")

    die = 4000000
    defp = tmp_path / "probe.def"
    defp.write_text(
        'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
        "DESIGN probe ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        f"DIEAREA ( 0 0 ) ( {die} {die} ) ;\nCOMPONENTS 4 ;\n"
        + "".join(f"- {n} {pad} ;\n" for n in ("ps", "pn", "pw", "pe"))
        + "END COMPONENTS\nEND DESIGN\n")
    tcl = tmp_path / "probe.tcl"
    tcl.write_text(_ORIENT_PROBE.format(
        tlef=tlefs[0], iolefs=f"{iolefs[0]}/*.lef", defp=defp,
        corner=corner, pad=pad))

    r = _pr.run(["openroad", "-no_init", "-exit", str(tcl)],
                       capture_output=True, text=True)
    got = {}
    for ln in r.stdout.splitlines():
        f = ln.split()
        if f[:1] == ["ORIENT"]:
            got[{"ps": "S", "pn": "N", "pw": "W", "pe": "E"}[f[1]]] = f[2]
    if len(got) != 4:
        pytest.skip(f"probe did not place four pads: {r.stdout[-400:]}")

    # the tool's names, in DEF spelling, are what the constants must hold
    measured = {s: PR.ORIENT_ALIASES[o] for s, o in got.items()}
    assert measured == PR.SIDE_ORIENT, (
        f"{tree}: the placer produces {measured}; SIDE_ORIENT holds "
        f"{PR.SIDE_ORIENT}. A constant has drifted from the tool -- which is "
        f"exactly how NORTH came to carry a rotation where the placer mirrors")

    # AND THE CORNERS, which were the larger defect: two of four carried a
    # rotation where the placer mirrors. Positions identify which corner is
    # which -- the instance names are the tool's, not ours.
    seen = {}
    for ln in r.stdout.splitlines():
        f = ln.split()
        if f[:1] != ["CORNER"]:
            continue
        x, y = int(f[3]), int(f[4])
        pos = ("S" if y < die // 2 else "N") + ("W" if x < die // 2 else "E")
        seen[pos[::-1] if pos in ("WS", "WN", "ES", "EN") else pos] = \
            PR.ORIENT_ALIASES[f[2]]
    if len(seen) == 4:
        assert seen == PR.CORNER_ORIENT, (
            f"{tree}: the placer produces {seen}; CORNER_ORIENT holds "
            f"{PR.CORNER_ORIENT}. The placer ALTERNATES rotation and mirror "
            f"(R0, MY, R180, MX); a pure rotate_cw walk gives E and W where it "
            f"writes FN and FS, which is the defect this pins")



#: The sentences `main` shipped as live claims about the placer, VERBATIM, for
#: scanning SOURCE. Every one is false: `-rotation_vertical` moves the S/N rows,
#: so the placer reads the variable. The retraction that replaced them is worded
#: so that it does not contain them, which is why a verbatim scan works here.
RETRACTED_CLAIMS = (
    "`PAD_ROTATION_VERTICAL` IS INERT",
    "The same measurement shows the placer does not read it.",
    "placer ignores it",
    "the knob does nothing",
)

#: The same falsehoods as the shortest fragment that still identifies one, for
#: scanning EMITTED text — the report and the console.
#:
#: THIS LIST EXISTS BECAUSE THE TWO GUARDS DISAGREED. The record guard listed
#: three phrases and did not list `placer ignores it`, so that one sentence
#: survived in the console line the whole time the commit next to it was
#: removing `is inert` from the record. One vocabulary, checked in both places,
#: is the fix — a second list is a second thing to forget to update.
RETRACTED_PHRASES = (
    "is inert",
    "does not read it",
    "the knob does nothing",
    "placer ignores it",
)





def _assert_no_retracted_claim(text: str, where: str) -> None:
    """No retracted falsehood in EMITTED text, verbatim or reworded."""
    low = text.lower()
    for lie in RETRACTED_PHRASES:
        assert lie not in low, (
            f"{where} carries the retracted claim {lie!r}: the placer DOES "
            f"read PAD_ROTATION_VERTICAL — it moves the S/N rows. This step "
            f"is what does not implement it.")







@pytest.mark.parametrize("var", ["PAD_ROTATION_HORIZONTAL",
                                 "PAD_ROTATION_VERTICAL",
                                 "PAD_ROTATION_CORNER"])


def test_the_refusal_names_the_variable_actually_declared(tmp_path, var,
                                                          capsys):
    """THE REFUSAL BROADENED TO THREE VARIABLES AND ITS REPORT DID NOT.

    All three are named for the ROW AXIS and this step implements none of
    them, so a declared non-default on any one is refused. But the rule id,
    the `variables_absent` entry and the console line were still the literal
    `PAD_ROTATION_VERTICAL`, so a run refused for declaring
    PAD_ROTATION_HORIZONTAL was told to go look at a variable it had left
    alone. A refusal that names the wrong input is a refusal a reader cannot
    act on.

    The console line is checked too, because it is the half a human reads and
    it is where `placer ignores it` — the retracted claim — survived the
    correction that removed it from the record."""
    root = _project(tmp_path, config=_config(**{var: "R90"}))
    assert f"{var}_NOT_HONOURED" in _rules(root)
    printed = capsys.readouterr().out
    assert f"{var}_NOT_HONOURED" in printed
    # BOTH halves, through the one shared vocabulary. An earlier draft of this
    # test left the `reason` assertion OUTSIDE the loop, so it re-used the
    # leaked loop variable and checked exactly one of the four claims against
    # exactly one of the two texts. Planting `placer ignores it` in the emitted
    # reason passed it 3/3.
    _assert_no_retracted_claim(printed, "the console line")




# --------------------------------------------------------------------------- #
# a refuted finding must lose its identifier
# --------------------------------------------------------------------------- #






def test_no_identifier_in_the_pad_ring_producer_asserts_inertness():
    """The general rule, not the one variable: a proposition the project has
    recorded as FALSE may not survive in an IDENTIFIER — a name, a schema key,
    a function. Every consumer keys on the identifier and none of them reads
    the retraction published elsewhere.

    PROSE IS DELIBERATELY NOT POLICED, and the first version of this test got
    that wrong. It scanned every string literal and excluded the specific
    sentences I had written, which made it pass on my edit and FAIL on an
    independent fix of the same defect (`origin/jpadsite/pad-site`) whose
    docstring retracts the claim by QUOTING it — 'THIS SECTION SAID "IS INERT"
    … AND BOTH WERE WRONG'. A retraction has to be able to name what it
    retracts. A guard whose pass condition is "contains the phrases the author
    happened to use" is fitted to one edit, not to the rule; measured
    three ways, this version FAILS on main, and PASSES on both independent
    fixes."""
    import ast
    offenders = []
    assert not offenders, (
        f"identifiers still assert a proposition measured false: {offenders}")




@pytest.mark.parametrize("kind,was,now", [("pad", "FS", "S"),
                                          ("corner", "FN", "E")])
def test_the_gate_refuses_a_mirror_written_where_the_report_says_a_rotation(
        tmp_path, kind, was, now):
    """THE CORRECTION WAS UNENFORCED IN THE ARTEFACT IT IS ABOUT.

    Three commits on this branch moved NORTH and two corners from a ROTATION to
    the MIRROR the placer produces. Nothing then stopped `padring.def` from
    carrying the rotation again: every check in `pad_ring_check` re-derives the
    FOOTPRINT from the DEF orientation, and a mirror and a rotation share a
    bounding box. MEASURED on the gate before this rule existed — north pad
    FS -> S, and corner FN -> E — each left it rc 0 with ZERO findings.

    Which is the exact failure mode part 3 of the flow owner's ruling names:
    the fit arithmetic cannot see it and a DEF reader deriving pin positions
    can. This test asserts the blindness is gone AND asserts the premise that
    made it blind, so the rule cannot be quietly replaced by an extent check.
    """
    root = _project(tmp_path)
    # the good path passes, so the refusal below is the rule firing and not
    # the fixture being broken

    # PREMISE: the swap is invisible to every extent-based check in the gate.
    size = (75.0, 350.0) if kind == "pad" else (355.0, 355.0)
    assert PR.footprint(size, was, UNITS) == PR.footprint(size, now, UNITS), (
        f"premise: {was} and {now} must share a bounding box, or this test "
        f"would be proving the footprint check rather than the orientation one")

    assert "PAD_ORIENT_DISAGREES_WITH_DEF" in _rules(root)
    assert "a mirror is not a rotation" in " ".join(
        f["message"] for f in _report(root)["findings"])


def test_the_doctrine_this_probe_broke_is_cited_by_a_name_that_exists():
    """A CITATION THAT ROTS IS WORSE THAN NONE — it sends the next author to a
    file that is not there, and prose cannot notice.

    The docstring points at the program stating the rule the original probe
    broke: an axis holding one value across differing arms is not evidence the
    lever does nothing, it is evidence the axis was not measured under it. Cited
    by PROGRAM NAME rather than by file:line, because a line-anchored citation
    rots on any edit above it; this one rots only on a rename, which is exactly
    what this test catches."""
    cited = "metric_constant_across_differing_arms_is_not_measured"
    assert (PROGRAMS / f"{cited}.py").is_file(), (
        f"pad_ring_gen cites {cited!r} and no such program exists — the "
        f"citation was not updated when the program moved or was renamed")

    # `_pad_ring` points the next author at the test that re-derives the eight
    # orientations from the placer. That pointer is the difference between a
    # constant somebody must trust and one anybody can re-check, so it is not
    # allowed to name a test that has been renamed away.
    named = "test_the_shipped_orientations_are_what_the_placer_produces"
    assert named in Path(PR.__file__).read_text(), (
        "_pad_ring no longer points at the test that re-derives SIDE_ORIENT "
        "and CORNER_ORIENT from the tool")
    assert named in globals(), (
        f"_pad_ring points at {named!r} and this module defines no such test "
        f"— the pointer rotted when the test was renamed")


# --------------------------------------------------------------------------- #
# the eight orientations, asked of the PLACER rather than of ourselves
# --------------------------------------------------------------------------- #
# EVERY OTHER TEST IN THIS FILE PINS THE CONSTANTS AGAINST THEMSELVES. They
# assert that the report carries `SIDE_ORIENT` and that `SIDE_ORIENT` is a
# particular dict, so an author who changed both together would pass all of
# them. The only thing tying the eight values to reality was a docstring
# saying MEASURED — which is precisely the shape of the claim this branch
# exists to retract, one nobody could falsify without redoing the work.
#
# So this asks the tool. It names no kit: the IO library, its pad master, its
# corner and its site width are all discovered by reading LEF, so it runs
# against whatever is installed and stays inside the chip-AGNOSTIC rule the
# tests above enforce on this very file.
_HAVE_OPENROAD = shutil.which("openroad") is not None
_PDK_ROOT = os.environ.get("PDK_ROOT") or ""

_LEF_MACRO = re.compile(r"^\s*MACRO\s+(\S+)", re.M)
_LEF_CLASS = re.compile(r"^\s*CLASS\s+([A-Z]+)(?:\s+([A-Z]+))?", re.M)
_LEF_SITE = re.compile(r"^\s*SITE\s+(\S+)\s*;", re.M)
_LEF_SIZE = re.compile(r"^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", re.M)


def _lef_cells(text: str):
    """(name, class, subclass, site, w, h) for each MACRO in one LEF."""
    out = []
    for chunk in text.split("MACRO ")[1:]:
        blk = "MACRO " + chunk
        m, c, z = _LEF_MACRO.search(blk), _LEF_CLASS.search(blk), _LEF_SIZE.search(blk)
        if not (m and c and z):
            continue
        s = _LEF_SITE.search(blk)
        out.append((m.group(1), c.group(1), c.group(2) or "",
                    s.group(1) if s else "", float(z.group(1)), float(z.group(2))))
    return out


def _find_io_library(pdk_root: str):
    """The first installed kit carrying a PAD-class cell and a corner."""
    for kit in sorted(Path(pdk_root).iterdir()):
        tlefs = sorted(kit.glob("libs.ref/*/techlef/*.tlef"))
        if not tlefs:
            continue
        for libdir in sorted(kit.glob("libs.ref/*/lef")):
            cells = [c for lef in sorted(libdir.glob("*.lef"))
                     for c in _lef_cells(lef.read_text(errors="replace"))]
            pads = [c for c in cells if c[1] == "PAD" and c[2] != "SPACER" and c[3]]
            spacers = [c for c in cells if c[1] == "PAD" and c[2] == "SPACER" and c[3]]
            corners = [c for c in cells if c[1] == "ENDCAP"]
            if not (pads and corners):
                continue
            pad = max(pads, key=lambda c: c[5])
            cor = max(corners, key=lambda c: c[4])
            return {"tech_lef": str(tlefs[0]), "lef_dir": str(libdir),
                    "pad_master": pad[0], "pad_site": pad[3],
                    "pad_w": pad[4], "pad_h": pad[5],
                    "corner_master": cor[0],
                    "corner_site": cor[3] or (pad[3] + "_CORNER"),
                    "corner_w": cor[4], "corner_h": cor[5],
                    "site_w": min([s[4] for s in spacers] or [pad[4]])}
    return None


_PLACER_TCL = """\
read_lef {tech_lef}
make_fake_io_site -name {pad_site} -width {site_w} -height {pad_h}
make_fake_io_site -name {corner_site} -width {corner_w} -height {corner_h}
foreach lef [glob {lef_dir}/*.lef] {{ read_lef $lef }}
read_def {def_path}
make_io_sites -horizontal_site {pad_site} -vertical_site {pad_site} \\
    -corner_site {corner_site} -offset {offset} \\
    -rotation_horizontal {rot} -rotation_vertical {rot} -rotation_corner {rot}
place_pad -row IO_SOUTH -location {loc} -master {pad_master} ps
place_pad -row IO_NORTH -location {loc} -master {pad_master} pn
place_pad -row IO_WEST  -location {loc} -master {pad_master} pw
place_pad -row IO_EAST  -location {loc} -master {pad_master} pe
place_corners {corner_master}
set blk [ord::get_db_block]
foreach i [$blk getInsts] {{
    set b [$i getBBox]
    puts "ORIENT [$i getName] [$i getOrient] \\
[expr ([$b xMin]+[$b xMax])/2] [expr ([$b yMin]+[$b yMax])/2]"
}}
set d [$blk getDieArea]
puts "DIE [$d xMin] [$d yMin] [$d xMax] [$d yMax]"
"""

_PLACER_DEF = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN probe ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( {d} {d} ) ;
COMPONENTS 0 ;
END COMPONENTS
END DESIGN
"""


def _measure_placer_orientations(lib, work: Path, rot: str):
    """Run upstream's own call shape and read the orientations back from odb."""
    side = max(int((lib["corner_w"] * 2 + lib["pad_w"] * 4 + 200) * 1000),
               2_000_000)
    dp = work / "probe.def"
    dp.write_text(_PLACER_DEF.format(d=side))
    tp = work / "probe.tcl"
    tp.write_text(_PLACER_TCL.format(
        def_path=dp, offset=int(lib["corner_w"] / 10) or 1,
        loc=int(side / 2000 / 2), rot=rot, **lib))
    run = _pr.run(["openroad", "-no_init", "-exit", str(tp)],
                         capture_output=True, text=True)
    got, die = {}, None
    for ln in run.stdout.splitlines():
        f = ln.split()
        if ln.startswith("ORIENT ") and len(f) >= 5:
            got[f[1]] = (f[2], int(f[3]), int(f[4]))
        elif ln.startswith("DIE ") and len(f) >= 5:
            die = tuple(int(x) for x in f[1:5])
    assert len(got) >= 8 and die, (
        f"the placer produced {len(got)} instance(s), not the 4 pads and 4 "
        f"corners this probe places — it did not run, so it measured nothing"
        f"\n--- stdout ---\n{run.stdout[-2000:]}"
        f"\n--- stderr ---\n{run.stderr[-2000:]}")
    mx, my = (die[0] + die[2]) / 2.0, (die[1] + die[3]) / 2.0
    sides = {n[1:].upper(): PR.normalise_orient(o)
             for n, (o, _, _) in got.items() if n[0] == "p" and len(n) == 2}
    corners = {}
    for name, (orient, cx, cy) in got.items():
        if name.startswith("p") and len(name) == 2:
            continue
        # by QUADRANT, never by the tool's own instance naming
        corners[("S" if cy < my else "N") + ("W" if cx < mx else "E")] = \
            PR.normalise_orient(orient)
    return sides, corners


@pytest.mark.skipif(not _HAVE_OPENROAD,
                    reason=not_verified_reason(
                        "openroad not on PATH; the live placer orientation "
                        "was not measured",
                        "run this test in the shipped flow image"))
@pytest.mark.skipif(not (_PDK_ROOT and Path(_PDK_ROOT).is_dir()),
                    reason=not_verified_reason(
                        "PDK_ROOT does not name an installed PDK tree; the "
                        "live placer orientation was not measured",
                        "set PDK_ROOT to the PDK tree mounted in the shipped "
                        "flow image"))
def test_the_shipped_orientations_are_what_the_placer_produces(tmp_path):
    """THE ONLY TEST HERE THAT CAN FALSIFY THE EIGHT CONSTANTS.

    `SIDE_ORIENT` and `CORNER_ORIENT` are the corrections this branch carries.
    Every other test compares them with a report this code produced FROM them,
    so all of those pass for any self-consistent pair of wrong values. This one
    runs upstream's own call shape — make_io_sites, place_pad on each side,
    place_corners, at librelane's default rotation — and compares what the tool
    put in the database with what we ship.

    IT IS THE TEST THE ORIGINAL PROBE NEEDED. That probe measured correctly and
    inferred wrongly because nothing re-asked the question afterwards; a claim
    about a tool that cannot be re-derived from the tool is a claim on trust.
    """
    lib = _find_io_library(_PDK_ROOT)
    if lib is None:
        skip_not_verified(
            "the selected PDK tree carries no discoverable IO library with "
            "a corner cell; the live placer orientation was not measured",
            "select a PDK tree with the IO LEF/GDS views used by the flow")
    sides, corners = _measure_placer_orientations(lib, tmp_path,
                                                  PR.ROTATION_DEFAULT)
    assert sides == dict(PR.SIDE_ORIENT), (
        f"the placer orients the sides {sides}; this step ships "
        f"{dict(PR.SIDE_ORIENT)}. The DEF must carry what the tool produces")
    assert corners == dict(PR.CORNER_ORIENT), (
        f"the placer orients the corners {corners}; this step ships "
        f"{dict(PR.CORNER_ORIENT)}. A square corner cell hides this in every "
        f"extent check — only a DEF reader sees it")


# --------------------------------------------------------------------------- #
# THE PDK-ADOPTION LAYER
#
# Five of the thirteen contract variables are properties of the IO CELL
# LIBRARY, not of the project: `PAD_SITE_NAME`, `PAD_CORNER_SITE_NAME`,
# `PAD_EDGE_SPACING`, `PAD_CORNER`, `PAD_FILLERS`. The PDK declares all five in
# the SAME `libs.tech/<flow>/<io library>/config.tcl` this step already opens
# for `PAD_FAKE_SITES` — a file this module transcribed two of the answers out
# of, into its own header, and then asked an operator for all five.
#
# The tests below hold three things apart, because they are three different
# claims:
#
#   ADOPTION      a variable the project left out and the PDK declares is
#                 filled FROM THE PDK, with the file AND LINE recorded. Not an
#                 invention: there is no default for any of the five anywhere
#                 in `_pad_ring`, and `..._invents_nothing` is the negative
#                 control that says so.
#   REFUSAL       a project that CONTRADICTS a declaration is refused BY NAME,
#                 `PAD_CONFIG_CONTRADICTS_PDK`, rather than silently preferred
#                 in either direction.
#   RESTRAINT     the other eight — the four side lists, the three rotations
#                 and `SIGNAL_MAP` — are NOT adopted and still SKIP with exit
#                 2. Five of those eight ARE the package pin-out.
# --------------------------------------------------------------------------- #
_FULL_DECL = (
    'set current_folder [file dirname [file normalize [info script]]]\n'
    'set ::env(PAD_SITE_NAME) "io_site"\n'
    'set ::env(PAD_CORNER_SITE_NAME) "io_corner_site"\n'
    'set ::env(PAD_EDGE_SPACING) "10"\n'
    'set ::env(PAD_CORNER) "pad_corner"\n'
    'set ::env(PAD_FILLERS) "pad_fill196"\n'
    "# Create fake pad sites\n"
    "# Note: This is needed if site definition are not in LEF\n"
    "set ::env(PAD_FAKE_SITES) [dict create]\n"
    'dict set ::env(PAD_FAKE_SITES) "io_site" "1.00, 350"\n'
    'dict set ::env(PAD_FAKE_SITES) "io_corner_site" "350, 350"\n'
)

#: The five, and the value the fixture PDK declares for each. Written once so
#: no test re-states the fixture's own numbers back at it.
_DECLARED = {"PAD_SITE_NAME": "io_site",
             "PAD_CORNER_SITE_NAME": "io_corner_site",
             "PAD_EDGE_SPACING": "10",
             "PAD_CORNER": "pad_corner",
             "PAD_FILLERS": ["pad_fill196"]}


def _project_pdk_declares_all_five(tmp_path: Path, *, config=...,
                                   declaration: str = _FULL_DECL,
                                   second: str = None) -> Path:
    """The tech-view fixture, with the config.tcl declaring all five."""
    root = _project(tmp_path, config=config, site_w=1.0)
    (root / "pdk/proc/libs.ref/proc_io/lef/io.lef").write_text(
        _io_lef_sites_not_in_lef(1.0))
    d = root / "pdk/proc/libs.tech/someflow/proc_io"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.tcl").write_text(declaration)
    if second is not None:
        e = root / "pdk/proc/libs.tech/someflow/proc_other_io"
        e.mkdir(parents=True, exist_ok=True)
        (e / "config.tcl").write_text(second)
    return root


def _decls(root: Path, **kw) -> "PR.PdkDeclarations":
    # QUOTED on purpose. This module has no `from __future__ import
    # annotations`, so a bare annotation is evaluated at def time and a tree
    # without the adoption layer would die at COLLECTION — one module error
    # in place of the per-test reds that are the whole point of running the
    # new tests against the old sources.
    lefs = PR.discover_io_lefs(str(root / "pdk"), "proc")
    return PR.PdkDeclarations(
        PR.discover_io_library_configs(str(root / "pdk"), "proc"),
        masters=PR.IoLibrary(lefs).masters, **kw)


# -- ADOPTION ---------------------------------------------------------------
def test_the_pdk_declares_all_five_and_all_five_are_read(tmp_path):
    """THE DEFECT, as a count. The file this step opens declares five of the
    thirteen contract variables and this step read one key out of it."""
    root = _project_pdk_declares_all_five(tmp_path)
    d = _decls(root)
    assert set(d.values) == set(PR.PDK_DECLARED_VARS)
    assert {k: d.values[k] for k in _DECLARED} == _DECLARED
    assert not d.conflicts and not d.rejected


def test_an_adopted_value_is_cited_to_a_file_AND_a_line(tmp_path):
    """A value with no provenance is a value somebody has to trust. The line
    matters as much as the file: this config.tcl declares six variables, and a
    reader sent to the file still has to find the one that was read."""
    root = _project_pdk_declares_all_five(tmp_path)
    d = _decls(root)
    lines = _FULL_DECL.splitlines()
    for var, src in d.sources.items():
        path, _, line = src.rpartition(":")
        assert path.endswith("proc_io/config.tcl"), src
        # the cited line really is the line that declares it
        assert lines[int(line) - 1].startswith(f"set ::env({var})"), src








def test_the_adoption_layer_invents_nothing(tmp_path):
    """THE NEGATIVE CONTROL, and the one that makes the rest mean something.
    Take the declaring file away and the five are not filled by anything —
    there is no default for any of them in `_pad_ring`, so the run refuses
    exactly as it did before this layer existed."""
    only_ours = {k: v for k, v in _config().items()
                 if k not in PR.PDK_DECLARED_VARS}
    root = _project_pdk_declares_all_five(tmp_path, config=only_ours)
    (root / "pdk/proc/libs.tech/someflow/proc_io/config.tcl").unlink()
    assert not _decls(root).values


def test_pad_fillers_is_adopted_as_the_list_the_contract_declares(tmp_path):
    """Upstream spells `PAD_FILLERS` as one whitespace-separated Tcl word and
    this flow's contract spells it as a list. Splitting is a transcription
    between two file formats: no element added, dropped or reordered."""
    decl = _FULL_DECL.replace(
        'set ::env(PAD_FILLERS) "pad_fill196"',
        'set ::env(PAD_FILLERS) "pad_fill196 \\\n'
        '                        pad_fill9"')
    root = _project_pdk_declares_all_five(tmp_path, declaration=decl)
    assert _decls(root).values["PAD_FILLERS"] == ["pad_fill196", "pad_fill9"]


# -- REFUSAL ----------------------------------------------------------------
def test_a_project_that_contradicts_the_pdk_is_refused_by_name(tmp_path):
    """THE REFUSAL THAT PAYS. `PAD_EDGE_SPACING` was checked only for being a
    non-negative number of microns, so a project could place a ring on a
    spacing the PDK contradicts and find out at the shuttle's pad-mask stage —
    a refusal several steps and one gate away from the two numbers that
    disagree, with nothing in any artefact naming them."""
    root = _project_pdk_declares_all_five(
        tmp_path, config=_config(PAD_EDGE_SPACING=20))
    assert "PAD_CONFIG_CONTRADICTS_PDK" in _rules(root)
    # BOTH numbers and the file:line, in the message. A refusal that named
    # only one of them would send a reader to look for the other.


def test_every_one_of_the_five_can_be_contradicted(tmp_path):
    """One refusal reached through one variable proves one variable. All five
    are the IO library's, so all five must refuse."""
    wrong = {"PAD_SITE_NAME": "other_site",
             "PAD_CORNER_SITE_NAME": "other_corner_site",
             "PAD_EDGE_SPACING": 20,
             "PAD_CORNER": "pad_bidir",
             "PAD_FILLERS": ["pad_bidir"]}
    assert set(wrong) == set(PR.PDK_DECLARED_VARS)
    for var, bad in wrong.items():
        root = _project_pdk_declares_all_five(
            tmp_path / var, config=_config(**{var: bad}))
        assert "PAD_CONFIG_CONTRADICTS_PDK" in _rules(root), var


def test_the_contradiction_refusal_is_load_bearing(tmp_path):
    """The bidirectional control. Remove the one comparison and the
    contradicting project is ACCEPTED — a ring placed on a spacing the PDK
    contradicts, with a PASS on it. A test that cannot fail against the
    pre-fix code proves nothing, so here is the pre-fix code."""
    # The PDK declares 20 and the project declares 10. The DISAGREEMENT is
    # what is under test, so it is put on the PDK's side of the fixture and
    # not the project's: the project's 10 is the spacing this synthetic ring
    # abuts at, so with the comparison removed the run reaches a full PASS
    # rather than exiting 1 further down for an unrelated geometric reason.
    # A control that dies of something else has not shown the guard is what
    # made the refusal.
    root = _project_pdk_declares_all_five(
        tmp_path,
        declaration=_FULL_DECL.replace('set ::env(PAD_EDGE_SPACING) "10"',
                                       'set ::env(PAD_EDGE_SPACING) "20"'))
    assert "PAD_CONFIG_CONTRADICTS_PDK" in _rules(root)

    mutant = _mutant(tmp_path, "_pad_ring.py",
                     "        if not _declarations_agree(var, have, "
                     "declared):",
                     "        if False:")
    mut_rep = json.loads((root / PR.REPORT_REL).read_text())
    assert mut_rep["verdict"] == "PASS"
    # and the ring it placed really is on the value the PDK contradicts
    assert mut_rep["config"]["PAD_EDGE_SPACING"] == 10.0






# -- RESTRAINT --------------------------------------------------------------
def test_the_eight_only_the_project_can_answer_still_skip(tmp_path):
    """The honest size of the ask. A project with NO config at all still
    SKIPs with exit 2 — five of the eight it is asked for ARE the package
    pin-out, and a pin-out this program chose would be indistinguishable in
    the artefact from one somebody decided."""
    root = _project_pdk_declares_all_five(tmp_path, config=None)
    rep = _report(root)
    cfg = [m for m in rep["missing_inputs"]
           if m["path"] == PR.ASSIGNMENT_REL][0]
    assert sorted(cfg["variables_from_pdk"]) == sorted(PR.PDK_DECLARED_VARS)
    assert sorted(cfg["variables_absent"]) == sorted(
        v for v in PR.REQUIRED_VARS if v not in PR.PDK_DECLARED_VARS)
    assert len(cfg["variables_absent"]) == 8
    # and the marker a reader standing in pnr/ finds says the same
    assert (root / PR.PADRING_SKIPPED_REL).is_file()


def test_the_adoption_set_is_a_subset_of_what_the_generator_delegates():
    """`pad_assignment_gen.PDK_DELEGATED_VARS` answers a DIFFERENT question —
    what a design's documents left to the PDK, for a config it then WRITES —
    and it delegates eight, including the three rotations. This tuple answers
    "what may this step adopt into a config somebody else wrote", and a
    rotation adopted here would be adopted into a step that has measured it
    cannot honour a non-default one. Pinned so the two never drift apart in
    silence."""
    sys.path.insert(0, str(PROGRAMS))
    import pad_assignment_gen as PAG
    assert set(PR.PDK_DECLARED_VARS) < set(PAG.PDK_DELEGATED_VARS)
    assert set(PAG.PDK_DELEGATED_VARS) - set(PR.PDK_DECLARED_VARS) == {
        "PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL",
        "PAD_ROTATION_CORNER"}
    assert PR.PDK_LIST_VARS == PAG.PDK_LIST_VARS


# -- WHAT THE PDK SAID THAT COULD NOT BE USED -------------------------------
def test_two_libraries_declaring_one_variable_two_ways_adopt_neither(
        tmp_path):
    """The same refusal `site_declaration_conflicts` makes one level down, for
    the same reason: resolving it by directory order would pick a corner
    master out of a directory listing."""
    other = _FULL_DECL.replace('set ::env(PAD_CORNER) "pad_corner"',
                               'set ::env(PAD_CORNER) "pad_bidir"')
    root = _project_pdk_declares_all_five(tmp_path, second=other)
    d = _decls(root)
    assert "PAD_CORNER" not in d.values
    assert [c["value"] for c in d.conflicts["PAD_CORNER"]] == ["pad_corner",
                                                              "pad_bidir"]
    # the other four agree in both files and are still adopted
    assert set(d.values) == set(PR.PDK_DECLARED_VARS) - {"PAD_CORNER"}




def test_the_one_tcl_substitution_these_files_use_is_resolved(tmp_path):
    """MEASURED in the pinned image: one open PDK writes its corner master as
    `"$::env(PAD_CELL_LIBRARY)__cor"`. Upstream sets that variable to the
    library whose config it is loading, which is the name of the DIRECTORY the
    file sits in — read off the path, not guessed."""
    d = tmp_path / "root/pdk/proc/libs.tech/someflow/pad_corner"
    d.mkdir(parents=True)
    (d / "config.tcl").write_text(
        'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)"\n')
    decls = PR.PdkDeclarations([d / "config.tcl"])
    assert decls.values["PAD_CORNER"] == "pad_corner"
    assert decls.sources["PAD_CORNER"].endswith(":1")


def test_a_substitution_that_cannot_be_expanded_is_rejected_with_its_reason(
        tmp_path):
    """"The PDK said nothing" and "the PDK said something this step could not
    expand" are different facts, and only the second one names a file to go
    and read. A master name with a `$` in it would be looked up, not found,
    and refused three steps later with the PDK blamed for it."""
    decl = _FULL_DECL.replace('set ::env(PAD_CORNER) "pad_corner"',
                              'set ::env(PAD_CORNER) "$::env(SOMETHING)_cor"')
    root = _project_pdk_declares_all_five(tmp_path, declaration=decl)
    d = _decls(root)
    assert "PAD_CORNER" not in d.values
    assert "$::env(SOMETHING)_cor" in d.rejected["PAD_CORNER"]
    assert "config.tcl:" in d.rejected["PAD_CORNER"]


def test_a_declaration_naming_a_master_the_library_does_not_carry_is_rejected(
        tmp_path):
    """Rejected HERE, where the file and line are still in hand, rather than
    adopted and refused three steps later with the PDK blamed for it."""
    decl = _FULL_DECL.replace('set ::env(PAD_CORNER) "pad_corner"',
                              'set ::env(PAD_CORNER) "no_such_master"')
    root = _project_pdk_declares_all_five(tmp_path, declaration=decl)
    d = _decls(root)
    assert "PAD_CORNER" not in d.values
    assert "no_such_master" in d.rejected["PAD_CORNER"]
    # and with no master to adopt, a project that leaves it out is refused
    # for the ABSENCE — not completed with a name the library does not have
    only_ours = {k: v for k, v in _config().items() if k != "PAD_CORNER"}
    root2 = _project_pdk_declares_all_five(
        tmp_path / "b", declaration=decl, config=only_ours)
    assert "PAD_CONFIG_VARIABLE_ABSENT" in _rules(root2)




# --------------------------------------------------------------------------- #
# the conflict direction, at this producer's own call site
#
# After the ring is placed, the producer folds the discovered IO LEFs through
# `merge_source_records(on_conflict="richer")` to build the terminal map
# `pad_terminal_bterms` places every chip-top BTerm on.
# `policy_direction_pin_check` reported that site UNPINNED on b309595f06: its
# one candidate test flipped the literal to `"sparser"` and stayed green.
#
# The fixtures above cannot reach the parameter for two independent reasons,
# and both had to be fixed here. They ship ONE library — one source produces
# one `distinct` record per macro and `merge_source_records` returns it before
# `on_conflict` is read — and their masters carry no PIN and their PDK no
# `PAD_PLACE_IO_TERMINALS`, so `pad_terminal_bterms` moves nothing at all and
# the merged map is never read. `test_a_bterm_on_its_pad_is_measured_not_
# declared` covers the same function directly, which is the shape that gets
# greener the more thorough it is and never dies under the flip.
# --------------------------------------------------------------------------- #

#: The masters the fixture below agrees about, in `_io_lef`'s own shape.
_RING_LEF_HEAD = _io_lef().split("MACRO pad_bidir")[0]
_RING_LEF_TAIL = "MACRO pad_corner" + _io_lef().split("MACRO pad_corner", 1)[1]


def _io_lef_with_terminal(pins) -> str:
    """`_io_lef`, with `pad_bidir` given the PORT rectangles a bond pad
    presents. `pins` is `[(pin, [(layer, (x1, y1, x2, y2)), ...]), ...]`."""
    body = ["MACRO pad_bidir", "  CLASS PAD ;", "  SIZE 75.00 BY 350 ;"]
    for pin, rects in pins:
        body += [f"  PIN {pin}", "    DIRECTION INOUT ;", "    USE SIGNAL ;",
                 "    PORT"]
        for layer, r in rects:
            body += [f"      LAYER {layer} ;",
                     "      RECT %.3f %.3f %.3f %.3f ;" % r]
        body += ["    END", f"  END {pin}"]
    body += ["END pad_bidir", ""]
    return _RING_LEF_HEAD + "\n".join(body) + _RING_LEF_TAIL




def _bterm_port_rect(root: Path, signal: str) -> str:
    """The PORT rectangle the emitted padring DEF gives one chip-top BTerm."""
    entry = re.search(rf"-\s+{re.escape(signal)}\s.*?;",
                      _ring_def(root).read_text(), re.S)
    assert entry, f"{signal} has no PIN entry in the padring DEF"
    port = re.search(r"\+\s*PORT\s*\+\s*LAYER\s+\S+\s*"
                     r"\(\s*-?\d+\s+-?\d+\s*\)\s*\(\s*-?\d+\s+-?\d+\s*\)",
                     entry.group(0))
    assert port, f"{signal} was not placed on a pad terminal: {entry.group(0)}"
    return " ".join(port.group(0).split())
