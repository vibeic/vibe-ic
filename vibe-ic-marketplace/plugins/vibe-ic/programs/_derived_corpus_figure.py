#!/usr/bin/env python3
"""A figure a checker states about its own corpus must be DERIVED, not typed.

A guard's docstring routinely argues for its own scope with numbers:

    "This clause alone takes 113 syntactic matches down to 13."
    "which is exactly the 2554-document L corpus"
    "the 531 programs still outside it are disclosed by the verdict line"

Every one of those is a measurement of the tree the program itself walks. The
program can compute it. Instead it is typed into prose, once, and then the tree
moves. Nothing recomputes it, nothing compares it, and no reader can tell a
figure that is still true from one that stopped being true eleven commits ago.

A figure a reader cannot reproduce is not evidence. It is not made evidence by
supporting a conclusion that happens to be correct.

THE THREE HONEST DISPOSITIONS OF A STATED FIGURE
------------------------------------------------
DERIVE   The figure describes the tree as it is NOW. It must be recomputed
         from the tree, never typed. There are two spellings, and which one
         is correct depends on WHO READS THE FILE:

         * ``{figure:NAME}`` -- a placeholder bound, in code, to a callable
           that recomputes it. The source then holds no number, so there is
           nothing to drift. Right for a docstring whose reader is holding
           the checker that can render it. (NAME is spelled in capitals
           throughout this docstring on purpose: a real placeholder is
           lower-snake, so no example here is itself a live claim.)

         * ``63<!--figure:NAME-->`` -- an ANCHORED figure: the number a
           reader sees, followed by an invisible anchor naming the same
           binding. Right for PUBLISHED prose -- a README on a git forge, a
           reference docstring people read as documentation -- where a
           placeholder nobody can render is a broken promise and a bare
           number is the defect this module exists to end. The anchor makes
           the digits a RENDERING: a generator rewrites them and a
           ``--check`` mode fails on drift, exactly as for a generated
           block, but without confining the figure to one marked region.

         Anchors exist because a marked-block generator only guards what is
         inside its markers. ``tools/gen_flow_matrix_census.py`` guarded a
         36-line block of a 501-line README and printed "census fresh" over
         five live-derived figures outside it, one of them invalidated by
         the very commit that gate's own message cites (vibe-ic#961).

PIN      The figure records a measurement taken THEN, to justify a decision
         made then. Keep the number, and attach the handle that lets a reader
         re-take it: a date, plus the literal command.

DISCLOSE Neither is possible — the quantity is not reachable from here. Say
         so, in the docstring, next to the number.

Nothing in this module decides WHICH disposition a figure deserves. That
decision needs to know whether the sentence is a claim about the corpus now or
a record of a measurement then, and both are spelled with the same tokens. See
``derived_corpus_figure_check`` for the boundary, stated as a boundary.

USING THE SEAM
--------------
An adopting module declares one module-global::

    CORPUS_FIGURES = CorpusFigures({
        "checker_shaped_population": lambda root: len(
            checker_population(root / "programs")),
    })

and writes ``{figure:CHECKER_SHAPED_POPULATION}`` -- lower-snake in real
source -- in its docstring wherever that number belongs. Bindings are LAZY:
they are never called on the normal
check path, only by ``--figures`` / ``--explain`` and by the tests. A binding
that costs a full tree walk therefore costs nothing in CI.

Render the live docstring with::

    python3 programs/derived_corpus_figure_check.py --explain <module>

An ANCHOR adopter declares the same ``CORPUS_FIGURES`` and calls
:func:`render_anchored` over the documents it owns -- in write mode to rewrite
the digits, in check mode to fail on drift. The anchor carries no value of its
own, so an adopter cannot buy a green by editing the anchor.

chip-AGNOSTIC: reads Python source and counts files. No PDK, vendor, process
or design literal appears here or can affect any result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Tuple

#: ``{figure:some_name}``. Lower-snake only, so it cannot collide with the
#: ``{}`` of an f-string or a ``str.format`` template quoted in prose.
PLACEHOLDER_RE = re.compile(r"\{figure:([a-z][a-z0-9_]*)\}")

#: The module-global an adopting module must define.
FIGURES_ATTR = "CORPUS_FIGURES"


class FigureError(RuntimeError):
    """A placeholder has no binding, or a binding did not produce an int."""


class CorpusFigures(Mapping):
    """``name -> callable(root: Path) -> int``, evaluated lazily and never cached.

    Not cached on purpose. A cache would let a figure be computed once, early,
    and then be stale for the rest of the process — a smaller copy of the exact
    defect this module exists to end.
    """

    def __init__(self, bindings: Mapping[str, Callable[[Path], int]]) -> None:
        bad = sorted(n for n in bindings if not PLACEHOLDER_RE.fullmatch("{figure:%s}" % n))
        if bad:
            raise FigureError(f"figure name(s) not lower-snake: {', '.join(bad)}")
        self._bindings: Dict[str, Callable[[Path], int]] = dict(bindings)

    # -- Mapping ---------------------------------------------------------
    def __getitem__(self, name: str) -> Callable[[Path], int]:
        return self._bindings[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._bindings)

    def __len__(self) -> int:
        return len(self._bindings)

    # -- evaluation ------------------------------------------------------
    def evaluate(self, name: str, root: Path) -> int:
        """Recompute one figure against ``root``. Raises rather than guessing."""
        try:
            fn = self._bindings[name]
        except KeyError:
            raise FigureError(
                f"no binding for {{figure:{name}}}; declared: "
                f"{', '.join(sorted(self._bindings)) or '(none)'}") from None
        value = fn(Path(root))
        if isinstance(value, bool) or not isinstance(value, int):
            raise FigureError(
                f"binding for {{figure:{name}}} returned {value!r} "
                f"({type(value).__name__}); a corpus figure must be an int")
        return value

    def evaluate_all(self, root: Path) -> Dict[str, int]:
        return {name: self.evaluate(name, root) for name in sorted(self._bindings)}


def placeholder_names(doc: str) -> List[str]:
    """Every ``{figure:NAME}`` in ``doc``, in order of appearance, deduplicated."""
    seen: List[str] = []
    for m in PLACEHOLDER_RE.finditer(doc or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def render(doc: str, figures: Mapping[str, int]) -> str:
    """Substitute every placeholder. An unbound name RAISES; it never renders.

    Rendering an unknown placeholder as itself, or as empty, would put a
    docstring back into the state this module exists to prevent: prose that
    reads as a measurement and is not one.
    """
    missing = [n for n in placeholder_names(doc) if n not in figures]
    if missing:
        raise FigureError(
            "docstring names figure(s) with no value: "
            + ", ".join("{figure:%s}" % n for n in missing))
    return PLACEHOLDER_RE.sub(lambda m: str(figures[m.group(1)]), doc)


# ------------------------------------------------------------------ ANCHORS --
#: ``63<!--figure:blocks_on_declared-->``. The digits are the RENDERING; the
#: HTML comment is the anchor that says which binding produced them. Invisible
#: in rendered Markdown, explicit in source, and -- the point -- machine
#: rewritable, so the number in published prose is derived without the prose
#: losing the number.
#:
#: The look-behind refuses a digit that is part of a longer token (a version, a
#: hash, an issue number), so an anchor can only ever be attached to a figure
#: someone wrote as a figure.
ANCHOR_RE = re.compile(
    r"(?<![\w.])(?P<value>\d{1,9})(?P<gap>[ \t]*)"
    r"<!--\s*figure:(?P<name>[a-z][a-z0-9_]*)\s*-->")

#: Reported dispositions of one anchored site.
ANCHOR_FRESH, ANCHOR_STALE, ANCHOR_UNBOUND = "fresh", "stale", "unbound"


@dataclass(frozen=True)
class AnchoredFigure:
    """One ``N<!--figure:name-->`` site, and what the tree says it should be."""

    name: str
    stated: int
    line: int
    status: str
    derived: Optional[int] = None

    @property
    def blocking(self) -> bool:
        return self.status in (ANCHOR_STALE, ANCHOR_UNBOUND)

    def describe(self) -> str:
        if self.status == ANCHOR_UNBOUND:
            return (f"{{figure:{self.name}}} is anchored to {self.stated} but "
                    f"nothing binds that name; an anchor with no binding reads "
                    f"as derived and is not")
        if self.status == ANCHOR_STALE:
            return (f"{{figure:{self.name}}} states {self.stated}; the tree "
                    f"says {self.derived}")
        return f"{{figure:{self.name}}} = {self.stated}"


def anchored_figures(text: str) -> List[AnchoredFigure]:
    """Every anchored site in ``text``, unresolved (``status`` is FRESH).

    Parsing only. Nothing is compared here, so a caller that merely wants to
    COUNT the guarded figures in a document -- which is what a coverage
    disclosure needs -- does not have to evaluate a single binding.
    """
    out: List[AnchoredFigure] = []
    for m in ANCHOR_RE.finditer(text or ""):
        out.append(AnchoredFigure(
            name=m.group("name"),
            stated=int(m.group("value")),
            line=(text or "").count("\n", 0, m.start()) + 1,
            status=ANCHOR_FRESH,
        ))
    return out


def strip_anchored(text: str) -> str:
    """``text`` with every anchored figure REMOVED, digits included.

    An anchored number is already derived, so it must not be counted again as
    a bare population figure by :func:`population_figures`. Removing the digits
    as well as the anchor is deliberate: leaving them would let a derived
    figure be reported as an unguarded one, which is a checker lying in the
    direction that makes it look thorough.
    """
    return ANCHOR_RE.sub("", text or "")


def render_anchored(text: str,
                    values: Mapping[str, int]) -> Tuple[str, List[AnchoredFigure]]:
    """``(rewritten text, per-site verdicts)``.

    Every anchored site is rewritten to the value ``values`` gives for its
    name. A site whose name has no binding is LEFT ALONE and reported
    ``unbound`` -- silently rendering it to something would invent a figure,
    and silently dropping it would hide one.

    The returned text is what the document SHOULD say. A checker compares it
    with what the document does say; a writer stores it. Both directions come
    from the same function on purpose, so a `--check` that passes cannot
    disagree with the rewrite that would follow it.
    """
    sites: List[AnchoredFigure] = []

    def _sub(m: "re.Match[str]") -> str:
        name = m.group("name")
        stated = int(m.group("value"))
        line = text.count("\n", 0, m.start()) + 1
        if name not in values:
            sites.append(AnchoredFigure(name, stated, line, ANCHOR_UNBOUND))
            return m.group(0)
        derived = int(values[name])
        sites.append(AnchoredFigure(
            name, stated, line,
            ANCHOR_FRESH if derived == stated else ANCHOR_STALE, derived))
        return f"{derived}{m.group('gap')}<!--figure:{name}-->"

    return ANCHOR_RE.sub(_sub, text or ""), sites


# ------------------------------------------- the population-figure vocabulary --
# Moved here from ``derived_corpus_figure_check`` so that the checker and every
# anchor adopter grade "is this an unguarded corpus figure?" by the SAME rule.
# Two copies of this vocabulary would let a gate's coverage report disagree with
# the gate, which is the failure mode a coverage report exists to expose.

#: Nouns that make an integer a POPULATION figure rather than a threshold, an
#: index, a byte count or a duration. Closed vocabulary, extended only with a
#: measured reason.
POPULATION_NOUN = (
    r"programs?|files?|checkers?|matches|match|sites?|candidates?|entries|entry|"
    r"tests?|occurrences?|instances?|documents?|projects?|modules?|records?|"
    r"accumulators?|merges?|directories|dirs?|cells?|hits?|rows?|blobs?|"
    r"steps?|clauses?|dimensions?"
)

#: ``123 files`` / ``123 syntactic matches`` / ``population 123``.
FIGURE_AFTER_RE = re.compile(
    r"(?<![\w.#$%/:-])(\d{1,7})\s+(?:\w+[- ]){0,2}(?:" + POPULATION_NOUN + r")\b",
    re.IGNORECASE)
FIGURE_BEFORE_RE = re.compile(
    r"\b(?:" + POPULATION_NOUN + r")\s+(?![\w.-])(\d{1,7})\b", re.IGNORECASE)

#: A number in a threshold is a RULE CONSTANT, not a measurement of anything.
THRESHOLD_LEAD_RE = re.compile(
    r"(>=|<=|>|<|at\s+least|at\s+most|fewer\s+than|more\s+than|up\s+to|"
    r"exactly|than|only|least|most)\s*$", re.IGNORECASE)

#: A PIN marks a figure as a record of a measurement taken THEN, against a
#: state a reader can still get back to. It is the only thing that exempts a
#: figure from being derived, because it is the only thing that stops the
#: figure being a claim about the tree as it is now.
PIN_RE = re.compile(
    r"\{figure:[a-z0-9_]+\}"                 # derived by this seam: not a claim
    r"|(?<![\w])[0-9a-f]{7,40}(?![\w])"      # pinned commit
    r"|#\d{2,5}\b"                           # pinned issue / PR
    r"|\bv\d+\.\d+\.\d+\b"                   # pinned version
    r"|\b20\d\d-\d\d-\d\d\b",                # dated measurement
    re.IGNORECASE)


def paragraphs(doc: str) -> List[Tuple[int, str]]:
    """Blank-line separated blocks, with the 1-based line offset of each.

    Shared, not duplicated: a pin binds the paragraph it sits in, so any two
    consumers that disagree about where a paragraph ends disagree about which
    figures are pinned.
    """
    out: List[Tuple[int, str]] = []
    cur: List[str] = []
    start = 1
    for i, line in enumerate((doc or "").splitlines(), start=1):
        if line.strip():
            if not cur:
                start = i
            cur.append(line)
        elif cur:
            out.append((start, "\n".join(cur)))
            cur = []
    if cur:
        out.append((start, "\n".join(cur)))
    return out


def population_figures(text: str) -> List[str]:
    """Integers sitting in population position, thresholds and anchors excluded."""
    text = strip_anchored(text)
    found: List[str] = []
    for rx in (FIGURE_AFTER_RE, FIGURE_BEFORE_RE):
        for m in rx.finditer(text):
            if THRESHOLD_LEAD_RE.search(text[max(0, m.start() - 16):m.start()]):
                continue
            found.append(" ".join(m.group(0).split()))
    return found
