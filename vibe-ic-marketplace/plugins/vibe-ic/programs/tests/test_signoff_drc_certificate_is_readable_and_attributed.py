"""The Step-31 sign-off DRC certificate: unreadable is not clean, and a waiver
must be backed by the attribution it claims.

WHAT WAS MEASURED, at v1.9.62, before anything changed.

`phase3_one_shot_runner.step_canonicalize_artefacts` publishes the Step-31
sign-off DRC certificate by PREPENDING a 4-line `#` provenance preamble to the
KLayout RDB::

    # Sign-off DRC report (... Step 31 alias).
    # Source: phase3/reports/drc.rpt
    # Tool: klayout
    #
    <?xml version="1.0" encoding="utf-8"?>

`_drc_real_violation_count` sniffed the dialect with
`text.lstrip().startswith("<?xml" | "<report-database")` — anchored to the first
non-WHITESPACE character of the whole file. `#` is not whitespace, so both tests
failed, `ET.fromstring` was NEVER CALLED, and the three text regexes ran over
2–12 MB of RDB that carries no summary count. The function returned None on
EIGHT tracked sign-off certificates.

Scoped as the flow declares step 31 — `drc_report_check . --mode drc --under
reports/phase3/drc_signoff.rpt`, a SINGLE-FILE scope — that file is the entire
discovery set, so `determined_files == 0` and the gate reported
DRC_VIOLATION_COUNT_UNDETERMINED. NOT MEASURED, carried as a failure.

NOT "the `#` header breaks parsing": 22 other tracked reports carry a `#`
preamble and read fine, because their bodies are TEXT and the text greps never
cared. The failure needs the preamble AND an XML-only body.

WHAT THE EIGHT CERTIFICATES ACTUALLY CONTAINED — the headline, established
before the fix was designed. Six were hiding violations::

    run   items      published   header read correctly
    A     40240      None        40240
    B     19145      None        19145
    C      7459      None         7459
    D      7284      None         7284
    E      6172      None         6172
    F      5293      None         5293
    G         0      None            0
    H         0      None            0

and a header-skip fix ALONE would have turned all eight GREEN, because the
prefix-only waiver tiers every one of those 85,593 items out of the gating
count. That waiver's premise does not survive measurement: the RDB states an
attribution on every item, and 94.7%–98.9% of the waived items say `chip_top`
— the design's OWN top cell, per the RDB's `<top-cell>` element. Only 1.1%–5.3%
resolve to a foundry std-cell master. The attribution is informative rather
than uniformly flattened precisely BECAUSE those few hundred per run DO resolve
to `sky130_fd_sc_hd__*` masters.

So the waiver is now backed by evidence: a waivable rule family AND the
report's own attribution to a foundry cell master. Result on the eight — six
STAY RED carrying 5,062–39,805 real user-routing violations (previously
invisible), two go GREEN on a genuine zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "eda_report_audit.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import eda_report_audit as era  # noqa: E402

_RUNNER_PREAMBLE = (
    "# Sign-off DRC report (ORGANIC-20260531 Step 31 alias).\n"
    "# Source: phase3/reports/drc.rpt\n"
    "# Tool: klayout\n"
    "#\n"
)


def _rdb(items: str, top: str = "chip_top", pad: bool = False) -> str:
    """A KLayout RDB. `pad` inflates it past MIN_REPORT_BYTES the way a real
    deck does — with more DECLARED CATEGORIES, INSIDE the document. Padding
    after `</report-database>` would make the XML malformed, which this
    module's own terminal-XML-branch rule correctly refuses to count."""
    extra = ""
    if pad:
        extra = "".join(
            f"  <category><name>pad.{i}</name>"
            f"<description>pad.{i} : min. spacing / width / enclosure rule "
            f"placeholder for size {i}</description></category>\n"
            for i in range(60))
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<report-database>\n"
        " <description>SKY130 DRC runset</description>\n"
        " <generator>drc: script='sky130A.lydrc'</generator>\n"
        f" <top-cell>{top}</top-cell>\n"
        " <categories>\n"
        "  <category><name>li.3</name><description>li.3 : min. li spacing"
        "</description></category>\n"
        "  <category><name>m2.1</name><description>m2.1 : min. met2 width"
        "</description></category>\n"
        "  <category><name>density</name><description>density : metal density"
        "</description></category>\n"
        "  <category><name>ant.1</name><description>ant.1 : antenna ratio"
        "</description></category>\n"
        "  <category><name>via.1</name><description>via.1 : via enclosure"
        "</description></category>\n"
        + extra +
        " </categories>\n"
        " <items>\n" + items + " </items>\n"
        "</report-database>\n"
    )


def _item(rule: str, cell: str) -> str:
    return (
        "  <item>\n"
        "   <tags/>\n"
        f"   <category>'{rule}'</category>\n"
        f"   <cell>{cell}</cell>\n"
        "   <multiplicity>1</multiplicity>\n"
        "   <values><value>edge-pair: (1.0,1.0;1.1,1.0)</value></values>\n"
        "  </item>\n"
    )


# ---------------------------------------------------------------------------
# 1. THE NEGATIVE CONTROL — this is the assertion that fails without the fix.
# ---------------------------------------------------------------------------
def test_runner_preamble_does_not_hide_the_klayout_rdb():
    """A certificate behind the runner's own `#` preamble MUST be counted.

    NEGATIVE CONTROL: at v1.9.62 this returns None — the exact defect. The
    body is byte-identical to a report that reads fine at byte 0.
    """
    body = _rdb(_item("li.3", "chip_top") * 3)
    assert era._drc_real_violation_count(body) == (3, 0), "control: bare RDB"

    behind_preamble = _RUNNER_PREAMBLE + body
    got = era._drc_real_violation_count(behind_preamble)
    assert got is not None, (
        "a sign-off certificate published by the runner's own canonicaliser "
        "returned None — NOT MEASURED masquerading as a gate failure")
    assert got == (3, 0)


def test_preamble_stripping_does_not_disturb_text_dialect_reports():
    """22 tracked reports carry a `#` preamble AND a text body. They read via
    the text path today and must keep their exact answers."""
    text = (
        "# OpenROAD detailed_route report\n"
        "# regenerated by the phase-3 runner\n"
        "#\n"
        "violation report: 72\n"
        "violation count summary: 72 violation(s) found\n"
        "spacing / width / via enclosure checked\n"
    )
    assert era._drc_real_violation_count(text) == (72, 0)


# ---------------------------------------------------------------------------
# 2. THE WAIVER MUST BE BACKED BY THE ATTRIBUTION IT CLAIMS
# ---------------------------------------------------------------------------
def test_waivable_rule_inside_a_foundry_cell_is_waived():
    """The legitimate case the waiver exists for: std-cell-INTERNAL geometry."""
    body = _rdb(_item("li.3", "sky130_fd_sc_hd__dfrtp_1") * 5)
    assert era._drc_real_violation_count(body) == (0, 5)


def test_waivable_rule_at_the_designs_own_top_cell_is_COUNTED():
    """The measured reality on six real Phase-3 runs: ~95% of the items the
    prefix-only waiver tiered out are attributed to the design's own top cell,
    not to any foundry master. A claim of 'std-cell-INTERNAL' about geometry
    the report places at chip_top is contradicted by the report itself."""
    body = _rdb(_item("li.3", "chip_top") * 7)
    assert era._drc_real_violation_count(body) == (7, 0), (
        "li.3 items at the design's own top cell were waived as "
        "'foundry std-cell-internal' on the report's own contrary evidence")


def test_missing_attribution_is_not_evidence():
    """An absent `<cell>` cannot support the waiver's claim."""
    body = _rdb("  <item><category>'li.3'</category></item>\n" * 4)
    assert era._drc_real_violation_count(body) == (4, 0)


def test_met2_honesty_gate_survives_even_inside_a_foundry_cell():
    """The pre-existing honesty gate is untouched: a met2+ rule is ALWAYS
    user-routing and can never be waived, whatever the attribution says."""
    body = _rdb(_item("m2.1", "sky130_fd_sc_hd__buf_16") * 2)
    assert era._drc_real_violation_count(body) == (2, 0)


def test_a_genuinely_clean_certificate_still_reads_zero():
    """Cell-awareness must never manufacture a violation. Measured across the
    corpus: every report with 0 items stays (0, 0)."""
    assert era._drc_real_violation_count(_RUNNER_PREAMBLE + _rdb("")) == (0, 0)


# ---------------------------------------------------------------------------
# 3. THE XML BRANCH IS TERMINAL — unreadable never falls through to the greps
# ---------------------------------------------------------------------------
def test_truncated_rdb_plus_a_clean_sentence_is_not_clean():
    """A KLayout run killed mid-write on a DIRTY design was graded CLEAN if any
    'N violations'-shaped sentence existed anywhere in the bytes — the exact
    injection this function was written to close, re-entered through the
    parse-failure door.

    MEASURED at v1.9.62 on a real corpus RDB (7,284 items):
        intact                                       -> (0, 7284)
        truncated + '<!-- summary: 0 violations -->'  -> (0, 0)   CLEAN
    """
    body = _rdb(_item("li.3", "chip_top") * 400)
    truncated = body[: len(body) // 2]
    assert era._drc_real_violation_count(truncated) is None
    poisoned = truncated + "\n<!-- summary: 0 violations found -->\n"
    assert era._drc_real_violation_count(poisoned) is None, (
        "a truncated RDB was credited with a count read from prose")


def test_report_database_without_items_is_not_clean():
    """A well-formed `<report-database>` with `<items>` ABSENT fell through to
    the text greps too."""
    doc = ('<?xml version="1.0"?>\n<report-database>'
           "<top-cell>chip_top</top-cell></report-database>\n")
    assert era._drc_real_violation_count(doc) is None
    assert era._drc_real_violation_count(doc + "\n0 violations\n") is None


def test_anchored_summary_beats_an_incidental_phrase_out_of_order():
    """Text dialect: a real summary line must win over a progress line
    regardless of which appears first."""
    text = (
        "Completing 10% with 0 violations.\n"
        "Completing 90% with 0 violations.\n"
        "violation count summary: 61 violation(s) found\n"
    )
    assert era._drc_real_violation_count(text) == (61, 0)


# ---------------------------------------------------------------------------
# 4. THE REFUSAL PATH — NOT READABLE gates, and is never silent
# ---------------------------------------------------------------------------
_PAD = "# " + ("=" * 78 + "\n") * 40  # satisfies MIN_REPORT_BYTES


def _clean_text_report() -> str:
    return ("[INFO drt-0012] OpenROAD detailed_route\n"
            "spacing / width / density / antenna / via / enclosure checked\n"
            "violation count summary: 0 violation(s) found\n" + _PAD)


def test_an_unreadable_report_beside_a_clean_one_does_not_pass(tmp_path):
    """THE DEFECT THAT LET THIS SURVIVE. `passed` only ever required
    `determined_files > 0`, never `determined_files == files_found`, and
    DRC_VIOLATION_COUNT_UNDETERMINED only fired when NOT ONE file parsed. So an
    unreadable report was dropped SILENTLY — no finding at any severity.

    MEASURED at v1.9.62, unreadable sign-off + clean sibling in one scope:
        passed=True  files_found=2  determined_files=1  ERRORs: []
    """
    d = tmp_path / "proj" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "drc_router.rpt").write_text(_clean_text_report())
    # An RDB truncated mid-element: announces its dialect, cannot be counted.
    (d / "drc_signoff.rpt").write_text(
        _RUNNER_PREAMBLE + _rdb(_item("li.3", "chip_top") * 40)[:900])

    with era.scoped_discovery([tmp_path / "proj"]):
        res = era._check_drc(tmp_path / "proj")

    rules = [f.rule for f in res.findings if f.severity == "ERROR"]
    assert "DRC_REPORT_NOT_READABLE" in rules, (
        f"an unreadable sign-off certificate was dropped silently: {rules}")
    assert res.passed is False, "a scope containing NOT-MEASURED bytes passed"
    assert res.summary["unreadable_files"] == 1
    assert res.summary["files_found"] == 2


def test_a_discovered_but_unopenable_report_gates(tmp_path):
    """A dangling symlink at a Step-31 evidence path. MEASURED at v1.9.62 on
    `benchmark-data/ic/edge_llm_accel` project-wide: passed=True,
    files_found=2, determined_files=1, ERRORs: [] — a GREEN DRC verdict over a
    sign-off certificate that does not exist. `fp.read_text()` raised OSError
    into a bare `continue`."""
    proj = tmp_path / "proj"
    steps = proj / "steps" / "31_physical_verification"
    steps.mkdir(parents=True)
    (proj / "reports").mkdir()
    (proj / "reports" / "drc_router.rpt").write_text(_clean_text_report())
    (steps / "drc_signoff.rpt").symlink_to(proj / "reports" / "gone.rpt")

    res = era._check_drc(proj)
    rules = [f.rule for f in res.findings if f.severity == "ERROR"]
    assert "DRC_REPORT_NOT_READABLE" in rules, rules
    assert res.passed is False


def test_all_readable_and_clean_still_passes(tmp_path):
    """The refusal path must not turn a genuinely clean scope red."""
    d = tmp_path / "proj" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "drc_router.rpt").write_text(_clean_text_report())
    (d / "drc_signoff.rpt").write_text(
        _RUNNER_PREAMBLE + _rdb("", pad=True))
    with era.scoped_discovery([tmp_path / "proj"]):
        res = era._check_drc(tmp_path / "proj")
    assert res.passed is True, [f.rule for f in res.findings
                                if f.severity == "ERROR"]
    assert res.summary["unreadable_files"] == 0


def test_waived_disclosure_is_not_filed_at_the_skimmable_tier():
    """A waiver is a decision to NOT look at something; the count of things not
    looked at is the most review-relevant fact a sign-off audit carries. The
    runner records these same runs `review_required: true`; the audit that
    echoes it must not be quieter than the runner."""
    sev = {}

    def _run(tmp):
        d = tmp / "reports" / "phase3"
        d.mkdir(parents=True)
        (d / "drc_signoff.rpt").write_text(
            _RUNNER_PREAMBLE
            + _rdb(_item("li.3", "sky130_fd_sc_hd__dfrtp_1") * 12, pad=True))
        with era.scoped_discovery([tmp]):
            return era._check_drc(tmp)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        res = _run(Path(td))
    for f in res.findings:
        sev[f.rule] = f.severity
    assert sev.get("DRC_FOUNDRY_STDCELL_EXCLUDED") == "WARNING", sev
    assert res.summary["foundry_stdcell_excluded"] == 12
