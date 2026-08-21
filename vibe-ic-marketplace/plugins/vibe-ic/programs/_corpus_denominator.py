#!/usr/bin/env python3
"""_corpus_denominator.py — a statistic over the corpus must carry its own
denominator, because 73 of 75 published run trees cannot answer. vibe-ic#1200.

THE MEASUREMENT
===============
On `a38902d1` (v1.10.35):

    published run trees under benchmark-data/ic : 75
      with a readable steps/STEP_INDEX.json     :  2
      without one                               : 73   (97%)

The two are `spm/v1.10.18_sky130A` and `spm/v1.9.96_gf180mcuD`, and where the
record exists it is complete — all 63 step ids.

So a question of the form *"how many published runs recorded X for step N"* is
unanswerable today for every X and every N. The answer that comes back is not an
error: it is a small number with a silently small denominator. #1070's per-edge
census returns `WOULD FLIP 0 of 2 countable`, and `0` is a true statement about
two run trees that says nothing about seventy-five.

`gate_discloses_denominator_check` already enforces "a PASS must say how much it
looked at" for GATES over an empty project. This is the same disease in a
different population — statistics over the published corpus — and the same
remedy: make the denominator impossible to omit.

WHY NOT BACKFILL, WHICH IS THE OBVIOUS FIX
==========================================
Re-running the 73 to generate their step records would be writing NEW claims
about runs that already happened. A published run tree is the evidence for a
claim about a run; regenerating its verdicts today produces a record of what the
current code would say, wearing the name of a run from months ago. That is worse
than the gap, so the 73 stay uncountable and are COUNTED as uncountable.

THE MECHANISM: YOU CANNOT GET THE NUMERATOR WITHOUT THE DENOMINATOR
====================================================================
:class:`Denominator` has no attribute that yields a bare rate. `fraction()`
returns the pair, `render()` returns a sentence carrying both, and there is
deliberately no `__int__`, no `__float__` and no `percent` — because every one of
those is a way to quote 2 without quoting 75, which is the whole defect. A caller
that wants a number must ask for `n_countable` and `n_total` by name, and having
typed both it can no longer print one by accident.

THE RATCHET, AND ITS ONE DIRECTION
==================================
`uncountable` may SHRINK and may not GROW. A newly published run tree that omits
`steps/STEP_INDEX.json` makes the corpus less answerable than it was, and that is
a regression a publication should not be able to make quietly. Old trees are
grandfathered by NUMBER, not by name-list: pinning the 73 paths would turn every
withdrawal into a test edit, and this repo has paid for name-list pins before.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

#: The per-step verdict record a run tree must carry to be countable.
STEP_INDEX_REL = "steps/STEP_INDEX.json"

#: Uncountable run trees measured on a38902d1. The ratchet's ceiling.
#:
#: A NUMBER and not a list of paths, deliberately. A name-list would make every
#: withdrawal or republish a test edit, and the property being guarded is "the
#: corpus did not become less answerable", which is a count.
UNCOUNTABLE_CEILING = 73


@dataclass(frozen=True)
class Denominator:
    """How much of the corpus could answer, and how much could not.

    Carries no bare-rate accessor on purpose — see the module docstring.
    """
    n_countable: int
    n_total: int
    uncountable: Tuple[str, ...] = ()
    reason: str = ""

    def fraction(self) -> Tuple[int, int]:
        """`(countable, total)`. Both, always, in that order."""
        return self.n_countable, self.n_total

    def render(self) -> str:
        """One sentence that cannot be quoted without its denominator."""
        if self.n_total == 0:
            return ("0 of 0 — nothing was scanned, so this statistic has no "
                    "population and is not a finding about the corpus")
        s = (f"{self.n_countable} of {self.n_total} run tree(s) could answer; "
             f"{len(self.uncountable)} could not")
        if self.reason:
            s += f" ({self.reason})"
        return s

    def as_dict(self) -> Dict[str, object]:
        return {"n_countable": self.n_countable, "n_total": self.n_total,
                "n_uncountable": len(self.uncountable),
                "uncountable": list(self.uncountable),
                "reason": self.reason,
                "disclosure": self.render()}

    @property
    def is_vacuous(self) -> bool:
        """True when NOTHING could answer. A statistic over zero is not a fact.

        Separate from `n_total == 0`: a corpus of 75 trees none of which can
        answer is just as vacuous as an empty one, and reads far more like a
        real result.
        """
        return self.n_countable == 0


def run_trees(ic_root: Path) -> List[Path]:
    """Every published run tree under `benchmark-data/ic/<IC>/<run>/`.

    Two levels, because that is the published shape: an IC directory holding one
    directory per run. A deeper walk would count `steps/` and `reports/` as run
    trees and inflate the denominator, which is the same lie upside down.
    """
    if not ic_root.is_dir():
        return []
    out: List[Path] = []
    for ic in sorted(p for p in ic_root.iterdir() if p.is_dir()):
        out.extend(sorted(p for p in ic.iterdir() if p.is_dir()))
    return out


def _has_step_index(tree: Path) -> bool:
    p = tree / STEP_INDEX_REL
    if not p.is_file():
        return False
    try:
        doc = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        # Present but unreadable is NOT countable. A record that cannot be
        # parsed answers nothing, and treating it as countable would put an
        # unanswerable tree in the numerator.
        return False
    return bool(doc)


def step_verdict_denominator(ic_root: Path,
                             countable: Optional[Callable[[Path], bool]] = None,
                             ) -> Denominator:
    """The denominator for any statistic about per-step verdicts."""
    pred = countable or _has_step_index
    trees = run_trees(ic_root)
    un = tuple(str(t.relative_to(ic_root)) for t in trees if not pred(t))
    return Denominator(n_countable=len(trees) - len(un), n_total=len(trees),
                       uncountable=un,
                       reason=f"no readable {STEP_INDEX_REL}")


def ratchet_verdict(den: Denominator,
                    ceiling: int = UNCOUNTABLE_CEILING) -> Tuple[bool, str]:
    """`(ok, sentence)` — the uncountable set may shrink, never grow."""
    n = len(den.uncountable)
    if n > ceiling:
        return False, (
            f"{n} run tree(s) cannot answer a per-step verdict question, up "
            f"from {ceiling}. A newly published run tree omitted "
            f"{STEP_INDEX_REL}, which makes the corpus less answerable than it "
            f"was. Publish the record with the run, or lower the ceiling and "
            f"say which trees came down.")
    if n < ceiling:
        return True, (
            f"{n} uncountable, down from {ceiling} — lower "
            f"UNCOUNTABLE_CEILING to {n} so the gain is held.")
    return True, f"{n} uncountable, unchanged from {ceiling}"
