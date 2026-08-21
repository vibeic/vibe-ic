#!/usr/bin/env python3
"""Guard the classified blocker list's contract on a compliance report.

WHAT THIS PROTECTS. `flow_compliance_check` now emits, beside the tally, one
classified record per non-PASS step: what it measures, what it observed, and
which of PLUGIN_DEFECT / DESIGN_FACT / MISSING_CAPABILITY / UNCLASSIFIED it is.
That list is only worth reading if three things stay true, and each of them has
a cheap way to go quietly wrong:

  1. NOTHING DROPS OUT. The list is complete over the non-PASS steps. The
     tempting "improvement" is to filter it until it is short — and a filter
     tightened until a count reaches zero has already been caught in this repo
     once, swallowing the real defect. So the check is a SET EQUALITY against
     the report's own `steps`, not a bound on the length.

  2. NOTHING IS INVENTED. No full-PASS step appears on the list. The opposite
     over-correction — attributing a blocker to a step that passed — fabricates
     work rather than losing it, and on a blocking consumer that is worse.

  3. NO CLASS WITHOUT A RULE. Every record names, in `basis`, the rule that
     decided it, and a record whose basis is `no-rule-matched` MUST be
     UNCLASSIFIED. This is the anti-guess property: it makes "assign a class
     you cannot justify" a failure rather than a judgement call, which is the
     only way UNCLASSIFIED survives contact with a number people want smaller.

WHAT THIS DELIBERATELY DOES NOT CHECK. Whether a particular classification is
CORRECT. That is not decidable from the report — it is the reviewer's job, and
`basis` exists to make it a two-line job. A guard that pretended to adjudicate
correctness would be the false-clean result this repo keeps closing.

PRE-CONTRACT REPORTS. A report with no `blockers` key was written by a producer
older than this contract. That is reported, by name, and exits 0 — a guard that
failed on every report in `benchmark-data/` would be flagging state the repo
already shipped, which is a bug in the guard.

Usage:
    python3 blocker_classification_check.py <report.json> [more.json ...]
    python3 blocker_classification_check.py --dir <tree>   # sweep *.json
    python3 blocker_classification_check.py <...> --json out.json

Exit codes:
    0 = at least one report CARRIED the contract and every checked report
        satisfies it
    1 = at least one contract violation
    2 = usage / I/O error, or NOTHING EXERCISED THE GUARD

THE LAST ONE IS THE POINT, AND IT USED TO BE A 0
------------------------------------------------
A sweep over reports that ALL predate the contract takes the `blockers is None`
early return on every one of them: none of the five rules above ever runs. The
first version of this program answered 0 there, and PR #858's review measured
exactly that state — `--dir` over the 5 committed reports, exit 0, guard body
never entered. `test_blocker_classification_sweep_reaches_its_guard` was written
from it and says it plainly: *a sweep whose guard is never entered is a green
light wired to nothing.* The test pins that the guard CAN be entered; it cannot
stop a caller from reading a green that means "nothing was exercised" as one
that means "the reports are clean".

So the program refuses the verdict instead. `exercised = checked - pre_contract`
is the denominator every run prints, and when it is zero the answer is
NOT_CHECKED / rc 2 — this repo's vacuous-exit convention, which
`_gate_dispatch.sh` records as NOT_CHECKED rather than folding into PASS. It
goes green by itself the first time a contract-carrying report is swept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import _blocker_classification as _bc
import _flow_verdict_tiers as _T

#: A record must carry every one of these. A key that is sometimes absent
#: forces each consumer to decide what missing means, which is the contract
#: re-derived at every reader.
REQUIRED_KEYS = ("step_id", "step_name", "stage", "status", "classification",
                 "basis", "measures", "observed", "derived_from",
                 "sub_blockers")

#: The one basis word that may not carry a class. See property 3 above.
_UNDECIDED_BASIS = "no-rule-matched"


def _is_compliance_report(doc: Any) -> bool:
    """Does this JSON look like a `flow_compliance_check --json` report?

    Shape-based on purpose: the sweep walks whole trees and must not depend on
    a filename convention, because the corpus does not have one (the same
    producer writes `flow_compliance.json`, `flow_compliance_strict.json`,
    `flow_compliance_baseline.json` and `_logs/*_splitrun.json`).
    """
    if not isinstance(doc, Mapping):
        return False
    steps = doc.get("steps")
    return ("overall" in doc and isinstance(steps, list) and bool(steps)
            and isinstance(steps[0], Mapping) and "status" in steps[0])


def check_report(doc: Mapping[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    """Return ``(violations, facts)`` for one compliance report."""
    violations: List[str] = []
    steps = [s for s in doc.get("steps", []) if isinstance(s, Mapping)]
    expected = [s for s in steps if _bc.is_blocker(s)]
    expected_ids = [str(s.get("id")) for s in expected]

    blockers = doc.get("blockers")
    facts: Dict[str, Any] = {
        "pre_contract": blockers is None,
        "steps": len(steps),
        "expected_blockers": len(expected_ids),
        "listed_blockers": 0,
        "class_counts": {},
    }
    if blockers is None:
        return violations, facts
    if not isinstance(blockers, list):
        return ([f"`blockers` is {type(blockers).__name__}, not a list"],
                facts)

    facts["listed_blockers"] = len(blockers)
    listed_ids = [str(b.get("step_id")) for b in blockers
                  if isinstance(b, Mapping)]

    # 1. nothing drops out
    for sid in expected_ids:
        if sid not in listed_ids:
            step = next(s for s in expected if str(s.get("id")) == sid)
            violations.append(
                f"step {sid} is {step.get('status')} (a blocker) but is "
                f"absent from `blockers` — the list is not complete over the "
                f"non-PASS steps")
    # 2. nothing is invented
    for sid in listed_ids:
        if sid not in expected_ids:
            violations.append(
                f"step {sid} appears in `blockers` but is not a blocker in "
                f"`steps` — a passing or inapplicable step must not be listed")
    if len(listed_ids) != len(set(listed_ids)):
        dupes = sorted({i for i in listed_ids if listed_ids.count(i) > 1})
        violations.append(
            f"duplicate `blockers` entries for step(s) {', '.join(dupes)} — "
            f"a step counted twice inflates every class count")

    # 3. shape, closed enum, and no class without a rule
    for b in blockers:
        if not isinstance(b, Mapping):
            violations.append(f"`blockers` entry is not an object: {b!r}")
            continue
        sid = b.get("step_id")
        for key in REQUIRED_KEYS:
            if key not in b:
                violations.append(f"step {sid}: record is missing `{key}`")
        cls = str(b.get("classification", ""))
        if cls not in _bc.BLOCKER_CLASSES:
            violations.append(
                f"step {sid}: classification {cls!r} is outside the closed "
                f"set {list(_bc.BLOCKER_CLASSES)}")
        basis = str(b.get("basis", "")).strip()
        if not basis:
            violations.append(
                f"step {sid}: classification {cls!r} names no `basis` — a "
                f"class with no rule behind it is a guess wearing a label")
        elif basis == _UNDECIDED_BASIS and cls != "UNCLASSIFIED":
            violations.append(
                f"step {sid}: basis {basis!r} with classification {cls!r} — "
                f"no rule matched, so the only honest class is UNCLASSIFIED")
        for sb in (b.get("sub_blockers") or []):
            if not isinstance(sb, Mapping):
                continue
            scls = str(sb.get("classification", ""))
            if scls not in _bc.BLOCKER_CLASSES:
                violations.append(
                    f"step {sid} / gate {sb.get('gate')!r}: classification "
                    f"{scls!r} is outside the closed set")
            if not str(sb.get("basis", "")).strip():
                violations.append(
                    f"step {sid} / gate {sb.get('gate')!r}: names no `basis`")

    # 4. the published counts are the list's own counts
    facts["class_counts"] = _bc.class_counts(
        [b for b in blockers if isinstance(b, Mapping)])
    published = doc.get("blocker_class_counts")
    if isinstance(published, Mapping):
        for cls in _bc.BLOCKER_CLASSES:
            if int(published.get(cls, 0)) != facts["class_counts"][cls]:
                violations.append(
                    f"`blocker_class_counts[{cls}]` = "
                    f"{published.get(cls)} but the list contains "
                    f"{facts['class_counts'][cls]} — a headline that does not "
                    f"sum to its own list is the defect this list replaces")

    # 5. an empty list must mean "nothing is blocked", never "the classifier
    #    fell over". The producer records that difference; refuse to let it be
    #    reported as a clean run.
    if not blockers and str(doc.get("blocker_list_error", "")):
        violations.append(
            f"`blockers` is empty and `blocker_list_error` is set "
            f"({doc['blocker_list_error']}) — an empty list produced by a "
            f"crash must not read as a clean one")
    return violations, facts


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="*", help="compliance report JSON file(s)")
    ap.add_argument("--dir", action="append", default=[],
                    help="sweep every *.json under this tree that looks like a "
                         "compliance report")
    ap.add_argument("--json", help="write the sweep result here")
    args = ap.parse_args(argv)

    paths: List[Path] = [Path(p) for p in args.reports]
    for d in args.dir:
        root = Path(d)
        if not root.is_dir():
            print(f"blocker_classification_check: --dir {d} is not a directory",
                  file=sys.stderr)
            return 2
        paths.extend(sorted(root.rglob("*.json")))
    if not paths:
        print("blocker_classification_check: no reports given "
              "(pass files or --dir)", file=sys.stderr)
        return 2

    checked = 0
    pre_contract = 0
    skipped_not_a_report = 0
    unreadable: List[str] = []
    failures: List[Dict[str, Any]] = []
    totals = {c: 0 for c in _bc.BLOCKER_CLASSES}

    for path in paths:
        try:
            doc = json.loads(path.read_text())
        except Exception as exc:
            # Only complain about files we were pointed at EXPLICITLY; a tree
            # sweep meets plenty of JSON that is not ours.
            if path in [Path(p) for p in args.reports]:
                unreadable.append(f"{path}: {exc}")
            continue
        if not _is_compliance_report(doc):
            skipped_not_a_report += 1
            continue
        violations, facts = check_report(doc)
        checked += 1
        if facts["pre_contract"]:
            pre_contract += 1
        for cls, n in (facts.get("class_counts") or {}).items():
            totals[cls] = totals.get(cls, 0) + n
        if violations:
            failures.append({"report": str(path), "violations": violations})

    print(f"blocker_classification_check: {checked} compliance report(s) "
          f"checked, {pre_contract} predate the blocker contract "
          f"(no `blockers` key — reported, not failed), "
          f"{skipped_not_a_report} JSON file(s) were not compliance reports")
    if checked - pre_contract:
        print("  classified blockers over the reports that carry the list: "
              + "  ".join(f"{c}={totals.get(c, 0)}"
                          for c in _bc.BLOCKER_CLASSES))
    for u in unreadable:
        print(f"  ✗ unreadable: {u}")
    for f in failures:
        print(f"  ✗ {f['report']}")
        for v in f["violations"]:
            print(f"      - {v}")

    # The number that decides whether this run MEASURED anything: a report
    # without the `blockers` key leaves `check_report` at its pre-contract
    # early return, so none of the five rules ran on it. See the exit-code
    # note in the module docstring — this used to be folded into PASS.
    exercised = checked - pre_contract
    if failures or unreadable:
        verdict = "FAIL"
    elif exercised > 0:
        verdict = "PASS"
    else:
        verdict = "NOT_CHECKED"

    result = {
        "program": "blocker_classification_check",
        "reports_checked": checked,
        "pre_contract_reports": pre_contract,
        "reports_exercising_the_contract": exercised,
        "non_report_json_skipped": skipped_not_a_report,
        "class_totals": totals,
        "unreadable": unreadable,
        "failures": failures,
        "verdict": verdict,
    }
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2,
                                              ensure_ascii=False))
    if verdict == "NOT_CHECKED":
        print(f"blocker_classification_check: NOT_CHECKED — 0 of {checked} "
              f"compliance report(s) carried a `blockers` key "
              f"({pre_contract} predate the contract, "
              f"{skipped_not_a_report} JSON file(s) were not compliance "
              f"reports), so not one of this guard's rules executed. That is "
              f"not a clean sweep, and reporting it as one is the defect this "
              f"guard exists to stop downstream.")
        return 2
    print(f"blocker_classification_check: {verdict}")
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
