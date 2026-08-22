"""v0.3.17 — #515: the tapeout sign-off DRC-evidence slot must consume the
DESIGN-LEVEL DRC count (continues #513's rule-layer classifier), not the raw
violation total.

The audited rot (field: subservient runner-auto LVS upgrade reran step_drc):
the KLayout SIGNOFF DRC report on a routing-DRC-clean design carries a large
RAW count (e.g. 115114) that is 100% stdcell-LIBRARY-INTERNAL (foundry cell
li/ct/m1 internal rules below the router metal stack). The tapeout DRC slot
gated on that raw count → held the slot → Step 36 FAIL even though the design
itself is routing-DRC-clean (design-level == 0, #513) and Step 31 already
waived it. The operator then had to HAND-WRITE a cascaded tapeout waiver to
get back to PASS_WITH_WAIVERS.

Fix: when the chosen signoff DRC report is a KLayout report-database, classify
by rule-layer (#513 `classify_xml`) and gate on the DESIGN-LEVEL count. When
design-level == 0, credit the DRC slot AS A WAIVER (verdict → PASS_WITH_WAIVERS)
so a routing-DRC-clean design reaches 4/4 with no cascaded waiver. A real
design-level defect (design_level > 0) still hard-FAILs the slot, and a report
we CANNOT rule-layer classify (plain-text log) keeps the strict raw-count FAIL.

chip-AGNOSTIC: synthetic project + synthetic KLayout report-database, no chip
literal; the rule names are foundry rule-layer tokens, not a chip identity.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gdsii  # noqa: E402
import _si_signoff_fixture  # noqa: E402

# 2026-07-27 (review follow-up): the tape-out GDS slot credits ONLY the flow's
# declared stream-out artefact (phase3/stage4/gds/*.gds), and only when it
# carries real GDSII substance. This file's subject is not the GDS slot; it
# just needs that slot satisfied, so its tape-out artefact is now a real
# minimal GDSII stream at the declared path rather than a text placeholder.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import signoff_audit as audit  # noqa: E402


def _report_db(category_counts: dict) -> str:
    """Build a minimal KLayout DRC report-database XML with the given number
    of <item> violations per rule category (e.g. {'li.3': 100, 'm2.1': 2})."""
    items = []
    for rule, n in category_counts.items():
        for _ in range(n):
            items.append(
                f"  <item>\n"
                f"   <category>'{rule}'</category>\n"
                f"   <cell>'top'</cell>\n"
                f"   <values><value>box: (0,0;1,1)</value></values>\n"
                f"  </item>")
    body = "\n".join(items)
    # category DEFINITIONS up top (must NOT be counted — classify_xml splits
    # on the first <items> and only reads after it).
    cat_defs = "\n".join(
        f"  <category><name>{r}</name></category>" for r in category_counts)
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<report-database>\n"
        " <categories>\n" + cat_defs + "\n </categories>\n"
        " <items>\n" + body + "\n </items>\n"
        "</report-database>\n")


def _proj(tmp_path, drc_text=None, drc_name="drc_signoff.rpt"):
    """A tapeout-ready project: gds + netlist + timing + LVS always present;
    DRC report content supplied per-test.

    2026-07-27: tapeout mode gained a fifth pillar (LVS). This suite is about
    the DRC slot, so the fixture carries a genuine netgen match — otherwise
    every case here would FAIL on the missing LVS evidence and stop
    discriminating the DRC tiers it exists to pin. Evidence denominators
    below moved 4 → 5 accordingly."""
    _gdsii.write_declared_streamout(tmp_path, "chip_top.gds")
    (tmp_path / "chip_top_synth.v").write_text("module chip_top();endmodule\n")
    (tmp_path / "sta_timing.rpt").write_text("slack 0.1\n")
    (tmp_path / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports/phase3/lvs.rpt").write_text(
        "Netlists match uniquely.\nFinal result: Circuits match uniquely.\n")
    # 2026-07-28: tape-out mode gained an SI (crosstalk-delay) blocking
    # condition. This fixture is about the DRC slot, so it carries a PROVED
    # SI verdict — without one every case here would collapse onto the
    # SI refusal and stop discriminating what it exists to pin.
    _si_signoff_fixture.write_proved_si_report(tmp_path)
    if drc_text is not None:
        (tmp_path / drc_name).write_text(drc_text)
    return tmp_path


# ── the #515 acceptance: library-internal/0-design-level → 4/4, no cascade ──

def test_library_internal_only_credits_drc_slot_4of4(tmp_path):
    # 115114-style: a big raw count, 100% stdcell-library-internal layers.
    xml = _report_db({"li.3": 500, "li.5": 300, "ct.2": 200,
                      "m1.2": 100, "li.1": 14})  # 1114 raw, design-level 0
    p = _proj(tmp_path, xml)
    r = audit._check_tapeout(p)
    assert r.summary["evidence_count"] == 5, r.summary  # 4 → 5: LVS pillar
    assert r.summary["evidence"]["drc"] == "library_internal_waived"
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS"
    assert r.summary["drc_library_internal_waived"] is True
    # the credited finding names the design-level=0 rationale.
    rules = {f.rule for f in r.findings}
    assert "TAPEOUT_DRC_LIBRARY_INTERNAL_WAIVED" in rules
    assert "TAPEOUT_DRC_VIOLATIONS" not in rules


def test_acceptance_main_exit_no_cascaded_waiver(tmp_path):
    # the issue's ## 驗收 end-state: PASS_WITH_WAIVERS with NO hand-written
    # cascaded tapeout waiver file anywhere in the project.
    # #651 UPDATE: PASS_WITH_WAIVERS now returns the DISTINCT waiver rc
    # (audit.WAIVER_EXIT_CODE == 3), not rc 0 — a bare PASS (rc 0) must
    # NEVER be conflated with PASS_WITH_WAIVERS at the rc-only flow gate
    # (CLAUDE.md rule 11). The #515 substance (no HAND-WRITTEN cascaded
    # waiver needed) still holds; an auto-emitted waivers.json Step-36
    # entry is the intended waiver-accounting artifact, not a cascade file.
    xml = _report_db({"li.3": 115114})
    p = _proj(tmp_path, xml)
    rc = audit.main([str(p), "--mode", "tapeout"])
    assert rc == audit.WAIVER_EXIT_CODE   # distinct PASS_WITH_WAIVERS rc, not 0
    assert rc != 0
    # no HAND-WRITTEN cascaded waiver artifact was needed/created.
    assert not list(p.rglob("*cascad*"))
    assert not list(p.rglob("*step36*waiver*"))


# ── regression guards: real defects + unclassifiable reports stay strict ──

def test_design_level_violation_still_fails(tmp_path):
    # one real routing defect on met2 / via2 → design_level > 0 → hard FAIL.
    xml = _report_db({"li.3": 500, "m2.1": 3, "via2.1a": 1})  # design-level 4
    p = _proj(tmp_path, xml)
    r = audit._check_tapeout(p)
    assert r.summary["evidence"]["drc"] is False
    assert r.passed is False            # 4 of 5 — the DRC slot is held
    assert r.summary["evidence_count"] == 4
    assert r.summary["verdict_tier"] == "FAIL"
    assert r.summary["drc_library_internal_waived"] is False
    msg = next(f.message for f in r.findings
               if f.rule == "TAPEOUT_DRC_VIOLATIONS")
    assert "design level" in msg            # cites the design-level count


def test_plaintext_log_cannot_be_classified_stays_strict(tmp_path):
    # a non-report-database DRC log can't be rule-layer classified → we
    # cannot PROVE library-internal → keep the strict raw-count FAIL.
    log = "DRC run complete\nTotal violations: 42\n"
    p = _proj(tmp_path, log, drc_name="drc_signoff.log")
    r = audit._check_tapeout(p)
    assert r.summary["evidence"]["drc"] is False
    assert r.passed is False
    assert r.summary["drc_library_internal_waived"] is False


def test_clean_drc_still_absolute_pass(tmp_path):
    # zero violations → unchanged behaviour: absolute PASS, not a waiver.
    xml = _report_db({})  # no items
    p = _proj(tmp_path, xml)
    r = audit._check_tapeout(p)
    assert r.summary["evidence"]["drc"] is True
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS"
    assert r.summary["drc_library_internal_waived"] is False


def test_malformed_reportdb_without_categories_stays_strict(tmp_path):
    # robustness guard: a report-database whose <item>s carry NO <category>
    # (malformed / partial) gives classified_total 0 while the raw count is
    # nonzero — the classifier did NOT account for the violations, so we
    # CANNOT prove library-internal. Must keep the strict FAIL (not silently
    # waive on an empty classification). This is the exact shape the legacy
    # substance-gate fixture uses.
    xml = ("<report-database>\n" + "<item>x</item>\n" * 7
           + "</report-database>\n")
    p = _proj(tmp_path, xml)
    r = audit._check_tapeout(p)
    assert r.summary["evidence"]["drc"] is False
    assert r.passed is False
    assert r.summary["drc_library_internal_waived"] is False
    rules = {f.rule for f in r.findings}
    assert "TAPEOUT_DRC_VIOLATIONS" in rules
    assert "TAPEOUT_DRC_LIBRARY_INTERNAL_WAIVED" not in rules
