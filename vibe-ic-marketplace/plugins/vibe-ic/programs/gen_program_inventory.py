#!/usr/bin/env python3
"""
gen_program_inventory.py — single source of truth for the plugin's PROGRAM counts.

Same pattern as `programs/gen_skill_inventory.py` (skills) and
`mcp-eda/tools/gen_mcp_tool_inventory.py` (MCP tools), for every number the
READMEs state about `programs/`. It writes `PROGRAM_INVENTORY.json` beside
`SKILL_INVENTORY.json`; **that artefact is the number, and a stated count must
read it from there rather than be hand-typed.**

WHY THIS EXISTS
---------------
The plugin's stated MCP tool count is right and its stated program count was
not, and the difference is mechanical rather than editorial: the tool count is
GENERATED, and `MCP_TOOL_INVENTORY.json` says in its own `_comment` "Do NOT
hand-edit; the website tool count must read `total` from here". The program
count had no generator and no gate, so it froze at whatever the tree held on
the day someone last counted it, while the tree kept growing underneath it.

PINNED — measured on 2026-08-19 at commit 397b3f25f, a record of the state that
motivated this file and NOT a claim about any later tree:

    stated in both READMEs        programs/*.py on disk
    917 "deterministic programs"  1178
    888 "catalogued"              1111
    3,737 "programs"              3817   (and that walk counts the test suite,
                                          which the same tree diagram then
                                          counts again as "test files")
    1608 / 2,545 "test files"     2609

`917` was accurate when it was written (73d1efb20, 2026-07-20). Nothing was
wrong with the person who typed it; what was missing is the thing this file
supplies.

EVERY KEY COUNTS A DIFFERENT THING, AND THAT IS THE POINT
----------------------------------------------------------
Two defensible counts of "the programs" differ by more than a factor of two,
and a bare integer in prose does not say which one a reader is holding. That
ambiguity is what let the drift survive: 544, 577, 1111, 1178, 2609 and 3817
are all true statements about `programs/` at the same instant, so any one of
them could be defended and no reader ever had grounds to call one wrong.

Each key below therefore ships its own one-sentence definition in the emitted
`definitions` block, and prose that quotes a number is expected to name the key
it quotes. `stated_count_drift_check.py` is the gate that enforces the match.

Keys:

  programs_top_level    `programs/*.py` — the NON-recursive glob: every
                        top-level module, helpers (`_*.py`) and deprecation
                        shims included. This is the headline "deterministic
                        programs" number.
  programs_catalogued   the subset `programs/INDEX.md` lists (helpers and
                        deprecation shims excluded). Read from INDEX.md's own
                        generated Stats line — INDEX.md is produced by
                        `tools/gen_programs_index.py` and a freshness test
                        already fails on drift, so re-deriving it here would
                        add a second, slower, disagreeing authority. It is
                        also the only one of these figures obtainable on the
                        flattened plugin cache, where the repo-root `tools/`
                        are absent.
  checkers_top_level    top-level `*_check.py` + `*_audit.py` + `*_lint.py`.
                        The "~600 checkers" figure. A DIFFERENT count from
                        programs_top_level, not a correction of it.
  check_suffix_only     top-level `*_check.py` alone.
  py_files_recursive    every `*.py` anywhere under `programs/`, including
                        `tests/` and the sub-packages. Counts the test suite;
                        must not be labelled "programs".
  test_files            `test_*.py` anywhere under `programs/tests/`.
  mcp_test_files        `test_*.py` anywhere under `mcp-eda/test/`.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
The 1178 filenames. `programs/INDEX.md` already enumerates them under its own
freshness gate, so a second copy would be a second authority to keep in step
and a merge conflict on every PR that adds a program. `programs_sha256` pins
the sorted top-level name list instead: it changes exactly when the population
changes, and INDEX.md names what changed.

Usage:
  python3 programs/gen_program_inventory.py            # regenerate + print
  python3 programs/gen_program_inventory.py --check    # verify committed == tree
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent        # plugins/vibe-ic/
PROGRAMS = PLUGIN / "programs"
INDEX_MD = PROGRAMS / "INDEX.md"
MCP_TEST = PLUGIN / "mcp-eda" / "test"
OUT = PLUGIN / "PROGRAM_INVENTORY.json"

#: The Stats line `tools/gen_programs_index.py` renders into INDEX.md.
_INDEX_TOTAL_RE = re.compile(
    r"^\-\s+\*\*Total programs \(excluding helpers / shims\):\*\*\s+(\d+)\s*$",
    re.MULTILINE,
)

DEFINITIONS = {
    "programs_top_level":
        "programs/*.py — the non-recursive glob; every top-level module, "
        "including helpers (_*.py) and deprecation shims.",
    "programs_catalogued":
        "the subset programs/INDEX.md catalogues (helpers and deprecation "
        "shims excluded); read from INDEX.md's own generated Stats line.",
    "checkers_top_level":
        "top-level *_check.py + *_audit.py + *_lint.py — the checker-shaped "
        "subset of programs_top_level, a different count and not a correction "
        "of it.",
    "check_suffix_only":
        "top-level *_check.py alone.",
    "py_files_recursive":
        "every *.py anywhere under programs/, including tests/ and the "
        "sub-packages; this counts the test suite and is not a program count.",
    "test_files":
        "test_*.py anywhere under programs/tests/.",
    "mcp_test_files":
        "test_*.py anywhere under mcp-eda/test/.",
}


def _index_catalogued() -> int:
    """The catalogued total, read from the generated INDEX.md Stats line.

    RAISES rather than returning a sentinel. A count this file cannot obtain is
    NOT DETERMINED, and a 0 written into the inventory would read as a measured
    zero to every consumer downstream.
    """
    if not INDEX_MD.is_file():
        raise RuntimeError(f"{INDEX_MD} missing — cannot derive programs_catalogued")
    m = _INDEX_TOTAL_RE.search(INDEX_MD.read_text(errors="replace"))
    if not m:
        raise RuntimeError(
            f"{INDEX_MD.name} carries no 'Total programs (excluding helpers / "
            f"shims)' Stats line — tools/gen_programs_index.py changed its "
            f"render and this reader must be updated with it"
        )
    return int(m.group(1))


def discover() -> dict:
    top_level = sorted(p.name for p in PROGRAMS.glob("*.py"))
    checkers = sorted(
        n for n in top_level
        if n.endswith(("_check.py", "_audit.py", "_lint.py"))
    )
    counts = {
        "programs_top_level": len(top_level),
        "programs_catalogued": _index_catalogued(),
        "checkers_top_level": len(checkers),
        "check_suffix_only": sum(1 for n in top_level if n.endswith("_check.py")),
        "py_files_recursive": sum(1 for _ in PROGRAMS.rglob("*.py")),
        "test_files": sum(1 for _ in (PROGRAMS / "tests").rglob("test_*.py")),
        "mcp_test_files": sum(1 for _ in MCP_TEST.rglob("test_*.py")),
    }
    digest = hashlib.sha256("\n".join(top_level).encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "_comment":
            "AUTHORITATIVE program inventory — generated from the tree by "
            "programs/gen_program_inventory.py. Do NOT hand-edit; every stated "
            "program count (READMEs, website, docs) must read its number from "
            "`counts` here, naming the key it quotes, never hand-typed. "
            "`definitions` says what each key counts — they are different "
            "questions with different true answers.",
        "counts": counts,
        "definitions": DEFINITIONS,
        "programs_sha256": digest,
        "programs_enumerated_in": "programs/INDEX.md",
    }


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if committed PROGRAM_INVENTORY.json != tree")
    a = ap.parse_args()
    inv = discover()

    if a.check:
        if not OUT.exists():
            _fail(f"{OUT.name} missing — run without --check to generate")
        committed = json.loads(OUT.read_text())
        drifted = [
            (k, committed.get("counts", {}).get(k), v)
            for k, v in inv["counts"].items()
            if committed.get("counts", {}).get(k) != v
        ]
        if drifted or committed.get("programs_sha256") != inv["programs_sha256"]:
            print("FAIL: program inventory drift. Re-run "
                  "`python3 programs/gen_program_inventory.py`.")
            for k, c, t in drifted:
                print(f"  {k}: committed={c} tree={t}")
            if committed.get("programs_sha256") != inv["programs_sha256"]:
                print("  programs_sha256: the top-level program set changed "
                      "(programs/INDEX.md names which programs)")
            sys.exit(1)
        print(f"OK: program inventory matches the tree — {inv['counts']}")
        sys.exit(0)

    OUT.write_text(json.dumps(inv, indent=2) + "\n")
    print(f"wrote {OUT}")
    for k, v in inv["counts"].items():
        print(f"  {k:22s} = {v}")


if __name__ == "__main__":
    main()
