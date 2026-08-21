#!/usr/bin/env python3
"""Tests for area_total_vs_budget_check.py — the synthesised area figure must
reach a COMPARISON, or the step must REFUSE and name the authority it lacks.

THIS FILE CARRIES THE HALF OF THE PREDICATE THE CORPUS CANNOT PROVE.

MEASURED on the published corpus (`benchmark-data` @ 146d665, 2026-08-20): 177
L19 copies, exactly ONE declaring `die_area_budget_um` ('1300x1300'), and TWO
runs carrying a synth `chip_area` — with ZERO overlap. So on real data this gate
has nothing to compare and refuses, exactly as `power_total_vs_budget_check`
does on power. That is an honest record, but on its own it would leave the
branch that REDDENS asserted and never executed, which is the defect the
mutation ledger exists to refuse. Everything below executes both branches.

`test_a_thousandfold_area_figure_reddens_a_run_that_can_compare` is the direct
analogue of ART-POWER-FIGURES-X1000 one axis over: an area figure shifted three
decades must go RED, and the reason it can is that the unit was established and
a ceiling was declared. `test_an_unestablished_unit_refuses_rather_than_guessing`
is the same defect's PREVENTION — with the unit unasserted, a 1000x figure and
the true one are indistinguishable, so the gate must refuse rather than pick.

Fixtures are SYNTHETIC and carry no process, foundry or chip token.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
PROG = _HERE.parent / "area_total_vs_budget_check.py"
sys.path.insert(0, str(_HERE.parent))

#: A ceiling of 40x50 um = 2000 um^2. Small on purpose: both branches of the
#: comparison have to be reachable with plain numbers a reader can check.
CEILING = "40x50"
CEILING_UM2 = 2000.0

#: The unit string a producer that DOES name its unit would write.
UNIT_KNOWN = "um^2"
#: The unit string the corpus actually carries today, verbatim from
#: `phase2/stage2/synth/stats.json`. It names no unit and must not be read as
#: one.
UNIT_CORPUS = ("cell-library area unit (as declared by the library the "
               "synthesis script loaded)")


def _stats(area, unit=UNIT_KNOWN) -> dict:
    return {"schema": "vibe-ic/synth-stats/1",
            "netlist": "phase2/stage2/synth/top_synth.v",
            "top_module": "top",
            "chip_area": area,
            "chip_area_unit": unit,
            "cell_count": 42,
            "includes_submodules": False,
            "selection": {"rule": "SINGLE_MODULE_NO_HIERARCHY"}}


def _project(tmp_path: Path, ceiling, area=None, unit=UNIT_KNOWN,
             extra_ceilings=()) -> Path:
    proj = tmp_path / "run"
    if area is not None:
        d = proj / "phase2" / "stage2" / "synth"
        d.mkdir(parents=True, exist_ok=True)
        (d / "stats.json").write_text(json.dumps(_stats(area, unit)))
    l19dir = proj / "phase1" / "generated_docs"
    l19dir.mkdir(parents=True, exist_ok=True)
    (l19dir / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"fields": {"pdk_target": None, "die_area_budget_um": ceiling,
                    "power_budget_uw": None}}))
    for i, extra in enumerate(extra_ceilings):
        alt = proj / "phase1" / f"merged_docs{i}"
        alt.mkdir(parents=True, exist_ok=True)
        (alt / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
            {"fields": {"die_area_budget_um": extra}}))
    proj.mkdir(parents=True, exist_ok=True)
    return proj


def _run(proj: Path, *extra):
    return subprocess.run([sys.executable, str(PROG), str(proj), *extra],
                          capture_output=True, text=True)


# ══════════════════════════════════════════════════════════════════════
# The comparison reddens — both branches EXECUTED, not asserted
# ══════════════════════════════════════════════════════════════════════
def test_cell_area_over_the_declared_die_fails(tmp_path):
    """The one bound this gate applies: utilisation cannot exceed 1.0."""
    r = _run(_project(tmp_path, CEILING, area=CEILING_UM2 * 1.5))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "AREA_TOTAL_OVER_DECLARED_DIE" in r.stdout
    assert "40x50" in r.stdout


def test_cell_area_under_the_declared_die_passes_and_names_the_threshold(
        tmp_path):
    r = _run(_project(tmp_path, CEILING, area=CEILING_UM2 * 0.5))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    # A PASS that names no threshold is indistinguishable from one that never
    # looked, so the figure AND the ceiling AND the limit's basis must appear.
    assert "L19.die_area_budget_um" in r.stdout
    assert "utilization 0.5000" in r.stdout
    assert "limit 1.0" in r.stdout
    assert "no tighter target is declared and none is derived" in r.stdout


def test_a_thousandfold_area_figure_reddens_a_run_that_can_compare(tmp_path):
    """ART-POWER-FIGURES-X1000, one axis over, EXECUTED.

    A design comfortably inside its declared die goes red when its area figure
    is shifted three decades. This is the property the corpus cannot exercise
    (no published run carries both a ceiling and an area figure), so it is
    measured here rather than promised.
    """
    honest = _project(tmp_path / "a", CEILING, area=CEILING_UM2 * 0.5)
    assert _run(honest).returncode == 0

    forged = _project(tmp_path / "b", CEILING, area=CEILING_UM2 * 0.5 * 1000)
    r = _run(forged)
    assert r.returncode == 1, (
        "a 1000x area figure must not read as the same PASS as the true one\n"
        + r.stdout + r.stderr)
    assert "AREA_TOTAL_OVER_DECLARED_DIE" in r.stdout


# ══════════════════════════════════════════════════════════════════════
# The three refusals are DISTINCT — "could not read it" != "read it, it was fine"
# ══════════════════════════════════════════════════════════════════════
def test_absent_ceiling_refuses_and_names_the_authority(tmp_path):
    r = _run(_project(tmp_path, None, area=CEILING_UM2 * 0.5))
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout.rstrip().splitlines()[-1].startswith("INCOMPLETE:")
    assert "die_area_budget_um" in r.stdout
    assert "will not derive one from a utilisation target" in r.stdout


def test_absent_area_figure_refuses_and_names_it(tmp_path):
    r = _run(_project(tmp_path, CEILING, area=None))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "a readable chip_area in any synth stats artefact" in r.stdout


def test_an_unestablished_unit_refuses_rather_than_guessing(tmp_path):
    """The corpus's own unit string must not be read as square micrometres.

    This is the PREVENTION half of ART-POWER-FIGURES-X1000: with the unit
    unasserted, a figure and the same figure times 1000 are the same evidence,
    so a verdict either way would be manufactured.
    """
    r = _run(_project(tmp_path, CEILING, area=CEILING_UM2 * 0.5,
                      unit=UNIT_CORPUS))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "chip_area_unit" in r.stdout
    assert "declines to assert the unit" in r.stdout


def test_the_three_refusals_do_not_produce_the_same_artefact(tmp_path):
    """Hard rule: three different missing authorities, three different texts."""
    def missing(proj):
        p = proj / "r.json"
        _run(proj, "--json", str(p))
        return json.loads(p.read_text())["missing_authority"]

    no_ceiling = missing(_project(tmp_path / "a", None, area=1.0))
    no_figure = missing(_project(tmp_path / "b", CEILING, area=None))
    no_unit = missing(_project(tmp_path / "c", CEILING, area=1.0,
                               unit=UNIT_CORPUS))
    assert len({no_ceiling, no_figure, no_unit}) == 3, (
        f"refusals collapsed: {no_ceiling!r} / {no_figure!r} / {no_unit!r}")


def test_empty_project_refuses_and_discloses(tmp_path):
    """An EMPTY tree must not PASS a blocking clause (vibe-ic#1017)."""
    proj = tmp_path / "empty"
    proj.mkdir()
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "read 0 synth area figure(s) and 0 L19 copy/copies" in r.stdout


# ══════════════════════════════════════════════════════════════════════
# Authority discipline
# ══════════════════════════════════════════════════════════════════════
def test_disagreeing_copies_are_not_an_authority(tmp_path):
    r = _run(_project(tmp_path, CEILING, area=1.0, extra_ceilings=("90x90",)))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "copies disagree" in r.stdout


def test_agreeing_copies_are_one_authority(tmp_path):
    r = _run(_project(tmp_path, CEILING, area=CEILING_UM2 * 0.5,
                      extra_ceilings=(CEILING,)))
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_bare_number_ceiling_is_refused_not_guessed(tmp_path):
    """`die_area_budget_um` is named in MICROMETRES, so a lone number is
    ambiguous between a side length and an area. Guessing either would be a
    ruler fitted to the answer."""
    r = _run(_project(tmp_path, "2000", area=1.0))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "die_area_budget_um" in r.stdout


def test_no_utilisation_target_is_ever_derived(tmp_path):
    """A design at 95% of its declared die PASSES. The gate must not invent the
    40-70% a real floorplan would target — that is a threshold nobody
    declared."""
    r = _run(_project(tmp_path, CEILING, area=CEILING_UM2 * 0.95))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "utilization 0.9500" in r.stdout


def test_overrides_are_honoured(tmp_path):
    proj = _project(tmp_path, None, area=CEILING_UM2 * 1.5, unit=UNIT_CORPUS)
    r = _run(proj, "--die-area-um", CEILING, "--area-unit-um2")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "AREA_TOTAL_OVER_DECLARED_DIE" in r.stdout


def test_bad_die_area_argument_is_an_argument_error(tmp_path):
    r = _run(_project(tmp_path, CEILING, area=1.0), "--die-area-um", "nonsense")
    assert r.returncode == 2
    assert "must be 'WxH'" in r.stderr


# ══════════════════════════════════════════════════════════════════════
# The verdict has to reach the flow
# ══════════════════════════════════════════════════════════════════════
def test_incomplete_sentinel_survives_the_flow_tail_cut(tmp_path):
    """`flow_compliance_check.output_snippet` keeps only the LAST 300 chars of
    stdout, so the token must start a line INSIDE that window."""
    r = _run(_project(tmp_path, None, area=1.0))
    tail = r.stdout[-300:]
    assert any(ln.startswith("INCOMPLETE:") for ln in tail.splitlines()), tail


def test_json_report_carries_the_comparison(tmp_path):
    proj = _project(tmp_path, CEILING, area=CEILING_UM2 * 0.5)
    out = proj / "reports" / "gates" / "area_budget.json"
    r = _run(proj, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    c = rep["comparison"]
    assert c["die_area_um2"] == CEILING_UM2
    assert c["cell_area_um2"] == CEILING_UM2 * 0.5
    assert c["utilization"] == 0.5
    assert c["limit"] == 1.0
    # The SELECTION the producing artefact made is carried, so the two can never
    # silently disagree about which number was compared.
    assert c["selection_rule"] == "SINGLE_MODULE_NO_HIERARCHY"


def test_the_program_names_no_process_or_vendor_token(tmp_path):
    """chip-AGNOSTIC, asserted rather than promised."""
    src = PROG.read_text().lower()
    for tok in ("sky130", "gf180", "sg13g2", "tsmc", "samsung", "globalfound",
                "intel", "umc", "smic"):
        assert tok not in src, f"{PROG.name} names {tok!r}"
