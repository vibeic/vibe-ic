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




# ───────────────────────────── ESTABLISHMENT, BOTH DIALECTS ────────────────









# ─────────────────────────────── THE REFUSAL TO GUESS ──────────────────────















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
