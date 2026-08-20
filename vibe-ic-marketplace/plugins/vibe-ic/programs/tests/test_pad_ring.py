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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _pad_ring as PR            # noqa: E402
import pad_ring_check as CHK      # noqa: E402
import pad_ring_gen as GEN        # noqa: E402

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
        "PAD_ROTATION_VERTICAL": "R90",
        "PAD_ROTATION_CORNER": "R0",
        "PAD_CORNER": "pad_corner",
        "PAD_FILLERS": ["pad_fill1"],
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


def test_the_spacing_is_upstreams_arithmetic(placed):
    """Steps 1-7 of their numbered algorithm, on the fixture's numbers:
    side 1_280_000, pads 4x75_000, fill 980_000, spacing 196_000, and the
    pad-to-corner spacing 196_000 — every gap a whole number of site widths."""
    rep, _ = CHK._unwrap(_report(placed))
    gaps = rep["abutment"]["gaps"]
    assert all(g == 196_000 for side in gaps for g in gaps[side]), gaps
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
    assert rep["fillers_placed"] is None, (
        "0 would read as `no fillers were needed`")
    assert "io_filler_placement" in rep["unperformed"]
    assert rep["fillers_declared"] == ["pad_fill1"]


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
    """The gap becomes 195_500 DEF units, which no whole number of 1_000 unit
    filler cells closes. Nothing about the PLACEMENT is wrong — the pad is on
    its side, inside the die, the right master, the right size, and it does
    not overlap. Only the abutment walk sees it."""
    _edit_def(placed, _line(placed, "pad_ssig1"),
              "- pad_ssig1 pad_bidir + FIXED ( 826500 10000 ) N ;")
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
def test_the_flow_declares_this_step_with_this_producer_and_this_gate():
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(FLOW.read_text())["steps"]
    step = next(s for s in steps if str(s["id"]) == "15.5ic")
    assert step["programs"] == ["pad_ring_gen"]
    assert step["gate"]["program_exit_zero"] == (
        "pad_ring_check . --json reports/phase3/padring.json")
    assert PR.PADRING_DEF_REL in step["required_outputs"]
    assert PR.REPORT_REL in step["required_outputs"]
    assert step["blocks_on"] == [15, "0.5ic"]


def test_the_step_runs_on_the_CHIP_PATH_and_not_on_the_operators_template():
    """The condition tests WHICH PATH, not whether a shuttle operator exists.

    A chip doing its own tape-out has no operator and therefore no
    `slots/*.yaml`; conditioning this step on that file skipped it silently for
    exactly the design that most needs a pad ring, because a die with no pads
    cannot be bonded or probed. Both of step 0.5ic's chip-path router files
    select this step; `NO_TEMPLATE.txt` — the IP/hardmacro terminal — must NOT,
    because an IP is delivered rather than fabricated.
    """
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(FLOW.read_text())["steps"]
    step = next(s for s in steps if str(s["id"]) == "15.5ic")
    cond = step["condition"]
    assert cond["any_of"] is True, (
        "without `any_of` the two entries are an AND, and 0.5ic's own gate "
        "refuses a tree carrying two router files at once — the step could "
        "then never run for any design")
    assert set(cond["files_exist"]) == {
        "input/submission_template/slots/*.yaml",
        "input/submission_template/SELF_TAPEOUT.txt"}
    assert not any("NO_TEMPLATE" in f for f in cond["files_exist"])
    assert step["condition_kind"] == "design_dependent"


# --------------------------------------------------------------------------- #
# chip-agnosticism
# --------------------------------------------------------------------------- #
_OURS = ("_pad_ring.py", "pad_ring_gen.py", "pad_ring_check.py",
         "tests/test_pad_ring.py")


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
    _edit_def(placed, _line(placed, "pad_ssig1"),
              "- pad_ssig1 pad_bidir + FIXED ( 826500 10000 ) N ;")
    mut = _mutant(tmp_path, "pad_ring_check.py",
                  "not PR.gap_is_fillable(gap, filler_widths)",
                  "False")
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
