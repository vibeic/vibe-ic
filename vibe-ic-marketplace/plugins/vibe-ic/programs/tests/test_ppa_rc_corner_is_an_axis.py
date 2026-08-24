#!/usr/bin/env python3
"""Two STA reports timed against DIFFERENT parasitics are two facts, not one.

MEASURED DEFECT (`_gf180b_priv/work/spm_core`, `…/spm_chip`, 2026-08-22)
=======================================================================
`PPA measurement coverage` refused four records as CONFLICTING_RECORD::

    timing.setup.worst_slack_ns  13.83 from phase3/stage3/sta/sta_mcorner_ocv.rpt
                                 15.29 from phase3/stage3/sta/sta_spef_based.rpt

Read as a disagreement between two sign-off reports, that is unsettleable —
nothing in the tree ranks one STA report over the other. It is not one. The two
runs read DIFFERENT parasitic files:

    sta_mcorner_ocv_setup.tcl   read_spef …/extracted/spef_corners/<top>.max.spef
    sta_spef_setup.tcl          read_spef …/extracted/<top>.spef

Same liberty, same netlist, same SDC, same derate; different RC extraction. A
max-RC slack IS worse than a nominal-RC one — that is what the extra coupling
capacitance is — so 13.83 and 15.29 never contradicted each other. They were
made to look like a contradiction because `scope.rc_corner` was left
unestablished on both, and two records that could not state their RC corner
compared as records taken at the SAME RC corner. That is §6.1's sentinel one
level out: the harm survives spelling the absence correctly, because the axis
itself was never read.

WHY IT WAS UNREADABLE, IN THREE PLACES
--------------------------------------
1. The report named a SPEF path but carried no explicit RC-corner fact. A path
   is not evidence of the extraction model that produced its bytes.
2. The OpenSTA parser schema had no field for a producer-written corner.
3. The timing consumer therefore had nothing safe to place in
   `scope.rc_corner`; deriving `max` from `<top>.max.spef` would only turn a
   naming convention into a fabricated measurement identity.

WHAT IS ASSERTED
================
The harm (identity), both dialects (establishment), the refusal to guess from
any filename, preservation and rejection of contradictory explicit stamps,
the documented repeated-stamp rule, fail-closed malformed/missing stamps, the
honesty of a missing-stamp gap, and the runner's stamp.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
from _ppa import metrics                        # noqa: E402
from _ppa import timing                         # noqa: E402
from _ppa.backends import opensta               # noqa: E402

_LIB = "/pdks/x_fd_sc_hd__ss_100C_1v60.lib"

#: Dialect B, as `_emit_mcorner_ocv_sta` writes it: the banner names the
#: parasitic file, and `%s` is the only thing that varies between the two
#: fixtures below.
MCORNER = """\
=== SETUP corner: process=SS liberty=%(lib)s, SPEF=%(spef)s ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: %(lib)s
STA_BASIS_NETLIST: dut_pnr.v
STA_BASIS_SPEF: %(spef)s
STA_BASIS_CORNER: %(corner)s
worst slack max 13.83
tns max 0.00
"""

#: Dialect B with the parasitic file struck out of BOTH the banner and the
#: stamp — the artefact as it looked to a reader before this fix could use it.
MCORNER_UNNAMED = """\
=== SETUP corner: process=SS liberty=%(lib)s ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: %(lib)s
worst slack max 13.83
tns max 0.00
"""

#: Dialect C: no banner at all, so the parasitics can only be stated whole-file.
SINGLE = """\
tns max 0.00
wns max 0.00
worst slack max 15.29
STA_BASIS: POST_ROUTE_SPEF
STA_SIGNOFF_CORNER: SS
STA_BASIS_LIBERTY: %(lib)s
STA_BASIS_SPEF: %(spef)s
STA_BASIS_CORNER: %(corner)s
STA_SIGNOFF_CORNER_COUNT: 1
"""

SINGLE_UNSTAMPED = SINGLE.replace("STA_BASIS_CORNER: %(corner)s\n", "")

SINGLE_UNNAMED = """\
tns max 0.00
wns max 0.00
worst slack max 15.29
STA_BASIS: POST_ROUTE_SPEF
STA_SIGNOFF_CORNER: SS
STA_BASIS_LIBERTY: %(lib)s
STA_SIGNOFF_CORNER_COUNT: 1
"""


def _project(tmp_path, reports):
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    for name, body in reports.items():
        (sta / name).write_text(body)
    return tmp_path


def _index(rows):
    """The gate's own two seams, in the gate's own order. Returns the refusal
    codes, so a test can say WHICH refusal it does or does not want."""
    idx = metrics.MetricIndex()
    codes = []
    for row in rows:
        rec = dict(row)
        errs = metrics.validate(rec)
        if errs:
            codes.extend(code for code, _msg in errs)
            continue
        try:
            idx.add(rec)
        except metrics.MetricError as exc:
            codes.append(exc.code)
    return idx, codes


def _setup_slacks(rows):
    return sorted(r["value"] for r in rows
                  if r["metric"] == "timing.setup.worst_slack_ns"
                  and r["status"] == "MEASURED")


# ─────────────────────────── THE HARM, AND ITS POSITIVE CONTROL ────────────

def test_two_reports_timed_against_different_parasitics_are_not_one_identity(
        tmp_path):
    """The formerly refused records survive under producer-stamped corners."""
    proj = _project(tmp_path, {
        "sta_mcorner_ocv.rpt": MCORNER % {
            "lib": _LIB, "spef": "dut.spef", "corner": "max"},
        "sta_spef_based.rpt": SINGLE % {
            "lib": _LIB, "spef": "dut.spef", "corner": "min"},
    })
    rows, _notes = timing.timing_rows(proj)
    idx, codes = _index(rows)

    assert "CONFLICTING_RECORD" not in codes, (
        "a max-RC slack and a min-RC slack were called a contradiction. They "
        "are two facts; the RC corner each report NAMES is what tells them "
        "apart, and it was thrown away. codes=%r" % (codes,))
    assert "SAME_ARTEFACT_TWO_VALUES" not in codes

    kept = [r for r in idx if r["metric"] == "timing.setup.worst_slack_ns"]
    assert len(kept) == 2, (
        "both readings must survive: settling this by keeping one would be "
        "picking a winner between measurements that never disagreed")
    assert sorted(r["value"] for r in kept) == [13.83, 15.29]
    assert sorted(r["scope"]["rc_corner"] for r in kept) == ["max", "min"]


#: The control below must differ in ONE variable. `MCORNER_UNNAMED` stamps
#: `OCV_DERATE_APPLIED` and `SINGLE_UNNAMED` does not, which did not matter
#: while the derating stance was outside `scope` -- and became the whole answer
#: the moment it went in (2026-08-25): the pair stopped conflicting for a
#: reason that has nothing to do with parasitics, and the control silently
#: stopped controlling. The fixture below holds the stance EQUAL so the RC
#: corner is the only thing left unread.
#:
#: MEASURED, because a control that is not itself controlled is a comment.
#: Striking `rc_corner` out of `_scope`'s output kills 4 of this file's 22
#: tests -- `test_two_reports_timed_against_different_parasitics_are_not_one_
#: identity` and the three establishment arms -- and this control is NOT among
#: them, which is correct: REMOVING an axis can only make more things collide,
#: so a test that asserts a collision cannot detect that loss. The harm test is
#: what catches it; this one exists so the harm test's pass cannot come from a
#: confound, and it can only do that job while the two fixtures differ in one
#: variable.
_SINGLE_UNNAMED_DERATED = (
    "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n" + SINGLE_UNNAMED)


def test_the_same_two_reports_that_name_no_parasitics_still_conflict(tmp_path):
    """POSITIVE CONTROL. Strike the SPEF out of both artefacts and the conflict
    comes back — so the test above is exercising the axis, not a fixture that
    happens to differ some other way. An artefact that states nothing about its
    parasitics has NOT become comparable; it has stayed unreadable, and the
    index is right to refuse it."""
    proj = _project(tmp_path, {
        "sta_mcorner_ocv.rpt": MCORNER_UNNAMED % {"lib": _LIB},
        "sta_spef_based.rpt": _SINGLE_UNNAMED_DERATED % {"lib": _LIB},
    })
    rows, _notes = timing.timing_rows(proj)
    _idx, codes = _index(rows)
    assert "CONFLICTING_RECORD" in codes, (
        "two unreadable views were quietly indexed as one fact")


# ───────────────────────────── ESTABLISHMENT, BOTH DIALECTS ────────────────

def test_a_section_corner_is_read_from_the_explicit_stamp_not_the_spef_name(
        tmp_path):
    """Dialect B: an opaque filename still gets the producer-stamped corner."""
    proj = _project(tmp_path, {
        "sta_mcorner_ocv.rpt": MCORNER % {
            "lib": _LIB, "spef": "dut.spef", "corner": "max"}})
    rows, _notes = timing.timing_rows(proj)
    setup = [r for r in rows if r["metric"] == "timing.setup.worst_slack_ns"]
    assert setup, "fixture produced no setup row"
    for r in setup:
        assert r["scope"]["rc_corner"] == "max"
        assert "rc_corner" not in (r.get("scope_gaps") or {})


def test_a_corner_is_not_invented_from_a_banner_name_that_DOES_carry_a_token(
        tmp_path):
    """Preserve the old guard: a suggestive SPEF name is still not a fact.

    Batch73 adds an explicit ``STA_BASIS_CORNER`` producer contract.  Removing
    that contract from this fixture must leave ``dut.max.spef`` unreadable as a
    corner, even though the filename contains the token the producer would
    otherwise stamp explicitly.
    """
    body = (MCORNER % {
        "lib": _LIB, "spef": "dut.max.spef", "corner": "max"
    }).replace("STA_BASIS_CORNER: max\n", "")
    proj = _project(tmp_path, {"sta_mcorner_ocv.rpt": body})
    rows, _notes = timing.timing_rows(proj)
    setup = [r for r in rows if r["metric"] == "timing.setup.worst_slack_ns"]
    assert setup, "fixture produced no setup row"
    for row in setup:
        assert "rc_corner" not in row["scope"]
        assert "dut.max.spef" in (
            (row.get("scope_gaps") or {}).get("rc_corner") or "")


def test_the_whole_file_corner_stamp_establishes_the_corner(
        tmp_path):
    """Dialect C has no banner; both path and corner come from file stamps."""
    parsed = opensta.parse_report(SINGLE % {
        "lib": _LIB, "spef": "dut.spef", "corner": "nom"})
    assert parsed.basis_spef == "dut.spef"
    assert parsed.basis_corners == ("nom",)
    proj = _project(tmp_path, {
        "sta_spef_based.rpt": SINGLE % {
            "lib": _LIB, "spef": "dut.spef", "corner": "nom"}})
    rows, _notes = timing.timing_rows(proj)
    setup = [r for r in rows if r["metric"] == "timing.setup.worst_slack_ns"]
    assert setup, "fixture produced no setup row"
    for r in setup:
        assert r["scope"]["rc_corner"] == "nom"
        assert "rc_corner" not in (r.get("scope_gaps") or {})


def test_the_whole_file_spef_stamp_is_read_but_does_not_establish_the_corner(
        tmp_path):
    """The path stamp remains readable but cannot replace the corner stamp."""
    body = SINGLE_UNSTAMPED % {
        "lib": _LIB, "spef": "dut.nom.spef", "corner": "unused"}
    parsed = opensta.parse_report(body)
    assert parsed.basis_spef == "dut.nom.spef"
    proj = _project(tmp_path, {"sta_spef_based.rpt": body})
    rows, _notes = timing.timing_rows(proj)
    setup = [r for r in rows if r["metric"] == "timing.setup.worst_slack_ns"]
    assert setup, "fixture produced no setup row"
    for row in setup:
        assert "rc_corner" not in row["scope"]
        assert "dut.nom.spef" in (
            (row.get("scope_gaps") or {}).get("rc_corner") or "")


# ─────────────────────────────── THE REFUSAL TO GUESS ──────────────────────

@pytest.mark.parametrize(
    "spef", ["dut.spef", "dut.pnr.spef", "dut.max.spef", "dut.MAXX.spef"])
def test_a_missing_corner_stamp_is_not_recovered_from_any_spef_name(
        tmp_path, spef):
    """`<top>.spef` is what the single-corner step really reads, and its
    extraction model is not stated anywhere in the name. Reading a corner out
    of it would be the invented identity `scope` exists to prevent — and an
    open "whatever sits before .spef" rule would mint an RC corner called
    `pnr`. The vocabulary is the closed set the extraction step emits."""
    proj = _project(tmp_path, {
        "sta_spef_based.rpt": SINGLE_UNSTAMPED % {
            "lib": _LIB, "spef": spef, "corner": "unused"}})
    rows, _notes = timing.timing_rows(proj)
    for r in rows:
        assert "rc_corner" not in r["scope"], (
            "a corner was invented from %r" % spef)
        gap = (r.get("scope_gaps") or {}).get("rc_corner")
        assert gap, "an absent key with no reason is the sentinel moved one field over"
        assert spef in gap, (
            "the gap must name the parasitic file the report DID state, so a "
            "reader can see which extraction is unaccounted for: %r" % gap)


@pytest.mark.parametrize("spef", ["dut.spef", "dut.pnr.spef", "dut.MAXX.spef"])
def test_a_corner_is_not_invented_from_a_name_that_does_not_carry_one(
        tmp_path, spef):
    """Retain the pre-Batch73 node IDs while exercising the new contract."""
    proj = _project(tmp_path, {
        "sta_spef_based.rpt": SINGLE_UNSTAMPED % {
            "lib": _LIB, "spef": spef, "corner": "unused"}})
    rows, _notes = timing.timing_rows(proj)
    assert rows, "fixture produced no timing rows"
    for row in rows:
        assert "rc_corner" not in row["scope"]
        gap = (row.get("scope_gaps") or {}).get("rc_corner") or ""
        assert spef in gap, gap


def test_a_wrong_corner_stamp_is_rejected_instead_of_picking_a_side(tmp_path):
    """The banner and common stamp are two explicit claims; disagreement
    invalidates the measurement rather than publishing either identity."""
    body = """\
=== SETUP (max-RC corner, SPEF=opaque, liberty=%s) ===
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_CORNER: min
worst slack max 1.00
tns max 0.00
""" % _LIB
    proj = _project(tmp_path, {"sta_spef_multicorner.rpt": body})
    rows, _notes = timing.timing_rows(proj)
    setup = [r for r in rows if r["metric"].startswith("timing.setup.")]
    assert setup, "fixture produced no setup rows"
    assert all(r["status"] == "INVALID" for r in setup), setup
    assert all("rc_corner" not in r["scope"] for r in setup)
    assert all("RC_CORNER_CONTRADICTION" in r["reason"] for r in setup)


@pytest.mark.parametrize(
    "first,second", [("max", "min"), ("min", "max")])
def test_conflicting_explicit_corner_declarations_are_all_preserved_and_rejected(
        tmp_path, first, second):
    """Regression control for first-value-wins, in both source orders."""
    body = (SINGLE % {
        "lib": _LIB, "spef": "opaque.spef", "corner": first
    }).replace(
        "STA_BASIS_CORNER: %s\n" % first,
        "STA_BASIS_CORNER: %s\nSTA_BASIS_CORNER: %s\n" % (first, second))
    parsed = opensta.parse_report(body)
    report_declarations = getattr(parsed, "basis_corners", None)
    if report_declarations is None:
        report_declarations = (getattr(parsed, "basis_corner", None),)
    section_declarations = getattr(
        parsed.sections[0], "basis_corners", None)
    if section_declarations is None:
        section_declarations = (
            getattr(parsed.sections[0], "basis_corner", None),)
    assert report_declarations == (first, second), (
        "the parser reduced contradictory declarations before the consumer "
        "could reject them")
    assert section_declarations == (first, second)

    proj = _project(tmp_path, {"sta_spef_based.rpt": body})
    rows, _notes = timing.timing_rows(proj)
    assert rows, "fixture produced no timing rows"
    assert all(r["status"] == "INVALID" for r in rows), rows
    assert all("rc_corner" not in r["scope"] for r in rows)
    assert all("RC_CORNER_CONTRADICTION" in r["reason"] for r in rows)
    assert all(first in r["reason"] and second in r["reason"] for r in rows)


def test_repeated_identical_corner_declarations_have_one_identity(tmp_path):
    """The producer contract permits redundant, semantically equal stamps."""
    body = (SINGLE % {
        "lib": _LIB, "spef": "opaque.spef", "corner": "max"
    }).replace(
        "STA_BASIS_CORNER: max\n",
        "STA_BASIS_CORNER: max\nSTA_BASIS_CORNER: MAX\n")
    parsed = opensta.parse_report(body)
    assert parsed.basis_corners == ("max", "MAX")

    proj = _project(tmp_path, {"sta_spef_based.rpt": body})
    rows, _notes = timing.timing_rows(proj)
    assert rows and all(r["status"] != "INVALID" for r in rows), rows
    assert all(r["scope"]["rc_corner"] == "max" for r in rows)


@pytest.mark.parametrize("malformed", ["", "maximum"])
def test_a_malformed_explicit_corner_declaration_is_invalid(
        tmp_path, malformed):
    """An explicit but unreadable declaration is not treated as absent."""
    body = SINGLE % {
        "lib": _LIB, "spef": "dut.max.spef", "corner": malformed}
    parsed = opensta.parse_report(body)
    assert parsed.basis_corners == (malformed,)

    proj = _project(tmp_path, {"sta_spef_based.rpt": body})
    rows, _notes = timing.timing_rows(proj)
    assert rows and all(r["status"] == "INVALID" for r in rows), rows
    assert all("rc_corner" not in r["scope"] for r in rows)
    assert all("unsupported RC corner" in r["reason"] for r in rows)


def test_a_report_that_named_its_parasitics_is_not_told_it_named_nothing(
        tmp_path):
    """The pre-fix sentence — "this report names no RC corner for the section;
    the RC axis is reported by the multi-corner SPEF report, not this one" —
    was ONE sentence for two different situations, and false on the artefact
    that founded this defect. "I read `dut.spef` and its name carries no corner
    token" and "I cannot tell you what I read" are not the same gap: the first
    points a reader at a file to go and identify, the second at nothing. A gap
    that misdescribes the artefact is worse than no gap, because it tells a
    reader to stop looking in the place the answer is."""
    def _gap(body):
        proj = _project(tmp_path / body[0], {"sta_spef_based.rpt": body[1]})
        rows, _notes = timing.timing_rows(proj)
        gaps = {(r.get("scope_gaps") or {}).get("rc_corner") for r in rows}
        gaps.discard(None)
        assert len(gaps) == 1, gaps
        return gaps.pop()

    named = _gap(("named", SINGLE_UNSTAMPED % {
        "lib": _LIB, "spef": "dut.spef", "corner": "unused"}))
    silent = _gap(("silent", SINGLE_UNNAMED % {"lib": _LIB}))

    assert named != silent, (
        "one sentence explains both a report that named its parasitic file and "
        "one that named nothing:\n  %r" % named)
    assert "dut.spef" in named
    assert "dut.spef" not in silent


# ─────────────────────────────── THE PRODUCER'S STAMP ──────────────────────

_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_rcaxis", _PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

CONTAINER = "test-container-no-such-container"


@pytest.fixture()
def _no_docker(monkeypatch):
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])
    monkeypatch.setattr(p3, "_discover_aocv_table", lambda *a, **k: None)

    def _fake_exec(container, cmd, *a, **k):
        for out in (k.get("outputs") or []):
            pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(out).write_text("worst slack max 1.00\ntns max 0.00\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


def test_the_single_corner_sta_step_stamps_the_parasitics_it_read(
        tmp_path, _no_docker):
    """RED pre-fix: `_emit_spef_sta` stamped the PROCESS corner and not the RC
    one, so the axis on which it differs from its sibling emitter was the one
    it left unstated."""
    top = "dut"
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / f"{top}_pnr.v").write_text(f"module {top}(); endmodule\n")
    (pnr / "constraint.sdc").write_text(
        "create_clock -period 10 [get_ports clk]\n")
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    spef = ext / f"{top}.spef"
    spef.write_text("*SPEF \"IEEE 1481-1998\"\n")
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    (libdir / "cellib_ss.lib").write_text("library (l) { }\n")
    pdk = p3.PdkConfig(
        name="testpdk", liberty=str(libdir / "cellib_ss.lib"),
        tech_lef=str(tmp_path / "tech.lef"),
        cell_lef=str(tmp_path / "cell.lef"), cell_gds=None,
        site="unit", drc_deck=None)
    rpt = tmp_path / "phase3" / "stage3" / "sta" / "sta_spef_based.rpt"
    notes: list = []
    p3._emit_spef_sta(tmp_path, top, pdk, CONTAINER, spef, rpt, notes)
    tcl = (rpt.parent / "sta_spef_based.tcl").read_text()

    assert "STA_BASIS_SPEF: %s.spef" % top in tcl, (
        "the step reads a parasitic file and does not say which; its sibling "
        "`_emit_mcorner_ocv_sta` does, and the difference between the two "
        "reports is exactly that file:\n%s" % tcl)
    assert "STA_BASIS_CORNER: nom" in tcl, (
        "the single-corner extraction selected the nominal RC model but the "
        "STA report did not record that producer-known role:\n%s" % tcl)
    # …and the stamp it writes must be the one the reader parses.
    parsed = opensta.parse_report(
        "worst slack max 1.00\nSTA_BASIS_SPEF: %s.spef\n"
        "STA_BASIS_CORNER: nom\n" % top)
    assert parsed.basis_spef == "%s.spef" % top
    assert parsed.basis_corners == ("nom",)


def test_the_aging_sta_step_stamps_the_selected_max_corner(
        tmp_path, _no_docker, monkeypatch):
    top = "dut"
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / f"{top}_pnr.v").write_text(f"module {top}(); endmodule\n")
    (pnr / "constraint.sdc").write_text(
        "create_clock -period 10 [get_ports clk]\n")
    ext = tmp_path / "phase3" / "stage3" / "extracted" / "spef_corners"
    ext.mkdir(parents=True)
    (ext / f"{top}.max.spef").write_text("*SPEF \"IEEE 1481-1998\"\n")
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    lib = libdir / "cellib_ss.lib"
    lib.write_text("library (l) { }\n")
    pdk = p3.PdkConfig(
        name="testpdk", liberty=str(lib), tech_lef=str(tmp_path / "tech.lef"),
        cell_lef=str(tmp_path / "cell.lef"), cell_gds=None,
        site="unit", drc_deck=None)
    rpt = tmp_path / "reports" / "phase3" / "aging_sta.rpt"
    out_json = rpt.with_suffix(".json")

    def _write_report(*args, **kwargs):
        rpt.parent.mkdir(parents=True, exist_ok=True)
        rpt.write_text("worst slack max 1.00\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _write_report)
    assert p3._emit_aging_sta_report(
        tmp_path, top, pdk, CONTAINER, rpt, out_json, [])
    tcl = (rpt.parent / f"aging_sta_{top}.tcl").read_text()
    assert "STA_BASIS_CORNER: max" in tcl
    assert "STA_BASIS_CORNER: max" in rpt.read_text()
    assert json.loads(out_json.read_text())["sta_basis_corner"] == "max"
