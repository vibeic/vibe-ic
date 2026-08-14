#!/usr/bin/env python3
"""hygiene_land_lines.py — publish the hygiene tier's PER-GATE verdicts into the
landing log, so the landing differential can tell one of them from another.

THE DEFECT (vibe-ic#1498)
=========================
`tools/gatekeeper-land.sh` prints ONE line for the whole hygiene tier:

    run "repo hygiene gates"      bash "$ROOT/tools/ci/repo_hygiene_gates.sh"

so every sub-gate reaches the landing log under a single label. The program
that
decides whether a PR may land — `programs/landing_merge_verdict.py` — subtracts
the base arm's failing gate labels from the candidate's and refuses only what is
NEW. With one label for the whole tier, that subtraction cannot discriminate,
and the consequence runs in BOTH directions at once:

  * an operator reading `FAIL  repo hygiene gates` on clean `main` concludes the
    landing bar is unsatisfiable — which is how #1498 was filed;
  * and, the far worse half, once the tier is red on the base EVERY hygiene
    finding a candidate introduces is waived, because the umbrella label is red
    on both arms and the difference is empty.

Measured against `landing_merge_verdict.decide` as it stands, base red on one
sub-gate and candidate red on that one PLUS a second it introduced itself:

    base blocking_failures : ['repo hygiene gates']
    cand blocking_failures : ['repo hygiene gates']
    VERDICT ok             : True
      note  gate fails on the base too, so it is not this branch's — repo hygiene gates

WHAT THIS PROGRAM DOES
======================
`tools/ci/_gate_dispatch.sh` already writes a per-gate record when asked
(`--summary-json PATH`): label, state and seconds for every gate the script
DECLARED. This turns that record into the four-word land-log vocabulary
`parse_land_log` reads, one line per gate, under a namespaced label:

      PASS  repo hygiene gates :: chip-AGNOSTIC source guard
      FAIL  repo hygiene gates :: gates are host-independent
      SKIP  repo hygiene gates :: macro OBS not crossed (spm)

The differential then works per sub-gate with no change to its rules: a NEW
failure refuses, an inherited one is excused BY NAME, and a base-red gate that
the candidate stopped asking is caught by the existing "silenced rather than
fixed" clause.

WHY THE PASSING GATES ARE PRINTED TOO
=====================================
Two reasons, and neither is decoration. The silencing clause asks whether the
candidate ASKED a gate at all — `cand_labels` is `passed | failed | skipped` —
so a gate that is green here and red on the base has to be visible or it reads
as removed. And the emitted set IS the tier's denominator: a reader of the land
log can see WHICH gates ran, rather than inferring the population from the one
that failed. Both are this repo's standing rules, applied to the tier that did not
have them.

STATE MAPPING, and the one that is NOT a fold
=============================================
    PASS          -> PASS
    FAIL          -> FAIL
    WROTE_CORPUS  -> FAIL   (a gate that changed the tree under audit is red;
                             the two are separate buckets in the record and
                             stay separate there — neither is ever green, so
                             collapsing them for the differential launders
                             nothing)
    NOT_CHECKED   -> SKIP   (rc 2: "I could not look". NEVER PASS. As SKIP it
                             also reaches the differential's silencing clause,
                             so a gate that was red on the base and merely
                             refuses here still refuses the landing)

REFUSAL, BECAUSE AN EMPTY RESULT IS NOT A ZERO
==============================================
Every way of not having a record ends in rc 2 with NO lines printed, never in a
silent zero:

    the file is missing, unreadable, or not JSON
    the record is a `--list` roster (declared, deliberately not run)
    it declares no gate, or carries no gate entries
    `declared` disagrees with the number of entries it carries
    a gate carries a state this program does not know
    two gates share one label (#1269 — one gate declared twice merges cleanly
        and nothing caught it; here it would merge two verdicts into one name)
    a gate is `OTHER_SHARD` — declared here and RUN ON ANOTHER HOST

That last one is refused by name rather than folded. `gatekeeper-land.sh`
invokes the hygiene script with no `--shard`, so it cannot arise on this path;
if it ever does, the arm has a partial view of the tier and publishing it as the
tier's verdict is the "smaller world" `tools/ci/shard_aggregate.py` exists to
refuse. Its four-word vocabulary has no way to say "another host was asked",
and SKIP — which means "this arm did not run it" — would read the same as a
gate that ran and could not look. A sharded landing publishes the AGGREGATE,
which is its own wiring.

Printing nothing is the fail-CLOSED direction on both sides of the differential
and needs no cooperation from it: the caller marks the tier FAILED, so against a
base that carries sub-labels every base-red one is missing here and the landing
is refused as silenced, and against a base whose tier was green the umbrella
failure is itself new. There is no arrangement of the two arms in which an
unreadable record reads as "the hygiene tier found nothing".

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The namespace. `parse_land_log` accepts any label text, and ` :: ` cannot
# occur in a hygiene gate label today (verified against the roster the script
# declares — 74 gates at v1.10.39, 83 at v1.10.40; the count is not the point,
# the granularity is) — but the check below refuses rather than trusts that,
# because a
# label that already carries the separator would nest and produce two names for
# one gate, which is the #1431 defect one level down.
PREFIX = "repo hygiene gates :: "

# The dispatcher's vocabulary (`tools/ci/_gate_dispatch.sh`, GATE_STATES) mapped
# to the land log's. An unknown state is a refusal, not a default: a state this
# program has never heard of is one whose severity it cannot know, and guessing
# PASS is the direction that loses a finding.
_STATE_WORD = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "WROTE_CORPUS": "FAIL",
    "NOT_CHECKED": "SKIP",
}


class Refused(Exception):
    """The record could not be turned into verdicts. rc 2, and no lines."""


def _load(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refused(f"the per-gate record at {path} could not be read "
                      f"({exc.__class__.__name__})") from exc
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise Refused(f"the per-gate record at {path} is not JSON ({exc})"
                      ) from exc
    if not isinstance(doc, dict):
        raise Refused(f"the per-gate record at {path} is not an object")
    return doc


def land_lines(doc: dict, prefix: str = PREFIX):
    """[(word, label)] for every gate in a dispatcher record.

    Raises :class:`Refused` for every shape that would report a smaller world
    than the one that was measured.
    """
    if doc.get("listed_only"):
        raise Refused("the record is a --list roster: the gates were declared "
                      "and deliberately not run, so it carries no verdict")
    gates = doc.get("gates")
    if not isinstance(gates, list) or not gates:
        raise Refused("the record carries no gate entries — nothing was "
                      "measured, and that is not the same as nothing found")
    declared = doc.get("declared")
    if not isinstance(declared, int) or declared <= 0:
        raise Refused(f"the record declares {declared!r} gate(s); a tier that "
                      f"declared none has not reported a clean tier")
    if declared != len(gates):
        raise Refused(f"the record declares {declared} gate(s) and carries "
                      f"{len(gates)} entr(ies) — it disagrees with itself, so "
                      f"the population it describes is unknown")

    out, seen = [], set()
    for i, g in enumerate(gates):
        if not isinstance(g, dict):
            raise Refused(f"gate entry {i} is not an object")
        label = g.get("label")
        state = g.get("state")
        if not isinstance(label, str) or not label.strip():
            raise Refused(f"gate entry {i} carries no label")
        if label in seen:
            # vibe-ic#1269 — one gate declared twice merged cleanly and nothing
            # caught it. Here the merge would be of two VERDICTS under one name,
            # and the differential would compare a name that means two things.
            raise Refused(f"two gates share the label {label!r} — one name "
                          f"cannot carry two verdicts")
        seen.add(label)
        if prefix.strip() and prefix.strip() in label:
            raise Refused(f"gate label {label!r} already contains the "
                          f"namespace {prefix.strip()!r}, so the emitted label "
                          f"would name two gates")
        if state == "OTHER_SHARD":
            raise Refused(
                f"gate {label!r} was declared here and run on ANOTHER SHARD, "
                f"so this record is one host's partial view of the tier. "
                f"gatekeeper-land.sh does not shard; a sharded landing must "
                f"publish the aggregate (tools/ci/shard_aggregate.py), not a "
                f"shard")
        word = _STATE_WORD.get(state)
        if word is None:
            raise Refused(f"gate {label!r} carries the state {state!r}, which "
                          f"this program does not know how to grade")
        out.append((word, prefix + label))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Publish the hygiene tier's per-gate verdicts as "
                    "gatekeeper-land.sh log lines, so the landing "
                    "differential can tell one sub-gate from another.")
    ap.add_argument("summary_json",
                    help="the record written by repo_hygiene_gates.sh "
                         "--summary-json")
    ap.add_argument("--prefix", default=PREFIX,
                    help="the label namespace (default: %(default)r)")
    a = ap.parse_args(argv)

    try:
        lines = land_lines(_load(Path(a.summary_json)), a.prefix)
    except Refused as exc:
        # NO LINES. The caller fails the tier, and a tier that reported no
        # sub-gate against a base that reported its whole roster is refused
        # by the differential's own silencing clause.
        print(f"[NOT CHECKED] hygiene_land_lines: {exc}. No per-gate verdict "
              f"was published, which is NOT the same as a tier that found "
              f"nothing.", file=sys.stderr)
        return 2
    for word, label in lines:
        # EXACTLY the shape `run()` prints and `parse_land_log` reads:
        # two spaces, the word, two spaces, the label.
        print(f"  {word}  {label}")
    print(f"        hygiene tier: {len(lines)} gate verdict(s) published for "
          f"the landing differential", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
