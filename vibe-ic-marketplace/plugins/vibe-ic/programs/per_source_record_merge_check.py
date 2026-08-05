#!/usr/bin/env python3
"""Find per-source record merges whose verdict is decided by filename order.

    for src in sources:
        acc.update(parse_one(src))        # last wins; `sources` is sorted()

When ``parse_one`` returns ``{key: RECORD}`` and one source describes a key
EMPTILY, ``update`` lets that emptiness overwrite another source's content. The
survivor is then chosen by the order the files happened to sort in. A gate
downstream reads the resulting absence as a measurement and finds less than
there is -- on a blocking gate, a false PASS.

The general form of a defect measured on a real post-route project: six LEFs
declared one macro, five with 61-65 obstruction rectangles and one with none;
``sorted()`` put the empty one last, so it won, and the gate passed a layout
with 28 real crossings. Renaming a file flipped the verdict.

WHAT THIS PROGRAM CAN AND CANNOT DECIDE
---------------------------------------
It CANNOT tell "merging equally-authoritative peer sources" from "layering a
deliberate override" -- both are spelled ``for s in srcs: acc.update(f(s))``,
and the intent lives in the author's head, not in the AST.

It does not need to. What it flags is narrower and is wrong under BOTH intents:
an order dependence that is not stated anywhere. A deliberate override that
relies on last-wins over an EMPTY record is relying on the discovery order too;
it is just relying on it on purpose, undocumented. The fix is the same in both
cases -- route the merge through ``_source_record_merge.merge_source_records``
and state the policy -- so the distinction the program cannot make is also a
distinction it does not have to make.

THE PREDICATE, and why each clause is there
-------------------------------------------
Fires only when ALL of these hold. Every clause removed a class of legitimate
merge from a real sweep of this repo; the counts are the measured ones.

  1. ``ACC.update(CALL(...))`` -- or ``ACC |= CALL(...)``, which is the same
     last-wins merge spelled with one token instead of seven -- with ACC a
     plain local name and, for the call form, one positional argument and no
     keywords. Both spellings are matched because a guard that only knows one
     of them is a guard a one-character edit walks past, and the edit does not
     even have to be deliberate: ``|=`` is what a reader reaches for when
     tidying up.
  2. Lexically inside a ``for``, and CALL mentions the loop target or a name
     assigned from it inside the body. This is what makes it ONE SOURCE PER
     ITERATION rather than a single fixed merge.
  3. ACC is a MAPPING, decided from its binding in the enclosing function
     (``{}``, ``dict()``, ``Dict[...]``/``Mapping``/``Counter`` annotation).
     A ``set`` accumulator merges by UNION -- nothing can be erased -- and a
     ``hashlib`` object is not a merge at all. This clause alone takes 113
     syntactic matches down to 13; the 8 it cannot classify are all hash
     objects and are SKIPPED, because a guard that guesses is worse than one
     that abstains.
  4. The called function's return annotation is ``Dict[K, V]`` (or ``dict``,
     ``Mapping``, ``DefaultDict``, ``OrderedDict``) where **V is itself a
     container** -- Dict/List/Set/Tuple/Mapping/Sequence/Iterable, bare or
     subscripted. This is the clause that separates a RECORD from a SCALAR.
     A scalar value has no "present but empty" state, so a source cannot be
     silent about a key it names, and re-stating the same scalar erases
     nothing. Unannotated, bare ``dict``, or scalar V -> SKIPPED.

Clause 4 is the load-bearing one, so here is what it decided on this repo's own
code rather than in the abstract:

    Dict[str, Dict[str, Any]]   macro obstructions, per-macro OBS ...... FIRES
    Dict[str, Dict[str, str]]   liberty pin directions, per cell ....... FIRES
    Dict[str, Dict[str, str]]   payload bit layouts, per byte .......... FIRES
    Dict[str, str]              flow layer refs; value is a substring of
                                the key, so re-stating it is identity ... skip
    Dict[str, int]              localparam values, subckt terminal
                                counts, mbist params ................... skip

CROSS-MODULE RESOLUTION
-----------------------
``programs/`` is a flat directory imported by module name, so ``import X as au``
followed by ``au.f(...)`` is resolved by reading ``X.py`` from the same root and
reading ``f``'s annotation there. Unresolvable -> SKIPPED, per clause 4.

DELIBERATELY NOT PRESENT: any list of file or function names. A name-based
allow-list outlives its own truth -- it keeps excusing a site long after the
reason stopped applying, and it excuses a new site that copies the name. Every
clause above is a property of the code's shape or of a declared type, so a site
stops being flagged only by actually changing.

THE SWEEP REPORTS ITS OWN FUNNEL, ON PASS AS WELL AS ON FAIL
------------------------------------------------------------
Every run prints how many sites reached each clause. That is not decoration. A
sweep whose every case abstains at clause 1 exits 0 and reads exactly like a
sweep that examined the corpus and found it clean -- the decision point was
never entered, and the exit code cannot tell you so. The funnel can:

    candidates 118 -> source-dependent 47 -> mapping acc 13 -> record-valued 0

says the predicate ran all the way down and 13 real accumulators were examined
by the load-bearing clause. A line reading ``candidates 0`` says the opposite,
in the same exit code, and `test_the_sweep_actually_reaches_its_decision_point`
holds the corpus to the first shape.

Exit codes
----------
    0  no site matched
    1  at least one site matched
    2  bad usage / unreadable root

chip-AGNOSTIC: reads Python source only. No PDK, vendor, process or design
literal appears here or can affect the result.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

RC_CLEAN, RC_FOUND, RC_USAGE = 0, 1, 2

MAPPING, NONMAPPING, UNKNOWN = "mapping", "non-mapping", "unknown"

# Type NAMES, not project names: the container constructors of the language and
# of `typing`. This is an API surface, not an allow-list of sites.
_MAPPING_NAMES = ("dict", "Dict", "DefaultDict", "defaultdict", "OrderedDict",
                  "Counter", "Mapping", "MutableMapping")
_SET_NAMES = ("set", "Set", "frozenset", "FrozenSet", "MutableSet")
_CONTAINER_NAMES = _MAPPING_NAMES + _SET_NAMES + (
    "list", "List", "tuple", "Tuple", "Sequence", "MutableSequence",
    "Iterable", "Collection", "Any")


def _bare(annotation: ast.AST) -> str:
    """Left-most identifier of a possibly dotted / subscripted annotation."""
    node = annotation
    if isinstance(node, ast.Subscript):
        node = node.value
    while isinstance(node, ast.Attribute):
        node = node.value          # typing.Dict -> Dict handled below
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Attribute):
        return annotation.value.attr
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.split("[")[0].split(".")[-1]
    return ""


# ---------------------------------------------------------------- clause 3 --
def _construct_kind(value: ast.AST) -> str:
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return MAPPING
    if isinstance(value, (ast.Set, ast.SetComp)):
        return NONMAPPING
    if isinstance(value, ast.Call):
        name = _bare(value.func) if not isinstance(value.func, ast.Name) else value.func.id
        if isinstance(value.func, ast.Attribute):
            name = value.func.attr
        if name in _MAPPING_NAMES:
            return MAPPING
        if name in _SET_NAMES:
            return NONMAPPING
    return UNKNOWN


def _annotation_kind(annotation: Optional[ast.AST]) -> str:
    if annotation is None:
        return UNKNOWN
    name = _bare(annotation)
    if name in _MAPPING_NAMES:
        return MAPPING
    if name in _SET_NAMES:
        return NONMAPPING
    return UNKNOWN


def accumulator_kind(scope: ast.AST, name: str) -> str:
    """MAPPING only when every binding of ``name`` in ``scope`` agrees.

    Disagreement or no evidence -> UNKNOWN -> the site is skipped. Abstaining
    is the safe direction for a guard: a missed site is a gap, a wrong site is
    noise that gets the whole guard turned off.
    """
    kinds: List[str] = []
    for node in ast.walk(scope):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name:
            kind = _annotation_kind(node.annotation)
            if kind == UNKNOWN and node.value is not None:
                kind = _construct_kind(node.value)
            kinds.append(kind)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    kinds.append(_construct_kind(node.value))
    kinds = [k for k in kinds if k != UNKNOWN]
    if not kinds:
        return UNKNOWN
    if all(k == MAPPING for k in kinds):
        return MAPPING
    if all(k == NONMAPPING for k in kinds):
        return NONMAPPING
    return UNKNOWN


# ---------------------------------------------------------------- clause 4 --
def record_valued_mapping(returns: Optional[ast.AST]) -> Optional[str]:
    """``Dict[K, V]`` with V a container -> the rendered annotation; else None."""
    if returns is None:
        return None
    if _bare(returns) not in _MAPPING_NAMES:
        return None
    if not isinstance(returns, ast.Subscript):
        return None                      # bare `dict` says nothing about V
    sl = returns.slice
    if isinstance(sl, ast.Index):        # py<3.9 shape, harmless if absent
        sl = sl.value                    # pragma: no cover
    if not isinstance(sl, ast.Tuple) or len(sl.elts) != 2:
        return None
    value_ann = sl.elts[1]
    if _bare(value_ann) not in _CONTAINER_NAMES:
        return None
    if _bare(value_ann) == "Any" and not isinstance(value_ann, ast.Subscript):
        return None                      # `Dict[str, Any]` -- V unknown
    return ast.unparse(returns)


class _ModuleIndex:
    """Return annotations of every ``def`` in the sweep root, by module."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: Dict[str, Dict[str, Optional[ast.AST]]] = {}

    def returns_of(self, module: Optional[str], func: str,
                   local: Dict[str, Optional[ast.AST]]) -> Optional[ast.AST]:
        if module is None:
            return local.get(func)
        table = self._cache.get(module)
        if table is None:
            path = self._root / f"{module}.py"
            table = {}
            if path.is_file():
                try:
                    tree = ast.parse(path.read_text(errors="replace"))
                    for node in tree.body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            table[node.name] = node.returns
                except SyntaxError:
                    pass
            self._cache[module] = table
        return table.get(func)


# ---------------------------------------------------------------- clause 2 --
def _source_aliases(loop: ast.AST) -> Set[str]:
    """The loop target plus every name assigned from it inside the body.

    ``for lp in liberties: p = Path(lp); acc.update(parse(p.read_text()))`` --
    the source reaches the merge through ``p``, so following one hop of
    assignment is required, not a refinement.
    """
    aliases = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
    changed = True
    while changed:                       # transitive: p = Path(lp); q = p.parent
        changed = False
        for node in ast.walk(loop):
            if not isinstance(node, ast.Assign):
                continue
            rhs = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            if not (rhs & aliases):
                continue
            for target in node.targets:
                for n in ast.walk(target):
                    if isinstance(n, ast.Name) and n.id not in aliases:
                        aliases.add(n.id)
                        changed = True
    return aliases


#: The clauses, in the order the predicate applies them. Named here so the
#: report, the JSON and the test all speak about the same funnel.
CLAUSES = ("candidates", "source_dependent", "mapping_accumulator",
           "record_valued_producer")


def new_stats() -> Dict[str, int]:
    return {c: 0 for c in CLAUSES}


def _merge_targets(loop: ast.AST) -> List[Tuple[ast.AST, str, ast.Call]]:
    """Every ``ACC.update(CALL(...))`` and ``ACC |= CALL(...)`` under ``loop``.

    The two spellings are one shape. `dict.__ior__` is last-wins exactly as
    `dict.update` is, so a site that changed from one to the other would keep
    the defect and lose the guard -- which is how a guard gets evaded without
    anyone intending to evade it.
    """
    out: List[Tuple[ast.AST, str, ast.Call]] = []
    for node in ast.walk(loop):
        if isinstance(node, ast.Call):
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "update"):
                continue
            if not isinstance(fn.value, ast.Name):
                continue
            if len(node.args) != 1 or node.keywords:
                continue
            if isinstance(node.args[0], ast.Call):
                out.append((node, fn.value.id, node.args[0]))
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr):
            if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Call):
                out.append((node, node.target.id, node.value))
    return out


def scan_source(text: str, path: str, index: _ModuleIndex,
                stats: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    if stats is None:
        stats = new_stats()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    local_returns: Dict[str, Optional[ast.AST]] = {}
    import_alias: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_returns[node.name] = node.returns
        elif isinstance(node, ast.Import):
            for a in node.names:
                import_alias[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]

    parent: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def enclosing_scope(node: ast.AST) -> ast.AST:
        cur = node
        while cur in parent:
            cur = parent[cur]
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur
        return tree

    findings: List[Dict[str, Any]] = []
    for loop in [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.AsyncFor))]:
        aliases = _source_aliases(loop)
        for call, acc, arg in _merge_targets(loop):
            # clause 1
            if acc in aliases:
                continue
            stats["candidates"] += 1
            # clause 2
            if not ({n.id for n in ast.walk(arg) if isinstance(n, ast.Name)} & aliases):
                continue
            stats["source_dependent"] += 1
            # clause 3
            if accumulator_kind(enclosing_scope(call), acc) != MAPPING:
                continue
            stats["mapping_accumulator"] += 1
            # clause 4
            producer, module = arg.func, None
            if isinstance(producer, ast.Attribute) and isinstance(producer.value, ast.Name):
                module = import_alias.get(producer.value.id)
                func = producer.attr
            elif isinstance(producer, ast.Name):
                func = producer.id
            else:
                continue
            rendered = record_valued_mapping(
                index.returns_of(module, func, local_returns))
            if rendered is None:
                continue
            stats["record_valued_producer"] += 1
            findings.append({
                "file": path,
                "line": call.lineno,
                "accumulator": acc,
                "producer": (f"{module}." if module else "") + func,
                "producer_returns": rendered,
                "code": ast.unparse(call),
                "rule": "empty-record-cannot-erase",
                "why": ("last-wins merge of per-source records: a source that "
                        "describes this key emptily overwrites one that "
                        "described it, and which one wins is decided by the "
                        "order the sources were discovered in"),
                "fix": ("_source_record_merge.merge_source_records(...) with an "
                        "explicit `content=` and `on_conflict=`"),
            })
    return findings


def sweep(root: Path, skip: Tuple[str, ...] = (),
          stats: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    index = _ModuleIndex(root)
    out: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in skip):
            continue
        out.extend(scan_source(path.read_text(errors="replace"), rel, index,
                               stats))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent),
                    help="directory to sweep (default: this programs/ dir)")
    ap.add_argument("--skip", action="append", default=[],
                    help="relative path prefix to leave out of the sweep; "
                         "reported in the JSON so a narrowed sweep cannot read "
                         "as a full one")
    ap.add_argument("--json", help="write the full finding list here")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[ERROR] per_source_record_merge_check: no such root: {root}",
              file=sys.stderr)
        return RC_USAGE

    stats = new_stats()
    findings = sweep(root, tuple(args.skip), stats)
    swept = sum(1 for _ in root.rglob("*.py"))
    payload = {
        "rule": "empty-record-cannot-erase",
        "root": str(root),
        "python_files_under_root": swept,
        "skipped_prefixes": list(args.skip),
        "clause_funnel": dict(stats),
        "findings": findings,
        "count": len(findings),
    }
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2))

    # Printed on BOTH exits. An exit 0 whose funnel is all zeroes means the
    # predicate never reached its decision point, which is a different fact
    # from a clean corpus and must not be readable as one.
    funnel = " -> ".join(f"{c.replace('_', '-')} {stats[c]}" for c in CLAUSES)
    if not findings:
        print(f"[PASS] per_source_record_merge_check: {swept} file(s) under "
              f"{root} — no per-source record merge decided by discovery order"
              + (f" (skipped: {', '.join(args.skip)})" if args.skip else ""))
        print(f"       clause funnel: {funnel}")
        return RC_CLEAN

    print(f"[FAIL] per_source_record_merge_check: {len(findings)} per-source "
          f"record merge(s) whose result depends on discovery order "
          f"({swept} file(s) swept; clause funnel: {funnel})")
    for f in findings:
        print(f"  {f['file']}:{f['line']}  {f['code']}")
        print(f"      {f['producer']} -> {f['producer_returns']}; "
              f"an empty record for a key overwrites a populated one")
        print(f"      fix: {f['fix']}")
    return RC_FOUND


if __name__ == "__main__":
    sys.exit(main())
