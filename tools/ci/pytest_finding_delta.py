#!/usr/bin/env python3
"""pytest_finding_delta.py — what did a test that is red on BOTH sides start saying?

WHY THIS EXISTS
===============
Every batch arm on this fleet differences two lists of FAILING TEST IDS. A test
red on the base and red on the candidate appears on both sides and cancels — so
`NEW_RED` is empty and nothing is wrong with that arithmetic. It is the only
question the instrument asks.

An already-red test is therefore an ABSORBING STATE: any number of new defects
can land inside one without moving a count. The information is destroyed by the
SHAPE of the comparison, before judgement gets a chance, and no care in running
the arms recovers it.

Measured instance, 2026-08-22, batch 68:

    tools/ci/test_gate_mutation_fixture_check.py::test_the_real_repo_is_clean_under_this_gate
      base      a00f53f20  FAILED, 6 unexcused gates
      candidate 833e8493f  FAILED, 8 unexcused gates   <- +2, both this batch's
    NEW_RED reported empty by three independent arms. Correctly.

This program answers the one question they could not: for the ids red on BOTH
sides, WHAT DID THE FAILURE SAY, and what does it say now that it did not before?

WHAT THIS IS NOT
================
**It is not a gate and must not become one without a decision nobody has made.**
No gate declares it, no landing path invokes it, and that is deliberate. The
obvious promotion — refuse a landing when a both-sides-red test says something
new — is NOT obviously right: failure text carries temp paths, durations and
orderings, and a landing gate that refuses on noise DEADLOCKS main. Choosing that
predicate has a deadlock on one side and a false green on the other. It belongs
to whoever owns the landing tier. A REPORT cannot deadlock anything; it can only
tell a human something the differential could not. That is the whole scope.

THE PREDICATE IS PRINTED, NOT MERELY APPLIED
============================================
Two honest censuses of one fixture disagreed 6 vs 3 on this repo, and the
disagreement was never in the data — one counted `shutil.copy` and the other
counted provision. A count whose predicate is printed can be reconciled against
someone else's; one whose predicate is implicit gets reconciled by argument. So
every run prints what it counted as a finding and what it normalised away.

A FINDING is a line inside a test's failure block carrying pytest's `E ` prefix.
That is pytest's own marker for the assertion text, it survives `-q`, and it is
the granularity at which repo gates enumerate ("NEW-OR-UNEXCUSED: '<gate>' ...").

NORMALISATION is deliberately NARROW. Only things that differ between two runs of
the SAME tree are erased. Digits are NOT normalised: `6 gate(s)` -> `8 gate(s)`
is exactly the signal this program exists to surface, and a normaliser that ate
it would be a false-green generator.
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Dict, List, Tuple

FINDING_PREDICATE = "a line inside a FAILURES block carrying pytest's `E ` prefix"

# Each entry is (pattern, replacement, why-it-is-noise). The `why` is printed, so
# a reader can disagree with a specific rule instead of with the whole program.
NORMALISERS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"/tmp/[\w.\-]+"), "<TMPPATH>",
     "temp directories carry a fresh random suffix per run"),
    (re.compile(r"0x[0-9a-fA-F]{6,}"), "<ADDR>",
     "object addresses differ per process"),
    (re.compile(r"\[\d+(?:\.\d+)?s\]"), "[<DURATION>]",
     "elapsed time is not a verdict"),
    (re.compile(r"\bin \d+(?:\.\d+)?s\b"), "in <DURATION>s",
     "elapsed time is not a verdict"),
]

_FAIL_HEAD = re.compile(r"^_{3,}\s+(?P<name>.+?)\s+_{3,}$")
_SHORT_FAIL = re.compile(r"^FAILED\s+(?P<id>\S+)")
_E_LINE = re.compile(r"^E\s{0,4}(?P<text>.*)$")


def normalise(line: str, repo_root: str | None) -> str:
    out = line.rstrip()
    if repo_root:
        out = out.replace(repo_root, "<REPO>")
    for pat, rep, _ in NORMALISERS:
        out = pat.sub(rep, out)
    return " ".join(out.split())


def parse(text: str, repo_root: str | None) -> Tuple[Dict[str, List[str]], List[str]]:
    """-> ({test id or section name: [findings]}, [ids reported FAILED]).

    Sections are delimited by pytest's `____ name ____` banners. A section's key
    is the banner name, which for a plain function test is the test's own name;
    the short summary's `FAILED <id>` lines give the fully qualified ids. The two
    are reconciled by suffix, and anything that cannot be reconciled is REPORTED
    rather than dropped — a finding silently attached to no id is the failure
    mode this whole program exists to complain about.
    """
    findings: Dict[str, List[str]] = {}
    failed: List[str] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        m = _FAIL_HEAD.match(line.strip())
        if m:
            current = m.group("name").strip()
            findings.setdefault(current, [])
            continue
        s = _SHORT_FAIL.match(line.strip())
        if s:
            failed.append(s.group("id"))
            current = None
            continue
        if current is not None:
            e = _E_LINE.match(line.strip())
            if e and e.group("text").strip():
                findings[current].append(normalise(e.group("text"), repo_root))
    return findings, failed


def resolve(section: str, ids: List[str]) -> str:
    """Map a banner name onto a full test id, or return the banner unchanged."""
    hits = [i for i in ids if i.split("::")[-1] == section
            or i.endswith("::" + section)]
    return hits[0] if len(hits) == 1 else section


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="pytest output from the BASE arm")
    ap.add_argument("--candidate", required=True, help="pytest output from the CANDIDATE arm")
    ap.add_argument("--repo-root", default=None,
                    help="absolute path to normalise to <REPO> (the two arms live in "
                         "different worktrees, so their roots differ by construction)")
    ap.add_argument("--base-repo-root", default=None,
                    help="the BASE arm's root, if it differs from --repo-root")
    a = ap.parse_args(argv)

    base_text = open(a.base, encoding="utf-8", errors="replace").read()
    cand_text = open(a.candidate, encoding="utf-8", errors="replace").read()

    b_find, b_ids = parse(base_text, a.base_repo_root or a.repo_root)
    c_find, c_ids = parse(cand_text, a.repo_root)

    print("pytest_finding_delta")
    print(f"  finding predicate := {FINDING_PREDICATE}")
    for _, rep, why in NORMALISERS:
        print(f"  normalised {rep}: {why}")
    print("  digits are NOT normalised — an enumerated count changing IS the signal")
    print(f"  base: {len(b_ids)} FAILED id(s), {len(b_find)} failure section(s)")
    print(f"  cand: {len(c_ids)} FAILED id(s), {len(c_find)} failure section(s)")

    if not b_find and not c_find:
        print("\n[CANNOT CHECK] neither report contains a FAILURES block. That is not "
              "a pass: run pytest without -q, or with -rf and full tracebacks, so "
              "the `E ` lines this program reads are present.")
        return 2

    both = sorted(set(b_find) & set(c_find))
    print(f"\nsections RED ON BOTH SIDES: {len(both)}"
          "  <- the region an id-level differential cancels")

    introduced = 0
    for sec in both:
        b_set, c_set = b_find[sec], c_find[sec]
        new = [f for f in c_set if f not in b_set]
        gone = [f for f in b_set if f not in c_set]
        if not new and not gone:
            continue
        introduced += len(new)
        print(f"\n  {resolve(sec, c_ids)}")
        print(f"    findings: base {len(b_set)} -> candidate {len(c_set)}")
        for f in new:
            print(f"    + NEW FINDING INSIDE AN ALREADY-RED TEST: {f}")
        for f in gone:
            print(f"    - no longer said: {f}")

    if introduced:
        print(f"\n{introduced} finding(s) were INTRODUCED inside tests that were already "
              "red, and no id-level differential can report them.")
        return 1
    print("\nNo finding was introduced inside an already-red test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
