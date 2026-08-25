#!/usr/bin/env python3
"""Programs that behave like checkers but are invisible to the wiring audit.

THIS IS A CENSUS, NOT A GATE. IT MUST NOT BE WIRED AS A BLOCKING CHECK. It
reports a count and exits 0. `--strict` restores a refusing exit for a caller
who wants one. The refusing instrument for this class is
`programs/layer_membership_is_declared_not_inferred_from_a_filename_prefix.py`,
which refuses the same defect -- a population selected by a NAME rather than by
a relation -- in the `ppa` layer.

WHAT IT ASKS THE REPOSITORY
===========================
`checker_execution_wiring_audit.py` answers "is this checker wired?" over a
population defined by FILENAME SUFFIX:

    _CHECKER_SUFFIXES = ("*_check.py","*_audit.py","*_guard.py","*_lint.py",
                         "*_gate.py")

A program that emits a verdict and can refuse, but is not named that way, is
not reported as unwired -- it is not reported at all. This census names those
programs.

WHY A CENSUS AND NOT A GATE. The population it reports is largely PRE-EXISTING:
a gate here would refuse the trunk, and a rule whose first act is to block main
is a re-baselining argument, not a finding. The count is the argument.

THE PREDICATE, AND WHY IT IS A RANGE
====================================
"Behaves like a checker" is reported two ways on purpose:

  WIDE    the verdict banner appears anywhere in the source, and the file has
          a `__main__` entry. Over-counts by the files that only DESCRIBE a
          banner: measured, 4 of 47, one of them this census, which prints
          `[CENSUS]` and merely documents the others.
  BANNER  the banner is a string literal inside a `print()`. Reads stricter and
          is NOT better on its own -- it FALSE-NEGATIVES the programs that
          compose the banner first, and two of the four it drops are real
          verdict emitters:
              landing_merge_verdict.py:1803  head = ("[PASS] ..." if v.ok
                                                     else "[FAIL] ...")
              coverage_closure.py:105        return 1, [f"[FAIL] ..."]
          Both are printed through a name, which no literal-in-print match
          sees. So both figures are disclosed and neither is called the answer.
  NARROW  that, and a REFUSING exit path -- `return 1` / `sys.exit(1)` as a
          literal, or an assignment `rc = 1` that is later returned.

The narrow predicate was written literal-only first and found 8 of this
branch's 20 instruments, though ALL TWENTY refuse: they assign `rc = 1` and
`return rc`, which a literal match never sees. That is why the assignment form
is tracked, and why both figures are printed. A single number here would be a
literal-match artefact, which is the error the whole capture exists to remove.

RC CONTRACT
===========
    0  the census ran (whatever it counted)          -- with --strict, 0 only
                                                        when the count is 0
    1  --strict and at least one program is invisible
    2  UNDETERMINED -- no programs directory, or the audit's suffix tuple
       could not be read. NOT a pass.
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
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

_AUDIT = "checker_execution_wiring_audit.py"
_VERDICT = ("[PASS]", "[FAIL]")


def _suffixes(programs: Path) -> Optional[List[str]]:
    """The audit's own tuple, READ FROM ITS SOURCE, never re-typed here.

    A copy would drift the moment somebody adds a sixth suffix, and this census
    would then report programs the audit can in fact see.
    """
    f = programs / _AUDIT
    try:
        src = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"_CHECKER_SUFFIXES\s*=\s*\(([^)]*)\)", src, re.S)
    if not m:
        return None
    pats = re.findall(r'"([^"]+)"', m.group(1))
    return pats or None


def _refuses(tree: ast.AST) -> bool:
    """A refusing exit path, in either form the tree actually uses."""
    rc_names: Set[str] = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                and n.value.value == 1):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    rc_names.add(t.id)
    for n in ast.walk(tree):
        if isinstance(n, ast.Return):
            v = n.value
            if isinstance(v, ast.Constant) and v.value == 1:
                return True
            if isinstance(v, ast.Name) and v.id in rc_names:
                return True
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "exit"
                and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == 1):
            return True
    return False


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    programs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    if not programs.is_dir():
        raise FileNotFoundError(f"no programs/ under {root}")
    return scan_programs(programs)


def scan_programs(programs: Path) -> Tuple[List[dict], Dict[str, int]]:
    """The census over an ALREADY-RESOLVED programs/ directory.

    Separate from `scan` because the in-process caller
    (`checker_execution_wiring_audit.CORPUS_FIGURES`) is handed the PLUGIN
    root and already knows where programs/ is; making it re-derive a checkout
    root so this function could re-derive programs/ from it would be a second
    copy of a path this repo has exactly one of.
    """
    if not programs.is_dir():
        raise FileNotFoundError(f"no such programs dir: {programs}")
    pats = _suffixes(programs)
    if pats is None:
        raise RuntimeError(f"could not read _CHECKER_SUFFIXES from {_AUDIT}")

    visible: Set[str] = set()
    for p in pats:
        visible |= {f.name for f in programs.glob(p)}

    top = sorted(programs.glob("*.py"))
    wide: List[dict] = []
    narrow = 0
    literal = 0
    for f in top:
        if f.name in visible:
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not any(v in src for v in _VERDICT):
            continue
        if '__name__ == "__main__"' not in src:
            continue
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        r = _refuses(tree)
        narrow += 1 if r else 0
        banner = any(
            isinstance(sub, ast.Constant) and isinstance(sub.value, str)
            and any(v in sub.value for v in _VERDICT)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "print"
            for sub in ast.walk(n))
        literal += 1 if banner else 0
        wide.append({"file": f.name, "refuses": r, "literal_banner": banner})

    denom = {
        "top_level_programs": len(top),
        "suffix_patterns": len(pats),
        "visible_to_the_audit": len(visible),
        "outside_that_population": len(top) - len(visible),
        "outside_and_emitting_a_verdict": len(wide),
        "of_those_with_a_literal_banner_in_a_print": literal,
        "outside_and_also_refusing": narrow,
    }
    return wide, denom


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="refuse (rc 1) when anything is invisible")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3

    root = Path(a.root).resolve() if a.root else _repo_root(
        Path(__file__).resolve())
    if root is None or not root.is_dir():
        print("[CANNOT DETERMINE] checker_population_is_structural: no "
              "checkout root. NOT a pass.")
        return 2
    try:
        findings, denom = scan(root)
    except Exception as exc:                                   # noqa: BLE001
        print(f"[CANNOT DETERMINE] checker_population_is_structural: the census "
              f"did not complete ({type(exc).__name__}: {exc}). NOT a pass.")
        return 2

    for k, v in denom.items():
        print(f"  {k.replace('_', ' ')}: {v}")
    if a.json_out:
        # ATOMIC (vibe-ic#1082): this is the DECLARED report a later
        # reader resolves, so the final name must appear only once the
        # write is complete.
        atomic_write_text(
            Path(a.json_out),
            json.dumps({"findings": findings, "denominator": denom}, indent=2),
            encoding="utf-8")

    if findings:
        print(f"\n[CENSUS] {len(findings)} program(s) emit a verdict and are "
              f"outside the wiring audit's filename-shaped population "
              f"({denom['outside_and_also_refusing']} of them also refuse):")
        for f in findings[:40]:
            print(f"   {f['file']}{'  (refuses)' if f['refuses'] else ''}")
        if len(findings) > 40:
            print(f"   ... and {len(findings) - 40} more")
        print("\n  CENSUS: reported, not refused. Membership of that audit's\n"
              "  population is decided by a NAME. The refusing instrument for\n"
              "  this class is\n"
              "  programs/layer_membership_is_declared_not_inferred_from_a_"
              "filename_prefix.py.")
        return 1 if a.strict else 0

    print("[CENSUS] 0 verdict-emitting programs outside the audit's population.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
