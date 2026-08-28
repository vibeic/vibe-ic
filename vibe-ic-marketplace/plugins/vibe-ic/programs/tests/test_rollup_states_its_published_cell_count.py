#!/usr/bin/env python3
"""The roll-up fraction must say how many PUBLISHED CELLS it counted.

THE DEFECT, AS IT WAS MEASURED
==============================
`benchmark_evidence_structure_check --tree` prints one line that a CI reader takes
the impression from. Over `vibeic/benchmark-data` at two commits, `--tree` on a
clean `a4caccefe` worktree:

    146d665   (pre-withdrawal, 4 published cells)  ->  "13/13 conformant, 0 nonconformant"
    3b58ccd42 (today,          0 published cells)  ->   "9/9 conformant, 0 nonconformant"

Both lines are TRUE. Neither states the cell count, and the two trees differ by
EVERY PUBLISHED CELL IN THE REPOSITORY. A reader gets the same sentence shape from
a corpus with four cells and from a corpus with none.

The per-unit rows are not wrong — each says `IC-level layout: 1 published entry
examined, all allowed`, which is the vibe-ic#967 disclosure working — and `--json`
carries `kind` per unit and separates them exactly. It is the ROLL-UP that did not,
and the roll-up is what gets read.

WHAT THIS IS NOT
================
It is a DISCLOSURE repair, not a verdict change. No gate that said PASS stops
saying PASS, no rc moves, and nothing here makes an empty corpus pass anything —
`9/9 conformant` over zero cells was already rc 0 and stays rc 0. What changes is
that the line now states the population it counted, so the two trees above can no
longer produce the same sentence.

THE FRACTION ITSELF IS UNTOUCHED, deliberately. `"N/N conformant"` is asserted by
substring containment in `test_issue967_empty_ic_unit_examined_nothing.py`, and
the clause is appended after it so every one of those assertions still holds.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_CHECK = _PROGRAMS / "benchmark_evidence_structure_check.py"


def _tree(root: Path, *, cells: int) -> Path:
    """An `ic/` tree with `cells` published cells and 2 IC-level roots."""
    for ic in ("alpha", "beta"):
        d = root / "ic" / ic
        d.mkdir(parents=True, exist_ok=True)
        (d / "input").mkdir(exist_ok=True)
    for n in range(cells):
        cell = root / "ic" / "alpha" / f"v1.{n}.0_sky130A"
        cell.mkdir(parents=True, exist_ok=True)
        (cell / "RESULT.md").write_text("PASS\n", encoding="utf-8")
    return root


def _rollup(tree: Path) -> str:
    r = _pr.run([sys.executable, str(_CHECK), "--tree", str(tree)],
                       capture_output=True, text=True)
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("benchmark_evidence_structure_check: "):
            return line
    raise AssertionError(
        f"no roll-up line in output: {(r.stdout + r.stderr)[-800:]!r}")


def test_the_rollup_states_the_cell_count_when_it_is_zero(tmp_path):
    """The row this whole repair is for. Zero must be PRINTED, not omitted.

    A clause that appears only when there are cells would leave the empty corpus
    with exactly the silence being disclosed.
    """
    line = _rollup(_tree(tmp_path, cells=0))
    assert "0 published cell(s)" in line, (
        "the roll-up over a corpus with NO published cell does not say so — a "
        f"reader cannot tell it from a corpus that has them: {line!r}")


def test_the_rollup_states_the_cell_count_when_there_are_cells(tmp_path):
    line = _rollup(_tree(tmp_path, cells=3))
    assert "3 published cell(s)" in line, line


def _stated_cell_count(line: str) -> int | None:
    """The number the line states for published cells, or None if it states none."""
    m = re.search(r"(\d+) published cell\(s\)", line)
    return int(m.group(1)) if m else None


def test_two_corpora_differing_by_every_cell_state_different_cell_counts(tmp_path):
    """The defect stated as the property it violates.

    AN EARLIER DRAFT OF THIS TEST PASSED ON UNFIXED MAIN. It compared everything
    after the first "conformant" and the two lines differed there already — in the
    #967 SKIPPED clause, which moves with the number of units that examined
    nothing and has nothing to do with cells. It was measuring the thing NEXT to
    the claim, so it certified a tree that had the defect.

    It now reads the cell count out of each line, which is the claim itself: on an
    unfixed tree both sides are None and the assertion cannot be satisfied by any
    other clause moving.
    """
    empty = _rollup(_tree(tmp_path / "empty", cells=0))
    full = _rollup(_tree(tmp_path / "full", cells=4))
    assert _stated_cell_count(empty) == 0, (
        f"the roll-up over a corpus with no published cell states no count: {empty!r}")
    assert _stated_cell_count(full) == 4, (
        f"the roll-up over a corpus with four published cells states no count: {full!r}")


def test_the_conformant_fraction_is_unchanged(tmp_path):
    """The substring every existing assertion depends on must still be there.

    `test_issue967_empty_ic_unit_examined_nothing.py` asserts `"N/N conformant" in
    out`; appending a clause must not disturb that, and this is the guard that
    says so in this file rather than leaving it to be discovered downstream.
    """
    line = _rollup(_tree(tmp_path, cells=2))
    # NOT `"conformant, 0 nonconformant" in line`. An earlier draft asserted that
    # and went red on the FIXED tree: these synthetic cells carry only a
    # RESULT.md, so they are genuinely nonconformant and the count is 2, not 0.
    # The assertion was a false claim about the fixture, and the repair is to ask
    # for the invariant that is actually being protected rather than to loosen it.
    frac = re.search(r"\d+/\d+ conformant, \d+ nonconformant", line)
    assert frac, f"the fraction's shape changed: {line!r}"
    assert frac.end() <= line.index("published cell(s)"), (
        "the population clause must come AFTER the fraction, or a substring "
        f"assertion on the fraction could straddle it: {line!r}")


def test_a_kind_with_no_label_still_reaches_the_line():
    """A kind added later must not fall out of the roll-up silently.

    The label map is a convenience for two known kinds; the COUNTS come from the
    results. This asserts the fallback exists rather than trusting the comment.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import benchmark_evidence_structure_check as B
    assert B._KIND_LABEL.get("cell") == "published cell"
    assert B._KIND_LABEL.get("ic-root") == "IC-level root"
    # The unknown kind falls back to its own name rather than vanishing.
    assert B._KIND_LABEL.get("some-future-kind", "some-future-kind") == \
        "some-future-kind"
