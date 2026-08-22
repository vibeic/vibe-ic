#!/usr/bin/env python3
"""Two ways to name the input, and nothing decides what happens if both arrive.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A tool grows a second way to name its input — a directory of many alongside the
single positional one — and the two are wired as INDEPENDENT options rather
than as ALTERNATIVES. Given both, the later branch wins and the other input is
never opened. Nothing is printed about the input that was dropped, so a caller
who names a failing record and adds the directory flag is told the DIRECTORY's
verdict and never learns their record was not read.

The output is well-formed and describes work that was genuinely done — just not
on the thing they named. That is why it is invisible.

THE PREDICATE
=============
A parser offers BOTH:

  * a SINGLE-target selector — a positional, or `--file` / `--record` /
    `--doc` / `--manifest` / `--target` / `--input` / `--path`; and
  * a COLLECTION selector — `--dir` / `--tree` / `--corpus` / `--batch` /
    `--all` / `--inputs` / `--files` / `--glob` / `--roots`.

A finding is such a parser where NEITHER

  * the two sit in one `add_mutually_exclusive_group()`, so the parser itself
    refuses both; NOR
  * any `if` TEST mentions both and is a conjunction, so the program decides
    the both-given case itself.

`--json` AND `--report` ARE NOT INPUT SELECTORS in this repository — they name
where output is written. Counting them took the candidate set from 9 to 13 with
every added hit a false positive, so they are excluded by name.

THE TEST EXPRESSION ONLY, NEVER THE BODY. Matching an `if` node's unparsed
source includes its body, and that reported a both-given branch for a program
whose actual conjunction is an unrelated environment override several lines
down. The predicate reads `If.test` alone.

THE REMEDY IS IN THE TREE. `step_internal_fail_bubble_up_check.py:1253` writes
`if args.corpus and args.project_dir:` and refuses, which is exactly what the
record asks for: refuse as a BAD INVOCATION and name both. Where a caller
genuinely needs both, adjudicate both populations and aggregate under the
most-severe rule — but say so, never pick one silently.

EXIT
====
  0  every dual-selector parser refuses or decides the both-given case
  1  a NEW one, or a stale inventory row
  2  cannot determine
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_INVENTORY_NAME = "dual_input_selector_inventory.json"

#: `--json` and `--report` name OUTPUT in this repository. Including them was
#: measured at four added candidates, all false.
#: SETS, NOT REGEXES, AND DELIBERATELY SO. Both of these were fully-anchored
#: alternations of literal option names -- `^--(a|b|c)$` -- which is set
#: membership written as a pattern. As a pattern the single-target one also
#: contained `input` and `record`, so
#: `hdl_declaration_scan_strips_comments_check` correctly classified it as a
#: DECLARATION-shaped regex and reported it scanning text no stripper touched.
#:
#: Comments cannot in fact reach it: `opt` is an `ast.Constant` value out of
#: `ast.parse`, which discards comments. So stripping comments here would be a
#: no-op that made the code claim a safety it was not performing. The honest
#: repair is to stop being a declaration-shaped regex at all -- the membership
#: test is what was meant, it is exactly equivalent for anchored alternations,
#: and it leaves that gate's detector untouched. Do not turn these back into
#: `re.compile`.
_SINGLE = frozenset({"file", "record", "path", "target", "input", "doc",
                     "manifest"})
_COLLECTION = frozenset({"dir", "directory", "tree", "glob", "all", "batch",
                         "corpus", "inputs", "files", "roots"})


def _mutually_exclusive_groups(tree: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                and n.targets and isinstance(n.targets[0], ast.Name):
            f = n.value.func
            if isinstance(f, ast.Attribute) \
                    and f.attr == "add_mutually_exclusive_group":
                out.add(n.targets[0].id)
    return out


def _selectors(tree: ast.AST) -> Tuple[List[str], List[str], Set[str]]:
    """(single-target names, collection names, names in an exclusive group)."""
    mx = _mutually_exclusive_groups(tree)
    singles: List[str] = []
    colls: List[str] = []
    in_mx: Set[str] = set()
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_argument" and n.args):
            continue
        a0 = n.args[0]
        if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
            continue
        opt = a0.value
        if isinstance(n.func.value, ast.Name) and n.func.value.id in mx:
            in_mx.add(opt.lstrip("-"))
        if opt.startswith("--"):
            if opt[2:] in _SINGLE:
                singles.append(opt.lstrip("-"))
            if opt[2:] in _COLLECTION:
                colls.append(opt.lstrip("-"))
        elif not opt.startswith("-"):
            singles.append(opt)                  # a positional target
    return singles, colls, in_mx


def _decides_both_given(tree: ast.AST, singles: List[str],
                        colls: List[str]) -> Optional[Tuple[int, str]]:
    """An `if` TEST naming both, as a conjunction. Never reads the body.

    THE CONJUNCTION IS READ AS A NODE, NOT AS THE SUBSTRING `" and "`, and the
    negation as `ast.Not`, NOT as the substring `"not "`. Both spellings were
    string tests, and the second one refused a correct remedy: the tree's own
    `if args.record is not None and args.corpus is not None:` — which names
    both, is a conjunction, and refuses — carries `not ` inside `is not None`
    and was skipped, so a program that DOES decide the both-given case was
    reported as one that does not. A `not` APPLIED to a selector is a different
    shape (`if not a.corpus and not a.record:` asks whether NEITHER was given,
    which decides nothing about both), and that one is still skipped.
    """
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        if not (isinstance(n.test, ast.BoolOp)
                and isinstance(n.test.op, ast.And)):
            continue
        if any(isinstance(x, ast.UnaryOp) and isinstance(x.op, ast.Not)
               for x in ast.walk(n.test)):
            continue
        try:
            t = ast.unparse(n.test)
        except Exception:                        # noqa: BLE001
            continue
        if any(re.search(rf"\.{re.escape(s)}\b", t) for s in singles) \
                and any(re.search(rf"\.{re.escape(c)}\b", t) for c in colls):
            return n.lineno, t[:70]
    return None


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    dual = 0
    base = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not base.is_dir():
        return findings, {"modules_parsed": 0, "dual_selector_parsers": 0,
                          "neither_refuses_nor_decides": 0}
    for f in sorted(base.rglob("*.py")):
        if "tests" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        parsed += 1
        singles, colls, in_mx = _selectors(tree)
        if not (singles and colls):
            continue
        dual += 1
        if (set(singles) & in_mx) and (set(colls) & in_mx):
            continue                             # the parser itself refuses
        if _decides_both_given(tree, singles, colls):
            continue                             # the program decides
        findings.append({"file": f.relative_to(root).as_posix(),
                         "single": sorted(set(singles))[:3],
                         "collection": sorted(set(colls))[:3]})
    return findings, {"modules_parsed": parsed,
                      "dual_selector_parsers": dual,
                      "neither_refuses_nor_decides": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{','.join(f['single'])}::{','.join(f['collection'])}"


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
            print("[CANNOT DETERMINE] two_input_selectors_given_together_must_"
                  "refuse: no repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if denom["modules_parsed"] == 0:
            print("[CANNOT DETERMINE] two_input_selectors_given_together_must_"
                  "refuse: no programs/ under that root. NOT a pass.",
                  file=sys.stderr)
            return 2
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] two_input_selectors_given_together_must_"
              f"refuse: the walk did not complete ({type(exc).__name__}: "
              f"{exc}). NOT a pass.", file=sys.stderr)
        return 2

    print(f"  modules parsed:                 {denom['modules_parsed']}")
    print(f"  dual-selector parsers:          {denom['dual_selector_parsers']}")
    print(f"  neither refuse nor decide:      "
          f"{denom['neither_refuses_nor_decides']}")
    print(f"  inventory rows applied:         {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} parser(s) accept two ways to name the input "
              f"and decide neither:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}  single={f['single']} "
                      f"collection={f['collection']}")
        print("\n  Given both, one silently shadows the other and the caller is "
              "told a verdict\n  about an input they did not name. Put them in "
              "one mutually exclusive group,\n  or decide the case explicitly — "
              "step_internal_fail_bubble_up_check.py:1253\n  shows the shape: "
              "`if args.corpus and args.project_dir:` and refuse.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] two_input_selectors_given_together_must_refuse: every "
              "dual-selector parser refuses or decides the both-given case.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
