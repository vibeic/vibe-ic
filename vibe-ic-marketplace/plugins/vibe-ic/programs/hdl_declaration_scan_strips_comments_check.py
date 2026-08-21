#!/usr/bin/env python3
"""An HDL declaration scanned out of text nobody stripped the comments from.

THIS GATE BLOCKS (rc=1) on a NEW one. vibe-ic#731.

WHY IT EXISTS
-------------
`// This module controls the round counter` matches `\\bmodule\\s+(\\w*)` and
mints a module named `controls`. MEASURED on a real cell (vibe-ic#729): 24
phantom modules across the staged RTL, `_module_ports` then spanning from a
comment into a real header, and FS1 reporting `DC=UNMEASURED (0 faults
injected)` on a design shipping a genuine SEC-DED ECC.

IT IS A DATAFLOW QUESTION, NOT A PRESENCE ONE — and that distinction is the
whole reason this program exists rather than a one-line grep. The defect
function CALLS the stripper:

    code = _strip_hdl_comments(t)      # for combined_code
    ...
    for mod in _MODULE_RE.findall(t):  # on the RAW t

So "does this function reach a comment stripper" answers YES for the one
instance it was written for. Three detectors were built and retracted on that
basis before this one; see the issue. What is asked here is whether the STRING
FLOWING INTO THIS CALL passed a stripper, resolved by a local def-use walk.

READING THE PATTERN
-------------------
From the AST `Constant`, never from `ast.unparse`, and the metacharacters are
normalised before the keyword is matched. `ast.unparse` re-escapes, so
`r"\\bmodule\\s+"` renders with `b` immediately before `module` and a
`\\bmodule\\b` probe finds no word boundary — an artefact that silently produced
two confident, wrong populations (252 and 10, neither containing the known
instance).

THE CONTROLS ARE PART OF THE GATE
---------------------------------
`test_hdl_declaration_scan_strips_comments` drives both, and they are the
acceptance criterion recorded in the issue:

    POSITIVE  fmeda_fault_injection_coverage.detect_safety_mechanism at the
              commit before its fix MUST be flagged.
    NEGATIVE  the same function after the fix MUST NOT be.

A detector that does not flag the known instance is not measuring the right
thing, however plausible its output.

BASELINE
--------
Call sites that scan a declaration regex over an unstripped local. Most are
harmless — a netlist has no comments, a prompt is not HDL — and failing all of
them on day one is how a gate gets switched off. The set may only shrink;
anything NEW fails from the first run.

The live number is in `hdl_declaration_scan_baseline.json`, not here: a count
written into prose stops tracking the thing it counts. This docstring said 174
while the register held 171, and neither figure was challenged because nothing
compares them.

chip-AGNOSTIC: pure AST structure. No design, PDK or vendor literal.

USAGE
-----
    hdl_declaration_scan_strips_comments_check.py [--root .] [--json OUT]
                                                  [--write-baseline]

    exit 0 = no NEW unstripped declaration scan
    exit 1 = a new one, or the baseline grew (BLOCKING)
    exit 2 = could not be determined — never a vacuous pass
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_BASELINE_NAME = "hdl_declaration_scan_baseline.json"

#: Regex metacharacters, blanked before the keyword search. See the docstring:
#: matching a keyword in a regex SOURCE without this is how the retracted
#: populations were produced.
_META = re.compile(r"\\[a-zA-Z]|\(\?[^)]*\)|[\[\]()+*?{}^$|]")
_KW = re.compile(r"\b(?:module|input|output|inout)\b")
#: A name that means "comments are gone".
_STRIPPER = re.compile(r"strip.*comment|_strip_hdl|decomment|no_comment", re.I)
#: A regex SOURCE that removes comments by naming a comment INTRODUCER. Stripping
#: is an operation, not a function name: `re.sub(r"//[^\n]*", " ", txt)` removes
#: comments just as surely as a helper called `strip_comments`, and recognising
#: only the latter made this gate report a call site that was already correct.
#:
#: Backslashes are dropped before the search because the pattern is read as
#: SOURCE: `/\*.*?\*/` carries `/\*`, not `/*`. Reading it from the AST Constant
#: rather than `ast.unparse` matters for the same reason — unparse re-escapes.
#:
#: HONEST LIMIT: this accepts a call that strips only ONE comment form. A site
#: that removes `//` but never `/* */` will read as stripped here and is not.
#: That is a narrower hole than the one it closes, and naming it is better than
#: a stricter rule that fails every file whose HDL has only line comments.
_COMMENT_PAT = re.compile(r"//|/\*|\*/")
_SCAN = {"search", "finditer", "findall", "match", "fullmatch", "split", "sub"}


def _strips_comments_inline(call: ast.Call) -> bool:
    """`re.sub(<a comment pattern>, ...)` — a strip written in place."""
    fn = call.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "sub" and call.args):
        return False
    src = "".join(n.value for n in ast.walk(call.args[0])
                  if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return bool(_COMMENT_PAT.search(src.replace("\\", "")))


def declares_hdl(pattern: str) -> bool:
    """Does this regex SOURCE name an HDL declaration keyword?"""
    return bool(_KW.search(_META.sub(" ", pattern or "")))


def _pattern_of(node: ast.AST) -> Optional[str]:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compile" and node.args):
        return None
    parts = [n.value for n in ast.walk(node.args[0])
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return "".join(parts) if parts else None


def declaration_regexes(tree: ast.Module) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            p = _pattern_of(n.value)
            if p and declares_hdl(p):
                out[n.targets[0].id] = p
    return out


def stripped_locals(fn: ast.AST) -> Set[str]:
    """Locals whose value passed through a stripper, transitively.

    Per-NAME, which is the point: a sibling variable being stripped does not
    make this one safe."""
    ok: Set[str] = set()
    grew = True
    while grew:
        grew = False
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name)):
                continue
            t = n.targets[0].id
            if t in ok:
                continue
            for sub in ast.walk(n.value):
                if isinstance(sub, ast.Call):
                    try:
                        fname = ast.unparse(sub.func)
                    except Exception:
                        fname = ""
                    if _STRIPPER.search(fname) or _strips_comments_inline(sub):
                        ok.add(t); grew = True
                        break
                if isinstance(sub, ast.Name) and sub.id in ok:
                    ok.add(t); grew = True
                    break
    return ok


def scan_source(src: str, label: str) -> List[str]:
    """`label::function::REGEX(arg)` for every unstripped declaration scan."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    regs = declaration_regexes(tree)
    if not regs:
        return []
    out: List[str] = []
    for fn in [x for x in ast.walk(tree)
               if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        safe = stripped_locals(fn)
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in _SCAN
                    and isinstance(n.func.value, ast.Name)):
                continue
            if n.func.value.id not in regs or not n.args:
                continue
            arg = n.args[-1] if n.func.attr in ("sub", "split") else n.args[0]
            if isinstance(arg, ast.Name) and arg.id not in safe:
                out.append(f"{label}::{fn.name}::{n.func.value.id}({arg.id})")
    return sorted(set(out))


def scan(root: Path) -> List[str]:
    out: List[str] = []
    for p in sorted((root / "programs").glob("*.py")):
        if p.stem.startswith("test_") or p.stem == Path(__file__).stem:
            continue
        try:
            out += scan_source(p.read_text(errors="replace"), p.stem)
        except OSError:
            continue
    return sorted(set(out))


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
        print(f"[CANNOT DETERMINE] hdl_declaration_scan: no programs/ under "
              f"{root}. NOT a pass.", file=sys.stderr)
        return 2

    now = scan(root)
    bpath = Path(a.baseline) if a.baseline else root / "programs" / _BASELINE_NAME

    if a.write_baseline:
        prev = _load(bpath) or []
        if prev and len(now) > len(prev):
            print(f"[FAIL] refusing to write a baseline that GREW "
                  f"({len(prev)} -> {len(now)}).", file=sys.stderr)
            return 1
        bpath.write_text(json.dumps(
            {"_comment": "Declaration regexes scanned over text no stripper "
                         "touched (vibe-ic#731). MAY ONLY SHRINK. A comment "
                         "sentence matching `module\\s+(\\w+)` mints a module "
                         "that does not exist — 24 of them, measured, in #729.",
             "known": now}, indent=2) + "\n")
        print(f"wrote {bpath} ({len(now)} recorded)")
        return 0

    base = _load(bpath)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"unstripped_scans": now, "baseline": base}, indent=2) + "\n")
    if base is None:
        print(f"[CANNOT DETERMINE] hdl_declaration_scan: no readable baseline "
              f"at {bpath}; {len(now)} call site(s) scan a declaration regex "
              f"over unstripped text and there is nothing to compare against. "
              f"NOT a pass.", file=sys.stderr)
        return 2

    new = sorted(set(now) - set(base))
    gone = sorted(set(base) - set(now))
    print(f"  declaration scans over unstripped text: {len(now)} "
          f"(baseline {len(base)})")
    if gone:
        print(f"  [NOTE] baseline shrank by {len(gone)}. Re-run with "
              f"--write-baseline.")
    if new:
        print(f"\n[FAIL] {len(new)} declaration regex(es) newly scan text no "
              f"stripper touched:")
        for n in new:
            print(f"   {n}")
        print("\n  A comment sentence matching `module\\s+(\\w+)` mints a module "
              "that does not\n  exist. Strip comments on the value that reaches "
              "the scan — stripping a\n  SIBLING variable does not make this one "
              "safe, which is the whole reason\n  this gate reads dataflow and "
              "not presence.")
        return 1
    if len(now) > len(base):
        print(f"\n[FAIL] the set grew {len(base)} -> {len(now)} with no new "
              f"name — the baseline is stale.")
        return 1
    print("[PASS] hdl_declaration_scan: no declaration regex newly reads "
          "unstripped text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
