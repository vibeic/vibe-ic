#!/usr/bin/env python3
"""A short wall-clock deadline asserted as a substantive finding.

VERDICT CLASS: **ADVISORY** (rc 0 with findings) unless ``--strict``.

WHAT IT ASKS THE REPOSITORY
===========================
A forward-progress deadline of a second or so, applied to a subject that spawns
processes, measures the HOST and not the code. Under load it fires and is
reported as a defect in whatever change is in flight; on an idle host it passes
and the same red is reported as fixed.

A timing bound is a verdict only when the load it was measured under is
recorded beside it. And a verdict taken from ONE sample on each side of a
comparison is not a comparison: the arm run second inherits the load of the arm
run first, so the direction of the error is not even random.

MEASURED: one identifier appeared as a NEW red on a candidate arm and was not
one. Re-run in isolation, serially, on an idle host at load 2.9, it measured
8 of 8 failing on the BASE tree and 8 of 8 on the candidate — red on both, so
the family run's green on the base was a FALSE GREEN. Its own diagnostic reads
"did not advance for > 0.45s — killed as hung, not slow". A single sample on
each side would have filed it as damage the change had done.

THE PREDICATE
=============
A finding is a site where ALL of these hold:

  1. the module can spawn a process — `subprocess`, `Popen`, `os.system`;
  2. a numeric literal STRICTLY BELOW the floor (default 2.0 seconds) is
     compared against a value that is a wall-clock elapsed time: a difference
     of `time.monotonic()` / `time.time()` / `perf_counter()` readings, or a
     name spelled `elapsed`, `dt`, `waited`, `since`, `idle`, `silence`,
     `age`, `stall`;
  3. the branch that comparison controls reports a SUBSTANTIVE finding — an
     `assert`, a `raise`, a `pytest.fail`, a kill, or an append onto a
     finding-shaped collection;
  4. THE FINDING FIRES WHEN THE ELAPSED TIME EXCEEDS THE BOUND; and
  5. no string in that branch mentions the LOAD.

Clause 4 is a polarity test and it is not a refinement. `assert elapsed > 0.8`
fires when the work was too FAST — it is asserting that a delay really
happened, and under load it passes more easily, not less. That is the opposite
of the defect. The first sweep without this clause returned eight sites and ALL
EIGHT were that shape. What the rule is about is the bound that fires when the
subject is SLOW, which is the bound the host can trip.

Clause 4 is the whole remedy and the reason this is advisory rather than
blocking. The rule does not say the bound is wrong. It says a bound that
cannot state the load it fired under, and the load it was chosen under, is not
reporting a property of the code.

THE FLOOR IS A PARAMETER, NOT A TRUTH
=====================================
`--floor` moves it. The predicate is the bound PLUS the subject, not the
number: 0.45 s against a subject that starts a two-way concurrent driver is
indefensible, and 0.45 s against a pure function is nobody's business. The
default of 2.0 s is the smallest bound this repository's own container
measurements make defensible, and a caller who has measured otherwise should
say so with the flag rather than edit the file.

EXIT
====
  0  advisory run, or strict run with no finding
  1  --strict with at least one finding
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

_DEFAULT_FLOOR = 2.0

_CLOCKS = ("monotonic", "time", "perf_counter", "process_time", "monotonic_ns")

#: Names that spell an elapsed wall-clock duration.
_ELAPSED_NAMES = ("elapsed", "dt", "waited", "since", "idle", "silence",
                  "stall", "age", "duration", "took", "delta_t")

_SPAWN_TOKENS = ("subprocess", "Popen", "os.system")

_FINDING_CALLS = ("fail", "kill", "terminate", "abort")
_FINDING_NAMES = ("finding", "failure", "fail", "viol", "error", "problem",
                  "issue", "bad", "hung", "stall")


def _is_clock_read(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return isinstance(f, ast.Attribute) and f.attr in _CLOCKS


def _is_elapsed(node: ast.AST) -> bool:
    """Does this expression hold a wall-clock elapsed time?"""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        if _is_clock_read(node.left) or _is_clock_read(node.right):
            return True
        return _is_elapsed(node.left) or _is_elapsed(node.right)
    if isinstance(node, ast.Name):
        low = node.id.lower()
        return any(low == n or low.startswith(n + "_") or low.endswith("_" + n)
                   for n in _ELAPSED_NAMES)
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id in ("abs", "float", "round"):
            return any(_is_elapsed(a) for a in node.args)
    return False


def _short_bound(node: ast.AST, floor: float) -> Optional[float]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        v = float(node.value)
        if 0 < v < floor:
            return v
    return None


def _mentions_load(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if "load" in n.value.lower():
                return True
        if isinstance(n, ast.Name) and "load" in n.id.lower():
            return True
        if isinstance(n, ast.Attribute) and "load" in n.attr.lower():
            return True
    return False


def _reports_a_finding(node: ast.AST) -> Optional[str]:
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            return "assert"
        if isinstance(n, ast.Raise):
            return "raise"
        if isinstance(n, ast.Call):
            f = n.func
            attr = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if attr in _FINDING_CALLS:
                return f"{attr}()"
            if attr in ("append", "extend") and isinstance(f, ast.Attribute) \
                    and isinstance(f.value, ast.Name):
                low = f.value.id.lower()
                if any(t in low for t in _FINDING_NAMES):
                    return f"{f.value.id}.{attr}()"
    return None


def _parents(tree: ast.AST) -> Dict[int, ast.AST]:
    out: Dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            out[id(c)] = n
    return out


def _controlled_branch(pm: Dict[int, ast.AST],
                       cmp_node: ast.AST) -> Tuple[Optional[ast.AST], bool]:
    """(the controlling statement, whether the finding is the NEGATION).

    An `assert X` reports when X is FALSE, so its finding is the negation of
    the comparison. An `if X:` body reports when X is true.
    """
    cur = cmp_node
    negated = False
    for _ in range(5):
        par = pm.get(id(cur))
        if par is None:
            return None, False
        if isinstance(par, ast.UnaryOp) and isinstance(par.op, ast.Not):
            negated = not negated
        if isinstance(par, ast.Assert):
            return par, not negated
        if isinstance(par, (ast.If, ast.While, ast.IfExp)):
            return par, negated
        cur = par
    return None, False


def _fires_on_exceeding(node: ast.Compare, bound_index: int,
                        negated: bool) -> bool:
    """Does the reporting branch fire when elapsed is GREATER than the bound?"""
    if len(node.ops) != 1:
        return False
    op = node.ops[0]
    if bound_index == 1:                     # elapsed OP bound
        exceeds = isinstance(op, (ast.Gt, ast.GtE))
    else:                                    # bound OP elapsed
        exceeds = isinstance(op, (ast.Lt, ast.LtE))
    return (not exceeds) if negated else exceeds


def scan(root: Path, floor: float) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    spawning = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "node_modules" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text)
            except (OSError, SyntaxError, ValueError):
                continue
            parsed += 1
            if not any(tok in text for tok in _SPAWN_TOKENS):
                continue
            spawning += 1
            pm = _parents(tree)
            rel = p.relative_to(root).as_posix()
            for n in ast.walk(tree):
                if not isinstance(n, ast.Compare):
                    continue
                sides = [n.left] + list(n.comparators)
                if len(sides) != 2:
                    continue
                bound = None
                bound_index = None
                for i, side in enumerate(sides):
                    b = _short_bound(side, floor)
                    if b is None:
                        continue
                    if _is_elapsed(sides[1 - i]):
                        bound, bound_index = b, i
                        break
                if bound is None:
                    continue
                branch, negated = _controlled_branch(pm, n)
                if branch is None:
                    continue
                if not _fires_on_exceeding(n, bound_index, negated):
                    continue
                why = _reports_a_finding(branch)
                if why is None:
                    continue
                if _mentions_load(branch):
                    continue
                findings.append({"file": rel, "line": n.lineno,
                                 "bound_s": bound, "reports": why})
    return findings, {"modules_parsed": parsed,
                      "modules_that_spawn": spawning,
                      "short_deadline_findings": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--floor", type=float, default=_DEFAULT_FLOOR,
                    help=f"seconds below which a deadline is reported "
                         f"(default {_DEFAULT_FLOOR})")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] wall_clock_bound_standing_in_for_a_"
                  "verdict: no repository root. NOT a pass.", file=sys.stderr)
            return 2
        if not (a.floor > 0):
            print("[CANNOT DETERMINE] wall_clock_bound_standing_in_for_a_"
                  "verdict: --floor must be positive. NOT a pass.",
                  file=sys.stderr)
            return 2
        findings, denom = scan(root, a.floor)
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"floor_s": a.floor, "denominators": denom,
                 "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] wall_clock_bound_standing_in_for_a_verdict: "
              f"the walk did not complete ({type(exc).__name__}: {exc}). NOT a "
              f"pass.", file=sys.stderr)
        return 2

    print(f"  floor:                     {a.floor} s")
    print(f"  modules parsed:            {denom['modules_parsed']}")
    print(f"  modules that spawn:        {denom['modules_that_spawn']}")
    print(f"  short deadlines asserted:  {denom['short_deadline_findings']}")

    if findings:
        print(f"\n[WARN] {len(findings)} wall-clock bound(s) below {a.floor} s "
              f"decide a finding without stating the load:")
        for f in findings:
            print(f"   {f['file']}:{f['line']}  {f['bound_s']} s -> "
                  f"{f['reports']}")
        print("\n  Carry the load average and the elapsed time in the verdict "
              "message, and\n  state in the bound's own docstring the load it "
              "was chosen under. Where a\n  candidate red compares two arms, "
              "interleave them: run in sequence, the\n  second arm inherits "
              "the first arm's load.")
        if a.strict:
            return 1
        return 0

    # A GREEN FROM AN EMPTY DENOMINATOR IS NOT A PASS. With nothing parsed
    # there is no population, and "no short wall-clock bound decides a finding" is a universally
    # quantified claim over the empty set -- vacuously true, and
    # indistinguishable to a caller from the same sentence over a real tree.
    # `gate_zero_denominator_refuses_check` refuses exactly this shape; it
    # cannot see this file (its population is `*_check.py`), so the refusal is
    # made here instead of relied upon there.
    if denom.get("modules_parsed", 0) == 0:
        print("[CANNOT DETERMINE] wall_clock_bound_standing_in_for_a_verdict: modules parsed is 0 -- "
              "nothing was examined, so there is no verdict. NOT a pass.")
        return 2

    print("[PASS] wall_clock_bound_standing_in_for_a_verdict: no short "
          "wall-clock bound decides a finding in silence about the load.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
