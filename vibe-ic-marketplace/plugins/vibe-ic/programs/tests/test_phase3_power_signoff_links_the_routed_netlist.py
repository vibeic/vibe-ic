#!/usr/bin/env python3
"""The Phase-3 power number was computed on the PRE-PnR netlist, and its own
header said it was not.

MEASURED DEFECT
===============
`_emit_power_report` is called twice: once for the Step-10 pre-layout preview
and once for the Step-33 sign-off power report. Both calls shared one body
that linked `<top>_synth.v`. So `reports/phase3/power.rpt` published a pre-PnR
figure under a generated header reading:

    # values reflect the post-PnR netlist + the typical-corner Liberty file

Measured on one real routed design, against a controlled re-measurement that
changed ONLY the netlist and added the extracted SPEF (same tool, same
liberty, same SDC, same vectorless activity basis):

    netlist        <top>_synth.v   287 instances   | <top>_pnr.v  3373, routed
    parasitics     none                            | <top>.spef
    total power    0.306 mW                        | 0.573 mW
    clock group    0.000 mW (0.0 %)                | 0.193 mW (33.7 %)

The shipped figure was 1.873x LOW and the clock tree — a third of real power —
reported as exactly zero, because the netlist it linked has no clock tree.

THE PROOF THAT MAKES IT UNDENIABLE
----------------------------------
Across a 60-configuration place-and-route sweep the shipped `power.rpt` was
BYTE-IDENTICAL 60/60 (one md5 over 60 files) while all 60 routed netlists and
all 60 SPEFs were distinct. No PnR knob can reach a pre-PnR netlist. A number
that cannot move when the thing it measures moves is not a measurement.

THE REMEDY IS THE SESSION, NOT THE HEADER
-----------------------------------------
Editing the header to say "pre-PnR" would make the document honest and leave
the sign-off measurement useless. So the sign-off call now asks for
`basis="post_pnr"` and the session links the routed netlist + the SPEF.

WHAT IS ASSERTED
================
1. FORWARD (fails against the pre-fix file): the sign-off basis links the
   ROUTED netlist and reads the extracted SPEF.
2. STAMP (fails pre-fix): the report states its own basis, in the vocabulary
   `_sta_basis.BASIS_TOKENS` already normalises.
3. HEADER-TRUTH (fails pre-fix, and is the implementation-independent one):
   the netlist the provenance envelope NAMES is the netlist the session's own
   TCL `read_verilog`s. This is the invariant the defect broke.
4. IT MOVES (fails pre-fix): two runs whose routed netlists differ must not
   produce the same measurement inputs. This is the 60/60 finding as a test.
5. DEGRADES LOUDLY (fails pre-fix in the other direction): asked for the
   post-PnR basis with no routed netlist on disk, the report is stamped
   PRE_LAYOUT_ESTIMATE, never POST_ROUTE, and the fallback is disclosed.
6. REVERSE (must pass BOTH pre-fix and post-fix): the Step-10 pre-layout
   preview still links the synth netlist, reads no SPEF and still succeeds.
   The fix must not turn the early-feedback preview into a post-route report.
   Its stamp is asserted in a SEPARATE test, so the control itself stays green
   on both arms.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_powerbasis",
    _PROGRAMS / "phase3_one_shot_runner.py",
)
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

CONTAINER = "test-container-no-such-container"
TOP = "dut"


def _mk_project(tmp_path: Path, *, routed: bool = True, spef: bool = True,
                routed_body: str = "// routed\n") -> Path:
    """A project with a synth netlist + SDC always, and optionally a routed
    netlist and a non-empty extracted SPEF."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / f"{TOP}_synth.v").write_text(f"module {TOP}(); endmodule\n")

    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "constraint.sdc").write_text(
        "create_clock -period 10 [get_ports clk]\n")
    if routed:
        (pnr / f"{TOP}_pnr.v").write_text(
            f"module {TOP}(); endmodule\n{routed_body}")

    if spef:
        ext = tmp_path / "phase3" / "stage3" / "extracted"
        ext.mkdir(parents=True)
        (ext / f"{TOP}.spef").write_text('*SPEF "IEEE 1481-1998"\n')

    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    (libdir / "cellib_typ.lib").write_text("library (l) { }\n")
    return tmp_path


def _mk_pdk(tmp_path: Path) -> "p3.PdkConfig":
    libdir = tmp_path / "input" / "pdk" / "liberty"
    return p3.PdkConfig(
        name="testpdk",
        liberty=str(libdir / "cellib_typ.lib"),
        tech_lef=str(tmp_path / "tech.lef"),
        cell_lef=str(tmp_path / "cell.lef"),
        cell_gds=None,
        site="unit",
        drc_deck=None,
    )


@pytest.fixture(autouse=True)
def _no_docker(monkeypatch):
    """No container on the test host: mounts pinned empty (so
    `_to_container_path` is the identity) and the tool call is a no-op that
    plants a plausible report body, so the emitter reaches its return."""
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])

    def _fake_exec(container, cmd, *a, **k):
        # The real command redirects OpenSTA's stdout into the report; mirror
        # that by writing to the `>` target named in the command itself, so the
        # test never has to be told where the report goes.
        tail = cmd.rsplit(" > ", 1)[-1]
        out = Path(tail.split(" ", 1)[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "Group   Internal Switching Leakage Total\n"
            "Sequential  1.0e-04 1.0e-05 1.0e-09 1.1e-04  50.0%\n"
            "Clock       1.0e-04 1.0e-05 1.0e-09 1.1e-04  50.0%\n"
            "Total       2.0e-04 2.0e-05 2.0e-09 2.2e-04 100.0%\n"
            "dynamic power / leakage power reported above\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


def _emit(project: Path, basis: str, rpt_name: str = "power.rpt"):
    """Emit one power session.

    `basis` is passed ONLY when the emitter accepts it. That is deliberate: on
    the pre-fix file the keyword does not exist, and a `TypeError: unexpected
    keyword argument` would redden every test below for the wrong reason — it
    would prove the signature changed, not that the pre-fix session measured
    the wrong netlist. Adapting here makes the pre-fix arm fail on the
    MEASUREMENT: it links `<top>_synth.v`, publishes a header claiming the
    post-PnR netlist, and produces identical inputs for two different routed
    designs. `test_the_default_basis_is_the_pre_layout_one` pins the keyword
    itself, so the parameter is not unpinned by this."""
    rpt = project / "reports" / "phase3" / rpt_name
    rpt.parent.mkdir(parents=True, exist_ok=True)
    notes: list = []
    kwargs = {}
    if "basis" in inspect.signature(p3._emit_power_report).parameters:
        kwargs["basis"] = basis
    ok = p3._emit_power_report(project, TOP, _mk_pdk(project), CONTAINER,
                               rpt, notes, **kwargs)
    tcl = (rpt.parent / f"power_{TOP}.tcl").read_text()
    return ok, tcl, rpt.read_text(), notes


def _read_verilog_arg(tcl: str) -> str:
    for ln in tcl.splitlines():
        if ln.strip().startswith("read_verilog "):
            return ln.strip().split(None, 1)[1]
    raise AssertionError(f"no read_verilog in emitted TCL:\n{tcl}")


def _linked_file(tcl: str, project: Path) -> Path:
    """The netlist the deck links, as a path on THIS filesystem.

    The deck spells paths under the run root against `$RUN_ROOT`, which the
    deck itself resolves from its own location at run time. That spelling is a
    separate fix with its own tests; here the question is only WHICH FILE the
    session reads, so resolve the variable the way the deck does."""
    arg = _read_verilog_arg(tcl)
    if arg.startswith("$RUN_ROOT/"):
        return project / arg[len("$RUN_ROOT/"):]
    return Path(arg)


# ---------------------------------------------------------------- FORWARD ---
def test_signoff_power_links_the_routed_netlist_and_the_spef(tmp_path):
    """FAILS pre-fix: the pre-fix body linked `<top>_synth.v` for both bases."""
    proj = _mk_project(tmp_path)
    ok, tcl, _, _ = _emit(proj, "post_pnr")
    assert ok is True

    linked = _read_verilog_arg(tcl)
    assert linked.endswith(f"{TOP}_pnr.v"), (
        "the SIGN-OFF power session must link the netlist that was routed. "
        f"It linked:\n    {linked}\n"
        "A pre-PnR netlist has no clock tree in it, so the Clock group reads "
        "exactly 0.000 mW and the total understates the routed design."
    )
    assert "read_spef " in tcl, (
        "the routed design's extracted parasitics must be read; without them "
        "switching power is computed on a netlist with no routing capacitance"
    )


# ------------------------------------------------------------------ STAMP ---
def test_the_report_states_which_side_of_pnr_it_measured(tmp_path):
    """FAILS pre-fix: the pre-fix report carried no basis stamp at all."""
    proj = _mk_project(tmp_path)
    _, tcl, body, _ = _emit(proj, "post_pnr")
    assert 'puts "POWER_BASIS: POST_ROUTE_SPEF"' in tcl
    assert "POWER_BASIS_NETLIST" in tcl and "POWER_BASIS_SPEF" in tcl
    # And the stamp is in the vocabulary the shipped ONE reader normalises,
    # so a consumer needs no second table.
    import _sta_basis
    assert _sta_basis.normalise_basis("POST_ROUTE_SPEF") == "POST_ROUTE"
    assert "basis:   POST_ROUTE_SPEF" in body


# ----------------------------------------------------------- HEADER-TRUTH ---
def test_the_header_names_the_netlist_the_session_actually_linked(tmp_path):
    """The implementation-independent invariant, and the one the defect broke.

    FAILS pre-fix: the envelope's Substance paragraph asserted "the post-PnR
    netlist" as a LITERAL while `read_verilog` named the synth netlist."""
    proj = _mk_project(tmp_path)
    _, tcl, body, _ = _emit(proj, "post_pnr")
    linked = Path(_read_verilog_arg(tcl)).name

    named = [ln for ln in body.splitlines() if ln.startswith("#   netlist:")]
    assert named, f"report carries no netlist provenance line:\n{body}"
    assert named[0].strip().endswith(linked), (
        f"the report NAMES {named[0].strip()!r} but the session linked "
        f"{linked!r} — the document and the measurement disagree"
    )
    assert "post-PnR netlist + the typical-corner" not in body, (
        "the Substance paragraph must be DERIVED from the linked inputs, not "
        "a literal claim that survives a change of netlist"
    )


# --------------------------------------------------------------- IT MOVES ---
def test_the_measurement_moves_when_the_routed_design_moves(tmp_path):
    """FAILS pre-fix. The 60-configuration sweep produced ONE md5 over 60
    `power.rpt` files while all 60 routed netlists differed; the measurement
    inputs must depend on the thing being measured."""
    a = _mk_project(tmp_path / "a", routed_body="// config A\n")
    b = _mk_project(tmp_path / "b", routed_body="// config B: wider rows\n")
    _, tcl_a, _, _ = _emit(a, "post_pnr")
    _, tcl_b, _, _ = _emit(b, "post_pnr")

    read_a = _linked_file(tcl_a, a)
    read_b = _linked_file(tcl_b, b)
    assert read_a.is_file() and read_b.is_file(), (read_a, read_b)
    assert read_a.read_text() != read_b.read_text(), (
        "two place-and-route configurations produced the same measurement "
        "input, so no PnR knob can move this number"
    )


# --------------------------------------------------- DEGRADES LOUDLY ---------
def test_no_routed_netlist_is_stamped_pre_layout_and_disclosed(tmp_path):
    """The other direction: the fix must never CLAIM post-route when the
    routed netlist is not there. FAILS pre-fix, whose header said post-PnR
    unconditionally."""
    proj = _mk_project(tmp_path, routed=False, spef=False)
    ok, tcl, body, notes = _emit(proj, "post_pnr")
    assert ok is True, "a project with no routed netlist must still get a report"
    assert _read_verilog_arg(tcl).endswith(f"{TOP}_synth.v")
    assert 'puts "POWER_BASIS: PRE_LAYOUT_ESTIMATE"' in tcl
    assert "POST_ROUTE" not in body.split("=== Begin")[0], (
        "a session that linked the pre-PnR netlist must not carry a "
        "post-route claim anywhere in its own header"
    )
    assert any("PRE-PnR netlist" in n for n in notes), notes


def test_routed_netlist_without_spef_says_no_spef(tmp_path):
    proj = _mk_project(tmp_path, routed=True, spef=False)
    _, tcl, body, notes = _emit(proj, "post_pnr")
    assert _read_verilog_arg(tcl).endswith(f"{TOP}_pnr.v")
    assert "read_spef " not in tcl
    assert 'puts "POWER_BASIS: POST_ROUTE_NO_SPEF"' in tcl
    assert any("no extracted SPEF" in n for n in notes), notes


# ---------------------------------------------------------------- REVERSE ---
# Must pass BOTH before and after the fix: the control against "point every
# power session at the routed netlist and call it done".
def test_the_pre_layout_preview_still_previews_the_pre_layout_netlist(tmp_path):
    proj = _mk_project(tmp_path)
    ok, tcl, body, _ = _emit(proj, "pre_pnr", rpt_name="preview.rpt")
    assert ok is True
    assert _read_verilog_arg(tcl).endswith(f"{TOP}_synth.v"), (
        "the Step-10 preview exists to give a power picture BEFORE PnR; "
        "linking the routed netlist would make it not a preview"
    )
    assert "read_spef " not in tcl


def test_the_pre_layout_preview_is_stamped_pre_layout(tmp_path):
    """The stamp half of the preview, kept OUT of the reverse control above so
    that control still passes on the pre-fix file — a control that goes red on
    the arm it is supposed to hold constant proves nothing."""
    proj = _mk_project(tmp_path)
    _, tcl, _, _ = _emit(proj, "pre_pnr", rpt_name="preview.rpt")
    assert 'puts "POWER_BASIS: PRE_LAYOUT_ESTIMATE"' in tcl


def test_the_default_basis_is_the_pre_layout_one(tmp_path):
    """Any caller that names no basis gets the conservative one: a report that
    claims less than it measured is recoverable, the converse is not."""
    proj = _mk_project(tmp_path)
    rpt = proj / "reports" / "phase3" / "default.rpt"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    p3._emit_power_report(proj, TOP, _mk_pdk(proj), CONTAINER, rpt, [])
    tcl = (rpt.parent / f"power_{TOP}.tcl").read_text()
    assert _read_verilog_arg(tcl).endswith(f"{TOP}_synth.v")
