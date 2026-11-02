"""The phase-3 synth/PnR/GDS cache must be keyed on the RECIPE, not only on
the design inputs — EXECUTABLE, end-to-end through ``main()``.

THE DEFECT
==========
Every pre-existing key on this cache asks "did the INPUT change?":

  * ``_netlist_matches_liberty``                       — the PDK  (PR-A3)
  * ``_stale_rtl_by_fingerprint`` / ``_stale_rtl_vs_netlist``
                                                       — the RTL  (#289/#349)
  * ``_pnr_cache_valid_for``                           — the die  (#593/#596)

Not one of them asks "did the RECIPE change?". So a landed fix to the synth /
PnR / stream-out recipe is a SILENT NO-OP on any tree that already holds an
artefact: the flow reuses what the OLD code produced and reports PASS for code
that never ran. "We landed the fix, re-run to confirm" becomes structurally
unable to confirm anything.

MEASURED, three independent times in one convergence round:
  * a landed tie-cell fix left two steps failing with the exact message it was
    written to eliminate, until the netlist was moved aside BY HAND;
  * three staged files had to be deleted by hand before fixed emitters ran;
  * "netlist already present ... (skipped re-run to preserve provenance)" was
    followed by PnR reading the PREVIOUS DAY's DEF.

THE MUTATION THESE TESTS CATCH
==============================
Deleting any one of the three ``_producer_cache_valid_for`` call sites in
``main()`` — the #755 "fixed one site is not fixed the class" shape. Each of
the three producing steps has its own test below, so removing the key from any
one of them fails a named test rather than being absorbed by the other two.

A source-string test alone would not catch this: a permanently-True
``_prod_ok`` satisfies "the helper is mentioned in main()". These tests DRIVE
``main()`` and observe whether the step was actually invoked.

chip-AGNOSTIC: plugin version + runner source digest; no design, PDK, vendor
or part identifier anywhere.
"""
from __future__ import annotations

import ast
import inspect
import json
import sys

import pytest
from pathlib import Path

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402
from _delivery_declaration import declare_delivery as _declare  # noqa: E402

TOP = "chip_top"
DIE, UTIL = "200x200", 0.45


# ── unit level: the key itself ──────────────────────────────────────────────

from test_phase3_postpnr_disclosure_and_gds_guard import _own_runtime_invocation, _source_unit_transports


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
    # These cache controls use the legacy direct synthesis recipe, not a
    # LibreLane handoff. State that selection before computing its read-set.
    switch = project / 'phase3/librelane_switch.json'
    settings = json.loads(switch.read_text()) if switch.is_file() else {}
    settings.setdefault('steps', {}).setdefault('9', 'direct')
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


def _unit(tmp_path: Path) -> Path:
    """A minimal project the step identity can actually be computed for."""
    rtl = R._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{TOP}.v").write_text(f"module {TOP}(); endmodule\n")
    _declare(tmp_path, "DIE")
    cons = tmp_path / "phase2" / "stage2" / "constraints"
    cons.mkdir(parents=True, exist_ok=True)
    (cons / "chip.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    # The DECLARED inputs of the three cached steps, per the flow itself:
    # step 9 reads the declaration, the RTL and the SDC (above); step 21 reads
    # `post_hold.def`; step 37 reads `filled.def OR metal_fill.done`. R-0924-3
    # hashes a step's declared inputs, and a declared input that is absent is
    # an unanswerable question, not an empty one — so a tree missing them
    # re-runs for that reason rather than the one under test.
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "post_hold.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    (pnr / "metal_fill.done").write_text("fill complete\n")
    _provenance(tmp_path)
    _span_inputs(tmp_path, TOP)
    return tmp_path


def _valid(tmp_path: Path, out_dir: Path, kind: str, monkeypatch):
    return R._producer_cache_valid_for(
        out_dir, kind, project=tmp_path, pdk=_pdk(tmp_path), container="",
        top=TOP, args=_IdentityArgs())


def test_matching_producer_is_reusable(tmp_path, monkeypatch):
    """Control, and it is the load-bearing one: an artefact THIS build wrote
    stays reusable — the fix must not degenerate into 'always re-run'.

    This assertion caught a real defect in the R-0924-3 change while it was
    being written: the PDK component was hashed host-side, every PDK file on
    the measured configuration lives only inside the container, so the
    component was permanently uncomputable and nothing would ever have been
    reused. Do not weaken it."""
    project = _unit(tmp_path)
    out = R._pl.synth_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "synth")
    ok, msg = _valid(project, out, "synth", monkeypatch)
    assert ok is True, msg
    assert "step unchanged" in msg


def test_a_version_bump_alone_no_longer_invalidates(tmp_path, monkeypatch):
    """SUPERSEDED AND INVERTED BY OWNER RULING R-0924-3 (2026-09-24).

    This test used to be `test_older_plugin_version_invalidates`, and it
    asserted that an artefact written by an earlier plugin build was never
    reusable. That WAS the contract, and it was the wrong one: because every
    landed fix bumps the version, it invalidated every cached step in the flow
    whatever the fix touched. MEASURED on spm run23 — `--force-step gds` on a
    finished tree re-ran synthesis and started PnR.

    R-0924-3: "freshness is judged PER STEP by what that step actually depends
    on ... not by the whole-plugin version." So the assertion is inverted, and
    deliberately kept HERE rather than deleted, so the history of the contract
    is visible at the place that used to enforce the opposite.

    What replaced it is not weaker: a step whose CODE changed still
    invalidates, which is what a version bump was ever a proxy for, and
    `test_edited_code_invalidates_without_a_version_bump` below holds that
    directly instead of by proxy."""
    project = _unit(tmp_path)
    out = R._pl.synth_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "synth")
    monkeypatch.setattr(R, "_plugin_version", lambda: "99.99.99-brand-new")
    ok, msg = _valid(project, out, "synth", monkeypatch)
    assert ok is True, (
        "a release with no change to this step's inputs, code, tools or PDK "
        f"re-ran it anyway — R-0924-3 forbids exactly this. {msg}")


def test_edited_code_invalidates_without_a_version_bump(tmp_path, monkeypatch):
    """The in-tree case a released version number cannot see: same version,
    edited code. This is the shape an agent testing its own fix hits on every
    iteration, and it is now held DIRECTLY rather than through a version
    proxy — including for a helper module, which the old key could not see at
    all and said so in a comment instead of fixing."""
    project = _unit(tmp_path)
    out = R._pl.pnr_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "pnr")
    assert _valid(project, out, "pnr", monkeypatch)[0] is True
    import _step_identity as _si
    rec = _si.read_sidecar(out, "pnr")
    rec["code"] = "0" * 64          # what an edit to this step's code does
    _si.write_sidecar(out, "pnr", rec)
    ok, msg = _valid(project, out, "pnr", monkeypatch)
    assert ok is False, msg
    assert "code:" in msg


def test_unstamped_artefact_fails_closed(tmp_path, monkeypatch):
    """Every artefact that exists TODAY has no stamp. Absence of evidence is
    not evidence of freshness: reuse requires positive proof."""
    project = _unit(tmp_path)
    out = R._pl.pnr_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    ok, msg = _valid(project, out, "gds", monkeypatch)
    assert ok is False
    assert "no recorded step identity" in msg, msg


def test_unreadable_stamp_fails_closed(tmp_path, monkeypatch):
    """A corrupt stamp is unreadable evidence, therefore no evidence."""
    import _step_identity as _si
    project = _unit(tmp_path)
    out = R._pl.synth_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    (out / _si.SIDECAR).write_text("{not json")
    assert _valid(project, out, "synth", monkeypatch)[0] is False


def test_unresolvable_current_identity_fails_closed(tmp_path, monkeypatch):
    """If THIS build cannot name what it is running, it cannot prove a match
    either. Under R-0924-3 the thing it must be able to name is no longer a
    version string but the image its tools ran in."""
    project = _unit(tmp_path)
    out = R._pl.synth_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "synth")
    assert _valid(project, out, "synth", monkeypatch)[0] is True
    monkeypatch.setattr(R, "_step_image_digest", lambda c: None)
    ok, msg = R._producer_cache_valid_for(
        out, "synth", project=project, pdk=_pdk(project), container="",
        top=TOP, args=_IdentityArgs())
    assert ok is False, "an unnameable image is not a proven image"


def test_a_pdk_that_cannot_be_read_still_refuses(tmp_path, monkeypatch):
    """The fail-closed rule the readable-PDK fixture must not be mistaken for
    relaxing: a PDK whose files cannot be hashed is not a matching PDK."""
    project = _unit(tmp_path)
    out = R._pl.synth_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "synth")
    ok, msg = R._producer_cache_valid_for(
        out, "synth", project=project, pdk=_pdk(None), container="",
        top=TOP, args=_IdentityArgs())
    assert ok is False, msg
    assert "pdk" in msg


def test_the_tool_ledger_is_not_the_source_of_the_tools_component(
        tmp_path, monkeypatch):
    """SUPERSEDED BY ROUND-4 REVIEW FINDING 4, and the replacement is the
    stronger contract.

    This test used to delete `provenance.jsonl` and require a re-run, on the
    reasoning that a tree which cannot say which tools made its artefacts
    cannot prove them current. That reasoning still holds — but the LEDGER is
    the wrong place to ask. `step_canonicalize_artefacts` keeps APPENDING to
    it AFTER the stamps, with version-less reconstructed rows (measured on
    spm_gf180_cleanrun_20260829_1819: yosys -> "", pnr tools -> None), so
    re-reading it made the component move on every no-op re-run. The ledger is
    a record of the past and it grows; a freshness key may not be read from it.

    The tools a step ran are now PROBED at stamp time and CARRIED in the
    stamp, so the tree still says which tools made the artefact — it just says
    it in the stamp, which does not grow underneath the answer. The ledger
    vanishing afterwards is therefore correctly irrelevant, and what still
    forces a re-run is an environment that cannot be named at all (the image),
    which `test_unresolvable_current_identity_fails_closed` holds."""
    project = _unit(tmp_path)
    out = R._pl.synth_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "synth")
    assert _valid(project, out, "synth", monkeypatch)[0] is True
    import _step_identity as _si
    rec = _si.read_sidecar(out, "synth")
    assert rec.get("probed_tools") is not None, (
        "the stamp must CARRY what it probed, or the ledger is still the "
        f"source: {sorted(rec)}")
    (project / "provenance.jsonl").unlink()
    ok, why = _valid(project, out, "synth", monkeypatch)
    assert ok is True, (
        f"the ledger vanished and the stamp still knows what ran: {why}")


def test_kinds_are_recorded_separately(tmp_path, monkeypatch):
    """A run that re-derived the DEF but reused the GDS is exactly the #593
    shape; one shared record could not express it."""
    project = _unit(tmp_path)
    out = R._pl.pnr_dir(project)
    out.mkdir(parents=True, exist_ok=True)
    _stamp(project, out, "pnr")
    assert _valid(project, out, "pnr", monkeypatch)[0] is True
    assert _valid(project, out, "gds", monkeypatch)[0] is False, (
        "stamping the DEF must not silently vouch for the GDS")
    _stamp(project, out, "gds")
    assert _valid(project, out, "pnr", monkeypatch)[0] is True, (
        "stamping the GDS must not erase the DEF's stamp")


def test_forced_reuse_is_permanently_disclosed(tmp_path, monkeypatch):
    """The escape hatch may buy back the reuse; it may NEVER buy back the
    appearance of freshness. The token must reach the step detail, which is
    what the published JSON report carries."""
    monkeypatch.setenv(R._STALE_PRODUCER_ENV, "1")
    ok, msg = R._producer_cache_valid_for(tmp_path, "synth")
    assert ok is True, "the documented override must actually permit reuse"
    assert "PRODUCER-STALE" in msg and R._STALE_PRODUCER_ENV in msg


def test_one_version_reader_for_the_whole_repo():
    """The plugin version must come from `plugin_manifest_discovery`, the
    repo's one reader. A second reader here is how the two drift apart
    (#309/#312/#348) — the producer/consumer split this campaign keeps
    re-finding."""
    import inspect
    src = inspect.getsource(R._plugin_version)
    assert "plugin_manifest_discovery" in src
    assert "plugin.json" not in src, (
        "a private second plugin.json reader was introduced — use the shared "
        "one so a manifest-layout change cannot desynchronise them")


# ── end-to-end: all THREE call sites, driven through main() ─────────────────

def _pdk(root: Path | None = None) -> R.PdkConfig:
    """THE FOURTH FIXTURE CATCH-UP, and the same kind as the three below.

    R-0924-3 made freshness the STEP's own identity, and one of its four
    components is the sha256 of the PDK files the step reads. `/nonexistent`
    paths are, correctly, unreadable, and an unreadable PDK is not a matching
    PDK — so with them nothing can ever be judged fresh and every test here
    would assert about a re-run that happened for the wrong reason. Given a
    root, the three declared PDK files are written for real, so the component
    is computable and the cache verdict under test is the one observed.

    NOTHING IS RELAXED: `test_a_pdk_that_cannot_be_read_still_refuses` keeps
    the unreadable case, which is the fail-closed rule itself."""
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
    pdk_dir = Path(root).parent / "_pdk_outside"
    pdk_dir.mkdir(parents=True, exist_ok=True)
    lib = pdk_dir / "tt.lib"
    tlef = pdk_dir / "tech.lef"
    clef = pdk_dir / "cells.lef"
    for f, text in ((lib, "library(testpdk){}\n"),
                    (tlef, "VERSION 5.8 ;\n"), (clef, "MACRO unit\n")):
        if not f.is_file():
            f.write_text(text)
    return R.PdkConfig(name="testpdk", liberty=str(lib), tech_lef=str(tlef),
                       cell_lef=str(clef), cell_gds=None, site="unit",
                       drc_deck=None)






def _provenance(project: Path) -> None:
    """The run ledger a tree that has already produced these artefacts carries.

    R-0924-3's `tools` component asks the run's OWN `provenance.jsonl` which
    tools this step invoked, rather than trusting a list kept in sync by hand.
    A tree with no ledger cannot answer, so it re-runs — which is right, and is
    why `test_a_tree_with_no_tool_ledger_re_runs` keeps that case. This fixture
    supplies what a real tree has: measured on a real stream-out run, the
    output prefixes are exactly `phase2/stage2/synth/`, `phase3/stage3/pnr/`
    and `phase3/stage4/gds/`."""
    (project / "provenance.jsonl").write_text("".join(
        json.dumps({"tool": tool, "version": ver,
                    "outputs": {out: "sha256:" + "0" * 64}}) + "\n"
        for tool, ver, out in (
            ("yosys", "0.38", f"phase2/stage2/synth/{TOP}_synth.v"),
            ("openroad", "2.0", f"phase3/stage3/pnr/{TOP}.def"),
            ("klayout", "0.28", f"phase3/stage4/gds/{TOP}.gds"))))


class _IdentityArgs:
    """The knobs R-0924-3 r3 folds into a step's identity — `--spare-density`
    and the env vars are inputs the step reads that are not files, so the
    fixtures must name them as a real invocation would."""
    spare_density = 0.02
    container = ""


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
                           for name in _sr.ENGINE_ENV}}, "")


def _stamp(project: Path, out_dir: Path, kind: str) -> None:
    """Stamp `kind` the way a real run does — with the context the step
    identity is computed from."""
    _seed_recording(kind)
    R._write_producer_identity(out_dir, kind, project=project,
                               pdk=_pdk(project), container="",
                               top=TOP, args=_IdentityArgs())


def _project(tmp_path: Path, *, stamp: bool) -> Path:
    """The 'everything already exists from a previous run' state. `stamp`
    decides whether that previous run was THIS build or an unknown one."""
    pnr = R._pl.pnr_dir(tmp_path)
    synth = R._pl.synth_dir(tmp_path)
    rtl = R._pl.rtl_dir(tmp_path)
    for d in (pnr, synth, rtl):
        d.mkdir(parents=True, exist_ok=True)
    (rtl / f"{TOP}.v").write_text(f"module {TOP}(); endmodule\n")
    (synth / f"{TOP}_synth.v").write_text("// cached netlist\n")
    # The DECLARED input of the PnR step, owed by step 12 and read by step 15.
    # Not decoration: `step_preflight` refuses to dispatch a step whose declared
    # inputs are absent, and it landed AFTER this fixture was written. Without
    # this file the runner never reaches the cache decision at all — the pnr row
    # comes back BLOCKED/REFUSED TO RUN and the two tests below assert about a
    # step that was never offered the chance to be cached or re-run.
    #
    # This is the fixture catching up with the flow, NOT a relaxation: preflight
    # still refuses when the input is genuinely absent (that is its own suite's
    # subject), and the tests below still fail if the producer key is removed
    # from their call site, which is the mutation they exist to catch.
    (synth / "post_dft_netlist.v").write_text("// cached post-DFT netlist\n")
    (pnr / f"{TOP}.def").write_text(
        "DIEAREA ( 0 0 ) ( 200000 200000 ) ;\nPINS 0 ;\nEND PINS\n")
    (pnr / f"{TOP}.gds").write_text("cached GDS\n")
    # The DECLARED inputs of the two phase-3 cached steps — step 21 reads
    # `post_hold.def`, step 37 reads `filled.def OR metal_fill.done`. Same
    # kind of catch-up as the post-DFT netlist above: R-0924-3 hashes a step's
    # declared inputs, and a tree that has already routed and streamed out
    # carries them.
    (pnr / "post_hold.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    (pnr / "metal_fill.done").write_text("fill complete\n")
    # ...and step 9's third declared input, the SDC owed by step 7.
    cons = tmp_path / "phase2" / "stage2" / "constraints"
    cons.mkdir(parents=True, exist_ok=True)
    (cons / "chip.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    R._write_pnr_args_sidecar(pnr, DIE, UTIL)
    R._write_synth_inputs_sidecar(synth / f"{TOP}_synth.v", rtl)
    _provenance(tmp_path)
    _span_inputs(tmp_path, TOP)
    # Step 9's first declared input; it must exist before the identity that
    # hashes it is stamped. Declared again below, where the comment that
    # explains why it is here at all lives; declaring twice is idempotent.
    _declare(tmp_path, "DIE")
    if stamp:
        _stamp(tmp_path, synth, "synth")
        _stamp(tmp_path, pnr, "pnr")
        _stamp(tmp_path, pnr, "gds")
    # The SECOND thing this fixture had to catch up with, and the same kind as
    # the post-DFT netlist above: v1.22.13 (#2376) made Phase 3 refuse a project
    # with no delivery declaration, BEFORE any step and before the report these
    # tests read is written, so the six cases here died on a missing file rather
    # than on the cache verdict they assert. Admission still runs; this supplies
    # the input a tree that has reached PnR would carry.
    _declare(tmp_path, "DIE")
    # THE THIRD, and the same kind again. `_cached_stage_decision` gained a
    # pad-ring clause: on a chip path the PnR cache is valid only while
    # `reports/phase3/pad_ring_route_evidence.json` still HASH-BINDS the DEF
    # and the GDS it was written for. Without it the disclosure reads
    #
    #   [pnr] cache invalid — geometry unchanged (...); producer unchanged
    #         (...); chip-path pad-ring route evidence absent, stale or
    #         hash-mismatched
    #
    # and PnR re-runs for a reason that is not the producer key these tests are
    # about. The premise is "everything already exists from the previous run",
    # and on a DIE that has reached PnR that includes its route evidence.
    #
    # NOTHING IS FAKED: the two hashes are computed from THIS fixture's own DEF
    # and GDS, so the record binds the bytes it actually describes — which is
    # what makes the clause still able to fire (see
    # `test_a_stale_pad_ring_record_still_invalidates_the_pnr_cache`).
    _pad_ring_evidence(tmp_path)
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


def _drive(monkeypatch, project: Path) -> list:
    """Neutralise everything main() does that is not the cache decision, and
    record which steps it invokes. The producer helpers are LEFT REAL — the
    cache verdict is what is under test."""
    _own_runtime_invocation(monkeypatch)
    _source_unit_transports(monkeypatch)
    called: list = []
    import execution_policy
    original_request = execution_policy.request
    # The old three-kind cache is a legacy-unit responsibility. A bare GDS
    # cache does not stand in for Default's current finishing/consumer chain.
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='ultra'))
    monkeypatch.setattr(execution_policy, 'bootstrap', lambda *a, **k: None)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    # This legacy recipe/cache unit has no native LOCAL runtime or current
    # canonical PnR receipt. Substitute only that unrelated transport, as the
    # geometry-cache fixture does; real cache/recording predicates stay live.
    monkeypatch.setattr(R, '_backend_parameter_values', lambda *a, **k: {})
    monkeypatch.setattr(R, '_default_step15_with_backend_receipt',
                        lambda *a, **k: R.step_pnr(*a, **k))

    def _touch_active_recipe(project):
        # Every recorded source-unit span, including no-op repairs, executes
        # this real retained helper. Live imports and test-only lambdas cannot
        # establish what ran inside the active retained tree.
        import runpy
        runpy.run_path(str(R.PROGRAMS_DIR / "_path_layout.py"))["pnr_dir"](project)

    def _step(name):
        def _f(*a, **k):
            called.append(name)
            _touch_active_recipe(a[0] if a else Path("."))
            return R.StepResult(name, "PASS", 0.0, f"{name} ok")
        return _f

    for attr in ("step_synth", "step_pnr", "step_gds", "step_drc", "step_lvs",
                 "step_canonicalize_artefacts"):
        monkeypatch.setattr(R, attr, _step(attr[len("step_"):]))
    def _no_repair(*a, **k):
        _touch_active_recipe(a[0])
        return None

    for attr in ("step_signoff_spef_repair", "step_postroute_repair_librelane",
                 "step_signoff_drv_wire_length_repair"):
        monkeypatch.setattr(R, attr, _no_repair)
    # This fixture tests cache identity with synthetic route and timing data.
    # Its independent pre-stream admission is supplied as a measured premise;
    # the cache and GDS dispatch assertions below remain unchanged.
    def _fake_gate(proj, top, pdk, container):
        basis, error = R._layout_basis(proj, top, pdk, container)
        assert not error, error
        gate = R._pl.reports_phase3_dir(proj) / "prestream_gate.json"
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text(json.dumps({"verdict": "PASS", "layout_digest": basis}) + "\n")
        return R.StepResult("prestream_gate", "PASS", 0.0,
                            "fixture routed basis admitted",
                            extras={"layout_digest": basis})
    monkeypatch.setattr(R, "step_prestream_gate", _fake_gate)
    # The public entry now requires the case to declare the selected fixture PDK.
    declared = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    declared.parent.mkdir(parents=True, exist_ok=True)
    declared.write_text(json.dumps({"fields": {"pdk_target": _pdk(project).name}}))
    monkeypatch.setattr(R, "_detect_pdk",
                        lambda *a, **k: _pdk(project))
    # R-0924-3: an image nobody can name is not a proven image, so the
    # tools component refuses without one and every step re-runs. A real
    # run has a digest; these tests are about the CACHE verdict, so it is
    # supplied rather than left to a container this suite does not have.
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
        "--die-um", DIE, "--util", str(UTIL), "--container", "",
    ])
    return called


def _plan(project: Path):
    doc = json.loads(
        R._pl.report_path(project, "phase3_one_shot.json").read_text())
    return {s["name"]: s for s in doc["steps"]}


# THE REGRESSION, one test per call site so removing the key from ONE of the
# three fails a named test instead of hiding behind the other two.

def test_unstamped_netlist_forces_a_synth_rerun(tmp_path, monkeypatch):
    """MUTATION CAUGHT: deleting the producer key at the synth call site."""
    project = _project(tmp_path, stamp=False)
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" in called, (
        "an unstamped netlist was reused: every synth fix landed since it was "
        f"written is a silent no-op. synth row: {_plan(project)['synth']}")


def test_unstamped_def_forces_a_pnr_rerun(tmp_path, monkeypatch):
    """MUTATION CAUGHT: deleting the producer key at the PnR call site.
    The netlist IS stamped, so only the PnR key can force this re-run."""
    project = _project(tmp_path, stamp=False)
    _stamp(project, R._pl.synth_dir(project), "synth")
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" not in called, "control: the stamped netlist must be reused"
    assert "pnr" in called, (
        f"an unstamped DEF was reused. pnr row: {_plan(project)['pnr']}")


def test_unstamped_gds_forces_a_gds_rerun(tmp_path, monkeypatch):
    """MUTATION CAUGHT: deleting the producer key at the GDS call site.
    Netlist and DEF are stamped, so only the GDS key can force this re-run —
    and the stream-out recipe can change while the router does not."""
    project = _project(tmp_path, stamp=False)
    _stamp(project, R._pl.synth_dir(project), "synth")
    _stamp(project, R._pl.pnr_dir(project), "pnr")
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" not in called and "pnr" not in called, (
        f"control: stamped netlist+DEF must be reused; called={called}")
    assert "gds" in called, (
        f"an unstamped GDS was reused. gds row: {_plan(project)['gds']}")


def test_a_stale_pad_ring_record_still_invalidates_the_pnr_cache(
        tmp_path, monkeypatch):
    """THE CONTROL FOR THE FIXTURE'S OWN THIRD CATCH-UP.

    `_project` now writes `reports/phase3/pad_ring_route_evidence.json`, because
    without it the chip-path clause in `_cached_stage_decision` invalidates the
    PnR cache for a reason none of these tests is about. Supplying evidence is
    only honest if the clause can still FIRE — otherwise the fixture would have
    switched a guard off and every cache assertion above would be green over a
    check that no longer runs.

    So: the same tree, with the record's GDS hash no longer binding the GDS it
    describes. The clause must refuse the cached route and PnR must re-run.
    """
    project = _project(tmp_path, stamp=True)
    rec = project / "reports" / "phase3" / "pad_ring_route_evidence.json"
    doc = json.loads(rec.read_text())
    doc["gds_evidence"]["sha256"] = "0" * 64        # no longer the shipped GDS
    rec.write_text(json.dumps(doc) + "\n")

    called = _drive(monkeypatch, project)
    R.main()
    assert "pnr" in called, (
        f"a pad-ring record that no longer binds its GDS was accepted; "
        f"pnr row: {_plan(project)['pnr']}")


def test_stamped_tree_still_hits_every_cache(tmp_path, monkeypatch):
    """The other direction, without which the three tests above would pass on
    an 'always re-run' mutation. Same build, same inputs, same geometry: the
    provenance-preserving reuse #593/v1.6.36 kept is UNCHANGED."""
    project = _project(tmp_path, stamp=True)
    called = _drive(monkeypatch, project)
    R.main()
    assert "synth" not in called and "pnr" not in called \
        and "gds" not in called, (
        f"a same-build re-run must still hit all three caches; called={called}")
    plan = _plan(project)
    for name in ("synth", "pnr", "gds"):
        assert "skipped re-run" in plan[name]["detail"]


def test_a_real_rerun_stamps_the_producer(tmp_path, monkeypatch):
    """The write side: after a producing step actually runs, the NEXT run must
    be able to prove the artefact is current. Without this the fix would
    re-run forever and would be reverted."""
    project = _project(tmp_path, stamp=False)
    called = _drive(monkeypatch, project)
    R.main()
    assert {"synth", "pnr", "gds"} <= set(called)
    ctx = dict(project=project, pdk=_pdk(project), container="")
    for kind, out in (("synth", R._pl.synth_dir(project)),
                      ("pnr", R._pl.pnr_dir(project)),
                      ("gds", R._pl.pnr_dir(project))):
        ok, msg = R._producer_cache_valid_for(
            out, kind, top=TOP, args=_IdentityArgs(), **ctx)
        assert ok is True, (
            f"after {kind} actually ran, the next run could not prove its "
            f"artefact current — the fix would re-run forever: {msg}")


def test_a_failed_step_does_not_stamp_a_producer(tmp_path, monkeypatch):
    """A FAILED synth must not stamp the netlist it did not produce —
    otherwise the next run would vouch for an artefact from the old build."""
    project = _project(tmp_path, stamp=False)
    _drive(monkeypatch, project)
    monkeypatch.setattr(
        R, "step_synth",
        lambda *a, **k: R.StepResult("synth", "FAIL", 0.0, "yosys died"))
    R.main()
    # WITH the full context — without it the predicate refuses for want of a
    # project and this assertion would pass for a reason that has nothing to
    # do with the failed step, which is a vacuous green, not a green.
    assert R._producer_cache_valid_for(
        R._pl.synth_dir(project), "synth", project=project,
        pdk=_pdk(project), container="", top=TOP,
        args=_IdentityArgs())[0] is False, (
        "a FAILED synth stamped a step identity onto the previous build's "
        "netlist — the next run would then reuse it as if it were current")


def test_reused_rows_name_the_producing_build(tmp_path, monkeypatch):
    """A stderr banner is lost in a log; the published JSON report is what
    every downstream gate and every human reads. A reused row must say which
    build produced the artefact, IN the report."""
    project = _project(tmp_path, stamp=True)
    _drive(monkeypatch, project)
    R.main()
    plan = _plan(project)
    for name in ("synth", "pnr", "gds"):
        detail = plan[name]["detail"]
        # R-0924-3: the row discloses WHY the step was judged unchanged, which
        # is strictly more than the build string it used to carry — a reader
        # can now see which of the four components was compared.
        assert "step unchanged" in detail, (
            f"the reused {name} row does not disclose its freshness basis: "
            f"{detail!r}")
        for component in ("inputs", "code", "tools", "pdk"):
            assert component in detail, (
                f"the reused {name} row names no {component} evidence: "
                f"{detail!r}")


#: The producer KINDS this runner has. Not a count of call sites — see
#: `_producer_kinds`.
_PRODUCER_KINDS = {"synth", "pnr", "gds"}


def _producer_kinds(src: str, fn: str):
    """(kinds, unreadable) — the `kind` literal each `fn(...)` call site names.

    WHY A SET OF KINDS AND NOT A COUNT OF CALL SITES. This guard existed as
    `src.count("_write_producer_identity(") == 3`, and MEASURED on live main
    7903c1972305 (2026-09-03, host load 6.3, pinned image
    sha256:66c33ff2...) that read 4:

        E   AssertionError: each producing call site must stamp on success;
            found 4

    The fourth site is `phase3_one_shot_runner.py:47353`,
    `_write_producer_identity(_pl.pnr_dir(project), "pnr")`, added by
    `551560ba18` (PDN/EM first-pass resize, v1.14.30): when EM sizing forces a
    resize the PnR step is RE-DISPATCHED, so the SAME producer kind is stamped
    a second time. There is no fourth producing KIND — the runner still
    produces synth, pnr and gds — so the defect this tripwire exists to catch
    (#755: "a fourth producing step added without the key") did not happen.
    The guard was counting TEXT OCCURRENCES, which cannot tell a legitimate
    re-stamp from a new unguarded producer.

    Raising 3 to 4 would freeze an instant into a contract: the next
    re-dispatch expires it again, and it would STILL pass a genuinely new
    `_write_producer_identity(..., "drc")` site, because that is also 4.
    Deleting it would leave the #755 shape unguarded. So the population is
    defined by BEHAVIOUR — which producer kinds does `main()` stamp and
    consult — which is blind to re-stamping and loud about a new kind.

    A call site whose kind is not a readable string literal is returned in
    `unreadable` and is a FAILURE, not a silent skip: a guard that cannot read
    a site cannot vouch for it, and a computed kind is exactly how a new
    producer would arrive unseen.
    """
    kinds, unreadable = [], []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.id if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", None))
        if name != fn:
            continue
        kind = node.args[1] if len(node.args) > 1 else None
        for kw in node.keywords:
            if kw.arg == "kind":
                kind = kw.value
        if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
            kinds.append(kind.value)
        else:
            unreadable.append(ast.unparse(node))
    return kinds, unreadable


#: The functions `main()` may consult the producer key THROUGH.
#:
#: vibe-ic#2166 moved the PnR and GDS reuse decisions out of `main()` into
#: `_cached_stage_decision`, because `main()` is not reachable from a test with
#: a prepared directory and so nothing about those decisions could be asserted
#: except by reading the source — the shape #2157 measured the cost of. The
#: `kind` LITERAL is still written at the call site in `main()`, so this guard
#: still reads it there and still fails on a producing kind that arrives with
#: no reuse consult. What moved is the NAME of the function the literal is
#: handed to, not the property. Both names are listed so a re-inline of either
#: call site is covered by the same population.
_CONSULTING_CALLS = ("_producer_cache_valid_for", "_cached_stage_decision")


def _consulted_kinds(src: str):
    """(kinds, unreadable) unioned over every consulting call `main()` makes."""
    kinds, unreadable = [], []
    for fn in _CONSULTING_CALLS:
        k, u = _producer_kinds(src, fn)
        kinds += k
        unreadable += u
    return kinds, unreadable


def test_all_three_call_sites_are_wired():
    """Tripwire for a fourth producing KIND being added without the key —
    the #755 shape ('fixed one site' vs 'fixed the class').

    Every kind the runner STAMPS must also be a kind it CONSULTS on reuse, and
    the two sets must be exactly the kinds this runner produces. A kind
    stamped but never consulted is an artefact nothing revalidates; a kind
    consulted but never stamped can never be reused at all.
    """
    src = inspect.getsource(R.main)
    stamped, stamp_bad = _producer_kinds(src, "_write_producer_identity")
    consulted, consult_bad = _consulted_kinds(src)

    assert not stamp_bad and not consult_bad, (
        "a producer call site names a kind this guard cannot read, so it "
        f"cannot vouch for it: {stamp_bad + consult_bad}")
    assert set(stamped) == _PRODUCER_KINDS, (
        f"the runner stamps producer kinds {sorted(set(stamped))}; the "
        f"guarded set is {sorted(_PRODUCER_KINDS)}. A new producing kind must "
        f"arrive WITH its cache key, not after it")
    assert set(consulted) == _PRODUCER_KINDS, (
        f"the runner consults producer kinds {sorted(set(consulted))}; the "
        f"guarded set is {sorted(_PRODUCER_KINDS)}. A reuse decision made "
        f"without the producer key is the #755 shape")


def test_the_kind_guard_still_refuses_a_new_unguarded_producer():
    """CONTROL, the direction that must stay RED.

    The counting form could not tell these two apart. This one must: a new
    KIND is a defect, a second stamp of an existing kind is the PDN/EM
    re-dispatch and is not.
    """
    src = inspect.getsource(R.main)

    # (a) a genuinely new producing kind, stamped and never consulted
    grown = src + (
        "\n\ndef _synthetic_new_producer(project):\n"
        "    _write_producer_identity(_pl.drc_dir(project), 'drc')\n")
    kinds, bad = _producer_kinds(grown, "_write_producer_identity")
    assert not bad
    assert set(kinds) != _PRODUCER_KINDS, (
        "a fourth producing KIND did not move the guarded set — the tripwire "
        "would not have caught the #755 shape it exists for")

    # (b) the measured legitimate case: the SAME kind stamped twice
    restamped = src + (
        "\n\ndef _synthetic_redispatch(project):\n"
        "    _write_producer_identity(_pl.gds_dir(project), 'gds')\n")
    kinds, bad = _producer_kinds(restamped, "_write_producer_identity")
    assert not bad
    assert set(kinds) == _PRODUCER_KINDS, (
        "a re-dispatch that stamps an existing kind a second time moved the "
        "guarded set; that is the false red this guard was rebuilt to stop")

    # (c) a kind the guard cannot read is a refusal, never a silent pass
    computed = src + (
        "\n\ndef _synthetic_computed_kind(project, kind):\n"
        "    _write_producer_identity(_pl.pnr_dir(project), kind)\n")
    _kinds, bad = _producer_kinds(computed, "_write_producer_identity")
    assert bad, (
        "a call site whose kind is a variable was read as if it named none; "
        "that is how a new producer arrives unseen")


def test_container_pdk_digest_uses_progress_supervision_and_refuses_stall(
        tmp_path, monkeypatch):
    import subprocess
    import _container_exec as CE

    path = str(tmp_path / "remote.lib")  # absent on host, resolved in container
    digest = "a" * 64
    results = [CE.STALLED_RC, 0]
    calls = []

    def supervised(container, cmd, **kwargs):
        calls.append((container, cmd, kwargs))
        return subprocess.CompletedProcess([], results.pop(0),
                                           f"{digest}  {path}\n", "")

    monkeypatch.setattr(CE, "run_in_container_supervised", supervised)
    monkeypatch.setattr(CE, "run_in_container", lambda *a, **k:
                        pytest.fail("a clock deadline was used"))
    R._STEP_PDK_HASH_CACHE.clear()
    hash_paths = R._step_pdk_hasher("calibration-container")
    assert hash_paths([path]) == {}, "a stalled run cannot prove a digest"
    assert hash_paths([path]) == {path: digest}, (
        "a completed supervised probe must still supply its digest")
    assert len(calls) == 2
    assert all(c[2] == {"ceiling_s": 120} for c in calls)
