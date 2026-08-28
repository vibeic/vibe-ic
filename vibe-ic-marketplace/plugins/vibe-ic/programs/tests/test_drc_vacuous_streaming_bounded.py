"""Streaming / bounded-memory tests for drc_vacuous_pass_check.

The defect these guard: `drc_vacuous_pass_check` used `Path.read_text` to pull an
ENTIRE DRC report into memory and then ran several whole-file regex passes over
it. On a real sign-off run the report was multi-gigabyte / ~10^8 lines, so the
read plus the regex passes overran the flow's per-gate budget and the gate was
killed. The gate correctly records that a timeout is NOT a verdict and marks the
step INCONCLUSIVE — but a step that should get a verdict never got one.

The fix streams the report through a fixed-size sliding window instead. Both
tests below are BIDIRECTIONAL negative controls: each FAILS against the
byte-identical pre-fix program (whole-file `read_text`) and PASSES against the
streaming version.

  1. SAME VERDICT, SAME EVIDENCE — `_scan_chunks` reproduces the whole-file
     reference (`_classify_one` / `_is_drc_log` / `bool(text.strip())`)
     byte-for-byte, even under a one-character read window that forces a
     boundary between almost every token. (Against pre-fix: no `_scan_chunks`
     exists, so the test errors — red.)

  2. BOUNDED MEMORY — peak RSS does not scale with report size. Growing the
     report 8x leaves peak RSS within a fixed window. (Against pre-fix: it holds
     the whole file, so peak RSS tracks file size and the assertion fails.)
"""
from __future__ import annotations

import io
import random
import re
import resource
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "drc_vacuous_pass_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import drc_vacuous_pass_check as dvp  # noqa: E402
import _watchdog  # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)


# ---------------------------------------------------------------------------
# Property 1 — the streaming window scanner is byte-identical to the whole-file
# reference. `_classify_one` + `_is_drc_log` + `bool(text.strip())` ARE the
# defined semantics; `_scan_chunks` must derive the same facts one window at a
# time. A deliberately tiny `block` puts a read boundary between almost every
# character, so cross-boundary tokens, false word-boundaries at window edges,
# and the finditer accept-once accounting are all exercised.
# ---------------------------------------------------------------------------
def _reference(text: str):
    return (bool(text.strip()), dvp._is_drc_log(text), dvp._classify_one(text))


def _streamed(text: str, block: int, overlap: int):
    ne, is_drc, c, _cited = dvp._scan_chunks(
        io.StringIO(text).read, (), block=block, overlap=overlap)
    return (ne, is_drc, c)


# Crafted reports, including cross-line coincidences that a naive line-by-line
# scan gets wrong (a number ending a line followed by a keyword starting the
# next, matched by the whole-file regex's `\s+`/`\s*` spanning the newline).
_FIXED_REPORTS = [
    "",
    "   \n\t\n",
    "random text with no keywords\n",
    "KLayout DRC engine\nTotal errors: 0\n",
    "DRC violations found: 13\nsome noise\n",
    "0 errors\n4211 shapes\ncells: 87\nshape count: 0\n",
    "Loading cell top\nchecking foo\nlayout read\nDRC is clean\n",
    "polygon: (1,2)\n<cell>x</cell>\n12 polygons\nrectangle count = 5\nerror\n",
    "no drc issues found\nTotal area: 12345.6\n",
    "errors: 0\nerrors: 7\nviolations = 3\n",
    "5\nerrors\n",                    # number, newline, keyword -> whole-file match
    "geometriesviolations\n",         # NO word-boundary before 'violations'
    "drc55\nlayout readX\n5errors\n0errorsx\n",
    "Total DRC errors found: 0\n" * 5,
    "cells: 5\ncells: 6\ncells: 7\n" * 3,
]

_TOKENS = [
    "error", "errors", "violation", "violations", "issue", "issues", "drc",
    "polygon", "polygons", "shape", "shapes", "cell", "cells", "rectangle",
    "geometry", "geometries", "count", "clean", "clear", "total", "area",
    "loading", "reading", "checking", "layout read", "cell x loaded",
    "empty cell", "nothing to check", "no ", "found",
    "0", "1", "5", "13", "87", "4211", ": ", "= ", " ", "\n", "  ", "\t",
    ":", "=", "(", ")", ".", "x", "abc", "-",
]


@pytest.mark.parametrize("block", [1, 2, 3, 5, 7, 64, 4096])
def test_streaming_is_byte_identical_to_whole_file(block):
    # overlap far exceeds the longest token / whitespace run in the corpus below,
    # which is the ONLY precondition of the equivalence (a match longer than the
    # overlap is the one construct outside it — orders of magnitude beyond any
    # real DRC-report record).
    overlap = 4096
    rng = random.Random(20260804)
    cases = list(_FIXED_REPORTS)
    for _ in range(3000):
        n = rng.randint(0, 24)
        cases.append("".join(rng.choice(_TOKENS) for _ in range(n)))
    for text in cases:
        assert len(text) < overlap
        got = _streamed(text, block, overlap)
        want = _reference(text)
        assert got == want, f"block={block} text={text!r}\n got={got}\nwant={want}"


def test_streaming_matches_reference_on_a_real_report_slice():
    """A concrete KLayout-shaped report: the streaming and whole-file paths must
    agree on verdict facts. (This is the in-process twin of the program-level
    old-vs-new equivalence run on a real corpus report.)"""
    text = (
        "<?xml version='1.0' encoding='utf-8'?>\n<report-database>\n"
        " <description>FreePDK-style DRC runset</description>\n"
        " <top-cell>some_design</top-cell>\n <items>\n"
        + (" <item>\n  <category>'M2.SPACING'</category>\n"
           "  <cell>some_design</cell>\n  <multiplicity>1</multiplicity>\n"
           "  <values>\n   <value>polygon: (1.0,2.0;1.0,2.1;1.1,2.1;1.1,2.0)</value>\n"
           "  </values>\n </item>\n") * 200
        + " </items>\n</report-database>\n"
    )
    assert _streamed(text, dvp._READ_BLOCK, dvp._CARRY_OVERLAP) == _reference(text)
    # and under a pathological 1-byte window
    assert _streamed(text, 1, 4096) == _reference(text)


# ---------------------------------------------------------------------------
# Property 2 — peak RSS must not scale with report size.
#
# Each measurement runs the checker in a FRESH process that imports the module,
# runs `audit()` on one report, and prints its own peak RSS (RUSAGE_SELF high-
# water mark, so it captures the moment the whole file would have been resident).
# Base interpreter RSS cancels in the growth delta. The pre-fix `read_text`
# program's peak tracks the file, so growing the report 8x grows peak RSS by
# ~7x the small file; the streaming program's peak stays within a fixed window.
# ---------------------------------------------------------------------------
_RSS_WRAPPER = textwrap.dedent(
    """
    import resource, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    import drc_vacuous_pass_check as dvp
    dvp.audit(Path(sys.argv[2]))
    print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    """
)

_MiB = 1024 * 1024


def _write_report(path: Path, size_bytes: int) -> Path:
    """A realistic KLayout-XML-shaped DRC report of ~size_bytes. The body line
    carries a `polygon:` value (like a real record) but no geometry COUNT token,
    so the checker's `reported_geometry_counts` list stays empty on both program
    versions — the memory difference is purely the file materialisation."""
    header = ("<?xml version='1.0'?>\n<report-database>\n"
              " <description>DRC runset</description>\n <items>\n")
    line = ("  <item><category>'SPACING'</category>"
            "<value>polygon: (12.3,45.6;12.3,47.8;12.4,47.8;12.4,45.6)</value>"
            "</item>\n")
    chunk = line * 1024
    with open(path, "w") as fh:
        fh.write(header)
        written = len(header)
        while written < size_bytes:
            fh.write(chunk)
            written += len(chunk)
        fh.write(" </items>\n</report-database>\n")
    return path


def _peak_rss_kib(report_path: Path, programs_dir: Path) -> int:
    out = _supervised(
        [sys.executable, "-c", _RSS_WRAPPER, str(programs_dir), str(report_path)])
    assert out.returncode == 0, f"checker failed: {out.stderr}"
    return int(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(sys.platform != "linux",
                    reason="RUSAGE_SELF.ru_maxrss is KiB only on Linux")
def test_peak_rss_does_not_scale_with_report_size(tmp_path):
    small_bytes, large_bytes = 8 * _MiB, 64 * _MiB      # 8x
    small = _write_report(tmp_path / "small.rpt", small_bytes)
    large = _write_report(tmp_path / "large.rpt", large_bytes)
    rss_small = _peak_rss_kib(small, SCRIPT.parent)
    rss_large = _peak_rss_kib(large, SCRIPT.parent)
    growth_kib = rss_large - rss_small
    file_growth_kib = (large_bytes - small_bytes) // 1024   # 56 MiB

    # The read window is a few MiB; a generous fixed ceiling well below the
    # 56 MiB of extra file proves peak RSS is bounded by the window, not the
    # file. The pre-fix whole-file read grows peak RSS by ~file_growth_kib and
    # blows past this ceiling — that is the negative control.
    ceiling_kib = 20 * 1024
    assert growth_kib < ceiling_kib, (
        f"peak RSS grew {growth_kib} KiB (small={rss_small}, large={rss_large}) "
        f"when the report grew {file_growth_kib} KiB — peak memory is scaling "
        f"with file size, not bounded by the read window")
# ---------------------------------------------------------------------------
# Property 3 — the bound holds for a report with NO NEWLINE in it.
#
# The trim snaps the cut back to a real left boundary so the next window's first
# character reads to the regex exactly as it does whole-file. The first revision
# knew only ONE such boundary, `\n`, and when it found none it fell back to
# "keep everything" — so a report without newlines was NEVER trimmed and the
# buffer grew to the whole file, with a `buf.lower()` copy of it per window on
# top. MEASURED on a 256 MiB single-line report, that made the streaming path
# 804 MiB / 2:19.98 against the whole-file `read_text` it replaces at 528 MiB /
# 1:29.33 — 1.5x the memory and 1.6x the time of the code it was supposed to
# bound, and the gap grew super-linearly with size.
#
# Nothing in a DRC report format requires newlines, and the claim in the module
# comment is unconditional, so the property is pinned here rather than assumed.
# ---------------------------------------------------------------------------
def _write_newline_free_report(path: Path, size_bytes: int) -> Path:
    """The same record shape as `_write_report`, emitted as ONE line."""
    unit = ("<item><category>'SPACING'</category>"
            "<value>polygon: (12.3,45.6;12.3,47.8;12.4,47.8;12.4,45.6)</value>"
            "</item> ")
    chunk = unit * 1024
    with open(path, "w") as fh:
        head = "DRC report "
        fh.write(head)
        written = len(head)
        while written < size_bytes:
            fh.write(chunk)
            written += len(chunk)
        fh.write(" Total DRC errors found: 0")
    return path


@pytest.mark.skipif(sys.platform != "linux",
                    reason="RUSAGE_SELF.ru_maxrss is KiB only on Linux")
def test_peak_rss_is_bounded_on_a_report_with_no_newlines(tmp_path):
    small_bytes, large_bytes = 4 * _MiB, 48 * _MiB      # 12x
    small = _write_newline_free_report(tmp_path / "s.rpt", small_bytes)
    large = _write_newline_free_report(tmp_path / "l.rpt", large_bytes)
    rss_small = _peak_rss_kib(small, SCRIPT.parent)
    rss_large = _peak_rss_kib(large, SCRIPT.parent)
    growth_kib = rss_large - rss_small
    file_growth_kib = (large_bytes - small_bytes) // 1024

    ceiling_kib = 20 * 1024
    assert growth_kib < ceiling_kib, (
        f"peak RSS grew {growth_kib} KiB (small={rss_small}, "
        f"large={rss_large}) when a NEWLINE-FREE report grew "
        f"{file_growth_kib} KiB — the trim found no cut point and never "
        f"trimmed, so the window bound does not hold for this report shape")


def test_the_bound_is_on_the_WINDOW_and_not_on_the_retained_counts():
    """WHAT THE BOUND DOES NOT COVER, pinned so the claim cannot be restated
    without it. Both memory properties above deliberately use a body with no
    geometry-COUNT token (their fixture docstrings say so), because
    `reported_geometry_counts` retains one float per matched summary and that
    list is proportional to the report, not to the window.

    On a body that prints a count on EVERY record the streaming path therefore
    has no memory advantage at all. MEASURED, 64 MiB report, `/usr/bin/time -v`,
    whole-file (origin/main) vs streaming:

        newline-free      143.8 MiB / 12.99 s  ->  46.5 MiB / 1.49 s
        newline-delimited 144.0 MiB / 17.55 s  ->  46.6 MiB / 6.91 s
        counts-printing   349.7 MiB / 17.44 s  -> 350.4 MiB / 7.36 s   <-- MORE

    The retained-counts cost is a separate defect with a separate fix (a 1 GB
    report yielded 10.88 M entries and a 174 MB JSON). This test pins the
    MECHANISM — the list length tracks the record count — rather than a memory
    inequality, so it stays true and stays honest either way."""
    unit = "cell top: 4211 shapes checked\n"
    for records in (100, 1000):
        text = "DRC report\n0 errors\n" + unit * records
        c = dvp._classify_one(text)
        assert len(c["reported_geometry_counts"]) == records, \
            "fixture no longer prints one count per record"
        assert _streamed(text, 4096, 4096)[2] == c
    # ...and the fixtures the memory properties use retain NOTHING, which is
    # why those measurements isolate the window.
    quiet = ("  <item><category>'SPACING'</category>"
             "<value>polygon: (12.3,45.6;12.3,47.8)</value></item>\n") * 200
    assert dvp._classify_one(quiet)["reported_geometry_counts"] == []


def test_a_newline_free_report_still_gets_the_whole_file_verdict(tmp_path):
    """Bounding the buffer must not cost the answer: the trim's non-newline cut
    points are chosen so the next window's left edge reads to the regex exactly
    as the whole file does."""
    text = ("DRC report 4211 shapes "
            + "M1.SPACING polygon (1.0,2.0;1.0,2.1) " * 20000
            + " Total DRC errors found: 0")
    assert "\n" not in text
    assert _streamed(text, dvp._READ_BLOCK, dvp._CARRY_OVERLAP) \
        == _reference(text)
    # and under a window small enough that the trim's cut path runs repeatedly
    assert _streamed(text, 4096, 4096) == _reference(text)


# ---------------------------------------------------------------------------
# Property 4 — a number the report's own prose DENIES is not a declaration.
#
# vibe-ic#712: an extractor that greps a value out of a sentence and publishes
# it as a declared fact republishes the values the sentence retracts. This
# checker does that in two places, and BOTH of them relax the gate:
# `reported_geometry_counts` is evidence (B) that the run looked at geometry,
# and a positive `nonzero_count` both satisfies (C) and routes the file past the
# vacuous check entirely. One shared extractor owns the polarity consult, so the
# whole-file reference path and the streaming path cannot disagree about it.
# ---------------------------------------------------------------------------
_DENIED_GEOM = ("DRC report\n"
                "The 4211 shapes reported by the previous run are not "
                "present in this one.\n"
                "0 errors\n")

_AFFIRMED_GEOM = ("DRC report\n"
                  "The run checked 4211 shapes in this cell.\n"
                  "0 errors\n")

_DENIED_VIOL = ("DRC report\n"
                "The 13 violations listed above are no longer applicable.\n")


def test_a_geometry_count_the_report_denies_is_not_evidence():
    c = dvp._classify_one(_DENIED_GEOM)
    assert c["reported_geometry_counts"] == [], \
        "a retracted shape count was published as evidence the run saw geometry"
    assert c["reported_geometry_max"] is None
    # the streaming path inherits the same answer, at every window size
    for blk in (1, 64, 4096, dvp._READ_BLOCK):
        assert _streamed(_DENIED_GEOM, blk, 4096)[2] == c


def test_an_affirmed_geometry_count_is_still_evidence():
    """Negative control: the consult must not be a blanket suppressor."""
    c = dvp._classify_one(_AFFIRMED_GEOM)
    assert c["reported_geometry_counts"] == [4211.0]
    assert c["reported_geometry_max"] == 4211.0
    for blk in (1, 64, 4096, dvp._READ_BLOCK):
        assert _streamed(_AFFIRMED_GEOM, blk, 4096)[2] == c


def test_a_violation_count_the_report_denies_is_not_the_verdict():
    c = dvp._classify_one(_DENIED_VIOL)
    assert c["nonzero_count"] is None, \
        ("a retracted violation count became this run's violation count — it "
         "would then prove geometry (C) and route the file past the vacuous "
         "check")
    for blk in (1, 64, 4096, dvp._READ_BLOCK):
        assert _streamed(_DENIED_VIOL, blk, 4096)[2] == c


def test_a_clean_verdict_is_not_read_as_denying_itself():
    """OVER-BREADTH GUARD. `zero_count` is a boolean over a pattern's PRESENCE,
    not a number lifted out of prose, and its own canonical spelling IS a
    negation. Running the denial vocabulary over it would make the cleanest
    statement a DRC tool can print deny itself."""
    for text in ("no drc errors found\n4211 shapes\n",
                 "no drc violations found\ncells: 87\n",
                 "DRC is clean\n0 errors\n12 polygons\n"):
        c = dvp._classify_one(text)
        assert c["zero_count"] is True, f"{text!r} stopped reading as clean"
        for blk in (1, 64, dvp._READ_BLOCK):
            assert _streamed(text, blk, 4096)[2] == c


def test_the_denial_substring_gate_is_sound():
    """`_denial_possible` is a SPEED gate in front of the polarity consult: a
    text holding none of its literals is never scanned for a denial at all. If
    a denial word were ever added to `_prose_polarity.NEGATION_RE` that none of
    the literals covers, the gate would start silently skipping real denials —
    a fast reject that is not a necessary condition is a wrong answer, not an
    optimisation.

    So the claim is proved against the vocabulary itself rather than restated:
    for every string the real `NEGATION_RE` matches, the gate must say
    'possible'. Driven over the denial vocabulary as it is spelled today plus
    random text, so an addition that breaks the coupling turns this red."""
    denials = [
        "not", "no", "none", "without", "excluding", "excluded", "excludes",
        "never", "non", "non-", "removed", "obsolete", "superseded",
        "supersedes", "n/a", "inapplicable", "deprecated", "no longer",
        "does not apply", "非", "无", "無", "不", "否",
    ]
    for w in denials:
        for ctx in (w, f"the value is {w} here", f"({w})", f"X {w.upper()} Y"):
            if dvp._DENIAL_RE.search(ctx):
                assert dvp._denial_possible(ctx.lower()), (
                    f"NEGATION_RE matches {ctx!r} but the substring gate would "
                    f"skip it — real denials would go unread")
    rng = random.Random(20260805)
    alphabet = "abcdefghijklmnopqrstuvwxyz /-0123456789\n"
    for _ in range(20000):
        t = "".join(rng.choice(alphabet)
                    for _ in range(rng.randint(0, 40)))
        if dvp._DENIAL_RE.search(t):
            assert dvp._denial_possible(t.lower()), \
                f"NEGATION_RE matches {t!r} but the substring gate skips it"


def _present_tables():
    """Every (pattern, necessary-substring table) pair the scanner gates on,
    paired the same way `_scan_chunks` pairs them — by INDEX into the pattern
    list, which is the coupling that can silently rot."""
    pairs = [(dvp._IS_DRC_RE, dvp._IS_DRC_TRIG)]
    for lst, trig in ((dvp._ZERO_COUNT_RE, dvp._ZERO_TRIG),
                      (dvp._NONZERO_COUNT_RE, dvp._NONZERO_TRIG),
                      (dvp._REPORTED_COUNT_RE, dvp._REPORTED_TRIG)):
        assert len(lst) == len(trig), "pattern/trigger tables are out of step"
        pairs += list(zip(lst, trig))
    wording = [r for _n, r in dvp._WORDING_HINT_RE]
    assert len(wording) == len(dvp._WORDING_TRIG)
    pairs += list(zip(wording, dvp._WORDING_TRIG))
    return pairs


def test_every_present_gate_is_a_NECESSARY_condition_of_its_pattern():
    """The five `_present` tables are SOUND FAST REJECTS: a window that holds
    none of a pattern's literals is never scanned with that pattern at all. If
    a table ever stops being a necessary condition of its pattern, the scanner
    silently skips real matches — a wrong answer, not an optimisation.

    The shipped suite proves this for `_DENIAL_TRIG` only
    (`test_the_denial_substring_gate_is_sound`); the five tables that gate the
    verdict patterns themselves had no equivalent proof and were pinned only
    incidentally by the equivalence fuzz. Proved the same way: against the
    PATTERNS as they are spelled today, so an edit that breaks the coupling
    turns this red rather than quietly disabling a scan."""
    rng = random.Random(20260806)
    alphabet = _TOKENS + ["clean", "clear", "geometries", "empty layout",
                          "nothing to check", "cell (?) ", "couldn't find",
                          "total area", "shape count", "issues", "found",
                          "reported", "detected", "present", "loaded"]
    corpus = list(_FIXED_REPORTS)
    for _ in range(6000):
        n = rng.randint(1, 8)
        corpus.append("".join(rng.choice(alphabet) for _ in range(n)))
    checked = 0
    for pat, trig in _present_tables():
        hits = 0
        for text in corpus:
            if pat.search(text):
                hits += 1
                assert dvp._present(trig, text.lower()), (
                    f"{pat.pattern!r} matches {text!r} but its trigger table "
                    f"{trig!r} would skip the scan — a real match goes unread")
        assert hits, f"corpus never exercised {pat.pattern!r}"
        checked += 1
    assert checked == len(_present_tables()) >= 12, checked


def test_the_trim_cuts_only_where_the_whole_file_has_a_boundary():
    """The trim may only cut where the whole file ALSO has a left boundary.

    Cut inside a token and the next window begins mid-token, so `\\b` and the
    `(?<![\\w.-])` citation look-behind see a start-of-string the whole file
    never had. MEASURED, when the non-newline fallback was an unconditional
    hard cut: a `top.gds` citation harvested out of `xtop.gds`.

    Driven on a newline-free buffer past `_SAFE_CUT_SCAN`, with the requested
    cut deliberately mid-token, so only the safe-character search can find an
    honest cut point."""
    body = ("a" * 100 + " ") * 700            # > _SAFE_CUT_SCAN, no newline
    buf = body + "xtop.gds trailing"
    keep_from = len(body) + 4                 # inside "xtop"
    assert "\n" not in buf
    assert keep_from >= dvp._SAFE_CUT_SCAN, "fixture must reach the fallback"

    cut = dvp._safe_cut_point(buf, keep_from)

    assert 0 < cut <= keep_from, f"nonsensical cut {cut} for {keep_from}"
    assert not re.match(r"[\w.\-]", buf[cut - 1]), (
        f"the window was cut inside a token (buf[{cut - 1}]={buf[cut - 1]!r}) "
        f"— the next window would start mid-token and the regex would see a "
        f"word boundary the whole file never had")


# ---------------------------------------------------------------------------
# Property 5 — the polarity consult must not FABRICATE a denial.
#
# The consult is NEW in this change: `origin/main` has none at all, so every
# verdict it moves is a verdict this change is responsible for. It moved two it
# should not have, on the two most ordinary lines a DRC tool prints. MEASURED
# end-to-end against `origin/main`:
#
#   "cell top: checked 4211 shapes, no drc violations found"
#        base  rc=0 PASS/DRC_CLEAN_EARNED       geom=[4211.0]
#        here  rc=1 INCONCLUSIVE/DRC_VACUOUS_PASS      geom=[]
#   "13 DRC errors found, none waived"
#        base  rc=0 PASS/DRC_NONZERO_COUNT      nonzero=13
#        here  rc=1 INCONCLUSIVE/DRC_UNVERIFIABLE_RUN  nonzero=None
#
# In both, the denial belongs to a DIFFERENT assertion on the same line. The
# same facts on a DIFFERENT line already agreed with base — which is why the
# shipped tests, all written in the separate-line shape, stayed green.
# ---------------------------------------------------------------------------
#: The separator between the two assertions is NOT part of the defect, so it is
#: swept. The first fix for this clamped the forward reach at a comma; holding
#: both assertions fixed and varying only this list, 8 of 11 still fabricated —
#: TAB and double space among them, i.e. any column-formatted report. A fix
#: that closes its own witnesses is not a fix, and the sweep is what says so.
_SEPS = [", ", "\t", " / ", "; ", " - ", "  ", " (", ". ", " -- ", " | ", " "]
_FAMILY_A = "cell top: checked 4211 shapes{sep}no drc violations found\n"
_FAMILY_B = "13 DRC errors found{sep}none waived\n"
_DIFF_LINE_CLEAN = ("cell top: checked 4211 shapes\n"
                    "no drc violations found\ntotal DRC errors: 0\n")
_DIFF_LINE_NONZERO = "13 DRC errors found\nnone waived\n"


def _all_paths(text: str):
    """The whole-file answer, and the streaming answer at four window sizes.
    One helper owns the consult, so these must never disagree."""
    c = dvp._classify_one(text)
    for blk in (1, 64, 4096, dvp._READ_BLOCK):
        assert _streamed(text, blk, 4096)[2] == c, f"window {blk} disagrees"
    return c


@pytest.mark.parametrize("sep", _SEPS, ids=[repr(s) for s in _SEPS])
def test_the_clean_verdict_never_denies_the_evidence_beside_it(sep):
    """THE FABRICATION, and it is a CLASS, not two strings. `no ... violations
    found` IS the clean verdict — the very statement `_ZERO_COUNT_RE`
    recognises, and the one the consult already exempts for `zero_count` on the
    grounds that running the denial vocabulary over it "would make the cleanest
    statement in the corpus deny itself". That exemption was written for the
    boolean and never applied to the SPAN, so the identical phrase went on
    denying the geometry count printed beside it — whatever separated them."""
    c = _all_paths(_FAMILY_A.format(sep=sep))
    assert c["reported_geometry_counts"] == [4211.0], (
        f"separator {sep!r}: a shape count was retracted by the CLEAN VERDICT "
        f"printed beside it — the gate then refuses a clean the report earned")
    assert c["zero_count"] is True


@pytest.mark.parametrize("sep", _SEPS, ids=[repr(s) for s in _SEPS])
def test_a_denial_about_waivers_is_refused_UNIFORMLY_and_DISCLOSED(sep):
    """THE RESIDUAL, pinned as a residual. "none waived" is a denial about
    WAIVERS, not about the error count, and nothing structural separates it
    from a real retraction without enumerating separators again — the move this
    change just rejected. So it stays DENIED, and the two things that matter
    about a residual are pinned instead:

      * it behaves the SAME for every separator (a gate whose answer depends on
        which whitespace the tool printed is worse than one that is uniformly
        conservative), except where the separator is a genuine record break;
      * it is DISCLOSED — `polarity_refused` counts it, so no verdict can say
        "no count was printed" about a report that printed one.

    Its direction is the safe one: it drops evidence and moves the verdict to
    INCONCLUSIVE, so it can lose a PASS the report earned but can never let a
    failure through."""
    c = _all_paths(_FAMILY_B.format(sep=sep))
    if sep in dvp._RECORD_STOPS:
        assert c["nonzero_count"] == 13, "a record break must end the record"
        assert c["polarity_refused"] == 0
    else:
        assert c["nonzero_count"] is None
        assert c["polarity_refused"] >= 1, (
            "the refusal is invisible — the verdict will say the report "
            "printed no count when it printed one and this gate refused it")


@pytest.mark.parametrize("block", [1, 2, 3, 5, 7, 16, 64, 512, 4096])
@pytest.mark.parametrize("overlap", [8, 16, 32, 64, 128, 512, 4096])
@pytest.mark.parametrize("text", [
    "the 3 violations reported earlier are not present\n7 errors\n",
    "not applicable: 3 errors\nviolations = 9\n",
    "the 3 issues above are no longer applicable" + (" x" * 60)
    + "\n11 drc errors\n",
    "no longer applicable: 5 errors, then 21 violations\n",
    "the 2 errors are not present" + ("\nfiller" * 3) + "\n8 violations\n",
])
def test_a_denied_match_advances_the_violation_cursor_exactly_once(
        text, block, overlap):
    """The VIOLATION loop's own resume-on-denial line. The geometry loop's
    cursor was pinned; this one has its own, and nothing drove it: a denied
    match that does not advance the cursor is re-found in the NEXT window and
    denied a SECOND time, so the same statement is refused twice.

    That was invisible while a refusal was thrown away. It is observable now
    that `polarity_refused` counts them, which is the other half of what the
    disclosure buys: with the advance removed this corpus diverges from the
    whole-file reference in 15 configurations."""
    assert _streamed(text, block, overlap)[2] == dvp._classify_one(text)


def test_a_refused_count_is_never_reported_as_an_absent_one(tmp_path):
    """The disclosure, end-to-end through `audit`. The residual above is
    acceptable only while the report SAYS what happened; the message it used to
    print — "No parseable violation verdict" — is false about a report that
    printed `13 DRC errors found`."""
    d = tmp_path / "p" / "reports"
    d.mkdir(parents=True)
    (d / "drc.rpt").write_text("13 DRC errors found - none waived\n")
    res = dvp.audit(tmp_path / "p")
    msgs = " ".join(f.message for f in res.findings)
    assert "No parseable violation verdict" not in msgs, (
        "the verdict claims the report printed no count; it printed 13")
    assert "polarity" in msgs and "REFUSED" in msgs
    assert res.summary["per_file"][0]["polarity_refused"] >= 1


@pytest.mark.parametrize("text,geom,nonzero", [
    (_DIFF_LINE_CLEAN, [4211.0], None),
    (_DIFF_LINE_NONZERO, [], 13),
])
def test_the_same_facts_on_separate_lines_are_unchanged(text, geom, nonzero):
    """REGRESSION GUARD for the shape the shipped tests were all written in:
    the record clamp already handled it, and none of the above may disturb
    it."""
    c = _all_paths(text)
    assert c["reported_geometry_counts"] == geom
    assert c["nonzero_count"] == nonzero


@pytest.mark.parametrize("text,why", [
    ("The 4211 shapes reported by the previous run are not present here.\n",
     "same field, denial after the number (#712's measured geometry case)"),
    ("The 13 violations listed above are no longer applicable.\n",
     "same field, denial after the number (#712's measured violation case)"),
    ("not applicable, 4211 shapes\n",
     "an EARLIER assertion — kept denied, the conservative direction"),
])
def test_a_denial_that_does_govern_the_number_still_retracts_it(text, why):
    """OVER-BREADTH GUARD, and the pin on the ASYMMETRY. Narrowing the forward
    reach to the field must not turn the consult off: both denials it exists
    for sit in the same field as their number, and a denial in an earlier field
    is still honoured because for a gate that exists to refuse an unearned
    clean, keeping it costs nothing."""
    c = _all_paths(text)
    assert c["reported_geometry_counts"] == [], why
    assert c["nonzero_count"] is None, why


@pytest.mark.parametrize("text,where", [
    # These four carry the clamps on their own: their denial is NOT a clean
    # verdict, so the blanking above cannot be what saves them and removing
    # either clamp turns them red.
    ("not applicable\ncells: 87\n", "the PREVIOUS line (non-verdict denial)"),
    ("cells: 87\nnot applicable\n", "the NEXT line (non-verdict denial)"),
    ("no longer applicable\nfoo\n4211 shapes\n", "two lines above"),
    ("4211 shapes\nfoo\nnot applicable\n", "two lines below"),
    ("no drc violations found\ncells: 87\n", "the PREVIOUS line"),
    ("cells: 87\nno drc violations found\n", "the NEXT line"),
    ("cells: 87\nfoo\nno drc errors found\n", "two lines below"),
    ("checked 4211 shapes. not applicable\n", "after a sentence break"),
    ("not applicable. checked 4211 shapes\n", "before a sentence break"),
    ("checked 4211 shapes; not applicable\n", "after a semicolon"),
    ("not applicable; checked 4211 shapes\n", "before a semicolon"),
])
def test_a_denial_outside_the_record_never_reaches_this_number(text, where):
    """BOTH `_record_span` clamps, driven — neither had a test, so removing
    either changed no answer. A DRC report's consecutive lines are unrelated
    records; a denial in one must not retract another's number, in EITHER
    direction."""
    c = _all_paths(text)
    assert c["reported_geometry_counts"], \
        f"a denial on {where} retracted this record's count"


@pytest.mark.parametrize("overlap", [8, 32, 64, 119, 128, 256, 4096])
@pytest.mark.parametrize("block", [1, 7, 64, 512])
def test_the_window_retains_the_context_the_consult_reads(block, overlap):
    """The consult judges a SPAN, so the window has to hold that span or the
    streaming answer stops being the whole-file answer. Two terms carry it and
    neither had a driver: the right margin covers `_POLARITY_AFTER` beyond the
    overlap, and the retained tail keeps `_POLARITY_BEFORE` before the earliest
    live cursor.

    Both are invisible at production sizes — the 256 KiB overlap dwarfs a
    240-character reach, so `max(overlap, _POLARITY_AFTER)` is `overlap` and
    the extra lookback is lost in the noise. They only bite where the window is
    smaller than the reach, which is exactly where a test can see them: with
    the reach terms removed this corpus diverges from the whole-file reference
    in 27 and 18 configurations respectively."""
    for maker in (lambda d: "not applicable " + ("x" * d) + " 4211 shapes\n",
                  lambda d: "4211 shapes " + ("x" * d) + " not applicable\n"):
        for dist in (0, 30, 80, 100, 110, 150, 200, 230):
            text = maker(dist)
            assert _streamed(text, block, overlap)[2] \
                == dvp._classify_one(text), \
                f"block={block} overlap={overlap} dist={dist} text={text!r}"


def test_the_record_span_only_ever_narrows_the_helpers_window():
    """`_record_span` no longer clamps anything itself — it passes
    `_RECORD_STOPS` to `sentence_scope` as `extra_breaks`, which the helper
    applies with its OWN symmetric rule (070aea3e8, v1.9.78). What has to stay
    true of the result is what a denial span means: it contains the match, and
    adding record breaks can only NARROW the plain sentence window, never widen
    it past a sentence break.

    Proven on every match of every count pattern in a corpus that mixes both
    scope shapes."""
    corpus = [_FAMILY_A.format(sep=", "), _FAMILY_B.format(sep=", "),
              _DIFF_LINE_CLEAN, _DIFF_LINE_NONZERO,
              "a. b; c, d no e. f 9 cells\n" * 20,
              "not applicable, 4211 shapes; 13 errors. no drc issues found\n",
              ("x" * 300) + " no " + ("y" * 300) + " 87 cells " + ("z" * 300)]
    checked = 0
    for text in corpus:
        for r in list(dvp._REPORTED_COUNT_RE) + list(dvp._NONZERO_COUNT_RE):
            for m in r.finditer(text):
                w_lo, w_hi = dvp._sentence_scope(
                    text, m.start(), m.end(),
                    before=dvp._POLARITY_BEFORE, after=dvp._POLARITY_AFTER)
                lo, hi = dvp._record_span(text, m)
                # It CONTAINS the match, at both ends...
                assert lo <= m.start() and hi >= m.end(), (lo, hi, m.span())
                # ...and it is INSIDE the plain sentence window, because the
                # record stops can only ADD breaks, never remove one.
                assert w_lo <= lo <= m.start(), (lo, w_lo, m.start())
                assert m.end() <= hi <= w_hi, (hi, w_hi, m.end())
                checked += 1
    assert checked >= 10, f"corpus drove only {checked} spans"


# ---------------------------------------------------------------------------
# Property 6 — the trim's HARD cut may land mid-token, and the scan must know.
#
# `_safe_cut_point`'s fallback (3) is RATIONED, not removed: once the
# reclaimable prefix is itself a `_SAFE_CUT_SCAN`-long unbroken `[\w.-]` run it
# cuts inside the token anyway, because the memory bound has to hold with no
# "unless". The comment claimed the rationing was the FIX for the mid-token
# hazard. It is not, and it was MEASURED not being it: at the rationed cut
# (>= 64 KiB run, cut=65547) the next window still opened on `top.gds` and
# still harvested a citation out of `xtop.gds`, which the whole file does not
# contain.
#
# What fixes it is the CALLER: `_scan_chunks` notices the cut split a token and
# starts the next window's scans at index 1, so every regex reads `buf[0]` —
# the REAL preceding character — exactly as it does whole-file. Precisely one
# index is skipped, and it is the only one whose left context the file never
# had.
# ---------------------------------------------------------------------------
def test_the_rationed_hard_cut_still_lands_mid_token():
    """The hazard is REAL and rationing does not remove it. Fixture at real
    scale, so no constant is being assumed away."""
    buf = ("z" * (dvp._SAFE_CUT_SCAN + 4465)) + "xtop.gds rest"
    keep_from = buf.index("xtop.gds") + 1          # inside "xtop"
    assert "\n" not in buf and " " not in buf[:keep_from]
    assert keep_from >= dvp._SAFE_CUT_SCAN, "fixture must reach the ration"
    cut = dvp._safe_cut_point(buf, keep_from)
    assert dvp._cut_is_mid_token(buf, cut), \
        "fixture no longer reaches the mid-token cut it is here to cover"
    nxt = buf[cut:]
    r = dvp._cite_matcher("top.gds")
    assert r.search(buf) is None, "the whole file does not cite top.gds"
    assert r.search(nxt, 0) is not None, \
        "fixture invalid: index 0 must be where the false citation appears"
    assert r.search(nxt, 1) is None, \
        ("starting at index 1 must restore the whole-file answer — the "
         "look-behind then reads the REAL preceding character")


def test_the_ration_declines_only_the_hard_cut_never_an_honest_one():
    """All three cut points, driven, plus the ration's exact scope.

    The ration used to sit ABOVE the boundary search, so a short buffer skipped
    cut point (2) as well: the middle case here has a perfectly good boundary
    and was returning 0, retaining the buffer to avoid a cut it never had to
    make. The docstring said the ration declined branch (3)."""
    # (1) after a newline, always, whatever else is true — and this is not a
    # cosmetic preference. The tier-2 search is BOUNDED to `_SAFE_CUT_SCAN`
    # back from `keep_from`, so on a buffer whose last 64 KiB is one unbroken
    # token, tier 2 can see no boundary at all and hard-cuts mid-token, while
    # tier 1 finds the newline sitting just before that run.
    assert dvp._safe_cut_point("abc\ndef", 6) == 4
    long_run = "a\n" + "b" * (dvp._SAFE_CUT_SCAN + 100)
    cut1 = dvp._safe_cut_point(long_run, dvp._SAFE_CUT_SCAN + 50)
    assert cut1 == 2, f"the newline at index 1 was not preferred (cut={cut1})"
    assert dvp._cut_is_mid_token(long_run, cut1) is False
    # (2) after any other non-`[\w.-]` character — including on a SHORT buffer
    assert dvp._safe_cut_point("a" * 100 + " " + "b" * 400, 500) == 101
    # ...the ration must not decline this one
    assert dvp._safe_cut_point("a" * 100 + " " + "b" * 400, 500) != 0
    # (2) again — the boundary sitting EXACTLY at the search's left edge. The
    # bounded search cannot see past `lo`, so a run that reaches it looks
    # identical to one that started earlier; `cut > lo` alone read that as "no
    # boundary" and hard-cut mid-token instead of taking the honest cut here.
    scan = dvp._SAFE_CUT_SCAN
    edge = "a" * 50 + " " + "b" * (scan + 100)
    assert dvp._safe_cut_point(edge, 51 + scan) == 51
    assert dvp._cut_is_mid_token(edge, dvp._safe_cut_point(edge, 51 + scan)) \
        is False
    # (3) nothing but token characters. Below the ration — which IS the
    # `lo == 0` arm, since `lo` is `keep_from - _SAFE_CUT_SCAN` clamped at 0 —
    # there is nothing to reclaim, so no trim at all...
    assert dvp._safe_cut_point("a" * 1000, 500) == 0
    # ...at or above it, take the hard cut rather than grow without bound
    big = "a" * (dvp._SAFE_CUT_SCAN + 500)
    assert dvp._safe_cut_point(big, dvp._SAFE_CUT_SCAN + 10) == \
        dvp._SAFE_CUT_SCAN + 10


@pytest.mark.parametrize("body,cited,why", [
    ("drc on top.gds done", True, "a bare citation"),
    ("drc on /a/b/top.gds done", True, "a path ending in the name"),
    ("drc on xtop.gds done", False, "the look-BEHIND: a longer name"),
    ("drc on my-top.gds done", False, "the look-behind rejects `-` too"),
    ("drc on top.gdsx done", False, "the look-AHEAD: a longer extension"),
    ("drc on top.gds-old done", False, "the look-ahead rejects `-` too"),
])
def test_a_citation_is_the_whole_filename_and_not_a_substring_of_one(
        body, cited, why):
    """`_cite_matcher` decides WHICH layout the gate measures, so a substring
    hit binds the verdict to an artifact the run never touched. Both
    assertions in the pattern carry that — dropping either was unpinned, and
    the mid-token defect above is exactly what a missing look-behind looks
    like from the inside."""
    got = dvp._cite_matcher("top.gds").search(body) is not None
    assert got is cited, why


def test_a_cut_at_a_real_boundary_is_not_reported_as_mid_token():
    """`_cut_is_mid_token` decides whether the next window loses index 0, so
    over-reporting costs a real match. It is a property of BOTH characters
    around the cut: a cut whose left neighbour is a boundary is not mid-token,
    however word-like the character after it looks."""
    assert dvp._cut_is_mid_token("abcdef", 3) is True
    assert dvp._cut_is_mid_token("abc def", 4) is False    # left is a space
    assert dvp._cut_is_mid_token("abc\ndef", 4) is False    # left is a newline
    assert dvp._cut_is_mid_token("abc ", 4) is False        # nothing after
    assert dvp._cut_is_mid_token("abcdef", 0) is False      # start of buffer
    assert dvp._cut_is_mid_token("ab.cd", 3) is True        # `.` is a token char
    assert dvp._cut_is_mid_token("ab-cd", 3) is True        # so is `-`


def test_a_mid_token_cut_never_invents_a_citation(monkeypatch):
    """END-TO-END through the real scanner. `_SAFE_CUT_SCAN` is shrunk so the
    ration is reachable in a kilobyte instead of 64 of them — the constant is
    the RATION, not the mechanism — and the token is swept across every offset
    so it lands on the cut. Sweeping is what makes the fixture robust: the cut
    position is arithmetic on block/overlap, not something to hard-code.

    Against the unguarded scan (`search(buf, 0)`) this fixture harvests
    `top.gds` from `xtop.gds` at three of the swept offsets."""
    monkeypatch.setattr(dvp, "_SAFE_CUT_SCAN", 64)
    cands = [Path("/x/top.gds")]
    mid_token_cuts = 0
    real_cut = dvp._safe_cut_point

    def spy(buf, keep_from):
        nonlocal mid_token_cuts
        c = real_cut(buf, keep_from)
        if dvp._cut_is_mid_token(buf, c):
            mid_token_cuts += 1
        return c

    monkeypatch.setattr(dvp, "_safe_cut_point", spy)
    for run in range(60, 1300):
        text = ("z" * run) + "xtop.gds|" + ("q" * 900)
        assert dvp._cite_matcher("top.gds").search(text) is None
        _ne, _d, _c, cited = dvp._scan_chunks(
            io.StringIO(text).read, cands, block=512, overlap=64)
        assert not cited, (
            f"run={run}: the scanner cited {sorted(cited)} — a filename the "
            f"report does not contain, harvested out of the token the trim "
            f"cut in half")
    assert mid_token_cuts > 0, \
        "fixture never reached a mid-token cut; it proves nothing"


# ---------------------------------------------------------------------------
# Property 7 — INCREMENTAL DECODE == WHOLE-FILE DECODE.
#
# Every equivalence claim above is stated over a decoded STRING. The program
# reaches that string a different way now: `Path.read_text(errors='replace')`
# decoded the whole byte sequence at once, `_scan_report_file` decodes it
# incrementally through repeated `read(n)`. If those disagree — a multi-byte
# sequence split across a read boundary replaced instead of buffered, a BOM
# re-emitted, a NUL treated differently — every regex downstream sees a
# different string and the equivalence is void before any pattern runs.
# ---------------------------------------------------------------------------
_DECODE_CASES = [
    b"DRC report\n0 errors\n4211 shapes\n",
    b"\xef\xbb\xbfBOM first: cells: 87\n0 errors\n",           # UTF-8 BOM
    b"bad \xff\xfe bytes, 0 errors, 12 polygons\n",            # invalid UTF-8
    b"nul\x00inside\x000 errors\n5 shapes\n",                  # NUL
    b"multi\xe4\xb8\xad\xe6\x96\x87 0 errors 7 cells\n",       # CJK
    b"\xe4\xb8" + b"a" * 3 + b"\x80 0 errors\n",               # truncated seq
    "无 drc found\n0 errors\n8 shapes\n".encode(),
    b"x" * 10 + b"\xc3",                                       # trailing partial
    b"",
    (b"\xff" * 37) + b"0 errors\n" + (b"\xfe" * 41),
]


@pytest.mark.parametrize("raw", _DECODE_CASES,
                         ids=[str(i) for i in range(len(_DECODE_CASES))])
@pytest.mark.parametrize("block", [1, 2, 3, 5, 7, 8, 13, 64, 4096])
def test_incremental_decode_equals_whole_file_decode(tmp_path, raw, block):
    fp = tmp_path / "drc.rpt"
    fp.write_bytes(raw)
    whole = fp.read_text(errors="replace")
    with open(fp, "r", errors="replace") as fh:
        parts = []
        while True:
            c = fh.read(block)
            if c == "":
                break
            parts.append(c)
    assert "".join(parts) == whole, (
        f"block={block}: the incremental decode differs from the whole-file "
        f"decode, so every regex below reads a different string")
    # ...and the facts derived from the FILE match the whole-file reference,
    # through the real entry point, with the same errors='replace' handling.
    ref = (bool(whole.strip()), dvp._is_drc_log(whole), dvp._classify_one(whole))
    with open(fp, "r", errors="replace") as fh:
        got = dvp._scan_chunks(fh.read, (), block=block, overlap=4096)[:3]
    assert got == ref
    assert dvp._scan_report_file(fp)[:3] == ref
