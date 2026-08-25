"""#1296 — the published census table dropped every cell it could not measure.

WHAT THE INSTRUMENT MEASURED vs WHAT IT CLAIMED
===============================================
`tools/gen_matrix_census.py` publishes a per-dimension table into
`matrix/README.md`, and the comment directly above that table claimed
"Every one of the 504 is now in exactly one" column. It printed SIX columns —
own / substituted / undeclared / CONTRADICTED / WAIVED / NA — while `_join_axes`
had learned to emit a seventh kind of label, `{state}-SKIPPED`, for a cell whose
predicate declined to run.

MEASURED on clean detached `7c376e348`, `git status --porcelain` empty::

    | **total** | | **17** | **44** | **367** | **0** | **8** | **15** |
                  17 + 44 + 367 + 0 + 8 + 15 = 451, against 504 cells

    | 3 | `outputs_produced` … | 0 | 0 | 0 | 0 | 0 | 11 |
                  dimension 3 published 11 of its 63 cells

The 53 missing cells were the ones whose predicate could not look — d3's whole
corpus-dependent cluster, plus one in d7. Dropped from every row, from the
total, and from the reader's view. A dimension that could not be measured read
as a dimension with nothing to report, which is the exact inversion of what the
NOT-MEASURED distinction was introduced (`4e51c4853`) to preserve.

`4e51c4853` gave the HEADLINE a partition guard (`_LABEL_KEYS`) and left the
table naming its columns inline, so the two disagreed by 53 cells and nothing
said so — except `test_the_published_total_equals_the_live_census`, which was
already red on main with `451 cells but the matrix has 504` and had been read as
noise.

WHY THESE TESTS ARE CHEAP
=========================
They drive `render()` and `_fold_label_columns()` on SYNTHETIC rows. The live
census costs ~2 minutes in a nested pytest; the property that must not regress —
that every cell reaches a printed column — is a property of the renderer, and a
guard nobody can afford to run is a guard that stops running.

The live half is covered by
`test_matrix_census_freshness.py::test_the_published_total_equals_the_live_census`.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest \\
      programs/tests/test_issue1296_census_table_partitions_every_cell.py -q
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Dict, List

import pytest

_REPO = Path(__file__).resolve().parents[5]
_GEN = _REPO / "tools" / "gen_matrix_census.py"

#: The shape MEASURED on `7c376e348`: dimension 3's corpus-dependent cells all
#: skipped, so 52 of its 63 carried a `-SKIPPED` label, and one of d7's did.
#: Reproduced here rather than invented, so this file fails for the reason the
#: issue names and not for a shape nobody has seen.
_MEASURED_SKIPPED = {3: {"enforced_skipped": 49, "waived_skipped": 3, "na": 11},
                     7: {"enforced_skipped": 1}}

#: The SAME skips with no other label moved, so a before/after comparison
#: isolates one variable. `_MEASURED_SKIPPED` also carries d3's 11 NA cells,
#: which is the real shape but not a clean delta.
_SKIPPED_ONLY = {3: {"enforced_skipped": 49, "waived_skipped": 3},
                 7: {"enforced_skipped": 1}}

_CELLS_PER_DIM = 63
_DIMS = (1, 2, 3, 4, 5, 6, 7, 8)


def _gen():
    spec = importlib.util.spec_from_file_location("gen_census_i1296", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(gen, skipped: Dict[int, Dict[str, int]]) -> List[Dict]:
    """One row per dimension, every cell accounted for, `skipped` applied."""
    rows = []
    for dim in _DIMS:
        row = {"dim": dim, "name": f"d{dim}", "question": "q",
               "own": 0, "substituted": 0, "undeclared": 0}
        row.update({key: 0 for key in gen._LABEL_KEYS})
        row.update(skipped.get(dim, {}))
        # Whatever is left over is plain ENFORCED, published as undeclared.
        rest = _CELLS_PER_DIM - sum(
            row[k] for k in gen._LABEL_KEYS if k != "enforced")
        row["enforced"] = rest
        row["undeclared"] = rest
        rows.append(row)
    return rows


def _totals(gen, rows: List[Dict]) -> Dict[str, int]:
    """Totals over whatever columns this generator's rows carry.

    `_fold_label_columns` is called WHEN IT EXISTS rather than unconditionally.
    That is not defensive style — it is what makes these tests grade the
    PUBLISHED TABLE instead of grading an implementation detail. Called
    unconditionally, every assertion below dies with `AttributeError: no
    attribute '_fold_label_columns'` against a tree that lacks the fix, which
    proves a helper is missing and says nothing at all about whether the table
    drops cells. A guard that reports "the fix is absent" when asked "is the
    published census short" is the same instrument defect #1296 is about.
    """
    fold = getattr(gen, "_fold_label_columns", None)
    if fold is not None:
        fold(rows)
    keys = {k for r in rows for k, v in r.items()
            if isinstance(v, int) and k != "dim"}
    totals = {k: sum(r.get(k, 0) for r in rows) for k in keys}
    totals["cells"] = _CELLS_PER_DIM * len(_DIMS)
    totals["cells_per_dim"] = _CELLS_PER_DIM
    return totals


def _published(gen, skipped: Dict[int, Dict[str, int]]) -> str:
    rows = _rows(gen, skipped)
    return gen.render(rows, _totals(gen, rows))


def _total_columns(block: str) -> Dict[str, int]:
    """``{column header: published total}`` — read off the rendered block.

    Keyed by the HEADER TEXT, so a column that does not exist reads as absent
    rather than shifting every figure after it by one position.
    """
    table = _table(block)
    header = table[0]
    total = next(r for r in table if "**total**" in r[0])
    out: Dict[str, int] = {}
    for name, cell in zip(header[2:], total[2:]):
        m = re.fullmatch(r"\*?\*?(\d+)\*?\*?", cell)
        if m:
            out[name] = int(m.group(1))
    return out


def _table(block: str) -> List[List[str]]:
    return [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in block.splitlines()
            if line.startswith("|") and not set(line) <= set("|-: ")]


def _figures(cells: List[str]) -> List[int]:
    """The COUNT cells of one printed row, bold or not.

    The first two columns are the dimension label and its question, never
    counts. Dropping them by position rather than by "is it a digit" matters:
    the dimension label IS a digit, so a naive numeric scan silently adds the
    dimension id to that dimension's own cell count.
    """
    figures = []
    for cell in cells[2:]:
        m = re.fullmatch(r"\*?\*?(\d+)\*?\*?", cell)
        assert m, f"non-numeric figure in a census count column: {cell!r}"
        figures.append(int(m.group(1)))
    return figures


# ──────────────────────────────────────────────────────────────────────
# DIRECTION 1 — a cell that could not be measured must still be PRINTED.
# This is what fails on the reverted tree.
# ──────────────────────────────────────────────────────────────────────

def test_every_dimension_row_accounts_for_every_one_of_its_cells():
    """The row is what a reader reads, so the row is what must partition.

    A total that reconciles can still hide one dimension dropping cells while
    another double-counts them. On `7c376e348` the total did not reconcile
    either, but the ROW is the stronger statement and it is the one a reader
    quotes when they say "dimension 3 is clean".
    """
    gen = _gen()
    block = _published(gen, _MEASURED_SKIPPED)
    body = [r for r in _table(block) if r[0].isdigit()]
    assert len(body) == len(_DIMS), f"expected {len(_DIMS)} rows, got {body}"
    for row in body:
        figures = _figures(row)
        assert sum(figures) == _CELLS_PER_DIM, (
            f"dimension {row[0]} publishes {sum(figures)} of "
            f"{_CELLS_PER_DIM} cells ({figures}). The cells it drops are the "
            f"ones whose predicate could not run, and dropping them makes an "
            f"unmeasurable dimension read as an empty one.")


def test_the_published_total_accounts_for_every_cell():
    gen = _gen()
    cells = _CELLS_PER_DIM * len(_DIMS)
    block = _published(gen, _MEASURED_SKIPPED)
    published = _total_columns(block)
    assert sum(published.values()) == cells, (
        f"the total row publishes {sum(published.values())} of {cells} cells "
        f"({published})")


def test_the_not_measured_cells_are_visible_by_name():
    """A column of digits with no word for what they mean is not a disclosure."""
    gen = _gen()
    block = _published(gen, _MEASURED_SKIPPED)
    header = _table(block)[0]
    assert "NOT MEASURED" in header, (
        f"no NOT MEASURED column in the published header: {header}")
    assert re.search(r"NOT MEASURED is not a pass and not a defect", block), (
        "the block prints a NOT MEASURED figure and never says what it means. "
        "A reader has to be told it is UNKNOWN, or they will read it as either "
        "coverage or a defect, and it is neither.")


# ──────────────────────────────────────────────────────────────────────
# DIRECTION 2 — the fix must not buy the partition by mislabelling.
# ──────────────────────────────────────────────────────────────────────

def test_a_not_measured_cell_is_never_counted_as_enforcement():
    """The cheap way to make the row add up is the one that recreates #888.

    Folding the skipped cells into `undeclared` would partition perfectly and
    republish exactly the lie this campaign exists to remove: a cell that
    proved nothing, counted as coverage.
    """
    gen = _gen()
    n_skipped = sum(v for d in _SKIPPED_ONLY.values()
                    for k, v in d.items() if k.endswith("_skipped"))
    assert n_skipped == 53, n_skipped
    clean = _total_columns(_published(gen, {}))
    skipped = _total_columns(_published(gen, _SKIPPED_ONLY))
    enforcement = [c for c in clean if c.startswith("ENFORCED")]
    assert enforcement, f"no ENFORCED column in the published header: {clean}"
    lost = sum(clean[c] for c in enforcement) - sum(
        skipped.get(c, 0) for c in enforcement)
    assert lost == n_skipped, (
        f"{n_skipped} cells stopped being measurable and the ENFORCED columns "
        f"lost {lost} of them. Every one must leave: an unmeasurable cell "
        f"inside a figure presented as enforcement is exactly the #888 "
        f"erasure, and folding the skips into `undeclared` is the cheap way to "
        f"make the row add up.\nclean={clean}\nskipped={skipped}")


def test_a_skipped_cell_is_not_reported_as_a_contradiction():
    """`-SKIPPED` and `-CONTRADICTED` have different causes and different owners.

    Filing "could not look" as "looked and found a defect" is the conflation
    `4e51c4853` removed one level down; the table must not rebuild it.
    """
    gen = _gen()
    published = _total_columns(_published(gen, _MEASURED_SKIPPED))
    assert published.get("CONTRADICTED") == 0, (
        f"unmeasurable cells were published as contradictions: {published}")
    assert published.get("NOT MEASURED") == 53, (
        f"the 53 cells whose predicate declined to run are not published under "
        f"NOT MEASURED; the table says {published}")


def test_a_label_with_no_column_refuses_instead_of_vanishing():
    """The structural half: a NINTH label must redden, not disappear.

    This is the property `_LABEL_KEYS` gave the headline and the table did not
    have. Without it the next label added to `_join_axes` repeats #1296
    verbatim.
    """
    gen = _gen()
    fold = getattr(gen, "_fold_label_columns", None)
    assert fold is not None, (
        "the generator has no step that maps every census label onto a printed "
        "column, so a label added to `_join_axes` reaches the headline and "
        "reaches no table column — which is #1296 exactly, and it will happen "
        "again the next time a label is added")
    gen._LABEL_KEYS = gen._LABEL_KEYS + ("enforced_quarantined",)
    rows = _rows(gen, {})
    for row in rows:
        row["enforced_quarantined"] = 0
    with pytest.raises(SystemExit) as excinfo:
        fold(rows)
    assert "enforced_quarantined" in str(excinfo.value), (
        f"a label with no table column was not named in the refusal: "
        f"{excinfo.value}")


def test_a_row_that_does_not_partition_aborts_the_generator():
    """The renderer refuses a table it cannot make add up.

    Degrade loudly: publishing a short row is what #1296 was, so the generator
    must stop rather than emit one.
    """
    gen = _gen()
    rows = _rows(gen, _MEASURED_SKIPPED)
    totals = _totals(gen, rows)
    assert "not_measured" in rows[2], (
        "no NOT MEASURED column exists to drop cells from — the renderer "
        "cannot refuse a short row because it has no notion of one")
    rows[2]["not_measured"] -= 7          # a column silently losing cells
    with pytest.raises(SystemExit) as excinfo:
        gen.render(rows, totals)
    assert "dimension 3" in str(excinfo.value), (
        f"the refusal did not name the dimension that dropped cells: "
        f"{excinfo.value}")


def test_the_gate_verdict_line_accounts_for_every_cell():
    """The PASS line is what a landing reviewer reads, and it dropped 53 too.

    MEASURED on `7c376e348`::

        [PASS] 63x8 census fresh: 504 cells over 8 dimensions;
               ENFORCED own=17 substituted=44 undeclared=367; WAIVED=8 NA=15.

    It announces 504 and then prints five figures that sum to 451. Nobody adds
    up a verdict line, which is exactly why the sum has to be printed on it.
    """
    gen = _gen()
    verdict = getattr(gen, "_verdict_partition", None)
    assert verdict is not None, (
        "the gate verdict line does not state whether its own figures account "
        "for the cell count it announces, so it can print `504 cells` over a "
        "set of columns that covers 451 of them — which is what it did")
    rows = _rows(gen, _MEASURED_SKIPPED)
    totals = _totals(gen, rows)
    assert verdict(totals) == f"{totals['cells']}/{totals['cells']} accounted"

    short = dict(totals)
    short["not_measured"] = 0          # the 53 dropped, as on the old tree
    assert "UNACCOUNTED: 53" in verdict(short), (
        f"a verdict line missing 53 cells did not say so: {verdict(short)}")


def test_the_verdict_line_names_the_unmeasured_cells():
    """A partition figure with no NOT-MEASURED term hides them inside the sum."""
    gen = _gen()
    src = Path(gen.__file__).read_text(encoding="utf-8")
    # Anchored on the print CALL, not on the string: the module docstring
    # quotes an old verdict line verbatim, and a scan that finds the prose
    # first grades a comment instead of the code.
    pass_line = re.search(
        r'print\(f"\[PASS\] 63x8 census fresh:.*?\)\n', src, re.S)
    assert pass_line, "the census PASS verdict line is no longer recognisable"
    for term in ("NOT-MEASURED", "CONTRADICTED", "_verdict_partition"):
        assert term in pass_line.group(0), (
            f"the PASS verdict line does not carry {term!r}; it announces a "
            f"cell count and publishes columns that do not reach it")
