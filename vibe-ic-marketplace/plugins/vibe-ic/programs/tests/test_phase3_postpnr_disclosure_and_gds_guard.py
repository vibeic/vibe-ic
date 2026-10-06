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
from _delivery_declaration import declare_delivery as _declare  # noqa: E402

TOP = "chip_top"
OLD_DIE, OLD_UTIL = "1233x1233", 0.40
NEW_DIE, NEW_UTIL = "1500x1500", 0.30


class _Drive:
    """Records which steps main() actually invoked."""

    def __init__(self):
        self.called = []






class _IdentityArgs:
    """The knobs R-0924-3 r3 folds into a step's identity — `--spare-density`
    and the env vars are inputs the step reads that are not files, so the
    fixtures must name them as a real invocation would."""
    spare_density = 0.02
    container = ""


def _pdk(root: Path | None = None) -> R.PdkConfig:
    """R-0924-3 CATCH-UP. One of a step's four identity components is the
    sha256 of the PDK files it reads, and `/nonexistent` paths are (rightly)
    unreadable — with them nothing is ever judged fresh and the GEOMETRY guard
    this file exists to test is never the reason anything re-runs. Given a
    root the declared files are written for real. The unreadable case is not
    lost: `test_phase3_cache_producer_identity` owns it."""
    if root is None:
        return R.PdkConfig(name="testpdk", liberty="/nonexistent/tt.lib",
                           tech_lef="/nonexistent/tech.lef",
                           cell_lef="/nonexistent/cells.lef", cell_gds=None,
                           site="unit", drc_deck=None)
    # OUTSIDE the project, which is where a PDK lives. R-0924-3 r3 added a
    # structural guard: a PDK path inside the run directory is this run's own
    # derivation (the VIA-patch legalizer stages one there), not a PDK input,
    # and it refuses. Writing the fixture's PDK inside the project tripped it —
    # correctly.
    d = Path(root).parent / "_pdk_outside"
    d.mkdir(parents=True, exist_ok=True)
    lib, tlef, clef = d / "tt.lib", d / "tech.lef", d / "cells.lef"
    for f, text in ((lib, "library(t){}\n"), (tlef, "VERSION 5.8 ;\n"),
                    (clef, "MACRO unit\n")):
        if not f.is_file():
            f.write_text(text)
    return R.PdkConfig(name="testpdk", liberty=str(lib), tech_lef=str(tlef),
                       cell_lef=str(clef), cell_gds=None, site="unit",
                       drc_deck=None)


def _span_inputs(project, top: str = "top") -> None:
    """Everything the three SPANS declare that they do not produce themselves.

    R-0924-3 r2 CATCH-UP. The review (wcxu446tu) found that keying a kind on
    the ONE step declaring its artefact made pnr hash `post_hold.def` — a file
    `step_pnr` writes itself — so a new netlist, SDC or slot never invalidated
    the routed DEF. Freshness is now keyed on the whole SPAN the runner
    function implements (pnr = 15..21, gds = 26.5ic..37), so "a tree from a
    previous run" means a tree carrying what those spans READ: the slot
    declaration, the RTL, the SDC, the netlist, the routed DEF, the spare-cell
    record and the SPEF. Same catch-up as the ones above, for the same reason.
    """
    from pathlib import Path as _P
    project = _P(project)
    # The cached fixture netlist is from the substituted direct producer.
    # Do not imply a LibreLane handoff that this fixture never produced.
    switch = project / "phase3/librelane_switch.json"
    settings = json.loads(switch.read_text()) if switch.is_file() else {}
    settings.setdefault("steps", {}).setdefault("9", "direct")
    switch.parent.mkdir(parents=True, exist_ok=True)
    switch.write_text(json.dumps(settings))
    for rel, text in (
        ("phase2/stage1/rtl/%s.v" % top, "module %s(); endmodule\n" % top),
        ("phase2/stage2/constraints/%s.sdc" % top,
         "create_clock -period 10\n"),
        ("phase2/stage2/synth/netlist.v", "module %s(); endmodule\n" % top),
        # r4: the netlist PnR ACTUALLY reads, per `pnr_input_netlist`.
        ("phase2/stage2/synth/%s_synth.v" % top,
         "module %s(); endmodule\n" % top),
        ("phase3/stage3/pnr/routed.def", "VERSION 5.8 ;\nEND DESIGN\n"),
        ("phase3/stage3/pnr/constraint.sdc", "create_clock -period 10\n"),
        ("phase3/stage3/pnr/spare_cells.json", "{}\n"),
        ("phase3/stage3/extracted/parasitic.spef", "*SPEF\n"),
    ):
        p = project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.is_file():
            p.write_text(text)


def _seed_recording(kind: str) -> None:
    """R-0924-3 r5: `code` comes from what the step RAN, and a step with no
    recording gets NO cache — which is the point of r5. A fixture that stamps
    a tree without running the step through `_recorded` must therefore supply
    the recording a real run would have left. The recorder's own behaviour is
    covered by the r5 tests that drive it for real."""
    import _step_recorder as _sr
    # DERIVED, not invented: a hand-written digest would not survive
    # re-derivation (the check side recomputes these keys from CURRENT
    # source), so the stand-in is computed the same way a real recording is.
    _d, _err = _sr.check_digests(R.PROGRAMS_DIR / "_step_identity.py", [])
    assert not _err, _err
    R._STEP_RECORDING[kind] = ({
        "_step_identity.py": _d,
        "__engine_env__": {name: _sr._engine_marker(name)
                           for name in _sr.ENGINE_ENV},
    }, "")


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
    # R-0924-3 made that key the STEP's identity, so "a previous run produced
    # these" now also means: its declared inputs are on disk, its tool ledger
    # exists and its PDK is readable. Same catch-up, same reason.
    (pnr / "post_hold.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    (pnr / "metal_fill.done").write_text("fill complete\n")
    cons = tmp_path / "phase2" / "stage2" / "constraints"
    cons.mkdir(parents=True, exist_ok=True)
    (cons / "chip.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    (tmp_path / "provenance.jsonl").write_text("".join(
        json.dumps({"tool": t, "version": v,
                    "outputs": {o: "sha256:" + "0" * 64}}) + "\n"
        for t, v, o in (
            ("yosys", "0.38", f"phase2/stage2/synth/{TOP}_synth.v"),
            ("openroad", "2.0", f"phase3/stage3/pnr/{TOP}.def"),
            ("klayout", "0.28", f"phase3/stage4/gds/{TOP}.gds"))))
    # The declaration is step 9's FIRST declared input, so it must exist
    # before the identity that hashes it is stamped. (It is declared again
    # below where it was originally added; declaring twice is idempotent and
    # the original comment is left where it explains itself.)
    _declare(tmp_path, "DIE")
    _span_inputs(tmp_path, TOP)
    _ctx = dict(project=tmp_path, pdk=_pdk(tmp_path), container="",
                top=TOP, args=_IdentityArgs())
    _seed_recording("synth")
    R._write_producer_identity(synth, "synth", **_ctx)
    _seed_recording("pnr")
    R._write_producer_identity(pnr, "pnr", **_ctx)
    _seed_recording("gds")
    R._write_producer_identity(pnr, "gds", **_ctx)
    # The SECOND thing this fixture had to catch up with, and the same kind as
    # the post-DFT netlist above: v1.22.13 (#2376) made Phase 3 refuse a project
    # with no delivery declaration, BEFORE any step and before the report these
    # tests read is written, so all ten cases here died on a missing file rather
    # than on the geometry guard they assert. Admission still runs; this
    # supplies the input a tree that has reached PnR would carry, and DIE is the
    # deliverable these die-geometry and stale-GDS assertions are about.
    _declare(tmp_path, "DIE")
    # THE THIRD, and the same kind again -- and it is the declaration ABOVE
    # that reaches it: `declare_delivery` writes `SELF_TAPEOUT.txt`, which is
    # exactly what makes `_chip_path_requests_pad_ring` true for this project.
    # `_cached_stage_decision` then applies its pad-ring clause: on a chip path
    # the PnR cache is valid only while
    # `reports/phase3/pad_ring_route_evidence.json` still HASH-BINDS the DEF and
    # the GDS it was written for. Without it the run discloses
    #
    #   [pnr] cache invalid -- geometry unchanged (requested die=1500x1500
    #         util=0.3); producer unchanged (...); chip-path pad-ring route
    #         evidence absent, stale or hash-mismatched
    #
    # and PnR RE-RUNS on the unchanged-geometry arm. That re-run is what the
    # four cases here were actually failing on, and it costs them two different
    # ways: `test_unchanged_geometry_still_reuses_the_gds` sees the re-dispatch
    # it exists to forbid, and the three pad-side cases lose their subject --
    # `_fake_pnr` rewrites the DEF as `PINS 0`, erasing the pins
    # `_with_pad_table` had just placed, so the gate reads a DEF with nothing in
    # it and answers `VACUOUS_PASS: pad-side table present but no DEF pins
    # matched its patterns`.
    #
    # The premise this file states is "everything already exists from the
    # previous run", and on a DIE that has reached PnR that includes its route
    # evidence. `test_phase3_cache_producer_identity.py` caught up with the same
    # clause in the same way and owns its coverage.
    #
    # NOTHING IS FAKED and NOTHING IS DISABLED: both hashes are computed from
    # THIS fixture's own DEF and GDS, so the record binds the bytes it actually
    # describes, and the clause remains able to fire -- a stale record still
    # invalidates the cache, which is that clause's own suite's subject.
    _pad_ring_evidence(tmp_path)
    # This previous run's mask has both a byte receipt and a PASS gate for
    # the exact routed basis. The cache assertion below is unchanged from #593.
    basis, error = R._layout_basis(tmp_path, TOP, _pdk(tmp_path), "")
    assert not error, error
    gate = R._pl.reports_phase3_dir(tmp_path) / "prestream_gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": basis}) + "\n")
    R._ga.admit_gds(tmp_path, pnr / f"{TOP}.gds", basis,
                    R._layout_basis_paths(tmp_path, TOP))
    return tmp_path


def _pad_ring_evidence(project: Path) -> Path:
    """The route evidence a chip-path PnR leaves behind, hash-bound to it."""
    pnr = R._pl.pnr_dir(project)
    path = project / "reports" / "phase3" / "pad_ring_route_evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "verdict": "PASS",
        "gds_source_def_sha256": R._sha256_file(pnr / f"{TOP}.def"),
        "gds_evidence": {"sha256": R._sha256_file(pnr / f"{TOP}.gds")},
    }) + "\n")
    return path


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
        dest = out / f"{top}.def"
        lines = dest.read_text().splitlines(keepends=True) if dest.is_file() else []
        area = (f"DIEAREA ( 0 0 ) ( {int(float(w)) * 1000} "
                f"{int(float(h)) * 1000} ) ;\n")
        # A repeated PnR run changes the requested die; it does not silently
        # erase already placed pins from this pad-side fixture.
        lines = [area if line.startswith("DIEAREA ") else line for line in lines]
        dest.write_text("".join(lines) if lines else area + "PINS 0 ;\nEND PINS\n")
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
    # This suite owns the geometry-cache decision. Its synthetic DEF has no
    # extracted STA, IR/EM or antenna evidence, so the independent pre-stream
    # admission is supplied as an already-measured PASS for this fixture.
    # T47's runner tests exercise that gate's blocking/diagnostic branches.
    def _fake_gate(proj, top, pdk, container):
        basis, error = R._layout_basis(proj, top, pdk, container)
        assert not error, error
        gate = R._pl.reports_phase3_dir(proj) / "prestream_gate.json"
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": basis}) + "\n")
        return R.StepResult("prestream_gate", "PASS", 0.0,
                            "fixture's routed basis admitted",
                            extras={"layout_digest": basis})
    monkeypatch.setattr(R, "step_prestream_gate", _fake_gate)

    monkeypatch.setattr(R, "_detect_pdk",
                        lambda *a, **k: _pdk(project))
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
    # The GATE PROGRAM's own word, which R-0915-85 did not touch: it is
    # `pad_side_constraint_check`'s stdout, not a step status.
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

#: The step-32 producer the main flow calls: the deck's own repair
#: (`step_signoff_spef_repair`, where a project opts step 21/32 out) and, since
#: T102 r4's chip-path cut-over, the LibreLane one. The guard property is the
#: SAME for both rows, so both are asserted.
_REPAIR_PRODUCERS = {
    "direct": ("step_signoff_spef_repair", "signoff_spef_repair",
               {"21": "direct", "32": "direct"}),
    "librelane": ("step_postroute_repair_librelane", "postroute_repair_librelane",
                  None),
}


def _repair_producer(monkeypatch, project, producer, status, detail):
    fn, row, switch = _REPAIR_PRODUCERS[producer]
    if switch is not None:
        sw = project / "phase3" / "librelane_switch.json"
        sw.parent.mkdir(parents=True, exist_ok=True)
        settings = json.loads(sw.read_text()) if sw.is_file() else {}
        settings.setdefault("steps", {}).update(switch)
        sw.write_text(json.dumps(settings))
    monkeypatch.setattr(R, fn, lambda *a, **k: R.StepResult(row, status, 0.0, detail))
    if producer == "librelane":
        monkeypatch.setattr(R, "_librelane_postroute_repair_mode", lambda p: "librelane")
    return row


@pytest.mark.parametrize("producer", sorted(_REPAIR_PRODUCERS))
def test_an_appended_repair_row_does_not_disable_the_guard(tmp_path,
                                                           monkeypatch, producer):
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    row = _repair_producer(monkeypatch, project, producer, "PASS", "no repair needed")
    R.main()

    plan = _plan(project)
    assert row in plan
    assert "gds" in d.called, (
        "a repair row between PnR and the GDS block must not disable the "
        f"#593 guard; gds row: {plan['gds']['detail']!r}")


# ---------------------------------------------------------------------------
# MIGRATED by R-0929-TAIL-CONTINUES (root, IC expert, 2026-09-29). This case
# asserted that a FAILING repair row stops the GDS. The ruling reverses that: a
# measured Step-32 FAIL is recorded FAIL and keeps the run FAIL, but stream-out
# and the tail are still measured on the route it leaves. The case keeps both of
# its observations -- the FAIL row survives, and the run does not exit 0 -- and
# the stopping direction is kept where the ruling keeps it (a Step-32 row that
# leaves NO route): `test_r0929_tail_continues.py::test_step32_that_left_no_route_*`.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("producer", sorted(_REPAIR_PRODUCERS))
def test_a_failing_repair_row_is_kept_and_the_gds_is_still_measured(
        tmp_path, monkeypatch, producer):
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    d = _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    row = _repair_producer(monkeypatch, project, producer, "FAIL", "repair blew up")
    rc = R.main()

    plan = _plan(project)
    assert plan[row]["status"] == "FAIL"
    assert "gds" in d.called, (
        "R-0929-TAIL-CONTINUES: a measured Step-32 FAIL must not stop "
        f"stream-out; gds row: {plan.get('gds')}")
    assert rc != 0, "the Step-32 FAIL must keep the run FAIL"


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
    # This helper REPLACES the DEF the fixture bound its route evidence to, so
    # the binding must follow the bytes. Re-bind rather than widen the check:
    # the record still describes the exact DEF and GDS on disk, and a record
    # that does not is still rejected.
    _pad_ring_evidence(project)
    # R-0924-3 r4: `input/docs/L9*` is a DESIGN input and is now hashed, so
    # writing the pad table legitimately invalidates PnR — and a re-run would
    # overwrite the very DEF this helper just placed. The premise is "a
    # previous run that ALREADY had this table", so the stamp is taken after
    # it, exactly as a real previous run's would have been. Same fixture
    # catch-up as the four above, and the identity is doing its job.
    _ctx = dict(project=project, pdk=_pdk(project), container="",
                top=TOP, args=_IdentityArgs())
    pnr = R._pl.pnr_dir(project)
    R._write_producer_identity(R._pl.synth_dir(project), "synth", **_ctx)
    _seed_recording("pnr")
    R._write_producer_identity(pnr, "pnr", **_ctx)
    _seed_recording("gds")
    R._write_producer_identity(pnr, "gds", **_ctx)


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
    assert row["status"] == "NOT_MEASURED", (
        f"'could not parse the DEF' is not a pad-side violation: {row}")
