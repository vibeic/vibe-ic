#!/usr/bin/env python3
"""#1215 — the SIGNOFF-layer EM INCOMPLETE convergence: all three benchmark
ICs died in phase3 sign-off with em_current_authority.json = INCOMPLETE and
perc_equivalent.json = PERC_EQUIV_INCOMPLETE, the SAME signature on every
design.

KIND, NAMED BEFORE FIXING (per the repo's INCOMPLETE discipline): kind (c) —
the measurement authority EXISTS under an unreachable path. The Jmax
reference (tech-LEF DCCURRENTDENSITY) is present in BOTH shipped PDKs
(measured inside the vibeic-eda image 2026-08-31: gf180mcuD tlefs carry 9
statements each, sky130A tlefs carry 10), but `/foss/pdks` is image-internal,
`$PDK_ROOT` is unset on the host where the gate runs, and no run tree carries
a `*.tlef` — so `_discover_jmax_ref` returned (None, None) on every run of
every design and the gate's honest verdict was INCOMPLETE forever.

THE FIX (runner, not the gate): `_emit_em_current_authority` stages the ONE
resolved `pdk.tech_lef` into the project (`phase3/pdk_stage/`, the existing
gitignored convention) and runs `em_peak_current_authority_check --tech-lef`
so the peak current reaches a COMPARISON; the Step-28 PERC aggregate's EM
category then reads that comparison's verdict instead of staying INCOMPLETE
on the measurement-only em.json.

NEVER-RELABEL GUARANTEE, tested here in both directions:
  * authority reachable  -> a MEASURED verdict (PASS on clean currents, FAIL
    when a segment is over Jmax — the mutation control);
  * authority genuinely absent -> the SAME honest INCOMPLETE as before the
    fix, never a promotion.

chip-AGNOSTIC: fixtures use LEF/CSV grammar only; no PDK, layer set, or
design literal is load-bearing (layer names below are arbitrary tokens).
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

# tempfile.mkdtemp, not tmp_path: the containerised suite's tmp_path carries
# a trailing-newline component that breaks path round-trips (see
# vibeic-eda pytest note); mkdtemp is safe in both worlds.


def _mk_project(peak_current_a: float) -> Path:
    """A minimal project carrying the two artefacts the authority gate reads:
    an em.rpt (peak + declared supply authority) and an em_segments.csv."""
    proj = Path(tempfile.mkdtemp(prefix="i1215_"))
    rpt3 = proj / "reports" / "phase3"
    rpt3.mkdir(parents=True)
    (rpt3 / "em.rpt").write_text(
        "########## EM analysis ###############\n"
        "Net              : VDD\n"
        "Total power      : 2.19e-02 W\n"
        "Supply voltage   : 5.00e+00 V\n"
        "Maximum current    : 3.69e-03 A\n"
        "segments_analysed: 2\n")
    (rpt3 / "em_segments.csv").write_text(
        "Node0 Layer,Node0 X location,Node0 Y location,"
        "Node1 Layer,Node1 X location,Node1 Y location,Current\n"
        "MetalA,1.0,1.0,MetalA,2.0,1.0,%.4e\n"
        "MetalA,1.0,2.0,MetalA,2.0,2.0,1.0000e-12\n" % peak_current_a)
    return proj


def _mk_tlef(where: Path, with_jmax: bool = True) -> Path:
    body = ["LAYER MetalA", "  TYPE ROUTING ;", "  WIDTH 0.23 ;",
            "  THICKNESS 0.53 ;"]
    if with_jmax:
        body.append("  DCCURRENTDENSITY AVERAGE 0.67 ;")
    body.append("END MetalA")
    p = where / "unit_tech.tlef"
    p.write_text("\n".join(body) + "\n")
    return p


def _emit(proj: Path, tlef: Path or None) -> dict:
    pdk = SimpleNamespace(tech_lef=(str(tlef) if tlef else None))
    notes = []
    emit = getattr(R, "_emit_em_current_authority", None)
    assert emit is not None, (
        "#1215: the runner must own an _emit_em_current_authority step — "
        "on the pre-fix tree no producer ever supplied the Jmax authority "
        "and the gate was INCOMPLETE on every design")
    assert emit(proj, pdk, container="", notes=notes) is True
    return json.loads(
        (proj / "reports" / "phase3" / "em_current_authority.json")
        .read_text())


def test_authority_reachable_reaches_a_measured_verdict_clean_currents():
    """Tiny segment currents + a reachable Jmax tech LEF -> PASS (measured),
    naming the jmax source. The pre-fix runner emitted nothing here."""
    proj = _mk_project(peak_current_a=1.0e-12)
    rep = _emit(proj, _mk_tlef(proj))
    assert rep["verdict"] == "PASS", rep.get("jmax_screen")
    assert rep["jmax_screen"]["jmax_source"], \
        "a PASS must name the authority it compared against"


def test_mutation_control_over_jmax_current_turns_the_same_project_FAIL():
    """Perturb ONLY the subject: one segment carrying 5 A (the ledger's
    ART-EM-CURRENT-DENSITY mutation shape) must flip the verdict to FAIL —
    proving the comparison is bound to the artefact, not vacuously green.
    (5 A also exceeds the declared supply current P/V = 4.38 mA, so the
    supply-conservation screen fires too; either named FAIL is measured.)"""
    proj = _mk_project(peak_current_a=5.0)
    rep = _emit(proj, _mk_tlef(proj))
    assert rep["verdict"] == "FAIL"


def test_authority_genuinely_absent_keeps_the_honest_INCOMPLETE():
    """No tech LEF at all -> the gate's pre-fix honest INCOMPLETE stands,
    naming the missing authority. INCOMPLETE is never relabelled."""
    proj = _mk_project(peak_current_a=1.0e-12)
    rep = _emit(proj, None)
    assert rep["verdict"] == "INCOMPLETE"
    assert "Jmax" in rep.get("missing_authority", "")


def test_tech_lef_without_dccurrentdensity_keeps_the_honest_INCOMPLETE():
    """A reachable tech LEF that states NO DCCURRENTDENSITY is not an
    authority; the Jmax tier must stay honestly unresolved (kind (b) is not
    silently converted into a fabricated PASS)."""
    proj = _mk_project(peak_current_a=1.0e-12)
    rep = _emit(proj, _mk_tlef(proj, with_jmax=False))
    assert rep["verdict"] == "INCOMPLETE"


def test_perc_em_category_reads_the_authority_comparison_SOURCE():
    """Step-28 PERC: when em.json is MEASURED-only, the EM category must read
    em_current_authority.json's PASS/FAIL — and ONLY PASS/FAIL: an absent or
    INCOMPLETE comparison leaves the honest INCOMPLETE standing."""
    import inspect
    src = inspect.getsource(R._emit_perc_equivalent)
    assert 'em_current_authority.json' in src, \
        "#1215: the PERC EM category must consume the Step-25 comparison"
    assert 'auth_v in ("PASS", "FAIL")' in src, \
        "#1215: only a MEASURED comparison verdict may replace INCOMPLETE"


def test_rerun_guards_can_recover_a_pre_fix_INCOMPLETE_tree_SOURCE():
    """A pre-fix run tree carries an em_current_authority.json that postdates
    the DEF, so the plain staleness guard would skip re-emission forever. The
    INCOMPLETE-retry clause (re-derive when the existing verdict is
    INCOMPLETE — the comparison never ran, so there is no measurement to
    preserve) and the perc multi-source staleness (perc now derives from the
    authority json) are what let a re-run move both gates."""
    import inspect
    src = inspect.getsource(R.step_canonicalize_artefacts)
    assert '_read_verdict(em_auth_json) == "INCOMPLETE"' in src
    assert '_signoff_regen(perc_rpt, primary_def,\n' in src or \
           '_signoff_regen(perc_rpt, primary_def, em_auth_json)' in src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
