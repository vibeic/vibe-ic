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

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

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
    """The PUBLISHED corpus, wherever it actually is.

    It used to be `<repo>/benchmark-data` and is now its own repository,
    `vibeic/benchmark-data`. The directory of that name still exists here — it
    holds the design INPUTS the flow reads — so `root.is_dir()` stopped being
    the question: it is true while carrying not one STA report, and the two
    sweeps below then measured nothing and said so as `0 > 0`, i.e. as a defect
    in the pattern. `corpus_root()` asks the question that is actually being
    asked (is a published cell readable here?) and `@needs_corpus` renders a
    "no" as a skip naming the corpus rather than as a finding about the regex.
    """
    root = corpus_root()
    assert root is not None, (
        "@needs_corpus should have skipped before this point")
    return root


@needs_corpus
def test_the_pattern_matches_real_reports_at_all():
    """Open real reports and compare with an independently written parser.

    The current published tree contains STA reports but no violating DRV row;
    requiring ``total > 0`` therefore turned a clean measured population into
    a regex failure.  Positive matching remains proven by ``_REAL_ROWS``
    above.  Here the non-vacuity is the number of reports opened, and a future
    real violation must be counted identically by both parsers.
    """
    independent = re.compile(
        r"^\s*\S+\s+-?[\d.]+\s+-?[\d.]+\s+-[\d.]+\s*(?:\([A-Z]+\))?\s*$",
        re.M)
    reports = sorted(_corpus().rglob("sta*.rpt"))
    assert reports, "no STA report under the published corpus"
    shipped_total = independent_total = opened = 0
    for p in reports:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        opened += 1
        shipped_total += len(M._DRV_ROW_RE.findall(text))
        independent_total += len(independent.findall(text))
    assert opened > 0, "STA reports were named but none could be opened"
    assert shipped_total == independent_total, (
        f"shipped DRV parser counted {shipped_total}, independently written "
        f"parser counted {independent_total} across {opened} opened report(s)")


@needs_corpus
def test_the_pattern_agrees_with_an_independently_written_one():
    """Cross-check against a pattern derived from the report FORMAT rather than
    from the shipped one, so a shared mistake cannot pass both.

    Measured at 48 = 48 across 97 reports when this landed.
    """
    independent = re.compile(
        r"^\s*\S+\s+-?[\d.]+\s+-?[\d.]+\s+-[\d.]+\s*(?:\([A-Z]+\))?\s*$", re.M)
    compared = 0
    for p in _corpus().rglob("sta*.rpt"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        compared += 1
        assert len(M._DRV_ROW_RE.findall(text)) == len(independent.findall(text)), p
    # A loop over nothing agrees with everything. This test read zero reports for
    # as long as the corpus was absent and still reported PASS — the exact shape
    # #579 is about, one level up. It is the corpus that must be missing loudly,
    # never the comparison that must be silently empty.
    assert compared > 0, (
        "no STA report under the published corpus — the cross-check compared "
        "nothing and a PASS here would mean 'I could not look'")
