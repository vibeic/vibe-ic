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
import json
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
import pad_ring_check as CHK      # noqa: E402
import pad_ring_gen as GEN        # noqa: E402
from not_verified_tier import (   # noqa: E402
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
def _io_lef(site_w: float = 1.0) -> str:
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
    SIZE 350.00 BY 350.00 ;
END io_corner_site
SITE core_site
    CLASS CORE ;
    SIZE 0.50 BY 4.00 ;
END core_site
MACRO pad_bidir
  CLASS PAD ;
  SIZE 75 BY 350 ;
END pad_bidir
MACRO pad_corner
  CLASS PAD ;
  SIZE 350 BY 350 ;
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
def _floorplan(pins=None, instances=None) -> str:
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
            f"DIEAREA ( 0 0 ) ( {DIE} {DIE} ) ;\n"
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
             io_lib: bool = True, site_w: float = 1.0) -> Path:
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
        (lib / "io.lef").write_text(_io_lef(site_w))
    return root


def _pdk_args(root: Path):
    return ["--pdk-root", str(root / "pdk"), "--pdk", "proc"]


def _gen(root: Path, *extra) -> int:
    return GEN.main([str(root), "--json", str(root / PR.REPORT_REL),
                     *_pdk_args(root), *extra])


def _chk(root: Path, *extra) -> int:
    return CHK.main([str(root), "--json", str(root / PR.REPORT_REL),
                     *_pdk_args(root), *extra])


def _report(root: Path) -> dict:
    return json.loads((root / PR.REPORT_REL).read_text())


def _rules(root: Path):
    return {f["rule"] for f in _report(root).get("findings", [])}


def _rewrite_producer(root: Path, mutate) -> None:
    """Edit the PRODUCER half of the report in place, dropping the wrapper."""
    prod, _ = CHK._unwrap(_report(root))
    mutate(prod)
    (root / PR.REPORT_REL).write_text(json.dumps(prod, indent=2))


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


@pytest.fixture
def placed(tmp_path):
    """A project with a generated, corroborated, abutting pad ring."""
    root = _project(tmp_path)
    assert _gen(root) == 0, _report(root)["reason"]
    return root


# --------------------------------------------------------------------------- #
# the producer — upstream's contract, upstream's algorithm
# --------------------------------------------------------------------------- #
def test_a_declared_config_is_placed_and_the_gate_agrees(placed):
    rep, _ = CHK._unwrap(_report(placed))
    assert rep["verdict"] == "PASS"
    assert len(rep["pads"]) == len(ALL_SIGNALS)
    assert len(rep["corners"]) == 4
    assert rep["bterms"]["uncovered"] == []
    assert rep["abutment"]["abuts"] is True
    assert _ring_def(placed).is_file()
    assert _chk(placed) == 0
    assert _report(placed)["verdict"] == "PASS"


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
    assert _gen(root) == 0, _report(root)
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


def test_the_spacing_is_upstreams_arithmetic(placed):
    """Steps 1-7 of their numbered algorithm, on the fixture's numbers:
    side 1_280_000, pads 4x75_000, fill 980_000, spacing 196_000, and the
    pad-to-corner spacing 196_000 — every gap a whole number of site widths."""
    rep, _ = CHK._unwrap(_report(placed))
    planned = rep["abutment"]["planned_gaps"]
    actual = rep["abutment"]["gaps"]
    assert all(g == 196_000 for side in planned for g in planned[side]), planned
    assert all(g == 0 for side in actual for g in actual[side]), actual
    xs = [p["x"] for p in rep["pads"] if p["side"] == "S"]
    assert xs == [556_000, 827_000, 1_098_000, 1_369_000]


def test_the_skip_names_every_absent_config_variable_one_by_one(tmp_path):
    """DISCLOSURE. Upstream shows exactly what the missing input IS, so the
    skip declares it rather than describing a hole."""
    root = _project(tmp_path, config=None)
    assert _gen(root) == 2
    rep, _ = CHK._unwrap(_report(root))
    assert rep["verdict"] == "SKIP"
    entry = next(m for m in rep["missing_inputs"]
                 if m["path"] == PR.ASSIGNMENT_REL)
    assert entry["variables_absent"] == list(PR.REQUIRED_VARS)
    for var in PR.REQUIRED_VARS:
        assert var in rep["reason"], f"{var} is not named in the skip reason"
    assert "PAD_SOUTH" in rep["reason"] and "PAD_FILLERS" in rep["reason"]
    assert rep["required_upstream_declaration"]
    assert not _ring_def(root).is_file()
    assert (root / PR.PADRING_SKIPPED_REL).is_file()


def test_the_skip_survives_the_gate_as_exit_two_and_never_zero(tmp_path):
    root = _project(tmp_path, config=None)
    assert _gen(root) == 2
    assert _chk(root) == 2
    assert _report(root)["verdict"] == "SKIP"


def test_the_producer_skips_when_the_io_cell_library_is_not_resolved(tmp_path):
    root = _project(tmp_path, io_lib=False)
    assert GEN.main([str(root), "--json", str(root / PR.REPORT_REL),
                     "--pdk-root", str(root / "nowhere")]) == 2
    rep, _ = CHK._unwrap(_report(root))
    assert any("libs.ref" in m["path"] for m in rep["missing_inputs"])


def test_upstream_refusals_are_data_and_not_a_line_on_stderr(placed):
    rep, _ = CHK._unwrap(_report(placed))
    published = {r["rule"]
                 for r in rep["upstream_refusals_made_machine_readable"]}
    assert published == {r for r, _ in
                         GEN.UPSTREAM_REFUSALS_MADE_MACHINE_READABLE}
    assert "PAD_SITE_NOT_FOUND" in published
    assert "PAD_INSTANCE_NOT_IN_BLOCK" in published
    assert "PAD_RING_DOES_NOT_FIT" in published


@pytest.mark.parametrize("var", PR.REQUIRED_VARS)
def test_one_absent_config_variable_is_refused_never_defaulted(tmp_path, var):
    """Their TCL aborts on the first unset `$::env`. So does this — and it
    says which one, in the report."""
    cfg = _config()
    del cfg[var]
    root = _project(tmp_path, config=cfg)
    assert _gen(root) == 1
    assert "PAD_CONFIG_VARIABLE_ABSENT" in _rules(root)
    assert var in _report(root)["reason"]


def test_an_unresolvable_pad_site_is_refused(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="no_such_site"))
    assert _gen(root) == 1
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_a_pad_site_whose_class_is_not_pad_is_refused(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="core_site"))
    assert _gen(root) == 1
    assert "PAD_SITE_CLASS_NOT_PAD" in _rules(root)


def test_an_instance_the_block_does_not_contain_is_refused(tmp_path):
    """Their `No instance <name> found.` — the side variables name instances
    the netlist must already carry."""
    root = _project(tmp_path,
                    floorplan=_floorplan(instances=list(PADS.values())[:-1]))
    assert _gen(root) == 1
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
    assert _gen(root) == 1
    assert "PAD_RING_DOES_NOT_FIT" in _rules(root)


def test_a_corner_spacing_off_the_site_grid_is_refused(tmp_path):
    """Their step 8. With a 6 um pad site the fixture's remaining area is
    202_000 DEF units, which 6_000 does not divide — so the gap between the
    corner and the first pad could not be closed by filler cells."""
    root = _project(tmp_path, site_w=6.0)
    assert _gen(root) == 1
    assert "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE" in _rules(root)


def test_a_non_rectangular_die_is_refused_not_approximated(tmp_path):
    """The contract has one PAD_CORNER and four named positions, so it cannot
    describe a ring on a rectilinear die. Refused rather than squared off —
    approximating it would place metal where the die is not."""
    fp = _floorplan().replace(
        f"DIEAREA ( 0 0 ) ( {DIE} {DIE} ) ;",
        f"DIEAREA ( 0 0 ) ( {DIE} 0 ) ( {DIE} {DIE} ) "
        f"( 500000 {DIE} ) ( 500000 500000 ) ( 0 500000 ) ;")
    root = _project(tmp_path, floorplan=fp)
    assert _gen(root) == 1
    assert "DIE_IS_NOT_RECTANGULAR" in _rules(root)
    assert not _ring_def(root).is_file()


def test_the_algorithm_publishes_its_own_numbers(placed):
    """Upstream prints its spacing arithmetic and keeps none of it. Ours is a
    field, so a later step can read the gaps it has to fill."""
    rep, _ = CHK._unwrap(_report(placed))
    for side in PR.SIDES:
        s = rep["spacing"][side]
        assert s["space_for_fill"] == 980_000
        assert s["between"] == 196_000
        assert s["to_corner"] == 196_000


def test_a_master_the_io_library_does_not_carry_is_refused(tmp_path):
    root = _project(tmp_path, config=_config(PAD_CORNER="corner_i_invented"))
    assert _gen(root) == 1
    assert "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY" in _rules(root)


def test_a_ring_whose_gaps_no_filler_can_close_is_refused(tmp_path):
    """ABUTMENT, at the producer. 196_000 is not a multiple of 9_000, so a
    ring whose only filler is 9 um wide never touches."""
    root = _project(tmp_path, config=_config(PAD_FILLERS=["pad_fill9"]))
    assert _gen(root) == 1
    assert "PADRING_DOES_NOT_ABUT" in _rules(root)
    assert not _ring_def(root).is_file()


def test_an_unknown_rotation_is_refused_not_defaulted(tmp_path):
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL="sideways"))
    assert _gen(root) == 1
    assert "PAD_ROTATION_UNKNOWN" in _rules(root)


def test_a_pad_ordered_on_two_sides_is_refused(tmp_path):
    cfg = _config()
    cfg["PAD_NORTH"] = cfg["PAD_NORTH"] + [cfg["PAD_SOUTH"][0]]
    root = _project(tmp_path, config=cfg)
    assert _gen(root) == 1
    assert "PAD_INSTANCE_DUPLICATED" in _rules(root)


def test_a_bterm_that_reaches_no_pad_is_refused(tmp_path):
    """Ours: upstream deletes IO placement saying `pads are the BTerms` and
    then never checks that every port reached one."""
    root = _project(tmp_path,
                    floorplan=_floorplan(pins=ALL_SIGNALS + ["orphan_port"]))
    assert _gen(root) == 1
    assert "BTERM_WITHOUT_PAD" in _rules(root)
    assert "orphan_port" in _report(root)["reason"]


def test_what_this_step_does_not_do_is_in_the_artefact(placed):
    rep, _ = CHK._unwrap(_report(placed))
    assert rep["fillers_placed"] == len(rep["fillers"]) == 20
    assert "io_filler_placement" not in rep["unperformed"]
    assert rep["fillers_declared"] == ["pad_fill196"]
    assert all(f["master"] == "pad_fill196" for f in rep["fillers"])


def test_removing_one_physical_filler_makes_the_gate_red(placed):
    rep, _ = CHK._unwrap(_report(placed))
    victim = rep["fillers"][0]["instance"]
    line = _line(placed, victim)
    _edit_def(placed, line + "\n", "")
    assert _chk(placed) == 1
    assert "PAD_INSTANCE_ABSENT_FROM_DEF" in _rules(placed)


def test_declared_but_unperformed_optional_variables_are_echoed(tmp_path):
    root = _project(tmp_path, config=_config(PAD_BONDPAD_NAME="pad_bond"))
    assert _gen(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    assert "PAD_BONDPAD_NAME" in rep["unperformed"]


# --------------------------------------------------------------------------- #
# the gate — DISCLOSURE
# --------------------------------------------------------------------------- #
def test_an_absent_report_is_not_a_skip(tmp_path):
    root = _project(tmp_path)
    assert _chk(root) == 1
    assert "PADRING_REPORT_ABSENT" in _rules(root)


def test_an_unreadable_report_is_not_a_skip(placed):
    (placed / PR.REPORT_REL).write_text("{not json")
    assert _chk(placed) == 1
    assert "PADRING_REPORT_UNREADABLE" in _rules(placed)


def test_a_report_of_an_unknown_schema_is_not_interpreted(placed):
    _rewrite_producer(placed, lambda r: r.update(schema="something/else"))
    assert _chk(placed) == 1
    assert "PADRING_REPORT_SCHEMA_UNKNOWN" in _rules(placed)


def test_a_verdict_outside_the_vocabulary_is_not_a_pass(placed):
    _rewrite_producer(placed, lambda r: r.update(verdict="OK"))
    assert _chk(placed) == 1
    assert "PADRING_VERDICT_UNRECOGNISED" in _rules(placed)


def test_a_producer_failure_is_propagated_not_absorbed(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="no_such_site"))
    assert _gen(root) == 1
    assert _chk(root) == 1
    assert "PADRING_GENERATION_FAILED" in _rules(root)


def test_a_skip_that_names_no_absent_input_fails(tmp_path):
    root = _project(tmp_path, config=None)
    _gen(root)
    _rewrite_producer(root, lambda r: r.update(missing_inputs=[]))
    assert _chk(root) == 1
    assert "PADRING_SKIP_UNDISCLOSED" in _rules(root)


def test_a_skip_whose_reason_is_a_shrug_fails(tmp_path):
    root = _project(tmp_path, config=None)
    _gen(root)
    _rewrite_producer(root, lambda r: r.update(reason="n/a"))
    assert _chk(root) == 1
    assert "PADRING_SKIP_REASON_TOO_SHORT" in _rules(root)


def test_a_skip_that_hides_one_of_its_absent_variables_fails(tmp_path):
    """The strong form of the disclosure rule: a reason that names the FILE
    but drops a variable off the list still fails."""
    root = _project(tmp_path, config=None)
    _gen(root)
    _rewrite_producer(root, lambda r: r.update(
        reason=r["reason"].replace("PAD_FILLERS, ", "")))
    assert _chk(root) == 1
    assert "PADRING_SKIP_DOES_NOT_NAME_INPUT" in _rules(root)
    assert "PAD_FILLERS" in str(_report(root)["findings"])


def test_a_skip_contradicted_by_a_ring_on_disk_fails(tmp_path):
    root = _project(tmp_path, config=None)
    _gen(root)
    _ring_def(root).write_text("VERSION 5.8 ;\n")
    assert _chk(root) == 1
    assert "PADRING_SKIP_CONTRADICTED" in _rules(root)


# --------------------------------------------------------------------------- #
# the gate — CORROBORATION
# --------------------------------------------------------------------------- #
def test_a_pass_with_no_layout_behind_it_fails(placed):
    _ring_def(placed).unlink()
    assert _chk(placed) == 1
    assert "PADRING_DEF_ABSENT" in _rules(placed)


def test_a_pass_over_zero_pads_fails(placed):
    _rewrite_producer(placed, lambda r: r.update(pads=[]))
    assert _chk(placed) == 1
    assert "PADRING_EMPTY" in _rules(placed), (
        "a green over an empty set is the defect this repository hunts")


def test_a_pad_the_def_does_not_instantiate_fails(placed):
    line = _line(placed, "pad_ssig1")
    _edit_def(placed, line + "\n", "")
    assert _chk(placed) == 1
    assert "PAD_INSTANCE_ABSENT_FROM_DEF" in _rules(placed)


def test_an_unplaced_pad_fails(placed):
    _edit_def(placed, _line(placed, "pad_ssig1"),
              "- pad_ssig1 pad_bidir + UNPLACED ;")
    assert _chk(placed) == 1
    assert "PAD_INSTANCE_UNPLACED" in _rules(placed)


def test_a_master_the_report_and_the_def_disagree_on_fails(placed):
    _edit_def(placed, "- pad_ssig1 pad_bidir", "- pad_ssig1 pad_fill1")
    assert _chk(placed) == 1
    assert "PAD_MASTER_MISMATCH" in _rules(placed)


def test_a_pad_on_the_wrong_side_of_the_die_fails(placed):
    """The side claim is re-derived from the placement, not believed."""
    _edit_def(placed, _line(placed, "pad_ssig1"),
              "- pad_ssig1 pad_bidir + FIXED ( 827000 1640000 ) S ;")
    assert _chk(placed) == 1
    assert "PAD_SIDE_MISMATCH" in _rules(placed)


def test_a_footprint_the_io_library_does_not_give_that_master_fails(placed):
    def _shrink(r):
        r["pads"][0]["width_dbu"] = 10
        r["pads"][0]["height_dbu"] = 10
    _rewrite_producer(placed, _shrink)
    assert _chk(placed) == 1
    assert "PAD_FOOTPRINT_DISAGREES_WITH_LIBRARY" in _rules(placed)


def test_a_pad_with_no_declared_footprint_cannot_be_corroborated(placed):
    _rewrite_producer(placed, lambda r: r["pads"][0].pop("width_dbu"))
    assert _chk(placed) == 1
    assert "PAD_FOOTPRINT_UNDECLARED" in _rules(placed)


def test_a_master_outside_the_io_cell_library_fails(placed):
    _edit_def(placed, "- pad_ssig1 pad_bidir", "- pad_ssig1 pad_drawn_by_hand")
    _rewrite_producer(
        placed,
        lambda r: [p.update(master="pad_drawn_by_hand")
                   for p in r["pads"] if p["instance"] == "pad_ssig1"])
    assert _chk(placed) == 1
    assert "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY" in _rules(placed)


def test_an_unresolved_io_library_is_not_a_pass(placed):
    """`the pads are PDK cells` is the central claim of the step. Unverified
    is not verified."""
    rc = CHK.main([str(placed), "--json", str(placed / PR.REPORT_REL),
                   "--pdk-root", str(placed / "nowhere")])
    assert rc == 1
    assert "PADRING_MASTERS_UNCORROBORATED" in _rules(placed)


def test_a_site_the_library_does_not_declare_fails_at_the_gate(placed):
    _rewrite_producer(placed,
                      lambda r: r["config"].update(PAD_SITE_NAME="gone"))
    assert _chk(placed) == 1
    assert "PAD_SITE_NOT_FOUND" in _rules(placed)


def test_a_site_whose_class_is_not_pad_fails_at_the_gate(placed):
    _rewrite_producer(
        placed, lambda r: r["config"].update(PAD_CORNER_SITE_NAME="core_site"))
    assert _chk(placed) == 1
    assert "PAD_SITE_CLASS_NOT_PAD" in _rules(placed)


def test_a_pad_off_the_die_fails(placed):
    _edit_def(placed, _line(placed, "pad_ssig1"),
              "- pad_ssig1 pad_bidir + FIXED ( 827000 -400000 ) N ;")
    assert _chk(placed) == 1
    assert "PAD_OUTSIDE_DIE" in _rules(placed)


def test_two_pads_in_the_same_place_fail(placed):
    _edit_def(placed, _line(placed, "pad_ssig1"),
              "- pad_ssig1 pad_bidir + FIXED ( 560000 10000 ) N ;")
    assert _chk(placed) == 1
    assert "PAD_OVERLAP" in _rules(placed)


def test_a_ring_with_an_unfilled_corner_fails(placed):
    _rewrite_producer(placed, lambda r: r["corners"].pop())
    assert _chk(placed) == 1
    assert "PADRING_CORNERS_INCOMPLETE" in _rules(placed)


def test_a_corner_cell_in_the_wrong_quadrant_fails(placed):
    _rewrite_producer(
        placed,
        lambda r: [c.update(position="NE") for c in r["corners"]
                   if c["position"] == "SW"])
    assert _chk(placed) == 1
    assert "PADRING_CORNER_POSITION_MISMATCH" in _rules(placed)


def test_a_bterm_that_reaches_no_pad_fails_at_the_gate_too(placed):
    (placed / PR.FLOORPLAN_DEF_REL).write_text(
        _floorplan(pins=ALL_SIGNALS + ["orphan_port"]))
    assert _chk(placed) == 1
    assert "BTERM_WITHOUT_PAD" in _rules(placed)


def test_a_pad_the_block_does_not_instantiate_fails_at_the_gate(placed):
    (placed / PR.FLOORPLAN_DEF_REL).write_text(
        _floorplan(instances=list(PADS.values())[:-1]))
    assert _chk(placed) == 1
    assert "PAD_INSTANCE_NOT_IN_BLOCK" in _rules(placed)


def test_an_absent_floorplan_leaves_coverage_unchecked_and_that_is_not_clean(placed):
    (placed / PR.FLOORPLAN_DEF_REL).unlink()
    assert _chk(placed) == 1
    assert "PADRING_BTERM_COVERAGE_UNCORROBORATED" in _rules(placed)


# --------------------------------------------------------------------------- #
# the gate — ABUTMENT
# --------------------------------------------------------------------------- #
def test_a_ring_that_places_perfectly_and_does_not_abut_fails(placed):
    """Remove one filler honestly from both report and DEF. Every remaining
    instance is valid and non-overlapping; only the physical gap is red."""
    producer, _ = CHK._unwrap(_report(placed))
    victim = producer["fillers"][0]["instance"]
    _edit_def(placed, _line(placed, victim) + "\n", "")
    def drop_filler(rep):
        rep["fillers"] = [f for f in rep["fillers"]
                          if f["instance"] != victim]
        rep["fillers_placed"] = len(rep["fillers"])
    _rewrite_producer(placed, drop_filler)
    assert _chk(placed) == 1
    rules = _rules(placed)
    assert "PADRING_DOES_NOT_ABUT" in rules
    assert not (rules & {"PAD_SIDE_MISMATCH", "PAD_OVERLAP", "PAD_OUTSIDE_DIE",
                         "PAD_MASTER_MISMATCH"}), rules


def test_a_filler_the_library_does_not_carry_leaves_abutment_unverified(placed):
    _rewrite_producer(
        placed, lambda r: r["config"].update(PAD_FILLERS=["filler_i_invented"]))
    assert _chk(placed) == 1
    assert "PADRING_FILLER_UNRESOLVED" in _rules(placed)


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
        plan = GEN._filler_plan(gap, widths)
        representable = any(3 * a + 5 * b == gap
                            for a in range(18) for b in range(12))
        assert (plan is not None) == representable, gap
        if plan is not None:
            assert sum(widths[master] for master in plan) == gap

    # The ordinary unfillable-gap path is refused before placement.  Force the
    # defensive planner branch so an internal invariant failure cannot regress
    # to an unexplained ``*_MISSING`` verdict that hides what it searched.
    root = _project(tmp_path)
    monkeypatch.setattr(GEN, "_filler_plan",
                        lambda _gap, _master_widths: None)
    assert _gen(root) == 1
    findings = [f for f in _report(root)["findings"]
                if f["rule"] == "PADRING_FILLER_PLAN_MISSING"]
    assert findings
    assert all("master candidates" in f["message"] for f in findings)
    assert all("pad_fill196" in f["message"] for f in findings)
    assert not _ring_def(root).is_file()


# --------------------------------------------------------------------------- #
# the audit must not become its own evidence
# --------------------------------------------------------------------------- #
def test_the_gate_preserves_the_producers_claim_verbatim(placed):
    before, _ = CHK._unwrap(_report(placed))
    assert _chk(placed) == 0
    after, merged = CHK._unwrap(_report(placed))
    assert merged, "the gate must wrap, not replace, the producer's report"
    assert after == before


def test_re_running_the_gate_does_not_nest_or_change_the_verdict(placed):
    assert _chk(placed) == 0
    assert _chk(placed) == 0
    doc = _report(placed)
    assert doc["producer"]["program"] == "pad_ring_gen"
    assert "producer" not in doc["producer"]


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
    fcc = pytest.importorskip("flow_compliance_check")
    for cmd in _gate_commands(_step_155ic()["gate"]):
        argv = fcc._resolve_program_cmd(cmd)
        assert argv, cmd
        assert Path(argv[1]).is_file(), cmd
    argv = fcc._resolve_program_cmd(
        "pad_ring_check . --json reports/phase3/padring.json")
    assert argv and Path(argv[1]).name == "pad_ring_check.py"
    assert (PROGRAMS / "pad_ring_gen.py").is_file()


def test_the_gate_runs_as_the_flow_spawns_it(placed):
    """Driven exactly as `program_exit_zero` drives it: cwd = the project, the
    report path relative, no PDK flags — so the PDK probe is the one a real
    run gets."""
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "pad_ring_check.py"), ".",
         "--json", PR.REPORT_REL],
        cwd=placed, capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "pad_ring_check" in r.stdout


# --------------------------------------------------------------------------- #
# chip-agnosticism
# --------------------------------------------------------------------------- #
_OURS = ("_pad_ring.py", "pad_ring_gen.py", "pad_ring_check.py",
         # The author of this step's own input (vibe-ic#1410/cpath). It reads
         # an operator slot file and a tape-out declaration and writes the
         # config `pad_ring_gen` consumes, so it is subject to exactly the
         # same rule as the three above.
         "pad_assignment_gen.py",
         "tests/test_pad_ring.py",
         "tests/test_pad_and_seal_ring_on_the_chip_path.py")


def test_no_process_node_shaped_literal_in_these_programs():
    """A process or library name in this domain looks like
    `<letters><digits>...`. The rule is generic so this test needs no
    forbidden literal of its own."""
    import re
    shaped = re.compile(r"\b[a-z]{2,}\d{2,}\w*\b")
    for rel in _OURS:
        for hit in shaped.findall((PROGRAMS / rel).read_text()):
            pytest.fail(f"{rel}: process-node-shaped literal {hit!r}")


def test_no_installed_pdk_tree_name_appears_in_these_programs():
    """The strongest available form: the names of the PDKs this run can see."""
    import os
    root = os.environ.get("PDK_ROOT")
    if not root or not Path(root).is_dir():
        pytest.skip("no PDK_ROOT on this host")
    names = [p.name for p in Path(root).iterdir() if p.is_dir()]
    assert names, "PDK_ROOT holds no tree; this test would prove nothing"
    for rel in _OURS:
        text = (PROGRAMS / rel).read_text().lower()
        for n in names:
            assert n.lower() not in text, f"{rel} names the PDK tree {n!r}"


# --------------------------------------------------------------------------- #
# the mutation harness the change report drives
# --------------------------------------------------------------------------- #
def _mutant(tmp_path: Path, filename: str, old: str, new: str) -> Path:
    """A scratch copy of the programs tree with ONE guard broken.

    Used to demonstrate that a refusal is load bearing: with the guard removed
    the corresponding case goes green where the real gate refuses.
    """
    dst = tmp_path / "mutant"
    dst.mkdir(exist_ok=True)
    for f in ("_pad_ring.py", "pad_ring_gen.py", "pad_ring_check.py",
              "_atomic_artefact.py"):
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


def test_the_empty_ring_guard_is_load_bearing(tmp_path, placed):
    """Remove the zero-pad refusal and the empty-set refusal stops being made.

    Asserted at RULE level rather than on the exit code, and that is not a
    weakening — it is what the artefact actually shows. An empty `pads` list
    also trips the corner and BTerm-coverage guards, so the mutant still exits
    1 by a different route. Comparing exit codes here would have "proved" the
    guard load bearing on a run where two OTHER guards did the work. What is
    load bearing about THIS guard is that it is the one which says the set was
    empty; with it removed, nothing does."""
    mut = _mutant(tmp_path, "pad_ring_check.py",
                  "if not isinstance(pads, list) or not pads:",
                  "if not isinstance(pads, list):")
    _rewrite_producer(placed, lambda r: r.update(pads=[]))
    assert _chk(placed) == 1
    assert "PADRING_EMPTY" in _rules(placed)
    r = _run(mut, placed)
    assert "PADRING_EMPTY" not in r.stdout, r.stdout


def test_the_abutment_guard_is_load_bearing(tmp_path, placed):
    """Remove the abutment walk's refusal and a ring that never touches
    passes — the exact defect no placement check notices."""
    producer, _ = CHK._unwrap(_report(placed))
    victim = producer["fillers"][0]["instance"]
    _edit_def(placed, _line(placed, victim) + "\n", "")
    def drop_filler(rep):
        rep["fillers"] = [f for f in rep["fillers"]
                          if f["instance"] != victim]
        rep["fillers_placed"] = len(rep["fillers"])
    _rewrite_producer(placed, drop_filler)
    mut = _mutant(tmp_path, "pad_ring_check.py",
                  "elif gap > 0:", "elif False:")
    real = _chk(placed)
    r = _run(mut, placed)
    assert real == 1 and r.returncode == 0, (
        f"real={real} mutant={r.returncode}\n{r.stdout}")


def test_the_skip_disclosure_guard_is_load_bearing(tmp_path):
    """Remove the `missing_inputs` requirement and a bare SKIP passes."""
    root = _project(tmp_path, config=None)
    _gen(root)
    _rewrite_producer(root, lambda r: r.update(missing_inputs=[]))
    mut = _mutant(tmp_path, "pad_ring_check.py",
                  "if not isinstance(missing, list) or not missing:",
                  "if False:")
    real = _chk(root)
    r = _run(mut, root)
    assert real == 1 and r.returncode == 2, (
        f"real={real} mutant={r.returncode}\n{r.stdout}")


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


def _site_declaration(*entries: tuple) -> str:
    """A PDK tech-view config in the form the distributions write it."""
    lines = ["set current_folder [file dirname [file normalize [info script]]]",
             'set ::env(PAD_SITE_NAME) "io_site"',
             'set ::env(PAD_CORNER_SITE_NAME) "io_corner_site"',
             "# Create fake pad sites",
             "# Note: This is needed if site definition are not in LEF",
             "set ::env(PAD_FAKE_SITES) [dict create]"]
    lines += [f'dict set ::env(PAD_FAKE_SITES) "{n}" "{w}, {h}"'
              for n, w, h in entries]
    return "\n".join(lines) + "\n"


def _project_sites_in_tech_view(tmp_path: Path, *, site_w: float = 1.0,
                                declare: bool = True,
                                second_lib: tuple = None,
                                config=...) -> Path:
    root = _project(tmp_path, config=config, site_w=site_w)
    (root / "pdk/proc/libs.ref/proc_io/lef/io.lef").write_text(
        _io_lef_sites_not_in_lef(site_w))
    if declare:
        d = root / "pdk/proc/libs.tech/someflow/proc_io"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.tcl").write_text(_site_declaration(
            ("io_site", f"{site_w:.2f}", "350"),
            ("io_corner_site", "350", "350")))
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
    assert _gen(root) == 0, _report(root)["reason"]
    rep, _ = CHK._unwrap(_report(root))
    assert rep["verdict"] == "PASS"
    assert len(rep["pads"]) == len(ALL_SIGNALS)
    assert rep["abutment"]["abuts"] is True
    assert _chk(root) == 0


def test_the_tech_view_site_is_the_same_ring_as_the_lef_site(tmp_path):
    """A site is a site. Reading the second view must place the SAME ring,
    to the DEF unit — otherwise the fix changed the geometry rather than
    where the geometry was read from."""
    lef_root = _project(tmp_path / "a")
    tech_root = _project_sites_in_tech_view(tmp_path / "b")
    assert _gen(lef_root) == 0 and _gen(tech_root) == 0
    a, _ = CHK._unwrap(_report(lef_root))
    b, _ = CHK._unwrap(_report(tech_root))
    assert a["pads"] == b["pads"]
    assert a["corners"] == b["corners"]
    assert a["spacing"] == b["spacing"]
    assert a["abutment"]["gaps"] == b["abutment"]["gaps"]


def test_the_artefact_says_which_pdk_view_each_site_came_from(tmp_path):
    """A resolved site is not enough; the report has to say WHERE from, or a
    reader cannot tell a site that was read from one that was declared."""
    tech_root = _project_sites_in_tech_view(tmp_path / "b")
    assert _gen(tech_root) == 0
    b, _ = CHK._unwrap(_report(tech_root))
    src = b["config"]["site_source"]
    assert src["PAD_SITE_NAME"].startswith(PR.SITE_SOURCE_DECLARED)
    assert src["PAD_CORNER_SITE_NAME"].startswith(PR.SITE_SOURCE_DECLARED)
    assert "config.tcl" in src["PAD_SITE_NAME"]
    lef_root = _project(tmp_path / "a")
    assert _gen(lef_root) == 0
    a, _ = CHK._unwrap(_report(lef_root))
    assert a["config"]["site_source"]["PAD_SITE_NAME"] == PR.SITE_SOURCE_LEF


def test_a_site_declared_by_neither_pdk_view_is_still_refused(tmp_path):
    """The refusal has to stay reachable. Reading a second view widens WHERE
    a site may be declared; it does not let a name nobody declared through."""
    root = _project_sites_in_tech_view(
        tmp_path, config=_config(PAD_SITE_NAME="no_such_site"))
    assert _gen(root) == 1
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_a_pdk_that_declares_no_site_anywhere_is_still_refused(tmp_path):
    """The LEF view is empty and there is no tech view either. Nothing was
    invented to fill the hole."""
    root = _project_sites_in_tech_view(tmp_path, declare=False)
    assert _gen(root) == 1
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_a_site_declared_at_two_sizes_is_refused_not_ordered(tmp_path):
    """A tree may ship more than one IO library. Upstream reads one config and
    never sees a second; this step discovers them, so it can. The site width
    is what every gap in the ring is rounded to, and picking it out of a
    directory listing would put the ring's abutment on file order."""
    root = _project_sites_in_tech_view(
        tmp_path, second_lib=(("io_site", "2.00", "350"),
                              ("io_corner_site", "350", "350")))
    assert _gen(root) == 1
    assert "PAD_SITE_DECLARATION_AMBIGUOUS" in _rules(root)
    assert "io_site" in _report(root)["reason"]


def test_two_libraries_that_agree_are_not_an_ambiguity(tmp_path):
    """Every distribution measured ships the same site twice, identically —
    once per IO library. Agreement is not a conflict."""
    root = _project_sites_in_tech_view(
        tmp_path, second_lib=(("io_site", "1.00", "350"),
                              ("io_corner_site", "350", "350")))
    assert _gen(root) == 0, _report(root)["reason"]


def test_only_the_pdk_may_declare_a_site_never_the_project(tmp_path):
    """The config contract carries no site GEOMETRY and this fix does not add
    any. A project that writes PAD_FAKE_SITES into its own pad_assignment.json
    gets nothing from it — the site is still looked up in the PDK."""
    root = _project_sites_in_tech_view(
        tmp_path, declare=False,
        config=dict(_config(PAD_SITE_NAME="project_invented_site"),
                    PAD_FAKE_SITES={"project_invented_site": [1.0, 350.0]}))
    assert _gen(root) == 1
    assert "PAD_SITE_NOT_FOUND" in _rules(root)


def test_the_gate_reads_the_same_two_views_as_the_producer(tmp_path):
    """An auditor that consulted only the LEF would call a correctly placed
    ring PAD_SITE_NOT_FOUND — a gate contradicting its own producer over which
    file it opened."""
    root = _project_sites_in_tech_view(tmp_path)
    assert _gen(root) == 0
    assert _chk(root) == 0
    _rewrite_producer(root,
                      lambda r: r["config"].update(PAD_SITE_NAME="gone"))
    assert _chk(root) == 1
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
def test_a_vertical_side_sums_the_master_width_not_its_height(tmp_path):
    """THE DEFECT. Four pads a side, 75 um wide and 350 um tall, on a die whose
    sides are 1280 um. Summing widths gives 300 and fits; summing heights gives
    1400 and does not. Upstream sums widths on every side."""
    root = _project(tmp_path)
    assert _gen(root) == 0, _report(root)["reason"]
    rep, _ = CHK._unwrap(_report(root))
    for side in ("PAD_EAST", "PAD_WEST"):
        assert rep["spacing"][side[4]]["space_for_fill"] == 1280_000 - 4 * 75_000
    # every side sums the same, because every side sums the same thing
    fills = {s: rep["spacing"][s]["space_for_fill"] for s in PR.SIDES}
    assert len(set(fills.values())) == 1, fills


def test_the_vertical_sides_carry_the_orientation_the_placer_produces(tmp_path):
    """THE DEF MUST NOT CONTRADICT ITSELF. The orientation written is the one
    the tool actually produces, ON ALL FOUR SIDES — measured at librelane's
    default: SOUTH R0->N, NORTH MX->FS, WEST MXR90->FW, EAST R90->W — so the
    footprint a DEF reader derives matches the geometry this step recorded.

    NORTH IS HERE BECAUSE IT WAS WRONG. This step used to compute NORTH as
    rotate_cw(PAD_ROTATION_HORIZONTAL, 2), which is S (R180) at the default,
    where the placer produces MX (FS): the same bounding box, MIRRORED rather
    than rotated, so pin positions differ. Part 3 of the ruling was applied to
    the vertical sides and missed this one."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    got = {p["side"]: p["orient"] for p in rep["pads"]}
    assert got["S"] == PR.SIDE_ORIENT["S"] == PR.ORIENT_ALIASES["R0"]
    assert got["N"] == PR.SIDE_ORIENT["N"] == PR.ORIENT_ALIASES["MX"], (
        "NORTH must be the placer's MX (FS), not rotate_cw(..., 2) -> S")
    assert got["W"] == PR.SIDE_ORIENT["W"] == PR.ORIENT_ALIASES["MXR90"]
    assert got["E"] == PR.SIDE_ORIENT["E"] == PR.ORIENT_ALIASES["R90"]
    # and the DEF says the same thing the report does
    for pad in rep["pads"]:
        assert f"( {pad['x']} {pad['y']} ) {pad['orient']} ;" in \
            _ring_def(root).read_text()
    # the recorded extents are the oriented footprint of that orientation
    for pad in (p for p in rep["pads"] if p["side"] in PR.VERTICAL_SIDES):
        w, h = PR.footprint(( 75.0, 350.0), pad["orient"], UNITS)
        assert (pad["width_dbu"], pad["height_dbu"]) == (w, h)


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
    assert _gen(root) == 2
    rep, _ = CHK._unwrap(_report(root))
    assert rep["verdict"] == "SKIP"
    assert "PAD_ROTATION_VERTICAL_NOT_HONOURED" in _rules(root)
    assert "PAD_ROTATION_VERTICAL" in rep["reason"]
    assert "R90" in rep["reason"]
    # no ring was placed and none was claimed
    assert not _ring_def(root).is_file()
    assert rep["pads"] == [] and rep["verdict"] != "PASS"
    assert (root / PR.PADRING_SKIPPED_REL).is_file()


@pytest.mark.parametrize("value", ["R90", "R180", "R270", "MX", "MXR90"])
def test_every_non_default_vertical_rotation_is_refused(tmp_path, value):
    """Not just the one the fixture used to carry."""
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL=value))
    assert _gen(root) == 2
    assert "PAD_ROTATION_VERTICAL_NOT_HONOURED" in _rules(root)


def test_the_default_vertical_rotation_proceeds_and_is_told_it_is_unhonoured(
        tmp_path):
    """The other half of the rule, and the half that keeps it honest. A run at
    librelane's default is indistinguishable from a run that set nothing, so it
    proceeds — and the report SAYS the variable is NOT HONOURED HERE, with the
    measurement, rather than leaving a reader to find out."""
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL="R0"))
    assert _gen(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    rec = rep["rotation_vertical_not_honoured"]
    assert rec["variable"] == "PAD_ROTATION_VERTICAL"
    assert rec["honoured"] is False
    assert rec["measured_orientation"] == {"W": "MXR90", "E": "R90"}
    assert rec["librelane_default"] == PR.ROTATION_DEFAULT


def test_the_disclosure_is_in_every_report_including_the_skip(tmp_path):
    """A disclosure only present on the happy path is not a disclosure."""
    for cfg in (None, _config(), _config(PAD_ROTATION_VERTICAL="R90")):
        root = _project(tmp_path / f"p{id(cfg)}", config=cfg)
        _gen(root)
        rep, _ = CHK._unwrap(_report(root))
        assert rep["rotation_vertical_not_honoured"]["honoured"] is False


def test_the_disclosure_does_not_claim_the_variable_is_inert(tmp_path):
    """THE CLAIM THIS PINS WAS SHIPPED WRONG, so it is pinned rather than
    trusted. The report used to say PAD_ROTATION_VERTICAL was INERT and that
    'the placer does not read it'. RE-MEASURED 2026-08-22 in OpenROAD
    26Q3-1581, holding one parameter and varying the other across all four
    sides: `-rotation_horizontal` moves WEST and EAST, `-rotation_vertical`
    moves SOUTH and NORTH. The parameters are named for the ROW AXIS, not the
    side. The original probe varied PAD_ROTATION_VERTICAL while watching only
    WEST and EAST -- the wrong pairing -- so it correctly saw no change and the
    wrong conclusion was drawn from a correct measurement.

    The honest claim is NOT HONOURED BY THIS STEP, which is weaker and true.
    This test fails if 'inert' or 'does not read' comes back."""
    root = _project(tmp_path, config=_config(PAD_ROTATION_VERTICAL="R0"))
    assert _gen(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    assert "rotation_vertical_inert" not in rep, (
        "the key asserts inertness in the schema itself")
    rec = rep["rotation_vertical_not_honoured"]
    blob = json.dumps(rec)
    _assert_no_retracted_claim(blob, "the disclosure")
    assert "does not implement" in blob.lower()


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
    assert _gen(root) == 0
    declared = PR.normalise_orient(_config()["PAD_ROTATION_VERTICAL"])
    assert declared != PR.SIDE_ORIENT["W"], (
        "premise: the declared rotation and the placer's are different")
    victim = next(p["instance"] for p in CHK._unwrap(_report(root))[0]["pads"]
                  if p["side"] == "W")
    _edit_def(root, _line(root, victim),
              _line(root, victim).rsplit(" ", 2)[0] + f" {declared} ;")
    assert _chk(root) == 1
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
    assert _gen(root) == 0, _report(root)["reason"]
    rep, _ = CHK._unwrap(_report(root))
    assert rep["config"]["site_source"]["PAD_SITE_NAME"] == PR.SITE_SOURCE_LEF
    assert rep["spacing"]["S"]["between"] % 1000 == 0, rep["spacing"]


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
    sources = "\n".join(
        (here / n).read_text(encoding="utf-8")
        for n in ("_pad_ring.py", "pad_ring_gen.py", "pad_ring_check.py"))
    actually = {v for v in upstream
                if re.search(r"\b%s\b" % re.escape(v), sources)}
    assert len(actually) == named_claim, (
        f"header claims {named_claim} named; the modules name "
        f"{len(actually)}: {sorted(actually)}")


def test_north_pads_are_mirrored_not_rotated(tmp_path):
    """THE DEFECT, STATED AS A VALUE THE OLD CODE CAN PRODUCE.

    Deliberately uses NO constant this change introduces, so the pre-fix tree
    runs it and answers WRONGLY rather than raising AttributeError. An
    AttributeError control observes nothing: it proves a rename happened, not
    that a defect existed.

    MEASURED, OpenROAD 26Q3-1581, librelane's default rotations, north pad:
    orient MX, whose DEF spelling is FS. The pre-fix step computed NORTH as
    rotate_cw(PAD_ROTATION_HORIZONTAL, 2) = S (R180). S and FS share a bounding
    box and differ by a mirror, so the fit arithmetic cannot see the difference
    and a DEF reader deriving pin positions can."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    north = sorted({p["orient"] for p in rep["pads"] if p["side"] == "N"})
    assert north == ["FS"], (
        f"north pads carry {north}; the placer produces MX -> 'FS'. "
        f"'S' is a 180-degree ROTATION where the tool applies a MIRROR")
    # and the DEF agrees with the report, since that is the whole point
    text = _ring_def(root).read_text()
    for pad in (p for p in rep["pads"] if p["side"] == "N"):
        assert f"( {pad['x']} {pad['y']} ) FS ;" in text


def test_corners_alternate_rotation_and_mirror(tmp_path):
    """TWO OF FOUR CORNERS WERE WRONG IN EVERY RING THIS STEP EVER WROTE.

    Uses no constant this change introduces, so the pre-fix tree runs it and
    answers wrongly rather than raising AttributeError.

    MEASURED, OpenROAD 26Q3-1581, `place_corners` after `make_io_sites
    -rotation_corner R0`: SW=R0, SE=MY, NE=R180, NW=MX -> N, FN, S, FS. THE
    PLACER ALTERNATES ROTATION AND MIRROR. The pre-fix step walked
    rotate_cw(PAD_ROTATION_CORNER, i) -- N, E, S, W -- a pure rotation, so SE
    and NW came out E and W. A square corner cell has the same bounding box
    either way, which is why no fit check could ever have caught it."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    got = {c["position"]: c["orient"] for c in rep["corners"]}
    assert got == {"SW": "N", "SE": "FN", "NE": "S", "NW": "FS"}, (
        f"corners are {got}; the placer produces "
        f"{{'SW': 'N', 'SE': 'FN', 'NE': 'S', 'NW': 'FS'}} -- a pure rotation "
        f"gives E and W where the tool mirrors")
    text = _ring_def(root).read_text()
    for c in rep["corners"]:
        assert f"( {c['x']} {c['y']} ) {c['orient']} ;" in text


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





def test_the_module_docstring_does_not_carry_the_inert_claim():
    """THE WRONG CLAIM LIVED IN THE DOCSTRING, AND THAT IS WHERE IT WAS READ
    FROM. The record-level guard above watches the emitted JSON; nothing
    watched the prose, which is what a human opens and what the "it is inert"
    conclusion was reported upward from.

    A wrong claim that a knob is inert is worse than a missing one: it tells
    the next author the parameter cannot matter, so nobody varies it again.
    This test fails if any of the four shipped sentences returns to either
    module, and fails if the retraction that replaced them is deleted."""
    for mod in (GEN, PR):
        src = Path(mod.__file__).read_text()
        for claim in RETRACTED_CLAIMS:
            assert claim not in src, (
                f"{Path(mod.__file__).name} carries the retracted claim "
                f"{claim!r}; -rotation_vertical moves the S/N rows, so the "
                f"placer does read PAD_ROTATION_VERTICAL")
    # and the retraction is stated, not silently substituted: a reader who
    # believed the old sentence has to be able to see it withdrawn.
    prose = " ".join(GEN.__doc__.split())
    assert 'THIS SECTION SAID "IS INERT"' in prose
    assert "AND BOTH WERE WRONG" in prose


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
    assert _gen(root) == 2
    rep, _ = CHK._unwrap(_report(root))
    assert f"{var}_NOT_HONOURED" in _rules(root)
    assert rep["missing_inputs"][0]["variables_absent"] == [var]
    assert var in rep["reason"]
    printed = capsys.readouterr().out
    assert f"{var}_NOT_HONOURED" in printed
    # BOTH halves, through the one shared vocabulary. An earlier draft of this
    # test left the `reason` assertion OUTSIDE the loop, so it re-used the
    # leaked loop variable and checked exactly one of the four claims against
    # exactly one of the two texts. Planting `placer ignores it` in the emitted
    # reason passed it 3/3.
    _assert_no_retracted_claim(printed, "the console line")
    _assert_no_retracted_claim(rep["reason"], "the refusal reason")




# --------------------------------------------------------------------------- #
# a refuted finding must lose its identifier
# --------------------------------------------------------------------------- #
def test_the_report_key_does_not_assert_the_refuted_premise(placed):
    """`PAD_ROTATION_VERTICAL` is NOT inert; it steers the SOUTH and NORTH rows,
    and this step does not implement it. The distinction is not cosmetic: the
    old key `rotation_vertical_inert` asserted the refuted proposition IN THE
    SCHEMA, where every consumer keys on it and none of them reads the
    retraction published elsewhere."""
    rep, _ = CHK._unwrap(_report(placed))
    assert "rotation_vertical_not_honoured" in rep, sorted(rep)
    assert "rotation_vertical_inert" not in rep, (
        "the report still carries a key asserting the variable is inert")
    rec = rep["rotation_vertical_not_honoured"]
    assert rec["honoured"] is False
    assert "does not implement it" in rec["reason"], rec["reason"]
    assert "the placer does not read it" not in rec["reason"], (
        "the reason still says the tool ignores the variable, which is the "
        "claim that was measured false")






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
    src = (PROGRAMS / "pad_ring_gen.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and "INERT" in node.id.upper():
            offenders.append(f"name: {node.id}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)) and "inert" in node.name.lower():
            offenders.append(f"def: {node.name}")
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and "inert" in k.value.lower()):
                    offenders.append(f"schema key: {k.value!r}")
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
    assert _gen(root) == 0
    # the good path passes, so the refusal below is the rule firing and not
    # the fixture being broken
    assert _chk(root) == 0
    rep, _ = CHK._unwrap(_report(root))
    if kind == "pad":
        entry = next(p for p in rep["pads"] if p["side"] == "N")
    else:
        entry = next(c for c in rep["corners"] if c["position"] == "SE")
    assert entry["orient"] == was

    # PREMISE: the swap is invisible to every extent-based check in the gate.
    size = (75.0, 350.0) if kind == "pad" else (355.0, 355.0)
    assert PR.footprint(size, was, UNITS) == PR.footprint(size, now, UNITS), (
        f"premise: {was} and {now} must share a bounding box, or this test "
        f"would be proving the footprint check rather than the orientation one")

    line = _line(root, entry["instance"])
    assert line.rstrip().endswith(f"{was} ;")
    _edit_def(root, line, line.rsplit(" ", 2)[0] + f" {now} ;")
    assert _chk(root) == 1
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
    assert cited in GEN.__doc__, "the cross-reference was dropped"
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
