#!/usr/bin/env python3
"""gate_mutation_fixture_check — every gate must carry fixtures in BOTH directions.

THIS GATE BLOCKS (rc=1) on a gate that has neither fixture and is not in the
baseline, on a gate whose baseline entry has become stale, and on a fixture
that is bound to no declared gate.

WHY
===
A gate proven only to PASS on good input has not been shown to discriminate.
Two failures of exactly that shape landed in this repo in one day: a check that
passes until its input is FORGED (vibe-ic#1745), and a check that reported a
decided verdict over ten gates it never ran.

`flow_step_can_fail_check` already asks the question of the 63 FLOW steps and
holds the answer to a baseline that may only shrink. Nothing asked it of the
gates in `tools/ci/repo_hygiene_gates.sh` — the set that decides whether a
change LANDS. This gate does, and it asks for evidence rather than for a
promise: not "does a criterion exist that could fail" but "here is an input
this gate accepts, and here is the mutation of it this gate rejects, and both
were EXECUTED against the command the dispatcher really runs."

THE REQUIREMENT
===============
For every gate the dispatcher declares, `tools/ci/gate_fixtures/<slug>.py`
must define BOTH `can_pass` and `can_fail`. See `gate_mutation_fixtures` for
the protocol and for why the fixture may choose the INPUT and never the ARGV.

A gate carrying only ONE of the two is a finding in its own right and is
reported as `HALF` — it is not a lesser version of having both, it is the
specific claim this file exists to refuse.

WHY A BASELINE, AND WHAT IT MAY NOT DO
======================================
MEASURED at 397b3f25f, before this change: 83 gates declared, 0 with a
can-fail fixture, 0 with both — the convention did not exist, so the honest
count is zero and not a generous estimate of it. Failing 83 gates on day one
produces a gate people route around, which is how the repo argued the same
point for `flow_step_can_fail_check` and for `silent_decline_audit`.

So the baseline in `gate_fixture_debt.json` names every gate that does not yet
carry both, WITH the reason it does not, and:

  * it MAY ONLY SHRINK — an entry may be deleted by writing the fixtures, and
    a gate outside it that lacks them FAILS;
  * a NEW gate is outside it by construction, so a gate added without both
    fixtures cannot land. That is the property worth having;
  * an entry whose gate already HAS both fixtures is STALE and fails, so the
    register cannot rot into a list of excuses nobody re-reads;
  * an entry naming a gate the dispatcher no longer declares is stale for the
    same reason and fails the same way. A renamed gate loses its slug, which
    is loud here rather than silent.

The reason field is not decoration. Three of the classes it records are
findings this exercise produced and could not have produced any other way:

    RUNTIME_EXPANDED  the declaration's subject is a loop variable only bash
                      can bind; the gate runs per published cell and there is
                      no cell in a bare checkout.
    SUBJECT_FIXED     the gate takes no subject argument and reads its OWN
                      installation, so no fixture can mutate its input without
                      editing the repository under test.
    CANNOT_FAIL       the gate is declared ADVISORY: with the argv the
                      dispatcher passes, findings exit 0. Its can-fail
                      direction does not exist to be written.

EXIT
    0  every declared gate has both fixtures or a live, accurate baseline entry
    1  a gate outside the baseline lacks a fixture, or the baseline is stale
    2  the declaration site could not be read, or nothing was declared —
       a census over zero gates is not a clean census

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_mutation_fixtures as F  # noqa: E402


def census(script: Optional[Path] = None,
           fixture_dir: Optional[Path] = None,
           debt_file: Optional[Path] = None) -> dict:
    """The three numbers, and everything needed to justify each one."""
    decls = F.declarations(script)
    fixtures = F.load_fixtures(fixture_dir)
    debt = F.load_debt(debt_file)
    excused = F.debt_labels(debt)

    by_slug = {F.slug(d.label): d for d in decls}
    collisions = F.slug_collisions([d.label for d in decls])

    both, only_pass, only_fail, neither = [], [], [], []
    mismatched: List[str] = []
    for d in decls:
        s = F.slug(d.label)
        fx = fixtures.get(s)
        if fx is None:
            neither.append(d.label)
            continue
        if fx.gate != d.label:
            mismatched.append(
                f"{fx.path.name}: GATE = {fx.gate!r} but the gate at "
                f"{F.HYGIENE_SCRIPT.name}:{d.lineno} is declared {d.label!r}")
        if fx.has_can_pass and fx.has_can_fail:
            both.append(d.label)
        elif fx.has_can_pass:
            only_pass.append(d.label)
        elif fx.has_can_fail:
            only_fail.append(d.label)
        else:
            neither.append(d.label)

    orphans = [fx.path.name for s, fx in sorted(fixtures.items())
               if s not in by_slug]

    have_fail = sorted(set(both) | set(only_fail))
    return {
        "declared": len(decls),
        "with_can_fail": len(have_fail),
        "with_both": len(both),
        "both": sorted(both),
        "only_can_pass": sorted(only_pass),
        "only_can_fail": sorted(only_fail),
        "neither": sorted(neither),
        "gate_label_mismatch": mismatched,
        "orphan_fixtures": orphans,
        "slug_collisions": {k: v for k, v in collisions.items()},
        "baseline_entries": len(excused),
        "excused": excused,
    }


def _verdict(c: dict) -> tuple[int, List[str]]:
    """rc and the violations, computed from the census alone."""
    v: List[str] = []
    excused = c["excused"]
    declared_labels = set(c["both"]) | set(c["only_can_pass"]) \
        | set(c["only_can_fail"]) | set(c["neither"])

    for slug_, labels in c["slug_collisions"].items():
        v.append(f"two gates share the fixture slug {slug_!r}: "
                 + " / ".join(repr(x) for x in labels)
                 + " — their evidence would be merged, so this is refused "
                   "rather than resolved by guessing")
    v.extend(c["gate_label_mismatch"])
    for name in c["orphan_fixtures"]:
        v.append(f"{name} is a fixture for no gate the dispatcher declares — "
                 f"either the gate was renamed (write the fixture under its new "
                 f"slug) or deleted (delete this file). A fixture nothing runs "
                 f"is the shape this gate exists to remove.")

    for lb in c["only_can_pass"]:
        v.append(f"HALF: {lb!r} carries a can-pass fixture and NO can-fail. "
                 f"A gate shown only to accept good input has not been shown "
                 f"to discriminate.")
    for lb in c["only_can_fail"]:
        v.append(f"HALF: {lb!r} carries a can-fail fixture and NO can-pass. "
                 f"Loud is not the same as correct: nothing here shows the gate "
                 f"is quiet on a clean tree.")
    for lb in c["neither"]:
        if lb not in excused:
            v.append(f"NEW-OR-UNEXCUSED: {lb!r} carries neither fixture and is "
                     f"not in {F.DEBT_FILE.name}. A gate lands with both "
                     f"directions or it does not land.")

    for lb, why in sorted(excused.items()):
        if lb not in declared_labels:
            v.append(f"STALE BASELINE: {lb!r} is excused in "
                     f"{F.DEBT_FILE.name} but the dispatcher no longer declares "
                     f"it. Delete the entry, or restore the gate.")
        elif lb in c["both"]:
            v.append(f"STALE BASELINE: {lb!r} now carries BOTH fixtures but is "
                     f"still excused in {F.DEBT_FILE.name}. Delete the entry — "
                     f"a baseline that outlives its reason is a list of excuses "
                     f"nobody re-reads.")
        elif not why.strip():
            v.append(f"UNREASONED BASELINE: {lb!r} is excused with no reason. "
                     f"An exemption is a promise to revisit, and one with no "
                     f"reason cannot be revisited.")
    return (1 if v else 0), v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Every gate in the dispatcher must carry a can-pass AND a "
                    "can-fail fixture.")
    ap.add_argument("--script", type=Path, default=None,
                    help="the gate declaration site "
                         "(default: tools/ci/repo_hygiene_gates.sh)")
    ap.add_argument("--fixtures", type=Path, default=None,
                    help="the fixture directory "
                         "(default: tools/ci/gate_fixtures)")
    ap.add_argument("--debt", type=Path, default=None,
                    help="the shrink-only baseline "
                         "(default: tools/ci/gate_fixture_debt.json)")
    ap.add_argument("--json", dest="json_out", type=Path, default=None,
                    help="write the census here")
    ap.add_argument("--census-only", action="store_true",
                    help="print the three numbers and exit 0 without judging")
    args = ap.parse_args(argv)

    script = args.script or F.HYGIENE_SCRIPT
    if not script.is_file():
        print(f"[NOT CHECKED] no gate declaration site at {script} — this "
              f"census could not look, which is not the same as finding "
              f"nothing.", file=sys.stderr)
        return 2

    c = census(script, args.fixtures, args.debt)
    if args.json_out:
        args.json_out.write_text(json.dumps(c, indent=2, sort_keys=True) + "\n")

    if c["declared"] == 0:
        print(f"[NOT CHECKED] {script} declares NO gate. A census over zero "
              f"gates reports clean for the same reason an empty corpus does, "
              f"and neither is a pass.", file=sys.stderr)
        return 2

    print(f"gate_mutation_fixture_check: {c['declared']} gate(s) declared in "
          f"{script.name}; {c['with_can_fail']} carry a CAN-FAIL fixture; "
          f"{c['with_both']} carry BOTH.")
    print(f"  baseline ({F.DEBT_FILE.name}) still excuses "
          f"{c['baseline_entries']} gate(s); it may only shrink.")

    if args.census_only:
        return 0

    rc, violations = _verdict(c)
    if rc == 0:
        print(f"[PASS] no gate is outside the baseline without both fixtures, "
              f"and no baseline entry has outlived its reason.")
        return 0
    print(f"[FAIL] gate_mutation_fixture_check: {len(violations)} finding(s)",
          file=sys.stderr)
    for x in violations:
        print(f"  - {x}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
