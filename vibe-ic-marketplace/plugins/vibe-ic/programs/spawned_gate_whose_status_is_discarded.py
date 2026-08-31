#!/usr/bin/env python3
"""A gate spawned as a subprocess whose verdict reaches nothing.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A gate spawned as a subprocess delivers its verdict in its exit status. When
the caller leaves the result UNBOUND, turns OFF raise-on-failure, and encloses
the call in a handler that swallows every exception, the verdict reaches
nothing — and a comment beside the call can describe it as blocking with no
reader noticing the contradiction. A call whose status no branch reads costs
time and decides nothing.

TWO CLAUSES, BECAUSE THE CLASS HAS TWO SHAPES
=============================================
CLAUSE A — THE DISCARDED SPAWN. A `subprocess` call whose argv names a
checking program, where ALL THREE hold:

    * the result is not bound to a name (a bare expression statement), and
    * `check=` is absent or False, and
    * the call is enclosed by a handler catching `Exception`/bare, which does
      not re-raise.

All three, deliberately. A bare spawn with `check=True` raises and IS a gate.
A bound result whose status some branch reads IS a gate. Only the conjunction
is the call that LOOKS blocking and is not — which is the state a comment
above it can describe as blocking without anyone noticing.

CLAUSE B — THE MIRROR. A program whose SUBJECT is whether something RAN, with
no way to start a process and no way to read a status: zero occurrences of
`subprocess`, `Popen`, `os.system`, `returncode` and `rc` anywhere in it. Such
a program decides by matching a command line as TEXT, and publishes a verdict
about something it never observed.

The two were found by different lanes on the same day, from different
directions, which is why one rule carries both.

COVERAGE, MEASURED — and the two clauses are NOT equal
=======================================================
CLAUSE A IS A RULE. Population on the tree this shipped with, restated at the
merge with main a4caccefe (v1.11.69): 669 modules contain a handler that
swallows everything, out of 4223 parsed. It returns 5, of which FOUR were found
by asking the repository rather than by anyone noticing. It generalises -- and
the population growing from 654 to 669 under 214 commits of main WITHOUT the
finding count moving is the useful part: the clause tracked a tree it had never
seen and still found the same five.

CLAUSE B IS A REGRESSION GUARD, NOT A RULE, AND SAYING SO IS THE POINT. Its
population is **1** — `full_suite_run_check.py`, which is the instance the
capture measured. It finds 1 of 1. By the standard this repository holds its
own gates to, that makes it a regression test wearing a rule's name, and it is
labelled here rather than left to read as coverage.

WIDENING IT WAS TRIED AND MEASURED, not assumed impossible. The name-shaped
population is itself the defect `invocation_proved_by_parse_not_by_text`
describes — a population defined by a NAME rather than by STRUCTURE. The
structural replacement is to read the module's own DOCSTRING NODE and take the
programs that CLAIM their subject is whether something ran:

    structural population                                    24
    of those, flagged by "no subprocess / Popen / returncode" 15

Fifteen is not coverage, it is noise. The flag condition assumes that observing
a run requires SPAWNING one, and it does not: reading a run's artefact — a
report, a log, a JSON record — is the normal and correct way, and most of those
15 do exactly that. The widened form would ship a false positive on a dozen
sound checkers.

So clause B stays narrow and stays labelled. What it actually guards is the
re-introduction of one specific shape: a program whose subject is a RUN, with
no artefact to read AND no way to start or observe a process. A future lane
that wants a real rule here needs a predicate for "has no evidence to read
either", which is a different question from the one this clause asks.

DECLARING A SPAWN ADVISORY
==========================
Where a spawn is deliberately advisory, say so at the call site — a comment
containing `ADVISORY` on the call's own line or the line above. That makes it a
decision on the record rather than an absence inferred from silence, and this
gate reads it and is satisfied.

EXIT
====
  0  no discarded gate spawn, no run-subject program that cannot run anything
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

_INVENTORY_NAME = "spawned_gate_status_inventory.json"

_SPAWNERS = ("run", "call", "check_call", "check_output", "Popen")

#: `os.system` / `os.popen` are spawns too, and `os.system` is the archetypal
#: DISCARDED status: it returns an exit code and has no `check=` at all. They
#: are matched only on the `os` module, so an unrelated `.system()` method on
#: some other object is not a spawn.
#:
#: ADDED 2026-08-22 by an audit of this file's OWN enumerations, prompted by
#: six instrument errors in one session that were all the same shape: a list of
#: the cases I expected, not of the cases the tree uses. There are ZERO real
#: `os.system` call sites today — both occurrences are strings inside test
#: fixtures — so this closes a latent gap and changes no finding.
_OS_SPAWNS = ("system", "popen")


def _is_os_spawn(node) -> bool:
    f = getattr(node, "func", None)
    return (isinstance(f, ast.Attribute) and f.attr in _OS_SPAWNS
            and isinstance(f.value, ast.Name) and f.value.id == "os")


#: An argv element naming a checking program.
#: A checker named in an argv. The name may END the string (an element of
#: an argv LIST) or sit mid-string (a `os.system` command line), so the
#: trailing anchor is a word boundary and not `$`. MEASURED: with `$` the
#: os.system form was invisible even after `os.system` was added to the
#: spawn set — widening the spawn list alone closed nothing, and the test
#: that proves the firing is what found it.
_CHECKER_RE = re.compile(
    r"[\w/]*(?:_check|_audit|_gate|_gates|_scan)\.py(?=[\s'\"]|$)")

#: Clause B: the tokens a program needs to start a process or read a status.
#:
#: `run_supervised` IS ONE OF THEM, and leaving it out made this clause
#: contradict `loop_watchdog_compliance_check`. That gate's class (c) REQUIRES an
#: opaque `bash <script>` spawn to be routed through `_watchdog.run_supervised`;
#: this clause reads a file with none of the other six tokens as unable to
#: observe a run. `full_suite_run_check.py` is the ONLY member of clause B's
#: population AND is the file the watchdog gate named, so obeying one gate broke
#: the other and no honest state of that file satisfied both.
#:
#: It is not a widening of convenience. `run_supervised` launches the child
#: (`popen_factory`, defaulting to a host `Popen`), supervises it by forward
#: progress, and returns a `SupervisedResult` whose `.rc` is the process's own
#: return code — RC_STALLED / RC_CEILING when it had to kill it. A caller that
#: reads that `.rc` has observed a run in exactly the sense this clause means,
#: and the clause's own words are "no way to start a process and no way to read
#: a status", not "does not contain the string `subprocess`".
_RUN_TOKENS = ("subprocess", "Popen", "os.system", "returncode",
               "check_output", "check_call", "run_supervised")

#: Clause B population: a program whose own name puts the RUN immediately
#: before the verdict word, so the run IS the subject. `run_output_
#: completeness_check` starts with `run_` and its subject is the OUTPUT, not
#: the run — measured as a false positive when the prefix form was used.
_RUN_SUBJECT_RE = re.compile(r"_(?:run|ran|execution)_(?:check|audit|gate)\.py$")


def _names_a_checker(node: ast.Call) -> Optional[str]:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if _CHECKER_RE.search(sub.value):
                return sub.value.rsplit("/", 1)[-1]
        if isinstance(sub, ast.JoinedStr):
            joined = "".join(v.value for v in sub.values
                             if isinstance(v, ast.Constant)
                             and isinstance(v.value, str))
            if _CHECKER_RE.search(joined):
                return joined.rsplit("/", 1)[-1]
    return None


def _is_spawn(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    attr = f.attr if isinstance(f, ast.Attribute) else (
        f.id if isinstance(f, ast.Name) else None)
    return attr in _SPAWNERS or _is_os_spawn(node)


def _check_is_on(node: ast.Call) -> bool:
    for k in node.keywords:
        if k.arg == "check":
            return not (isinstance(k.value, ast.Constant)
                        and k.value.value is False)
    return False


def _swallowing_handlers(tree: ast.AST) -> List[Tuple[int, int]]:
    """(start, end) line spans of `try` bodies whose handler swallows all."""
    spans: List[Tuple[int, int]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Try):
            continue
        for h in n.handlers:
            catches_all = h.type is None or (
                isinstance(h.type, ast.Name) and h.type.id in
                ("Exception", "BaseException"))
            if not catches_all:
                continue
            if any(isinstance(x, ast.Raise) for x in ast.walk(h)):
                continue
            lo = min(s.lineno for s in n.body)
            hi = max(getattr(s, "end_lineno", s.lineno) for s in n.body)
            spans.append((lo, hi))
            break
    return spans


def _advisory_here(lines: List[str], lineno: int) -> bool:
    for i in (lineno - 1, lineno - 2):
        if 0 <= i < len(lines) and "ADVISORY" in lines[i]:
            return True
    return False


def scan_clause_a(path: Path, root: Path) -> List[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError, ValueError):
        return []
    lines = text.splitlines()
    spans = _swallowing_handlers(tree)
    if not spans:
        return []
    rel = path.relative_to(root).as_posix()
    out: List[dict] = []
    for n in ast.walk(tree):
        # UNBOUND: the call is the whole statement.
        if not isinstance(n, ast.Expr) or not _is_spawn(n.value):
            continue
        call = n.value
        gate = _names_a_checker(call)
        if gate is None or _check_is_on(call):
            continue
        if not any(lo <= n.lineno <= hi for lo, hi in spans):
            continue
        if _advisory_here(lines, n.lineno):
            continue
        out.append({"clause": "A", "file": rel, "line": n.lineno, "gate": gate})
    return out


def _code_only(text: str) -> str:
    """`text` with every comment and string literal blanked out.

    MEASURED, and it is why this exists: with the raw text, the string
    `subprocess` surviving in ONE COMMENT was enough to keep clause B green over
    a program that had no way left to start a process. A prose mention is not an
    invocation — this file's own COVERAGE section names
    `invocation_proved_by_parse_not_by_text` as the defect to avoid, and a
    substring test over comments is that defect.

    Positions are preserved (blanks, not deletions) so a line number taken from
    the AST still lines up. A file that will not tokenize falls back to the raw
    text, which is the previous behaviour and the conservative direction: it can
    only make the clause say LESS, never more.
    """
    try:
        import io
        import tokenize
        out = list(text)
        lines = [0]
        for ln in text.splitlines(keepends=True):
            lines.append(lines[-1] + len(ln))
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            a, b = lines[r1 - 1] + c1, lines[r2 - 1] + c2
            for i in range(a, min(b, len(out))):
                if out[i] != "\n":
                    out[i] = " "
        return "".join(out)
    except Exception:                       # noqa: BLE001 — see the docstring
        return text


def scan_clause_b(path: Path, root: Path) -> List[dict]:
    # A test ABOUT such a program is not such a program.
    if "tests" in path.parts:
        return []
    if not _RUN_SUBJECT_RE.search(path.name):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if any(tok in _code_only(text) for tok in _RUN_TOKENS):
        return []
    return [{"clause": "B", "file": path.relative_to(root).as_posix(),
             "line": 1, "gate": path.name}]


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    clause_a_pop = 0
    clause_b_pop = 0
    bases = [root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
             root / "tools"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "node_modules" in p.parts:
                continue
            parsed += 1
            try:
                _t = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                if _swallowing_handlers(_t):
                    clause_a_pop += 1
            except (OSError, SyntaxError, ValueError):
                pass
            if "tests" not in p.parts and _RUN_SUBJECT_RE.search(p.name):
                clause_b_pop += 1
            a = scan_clause_a(p, root)
            findings.extend(a)
            findings.extend(scan_clause_b(p, root))
    return findings, {"modules_parsed": parsed,
                      "clause_a_population": clause_a_pop,
                      "clause_b_population": clause_b_pop,
                      "clause_a_findings": sum(1 for f in findings
                                               if f["clause"] == "A"),
                      "clause_b_findings": sum(1 for f in findings
                                               if f["clause"] == "B")}


def _key(f: dict) -> str:
    return f"{f['clause']}::{f['file']}::{f['gate']}"


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
            print("[CANNOT DETERMINE] spawned_gate_whose_status_is_discarded: "
                  "no repository root. NOT a pass.", file=sys.stderr)
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
        print(f"[CANNOT DETERMINE] spawned_gate_whose_status_is_discarded: the "
              f"walk did not complete ({type(exc).__name__}: {exc}). NOT a "
              f"pass.", file=sys.stderr)
        return 2

    print(f"  modules parsed:                 {denom['modules_parsed']}")
    print(f"  clause A population:            {denom['clause_a_population']}"
          f"   (modules with a swallow-all handler)")
    print(f"  discarded gate spawns (A):      {denom['clause_a_findings']}")
    print(f"  clause B population:            {denom['clause_b_population']}"
          f"   <- a REGRESSION GUARD, not a rule; see COVERAGE")
    print(f"  run-subject, cannot run (B):    {denom['clause_b_findings']}")
    print(f"  inventory rows applied:         {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} gate spawn(s) whose verdict reaches "
              f"nothing:")
        for f in findings:
            if _key(f) in new:
                if f["clause"] == "A":
                    print(f"   {f['file']}:{f['line']}  spawns {f['gate']} — "
                          f"result unbound, check off, inside a handler that "
                          f"swallows everything")
                else:
                    print(f"   {f['file']}  its subject is whether something "
                          f"RAN, and it can neither start a process nor read a "
                          f"status")
        print("\n  Bind the result and read its status, or say ADVISORY at the "
              "call site so\n  the decision is on the record rather than "
              "inferred from silence.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] spawned_gate_whose_status_is_discarded: every spawned "
              "gate's verdict is read or declared advisory.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
