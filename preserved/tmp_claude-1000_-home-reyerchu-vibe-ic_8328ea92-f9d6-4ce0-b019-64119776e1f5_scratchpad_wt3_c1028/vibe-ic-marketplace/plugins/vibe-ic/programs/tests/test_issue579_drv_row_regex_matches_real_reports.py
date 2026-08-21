"""#579 — a BLOCKING gate whose row pattern matched nothing.

`drv_promotion_corroboration_check` counts sign-off DRV violations with

    _DRV_ROW_RE = re.compile(r"^\\s*\\S+\\s+-?[\\d.]+\\s+-?[\\d.]+\\s+(-[\\d.]+)\\s*$", re.M)

anchoring `\\s*$` immediately after the slack field. OpenSTA does not end the
line there — every violating row it prints carries a trailing tag:

    _07896_/B0                              3.00    6.12   -3.12 (VIOLATED)

So the pattern matched NOTHING, `signoff_drv_violations()` returned 0 for every
report ever written, and a gate wired as BLOCKING could not fail. Measured on a
real shipped `sta_mcorner_ocv.rpt`: 0 matches against 4 rows carrying
`(VIOLATED)`.

CORPUS, swept before and after — 97 STA reports under `benchmark-data/`:

    shipped pattern                      0 rows
    fixed pattern                       48 rows
    `(VIOLATED)` tags in those files    52
    independently-written DRV-row RE    48   <- agrees exactly

The 52-vs-48 gap is NOT a miss. Four of the tags are on a setup-slack SUMMARY
line, which has a different shape entirely:

    '          -3.81   slack (VIOLATED)\\n'

three fields, not the pin/limit/value/slack four. Counting it as a DRV row would
be a different wrong answer, so the fixed pattern correctly declines it — and
that is why this file checks against an independently derived row pattern rather
than against a tag count.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "drv_promotion_corroboration_check.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "drv_promotion_corroboration_check_probe", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["drv_promotion_corroboration_check_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

#: Real rows, copied from a shipped `sta_mcorner_ocv.rpt`.
_REAL_ROWS = """\
_07896_/B0                              3.00    6.12   -3.12 (VIOLATED)
_07206_/Y                               0.31    0.38   -0.07 (VIOLATED)
"""

#: A setup-slack summary line. Three fields, not four — counting it as a DRV row
#: is a different wrong answer from missing the real rows.
_SUMMARY_LINE = "          -3.81   slack (VIOLATED)\n"

#: A met row. The gate counts VIOLATIONS, so a positive slack must not count.
_MET_ROW = "_07300_/A                               1.50    0.20    1.30\n"


def test_a_tagged_violation_row_is_counted():
    """The defect: the shipped pattern matched zero of these."""
    assert len(M._DRV_ROW_RE.findall(_REAL_ROWS)) == 2, (
        "a real OpenSTA violation row is not matched; the gate counts 0 for "
        "every report and cannot fail")


def test_an_untagged_negative_row_is_still_counted():
    """The trailing group is OPTIONAL, deliberately.

    Requiring `(VIOLATED)` would trade one unfireable gate for a narrower one
    and would tie this gate to one tool build's choice of decoration. Measured:
    0 rows in the corpus end in a bare negative slack today, so this arm changes
    no current verdict — it exists so a build that stops printing the tag does
    not silently re-empty the gate.
    """
    assert len(M._DRV_ROW_RE.findall(
        "_07896_/B0                              3.00    6.12   -3.12\n")) == 1


def test_a_met_row_is_not_counted():
    """The accept case. A pattern that matched every row would satisfy the two
    tests above and make the gate fire on clean designs."""
    assert M._DRV_ROW_RE.findall(_MET_ROW) == []


def test_a_setup_slack_summary_line_is_not_counted():
    """It carries `(VIOLATED)` and is NOT a DRV row.

    This is why the fix is verified against a row SHAPE and not against a tag
    count: 4 of the corpus's 52 tags are on this line, and counting them would
    inflate every DRV verdict by the setup summary.
    """
    assert M._DRV_ROW_RE.findall(_SUMMARY_LINE) == []


def test_the_counter_function_sees_them():
    """The regex is not the interface — `signoff_drv_violations` is."""
    assert M.signoff_drv_violations(_REAL_ROWS) == 2
    assert M.signoff_drv_violations(_MET_ROW) == 0
    assert M.signoff_drv_violations("") == 0
    assert M.signoff_drv_violations(None) == 0


# ── the corpus, which is what makes "it works" mean something ────────────────
def _corpus():
    root = _PROGRAMS.parents[3] / "benchmark-data"
    if not root.is_dir():
        pytest.skip("benchmark-data not present in this checkout")
    return root


def _drv_row_census():
    """(reports seen, DRV rows matched, files carrying at least one)."""
    reports = rows = carriers = 0
    for p in _corpus().rglob("sta*.rpt"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        reports += 1
        n = len(M._DRV_ROW_RE.findall(text))
        rows += n
        carriers += 1 if n else 0
    return reports, rows, carriers


def test_the_pattern_matches_real_reports_at_all():
    """Guards the regression that opened this issue: a pattern that matches
    nothing passes every unit test written against synthetic strings if those
    strings were written to match it.

    vibe-ic#1028 — LEFT RED DELIBERATELY. Re-derivation is impossible and
    retirement is wrong, because this assertion is now the only thing in the
    suite that reports the loss.

    Measured on the pre-withdrawal tree: 34 DRV rows across 11 carrier files.
    ALL ELEVEN CARRIERS WERE WITHDRAWN (#1015/#1010) — 34 − 34 = 0. Eleven
    `sta*.rpt` still ship, so the population did not go to zero; what went to
    zero is the property. That distinction is the whole message below: this is
    NOT "the corpus is not checked out", the state in which nothing has been
    lost.

    Retained: `test_the_counter_function_sees_them` and the row-shape units
    above still exercise the pattern against rows copied from a shipped report.
    What is NOT retained is the confirmation that the shipped pattern still
    matches reports the flow produces today — which is exactly the regression
    this issue was opened for, and why the clause stays.
    """
    reports, rows, carriers = _drv_row_census()
    assert rows > 0, (
        "REAL-DATA ANCHOR LOST, not a checkout without the corpus: "
        f"{reports} tracked `sta*.rpt` are present and readable, and NONE of "
        f"them carries a DRV row ({carriers} carrier file(s)). All 11 files "
        "that carried the 34 measured rows lived under run roots withdrawn "
        "from publication (vibe-ic#1015/#1010). The pattern is therefore no "
        "longer confirmed against any report the flow actually produced — "
        "which is the state this issue was opened for. Publishing any run that "
        "carries a signoff STA report restores it.")


def test_the_pattern_agrees_with_an_independently_written_one():
    """Cross-check against a pattern derived from the report FORMAT rather than
    from the shipped one, so a shared mistake cannot pass both.

    Measured at 48 = 48 across 97 reports when this landed.

    vibe-ic#1028 — MUST NOT PASS OVER NOTHING. This compares two counts per
    report, so with no DRV row anywhere in the corpus every comparison is
    `0 == 0` and the test goes green while cross-checking nothing at all. A
    green here would then be read as "the two patterns agree on real reports",
    which would be false — and it is the same defect as the one this PR found
    in `_real_spef()`: a real-data claim standing on data that is not there.
    So the premise is stated up front and this SKIPS, loudly, rather than
    passing vacuously. The loss itself is reported (red) by the test above; one
    reporter is enough, but a vacuous green is not acceptable from either.
    """
    _reports, rows, _carriers = _drv_row_census()
    if rows == 0:
        pytest.skip(
            "CROSS-CHECK HAS NO SUBJECT, not a checkout without the corpus: no "
            "tracked `sta*.rpt` carries a DRV row (all 11 carriers were "
            "withdrawn, vibe-ic#1015/#1010), so every comparison below would "
            "be 0 == 0 and this test would agree about nothing while reporting "
            "that the two patterns agree.")
    independent = re.compile(
        r"^\s*\S+\s+-?[\d.]+\s+-?[\d.]+\s+-[\d.]+\s*(?:\([A-Z]+\))?\s*$", re.M)
    for p in _corpus().rglob("sta*.rpt"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        assert len(M._DRV_ROW_RE.findall(text)) == len(independent.findall(text)), p
