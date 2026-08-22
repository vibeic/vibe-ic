#!/usr/bin/env python3
"""A layer population selected by a filename prefix instead of by the relation.

THIS GATE BLOCKS (rc=1), AND IT IS RED ON THE TREE IT SHIPPED WITH.
===================================================================
That is deliberate and it is the point. Membership of a layer is a RELATION —
the executable imports the layer's package — and a naming convention standing
in for that boundary silently shrinks the population every time the layer grows
in a direction the convention did not anticipate. The members that fell outside
are exactly the ones nobody is looking at, so the shrinkage is invisible.

There is no inventory here on purpose. A recorded waiver would make the
question disappear; a red gate keeps it visible until the two suites below are
pointed at the relation. Per the 2026-08-22 ruling: an instrument that cannot
go red on a real defect is not a gate, and a gate that is green because its own
inventory absorbed the finding is the shape this work exists to remove.

WHAT IS RED, AND WHAT FIXES IT
==============================
    layer `ppa`
        glob-derived   (`ppa_*.py`)                    20
        relation-derived (executables importing `_ppa`) 26
        IN THE LAYER, OUTSIDE THE GLOB                   6

        area.py · gate_proof_vocabulary_has_a_producer.py · openroad.py
        power_total_vs_budget_check.py · readme_ppa_extractor.py · timing.py

        Restated at the merge with main a4caccefe (v1.11.69), which grew the
        layer. ONE OF THE SIX IS THIS BRANCH'S OWN
        `gate_proof_vocabulary_has_a_producer.py`: it imports `_ppa` and is
        executable, so it is a layer member that the `ppa_*.py` glob does not
        reach, and the two suites below do not enforce the layer contract on
        it. That is the defect this gate reports, arriving by the ordinary
        route -- somebody added a member -- which is the point.

    used by  test_ppa_layer_exit_contract.py
             test_ppa_layer_internal_error_is_not_a_finding.py

Both suites enforce a LAYER-WIDE property — the exit-code contract, and that an
internal error is not reported as a finding — over a population that omits six
of the layer's own executables. The first even says so in a comment: "Discovered,
not listed: a fifteenth program added tomorrow is covered by this file the
moment it lands, which is the only way a LAYER property stays a layer property."
The discovery is real; the SET it discovers is not the layer.

THE REMEDY the record asks for: define the population as every executable that
imports the layer's package, take the prefix glob as ONE CONTRIBUTOR rather
than as the definition, assert the relation-derived set is a SUPERSET of the
glob-derived one, and drive every arm over the relation-derived set.

THE PREDICATE
=============
For every filename-prefix glob `<p>_*.py` used in a test to build a population,
compare against the relation: modules that import the package `_<p>` AND are
EXECUTABLE (they carry an `if __name__ == "__main__"` guard). A finding is a
prefix whose relation-derived set is not a subset of the glob-derived set.

EXECUTABILITY IS PART OF THE RELATION, not a refinement. Seven modules import
`_ppa` outside the glob; two of them (`closure.py`, `yosys.py`) carry no entry
point, so an exit-code contract cannot be enforced on them and they are not
members of the population these suites test. Counting them would have inflated
the finding by 40 per cent with modules the rule has nothing to say about.

`test_*.py` IS EXCLUDED. A suite globbing `test_*.py` is discovering tests, not
a layer, and there is no package `_test` for it to relate to.

EXIT
====
  0  every prefix-derived layer population contains its whole relation
  1  a layer member outside the glob that selects the population
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

#: A suite globbing this is discovering tests, not relating to a layer.
_NOT_A_LAYER = frozenset({"test"})

_PREFIX_GLOB = re.compile(r'glob\(\s*["\']([a-z0-9_]+)_\*\.py["\']\s*\)')


def _is_executable(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.If):
            try:
                if "__main__" in ast.unparse(n.test):
                    return True
            except Exception:                    # noqa: BLE001
                continue
    return False


def _imports(tree: ast.AST, pkg: str) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Import) and any(
                a.name.split(".")[0] == pkg for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == pkg:
            return True
    return False


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    tests = progs / "tests"
    if not progs.is_dir() or not tests.is_dir():
        return [], {"tests_read": 0, "prefix_globs": 0, "layers_examined": 0,
                    "layers_short": 0}

    users: Dict[str, Set[str]] = {}
    tests_read = 0
    for p in sorted(tests.rglob("test_*.py")):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tests_read += 1
        for m in _PREFIX_GLOB.finditer(src):
            pre = m.group(1)
            if pre in _NOT_A_LAYER:
                continue
            users.setdefault(pre, set()).add(p.name)

    parsed: List[Tuple[Path, ast.AST]] = []
    for p in sorted(progs.rglob("*.py")):
        if "tests" in p.parts:
            continue
        try:
            parsed.append((p, ast.parse(
                p.read_text(encoding="utf-8", errors="replace"))))
        except (OSError, SyntaxError, ValueError):
            continue

    findings: List[dict] = []
    examined = 0
    for pre, by in sorted(users.items()):
        pkg = "_" + pre
        if not (progs / pkg).is_dir() and not (progs / f"{pkg}.py").is_file():
            continue                             # no package: no relation
        examined += 1
        globset = {q.name for q in progs.glob(f"{pre}_*.py")}
        relation = {p.name for p, t in parsed
                    if _imports(t, pkg) and _is_executable(t)}
        outside = sorted(relation - globset)
        if outside:
            findings.append({"layer": pre, "glob": len(globset),
                             "relation": len(relation), "outside": outside,
                             "selected_by": sorted(by)})
    return findings, {
        "tests_read": tests_read,
        "prefix_globs": len(users), "layers_examined": examined,
                      "layers_short": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] layer_membership_is_declared: no "
                  "repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] layer_membership_is_declared: the walk did "
              f"not complete ({type(exc).__name__}: {exc}). NOT a pass.",
              file=sys.stderr)
        return 2

    print(f"  filename-prefix globs in tests: {denom['prefix_globs']}")
    print(f"  of those with a layer package:  {denom['layers_examined']}")
    print(f"  layers the glob under-counts:   {denom['layers_short']}")

    if findings:
        print(f"\n[FAIL] {len(findings)} layer population(s) selected by a "
              f"filename prefix omit their own members:")
        for f in findings:
            print(f"   layer `{f['layer']}`: glob {f['glob']}, relation "
                  f"{f['relation']}, {len(f['outside'])} outside")
            for m in f["outside"]:
                print(f"       {m}")
            print(f"     selected by: {', '.join(f['selected_by'])}")
        print("\n  The layer property is UNENFORCED on every member the glob "
              "does not reach,\n  and those are exactly the ones nobody is "
              "looking at. Define the population\n  as every executable that "
              "imports the layer's package; keep the glob as one\n  contributor "
              "and assert the relation is a superset of it.")
        return 1

    # A GREEN FROM AN EMPTY DENOMINATOR IS NOT A PASS -- and the denominator
    # that decides it is TESTS READ, not globs in scope. Those are different:
    # a tree whose only prefix glob turns out to be test discovery HAS been
    # examined and found nothing in scope, which is a real rc 0. A tree with no
    # test files at all was not examined, and "every prefix-selected layer
    # population contains its whole relation" over the empty set is vacuously
    # true. An earlier attempt keyed this on `prefix_globs` and turned three of
    # this file's own tests red -- correctly, because it conflated the two.
    if denom.get("tests_read", 0) == 0:
        print("[CANNOT DETERMINE] layer_membership_is_declared: 0 test files "
              "were read, so no layer population was examined. NOT a pass.")
        return 2

    print("[PASS] layer_membership_is_declared: every prefix-selected layer "
          "population contains its whole relation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
