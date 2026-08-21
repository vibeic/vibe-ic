"""ORGANIC #595 — step_lvs correctly aborts (per #477) on a high
ext2spice extraction-error count, but the message framed it as an
extraction-fidelity problem in isolation while the SAME run's signoff
DRC was dominated by OFFGRID-vertex violations. Magic's extractor chokes
on exactly that off-grid geometry, so the LVS abort and the DRC OFFGRID
wall are almost certainly the same root cause — yet nothing in the LVS
verdict pointed there, costing a triage step.

Fix: _run_drc_offgrid_population() classifies the run's DRC report; when
the #477 abort fires AND the DRC carries a large OFFGRID population, the
verdict cross-references it ("likely downstream of N OFFGRID-vertex DRC
violations — fix the flow grid, #594, before re-extracting"). The #477
abort itself is unchanged.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _drc_report(project: Path, items):
    rpt = project / "phase3" / "reports" / "drc.rpt"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    cats = sorted({c for c, _ in items})
    cat_xml = "".join(
        f"<category><name>{c}</name><description>"
        f"{'x.1b: OFFGRID vertex' if 'OFFGRID' in c else c}"
        f"</description></category>" for c in cats)
    item_xml = "".join(
        f"<item><category>'{c}'</category>"
        f"<multiplicity>{m}</multiplicity></item>" for c, m in items)
    rpt.write_text(f"<report-database><categories>{cat_xml}</categories>"
                   f"<items>{item_xml}</items></report-database>")
    return rpt


def test_population_returns_offgrid_classification(tmp_path):
    _drc_report(tmp_path, [("m1_OFFGRID", 29670), ("ct_OFFGRID", 6204),
                           ("m1.2", 11470)])
    og = R._run_drc_offgrid_population(tmp_path)
    assert og is not None
    assert og["verdict"] == "FLOW_OFFGRID"
    assert og["offgrid_total"] == 29670 + 6204
    assert og["offgrid_fraction"] > 0.7


def test_population_none_without_report(tmp_path):
    assert R._run_drc_offgrid_population(tmp_path) is None


def test_population_clean_report_no_offgrid(tmp_path):
    _drc_report(tmp_path, [("m1.2", 5)])
    og = R._run_drc_offgrid_population(tmp_path)
    assert og is not None
    assert og["verdict"] == "PASS"
    assert og["offgrid_total"] == 0


# ── wiring: the #477 abort cross-references OFFGRID when present ─────────────

def test_lvs_abort_cross_references_offgrid():
    src = inspect.getsource(R._run_extraction_lvs)
    assert "_run_drc_offgrid_population" in src
    assert "offgrid_drc_cross_ref" in src
    assert "OFFGRID-" in src
    # the #477 abort is preserved (still FAIL on the ceiling)
    assert "LVS_EXTRACTION_ERROR_FLOOD" in src
    # cross-ref is GATED on a large/dominant population, not any offgrid
    assert "0.5" in src and "1000" in src


def test_offgrid_xref_gating_matches_issue_thresholds():
    """The cross-reference fires only when OFFGRID is dominant (>=50%)
    or a flood (>=1000) — not for a handful of off-grid vertices."""
    src = inspect.getsource(R._run_extraction_lvs)
    # dominant-fraction OR absolute-flood disjunction present
    assert 'offgrid_fraction", 0) >= 0.5' in src
    assert 'offgrid_total", 0) >= 1000' in src
