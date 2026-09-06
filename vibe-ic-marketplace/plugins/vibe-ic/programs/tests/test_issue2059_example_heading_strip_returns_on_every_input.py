#!/usr/bin/env python3
"""#2059 — `spec_enumset_extract._strip_example_sections` must RETURN on every
finite input. A deterministic non-return is a defect in the extractor, never a
timeout and never a size cap.

THE MECHANISM, as measured on the unmodified tree (8hd-3, 2026-09-06). The
example-heading recogniser used to be one pattern::

    ^\\s*(?:#{1,6}\\s*|\\*\\*\\s*|\\d+\\.\\s*)*(?:example|scenario|...)\\b

whose quantified group carries a quantified FIRST alternative. A run of N ``#``
can be cut into runs of 1..6 in ``a(N) = a(N-1)+...+a(N-6)`` ways (hexanacci), and
when the keyword does NOT follow, the engine must enumerate every cut before it
may report failure. Measured wall clock on that pattern against ``'#' * N``:

    N=16 0.0070 s   N=20 0.108 s   N=24 1.75 s   N=28 27.3 s

a ratio of 1.98 per added ``#``, against the predicted a(N) ratio of 1.984 — they
agree to three digits. A real corpus INPUT document
(``evaluation/phase1_parity/ufs/input/docs/ufs_spec.txt``, 57 803 bytes) opens
its parts with a banner rule of exactly EIGHTY ``#``; a(80) = 3.26e23, i.e.
~8e16 seconds. That is the "hang": not a slow machine, a decidable amount of work
that finishes after the heat death of nothing in particular.

The fix consumes the heading decoration with a LINE SCANNER
(``_is_example_heading``), one greedy step at a time, never reconsidered. These
tests assert (1) the scan is LINEAR, by an OPERATION COUNT — not by a clock;
(2) the recogniser carries no ambiguous nested quantifier, so the shape cannot
come back; (3) acceptance is unchanged; (4) the document that never returned
returns. Wall clock appears once, as a stated upper SANITY bound on a fixture
that previously never returned — never as the assertion's subject.

chip-AGNOSTIC: pure markdown heading grammar, no design/PDK/vendor literal.
"""
import os
import re
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import spec_enumset_extract as SE  # noqa: E402
from _corpus_guard import corpus_root, require_corpus  # noqa: E402

# The banner rule the real input document carries. Eighty '#' and nothing else.
BANNER = "#" * 80

#: The path, inside the corpus, of the document `check()` did not return on.
UFS_DOC = "evaluation/phase1_parity/ufs/input/docs/ufs_spec.txt"

#: Wall-clock SANITY ceiling, in seconds. It is not what any test asserts about
#: the cost — the operation-count test below is. It exists so a reintroduced
#: catastrophic pattern ends the run instead of hanging the suite forever.
SANITY_CEILING_S = 60.0


class _CountingPattern:
    """A wrapper that COUNTS how many times the scanner consults its step
    pattern. This is the operation budget: the old shape's cost was invisible
    (one `.match` call that never returned), the new shape's cost is exactly the
    number of steps, and a step always advances by at least one character."""

    def __init__(self, pattern):
        self._pattern = pattern
        self.calls = 0

    def match(self, *args, **kwargs):
        self.calls += 1
        return self._pattern.match(*args, **kwargs)


def _count_steps(monkeypatch, line):
    counter = _CountingPattern(SE._HEADING_PREFIX_STEP_RE)
    monkeypatch.setattr(SE, "_HEADING_PREFIX_STEP_RE", counter)
    SE._is_example_heading(line)
    return counter.calls


# ---------------------------------------------------------------------------
# 1. the operation budget — the assertion is about the STEP COUNT, not a clock
# ---------------------------------------------------------------------------
def test_the_heading_prefix_scan_costs_at_most_one_step_per_character(monkeypatch):
    """Linear, by count. The old shape needed a(N) attempts; this needs <= N."""
    for n in (1, 6, 7, 16, 28, 80, 400):
        line = "#" * n + "\n"
        steps = _count_steps(monkeypatch, line)
        assert steps <= len(line), (
            f"{n} '#' took {steps} prefix steps for a {len(line)}-character line; "
            f"a step must consume at least one character")


def test_the_step_count_grows_linearly_not_exponentially(monkeypatch):
    """Doubling the run doubles the work — it does not square it. Under the old
    pattern the same doubling multiplied the work by a(2N)/a(N) ~ 1.98**N."""
    small = _count_steps(monkeypatch, "#" * 40 + "\n")
    large = _count_steps(monkeypatch, "#" * 80 + "\n")
    assert small >= 2, "the fixture must actually exercise several steps"
    assert large <= 3 * small, (
        f"40 '#' -> {small} steps but 80 '#' -> {large}; that is not linear")


# ---------------------------------------------------------------------------
# 2. the shape cannot come back — a quantified group with a quantified member
# ---------------------------------------------------------------------------
def _quantified_group_sources(pattern_source):
    """Yield the body of every group in `pattern_source` that is itself
    quantified by `*`, `+` or an open-ended `{n,}`. Nesting-aware."""
    out = []
    i, n = 0, len(pattern_source)
    while i < n:
        ch = pattern_source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "(":
            depth, j = 1, i + 1
            while j < n and depth:
                if pattern_source[j] == "\\":
                    j += 2
                    continue
                if pattern_source[j] == "(":
                    depth += 1
                elif pattern_source[j] == ")":
                    depth -= 1
                j += 1
            body, after = pattern_source[i + 1:j - 1], pattern_source[j:j + 1]
            if after in ("*", "+") or re.match(r"\{\d*,\}", pattern_source[j:]):
                out.append(body)
            i += 1
            continue
        i += 1
    return out


_QUANTIFIER_INSIDE = re.compile(r"(?<!\\)[*+]|(?<!\\)\{\d+(,\d*)?\}")


def test_the_example_heading_recogniser_has_no_ambiguous_nested_quantifier():
    """The regression guard. A quantified group whose body is itself quantified
    is the exact shape that made a finite input undecidable in practice."""
    for name in ("_HEADING_PREFIX_STEP_RE", "_EXAMPLE_KEYWORD_RE",
                 "_LEADING_WS_RE"):
        pattern = getattr(SE, name)
        for body in _quantified_group_sources(pattern.pattern):
            assert not _QUANTIFIER_INSIDE.search(body), (
                f"{name} has a quantified group whose body is quantified "
                f"({body!r}); that is the #2059 shape")


def test_the_detector_itself_fires_on_the_pattern_that_was_removed():
    """A check that cannot fail is not a check: the SAME detector, given the
    pattern this fix removed, must report it."""
    removed = r"^\s*(?:#{1,6}\s*|\*\*\s*|\d+\.\s*)*(?:example|sample)\b"
    bodies = _quantified_group_sources(removed)
    assert bodies, "the detector saw no quantified group in the removed pattern"
    assert any(_QUANTIFIER_INSIDE.search(b) for b in bodies), (
        "the detector did not flag the pattern it exists to flag")


# ---------------------------------------------------------------------------
# 2b. the budget the removed pattern blows, asserted on a BOUNDED ladder
# ---------------------------------------------------------------------------
#: The pattern this fix removed, verbatim, so the control can measure the thing it
#: is a control for. It is a LITERAL here and nothing imports it.
REMOVED_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*\s*|\d+\.\s*)*"
    r"(?:example|scenario|test\s*case|test\s*inputs|sample)\b", re.I)

#: Ladder ends. Chosen so the REMOVED pattern still RETURNS at both — measured
#: 0.007 s and 0.108 s — because a control that has to be killed is not a control.
LADDER_SMALL, LADDER_BIG = 16, 20

#: Linear would put the ratio at 20/16 = 1.25; the hexanacci model puts it at
#: 1.984**4 = 15.5. Four is far from both, so the assertion survives a loaded host.
EXPONENTIAL_RATIO = 4.0


def _fastest(fn, repeats=3):
    """Best of N. The scheduler can only make a measurement look SLOWER, so the
    minimum is the least noisy estimate of the work actually done."""
    best = None
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
    return best


def test_the_removed_pattern_blows_a_bounded_budget_on_the_same_input():
    """The re-hang, asserted rather than waited for.

    Restoring the removed pattern makes the banner fixture never return, but
    "never" is not something a test may sit and confirm. So measure it on a ladder
    short enough to finish and assert the GROWTH: the cost multiplies by ~2 per
    added '#', which is what makes a(80) = 3.26e23 and the 80-'#' fixture
    unreachable. Nothing here touches the module — this is the control's own
    subject."""
    small = _fastest(lambda: REMOVED_PATTERN.match("#" * LADDER_SMALL + "\n"))
    big = _fastest(lambda: REMOVED_PATTERN.match("#" * LADDER_BIG + "\n"))
    assert small > 0, "the ladder's small end measured no work at all"
    assert big / small > EXPONENTIAL_RATIO, (
        f"{LADDER_SMALL} -> {LADDER_BIG} '#' cost {small:.6f}s -> {big:.6f}s "
        f"(ratio {big / small:.1f}); the removed pattern is supposed to be "
        f"exponential in the run length and this control cannot see it")


def test_the_shipped_scanner_stays_inside_the_budget_on_that_same_ladder(monkeypatch):
    """The other direction, by operation COUNT and no clock at all: over the same
    two inputs the shipped scanner's step count grows linearly."""
    small = _count_steps(monkeypatch, "#" * LADDER_SMALL + "\n")
    big = _count_steps(monkeypatch, "#" * LADDER_BIG + "\n")
    assert small >= 2, "the ladder's small end exercises no steps"
    assert big <= 2 * small, (
        f"{LADDER_SMALL} -> {LADDER_BIG} '#' took {small} -> {big} prefix steps; "
        f"that is not linear")
    assert big <= LADDER_BIG + 2, (
        f"{big} steps for a {LADDER_BIG}-character run exceeds one step per "
        f"character")


# ---------------------------------------------------------------------------
# 3. acceptance is unchanged — the scanner takes exactly what the group took
# ---------------------------------------------------------------------------
ACCEPTED = [
    "Example",
    "example: two modes\n",
    "  Sample values\n",
    "# Example\n",
    "### Example of the encoding\n",
    "**Example**\n",
    "** Scenario 2\n",
    "1. Example\n",
    "## 3. Test case 4\n",
    "#1. sample\n",
    "###   **  2. test  inputs\n",
    "\t#### Scenario\n",
    "######## Example\n",          # 8 '#': two scanner steps, still a heading
]

REJECTED = [
    "",
    "\n",
    BANNER + "\n",
    BANNER,
    "#" * 400 + "\n",
    "# Interface\n",
    "Examples of the register map\n",   # 'Examples' — \b after 'example' fails
    "exampled\n",
    "*Example*\n",                      # one '*' is not a heading decoration
    "1 Example\n",                      # no '.' after the number
    "the example below\n",              # not at the start of the line
    "| Example | value |\n",
    "-- Example\n",
]


@pytest.mark.parametrize("line", ACCEPTED)
def test_the_scanner_accepts_the_documented_heading_forms(line):
    assert SE._is_example_heading(line) is True, repr(line)


@pytest.mark.parametrize("line", REJECTED)
def test_the_scanner_rejects_what_is_not_an_example_heading(line):
    assert SE._is_example_heading(line) is False, repr(line)


# ---------------------------------------------------------------------------
# 4. the strip still does its job, and it does it on a document with a banner
# ---------------------------------------------------------------------------
DOC_WITH_BANNER = (
    BANNER + "\n"
    "# PART 1 - the encoding\n"
    "\n"
    "| MODE | meaning |\n"
    "|---|---|\n"
    "| 2'b00 | idle |\n"
    "| 2'b01 | run |\n"
    "| 2'b10 | halt |\n"
    "\n"
    + BANNER + "\n"
    "## Example\n"
    "- mode = 2'b11 drives the error output\n"
    "\n"
    "## Encoding notes\n"
    "- the map above is complete\n"
)


def test_a_banner_rule_does_not_stop_the_example_section_strip():
    """The whole point: this input previously never came back."""
    started = time.monotonic()
    stripped = SE._strip_example_sections(DOC_WITH_BANNER)
    elapsed = time.monotonic() - started
    # SANITY bound only — the cost assertion is the operation count above.
    assert elapsed < SANITY_CEILING_S, f"took {elapsed:.1f}s"
    assert stripped.count("\n") == DOC_WITH_BANNER.count("\n"), (
        "lines are blanked, not removed, so line counts are preserved")
    assert "2'b11" not in stripped, "the example section was not blanked"
    assert "2'b01" in stripped, "the definition table was blanked by mistake"
    assert "the map above is complete" in stripped, (
        "the example section did not end at the next same-level heading")


def test_a_document_with_no_example_heading_is_returned_unchanged():
    """The invariant the banner case is really about. `_strip_example_sections` blanks
    example sections and touches nothing else, so a document that opens no example
    section must come back BYTE-IDENTICAL. Measured over this repo's corpus: 8993 of
    9028 documents carry no example heading, and on every one of them the strip is the
    identity — which is what makes the old pattern's 3.26e23 steps so expensive for so
    little: they were spent deciding that a row of hashes is not the word "example",
    and then returning the input unchanged."""
    for text in (BANNER + "\n",
                 BANNER + "\n# PART 1\n\n| MODE | m |\n| 2'b00 | idle |\n",
                 "#" * 400 + "\n\nplain prose\n",
                 "## Interface\n- clk is the clock\n",
                 ""):
        assert not any(SE._is_example_heading(line)
                       for line in text.splitlines(keepends=True)), (
            "fixture error: this text was supposed to carry no example heading")
        assert SE._strip_example_sections(text) == text, repr(text[:60])


def test_extract_returns_on_a_document_carrying_a_banner_rule():
    """Through the public entry point, which is what `check()` reaches."""
    started = time.monotonic()
    items = SE.extract(DOC_WITH_BANNER)
    assert time.monotonic() - started < SANITY_CEILING_S
    codes = [it["coverage_tokens"][0] for it in items
             if it["kind"] == "enum_set"]
    assert codes == ["2'b00", "2'b01", "2'b10"], codes
    assert "2'b11" not in codes, (
        "the example section's stimulus value was minted as a map member")


# ---------------------------------------------------------------------------
# 5. the real document — named, so a skip says what went unmeasured
# ---------------------------------------------------------------------------
def _ufs_document():
    """The real document, wherever this run's corpus is bound.

    `corpus_root` resolves the `ic` cell root (or whatever `$VIBE_IC_BENCHMARK_DATA`
    names); the parity documents sit beside it, so both the pointer itself and its
    parent are candidates. Every candidate that was looked at is named in the skip
    reason — "could not read it" must never read as "read it and it was fine"."""
    programs = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bound = corpus_root(programs)
    tried = [bound / UFS_DOC, bound.parent / UFS_DOC]
    for candidate in tried:
        if candidate.is_file():
            return candidate
    require_corpus(bound, f"#2059 non-return on {UFS_DOC}")
    pytest.skip("corpus is present but does not carry "
                + UFS_DOC + "; looked at " + ", ".join(str(t) for t in tried))


def test_the_real_input_document_that_never_returned_now_returns():
    doc = _ufs_document()
    text = doc.read_text(encoding="utf-8", errors="replace")
    started = time.monotonic()
    stripped = SE._strip_example_sections(text)
    assert time.monotonic() - started < SANITY_CEILING_S
    assert stripped.count("\n") == text.count("\n")
    assert BANNER in stripped, "the banner rule is not an example heading"
    # The real assertion, not just "it came back": this document opens no example
    # section, so the strip must be the IDENTITY on it. Checking only that the banner
    # survived would still pass if half the document had been blanked.
    if not any(SE._is_example_heading(line)
               for line in text.splitlines(keepends=True)):
        assert stripped == text, (
            "the document carries no example heading, so the strip must return it "
            "unchanged; it did not")
