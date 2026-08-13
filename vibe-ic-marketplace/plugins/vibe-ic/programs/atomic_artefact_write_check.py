#!/usr/bin/env python3
"""atomic_artefact_write_check.py — a declared artefact must not appear before
it is complete. vibe-ic#1082.

THIS GATE BLOCKS (rc=1) on any NEW non-atomic artefact write.

WHY A RATCHET AND NOT A SWEEP
-----------------------------
The invariant is worth having everywhere (`_atomic_write`'s docstring argues
it), but MEASURED on `a38902d16` the population is:

    713 programs write a file at all (`write_text` / `json.dump`)
    548 write through their OWN `--json` argument — the artefact class the
        flow's gates actually consult
      0 use `os.replace`, i.e. there was no atomic writer in the tree

A 548-file diff is not reviewable, and a sweep that large lands by being waved
through, which is the opposite of what this repository does. So the repair is
split: `_atomic_write` is the seam, this gate is the ratchet that stops the
population GROWING, and conversion happens in reviewable tranches that each
lower the recorded number.

That ordering matters. Without the ratchet, every conversion tranche races new
non-atomic writers being added faster than they are removed — which is how the
count reached 548 with nobody deciding it should.

548 IS THE SECOND NUMBER THIS GATE MEASURED, AND THE FIRST ONE WAS WRONG.
The detector first matched only writes whose receiver expression itself named
`args.json`, which missed `out = Path(args.json); out.write_text(...)` — the
dominant spelling here — and reported 533. The gap was found by converting
three programs and watching the count fall by two. `_json_aliases` closes it;
see its docstring. The baseline was re-derived through `--ruler-widened`, which
exists so a widening is RECORDED rather than absorbed.

WHAT IT MEASURES
----------------
A program is an OFFENDER when both hold, decided by AST and never by grep:

  * it declares a `--json` command-line argument, i.e. the caller names the
    artefact and the flow can consult it; and
  * it writes through that argument (`write_text` / `write_bytes` / `json.dump`
    on a receiver derived from `args.json` and its spellings) WITHOUT going
    through `_atomic_write`.

AST rather than text, for the reason this codebase keeps relearning: a comment
or a docstring mentioning `--json` is not a call site, and PR #460 shipped a
broken change because a grep could not tell the difference.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* It does not judge the 180 programs that write something other than their
  `--json` target. Logs, scratch files and caches are not artefacts the flow
  reads a verdict out of; widening the ruler to them would inflate the number
  without adding meaning.
* It does not check that the write SUCCEEDED, only that a reader cannot observe
  it half-done. Whether the content is right is every other gate's job.

chip-AGNOSTIC: no design, PDK or vendor literal decides anything.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

_HERE = Path(__file__).resolve().parent
BASELINE_NAME = "atomic_artefact_write_baseline.json"

#: The argparse option that makes an artefact the CALLER's to name, and so the
#: flow's to consult.
_JSON_OPT = "--json"

#: Receiver names that mean "the --json target". `argparse` stores `--json`
#: as `args.json` unless `dest=` says otherwise; the extra spellings are the
#: local variables this tree assigns it to before writing.
_JSON_NAMES: Set[str] = {"json", "json_out", "json_path", "out_json"}

#: The write calls that can land a partial file under a final name.
_WRITE_ATTRS = {"write_text", "write_bytes", "dump"}

#: Importing the seam in any spelling counts as adoption; the gate does not
#: care which helper of it is used.
_SEAM = "_atomic_write"


def _declares_json_arg(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument":
            for a in n.args:
                if isinstance(a, ast.Constant) and a.value == _JSON_OPT:
                    return True
    return False


def _imports_seam(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            if any(al.name.endswith(_SEAM) for al in n.names):
                return True
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").endswith(_SEAM):
                return True
    return False


def _json_aliases(tree: ast.AST) -> Set[str]:
    """Local names bound to the `--json` target.

    THE FIRST VERSION OF THIS GATE DID NOT DO THIS, AND IT COST ACCURACY.
    It matched only writes whose receiver expression itself mentioned
    `args.json`, so the dominant spelling in this tree —

        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(...)

    — was invisible, because the receiver is `out`. Measured: it under-counted
    by missing `gate_skip_routing_check.py` entirely, and a NEW offender written
    in that style would have passed the ratchet. A ratchet with a hole is worse
    than no ratchet, because it reports a number nobody re-derives.

    One pass, module-wide rather than per-function: an alias is any Name
    assigned from an expression that mentions a `--json` spelling. Module-wide
    over-approximates (two functions could reuse the name `out` for different
    things), and that direction is the safe one here — the cost is judging a
    write that was already going to be judged, never missing one.
    """
    alias: Set[str] = set(_JSON_NAMES)
    # Iterate to a fixed point: `p = args.json` then `q = Path(p)`.
    for _ in range(4):
        grew = False
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                continue
            tgt = n.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            dumped = ast.dump(n.value)
            if any(f"attr='{x}'" in dumped or f"id='{x}'" in dumped
                   for x in alias):
                if tgt.id not in alias:
                    alias.add(tgt.id)
                    grew = True
        if not grew:
            break
    return alias


def _writes_through_json(tree: ast.AST) -> int:
    names = _json_aliases(tree)
    hits = 0
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if getattr(n.func, "attr", "") not in _WRITE_ATTRS:
            continue
        dumped = ast.dump(n)
        if any(f"attr='{x}'" in dumped or f"id='{x}'" in dumped
               for x in names):
            hits += 1
    return hits


def offenders(programs_dir: Path) -> List[str]:
    """Programs that name an artefact via --json and write it non-atomically."""
    out: List[str] = []
    for p in sorted(programs_dir.glob("*.py")):
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except SyntaxError:
            continue
        if not _declares_json_arg(tree):
            continue
        if not _writes_through_json(tree):
            continue
        if _imports_seam(tree):
            continue
        out.append(p.name)
    return out


def _load_baseline(p: Path) -> Optional[Dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("programs_dir", nargs="?", default=str(_HERE))
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT offender set; it may only shrink")
    ap.add_argument("--ruler-widened", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the DETECTOR now sees more than it did — not because "
                         "more offenders were written. Modelled on "
                         "evidence_citation_resolves_check --scope-expanded: a "
                         "wider ruler finding pre-existing debt is not a "
                         "regression, but it must be RECORDED, not assumed.")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)

    pdir = Path(args.programs_dir).resolve()
    found = offenders(pdir)
    bl_path = Path(args.baseline) if args.baseline else _HERE / BASELINE_NAME

    print(f"atomic_artefact_write_check: {len(found)} program(s) name an "
          f"artefact via {_JSON_OPT} and write it non-atomically, under {pdir}")

    if args.json_out:
        # Dogfooding: this gate writes its OWN report through the seam.
        from _atomic_write import write_json_atomic
        write_json_atomic(args.json_out,
                          {"offenders": found, "count": len(found)})

    if args.write_baseline:
        from _atomic_write import write_json_atomic
        prev = _load_baseline(bl_path)
        if (prev and len(found) > len(prev.get("offenders", []))
                and not args.ruler_widened):
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(prev.get('offenders', []))} -> {len(found)}). This "
                  f"ratchet exists to stop the population growing; a rise is a "
                  f"regression to fix, not a number to record. If the DETECTOR "
                  f"now sees more than it did, say so with "
                  f"--ruler-widened '<why>'.")
            return 1
        write_json_atomic(bl_path, {
            "_comment": ("Programs that name an artefact via --json and write "
                         "it non-atomically (vibe-ic#1082). MAY ONLY SHRINK. "
                         "Convert one by importing programs/_atomic_write and "
                         "writing through it; the wrong repair is to stop "
                         "declaring --json."),
            "count": len(found),
            "offenders": found,
            **({"ruler_widened": args.ruler_widened}
               if args.ruler_widened else {}),
        })
        print(f"wrote {bl_path} ({len(found)} offender(s))")
        return 0

    bl = _load_baseline(bl_path)
    if bl is None:
        print(f"[FAIL] no baseline at {bl_path}; run --write-baseline once and "
              f"commit it, or this gate can never say anything")
        return 1

    recorded = set(bl.get("offenders", []))
    new = sorted(set(found) - recorded)
    gone = sorted(recorded - set(found))

    if new:
        print(f"[FAIL] {len(new)} NEW non-atomic artefact write(s) — a reader "
              f"can observe these files half-written under their final name, "
              f"and every check that opens one inherits the lie:")
        for n in new:
            print(f"   {n}")
        print(f"Write through `programs/_atomic_write.py` "
              f"(`write_json_atomic(args.json, payload)`).")
        return 1

    if gone:
        print(f"[PASS] {len(recorded)} -> {len(found)}; {len(gone)} converted. "
              f"Lower the baseline so the record stops claiming debt that is "
              f"paid: --write-baseline")
        return 0

    print(f"[PASS] no NEW non-atomic artefact write ({len(recorded)} recorded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
