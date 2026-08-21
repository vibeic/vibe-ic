"""ORGANIC #593 stale-GDS guard — EXECUTABLE, end-to-end through `main()`.

WHY THIS FILE EXISTS
====================
The only pre-existing coverage of the #593 guard was
``test_v0_3_41_issue593_pnr_cache_geometry.py::
test_orchestrator_cache_skip_is_geometry_aware``, which asserts
``"_pnr_reran" in inspect.getsource(R.main)``. A PERMANENTLY-FALSE variable
satisfies that assertion, and that is exactly what happened: the pad-side
capture appended a disclosure ``StepResult`` right after PnR, so
``plan[-1].name == "pnr"`` was never true again, ``_pnr_reran`` was
dead-False on every path, and a geometry-changing re-dispatch re-ran PnR,
produced a NEW DEF and then SHIPPED THE PREVIOUS DIE'S GDS — with DRC/LVS
signing off on it — under the benign-looking row
``"GDS already present: top.gds (skipped re-run)"``.

The whole failure is invisible to a source-string test, so these tests DRIVE
``main()`` and observe whether ``step_gds`` was actually called. The same
latent bug also fires WITHOUT this capture whenever
``step_signoff_spef_repair`` or the DRV escalation appends a row, so the
guard is now taken from the PnR row BY NAME rather than from ``plan[-1]``.

Scenario under test is the one #593 was filed for: unconverged at
1233x1233 -> operator re-dispatches ``--die-um 1500x1500 --util 0.3``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402

TOP = "chip_top"
OLD_DIE, OLD_UTIL = "1233x1233", 0.40
NEW_DIE, NEW_UTIL = "1500x1500", 0.30


class _Drive:
    """Records which steps main() actually invoked."""

    def __init__(self):
        self.called = []


def _pdk() -> R.PdkConfig:
    return R.PdkConfig(name="testpdk", liberty="/nonexistent/tt.lib",
                       tech_lef="/nonexistent/tech.lef",
                       cell_lef="/nonexistent/cells.lef", cell_gds=None,
                       site="unit", drc_deck=None)


def _project(tmp_path: Path, *, cached_die: str, cached_util: float) -> Path:
    """A project in the 'everything already exists from the previous run'
    state: cached netlist, cached DEF, cached GDS, and a geometry sidecar
    recording the PREVIOUS run's die."""
    pnr = R._pl.pnr_dir(tmp_path)
    synth = R._pl.synth_dir(tmp_path)
    rtl = R._pl.rtl_dir(tmp_path)
    for d in (pnr, synth, rtl):
        d.mkdir(parents=True, exist_ok=True)
    (rtl / f"{TOP}.v").write_text(f"module {TOP}(); endmodule\n")
    (synth / f"{TOP}_synth.v").write_text(f"module {TOP}(); endmodule\n")
    # Step 15 (PnR) DECLARES `phase2/stage2/synth/post_dft_netlist.v` as a
    # required input owed by step 12, and the runner refuses to run a step
    # whose declared inputs are absent. Without this file the geometry-change
    # arm never reaches `step_pnr` at all:
    #
    #   BLOCKED pnr  REFUSED TO RUN: 1 declared input(s) ABSENT —
    #                phase2/stage2/synth/post_dft_netlist.v (owed by step 12)
    #
    # so no new DEF is produced, and the `gds` and `pad_side_constraint` rows
    # are never emitted — which is what the six assertions in this file were
    # reading when they failed. It is invisible on the UNCHANGED-geometry arm
    # because PnR short-circuits on "DEF already present" before the declared
    # input is consulted, which is why only half this file went red.
    #
    # This belongs in the fixture rather than being worked around: the
    # docstring above states the premise as "everything already exists from
    # the previous run", and a post-DFT netlist is part of everything.
    (synth / "post_dft_netlist.v").write_text(f"module {TOP}(); endmodule\n")
    (pnr / f"{TOP}.def").write_text(
        "DIEAREA ( 0 0 ) ( 1233000 1233000 ) ;\nPINS 0 ;\nEND PINS\n")
    (pnr / f"{TOP}.gds").write_text("STALE GDS FROM THE PREVIOUS DIE\n")
    R._write_pnr_args_sidecar(pnr, cached_die, cached_util)
    # The fixture's premise is "a PREVIOUS RUN produced these", and a previous
    # run is now IDENTIFIED — the cache is keyed on the producing build as well
    # as on the design inputs (see `_producer_cache_valid_for`). Stamping the
    # current build keeps this file testing what it was written to test, the
    # #593 GEOMETRY guard, instead of tripping on the producer guard first.
    # test_phase3_cache_producer_identity.py owns the producer key's coverage.
    R._write_producer_identity(synth, "synth")
    R._write_producer_identity(pnr, "pnr")
    R._write_producer_identity(pnr, "gds")
    return tmp_path


def _drive(monkeypatch, project: Path, *, die: str, util: float) -> _Drive:
    """Neutralise everything main() does that is not the cache decision, and
    record the steps it invokes. `_pnr_cache_valid_for` and the geometry
    sidecar are LEFT REAL — the cache verdict is what is under test."""
    d = _Drive()

    def _fake_pnr(proj, top, pdk, container, die_um, u, **kw):
        d.called.append("pnr")
        out = R._pl.pnr_dir(proj)
        out.mkdir(parents=True, exist_ok=True)
        # A real re-run rewrites the DEF and the geometry sidecar.
        w, _, h = die_um.partition("x")
        (out / f"{top}.def").write_text(
            f"DIEAREA ( 0 0 ) ( {int(float(w)) * 1000} "
            f"{int(float(h)) * 1000} ) ;\nPINS 0 ;\nEND PINS\n")
        R._write_pnr_args_sidecar(out, die_um, u)
        return R.StepResult("pnr", "PASS", 0.0,
                            f"PnR OK: routed {die_um} (re-ran: geometry changed)")

    def _fake_gds(proj, top, pdk, container):
        d.called.append("gds")
        gds = R._pl.pnr_dir(proj) / f"{top}.gds"
        gds.write_text("FRESH GDS DERIVED FROM THE NEW DEF\n")
        return R.StepResult("gds", "PASS", 0.0, "gds re-derived from new DEF",
                            [str(gds)])

    def _step(name):
        def _f(*a, **k):
            d.called.append(name)
            return R.StepResult(name, "PASS", 0.0, f"{name} ok")
        return _f

    monkeypatch.setattr(R, "step_pnr", _fake_pnr)
    monkeypatch.setattr(R, "step_gds", _fake_gds)
    monkeypatch.setattr(R, "step_synth", _step("synth"))
    monkeypatch.setattr(R, "step_drc", _step("drc"))
    monkeypatch.setattr(R, "step_lvs",
                        lambda *a, **k: (d.called.append("lvs")
                                         or R.StepResult("lvs", "PASS", 0.0,
                                                         "lvs ok")))
    monkeypatch.setattr(R, "step_canonicalize_artefacts",
                        _step("canonicalize_artefacts"))
    monkeypatch.setattr(R, "step_signoff_spef_repair", lambda *a, **k: None)
    monkeypatch.setattr(R, "step_signoff_drv_wire_length_repair",
                        lambda *a, **k: None)

    monkeypatch.setattr(R, "_detect_pdk", lambda *a, **k: _pdk())
    monkeypatch.setattr(R._runner_lock, "acquire_or_reenter",
                        lambda *a, **k: object())
    monkeypatch.setattr(R, "commercial_pdk_fallback_guard",
                        lambda *a, **k: None)
    monkeypatch.setattr(R, "macro_lef_layer_compat_guard", lambda *a, **k: None)
    monkeypatch.setattr(R, "_container_mounts", lambda *a, **k: [])
    monkeypatch.setattr(R, "_is_pure_analog_no_rtl_track",
                        lambda *a, **k: (False, ""))
    monkeypatch.setattr(R, "_netlist_matches_liberty", lambda *a, **k: True)
    monkeypatch.setattr(R, "_stale_rtl_by_fingerprint", lambda *a, **k: [])
    monkeypatch.setattr(R, "_stale_rtl_vs_netlist", lambda *a, **k: [])
    monkeypatch.setattr(R, "_resolve_asic_top_structural",
                        lambda proj, top, hint=None: top)
    monkeypatch.setattr(R, "_DERIVED_ARTEFACT_GENERATORS", ())
    monkeypatch.setattr(R._pl, "emit_final_summary", lambda *a, **k: False)

    monkeypatch.setattr(sys, "argv", [
        "phase3_one_shot_runner", str(project), "--top-name", TOP,
        "--die-um", die, "--util", str(util), "--container", "",
    ])
    return d


def _plan(project: Path):
    doc = json.loads(
        R._pl.report_path(project, "phase3_one_shot.json").read_text())
    return {s["name"]: s for s in doc["steps"]}


# ---------------------------------------------------------------------------
# THE REGRESSION: a geometry change must re-derive the GDS, even though a
# disclosure row now sits between PnR and the GDS cache block.
#
# MUTATION THIS CATCHES (the skeptic's own):
#     _pnr_reran = (plan[-1].name == "pnr"
#                   and "skipped" not in plan[-1].detail)
# -> step_gds is never called and the STALE GDS is shipped.
# ---------------------------------------------------------------------------

def test_geometry_change_rederives_the_gds(tmp_path, monkeypatch):
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    gds = R._pl.pnr_dir(project) / f"{TOP}.gds"
    stale = gds.read_text()

    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    R.main()

    plan = _plan(project)
    assert "pnr" in d.called, "the geometry change must force a PnR re-run"
    assert "gds" in d.called, (
        "ORGANIC #593: PnR re-ran on a NEW die, so the GDS must be "
        "re-derived from the new DEF. It was not — the run would ship the "
        f"PREVIOUS die's GDS. gds row: {plan['gds']['detail']!r}")
    assert gds.read_text() != stale, "the shipped GDS is still the stale one"
    assert "skipped re-run" not in plan["gds"]["detail"]


def test_the_disclosure_row_is_present_and_did_not_block_anything(
        tmp_path, monkeypatch):
    """The pad-side row IS emitted (it is the capture's whole point) and the
    steps after it still ran — so the test above cannot be passing merely
    because the disclosure row went missing."""
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    R.main()

    plan = _plan(project)
    assert "pad_side_constraint" in plan, (
        f"the disclosure row must be emitted; rows={sorted(plan)}")
    # No project ships a pad-side table today, so the ordinary green path is
    # a VACUOUS_PASS row — the exact shape under which the stale GDS shipped.
    assert plan["pad_side_constraint"]["status"] == "PASS"
    assert "VACUOUS_PASS" in plan["pad_side_constraint"]["detail"]
    for step in ("gds", "drc", "lvs", "canonicalize_artefacts"):
        assert step in plan, f"{step} must still run after the disclosure row"


# ---------------------------------------------------------------------------
# The other direction — so the test above cannot pass by always re-running.
# ---------------------------------------------------------------------------

def test_unchanged_geometry_still_reuses_the_gds(tmp_path, monkeypatch):
    """Same die + same util as the cached run: PnR is skipped and the GDS is
    reused. This is the provenance-preserving behaviour #593 kept."""
    project = _project(tmp_path, cached_die=NEW_DIE, cached_util=NEW_UTIL)
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    R.main()

    plan = _plan(project)
    assert "pnr" not in d.called, "unchanged geometry must hit the PnR cache"
    assert "gds" not in d.called, "unchanged geometry must hit the GDS cache"
    assert "skipped re-run" in plan["gds"]["detail"]


# ---------------------------------------------------------------------------
# The SAME latent bug without this capture: an appended repair row.
#
# MUTATION THIS CATCHES: any reversion of `_pnr_reran` / the `_chain_ok`
# chain to `plan[-1]`. On upstream tip this scenario ALREADY shipped a stale
# GDS whenever step_signoff_spef_repair returned a row.
# ---------------------------------------------------------------------------

def test_an_appended_repair_row_does_not_disable_the_guard(tmp_path,
                                                           monkeypatch):
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    monkeypatch.setattr(
        R, "step_signoff_spef_repair",
        lambda *a, **k: R.StepResult("signoff_spef_repair", "PASS", 0.0,
                                     "no repair needed"))
    R.main()

    plan = _plan(project)
    assert "signoff_spef_repair" in plan
    assert "gds" in d.called, (
        "a repair row between PnR and the GDS block must not disable the "
        f"#593 guard; gds row: {plan['gds']['detail']!r}")


# ---------------------------------------------------------------------------
# The chain gating must be PRESERVED exactly: a FAILING repair row still
# stops the GDS/DRC-facing steps, as it did before.
# ---------------------------------------------------------------------------

def test_a_failing_repair_row_still_stops_the_gds(tmp_path, monkeypatch):
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    monkeypatch.setattr(
        R, "step_signoff_spef_repair",
        lambda *a, **k: R.StepResult("signoff_spef_repair", "FAIL", 0.0,
                                     "repair blew up"))
    R.main()

    plan = _plan(project)
    assert plan["signoff_spef_repair"]["status"] == "FAIL"
    assert "gds" not in d.called, (
        "a FAILED repair must still gate the GDS step (unchanged behaviour)")


def test_failed_pnr_gates_the_gds_and_emits_no_padside_row(tmp_path,
                                                           monkeypatch):
    """A FAILED PnR must not gain a second, fabricated failure row. The
    pad-side gate has nothing to measure and says nothing.

    MUTATION THIS CATCHES: running the gate unconditionally, which on a
    failed PnR emits `FAIL: No DEF file found under phase3/`.
    """
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    (R._pl.pnr_dir(project) / f"{TOP}.def").unlink()
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    monkeypatch.setattr(
        R, "step_pnr",
        lambda *a, **k: (d.called.append("pnr")
                         or R.StepResult("pnr", "FAIL", 0.0,
                                         "PnR died: ROUTE_NOT_CONVERGED")))
    R.main()

    plan = _plan(project)
    assert plan["pnr"]["status"] == "FAIL"
    assert "gds" not in d.called
    assert "pad_side_constraint" not in plan, (
        "the pad-side gate must not manufacture a second failure on a run "
        f"that has no DEF: {plan.get('pad_side_constraint')}")


# ---------------------------------------------------------------------------
# The DISCLOSURE claim itself, executed. The capture claimed the gate
# "unconditionally runs post-PnR so violations are DISCLOSED"; nothing
# executed main()'s pad-side block, so recording a FAIL verdict as a PASS row
# passed the whole suite.
#
# MUTATION THIS CATCHES: `_psc_status = "PASS"` (violation disclosed nowhere,
# blocks nothing).
# ---------------------------------------------------------------------------

_PAD_TABLE_MD = """\
### Pad placement

| Edge | Signals |
|------|---------|
| North (N) | `sig_a` |
| South (S) | `sig_b` |
"""


def _def_with_pins(w: int, h: int, pins: dict) -> str:
    lines = [f"DIEAREA ( 0 0 ) ( {w} {h} ) ;", f"PINS {len(pins)} ;"]
    for name, (x, y) in pins.items():
        lines += [f"    - {name} + NET {name} + DIRECTION INPUT + USE SIGNAL",
                  f"      + PLACED ( {x} {y} ) N ;"]
    lines += ["END PINS", "END DESIGN"]
    return "\n".join(lines) + "\n"


def _with_pad_table(project: Path, pins: dict) -> None:
    docs = project / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_floorplan.md").write_text(_PAD_TABLE_MD, encoding="utf-8")
    (R._pl.pnr_dir(project) / f"{TOP}.def").write_text(
        _def_with_pins(1500000, 1500000, pins))


def test_pad_side_violation_is_disclosed_as_a_fail_row(tmp_path, monkeypatch):
    """Both pins on the North edge; the table puts sig_b on South -> FAIL row
    naming the pin."""
    project = _project(tmp_path, cached_die=NEW_DIE, cached_util=NEW_UTIL)
    _with_pad_table(project, {"sig_a": (700000, 1499000),
                              "sig_b": (800000, 1499000)})
    _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    R.main()

    row = _plan(project)["pad_side_constraint"]
    assert row["status"] == "FAIL", (
        f"a wrong-side pin must be DISCLOSED as FAIL, not laundered into a "
        f"PASS row: {row}")
    assert "sig_b" in row["detail"]


def test_pad_side_conforming_layout_is_a_pass_row(tmp_path, monkeypatch):
    """Control for the test above: pins placed exactly where the table says
    -> PASS. Without this, `_psc_status = "FAIL"` would also 'pass'."""
    project = _project(tmp_path, cached_die=NEW_DIE, cached_util=NEW_UTIL)
    _with_pad_table(project, {"sig_a": (700000, 1499000),
                              "sig_b": (800000, 1000)})
    _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    R.main()

    row = _plan(project)["pad_side_constraint"]
    assert row["status"] == "PASS", row
    assert "PASS: all 2 constrained pin(s)" in row["detail"]


def test_pad_side_fail_does_not_block_the_rest_of_the_flow(tmp_path,
                                                           monkeypatch):
    """It is a DISCLOSURE gate: a FAIL row must still let GDS/DRC/LVS run
    (the run's headline verdict carries the failure)."""
    project = _project(tmp_path, cached_die=NEW_DIE, cached_util=NEW_UTIL)
    _with_pad_table(project, {"sig_a": (700000, 1499000),
                              "sig_b": (800000, 1499000)})
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    rc = R.main()

    plan = _plan(project)
    assert plan["pad_side_constraint"]["status"] == "FAIL"
    # `gds` is the load-bearing one: gating it on `plan[-1].status == "PASS"`
    # would silently DROP the GDS/DRC/LVS sign-off whenever the disclosure
    # row is not PASS.
    for step in ("gds", "drc", "lvs", "canonicalize_artefacts"):
        assert step in plan, f"{step} row missing; rows={sorted(plan)}"
    assert rc != 0, "a disclosed pad-side violation must not exit 0"


def test_unmeasurable_pad_side_is_skip_not_fail(tmp_path, monkeypatch):
    """A DEF the gate cannot parse means 'cannot verify', NOT 'violated'.

    MUTATION THIS CATCHES: mapping the check's ERROR verdict to a FAIL row,
    which turns every unparseable-DEF run into a fabricated pad-side
    violation (and, with a pad table absent, a FAIL the design never earned).
    """
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    (project / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (project / "input" / "docs" / "L9_floorplan.md").write_text(
        _PAD_TABLE_MD, encoding="utf-8")
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)

    def _pnr_no_diearea(proj, top, pdk, container, die_um, u, **kw):
        d.called.append("pnr")
        out = R._pl.pnr_dir(proj)
        (out / f"{top}.def").write_text("VERSION 5.8 ;\nDESIGN x ;\n")
        R._write_pnr_args_sidecar(out, die_um, u)
        return R.StepResult("pnr", "PASS", 0.0, f"PnR OK: routed {die_um}")

    monkeypatch.setattr(R, "step_pnr", _pnr_no_diearea)
    R.main()

    row = _plan(project)["pad_side_constraint"]
    assert row["status"] == "SKIP", (
        f"'could not parse the DEF' is not a pad-side violation: {row}")
