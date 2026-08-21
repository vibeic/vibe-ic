#!/usr/bin/env python3
"""gate_fixture_runner — EXECUTE the fixtures, in both directions.

`gate_mutation_fixture_check` asks whether the two fixtures EXIST. That is a
census, and a census is exactly the kind of evidence this repo keeps finding
insufficient: a fixture file that is never run proves nothing about the gate it
names, the same way a gate that is never invoked proves nothing about the tree.

So the presence check and the EXECUTION are two programs, and both are wired.
This one builds each fixture's subject in a throwaway directory, runs the gate
EXACTLY as `tools/ci/repo_hygiene_gates.sh` declares it, and requires:

    can_pass   rc 0
    can_fail   rc != 0 AND the refusal contains the fragment the fixture
               declares it expects

The second half of the can-fail condition is load-bearing. A gate that refuses
the mutated subject for an unrelated reason — a missing prerequisite, an
argparse error, a traceback — would otherwise be recorded as discriminating.
That is the forged-input shape of vibe-ic#1745 one level up.

EXIT
    0  every fixture present ran and behaved in both directions
    1  a fixture failed in one or both directions
    2  no fixture ran at all — an empty run is not a pass
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_mutation_fixtures as F  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run every gate fixture pair.")
    ap.add_argument("--gate", action="append", default=None,
                    help="run only this gate LABEL (repeatable)")
    ap.add_argument("--script", type=Path, default=None)
    ap.add_argument("--fixtures", type=Path, default=None)
    ap.add_argument("--json", dest="json_out", type=Path, default=None)
    args = ap.parse_args(argv)

    decls = {d.label: d for d in F.declarations(args.script)}
    fixtures = F.load_fixtures(args.fixtures)

    todo = []
    for fx in fixtures.values():
        if not (fx.has_can_pass and fx.has_can_fail):
            continue
        if args.gate and fx.gate not in args.gate:
            continue
        d = decls.get(fx.gate)
        if d is None:
            print(f"[FAIL] {fx.path.name}: GATE {fx.gate!r} is declared by no "
                  f"gate in the dispatcher", file=sys.stderr)
            return 1
        todo.append((d, fx))

    if not todo:
        print("[NOT CHECKED] no complete fixture pair was selected; a run that "
              "executed nothing is not a pass", file=sys.stderr)
        return 2

    results, bad = [], 0
    for d, fx in sorted(todo, key=lambda t: t[1].slug):
        t0 = time.time()
        p, f = F.run_pair(d, fx)
        dt = time.time() - t0
        ok = p.ok and f.ok
        bad += 0 if ok else 1
        results.append({"gate": d.label, "slug": fx.slug, "seconds": round(dt, 1),
                        "can_pass_ok": p.ok, "can_fail_ok": f.ok,
                        "can_pass": p.detail, "can_fail": f.detail})
        tag = "PASS" if ok else "FAIL"
        print(f"  {tag}  {d.label}  ({dt:.1f}s)")
        if not p.ok:
            print(f"        can_pass: {p.detail}", file=sys.stderr)
        if not f.ok:
            print(f"        can_fail: {f.detail}", file=sys.stderr)

    if args.json_out:
        args.json_out.write_text(json.dumps(results, indent=2) + "\n")

    if bad:
        print(f"[FAIL] gate_fixture_runner: {bad} of {len(results)} fixture "
              f"pair(s) did not discriminate", file=sys.stderr)
        return 1
    print(f"[PASS] gate_fixture_runner: {len(results)} fixture pair(s) ran; "
          f"each gate accepted its known-good subject and rejected its "
          f"mutation for the declared reason.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
