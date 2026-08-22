#!/usr/bin/env python3
"""The two MULTI-CORNER sign-off STA reports carried no `STA_BASIS` stamp.

MEASURED DEFECT
===============
`grep -n 'puts .*STA_BASIS' phase3_one_shot_runner.py`, before this fix:

    _emit_spef_sta        (SINGLE corner)            ->  STA_BASIS: POST_ROUTE_SPEF
    _emit_multi_corner_sta (per-corner pre-layout)   ->  STA_BASIS: {basis}
    the aging report                                 ->  STA_BASIS: {basis}
    _emit_corner_spef_sta  -> sta_spef_multicorner.rpt   ->  0 occurrences
    _emit_mcorner_ocv_sta  -> sta_mcorner_ocv.rpt        ->  0 occurrences

The one report that discloses its stage is the SINGLE-corner one. The two
MULTI-CORNER SIGN-OFF reports — the ones carrying the actual sign-off corners,
setup at the slow corner and hold at the fast one — disclosed nothing.

`_ppa/timing.py::_stage_for` therefore emitted `scope.stage = null` for every
row it parsed out of them, with the reason `"report carries no STA_BASIS
stamp"` recorded, rather than inferring a stage from the filename — inferring
would let a pre-layout estimate be compared against sign-off evidence the
moment a pre-layout report lands in the same directory. Degrading loudly is
correct, and it is not free: on one real run 48 of 56 timing rows were then
refused as SCOPE_INCOMPLETE and setup and hold both came back
FEAS_INCOMPLETE_VIEW_SET.

THE FIX BELONGS IN THE STEP'S OWN TOOL, not in the downstream reader: the
emitter is the only thing that knows which netlist, which liberty and which
SPEF each stanza read.

WHAT IS ASSERTED
================
1. FORWARD, both emitters (fails against the pre-fix file, which emits the
   string nowhere): every stanza stamps `STA_BASIS` and the liberty it read.
2. PER-STANZA TRUTH (fails pre-fix): in the process-corner report the SETUP
   stanza names the SLOW liberty and the HOLD stanza names the FAST one. A
   single file-level stamp copied from the single-corner emitter would name
   one liberty for two stanzas that read different ones.
3. THE SHIPPED READER ACCEPTS IT (fails pre-fix): the stamp each stanza emits
   resolves through `_sta_basis` — the ONE reader — to a real stage instead of
   `None`, so `_ppa/timing.py` stops recording the gap reason.
4. DERIVED, NOT LITERAL (fails pre-fix in the other direction): with no routed
   netlist on disk the stanzas stamp `PRE_LAYOUT_ESTIMATE`, never a sign-off
   basis they do not have.
5. NO-SPEF (fails pre-fix): a process-corner stanza that reads no SPEF stamps
   `POST_ROUTE_NO_SPEF`, which is a stage of its own in the reader's table.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_mcbasis", _PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

import _sta_basis  # noqa: E402  — the ONE reader of the stamp

CONTAINER = "test-container-no-such-container"
TOP = "dut"


def _mk_project(tmp_path: Path, *, routed: bool = True) -> Path:
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / f"{TOP}_synth.v").write_text(f"module {TOP}(); endmodule\n")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "constraint.sdc").write_text(
        "create_clock -period 10 [get_ports clk]\n")
    if routed:
        (pnr / f"{TOP}_pnr.v").write_text(f"module {TOP}(); endmodule\n")
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    for n in ("cellib_ss.lib", "cellib_typ.lib", "cellib_ff.lib"):
        (libdir / n).write_text("library (l) { }\n")
    return tmp_path


def _mk_pdk(tmp_path: Path) -> "p3.PdkConfig":
    libdir = tmp_path / "input" / "pdk" / "liberty"
    return p3.PdkConfig(
        name="testpdk", liberty=str(libdir / "cellib_typ.lib"),
        tech_lef=str(tmp_path / "tech.lef"),
        cell_lef=str(tmp_path / "cell.lef"),
        cell_gds=None, site="unit", drc_deck=None)


def _mk_spefs(tmp_path: Path, corners) -> dict:
    d = tmp_path / "phase3" / "stage3" / "extracted" / "spef_corners"
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    for c in corners:
        f = d / f"{TOP}.{c}.spef"
        f.write_text('*SPEF "IEEE 1481-1998"\n')
        out[c] = f
    return out


@pytest.fixture(autouse=True)
def _no_docker(monkeypatch):
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])

    def _fake_exec(container, cmd, *a, **k):
        for out in (k.get("outputs") or []):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text("worst slack max 1.00\ntns max 0.00\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


_PUTS = re.compile(r'puts \$_f "([^"]*)"')


def _report_body(tcl: str) -> str:
    """What these `puts $_f` commands will put in the report.

    The emitter's contract with the report is exactly this set of lines; the
    surrounding OpenSTA commands append their own output around them. Reading
    the payloads back is how the report body is checked without a tool run."""
    return "\n".join(_PUTS.findall(tcl))


def _emit_rc(tmp_path: Path, corners=("min", "max"), routed=True):
    proj = _mk_project(tmp_path, routed=routed)
    spefs = _mk_spefs(proj, corners)
    rpt = proj / "phase3" / "stage3" / "sta" / "sta_spef_multicorner.rpt"
    res = p3._emit_corner_spef_sta(proj, TOP, _mk_pdk(proj), CONTAINER,
                                   spefs, rpt, [], corner_libs=None)
    setup_tcl = (rpt.parent / "sta_spef_setup.tcl").read_text()
    hold_tcl = (rpt.parent / "sta_spef_hold.tcl").read_text()
    return res, setup_tcl, hold_tcl


def _emit_ocv(tmp_path: Path, *, with_spef=True, routed=True):
    proj = _mk_project(tmp_path, routed=routed)
    libdir = proj / "input" / "pdk" / "liberty"
    corner_libs = {"SS": str(libdir / "cellib_ss.lib"),
                   "FF": str(libdir / "cellib_ff.lib")}
    spefs = _mk_spefs(proj, ("min", "max")) if with_spef else {}
    rpt = proj / "phase3" / "stage3" / "sta" / "sta_mcorner_ocv.rpt"
    ran = p3._emit_mcorner_ocv_sta(proj, TOP, _mk_pdk(proj), CONTAINER,
                                   corner_libs, spefs, None, rpt, [])
    setup_tcl = (rpt.parent / "sta_mcorner_ocv_setup.tcl").read_text()
    hold_tcl = (rpt.parent / "sta_mcorner_ocv_hold.tcl").read_text()
    return ran, setup_tcl, hold_tcl


# ---------------------------------------------------------------- FORWARD ---
def test_rc_multicorner_report_declares_post_route_spef(tmp_path):
    """FAILS pre-fix: `sta_spef_multicorner.rpt` carried no stamp at all."""
    res, setup_tcl, hold_tcl = _emit_rc(tmp_path)
    assert res["ok"] is True
    for name, tcl in (("setup", setup_tcl), ("hold", hold_tcl)):
        body = _report_body(tcl)
        assert "STA_BASIS: POST_ROUTE_SPEF" in body, (
            f"the {name} stanza of the multi-corner SIGN-OFF report discloses "
            f"no stage, so every timing row parsed out of it is refused as "
            f"SCOPE_INCOMPLETE:\n{body}")
        assert "STA_BASIS_LIBERTY: " in body
        assert f"STA_BASIS_NETLIST: {TOP}_pnr.v" in body
        assert "STA_BASIS_SPEF: " in body


def test_ocv_process_corner_report_declares_post_route_spef(tmp_path):
    """FAILS pre-fix: `sta_mcorner_ocv.rpt` carried no stamp at all."""
    ran, setup_tcl, hold_tcl = _emit_ocv(tmp_path)
    assert ran is True
    for name, tcl in (("SETUP", setup_tcl), ("HOLD", hold_tcl)):
        body = _report_body(tcl)
        assert "STA_BASIS: POST_ROUTE_SPEF" in body, (
            f"the {name} stanza of the PROCESS-corner sign-off report "
            f"discloses no stage:\n{body}")


# ------------------------------------------------------- PER-STANZA TRUTH ---
def test_each_process_corner_stanza_names_the_liberty_it_read(tmp_path):
    """The reason the fix is not a copied literal.

    The two stanzas of the process-corner report read DIFFERENT libraries —
    slow for setup, fast for hold — so one file-level stamp would be wrong for
    one of them. FAILS pre-fix (no stamp), and would fail a copy-the-literal
    fix (one liberty for two stanzas)."""
    _, setup_tcl, hold_tcl = _emit_ocv(tmp_path)

    def _lib(tcl):
        m = re.search(r"STA_BASIS_LIBERTY: (\S+)", _report_body(tcl))
        assert m, f"no STA_BASIS_LIBERTY in:\n{_report_body(tcl)}"
        return Path(m.group(1)).name

    assert _lib(setup_tcl) == "cellib_ss.lib"
    assert _lib(hold_tcl) == "cellib_ff.lib"
    assert _lib(setup_tcl) != _lib(hold_tcl), (
        "the setup and hold stanzas read different process libraries; a stamp "
        "that names one liberty for both is a copied literal, not a reading"
    )
    # And each stanza's stamp agrees with the read_liberty it actually issues.
    for tcl, want in ((setup_tcl, "cellib_ss.lib"), (hold_tcl, "cellib_ff.lib")):
        reads = [ln.split()[-1] for ln in tcl.splitlines()
                 if ln.strip().startswith("read_liberty ")]
        assert reads and Path(reads[0]).name == want


# ------------------------------------------- THE SHIPPED READER ACCEPTS IT ---
def test_the_one_shipped_reader_resolves_both_reports_to_a_stage(tmp_path):
    """FAILS pre-fix: `declared_basis` returned None, which is `stage: null`
    plus a recorded gap reason, on both sign-off reports."""
    _, rc_setup, _ = _emit_rc(tmp_path / "rc")
    _, ocv_setup, _ = _emit_ocv(tmp_path / "ocv")
    for label, tcl in (("sta_spef_multicorner.rpt", rc_setup),
                       ("sta_mcorner_ocv.rpt", ocv_setup)):
        basis = _sta_basis.declared_basis(_report_body(tcl))
        assert basis == "POST_ROUTE", (
            f"{label} still reads as undeclared to the one shipped reader "
            f"(got {basis!r})")


# ----------------------------------------------------- DERIVED NOT LITERAL ---
def test_no_routed_netlist_is_not_stamped_as_signoff(tmp_path):
    """The fix must never CLAIM post-route. With no `<top>_pnr.v` the emitters
    fall back to the synth netlist — the pre-existing behaviour — and the
    stamp must say so."""
    _, rc_setup, _ = _emit_rc(tmp_path / "rc", routed=False)
    _, ocv_setup, _ = _emit_ocv(tmp_path / "ocv", routed=False)
    for label, tcl in (("rc", rc_setup), ("ocv", ocv_setup)):
        body = _report_body(tcl)
        assert "STA_BASIS: PRE_LAYOUT_ESTIMATE" in body, (label, body)
        assert "POST_ROUTE" not in body, (label, body)


def test_a_process_corner_stanza_with_no_spef_says_so(tmp_path):
    """FAILS pre-fix. `POST_ROUTE_NO_SPEF` is its own stage in the reader's
    table; collapsing it into `POST_ROUTE_SPEF` would claim parasitics that
    were never read."""
    _, setup_tcl, hold_tcl = _emit_ocv(tmp_path, with_spef=False)
    for tcl in (setup_tcl, hold_tcl):
        body = _report_body(tcl)
        assert "STA_BASIS: POST_ROUTE_NO_SPEF" in body, body
        assert "read_spef " not in tcl
