#!/usr/bin/env python3
"""#2060 item 3 (from lane czhang's #2059 measurement) — `_RE_BULLET_ONLY` did
not return, and the answer is a linear scanner, not a timeout and not a cap.

    (?m)\\A(?:\\s*(?:[-*+]\\s+[^\\n]*)?\\n?)+\\Z

The outer `+` quantifies a body that can match the EMPTY string, and `\\s*`
(which spans newlines) competes with `\\n?` for every line separator, so on a
block that FAILS the engine enumerates every way to split the text between
them. MEASURED on 8HD-6, before any edit, over
`"- item i with some ordinary text" * n + "\\n---"` — an ordinary nested bullet
list closed by a horizontal rule, which is the shape of block 4 of a real
corpus input prompt:

    indent 0:   4 lines 0.5 ms  ->  11 lines 8458 ms   (x4.0 per added line)
    indent 2:   4 lines 107 ms  ->   6 lines 27234 ms  (x16.0 per added line)
    indent 4:   4 lines 26267 ms

A 21-line nested list never returns, and NOTHING LOOKS EXPENSIVE: the same text
WITHOUT the closing `---` matches instantly on the first greedy path.
`emit_interface_prose` runs this over blocks of a document its caller hands it,
so it is a hang in the Phase-1 front door.

TWO PLACES THE OLD LANGUAGE WAS ALSO WRONG, both found by sweeping rather than
by reading, and both of which made the call site DROP a block (a bullet-only
block is skipped as "the port table, which L9 already holds structurally"):

  (a) `\\s+` after the marker could match the LINE SEPARATOR, so a bare `-`
      alone on a line swallowed the NEXT line as its own text. Absent from all
      4787 real design-input documents — measured, 0 blocks.
  (b) the same `\\s+` let an EMPHASIS marker at the end of a bullet line
      swallow the following prose line: on the real corpus document
      cvdp_copilot_dot_product_0012, the block
      `- **Multi-Driven Signals**  \\nIdentify and resolve any signals ...`
      read as bullet-only and its second line — a design requirement — was
      dropped from L9's prose channel. The linear scanner keeps it.

So the rewrite is not byte-identical, and this file says exactly where it is
not, rather than leaving it to be found later.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_port_extract as PPX  # noqa: E402

#: The exact expression this item removes. Kept HERE, in the test, so the
#: mutation is the real thing and the tree carries no reachable copy of it.
PRE_2060 = re.compile(r"(?m)\A(?:\s*(?:[-*+]\s+[^\n]*)?\n?)+\Z")


def _nested_list(n, indent=0, closed=True):
    pad = " " * indent
    body = "\n".join(f"{pad}- item {i} with some ordinary text" for i in range(n))
    return body + ("\n---" if closed else "")


class _CountingPattern:
    """A proxy that answers exactly as the real line pattern does and counts
    how many times it was applied. A number, not a duration."""

    def __init__(self, real):
        self._real = real
        self.calls = 0

    def match(self, s):
        self.calls += 1
        return self._real.match(s)


def _steps(text):
    real = PPX._RE_BULLET_LINE
    proxy = _CountingPattern(real)
    PPX._RE_BULLET_LINE = proxy
    try:
        verdict = PPX.is_bullet_only_block(text)
    finally:
        PPX._RE_BULLET_LINE = real
    return verdict, proxy.calls


# ── the block that did not return ─────────────────────────────────────

def test_the_real_shape_returns_and_is_not_bullet_only():
    """21 lines, nested, closed by `---`. On the old pattern this does not
    return at all; the number below is what "returns" means here."""
    block = _nested_list(21, indent=4)
    verdict, calls = _steps(block)
    assert verdict is False
    assert calls == 22, calls


def test_the_step_count_is_one_per_non_blank_line_and_indent_does_not_change_it():
    """STEP BUDGET, not a stopwatch. The old cost multiplied by ~4 per added
    line at indent 0, ~16 at indent 2 and reached 26 seconds at FOUR lines at
    indent 4 — indent was a cost multiplier because `\\s*` and the bullet's own
    `\\s+` compete for it. Here the count depends on the number of lines and on
    nothing else."""
    for indent in (0, 2, 4, 8):
        for n in (1, 5, 21, 200):
            verdict, calls = _steps(_nested_list(n, indent=indent))
            assert verdict is False
            assert calls == n + 1, (indent, n, calls)
    # blank lines are skipped without applying the pattern at all
    verdict, calls = _steps("- a\n\n\n- b\n")
    assert verdict is True and calls == 2, calls


def test_the_matching_prefix_is_still_bullet_only():
    """CONTROL. Removing the closing `---` is what made the old pattern
    instant, and it must still be the same answer: a pure bullet list IS the
    port table, and the call site skips it."""
    for indent in (0, 2, 4):
        assert PPX.is_bullet_only_block(_nested_list(21, indent, closed=False))
        assert PRE_2060.match(_nested_list(21, indent, closed=False))


def test_growth_is_flat_where_the_old_pattern_multiplies():
    """MUTATION, as a RATIO between two sizes measured on THIS host inside
    THIS test — never an absolute second-count, which would be a bound on how
    busy the machine is as much as on the code (the idiom
    `test_router_reads_rtl_embedded_in_the_prompt` establishes here).

    One added line multiplies the old pattern's cost; it must not multiply the
    new one's. Nine lines at indent 0 is ~0.5 s on the measured host and ten is
    ~2 s, which is enough to see the shape without making the suite slow."""
    small, big = _nested_list(9), _nested_list(10)

    def _best(fn, text, reps=3):
        return min(_timed(fn, text) for _ in range(reps))

    def _timed(fn, text):
        t0 = time.perf_counter()
        fn(text)
        return time.perf_counter() - t0

    new_ratio = (_best(PPX.is_bullet_only_block, big)
                 / max(_best(PPX.is_bullet_only_block, small), 1e-9))
    old_ratio = (_timed(PRE_2060.match, big)
                 / max(_timed(PRE_2060.match, small), 1e-9))
    assert old_ratio > 2.5, (
        f"the pre-#2060 pattern grew only {old_ratio:.1f}x for ONE added line — "
        f"the mutation is not reaching the defect, so this row proves nothing")
    assert new_ratio < 2.0, (
        f"the linear scanner grew {new_ratio:.1f}x for one added line "
        f"({old_ratio:.1f}x on the pre-#2060 pattern)")


# ── the language, and where it deliberately differs ───────────────────

_ALPHABET = ("- item", "* item", "+ item", "---", "prose line", "",
             " - indented", "  continued")


def test_the_two_languages_agree_on_every_block_over_a_line_alphabet():
    """EXHAUSTIVE, not representative: every block of up to three lines over
    the alphabet above — 585 cases. The bare marker is excluded here and
    pinned separately below, because it is the ONE shape where the answers
    differ by design."""
    import itertools
    checked = 0
    for n in range(0, 4):
        for combo in itertools.product(_ALPHABET, repeat=n):
            block = "\n".join(combo)
            checked += 1
            assert bool(PRE_2060.match(block)) is PPX.is_bullet_only_block(
                block), repr(block)
    assert checked == 585, checked


def test_the_divergences_are_exactly_the_two_measured_shapes():
    """Both are the old `\\s+` matching a LINE SEPARATOR, and in both the old
    answer DROPPED a line of the design's own prose. Stated, not discovered
    later."""
    swallows_next_line = "-\nIdentify and resolve any multi-driven signals."
    assert PRE_2060.match(swallows_next_line)
    assert PPX.is_bullet_only_block(swallows_next_line) is False

    real_corpus_block = ("- **Multi-Driven Signals**  \n"
                         "Identify and resolve any signals driven from "
                         "multiple sources, which can lead to unpredictable "
                         "behavior.")
    assert PRE_2060.match(real_corpus_block)
    assert PPX.is_bullet_only_block(real_corpus_block) is False


def test_a_horizontal_rule_and_a_bare_marker_are_not_bullet_lines():
    """`---` is why the real block FAILS, and failing is what used to be
    expensive. A marker must be followed by whitespace on its OWN line."""
    assert PPX.is_bullet_only_block("---") is False
    assert PPX.is_bullet_only_block("-") is False
    assert PPX.is_bullet_only_block("- ") is True
    assert PPX.is_bullet_only_block("- a\n---") is False
    assert PPX.is_bullet_only_block("") is True


def test_the_block_the_old_pattern_dropped_is_now_carried_into_l9():
    """END TO END at the emitter, on the real corpus block: the block names a
    declared port, so the anchored branch must KEEP it. Under the old pattern
    it read as bullet-only and was skipped."""
    content = {"ports": [{"name": "signals_bus"}, {"name": "data_in"}]}
    block = ("- **Multi-Driven Signals**  \n"
             "Identify and resolve any signals driven onto data_in from "
             "multiple sources, which can lead to unpredictable behavior.")
    padding = "\n\n".join("filler paragraph %d about data_in %s"
                          % (i, "x" * 200) for i in range(30))
    PPX.emit_interface_prose(content, {"design_description.md":
                                       block + "\n\n" + padding})
    joined = content.get("notes") or ""
    assert "Multi-Driven Signals" in joined, content.get(
        "interface_prose_provenance")
    # …and the SECOND line, the design requirement the old answer dropped
    assert "multiple sources" in joined


# ── the name the held file re-exports ─────────────────────────────────

def test_the_re_export_the_docs_door_uses_resolves_to_the_one_implementation():
    """`phase1_doc_one_shot_runner` does `_RE_CZL9_BULLET_ONLY =
    _ppx._RE_BULLET_ONLY`, and that file is held by another lane, so the NAME
    must keep resolving or the docs door does not import at all. It now names
    the predicate: one implementation, and the non-returning pattern is not
    kept alive behind it.

    ASSERTED AGAINST THE MODULE THE DOCS DOOR ITSELF IMPORTED, not against this
    file's own import. Measured in the pinned image: under the full selection
    the two spellings of this module's path load it TWICE, so
    `D._RE_CZL9_BULLET_ONLY is PPX.is_bullet_only_block` compared two distinct
    function objects of the same source and failed — a property of the test
    loader, not of the code. The property that matters is that the docs door's
    name resolves to ITS `_ppx`'s predicate and ANSWERS as one; that holds
    however many times the module is loaded."""
    assert PPX._RE_BULLET_ONLY is PPX.is_bullet_only_block
    import phase1_doc_one_shot_runner as D
    assert D._RE_CZL9_BULLET_ONLY is D._ppx.is_bullet_only_block
    assert D._RE_CZL9_BULLET_ONLY.__name__ == "is_bullet_only_block"
    # …and it is a PREDICATE, not a compiled pattern kept alive behind the name
    assert not hasattr(D._RE_CZL9_BULLET_ONLY, "match")
    assert D._RE_CZL9_BULLET_ONLY("- a\n- b") is True
    assert D._RE_CZL9_BULLET_ONLY("- a\n---") is False


def test_the_non_returning_pattern_is_gone_from_the_tree():
    """Not disabled, not guarded, not behind a flag — absent. A quoted copy in
    a comment or in this test file is evidence, not a reachable code path, so
    the check is on compiled patterns."""
    src = (PROGRAMS / "phase1_port_extract.py").read_text()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("#:"):
            continue
        assert r"[-*+]\s+[^\n]*" not in stripped, line
