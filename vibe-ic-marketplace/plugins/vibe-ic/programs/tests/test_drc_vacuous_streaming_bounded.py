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
    out = subprocess.run(
        [sys.executable, "-c", _RSS_WRAPPER, str(programs_dir), str(report_path)],
        capture_output=True, text=True, timeout=600)
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
