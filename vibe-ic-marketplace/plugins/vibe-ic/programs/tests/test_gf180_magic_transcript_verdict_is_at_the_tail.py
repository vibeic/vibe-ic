"""A Magic DRC transcript puts its verdict at the END, and the classifier read
only the first 64 kB.

MEASURED, gf180mcuD chip path 2026-08-21, on the real 11 471 075-byte transcript
LibreLane's `Magic.DRC` step emitted for `spm`:

    'Magic 8.3'        first at byte           1     <- inside the 64 kB head
    'No errors found'  first at byte  11 470 745     <- 175x beyond it
    'COUNT:'           first at byte  11 470 769
    'drc count|why|check|catchup'  ABSENT ENTIRELY

So the banner was visible and the verdict was not, and the file classified as
"no recognised producer signature" -- a CLEAN Magic DRC reported as an
UNREADABLE report, while the shuttle operator's own container passed the same
layout 16/16. Two independent causes, both fixed here:

  1. the count dialect. This flow writes `[INFO] COUNT: N`; the classifier knew
     only `DRC errors found: N`, which that flow never emits.
  2. the window. A transcript's verdict is at its tail by nature.

Anchoring matters: `COUNT:` is a common word, so the pattern is anchored to line
start (with an optional `[INFO]` tag) and must not fire on prose.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _signoff_drc_format as F  # noqa: E402
import eda_report_audit as A  # noqa: E402

_MAGIC_HEAD = (
    "\nMagic 8.3 revision 660 - Compiled on Mon Jun  8 08:14:47 UTC 2026.\n"
    "Starting magic under Tcl interpreter\n"
    "Using NULL graphics device.\n"
)
_MAGIC_TAIL_CLEAN = "\nNo errors found.\n[INFO] COUNT: 0\n[INFO] Should be divided by 3 or 4\n"
_MAGIC_TAIL_DIRTY = "\n[INFO] COUNT: 7\n[INFO] Should be divided by 3 or 4\n"
#: Big enough that the tail is far outside the 64 kB head window, exactly as the
#: real transcript's is.
_BULK = "".join(f'Reading "VIA_via3_{i}".\n' for i in range(6000))


def _transcript(tail):
    return _MAGIC_HEAD + _BULK + tail


def test_the_bulk_really_pushes_the_verdict_past_the_head_window():
    """CONTROL: if the fixture were small the test would prove nothing."""
    t = _transcript(_MAGIC_TAIL_CLEAN)
    assert t.index("COUNT:") > F._HEAD_BYTES, (
        "fixture too small — the verdict must sit beyond the head window for "
        "this test to exercise the defect"
    )


def test_a_large_clean_magic_transcript_is_CLASSIFIED():
    """THE DEFECT: banner in the head, verdict in the tail -> unrecognised."""
    p = F.classify_text(_transcript(_MAGIC_TAIL_CLEAN))
    assert p.kind == F.MAGIC, (
        f"a clean Magic DRC transcript classified as {p.kind!r} "
        f"({p.evidence!r}) — an unreadable report, not a clean one"
    )


def test_the_short_report_form_is_classified_too():
    """The same step also writes a 4-line `.rpt`; it has no Magic banner and no
    `drc <cmd>`, only the count, so it needs the count dialect."""
    p = F.classify_text("chip_top\n---------\n[INFO] COUNT: 0\n")
    assert p.kind == F.MAGIC, (p.kind, p.evidence)


def test_the_violation_count_parses_from_the_magic_dialect():
    assert A._drc_real_violation_count(_transcript(_MAGIC_TAIL_CLEAN)) == (0, 0)
    assert A._drc_real_violation_count("chip_top\n[INFO] COUNT: 0\n") == (0, 0)


def test_NEGATIVE_a_dirty_magic_transcript_is_still_caught():
    """NO-LEAK (methodology 4.05). Teaching a gate a new dialect widens what it
    accepts, so the load-bearing half is that a REAL violation still counts."""
    got = A._drc_real_violation_count(_transcript(_MAGIC_TAIL_DIRTY))
    assert got is not None and got[0] == 7, got


def test_NEGATIVE_an_inline_prose_count_does_not_fire():
    """`COUNT:` is a common word. An unanchored pattern would pick a number out
    of 11 MB of prose and report it as a DRC verdict."""
    assert A._drc_real_violation_count(
        "some prose mentioning count: 3 inline\n") is None
    assert F.classify_text("a log that merely says count: 3 mid-line\n").kind \
        is not F.MAGIC


def test_NEGATIVE_a_file_with_no_verdict_at_all_stays_unrecognised():
    """UNMEASURED IS NOT ZERO: a transcript that never reports a count must not
    become a clean one just because it says the word 'magic'."""
    p = F.classify_text(_MAGIC_HEAD + _BULK)
    assert p.kind is not F.MAGIC or \
        A._drc_real_violation_count(_MAGIC_HEAD + _BULK) is None
