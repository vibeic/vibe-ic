#!/usr/bin/env python3
"""A marker searched inside a fixed-size slice, and a miss called ABSENCE.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A predicate deciding whether a required declaration is present must search the
WHOLE text. When the search runs over a fixed-size head or tail slice, an
identical declaration reads as ABSENT purely because of where it sits, and the
finding then names the wrong defect: it reports the author as having declared
nothing.

Declared-outside-the-window and absent are different states and must stay
different. The first is a formatting problem; the second is a governance one.

MEASURED, through the real predicate: two programs carrying a byte-identical
declaration line, one at byte 26 and one at byte 5121. A 4000-byte head window
returns `blocking` for the first and `None` for the second — the same
declaration, opposite verdicts, decided by the length of the prose above it.

THE PREDICATE
=============
A finding is a SLICE-THEN-SEARCH site:

  1. a subscript with a constant bound — `text[:N]` or `text[-N:]` — where
     `N >= 100`. Below that the number is an index or a field width, not a
     window; a bound written to limit SIZE is what this rule is about.
  2. whose result is SEARCHED in the same function: as the right operand of
     `in`, as the receiver of `.find` / `.index` / `.startswith` /
     `.endswith`, or as the subject argument of `re.search` / `re.match` /
     `re.findall` / `re.fullmatch`.

The head-slice and the tail-slice shapes are ONE class and both are read. In
both, a bound written to limit size is silently doing the work of a predicate.

WHAT IS NOT A FINDING
=====================
A slice that only feeds OUTPUT — a `print`, a report field, an f-string in a
message — is a display bound and is correct. The rule turns on the slice
reaching a SEARCH, which is the only place a window can change a verdict.

The remedy the rule asks for is not "delete the window". Keep it for display,
and on a miss re-run the same search over the full text, reporting a
declaration found outside the window as its own outcome, naming the byte offset
and the window size — never as absence.

EXIT
====
  0  no slice-then-search site outside the inventory
  1  a NEW one, or a stale inventory row
  2  cannot determine
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_INVENTORY_NAME = "truncated_window_search_inventory.json"

#: Below this a constant bound is an index or a field width, not a window.
_WINDOW_FLOOR = 100

_SEARCH_METHODS = ("find", "rfind", "index", "startswith", "endswith", "count")
_RE_SEARCHES = ("search", "match", "findall", "fullmatch", "finditer", "split")


def _window_bound(node: ast.Subscript) -> Optional[Tuple[str, int]]:
    """('head'|'tail', N) when this subscript is a constant-size slice."""
    sl = node.slice
    if not isinstance(sl, ast.Slice) or sl.step is not None:
        return None
    lo, hi = sl.lower, sl.upper
    if lo is None and isinstance(hi, ast.Constant) and \
            isinstance(hi.value, int) and hi.value >= _WINDOW_FLOOR:
        return "head", hi.value
    if hi is None and isinstance(lo, ast.UnaryOp) and \
            isinstance(lo.op, ast.USub) and isinstance(lo.operand, ast.Constant) \
            and isinstance(lo.operand.value, int) \
            and lo.operand.value >= _WINDOW_FLOOR:
        return "tail", lo.operand.value
    return None


def _searched_here(parent_map: Dict[int, ast.AST], node: ast.AST) -> Optional[str]:
    """How the sliced value is SEARCHED, walking up from the slice."""
    cur = node
    for _ in range(4):
        par = parent_map.get(id(cur))
        if par is None:
            return None
        # `marker in <slice>`
        if isinstance(par, ast.Compare) and cur is par.comparators[0] if \
                (isinstance(par, ast.Compare) and par.comparators) else False:
            if any(isinstance(o, (ast.In, ast.NotIn)) for o in par.ops):
                return "`in` membership"
        if isinstance(par, ast.Compare) and any(
                isinstance(o, (ast.In, ast.NotIn)) for o in par.ops):
            if cur in par.comparators:
                return "`in` membership"
        # `<slice>.find(...)`
        if isinstance(par, ast.Attribute) and par.attr in _SEARCH_METHODS \
                and par.value is cur:
            return f".{par.attr}()"
        # `re.search(pat, <slice>)`
        if isinstance(par, ast.Call):
            f = par.func
            attr = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if attr in _RE_SEARCHES:
                # `re.search(pat, s)` puts the subject second; a COMPILED
                # pattern — `_DECL_RE.search(s)` — puts it first. The known
                # 4000-byte declaration window is the compiled form, and a
                # rule that reads only the module form would miss the very
                # site it was written for.
                if len(par.args) >= 2 and par.args[1] is cur:
                    return f"re.{attr}()"
                if par.args and par.args[0] is cur and isinstance(
                        f, ast.Attribute) and not (
                        isinstance(f.value, ast.Name) and f.value.id == "re"):
                    return f"<compiled pattern>.{attr}()"
            return None
        cur = par
    return None


def _parents(tree: ast.AST) -> Dict[int, ast.AST]:
    out: Dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            out[id(c)] = n
    return out


def _sliced_name(node: ast.Subscript) -> str:
    v = node.value
    if isinstance(v, ast.Name):
        return v.id
    try:
        return ast.unparse(v)[:48]
    except Exception:                            # noqa: BLE001
        return "<expr>"


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    windows = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            # A test asserting over a bounded snippet of its own fixture is an
            # assertion about a local region, not a predicate deciding a
            # verdict over a live population. Twelve of the eighteen sites the
            # first sweep returned were that, and none of them can report an
            # author as having declared nothing.
            if "node_modules" in p.parts or "tests" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                continue
            parsed += 1
            pm = _parents(tree)
            rel = p.relative_to(root).as_posix()
            for n in ast.walk(tree):
                if not isinstance(n, ast.Subscript):
                    continue
                w = _window_bound(n)
                if w is None:
                    continue
                windows += 1
                how = _searched_here(pm, n)
                if how is None:
                    continue
                findings.append({"file": rel, "line": n.lineno,
                                 "side": w[0], "size": w[1],
                                 "sliced": _sliced_name(n), "searched_by": how})
    return findings, {"modules_parsed": parsed,
                      "constant_size_windows": windows,
                      "slice_then_search_sites": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['sliced']}::{f['side']}::{f['size']}"


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] declaration_searched_only_inside_a_"
                  "truncated_window: no repository root. NOT a pass.",
                  file=sys.stderr)
            return 2
        findings, denom = scan(root)
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] declaration_searched_only_inside_a_truncated_"
              f"window: the walk did not complete ({type(exc).__name__}: {exc}). "
              f"NOT a pass.", file=sys.stderr)
        return 2

    print(f"  modules parsed:            {denom['modules_parsed']}")
    print(f"  constant-size windows:     {denom['constant_size_windows']}")
    print(f"  slice-then-search sites:   {denom['slice_then_search_sites']}")
    print(f"  inventory rows applied:    {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} search(es) run over a fixed-size slice:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  {f['sliced']}"
                      f"[{'' if f['side'] == 'head' else '-'}{f['size']}"
                      f"{':' if f['side'] == 'tail' else ''}] searched by "
                      f"{f['searched_by']}")
        print("\n  Keep the window for DISPLAY and search the whole text. On a "
              "miss inside\n  the window, re-run over the full text and report "
              "a marker found outside\n  it as its own outcome, naming the byte "
              "offset — never as absence.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] declaration_searched_only_inside_a_truncated_window: no "
              "search decides a verdict inside a fixed-size slice.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
