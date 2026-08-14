#!/usr/bin/env python3
"""atomic_artifact_write_check.py — a gate report must appear whole or not at all
(vibe-ic#1082).

WHAT IT MEASURES
================
For every shipped program that declares a report destination on its CLI
(`--json`, `--out`, `--output`, `--report`), every write whose TARGET traces
back to that destination must go through `_atomic_artefact`. A direct
`dest.write_text(...)` / `open(dest, "w")` creates the final name first and
fills it second, so a writer that dies in between leaves a truncated artefact
under the name a `required_outputs` check reads as "the step produced this".

WHY THIS POPULATION AND NOT "EVERY WRITE"
=========================================
Most writes in this tree are into `tmp_path`, into a scratch dir, or into a
staging area nothing declares. Those can be partial without lying to anyone —
no consumer resolves them, and no step's verdict rests on their existence. The
writes that MATTER are the ones a later reader treats as evidence, and the
CLI report destination is the mechanically-identifiable form of that: it is the
path the flow's `gate:` line names with `--json`, and therefore the path
`check_step` and every downstream consumer opens.

Narrow on purpose. A rule that fires on every `open(..., "w")` in 1078 programs
is a rule that gets read as noise and waived wholesale.

THE RESIDUAL, AND WHY IT IS PUBLISHED RATHER THAN WAIVED
========================================================
The tree did not start atomic. Converting every offender in one change would be
a 600-file sweep that no one can review, so the gate ships with a RESIDUAL: the
offenders present when it landed are recorded in `_ATOMIC_RESIDUAL_BASELINE`
and reported every run, by name and by count. What is BLOCKING is the delta —
a program that becomes an offender, or a NEW program that lands as one.

That is the only shape that is honest here. A silent allow-list would let the
number grow back; a hard fail on day one would be reverted within the hour. The
residual is printed on every run precisely so it cannot be forgotten, and it
may only ever shrink — `--strict` fails if it GREW, which is the ratchet.

exit 0 = PASS         no new offender (residual may still be non-zero, and is named)
exit 1 = FAIL         a new offender, or the residual grew
exit 2 = NOT CHECKED  the programs directory is unreadable / no program parsed
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

HELPER_MODULE = "_atomic_artefact"

#: CLI destinations whose value is an artefact a later reader resolves.
_DEST_FLAGS = ("--json", "--out", "--output", "--report")

#: Write forms that create the final name before filling it.
_DIRECT_WRITE_METHODS = {"write_text", "write_bytes"}


def _dest_arg_names(tree: ast.AST) -> Set[str]:
    """argparse destinations for the report flags, as attribute names.

    `add_argument("--json")` -> args.json ; `--out-dir` -> args.out_dir. The
    explicit `dest=` form wins when present, exactly as argparse resolves it.
    """
    names: Set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not any(f in _DEST_FLAGS for f in flags):
            continue
        explicit = next((kw.value.value for kw in node.keywords
                         if kw.arg == "dest"
                         and isinstance(kw.value, ast.Constant)), None)
        if explicit:
            names.add(str(explicit))
            continue
        for f in flags:
            if f.startswith("--"):
                names.add(f[2:].replace("-", "_"))
    return names


def _mentions(node: ast.AST, names: Set[str]) -> bool:
    """Does this expression reach one of the report destinations?

    Deliberately generous: `Path(args.json)`, `out_json`, `Path(args.json) /
    "x"` all count. A generous TARGET test with a narrow POPULATION is the
    right way round — the alternative under-reports, and an under-reporting
    gate is the failure mode this whole file exists to remove.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in names:
            return True
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
    return False


def scan_program(path: Path) -> List[Dict[str, Any]]:
    """Non-atomic writes to this program's own report destination."""
    try:
        src = path.read_text(errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []
    dests = _dest_arg_names(tree)
    if not dests:
        return []
    # A local variable assigned FROM a destination inherits it: `out =
    # Path(args.json)` makes `out` a destination name too. One hop is enough
    # for every shape in this tree and keeps the rule explainable.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _mentions(node.value, dests):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    dests.add(t.id)

    findings: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _DIRECT_WRITE_METHODS \
                and _mentions(node.func.value, dests):
            findings.append({"line": node.lineno,
                             "form": f".{node.func.attr}(...)"})
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "open" and len(node.args) >= 2:
            mode = node.args[1]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                    and ("w" in mode.value or "a" in mode.value) \
                    and _mentions(node.args[0], dests):
                findings.append({"line": node.lineno,
                                 "form": f"open(..., {mode.value!r})"})
    return findings


def audit(programs_dir: Path) -> Dict[str, Any]:
    offenders: Dict[str, List[Dict[str, Any]]] = {}
    parsed = 0
    for p in sorted(programs_dir.glob("*.py")):
        parsed += 1
        hits = scan_program(p)
        if hits:
            offenders[p.name] = hits
    return {"programs_parsed": parsed,
            "offenders": offenders,
            "offender_count": len(offenders)}


def _load_baseline(path: Path) -> Set[str]:
    if not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text()).get("offenders", []))
    except (OSError, ValueError):
        return set()


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("programs_dir", nargs="?", default=None)
    ap.add_argument("--baseline", default=None,
                    help="JSON holding the residual this gate ratchets down")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="also fail if the residual GREW without a new name")
    args = ap.parse_args(argv)

    pdir = Path(args.programs_dir) if args.programs_dir \
        else Path(__file__).resolve().parent
    if not pdir.is_dir():
        print(f"NOT CHECKED: {pdir} is not a directory", file=sys.stderr)
        return 2

    rep = audit(pdir)
    if not rep["programs_parsed"]:
        print(f"NOT CHECKED: no program parsed under {pdir}", file=sys.stderr)
        return 2

    bl_path = Path(args.baseline) if args.baseline \
        else pdir / "_atomic_artefact_residual.json"
    baseline = _load_baseline(bl_path)
    current = set(rep["offenders"])
    new = sorted(current - baseline)
    fixed = sorted(baseline - current)

    rep.update({"baseline_size": len(baseline), "new_offenders": new,
                "fixed_since_baseline": fixed,
                "baseline_file": str(bl_path)})

    print(f"atomic_artifact_write_check: {rep['programs_parsed']} program(s) "
          f"parsed; {rep['offender_count']} write their declared report "
          f"destination NON-atomically (residual baseline {len(baseline)})")
    if fixed:
        print(f"  converted since the baseline ({len(fixed)}): "
              f"{', '.join(fixed[:8])}{' …' if len(fixed) > 8 else ''}")
    # THE RESIDUAL IS NAMED ON EVERY RUN. A number nobody sees is a number
    # nobody works down; this is the line that keeps it from going quiet.
    still = sorted(current & baseline)
    if still:
        print(f"  residual, not yet converted ({len(still)}): "
              f"{', '.join(still[:8])}{' …' if len(still) > 8 else ''}")

    if args.json_out:
        try:
            from _atomic_artefact import write_json
            write_json(args.json_out, rep)
        except ImportError:                      # pragma: no cover
            Path(args.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if new:
        print(f"[FAIL] {len(new)} program(s) newly write a declared report "
              f"destination without _atomic_artefact:", file=sys.stderr)
        for name in new:
            for h in rep["offenders"][name]:
                print(f"   {name}:{h['line']}  {h['form']}", file=sys.stderr)
        print("  Remedy: `from _atomic_artefact import write_json` and "
              "write through it. See vibe-ic#1082.", file=sys.stderr)
        return 1
    if args.strict and len(current) > len(baseline):
        print(f"[FAIL] residual grew {len(baseline)} -> {len(current)}",
              file=sys.stderr)
        return 1
    print("[PASS] no new non-atomic declared-report write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
