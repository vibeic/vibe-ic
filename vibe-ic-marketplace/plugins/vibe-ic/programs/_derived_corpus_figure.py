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
DERIVE   The figure describes the tree as it is NOW. Write it as a
         ``{figure:NAME}`` placeholder bound, in code, to a callable that
         recomputes it. The source then holds no number, so there is nothing
         to drift. This module is that seam. (NAME is spelled in capitals
         throughout this docstring on purpose: a real placeholder is
         lower-snake, so no example here is itself a live claim.)

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

chip-AGNOSTIC: reads Python source and counts files. No PDK, vendor, process
or design literal appears here or can affect any result.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping

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
