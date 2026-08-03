#!/usr/bin/env python3
"""A prose extractor that never asks whether the sentence DENIES the value.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHY (vibe-ic#712)
-----------------
It happened twice in one day, in two fields, found by the same activity —
retargeting a design from one process to another:

    #706  pdk_target          "This block is NOT targeted at <PDK>."
                              -> pdk_target = <PDK>, outranking the design's own
                                 labelled declaration three lines below.
    #711  die_area_budget_um  a document saying the old fixed die "has NO
                              meaning here and is REMOVED, not translated"
                              re-declared that exact rectangle as a mandate.

Neither is cosmetic. `die_area_budget_um` sits above `auto` in the phase-3
runner's documented precedence, so the design is hard-sized onto a die belonging
to a different chip — citing the design's own document as the authority. Nothing
warned; the floorplan read as declared rather than inherited.

WHAT IT MEASURES
----------------
Not "is this extractor correct" — that is a semantic question and a program that
guessed would produce confident wrong answers. It asks the structural one the
two defects share:

    a function that SEARCHES prose for a value and WRITES that value into a
    declared field, without ever consulting the polarity vocabulary.

A function is in scope when it both matches prose (a module-level `re` pattern
or an inline `re.search`/`findall` over a text argument) and assigns into a
record. It is CLEAN when it reaches `_prose_polarity` — directly, or through a
local alias of one of its names.

WHY NOT A LINT ON THE FIELD NAMES. Because the field is not the tell. Both
defects were in different fields, in different files, written by different
authors, weeks apart. What they share is the shape.

BASELINE, AND WHY IT MAY ONLY SHRINK
------------------------------------
Extractors that predate the vocabulary are recorded, not failed: failing a
pre-existing pile on day one is how a gate ends up switched off, and this repo
has measured that. Anything NEW fails from the first run.

chip-AGNOSTIC: pure AST structure. No chip, PDK, vendor or field literal.

USAGE
-----
    prose_polarity_consulted_check.py [--root .] [--json OUT] [--write-baseline]

    exit 0 = no NEW polarity-blind extractor, and the baseline has not grown
    exit 1 = a new one, or the baseline grew (BLOCKING)
    exit 2 = could not be determined — never a vacuous pass
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_BASELINE_NAME = "prose_polarity_baseline.json"
_POLARITY_MODULE = "_prose_polarity"
#: The names that ARE consulting polarity. A local alias of any of them counts —
#: both existing callers import under their own name, which is fine.
_POLARITY_NAMES = {
    "is_denied", "NEGATION_RE", "DENIAL_CORE_RE", "DENIAL_RETIRED_RE",
    "blank_bracketed", "sentence_scope",
}
#: Calls that read prose.
_SEARCH_ATTRS = {"search", "findall", "finditer", "match", "fullmatch"}


def _aliases(tree: ast.Module) -> Set[str]:
    """Local names bound to something from the polarity module."""
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(_POLARITY_MODULE):
            for a in n.names:
                out.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.endswith(_POLARITY_MODULE):
                    out.add(a.asname or a.name)
    return out


def _searches_prose(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in _SEARCH_ATTRS:
                return True
    return False


def _match_derived_names(fn: ast.AST) -> Set[str]:
    """Locals bound to a regex match or to text taken out of one.

    `m = RE.search(t)`, `hits = RE.findall(t)`, `val = m.group(1)`, and one hop
    onward (`val = raw.strip()`), which is how both real defects were written."""
    out: Set[str] = set()
    for _ in range(3):                       # transitive, cheaply bounded
        grew = False
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                continue
            t = n.targets[0]
            if not isinstance(t, ast.Name):
                continue
            for sub in ast.walk(n.value):
                hit = (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                       and sub.func.attr in (_SEARCH_ATTRS | {"group", "groups", "groupdict"})) \
                    or (isinstance(sub, ast.Name) and sub.id in out)
                if hit and t.id not in out:
                    out.add(t.id); grew = True
                    break
        if not grew:
            break
    return out


def _writes_a_declared_value(fn: ast.AST) -> bool:
    """Does it write THE MATCHED VALUE into a record?

    NARROWED, and the narrowing is the work. "Any subscript assignment" caught
    592 functions — every one that greps something and fills a dict — which is
    noise, not disclosure, and a baseline of 592 records nothing. Both real
    defects have a tighter shape: the value taken OUT of the prose is the value
    written IN as the declaration. That is what is asked here.
    """
    derived = _match_derived_names(fn)
    if not derived:
        return False
    for n in ast.walk(fn):
        vals = []
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript)
                                             for t in n.targets):
            vals = [n.value]
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("setdefault", "update"):
            vals = list(n.args[1:]) + [k.value for k in n.keywords]
        for v in vals:
            for sub in ast.walk(v):
                if isinstance(sub, ast.Name) and sub.id in derived:
                    return True
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                        and sub.func.attr in ("group", "groups", "groupdict"):
                    return True
    return False


def _consults_polarity(fn: ast.AST, aliases: Set[str]) -> bool:
    ok = _POLARITY_NAMES | aliases
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id in ok:
            return True
        if isinstance(n, ast.Attribute) and n.attr in ok:
            return True
    return False


def scan(root: Path) -> List[str]:
    """`module::function` for every polarity-blind prose extractor."""
    found: List[str] = []
    for p in sorted((root / "programs").glob("*.py")):
        if p.stem.startswith("test_") or p.stem == Path(__file__).stem:
            continue
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        al = _aliases(tree)
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (_searches_prose(n) and _writes_a_declared_value(n)):
                continue
            if _consults_polarity(n, al):
                continue
            found.append(f"{p.stem}::{n.name}")
    return sorted(set(found))


def _load(p: Path) -> Optional[List[str]]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = d.get("known") if isinstance(d, dict) else d
    return sorted(v) if isinstance(v, list) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    if not (root / "programs").is_dir():
        print(f"[CANNOT DETERMINE] prose_polarity_consulted: no programs/ under "
              f"{root}. NOT a pass.", file=sys.stderr)
        return 2

    now = scan(root)
    bpath = Path(a.baseline) if a.baseline else root / "programs" / _BASELINE_NAME

    if a.write_baseline:
        prev = _load(bpath) or []
        if prev and len(now) > len(prev):
            print(f"[FAIL] refusing to write a baseline that GREW "
                  f"({len(prev)} -> {len(now)}). It is a debt register, not a "
                  f"waiver list.", file=sys.stderr)
            return 1
        bpath.write_text(json.dumps(
            {"_comment": "Prose extractors that never consult the polarity of "
                         "the sentence they read (vibe-ic#712). MAY ONLY "
                         "SHRINK. A denied value published as a declaration is "
                         "how a design gets hard-sized onto another chip's die "
                         "while citing its own document as the authority.",
             "known": now}, indent=2) + "\n")
        print(f"wrote {bpath} ({len(now)} recorded)")
        return 0

    base = _load(bpath)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"polarity_blind": now, "baseline": base}, indent=2) + "\n")
    if base is None:
        print(f"[CANNOT DETERMINE] prose_polarity_consulted: no readable "
              f"baseline at {bpath}; {len(now)} extractor(s) are polarity-blind "
              f"and there is nothing to compare against. NOT a pass.",
              file=sys.stderr)
        return 2

    new = sorted(set(now) - set(base))
    gone = sorted(set(base) - set(now))
    print(f"  prose extractors that write a declared value: polarity-blind "
          f"{len(now)} (baseline {len(base)})")
    if gone:
        print(f"  [NOTE] baseline shrank — now polarity-aware: "
              f"{', '.join(gone[:6])}. Re-run with --write-baseline.")
    if new:
        print(f"\n[FAIL] {len(new)} prose extractor(s) read a value out of a "
              f"sentence and write it as a declaration without asking whether "
              f"the sentence DENIES it:")
        for n in new:
            print(f"   {n}")
        print(f"\n  Consult `{_POLARITY_MODULE}` — one vocabulary, so the next "
              f"field does not\n  have to learn this the way `pdk_target` and "
              f"`die_area_budget_um` did.")
        return 1
    if len(now) > len(base):
        print(f"\n[FAIL] the set grew {len(base)} -> {len(now)} with no new "
              f"name — the baseline is stale.")
        return 1
    print(f"[PASS] prose_polarity_consulted: no extractor newly reads a value "
          f"without its polarity.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
