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
1. `opensta.Section.spef` was parsed off the dialect-B banner
   (`=== SETUP corner: process=SS liberty=…, SPEF=<top>.max.spef ===`)
   and NEVER READ by `_ppa.timing`. The corner was in the artefact, in a field
   the backend already had, and the extractor threw it away.
2. The whole-file `STA_BASIS_SPEF:` stamp — which two of this runner's STA
   emitters already write — had no regex in the backend at all.
3. `_emit_spef_sta` stamped `STA_SIGNOFF_CORNER` (the PROCESS axis) and not the
   parasitics it read, so the one axis on which it differs from
   `sta_mcorner_ocv.rpt` was the one axis it did not state. Its own comment
   said it was stamping "what it timed".

And the gap the extractor wrote in place of the corner was FALSE: "this report
names no RC corner for the section", on a section whose banner names
`SPEF=<top>.max.spef`.

WHAT IS ASSERTED
================
The harm (identity), both dialects (establishment), the refusal to guess
(`<top>.spef` establishes NOTHING — a corner is not inferred from a file name
that does not carry one), the honesty of the gap, and the runner's stamp.
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
STA_SIGNOFF_CORNER_COUNT: 1
"""

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
    """The four refused records, in one assertion.

    RED before the fix: both rows carry no RC corner, collide on
    `(timing.setup.worst_slack_ns, scope_digest)` and the index refuses the
    second as CONFLICTING_RECORD.
    """
    proj = _project(tmp_path, {
        "sta_mcorner_ocv.rpt": MCORNER % {"lib": _LIB, "spef": "dut.max.spef"},
        "sta_spef_based.rpt": SINGLE % {"lib": _LIB, "spef": "dut.min.spef"},
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


def test_the_same_two_reports_that_name_no_parasitics_still_conflict(tmp_path):
    """POSITIVE CONTROL. Strike the SPEF out of both artefacts and the conflict
    comes back — so the test above is exercising the axis, not a fixture that
    happens to differ some other way. An artefact that states nothing about its
    parasitics has NOT become comparable; it has stayed unreadable, and the
    index is right to refuse it."""
    proj = _project(tmp_path, {
        "sta_mcorner_ocv.rpt": MCORNER_UNNAMED % {"lib": _LIB},
        "sta_spef_based.rpt": SINGLE_UNNAMED % {"lib": _LIB},
    })
    rows, _notes = timing.timing_rows(proj)
    _idx, codes = _index(rows)
    assert "CONFLICTING_RECORD" in codes, (
        "two unreadable views were quietly indexed as one fact")


# ───────────────────────────── ESTABLISHMENT, BOTH DIALECTS ────────────────

def test_the_rc_corner_a_section_banner_names_is_established(tmp_path):
    """Dialect B. `Section.spef` existed and nothing read it."""
    proj = _project(tmp_path, {
        "sta_mcorner_ocv.rpt": MCORNER % {"lib": _LIB, "spef": "dut.max.spef"}})
    rows, _notes = timing.timing_rows(proj)
    got = {r["scope"].get("rc_corner") for r in rows
           if r["metric"] == "timing.setup.worst_slack_ns"}
    assert got == {"max"}, (
        "the banner names SPEF=dut.max.spef and the row's RC corner is %r"
        % (got,))
    for r in rows:
        assert "rc_corner" not in (r.get("scope_gaps") or {}), (
            "an ESTABLISHED key must not also be explained as absent")


def test_the_whole_file_spef_stamp_is_read_for_the_unbannered_dialect(
        tmp_path):
    """Dialect C. The stamp two of this runner's emitters already wrote had no
    reader; a report that spelled out its parasitics was still unreadable."""
    assert opensta.parse_report(
        SINGLE % {"lib": _LIB, "spef": "dut.nom.spef"}).basis_spef \
        == "dut.nom.spef"
    proj = _project(tmp_path, {
        "sta_spef_based.rpt": SINGLE % {"lib": _LIB, "spef": "dut.nom.spef"}})
    rows, _notes = timing.timing_rows(proj)
    got = {r["scope"].get("rc_corner") for r in rows
           if r["metric"] == "timing.setup.worst_slack_ns"}
    assert got == {"nom"}


# ─────────────────────────────── THE REFUSAL TO GUESS ──────────────────────

@pytest.mark.parametrize("spef", ["dut.spef", "dut.pnr.spef", "dut.MAXX.spef"])
def test_a_corner_is_not_invented_from_a_name_that_does_not_carry_one(
        tmp_path, spef):
    """`<top>.spef` is what the single-corner step really reads, and its
    extraction model is not stated anywhere in the name. Reading a corner out
    of it would be the invented identity `scope` exists to prevent — and an
    open "whatever sits before .spef" rule would mint an RC corner called
    `pnr`. The vocabulary is the closed set the extraction step emits."""
    proj = _project(tmp_path, {
        "sta_spef_based.rpt": SINGLE % {"lib": _LIB, "spef": spef}})
    rows, _notes = timing.timing_rows(proj)
    for r in rows:
        assert "rc_corner" not in r["scope"], (
            "a corner was invented from %r" % spef)
        gap = (r.get("scope_gaps") or {}).get("rc_corner")
        assert gap, "an absent key with no reason is the sentinel moved one field over"
        assert spef in gap, (
            "the gap must name the parasitic file the report DID state, so a "
            "reader can see which extraction is unaccounted for: %r" % gap)


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

    named = _gap(("named", SINGLE % {"lib": _LIB, "spef": "dut.spef"}))
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
    # …and the stamp it writes must be the one the reader parses.
    assert opensta.parse_report(
        "worst slack max 1.00\nSTA_BASIS_SPEF: %s.spef\n" % top
    ).basis_spef == "%s.spef" % top
