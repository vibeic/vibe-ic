"""Post-route repair: DRV is a CLOSURE AXIS, not a side effect of setup closure.

MEASURED DEFECT (a real converge run, sky130A, spm; re-measured end-to-end in
the flow's own container before and after this change):

  * Post-route multi-corner sign-off STA (Step 23) FAILed with 5 DRV
    violations — 4 `max slew` (1.50 limit / 1.63 actual) + 1 `max capacitance`
    (0.08 limit / 0.09 actual), all traceable to ONE weakest-drive buffer
    driving a 3-sink net.
  * `signoff_spef_repair` had already run and reported real work
    (`SHIP_ROUTING_CLEARED: 364`, `SHIP_WNS_BEFORE 4.28 -> AFTER_REPAIR 4.66`).
  * Yet its POST-REROUTE convergence loop executed ZERO `repair_design` calls:
    it broke at pass 0 with `SHIP_CVG_CLOSED` because its ONLY closure
    criterion was setup worst slack (`sta::worst_slack -max >= -0.001`), which
    read +4.72 ns. The loop's final block likewise reported ONLY setup slack,
    so the shipped transcript contained no DRV number at all.
  * Replaying ONE `repair_design` on exactly those post-reroute parasitics, in
    the same container, found the slew violation, resized ONE instance, and
    after the reroute + fresh real-SPEF extraction the violator table was
    EMPTY — setup unchanged (4.716 -> 4.713 ns), route DRC-clean (0
    violations). The resizer could always fix it; the loop never asked.

So the defect is NOT the buffer, NOT a do-not-use cell-pool restriction, NOT a
failed/swallowed write, and NOT a broken hand-off (the repaired DEF *was*
written and *was* promoted — `routed.def` being byte-identical to
`routed_repaired.def` is the PROMOTION copy, and `routed_base_prerepair.def`
holds the pre-repair route). The defect is the closure criterion.

FIX (producer-side, chip/PDK-AGNOSTIC):
  1. `_ship_drv_count` measures the CURRENT DRV violator population with the
     SAME `report_check_types -violators` emitter the sign-off uses. -1 means
     the query failed: UNMEASURED, never zero.
  2. The convergence loop closes only when setup AND DRV are both clean, and
     plateaus only when NEITHER axis improved.
  3. `SHIP_DRV_BEFORE` / `SHIP_DRV_POSTROUTE` + the residual violating pins are
     emitted, so a run that ships a DRV residual says so in its own transcript.
  4. The promotion gate refuses a like-for-like DRV regression, refuses a write
     that DISCLOSED failure, and the step deletes the previous run's repaired
     artefacts first so a stale file can never masquerade as a fresh write.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


def _emit(tmp_path: Path) -> str:
    return R._ship_signoff_spef_repair_tcl(
        top="chip_top",
        tech_lef_c=str(tmp_path / "tech.lef"),
        cell_lef_c=str(tmp_path / "cells.lef"),
        ss_liberty_c=str(tmp_path / "ss.lib"),
        pnr_dir_c=str(tmp_path / "pnr"),
        max_captable_c=str(tmp_path / "rules.magic"),
        metal_prefix="met",
        thread_count=4,
    )


# A tclsh harness that emulates just enough of OpenROAD to reproduce the
# MEASURED physics of the defect:
#   * `sta::worst_slack` returns a COMFORTABLY POSITIVE setup slack (+4.72 ns,
#     the measured value) — the exact situation the defect hid in.
#   * `report_check_types ... >> <path>` writes `$::drv` violator lines, the way
#     OpenSTA's redirect does.
#   * `detailed_route` is what MOVES the DRV population, because DRV is a
#     function of the routed parasitics. The FIRST (base) reroute lands the
#     pre-reroute repair — which was optimised against the PRE-reroute
#     parasitics — on new wiring and re-explodes slew (measured: 1 slew
#     violation repaired pre-reroute, 5 violating pins present after). A LATER
#     reroute, following a repair made against post-reroute parasitics, keeps
#     the fix (measured: violator table empty, route DRC-clean).
#   * `repair_design` is counted; on its own it changes nothing, exactly like
#     the real tool whose effect is only visible after re-extraction.
# Everything else is absorbed by `unknown`.
_HARNESS = r"""
proc unknown {args} { return "" }
set ::rd 0
set ::routes 0
set ::drv %DRV0%
proc report_check_types {args} {
  set _path [lindex $args end]
  set _fh [open $_path a]
  for {set _k 0} {$_k < $::drv} {incr _k} {
    puts $_fh "somepin/X    1.50    1.63   -0.13 (VIOLATED)"
  }
  close $_fh
  return ""
}
proc repair_design {args} { incr ::rd ; return "" }
proc detailed_route {args} {
  incr ::routes
  if {$::routes == 1} { set ::drv %DRV1% } else { set ::drv %DRVN% }
  return ""
}
namespace eval sta { proc worst_slack {args} { return 4.72 } }
"""


def _run(tmp_path: Path, drv0: int, drv1: int, drvn: int, extra: str = ""):
    """drv0 = DRV of the base route; drv1 = DRV the base reroute leaves;
    drvn = DRV a later (post-repair) reroute leaves."""
    script = tmp_path / "s.tcl"
    harness = (_HARNESS.replace("%DRV0%", str(drv0))
                       .replace("%DRV1%", str(drv1))
                       .replace("%DRVN%", str(drvn)))
    script.write_text(harness + extra + _emit(tmp_path)
                      + "\nputs \"RD_CALLS: $::rd\"\n")
    (tmp_path / "pnr").mkdir(exist_ok=True)
    r = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _marker(out: str, tag: str) -> str:
    for ln in out.splitlines():
        if ln.startswith(tag):
            return ln.split(":", 1)[1].strip()
    raise AssertionError(f"marker {tag} not in transcript:\n{out}")


# ------------------------------------------------- the defect itself -----

@needs_tclsh
def test_positive_setup_with_drv_still_runs_postroute_repair(tmp_path):
    """THE REGRESSION TEST. Setup is comfortably positive (+4.72 ns) and the DRV
    population is non-zero — the exact measured shape. The post-reroute
    convergence loop MUST still run `repair_design`.

    On the pre-fix program the loop breaks at pass 0 (`SHIP_CVG_CLOSED` on setup
    alone) and the post-reroute repair count is 0, so `RD_CALLS` stops at the 5
    pre-reroute calls. This assertion is what fails when the fix is reverted."""
    out = _run(tmp_path, drv0=5, drv1=5, drvn=0)
    # 5 pre-reroute calls are unconditional; anything above that is the
    # convergence loop actually repairing the post-reroute DRV.
    calls = int(_marker(out, "RD_CALLS"))
    assert calls > 5, (
        f"post-reroute repair_design never ran (RD_CALLS={calls}); the loop "
        f"closed on setup alone and shipped the DRV residual:\n{out}")


@needs_tclsh
def test_drv_population_is_measured_and_on_the_record(tmp_path):
    """The transcript must carry the DRV population of the BASE route, of every
    convergence pass, and of the route the step is about to ship. Before the fix
    the transcript contained no DRV number anywhere, so the residual was
    invisible until Step-23 sign-off STA found it."""
    out = _run(tmp_path, drv0=5, drv1=5, drvn=0)
    assert _marker(out, "SHIP_DRV_BEFORE") == "5"
    assert _marker(out, "SHIP_DRV_CVG_PASS0") == "5"
    assert _marker(out, "SHIP_DRV_POSTROUTE") == "0"


@needs_tclsh
def test_residual_violating_pins_are_disclosed(tmp_path):
    """A residual the repair genuinely CANNOT clear must be named pin-by-pin in
    the step's own transcript, not left for a downstream gate to discover — and
    the loop must still terminate on the plateau instead of spinning."""
    out = _run(tmp_path, drv0=3, drv1=3, drvn=3)
    assert _marker(out, "SHIP_DRV_POSTROUTE") == "3"
    pins = [ln for ln in out.splitlines()
            if ln.startswith("SHIP_DRV_RESIDUAL_PIN")]
    assert len(pins) == 3, f"residual pins not disclosed:\n{out}"
    assert "SHIP_CVG_PLATEAU" in out


@needs_tclsh
def test_loop_terminates_once_both_axes_close(tmp_path):
    """Closure still happens — the loop must not spin now that it has a second
    axis. With setup positive and DRV driven to 0 it reports SHIP_CVG_CLOSED."""
    out = _run(tmp_path, drv0=5, drv1=5, drvn=0)
    assert "SHIP_CVG_CLOSED" in out


@needs_tclsh
def test_clean_design_still_closes_at_pass_zero(tmp_path):
    """NON-REGRESSION: a design that is genuinely clean on BOTH axes must still
    close immediately and do no extra reroutes (the fix must not make every
    already-converged run pay for three more routing passes)."""
    out = _run(tmp_path, drv0=0, drv1=0, drvn=0)
    assert "SHIP_CVG_CLOSED" in out
    assert _marker(out, "SHIP_DRV_CVG_PASS0") == "0"
    assert int(_marker(out, "RD_CALLS")) == 5   # pre-reroute loop only


@needs_tclsh
def test_unmeasured_drv_is_not_read_as_zero(tmp_path):
    """A tool whose `report_check_types` redirect produces nothing yields -1
    (UNMEASURED). It must be DISCLOSED as such and must not be reported as a
    clean zero — while still degrading to the historical setup-only closure so
    an older tool does not spin the loop."""
    silent = "proc report_check_types {args} { return \"\" }\n"
    out = _run(tmp_path, drv0=5, drv1=5, drvn=0, extra=silent)
    assert _marker(out, "SHIP_DRV_BEFORE") == "-1"
    assert "SHIP_CVG_DRV_UNMEASURED" in out
    assert "SHIP_CVG_CLOSED" in out


# -------------------------------------------------- write disclosure -----

@needs_tclsh
def test_failed_write_is_disclosed_not_swallowed(tmp_path):
    """The two writes produce the ONLY artefacts the step promotes. A failure
    must be stated (SHIP_WD_FAILED / SHIP_WV_FAILED), and so must success
    (SHIP_WD_OK / SHIP_WV_OK) — the absence of a failure line is not evidence a
    write happened. Here `write_def`/`write_verilog` are absorbed by `unknown`
    and produce no file, which is exactly the silent-failure shape."""
    out = _run(tmp_path, drv0=0, drv1=0, drvn=0)
    assert "SHIP_WD_FAILED:" in out
    assert "SHIP_WV_FAILED:" in out


def test_emitter_states_both_write_outcomes(tmp_path):
    """Both the success and the failure marker must exist in the emitted script
    — a script that can only ever print a failure still cannot distinguish
    'wrote nothing' from 'never reached'."""
    tcl = _emit(tmp_path)
    for marker in ("SHIP_WD_OK", "SHIP_WD_FAILED",
                   "SHIP_WV_OK", "SHIP_WV_FAILED"):
        assert marker in tcl, marker


# --------------------------------------------------- parse + gate --------

def test_parse_extracts_drv_and_write_outcomes():
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: 4.28\nSHIP_DRV_BEFORE: 5\n"
        "SHIP_WNS_AFTER_REPAIR: 4.66\nSHIP_WNS_POSTROUTE: 4.71\n"
        "SHIP_DRV_POSTROUTE: 0\nNumber of violations = 0\n"
        "SHIP_WD_OK: 193790\nSHIP_WV_OK: 42951\n"
        "SHIP_SIGNOFF_REPAIR_DONE\n")
    assert p["drv_before"] == 5
    assert p["drv_postroute"] == 0
    assert p["def_write_failed"] is False
    assert p["v_write_failed"] is False


def test_parse_keeps_unmeasured_drv_negative():
    """-1 must survive parsing as -1. Clamping it to 0 would turn UNMEASURED
    into a clean bill of health at the gate."""
    p = R._parse_ship_repair_log("SHIP_DRV_BEFORE: -1\nSHIP_DRV_POSTROUTE: -1\n")
    assert p["drv_before"] == -1
    assert p["drv_postroute"] == -1


def test_gate_refuses_a_like_for_like_drv_regression():
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: 4.28\nSHIP_WNS_AFTER_REPAIR: 4.66\n"
        "SHIP_WNS_POSTROUTE: 4.71\nNumber of violations = 0\n"
        "SHIP_DRV_BEFORE: 1\nSHIP_DRV_POSTROUTE: 7\n")
    assert R._ship_repair_should_promote(p, True, True) is False


def test_gate_promotes_a_drv_improvement():
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: 4.28\nSHIP_WNS_AFTER_REPAIR: 4.66\n"
        "SHIP_WNS_POSTROUTE: 4.71\nNumber of violations = 0\n"
        "SHIP_DRV_BEFORE: 5\nSHIP_DRV_POSTROUTE: 0\n")
    assert R._ship_repair_should_promote(p, True, True) is True


def test_gate_ignores_unmeasured_drv_endpoints():
    """UNMEASURED (-1) is not evidence of a regression either — the guard must
    stay silent rather than invent a refusal from a failed measurement."""
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: 4.28\nSHIP_WNS_AFTER_REPAIR: 4.66\n"
        "SHIP_WNS_POSTROUTE: 4.71\nNumber of violations = 0\n"
        "SHIP_DRV_BEFORE: -1\nSHIP_DRV_POSTROUTE: 7\n")
    assert R._ship_repair_should_promote(p, True, True) is True


def test_gate_refuses_when_a_write_disclosed_failure():
    """`repaired_def_ok`/`repaired_v_ok` are `is_file() and size > 0`, which a
    STALE artefact satisfies. A disclosed write failure must veto regardless."""
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: 4.28\nSHIP_WNS_AFTER_REPAIR: 4.66\n"
        "SHIP_WNS_POSTROUTE: 4.71\nNumber of violations = 0\n"
        "SHIP_WD_FAILED: cannot open output file\n")
    assert R._ship_repair_should_promote(p, True, True) is False


def test_drv_phrase_never_renders_unmeasured_as_a_number():
    assert R._ship_drv_phrase(None) == "UNMEASURED"
    assert R._ship_drv_phrase(-1) == "UNMEASURED"
    assert R._ship_drv_phrase(0) == "0"
    assert R._ship_drv_phrase(5) == "5"


# ------------------------------------------- stale-artefact promotion ----

def test_stale_repaired_artefacts_cannot_be_promoted(tmp_path, monkeypatch):
    """A previous run's `routed_repaired.def` sitting in the reused pnr dir must
    not be able to satisfy this run's promotion evidence. The step removes both
    repaired artefacts BEFORE the tool runs, so a repair that writes nothing
    leaves nothing to promote and `routed.def` is untouched."""
    pnr = tmp_path / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("BASE ROUTE\n")
    # Artefacts from an earlier run, complete and non-empty.
    stale_def = pnr / "routed_repaired.def"
    stale_v = pnr / "chip_top_pnr_repaired.v"
    stale_def.write_text("STALE REPAIRED ROUTE\n")
    stale_v.write_text("module chip_top; endmodule\n")

    monkeypatch.setattr(R, "_openroad_supports_postroute_spef_repair",
                        lambda c: True)
    monkeypatch.setattr(R, "_resolve_signoff_corner_libs",
                        lambda p, k, c: {"SS": "/ss.lib"})
    monkeypatch.setattr(R, "_max_captable_c", lambda k, c: "/rules.magic")
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: str(p))
    monkeypatch.setattr(R, "_filler_masters_for_pdk", lambda k: [])
    monkeypatch.setattr(R, "_openroad_thread_count", lambda: 4)
    # The tool "runs" but writes no artefacts and discloses the failure.
    monkeypatch.setattr(
        R, "_docker_exec",
        lambda c, cmd, *a, **kw: (
            0,
            "SHIP_WNS_BEFORE: 1.0\nSHIP_DRV_BEFORE: 0\n"
            "SHIP_WNS_AFTER_REPAIR: 1.0\nSHIP_WNS_POSTROUTE: 1.0\n"
            "SHIP_DRV_POSTROUTE: 0\nNumber of violations = 0\n"
            "SHIP_WD_FAILED: disk full\nSHIP_WV_FAILED: disk full\n"
            "SHIP_SIGNOFF_REPAIR_DONE\n",
            ""))

    class _Pdk:
        tech_lef = "/tech.lef"
        cell_lef = "/cells.lef"
        metal_prefix = "met"

    res = R.step_signoff_spef_repair(tmp_path, "chip_top", _Pdk(), "ctr")
    assert res is not None
    assert not stale_def.exists(), "stale repaired DEF survived into this run"
    assert not stale_v.exists(), "stale repaired netlist survived into this run"
    assert (pnr / "routed.def").read_text() == "BASE ROUTE\n"
    assert (pnr / "routed_base_prerepair.def").exists() is False
    assert "not promoted" in res.detail
