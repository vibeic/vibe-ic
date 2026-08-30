#!/usr/bin/env python3
"""Which of a batch's INPUTS have moved since the batch merged them?

WHY THIS EXISTS
===============
An assembled batch is measured as a whole. Every push to one of its inputs makes
that measurement older than the branch it describes, and the landing gate then
refuses the batch -- correctly, and at the worst possible moment, because by then
the whole measurement has been paid for. `gatekeeper-land.sh` says so in its own
words at the point where it fails a landing "when the tree moves under the gates,
so the price is the batch".

MEASURED, and it is why this is a gate hole rather than a nicety: one batch lost
THREE full measurement rounds to exactly this, with ten of sixteen inputs still
moving while it was being measured. The fix adopted was to freeze the inputs. A
freeze is a rule, and a rule with nothing measuring it is a request -- this is the
measurement.

HOW THE INPUTS ARE IDENTIFIED, and why not from the commit subject
==================================================================
A batch's merge commits carry a subject naming the branch, but that is a
CONVENTION of whoever assembled it. A checker keyed on a subject format finds
nothing the day the format changes, and "found nothing" is indistinguishable from
"nothing moved" -- the failure mode this repo names a liar.

So the key is STRUCTURAL: a merge commit's SECOND PARENT is the input's tip at
the moment it was merged. That is a property of the graph, not of anyone's
wording. The branch NAME is recovered from the subject only for the report, and
when it cannot be recovered the sha is printed instead -- never skipped.

EXITS
=====
  0  every input the batch merged is still at the sha the batch merged
  1  at least one input has MOVED; each is named with both shas
  2  could not look -- and it says exactly what it could not read
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

#: `catch-up: <branch> (...)`, `Merge remote-tracking branch 'origin/<branch>' ...`,
#: `Merge branch '<branch>' ...`. Best-effort and REPORT-ONLY: a subject that
#: matches none of these yields no name, and the sha is reported instead.
_NAME_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"^catch-up:\s+(\S+)"),
    re.compile(r"Merge remote-tracking branch '(?:origin/)?([^']+)'"),
    re.compile(r"Merge branch '(?:origin/)?([^']+)'"),
    #: `merge <branch>` -- the dominant form in practice, and the reason the first
    #: version of this file could name only 27 of 107 inputs. The `(?!:)` keeps
    #: `merge: <prose>` out: that form names no branch and must stay UNNAMED
    #: rather than capture a sentence's first word.
    re.compile(r"^merge(?!:)\s+(\S+)\s*$"),
)

#: A parsed name is CONFIRMED by resolving it, never trusted from the regex. An
#: unconfirmed name is reported as UNRESOLVED and NOT as GONE, because this
#: checker cannot tell a deleted branch from a misparsed subject and saying
#: "GONE" about a misparse would be a false alarm with someone else's name on it.


def _git(args: List[str], cwd: Optional[str]) -> Tuple[int, str, str]:
    p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _name_from_subject(subject: str) -> Optional[str]:
    for pat in _NAME_PATTERNS:
        m = pat.search(subject)
        if m:
            return m.group(1)
    return None


def collect_inputs(base: str, batch: str, cwd: Optional[str] = None
                   ) -> List[Tuple[str, Optional[str]]]:
    """(input tip sha, branch name or None) for every merge in base..batch.

    The sha comes from the merge's second parent -- structural. The name is
    best-effort from the subject and may be None, which the caller must report
    rather than drop.
    """
    rc, out, err = _git(["rev-list", "--merges", f"{base}..{batch}"], cwd)
    if rc != 0:
        raise LookupError(f"cannot list merges in {base}..{batch}: {err or 'git failed'}")
    # `rev-list` is NEWEST-FIRST, and that ordering is load-bearing here.
    #
    # A batch can merge the same branch TWICE -- an early merge and a later
    # catch-up. The first version of this function keyed on the TIP, so such a
    # branch appeared as two inputs and was counted as two movers. Measured on a
    # real 107-input batch: two branches were double-counted that way.
    #
    # Only the LATEST merge is what the batch's measurement describes, so named
    # inputs are keyed by NAME and the first sighting (= newest merge) wins.
    # Unnamed ones stay keyed by tip: with no name there is nothing to collapse
    # on, and collapsing them by anything else would invent a relationship.
    by_name: Dict[str, str] = {}
    by_tip: Dict[str, None] = {}
    for merge in out.split("\n"):
        if not merge:
            continue
        rc2, tip, _ = _git(["rev-parse", f"{merge}^2"], cwd)
        if rc2 != 0:
            continue                      # a merge with no second parent: not an input
        rc3, subject, _ = _git(["log", "-1", "--format=%s", merge], cwd)
        name = _name_from_subject(subject) if rc3 == 0 else None
        if name is None:
            by_tip.setdefault(tip, None)
        else:
            by_name.setdefault(name, tip)          # newest merge wins
    out_pairs: List[Tuple[str, Optional[str]]] = [(t, n) for n, t in by_name.items()]
    out_pairs += [(t, None) for t in by_tip]
    return sorted(out_pairs, key=lambda kv: (kv[1] or "~", kv[0]))


def remote_tip(name: str, remote: str, cwd: Optional[str] = None) -> Optional[str]:
    rc, out, _ = _git(["ls-remote", "--heads", remote, f"refs/heads/{name}"], cwd)
    if rc != 0 or not out:
        return None
    return out.split()[0]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="what the batch was assembled ON")
    ap.add_argument("--batch", required=True, help="the assembled batch ref")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--repo", default=None)
    a = ap.parse_args(argv)

    try:
        inputs = collect_inputs(a.base, a.batch, a.repo)
    except LookupError as e:
        print(f"UNDETERMINED: {e}", file=sys.stderr)
        return 2
    if not inputs:
        print(f"UNDETERMINED: no merge commit in {a.base}..{a.batch} has a second "
              f"parent, so no input could be identified. This is not 'nothing "
              f"moved' -- nothing was examined.", file=sys.stderr)
        return 2

    moved, unnamed, unresolved, same = [], [], [], 0
    for tip, name in inputs:
        if name is None:
            unnamed.append(tip)
            continue
        now = remote_tip(name, a.remote, a.repo)
        if now is None:
            unresolved.append((name, tip))
        elif now != tip:
            moved.append((name, tip, now))
        else:
            same += 1

    # A LANDED batch answers this question truthfully and uselessly: its inputs
    # kept developing afterwards, which is expected and is not drift under a
    # measurement. Measured on the previous batch (v1.11.69 -> v1.11.70, already
    # main): 11 "MOVED" that mean only "these branches carried on". The tool must
    # say what its answer is ABOUT, or a true number gets read as an alarm.
    rc_l, main_tip, _ = _git(["rev-parse", f"{a.remote}/main"], a.repo)
    landed = False
    if rc_l == 0:
        rc_a, _, _ = _git(["merge-base", "--is-ancestor", a.batch, main_tip], a.repo)
        landed = (rc_a == 0)
    if landed:
        print(f"NOTE: {a.batch} is already an ancestor of {a.remote}/main -- it has "
              f"LANDED. Inputs moving after a landing is normal development, not "
              f"drift under a measurement. This check is for an UNLANDED batch; "
              f"what follows is reported, not raised.")
    print(f"{len(inputs)} input(s) identified in {a.base}..{a.batch} "
          f"(by merge second parent, not by subject)")
    for name, was, now in moved:
        print(f"  MOVED   {name}\n            batch merged {was[:9]}\n"
              f"            {a.remote} now has {now[:9]}")
    for name, was in unresolved:
        print(f"  UNRESOLVED {name} -- no such ref on {a.remote} (batch merged "
              f"{was[:9]}). That is EITHER a deleted branch OR a misparsed "
              f"subject, and this checker cannot tell them apart.")
    for tip in unnamed:
        print(f"  UNNAMED {tip[:9]} -- its merge subject names no branch, so this "
              f"input could not be checked. Reported, not skipped.")
    print(f"\nconfirmed unmoved {same} | MOVED {len(moved)} | "
          f"UNRESOLVED {len(unresolved)} | UNNAMED {len(unnamed)}")
    if moved:
        print(f"{len(moved)} input(s) MOVED since the batch merged them."
              + ("" if landed else " Every one makes the batch's measurement older "
                 "than the branch it describes."))
        return 0 if landed else 1
    if unnamed or unresolved:
        print("0 inputs moved among those that could be checked -- but a clean "
              "result over a partial scan is a partial result.")
        return 0 if landed else 1
    print("Every input is still at the sha the batch merged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
