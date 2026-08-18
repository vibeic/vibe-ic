#!/usr/bin/env python3
"""A census row may not publish fewer cells than the dimension it names.

WHAT THE INSTRUMENT MEASURED VS WHAT IT CLAIMED
===============================================
The generated table in ``matrix_63x8/README.md`` measured *cells whose predicate
returned a verdict* and published them as *the dimension*. Those are the same
number only while every predicate can run.

MEASURED on ``7c376e348``, from the committed block itself — no re-run needed,
the arithmetic is on the page::

    **504 cells: 428 ENFORCED, 0 ENFORCED-CONTRADICTED, 8 WAIVED, 15 NA,
      50 ENFORCED-SKIPPED, 3 WAIVED-SKIPPED.**

    | 3 | `outputs_produced` … | 0 | 0 | 0 | 0 | 0 | 11 |
    | 7 | `outputs_list_complete` … | 0 | 0 | 57 | 0 | 4 | 1 |
    | **total** | | **17** | **44** | **367** | **0** | **8** | **15** |

    row d3     ->  11 of 63
    row d7     ->  62 of 63
    total row  -> 451 of 504

The headline partitioned; the table did not. ``_join_axes`` emits nine labels
and the table enumerated six columns by hand, so every ``-SKIPPED`` cell was
printed nowhere at all. Dimension 3's 52 unmeasured cells — the published
corpus is not in this checkout, so not one of its predicates could look at a
single byte — left the row silently, and what remained read ``0 0 0 0 0 11``:
a dimension with no contradictions, no waivers, nothing wrong in it. A reader
cannot tell that from a dimension that was measured and came back clean, which
is this repository's oldest defect shape, printed in its headline table.

The generator already knew. Six lines above the table it says a column exists
for CONTRADICTED because "a row that silently drops cells is the
erasure-by-omission this file warns about", and ends "Every one of the 504 is
now in exactly one." That sentence lived in a comment, so it went false without
anything noticing.

WHAT IS GUARDED HERE, IN BOTH DIRECTIONS
========================================
* FORWARD — the committed block partitions: every dimension row sums to its own
  cell count and the total row sums to the headline. Deleting the NOT MEASURED
  column reddens this immediately, because the 53 cells have nowhere else to go.
* REVERSE — the generator REFUSES rather than under-reports. Removing the
  per-row denominator check, or adding a label with no column, must abort the
  render by name. A generator that quietly prints a short row is exactly what
  produced the block above, and a green run over it proved nothing.

Neither test runs the live census: both drive ``render()`` over synthetic rows
or parse the committed artefact. The two-minute nested pytest belongs to
``test_matrix_63x8_census_freshness.py``, which checks a different property.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path, repo_path_or_missing

GEN = repo_path_or_missing("tools", "gen_matrix_63x8_census.py")
README = plugin_path("programs", "tests", "matrix_63x8", "README.md")

BEGIN = ("<!-- BEGIN GENERATED CENSUS — tools/gen_matrix_63x8_census.py — "
         "DO NOT EDIT BY HAND -->")
END = "<!-- END GENERATED CENSUS -->"

#: A dimension row: ``| <dim> | <question> | n | n | ... |``. The question text
#: carries pipes nowhere, but it does carry em dashes and backticks, so the row
#: is matched by its shape — a leading small integer and a tail of bare numbers.
_ROW = re.compile(r"^\|\s*(\d+)\s*\|[^|]*\|((?:\s*\d+\s*\|)+)\s*$", re.M)
_TOTAL = re.compile(r"^\|\s*\*\*total\*\*\s*\|[^|]*\|((?:\s*\*\*\d+\*\*\s*\|)+)\s*$",
                    re.M)


def _gen_or_skip() -> Path:
    if not GEN.exists():
        pytest.skip(
            f"generator not present at {GEN} (mirror tree); the census table "
            f"is generated in the source-of-truth tree only")
    return GEN


def _load_generator():
    """Import the generator without leaving bytecode in the audited tree."""
    spec = importlib.util.spec_from_file_location(
        "_gen_matrix_63x8_census_partition", str(_gen_or_skip()))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


def _block() -> str:
    text = README.read_text(encoding="utf-8")
    start, stop = text.find(BEGIN), text.find(END)
    assert 0 <= start < stop, (
        f"{README} has no generated-census block; without the markers there is "
        f"no published table to check and this test has NOT looked")
    return text[start:stop + len(END)]


def _headline_cells(block: str) -> int:
    m = re.search(r"\*\*(\d+) cells:", block)
    assert m, (
        f"no ``**N cells:`` headline in the census block. The headline is the "
        f"denominator every row below is measured against; without it this "
        f"test cannot compare and must not pass.\n{block[:600]}")
    return int(m.group(1))


def _rows(block: str):
    out = [(int(m.group(1)),
            [int(x) for x in m.group(2).split("|") if x.strip()])
           for m in _ROW.finditer(block)]
    assert out, f"no dimension rows parsed from the census block\n{block[:800]}"
    return out


# ──────────────────────────────────────────────────────────────────────
# FORWARD: the committed artefact partitions.
# ──────────────────────────────────────────────────────────────────────
def test_every_published_dimension_row_accounts_for_all_of_its_cells():
    """d3 published 11 of 63 and nothing was red. That is the defect."""
    block = _block()
    cells = _headline_cells(block)
    rows = _rows(block)
    per_dim, remainder = divmod(cells, len(rows))
    assert not remainder, (
        f"{cells} cells over {len(rows)} dimensions is not a rectangle; this "
        f"test's per-row denominator does not apply and it has not checked")
    short = [(dim, sum(cols), cols) for dim, cols in rows
             if sum(cols) != per_dim]
    assert not short, (
        f"published row(s) do not account for every cell of their dimension "
        f"(expected {per_dim} each): "
        + "; ".join(f"d{d} publishes {n} — {c}" for d, n, c in short)
        + ". A dimension whose predicates could not run drops out of its own "
          "row and the remainder reads as a clean dimension. Every label "
          "`_join_axes` can emit needs a column; see _COLUMN_OF_LABEL in "
          "tools/gen_matrix_63x8_census.py.")


def test_the_published_total_row_accounts_for_the_whole_matrix():
    block = _block()
    cells = _headline_cells(block)
    m = _TOTAL.search(block)
    assert m, f"no ``**total**`` row parsed from the census block\n{block[:800]}"
    figures = [int(x) for x in re.findall(r"\d+", m.group(1))]
    assert sum(figures) == cells, (
        f"the published total row accounts for {sum(figures)} cells "
        f"({figures}) while the headline directly above it says {cells}. "
        f"MEASURED on 7c376e348: 451 vs 504. The 53 missing cells were the "
        f"ones nothing could measure, and a total that omits them reports the "
        f"matrix as fully looked at.")


def test_the_not_measured_column_is_published_even_when_it_is_zero():
    """The column must be a fixture of the table, not something that appears
    only once a cell has already gone dark. A reader who cannot see the column
    cannot tell a fully-measured matrix from one with an axis missing."""
    block = _block()
    assert "NOT MEASURED" in block, (
        "the census table has no NOT MEASURED column. Cells whose predicate "
        "could not run then belong to no column and leave the row without a "
        "trace — which is how dimension 3 published 11 of its 63 cells.")


# ──────────────────────────────────────────────────────────────────────
# REVERSE: the generator refuses instead of under-reporting.
# ──────────────────────────────────────────────────────────────────────
def _synthetic(n_dims=2, cells_per_dim=63):
    """Rows shaped like `census_rows()`, with one dimension gone entirely dark."""
    rows = []
    for dim in range(1, n_dims + 1):
        dark = cells_per_dim if dim == 1 else 0
        rows.append({
            "dim": dim, "name": f"dim{dim}", "question": f"question {dim}?",
            "cells": cells_per_dim,
            "own": 0, "substituted": 0,
            "undeclared": 0 if dark else cells_per_dim,
            "enforced": 0 if dark else cells_per_dim,
            "contradicted": 0, "waived": 0, "na": 0,
            "waived_contradicted": 0, "na_contradicted": 0,
            "enforced_skipped": dark, "waived_skipped": 0, "na_skipped": 0,
        })
    totals = {k: sum(r[k] for r in rows)
              for k in ("own", "substituted", "undeclared", "enforced",
                        "contradicted", "waived", "na", "waived_contradicted",
                        "na_contradicted", "enforced_skipped",
                        "waived_skipped", "na_skipped")}
    totals["cells"] = n_dims * cells_per_dim
    return rows, totals


def test_a_dimension_that_measured_nothing_is_printed_as_such():
    """The positive half: 63 unmeasured cells must reach the page."""
    gen = _load_generator()
    rows, totals = _synthetic()
    block = gen.render(rows, totals)
    parsed = dict(_rows(block))
    assert sum(parsed[1]) == 63, (
        f"the fully-dark dimension published {sum(parsed[1])} of its 63 cells "
        f"({parsed[1]}); its unmeasured cells are being dropped from the row")
    assert 63 in parsed[1], (
        f"the 63 unmeasured cells are not printed as their own figure: "
        f"{parsed[1]}")
    m = _TOTAL.search(block)
    assert m and sum(int(x) for x in re.findall(r"\d+", m.group(1))) == 126


def test_a_label_with_no_column_aborts_the_render_by_name():
    """A label the table cannot print must stop the generator, not shrink a row."""
    gen = _load_generator()
    assert hasattr(gen, "_COLUMN_OF_LABEL"), (
        "the generator has no _COLUMN_OF_LABEL map, so its table columns are "
        "enumerated by hand again and a new label from `_join_axes` will be "
        "printed nowhere")
    rows, totals = _synthetic()
    gen._COLUMN_OF_LABEL.pop("enforced_skipped")
    try:
        with pytest.raises(SystemExit) as exc:
            gen.render(rows, totals)
    finally:
        gen._COLUMN_OF_LABEL["enforced_skipped"] = "not_measured"
    assert "enforced_skipped" in str(exc.value), (
        f"the render aborted without naming the label it has no column for, "
        f"so the reader cannot act on it: {exc.value}")


def test_a_row_that_under_reports_its_own_denominator_is_refused():
    """The PER-ROW check, isolated from the headline one that already existed.

    Constructed so the headline partitions PERFECTLY — its label totals reach
    its cell count — while one row does not reach its own. That is not a
    contrived split: it is precisely the state of 7c376e348, where the
    headline reconciled 504 and the d3 row published 11 of 63. A guard that
    only sums the headline is green over both.
    """
    gen = _load_generator()
    rows, _ = _synthetic()
    for key in ("enforced", "enforced_skipped", "undeclared"):
        rows[0][key] = 0                      # dimension 1: 63 cells, none printed
    totals = {k: sum(r.get(k, 0) for r in rows)
              for k in ("own", "substituted", "undeclared", "enforced",
                        "contradicted", "waived", "na", "waived_contradicted",
                        "na_contradicted", "enforced_skipped",
                        "waived_skipped", "na_skipped")}
    # The headline's own guard must be satisfied, or it fires first and this
    # test proves nothing about the row.
    totals["cells"] = sum(totals[k] for k in gen._LABEL_KEYS)
    assert totals["cells"] == 63, totals

    with pytest.raises(SystemExit) as exc:
        gen.render(rows, totals)
    message = str(exc.value)
    assert "63" in message and "partition" in message, (
        f"a row publishing 0 of its 63 cells was rendered without refusal or "
        f"without naming the gap: {message}")
    assert "dimension 1" in message, (
        f"the refusal does not say WHICH row is short, so the reader cannot "
        f"act on it: {message}")
