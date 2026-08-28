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

Nor is a CONTENT-TYPE SNIFF. This rule is about a search for something an
AUTHOR WROTE, where a miss is reported as "nothing was declared". A sniff asks
what KIND of bytes these are — `b"\x00" in data[:8192]`, git's own text/binary
heuristic — and its miss means "probably text", the fallback, never a claim
about anybody. There is no declaration in the picture for a window to falsify,
so the bound there IS the heuristic and not a truncation of one. The separator
is structural and is stated in `_is_byte_class_probe`: a needle that is a
`bytes` literal with no printable byte in it cannot be a declaration.

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


def _module_int_constants(tree: ast.AST) -> Dict[str, int]:
    """Module-level `NAME = <int literal>` bindings this rule may resolve.

    WHY A SAME-NODE PREDICATE IS NOT ENOUGH (measured 2026-08-22). This rule
    read the upper bound as an `ast.Constant` and nothing else, so
    `text[:DECL_WINDOW_BYTES]` — behaviourally IDENTICAL to `text[:4000]` — was
    lexically invisible to it. Two agents found the same 4000-byte truncation
    on the same day; one recorded the site as debt under a may-only-shrink
    inventory, the other extracted the number into a NAMED constant so two
    copies of it could not drift. Both repairs are right, and composed they
    turned the detector blind: the window was still 4000 bytes and the row
    recording it matched nothing. A rule defeated by extract-a-constant is a
    rule that gets quieter every time the tree gets tidier.

    CONSERVATIVE ON PURPOSE — a name resolves only if it is bound EXACTLY ONCE
    anywhere in the module and that one binding is a module-level integer
    literal. A name that is also a parameter, a loop variable, an import, an
    `except ... as`, a re-binding or an `AugAssign` is not resolved at all,
    because this rule reports a size to a reader and a size it inferred from
    the wrong binding would be worse than the blindness it replaces. `True` and
    `False` are `int` in Python and are excluded: a flag is not a window.
    """
    bound: Dict[str, int] = {}

    def seen(name: str) -> None:
        bound[name] = bound.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            seen(node.id)
        elif isinstance(node, ast.arg):
            seen(node.arg)
        elif isinstance(node, ast.alias):
            seen((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            seen(node.name)

    literal: Dict[str, int] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        n = _int_literal(value)
        if n is None:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                literal[t.id] = n
    return {k: v for k, v in literal.items() if bound.get(k) == 1}


def _int_literal(node: Optional[ast.AST]) -> Optional[int]:
    """The integer a node IS, or None. `True`/`False` are not integers here."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return node.value
    return None


def _as_int(node: Optional[ast.AST], consts: Dict[str, int]) -> Optional[int]:
    """The integer a bound EVALUATES to: a literal, or a resolvable NAME."""
    n = _int_literal(node)
    if n is not None:
        return n
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _window_bound(node: ast.Subscript,
                  consts: Optional[Dict[str, int]] = None
                  ) -> Optional[Tuple[str, int]]:
    """('head'|'tail', N) when this subscript is a constant-size slice.

    `consts` is the module's resolvable `NAME = <int>` table; omitted, the rule
    reads literals only, which is what it did before `_module_int_constants`.
    """
    consts = consts or {}
    sl = node.slice
    if not isinstance(sl, ast.Slice) or sl.step is not None:
        return None
    lo, hi = sl.lower, sl.upper
    hi_n = _as_int(hi, consts)
    if lo is None and hi_n is not None and hi_n >= _WINDOW_FLOOR:
        return "head", hi_n
    if hi is None and isinstance(lo, ast.UnaryOp) and \
            isinstance(lo.op, ast.USub):
        lo_n = _as_int(lo.operand, consts)
        if lo_n is not None and lo_n >= _WINDOW_FLOOR:
            return "tail", lo_n
    return None


def _searched_here(parent_map: Dict[int, ast.AST], node: ast.AST
                   ) -> Optional[Tuple[str, Optional[ast.AST]]]:
    """(how the sliced value is SEARCHED, what is searched FOR), or None.

    The second element is the NEEDLE — the thing whose presence the search is
    deciding. It is what tells a declaration search apart from a content-type
    sniff; see `_is_byte_class_probe`.
    """
    cur = node
    for _ in range(4):
        par = parent_map.get(id(cur))
        if par is None:
            return None
        # `marker in <slice>`
        if isinstance(par, ast.Compare) and any(
                isinstance(o, (ast.In, ast.NotIn)) for o in par.ops):
            if cur in par.comparators:
                return "`in` membership", par.left
        # `<slice>.find(...)`
        if isinstance(par, ast.Attribute) and par.attr in _SEARCH_METHODS \
                and par.value is cur:
            call = parent_map.get(id(par))
            needle = (call.args[0] if isinstance(call, ast.Call) and call.args
                      else None)
            return f".{par.attr}()", needle
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
                    return f"re.{attr}()", par.args[0]
                if par.args and par.args[0] is cur and isinstance(
                        f, ast.Attribute) and not (
                        isinstance(f.value, ast.Name) and f.value.id == "re"):
                    return f"<compiled pattern>.{attr}()", f.value
            return None
        cur = par
    return None


def _is_byte_class_probe(needle: Optional[ast.AST]) -> bool:
    """Is this search a CONTENT-TYPE SNIFF rather than a DECLARATION SEARCH?

    WHAT DISTINGUISHES THEM (2026-08-28 — state it here so the next reader does
    not re-derive it). A DECLARATION SEARCH looks for something an AUTHOR WROTE
    — `ENFORCEMENT:`, `FATAL`, a required statement — and a miss is a claim
    about that author: "nothing was declared". That claim is what this rule
    protects, and it is what a window can falsify.

    A CONTENT-TYPE SNIFF asks what KIND of bytes these are. Its needle is not a
    word; it is a byte class, and a miss is not a claim about anybody. `b"\x00"
    in data[:8192]` is exactly git's own text/binary heuristic: no NUL in the
    first 8 KiB means "treat this as text", the FALLBACK — never "the author
    declared nothing". Moving the window cannot turn an author's declaration
    into an absence here, because there is no declaration in the picture. The
    bound is the heuristic, not a truncation of one.

    THE STRUCTURAL SEPARATOR. A declaration is text a human typed, so it always
    carries at least one printable character. A needle that is a `bytes` literal
    with NO printable ASCII byte in it cannot be a declaration in any encoding a
    person writes — it can only be a byte-class probe. That is the whole rule,
    and it cannot hide a real declaration search: make the needle a word and
    this returns False.

    Deliberately NARROW. A magic number that IS printable (`b"%PDF"`,
    `b"\x89PNG"`) is not exempted here — it stays a finding until someone
    measures one, which is the safe direction for a rule whose job is to refuse.
    """
    if isinstance(needle, (ast.Tuple, ast.List, ast.Set)):
        return bool(needle.elts) and all(
            _is_byte_class_probe(e) for e in needle.elts)
    if not isinstance(needle, ast.Constant):
        return False
    v = needle.value
    if not isinstance(v, (bytes, bytearray)) or not v:
        return False
    return not any(0x20 <= b <= 0x7E for b in v)


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
    sniffs = 0
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
            consts = _module_int_constants(tree)
            rel = p.relative_to(root).as_posix()
            for n in ast.walk(tree):
                if not isinstance(n, ast.Subscript):
                    continue
                w = _window_bound(n, consts)
                if w is None:
                    continue
                windows += 1
                hit = _searched_here(pm, n)
                if hit is None:
                    continue
                how, needle = hit
                # A content-type sniff is not a declaration search: its miss is
                # "probably text", never "the author declared nothing".
                if _is_byte_class_probe(needle):
                    sniffs += 1
                    continue
                findings.append({"file": rel, "line": n.lineno,
                                 "side": w[0], "size": w[1],
                                 "sliced": _sliced_name(n), "searched_by": how})
    return findings, {"modules_parsed": parsed,
                      "constant_size_windows": windows,
                      "content_type_sniffs": sniffs,
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
    print(f"  content-type sniffs:       {denom['content_type_sniffs']}")
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
