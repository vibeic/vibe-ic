"""A DRC report's antenna category is decided by the DECK'S vocabulary, not by
one English word (vibe-ic#2172, third recorded item).

WHAT WAS WRONG. `eda_report_audit._check_drc` classified the antenna category
with `re.compile(r"antenna", re.I)` over the report text. A KLayout gf180
sign-off RDB never writes that word: it names its rules `ANT.8`,
`ANT.16_ii_ANT.4`, `ANT.16_iii_ANT.15_V4_MIMB`, and describes each as a ratio
to "related gate oxide area".

MEASURED on the published corpus (benchmark-data 146d6656):

    ic/spm/v1.9.96_gf180mcuD/reports/phase3/drc_signoff.rpt
        antenna rule instances   20
        literal "antenna"         0
        categories_found  ['spacing', 'width', 'via', 'enclosure']

WHAT IS NOT WRONG, AND IT IS SAID FIRST SO NOBODY CHASES IT. This changes NO
project-level verdict on the corpus as it stands, and the reason is worth
keeping: `cats_found` is a UNION over every DRC report the audit discovers, and
this root's sibling `reports/phase3/drc_router.rpt` is OpenROAD's, which DOES
say "antenna" twice. Driven three ways on that root:

    drc_report_check --mode drc                     2 files  antenna PRESENT
    drc_report_check --mode drc --signoff           2 files  antenna PRESENT
    drc_report_check --mode drc --under <signoff>   1 file   antenna ABSENT

So the Step-31 shape (`--signoff`) does not narrow the file set and is masked
too. The classification is wrong at the REPORT level and latent at the PROJECT
level; it surfaces for any caller that narrows to the sign-off report, and for
any gf180 root whose OpenROAD router report is absent or itself antenna-free.
`DRC_CATEGORY_PRESENT` is a WARNING and is documented in that function as
"informational only, never gating", so no `passed` moves either way.

OVER-MATCH CONTROL, which is the direction a widening goes wrong in. Over the
31 DRC reports of the published corpus: 14 matched before and still match,
**2 files / 1 ROOT** gained (that spm report, under two paths), 15 still do not
match. The tokens are anchored so the English words that merely contain "ant"
cannot match.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eda_report_audit as A  # noqa: E402


def _antenna_re():
    """The shipped antenna category regex, read out of the shipped function.

    Taken from the source rather than re-declared here: a copy in the test
    would go on passing after the real one was reverted.
    """
    src = A.__dict__["_check_drc"].__code__
    # The table is a local of `_check_drc`; reach it the way a reader would,
    # by compiling the module's own literal out of the source.
    text = Path(A.__file__).read_text(encoding="utf-8")
    m = re.search(r'"antenna":\s*re\.compile\((r"[^"]+")\s*,\s*re\.I\)', text)
    assert m, "the antenna category regex is not where this test can read it"
    return re.compile(eval(m.group(1)), re.I), src


#: The gf180 sign-off deck's own words, copied from the corpus report named in
#: the docstring. NOT invented: every line here appears in that file.
_GF180_RDB = """\
  <category>
   <name>ANT.8</name>
   <description>ANT.8: Maximum ratio of contact area to related gate oxide area: 10</description>
  </category>
  <category>
   <name>ANT.16_ii_ANT.4</name>
   <description>ANT.16_ii_ANT.4: Maximum ratio of Metal1 perimeter area to related thin gate oxide area: 400</description>
  </category>
"""

#: A DRC report with no antenna content whatsoever. The negative control.
_NO_ANTENNA = """\
  <category><name>M2.4</name><description>M2.4: min spacing</description></category>
  <category><name>M3.1</name><description>M3.1: min width</description></category>
  total violations: 3
"""


def test_the_gf180_signoff_deck_is_classified_as_antenna():
    """THE DEFECT. 20 antenna rules and the word never appears."""
    rx, _ = _antenna_re()
    assert not re.search(r"antenna", _GF180_RDB, re.I), (
        "this fixture must NOT contain the literal, or it cannot distinguish "
        "the old classifier from the new one")
    assert rx.search(_GF180_RDB), _GF180_RDB


def test_the_openroad_wording_still_classifies_as_antenna():
    """THE PAIRED ARM. Widening must not cost the case that already worked."""
    rx, _ = _antenna_re()
    assert rx.search("antenna check: 1 net violations, 1 pin violations")
    assert rx.search("ANT-0008 antenna violation")


def test_a_report_with_no_antenna_content_is_not_classified_as_antenna():
    """THE OVER-MATCH CONTROL, and the direction a widening goes wrong in."""
    rx, _ = _antenna_re()
    assert not rx.search(_NO_ANTENNA), _NO_ANTENNA


@pytest.mark.parametrize("word", [
    "SLANT", "GIANT", "ANTI-FUSE", "PLANT", "constant", "ANT", "ANTENNAE",
])
def test_english_words_containing_ant_do_not_manufacture_the_category(word):
    """`ANT` is not a token; `ANT.<digit>` / `ANT-<digit>` is.

    `ANTENNAE` is in this list on purpose and is EXPECTED to match -- it
    contains the literal the old classifier used, so refusing it would be a
    regression, not a tightening. Every other member must not match.
    """
    rx, _ = _antenna_re()
    line = f"  <description>{word} rule check: 0 violations</description>"
    if "ANTENNA" in word.upper():
        assert rx.search(line), line
    else:
        assert not rx.search(line), line


def test_the_category_never_decides_the_verdict(tmp_path):
    """THE BLAST RADIUS, driven rather than grepped.

    Two projects identical but for antenna content in their one DRC report.
    The category set must DIFFER (that is the fix working) and `passed` must
    NOT (that is the fix being safe). If a future edit lets category presence
    gate again, this widening silently becomes a verdict change on every gf180
    run at once, and that is an owner decision, not a side effect of a regex.
    """
    def _run(body: str):
        proj = tmp_path / ("with" if "ANT." in body else "without")
        rpt = proj / "reports" / "phase3"
        rpt.mkdir(parents=True)
        # Padded past MIN_REPORT_BYTES["drc"] so the verdict is decided by the
        # report's content and not by its size.
        filler = "\n".join(
            f"  <item><category>M2.4</category><n>{i}</n></item>"
            for i in range(200))
        (rpt / "drc_signoff.rpt").write_text(
            "<report>\n" + body + filler +
            "\n  <description>M2.4: min spacing</description>"
            "\n  <description>M3.1: min width</description>"
            "\n  <description>via enclosure density</description>"
            "\ntotal: 0 violations\n</report>\n", encoding="utf-8")
        with A.named_subjects([rpt / "drc_signoff.rpt"]):
            res = A._check_drc(proj)
        return set(res.summary.get("categories_found", [])), res.passed

    cats_with, passed_with = _run(_GF180_RDB)
    cats_without, passed_without = _run("")

    assert "antenna" in cats_with, cats_with
    assert "antenna" not in cats_without, cats_without
    assert passed_with == passed_without, (passed_with, passed_without)
