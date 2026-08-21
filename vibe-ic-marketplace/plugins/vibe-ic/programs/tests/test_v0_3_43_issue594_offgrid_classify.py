"""ORGANIC #594 — the first design to reach GDS failed signoff DRC with
the count DOMINATED by OFFGRID-vertex rules (m1_OFFGRID=29,670 +
ct_OFFGRID=6,204 ≈ 74% of 48,533 user violations on the motivating IC).
An OFFGRID vertex is a polygon vertex off the PDK manufacturing grid — a
FLOW defect (routing/streamout), NOT design content. Counted together
with real spacing/width DRC it hides the flow regression inside a huge
"design DRC" number.

Fix: offgrid_drc_classify_check.py splits the KLayout DRC report into the
OFFGRID class vs real spacing/width and emits a distinct FLOW_OFFGRID
finding; step_drc surfaces flow_offgrid_violations separately from
design_drc_violations so a grid regression is never miscounted.
"""
import inspect
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import offgrid_drc_classify_check as OGC  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402


def _klayout_report(tmp_path, items):
    """Write a minimal KLayout sign-off DRC XML report. `items` is a
    list of (category, multiplicity); categories with descriptions are
    auto-derived (OFFGRID names carry the canonical x.1b phrasing)."""
    cats = sorted({c for c, _ in items})
    cat_xml = "".join(
        f"<category><name>{c}</name><description>"
        f"{'x.1b: OFFGRID vertex' if 'OFFGRID' in c else c + ' spacing'}"
        f"</description></category>"
        for c in cats)
    item_xml = "".join(
        f"<item><category>'{c}'</category>"
        f"<multiplicity>{m}</multiplicity></item>"
        for c, m in items)
    xml = (f"<report-database><categories>{cat_xml}</categories>"
           f"<items>{item_xml}</items></report-database>")
    p = tmp_path / "drc.xml"
    p.write_text(xml)
    return p


# ── the issue's exact 現象: OFFGRID dominates, classified distinctly ─────────

def test_offgrid_dominated_report_flags_flow_offgrid(tmp_path):
    rpt = _klayout_report(tmp_path, [
        ("m1_OFFGRID", 29670), ("ct_OFFGRID", 6204),
        ("m1.2", 11470), ("li.1", 1189),
    ])
    rep = OGC.classify(rpt)
    assert rep["verdict"] == "FLOW_OFFGRID"
    assert rep["offgrid_total"] == 29670 + 6204
    assert rep["other_total"] == 11470 + 1189
    assert rep["offgrid_fraction"] > 0.7         # ≈74% like the live case
    assert set(rep["offgrid_per_rule"]) == {"m1_OFFGRID", "ct_OFFGRID"}
    assert "m1.2" in rep["other_per_rule"]


def test_clean_report_no_offgrid(tmp_path):
    """NEGATIVE: a report with only real spacing/width is PASS (no
    OFFGRID-class) — design DRC is NOT relabelled as a flow defect."""
    rpt = _klayout_report(tmp_path, [("m1.2", 5), ("li.1", 3)])
    rep = OGC.classify(rpt)
    assert rep["verdict"] == "PASS"
    assert rep["offgrid_total"] == 0
    assert rep["other_total"] == 8


def test_description_based_offgrid_match(tmp_path):
    """A rule whose NAME lacks OFFGRID but whose description is the
    canonical 'x.1b OFFGRID vertex' is still caught."""
    xml = ("<report-database><categories>"
           "<category><name>x.1b</name>"
           "<description>x.1b: OFFGRID vertex</description></category>"
           "</categories><items>"
           "<item><category>'x.1b'</category>"
           "<multiplicity>42</multiplicity></item>"
           "</items></report-database>")
    p = tmp_path / "d.xml"
    p.write_text(xml)
    rep = OGC.classify(p)
    assert rep["verdict"] == "FLOW_OFFGRID"
    assert rep["offgrid_total"] == 42


def test_classify_per_rule_name_only():
    rep = OGC.classify_per_rule({"m1_OFFGRID": 100, "via_offgrid": 5,
                                 "m1.2": 20})
    assert rep["verdict"] == "FLOW_OFFGRID"
    assert rep["offgrid_total"] == 105
    assert rep["other_total"] == 20


def test_classify_per_rule_clean():
    rep = OGC.classify_per_rule({"m1.2": 20, "li.1": 3})
    assert rep["verdict"] == "PASS"
    assert rep["offgrid_total"] == 0


# ── CLI end-state ────────────────────────────────────────────────────────────

def test_cli_fails_on_offgrid(tmp_path):
    rpt = _klayout_report(tmp_path, [("m1_OFFGRID", 100), ("m1.2", 5)])
    r = subprocess.run(
        [sys.executable, str(PROG / "offgrid_drc_classify_check.py"),
         str(rpt)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "FLOW_OFFGRID" in r.stdout
    assert "off-grid" in r.stdout


def test_cli_passes_on_clean(tmp_path):
    rpt = _klayout_report(tmp_path, [("m1.2", 5)])
    r = subprocess.run(
        [sys.executable, str(PROG / "offgrid_drc_classify_check.py"),
         str(rpt)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "no OFFGRID-class DRC" in r.stdout


# ── step_drc wiring ──────────────────────────────────────────────────────────

def test_step_drc_surfaces_flow_offgrid_distinctly():
    src = inspect.getsource(R.step_drc)
    assert "offgrid_drc_classify_check" in src
    assert "flow_offgrid_violations" in src
    assert "design_drc_violations" in src
    assert "FLOW_OFFGRID" in src
