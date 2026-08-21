#!/usr/bin/env python3
"""landing_gate_result_consume.py — state a gate's verdict from the machine
record the suite that ALREADY ran it wrote in this round, instead of running
the same program a second time over the same tree.

WHY IT EXISTS
=============
`tools/gatekeeper-land.sh` ran `plugin_full_audit.py` TWICE per landing: once
inside `tools/ci/repo_hygiene_gates.sh` (its `plugin full audit` gate, invoked
from the landing script's own full tier) and once again three lines later, on
its own. MEASURED on a detached worktree at origin/main f6b0e77dd, both call
sites, one after the other:

    site 1  cd $PLUGIN && python3 programs/plugin_full_audit.py       rc=0  19.64 s
    site 2  cd $ROOT   && python3 $PROGRAMS/plugin_full_audit.py $PLUGIN  rc=0  20.00 s

    sha256(stdout) c79a86b0…  IDENTICAL      sha256(stderr) e3b0c442…  IDENTICAL

Not merely the same verdict: the same bytes, on both channels. The two argv
forms cannot address different subjects either — the program's own default is
`Path(__file__).resolve().parent.parent`, and `$PROGRAMS` is `$PLUGIN/programs`,
so the argument site 2 passes IS the path site 1 derives. Nothing between the
two writes to the tree, and `suite_write_guard --compare` plus
`landing_worktree_is_clean_check --expect-fingerprint` at the end of the tier
fail the whole round if anything did.

WHAT THIS IS NOT
================
It is NOT a cache and it does NOT decide anything itself. It reads ONE record,
written by ONE run that has already finished in this same process tree, and
re-states that run's verdict under the caller's own label. The gate it consumes
keeps its ability to fail — a recorded FAIL is rc 1 here — and the layer that
OWNS the assertion is unchanged: `repo_hygiene_gates.sh` still executes the
program, still prints its output, and is still driven twice by
`gate_host_independence_check`.

A CONSUMER THAT CANNOT FIND ITS SUBJECT MUST NOT PASS
=====================================================
Every way of not knowing is rc 2, never rc 0:

  * the record is missing, empty, or not JSON              — nothing ran, or it did not finish
  * the record was produced by a `--list` run              — the gates were declared, not executed
  * the label appears in no gate                           — the gate was renamed or deleted
  * the label appears more than once                       — two gates answer to one name
  * the recorded state is not PASS and not FAIL            — LISTED / OTHER_SHARD / OUT_OF_SCOPE /
                                                             NOT_CHECKED / WROTE_CORPUS all mean the
                                                             gate reached no verdict about its subject

"I could not look" sharing an exit code with "I looked and it was clean" is the
defect this repository removes from gates one at a time; a program written to
stand in for a gate must not reintroduce it. `tools/gatekeeper-land.sh`'s `run`
helper treats every non-zero rc as FAIL, so rc 2 refuses the landing there.

Exit: 0 = the record says PASS / 1 = the record says FAIL / 2 = cannot consume.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

#: The two states that are a VERDICT ABOUT THE SUBJECT. Every other state
#: `_gate_dispatch.sh` can record — LISTED, OTHER_SHARD, OUT_OF_SCOPE,
#: NOT_CHECKED, WROTE_CORPUS — says something about the RUN and nothing about
#: the tree, so none of them may be re-stated as this gate's answer.
DECIDED = ("PASS", "FAIL")

RC_PASS = 0
RC_FAIL = 1
RC_CANNOT_CONSUME = 2


def _refuse(message: str) -> int:
    # `[FAIL]` DELIBERATELY LEADS THE LINE. `tools/gatekeeper-land.sh`'s `run`
    # helper prints the FAILING lines first by grepping for `^\s*(FAIL|ERROR)`
    # or `[FAIL]`, then a `tail -5`. A refusal spelled only "CANNOT CONSUME"
    # would reach the reader as five lines of tail with the reason off the top,
    # which is the "named nowhere" defect that comment was written about.
    print(f"[FAIL] CANNOT CONSUME: {message}")
    print("consume: refusing to state a verdict I did not read — "
          "'I could not look' is not 'I looked and it was clean'")
    return RC_CANNOT_CONSUME


def load_record(path: Path) -> Optional[dict]:
    """The record, or None when it cannot be read as one."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def matching_gates(doc: dict, label: str) -> List[dict]:
    """Every recorded gate whose label is EXACTLY `label`.

    Exact, never a substring. `repo_hygiene_gates.sh` labels are prose written
    by hand and nothing keeps one from becoming a prefix of another — the
    per-published-cell loop already mints labels by interpolation. A consumer
    that matched loosely would re-state the wrong gate's verdict while looking
    like it worked, which is the failure mode this whole file exists to avoid.
    """
    gates = doc.get("gates")
    if not isinstance(gates, list):
        return []
    return [g for g in gates
            if isinstance(g, dict) and g.get("label") == label]


def consume(record: Path, label: str, subject: Optional[str] = None) -> int:
    doc = load_record(record)
    if doc is None:
        return _refuse(f"no readable gate record at {record} — the suite that "
                       f"owns \"{label}\" did not finish, or never wrote one")
    if doc.get("listed_only"):
        return _refuse(f"the record at {record} was produced by a --list run: "
                       f"\"{label}\" was DECLARED, not executed")
    found = matching_gates(doc, label)
    if not found:
        declared = doc.get("declared")
        return _refuse(
            f"the record at {record} declares {declared} gate(s) and none is "
            f"labelled \"{label}\" — it was renamed or deleted, and this line "
            f"has been standing in for a gate that no longer runs")
    if len(found) > 1:
        return _refuse(
            f"{len(found)} gates in {record} answer to \"{label}\"; a verdict "
            f"consumed from an ambiguous name is not that gate's verdict")
    gate = found[0]
    state = gate.get("state")
    seconds = gate.get("seconds")
    where = f"{record} (state={state}, {seconds}s)"
    if state not in DECIDED:
        return _refuse(
            f"\"{label}\" is recorded {state} in {record}: it reached no "
            f"verdict about its subject, so there is nothing to re-state")
    named = f" [{subject}]" if subject else ""
    if state == "FAIL":
        print(f"[FAIL] \"{label}\"{named} FAILED where it ran — {where}")
        print("consume: the owning suite printed the findings; this line is "
              "the same verdict, not a second opinion")
        return RC_FAIL
    print(f"[PASS] \"{label}\"{named} PASSED where it ran — {where}")
    return RC_PASS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", required=True,
                    help="the --summary-json record written by the suite that "
                         "already ran the gate")
    ap.add_argument("--gate", required=True,
                    help="the EXACT gate label to re-state")
    ap.add_argument("--subject", default=None,
                    help="what the gate decided about, named in the log so a "
                         "reader can see which program's verdict this is")
    a = ap.parse_args(argv)
    return consume(Path(a.record), a.gate, a.subject)


if __name__ == "__main__":
    sys.exit(main())
