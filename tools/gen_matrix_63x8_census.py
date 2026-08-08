#!/usr/bin/env python3
"""Regenerate the 63x8 census table in ``matrix_63x8/README.md`` from the live
suite, so the number a reader quotes cannot drift away from the tree again.

WHY THIS EXISTS
===============
The README published this table by hand::

    | **total** |  | **483** | **9** | **12** |

Measured 2026-08-09 on ``origin/main`` at ``dee025059``, with the README's own
reproduce command::

    Counter({'ENFORCED': 481, 'NA': 12, 'WAIVED': 11})

Four of the eight rows had drifted (d2 62/0/1 -> 60/2/1, d3 52/4/7 -> 53/3/7,
d5 62/0/1 -> 61/1/1). Nothing recomputed the table, so the campaign's headline
figure was a number someone typed once — while every cell underneath it was
being recomputed live, which is the whole point of the suite. The README even
carried the command that disproves it, two lines below the table.

Editing the table to say 481 would have bought a fortnight. It is generated
instead, and a freshness test (``programs/tests/test_matrix_63x8_census_freshness.py``)
diffs the regenerated block against the committed one exactly as
``test_programs_index_freshness.py`` does for ``programs/INDEX.md`` — the house
pattern for a derived artefact in this repo.

WHAT IT COMPUTES, and how
-------------------------
Everything comes from ``test_matrix_63x8_coverage``, which is the module that
already asks each dimension for the state of the cells it owns and cross-checks
the answer against pytest's own collection. This program adds no opinion of its
own; it renders.

* ENFORCED / WAIVED / NA per dimension -- ``state_census()``.
* The ENFORCED split -- ``substitution_census()``: for each ENFORCED cell, did
  its predicate run against the step's OWN mechanism, against a SUBSTITUTED
  stand-in, or is the dimension UNDECLARED? See
  ``matrix_63x8/substitution.py``.

WHAT IT REFUSES
---------------
It refuses to publish a single "enforcing" total.

That total is what the finding was about: dimension 8 substitutes a stand-in
gate for 45 of its 61 ENFORCED cells, discloses it honestly in its own
docstring, and the disclosure died at the moment eight rows were added up. So
the ENFORCED column is printed SPLIT, always, and the headline states the
genuinely-enforcing figure as a FLOOR with the undeclared remainder named
beside it rather than absorbed into it.

It also refuses to stamp a timestamp into the block. A generated artefact that
changes on every run cannot be diffed for drift, so ``--check`` would be
meaningless the day it was needed.

Run::

    python3 tools/gen_matrix_63x8_census.py           # rewrite the block
    python3 tools/gen_matrix_63x8_census.py --check   # exit 1 on drift
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
README = PLUGIN_ROOT / "programs" / "tests" / "matrix_63x8" / "README.md"

BEGIN = ("<!-- BEGIN GENERATED CENSUS — tools/gen_matrix_63x8_census.py — "
         "DO NOT EDIT BY HAND -->")
END = "<!-- END GENERATED CENSUS -->"


def _load():
    """Import the coverage meta-test with the plugin's own import posture.

    ``PYTEST_DISABLE_PLUGIN_AUTOLOAD`` matches the suite's documented invocation
    (a stray third-party pytest plugin otherwise breaks the subprocess
    collection ``state_census()`` depends on).
    """
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    for p in (PLUGIN_ROOT / "programs" / "tests", PLUGIN_ROOT / "programs"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    import test_matrix_63x8_coverage as CV  # noqa: E402
    from matrix_63x8 import substitution as SUB  # noqa: E402
    from matrix_63x8.cells import (  # noqa: E402
        DIMENSIONS, DIMENSION_NAMES, DIMENSION_QUESTIONS,
    )
    return CV, SUB, DIMENSIONS, DIMENSION_NAMES, DIMENSION_QUESTIONS


def census_rows() -> Tuple[List[Dict], Dict[str, int]]:
    """``([per-dimension row], totals)`` recomputed from the live suite."""
    CV, SUB, DIMENSIONS, NAMES, QUESTIONS = _load()
    states = CV.state_census()
    subs = CV.substitution_census()
    rows: List[Dict] = []
    for dim in DIMENSIONS:
        per = [v for (s, d), v in states.items() if d == dim]
        buckets = [v for (s, d), v in subs.items() if d == dim]
        rows.append({
            "dim": dim,
            "name": NAMES[dim],
            "question": QUESTIONS[dim],
            "own": buckets.count(SUB.OWN_MECHANISM),
            "substituted": buckets.count(SUB.SUBSTITUTED),
            "undeclared": buckets.count(SUB.UNDECLARED_BUCKET),
            "enforced": per.count("ENFORCED"),
            "waived": per.count("WAIVED"),
            "na": per.count("NA"),
        })
    totals = {k: sum(r[k] for r in rows)
              for k in ("own", "substituted", "undeclared",
                        "enforced", "waived", "na")}
    totals["cells"] = len(states)
    return rows, totals


def render(rows: List[Dict], totals: Dict[str, int]) -> str:
    """The generated block, marker to marker. No timestamp: see WHAT IT REFUSES."""
    out: List[str] = [BEGIN, ""]
    out.append(
        f"**{totals['cells']} cells: {totals['enforced']} ENFORCED, "
        f"{totals['waived']} WAIVED, {totals['na']} NA.**")
    out.append("")
    out.append(
        f"`ENFORCED` is published SPLIT, because it is not one thing. It means "
        f"a live predicate ran and passed; it does not say WHAT it ran against, "
        f"and that turns out to be three different answers:")
    out.append("")
    out.append(
        f"* **{totals['own']}** — measured against the step's OWN mechanism. "
        f"This is the only figure that means what \"enforcing\" sounds like, "
        f"and it is a floor: the two rows below are not evidence against it, "
        f"they are the part nobody has evidence for.")
    out.append(
        f"* **{totals['substituted']}** — measured against a SUBSTITUTED "
        f"stand-in. The predicate runs and passes; what it exercises is not "
        f"the mechanism the cell is named after. Each one carries a disclosure "
        f"from the module that owns it.")
    out.append(
        f"* **{totals['undeclared']}** — in dimensions that have not answered "
        f"the question at all. NOT counted as clean: UNDECLARED is a state, "
        f"not a synonym for \"own mechanism\". See `substitution.py`, "
        f"\"WHY UNDECLARED IS A STATE AND NOT A DEFAULT\".")
    out.append("")
    out.append(
        f"The {totals['waived']} WAIVED and {totals['na']} NA cells are not "
        f"enforcing anything and enter none of those columns. There is "
        f"deliberately no single \"enforcing\" total to quote.")
    out.append("")
    out.append("| dim | question | ENFORCED: own | ENFORCED: substituted "
               "| ENFORCED: undeclared | WAIVED | NA |")
    out.append("|-----|----------|--------------:|----------------------:"
               "|---------------------:|-------:|---:|")
    for r in rows:
        out.append(
            f"| {r['dim']} | `{r['name']}` — {r['question']} "
            f"| {r['own']} | {r['substituted']} | {r['undeclared']} "
            f"| {r['waived']} | {r['na']} |")
    out.append(
        f"| **total** | | **{totals['own']}** | **{totals['substituted']}** "
        f"| **{totals['undeclared']}** | **{totals['waived']}** "
        f"| **{totals['na']}** |")
    out.append("")
    out.append("Regenerate (never edit this block by hand, and never quote it "
               "without re-running):")
    out.append("")
    out.append("```")
    out.append("python3 tools/gen_matrix_63x8_census.py          # rewrite")
    out.append("python3 tools/gen_matrix_63x8_census.py --check  # exit 1 on drift")
    out.append("```")
    out.append("")
    out.append(END)
    return "\n".join(out)


def splice(text: str, block: str) -> str:
    """Replace the marked block, or raise if the markers are gone."""
    start = text.find(BEGIN)
    stop = text.find(END)
    if start < 0 or stop < 0 or stop < start:
        raise SystemExit(
            f"{README}: generated-census markers not found (looked for\n"
            f"  {BEGIN}\n  {END}\n). A hand edit that removed them would make "
            f"this generator silently write nothing, so it refuses instead.")
    return text[:start] + block + text[stop + len(END):]


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed block would change (CI mode)")
    ap.add_argument("--out", default=str(README),
                    help=f"README to rewrite (default {README})")
    args = ap.parse_args(argv)

    rows, totals = census_rows()

    # A PASS must say how much it examined (vibe-ic#447). A census rendered over
    # zero cells matches an empty table trivially, and every count below would
    # read 0 without a single assertion firing.
    if not rows or not totals["cells"]:
        sys.stderr.write(
            f"NOTHING_SCANNED: the live census produced {len(rows)} dimension "
            f"row(s) over {totals.get('cells', 0)} cell(s) — this is NOT a "
            f"pass. Check that the eight dimension modules import and that "
            f"pytest can collect them.\n")
        return 2

    path = Path(args.out)
    text = path.read_text(encoding="utf-8")
    updated = splice(text, render(rows, totals))

    if args.check:
        if updated != text:
            sys.stderr.write(
                f"{path} census block is stale; re-run "
                f"`python3 tools/gen_matrix_63x8_census.py`\n")
            return 1
        print(f"[PASS] 63x8 census fresh: {totals['cells']} cells over "
              f"{len(rows)} dimensions; ENFORCED own={totals['own']} "
              f"substituted={totals['substituted']} "
              f"undeclared={totals['undeclared']}; "
              f"WAIVED={totals['waived']} NA={totals['na']}.")
        return 0

    if updated == text:
        print(f"no change ({totals['cells']} cells)")
        return 0
    path.write_text(updated, encoding="utf-8")
    print(f"wrote {path}: ENFORCED own={totals['own']} "
          f"substituted={totals['substituted']} "
          f"undeclared={totals['undeclared']}; "
          f"WAIVED={totals['waived']} NA={totals['na']}; "
          f"{totals['cells']} cells.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
