#!/usr/bin/env python3
"""prose_polarity_census.py — how many prose extractors do NOT consult polarity,
counted with a predicate sharper than the gate's, and never blocking on it.

WHY THIS EXISTS SEPARATELY FROM THE GATE
========================================
`prose_polarity_consulted_check` refuses: a new polarity-blind extractor fails
CI, and its debt register `prose_polarity_baseline.json` MAY ONLY SHRINK. That
rule is right and it is also what seals the gate against its own improvement.

Its `_writes_a_declared_value` misses two spellings. A match bound by a `for`
TARGET never enters `_match_derived_names`, which walks only `ast.Assign`; and
`out.setdefault(KEY, set()).add(VALUE)` is read for `setdefault`'s DEFAULT and
not for the value pushed into the container it returns. Measured on the corpus
this ships in:

    the gate's own census                     : 213   (= its baseline)
    + matches bound by a `for` target         : 240   (27 more)
    + setdefault(...).add(...) as a write     : 232   (19 more)
    both                                      : 259   (46 more)

Sharpening the GATE would therefore fail CI on 46 extractors that predate the
change, and they cannot be recorded, because the register may only shrink. A
branch that fixes one blind extractor and blocks the tree on forty-six is not a
fix; it is the original finding multiplied.

So the sharper predicate lives here, as a CENSUS: it records the debt and it
NEVER refuses. The gate keeps the power to refuse and keeps its narrower
predicate; nothing is dropped and nothing is weakened. When one of the 46 is
repaired this number falls, and the fall is the evidence.

NOT WIRED, DELIBERATELY. Wiring is the gatekeeper's decision, and a census
wired as blocking would become the thing it was built to avoid. If it is wired
at all it belongs on a tolerant wrapper, and `test_the_census_is_not_wired_as_
blocking` fails if it ever reaches a plain `run `.

ONE VOCABULARY. The predicates are IMPORTED from the gate, never copied: three
private copies of a negation vocabulary is the defect #712 exists to answer, and
a census that re-implemented `_searches_prose` would drift from the thing that
actually decides the census.

EXIT CODES
==========
    0  the corpus was read and the census is printed. ALWAYS 0 when it could
       look, however large the number -- this records debt, it does not refuse.
    2  UNDETERMINED: it could not look, and the line NAMES what it could not
       read. Never a finding about the tree.
    3  the command line was rejected.

USAGE
-----
    prose_polarity_census.py [--programs DIR] [--json OUT]
    --json -   puts the report document on stdout and the human report on
               stderr, the spelling 34 programs in this corpus share.

--json, AND WHAT IT CARRIES
---------------------------
    tool                 this program's name
    corpus               what was SCANNED: {"programs": P, "unreadable": U}
    gate_census          what the gate's own predicate finds (its baseline size)
    census               what the sharper predicate finds
    newly_visible        the difference, named -- the debt this file exists for
    unreadable           sources that would not parse: "<name>: <reason>"
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import prose_polarity_consulted_check as _gate

#: Captured at import, BEFORE anything can patch the module attribute.
_GATE_DERIVED_NAMES = _gate._match_derived_names

TOOL = "prose_polarity_census"
RC_OK, RC_UNDETERMINED, RC_USAGE = 0, 2, 3


def _exempt() -> Set[str]:
    """The gate's own exemption register, read and never extended here.

    A census that could exempt would be a register with two authors, and the
    second one is always the one in a hurry."""
    reg = getattr(_gate, "_NOT_PROSE", {})
    return set(reg) if isinstance(reg, dict) else set(reg or ())


def derived_names(fn: ast.AST) -> Set[str]:
    """The gate's derived-match names, PLUS matches bound by a `for` target.

    `_match_derived_names` walks `ast.Assign` only, so `for m in RE.finditer(s)`
    never enters it and every write derived from `m` is invisible. Widening it
    is the first of the two spellings this census exists to see."""
    names = set(_GATE_DERIVED_NAMES(fn))   # the ORIGINAL, never the
    #                                       patched attribute: calling
    #                                       through the module here
    #                                       recurses forever once this
    #                                       function is installed as it
    for n in ast.walk(fn):
        if (isinstance(n, ast.For) and isinstance(n.target, ast.Name)
                and isinstance(n.iter, ast.Call)
                and getattr(n.iter.func, "attr", "") == "finditer"):
            names.add(n.target.id)
    return names


def writes_a_declared_value(fn: ast.AST) -> bool:
    """The gate's write test, PLUS `container.setdefault(K, set()).add(V)`.

    The gate reads `setdefault`'s DEFAULT argument, which is the empty set, and
    not the value pushed into the container it returns -- so the whole
    accumulate-into-a-set idiom writes a declared value invisibly."""
    if _gate._writes_a_declared_value(fn):
        return True
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add"
                and isinstance(n.func.value, ast.Call)
                and getattr(n.func.value.func, "attr", "") == "setdefault"):
            return True
    return False


def blind_in(tree: ast.Module, stem: str, *, sharp: bool) -> List[str]:
    """`[stem::fn]` for every extractor in one module that consults nothing."""
    aliases = _gate._aliases(tree)
    writes = writes_a_declared_value if sharp else _gate._writes_a_declared_value
    out: List[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        if not _gate._searches_prose(fn):
            continue
        if not writes(fn):
            continue
        if _gate._consults_polarity(fn, aliases):
            continue
        out.append(f"{stem}::{fn.name}")
    return out


def census_of(programs: Path) -> Tuple[List[str], List[str], List[str]]:
    """`(sharp, gate_only, unreadable)` over a directory of programs.

    THE `for`-TARGET WIDENING IS INSTALLED, NOT MERELY DEFINED. The gate's
    `_writes_a_declared_value` calls `_match_derived_names` itself, so a wider
    version has to replace the one it calls -- defining `derived_names` and
    passing it nowhere left it dead, and the census reported 19 newly visible
    instead of 46 while looking exactly as though it worked. Scoped to the sharp
    pass and restored in `finally`, because a module attribute left patched is
    the next reader's mystery."""
    exempt = _exempt()
    trees: List[Tuple[str, ast.Module]] = []
    unreadable: List[str] = []
    for p in sorted(programs.glob("*.py")):
        try:
            trees.append((p.stem,
                          ast.parse(p.read_bytes().decode("utf-8",
                                                          errors="replace"))))
        except SyntaxError as e:
            unreadable.append(f"{p.name}: line {e.lineno}: {e.msg}")
        except OSError as e:
            unreadable.append(f"{p.name}: {e.strerror or e}")

    narrow = [n for stem, t in trees
              for n in blind_in(t, stem, sharp=False) if n not in exempt]

    original = _gate._match_derived_names
    try:
        _gate._match_derived_names = derived_names
        sharp = [n for stem, t in trees
                 for n in blind_in(t, stem, sharp=True) if n not in exempt]
    finally:
        _gate._match_derived_names = original
    return sorted(sharp), sorted(narrow), unreadable


def main(argv: List[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        prog=TOOL, description="census of prose extractors that do not consult "
                               "polarity, with a predicate sharper than the gate's")
    ap.add_argument("--programs", type=Path, default=here)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if not args.programs.is_dir():
        print(f"USAGE_ERROR: {TOOL}: --programs {args.programs} is not a "
              f"directory", file=sys.stderr)
        return RC_USAGE
    if args.json is not None and str(args.json) != "-" and args.json.is_dir():
        print(f"USAGE_ERROR: {TOOL}: --json {args.json} is a directory",
              file=sys.stderr)
        return RC_USAGE

    sources = sorted(args.programs.glob("*.py"))
    sharp, narrow, unreadable = census_of(args.programs)
    newly = sorted(set(sharp) - set(narrow))

    report: Dict[str, object] = {
        "tool": TOOL,
        "corpus": {"programs": len(sources), "unreadable": len(unreadable)},
        "gate_census": len(narrow),
        "census": len(sharp),
        "newly_visible": newly,
        "unreadable": unreadable,
    }
    to_stderr = False
    if args.json is not None:
        if str(args.json) == "-":
            print(json.dumps(report, indent=2))
            to_stderr = True
        else:
            try:
                args.json.parent.mkdir(parents=True, exist_ok=True)
                args.json.write_text(json.dumps(report, indent=2) + "\n",
                                     encoding="utf-8")
            except OSError as e:
                print(f"USAGE_ERROR: {TOOL}: --json {args.json} could not be "
                      f"written: {e.strerror or e}", file=sys.stderr)
                return RC_USAGE
    out = sys.stderr if to_stderr else sys.stdout

    if not sources:
        print(f"[CANNOT DETERMINE] {TOOL}: {args.programs} holds no program at "
              f"all, so this is not a statement about any tree", file=out)
        return RC_UNDETERMINED

    for u in unreadable:
        print(f"  [UNPARSED] {u} — not examined, so it is not in the count "
              f"below", file=out)
    for n in newly:
        print(f"  [DEBT] {n} — reads prose, writes a declared value and "
              f"consults no polarity. Invisible to the gate because of how the "
              f"write is SPELLED, not because it is safe", file=out)
    print(f"[CENSUS] {TOOL}: {len(sharp)} polarity-blind extractor(s) under the "
          f"sharper predicate, {len(narrow)} under the gate's own, so "
          f"{len(newly)} the gate cannot see [{len(sources)} program(s) "
          f"SCANNED; {len(unreadable)} NOT examined because they would not "
          f"parse]. THIS RECORDS DEBT AND NEVER REFUSES.", file=out)
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
