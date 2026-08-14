#!/usr/bin/env python3
"""Which hygiene findings did this tree INTRODUCE, relative to its base?

WHY THIS EXISTS (vibe-ic#1498)
------------------------------
The two landing tiers disagreed about what a red reference means.

The PYTEST tier already has the right rule: `main` is red, so a candidate lands
when its failures are a SUBSET of the base's — what must be empty is the
DIFFERENCE, not the count (`landing_merge_verdict.failed_set_delta`).

The HYGIENE tier had no such rule. `gatekeeper-land.sh` treated
`repo_hygiene_gates.sh` as pass/fail on exit code, measured against a `main`
that fails it. Every batch inherits the base's findings, so every batch failed
hygiene regardless of its own content — measured across six rebuilt batches
(135 PRs), every one that reached a verdict failed this tier. Two tiers cannot
both be right about the same red reference.

WHAT THIS IS NOT
----------------
It is not a way to wave findings through. It answers exactly one question —
"is this finding already on the base?" — and it REFUSES rather than guesses
whenever it cannot answer that. Every refusal below is a BLOCK, not a pass:
a landing gate that cannot measure must never report that it measured.

IDENTITY, AND WHY THE NORMALISATION IS DELIBERATELY MINIMAL
-----------------------------------------------------------
A finding is identified by ``(kind, label, corpus)`` where `kind` is the gate
STATE that constitutes a finding (FAIL or WROTE_CORPUS) and `label` is the
gate's own label from `--summary-json`.

The label is a sound identity because `_gate_dispatch.sh` guarantees it:

    "The label is the gate's IDENTITY and is recorded UNCHANGED … a denominator
     glued into the label would make every loop-driven record unattributable.
     The denominator is a fact ABOUT this invocation, printed beside the label,
     not part of it."

So counts are already outside the label by construction. What the dispatcher
keeps beside it — ``[item N of M over C]`` — reaches this program as the
separate ``corpus_item`` / ``corpus_items`` fields, and BOTH are excluded from
identity:

  * ``corpus_item`` is an ORDINAL. Adding one published cell renumbers every
    later item, which would present the whole tail of the loop as introduced.
  * ``corpus_items`` is a COUNT of the denominator, which is the thing #1498 is
    about not confusing with a finding.

The corpus NAME is kept, because it says which loop a label belongs to.

THE NORMALISATION REFUSES RATHER THAN MERGES
--------------------------------------------
Normalisation is whitespace-only: collapse runs of whitespace, strip. It does
NOT mask digits, and that is the load-bearing decision.

Masking digits is the obvious way to make "differs only by a count" collapse,
and it is wrong here, because in this corpus the digits ARE the identity. A
loop label is built as

    "inner FAILs reach the verdict (<basename of the cell directory>)"

and those directory names differ from each other only in their version digits.
Digit-masking would merge two genuinely different published cells into one
finding, and a batch that broke a second cell would land — the precise failure
mode this program exists to prevent, arrived at from the other side.

So instead of trusting that a normalisation is injective, `check_injective`
ASSERTS it: if two distinct raw labels ever collapse to the same normalised
key, that is a REFUSAL (rc 2), not a merge. The property is checked on the real
data of both arms every time this runs, so it cannot rot.

"COULD NOT CHECK" NEVER DIFFERENCES TO "CLEAN"
----------------------------------------------
`NOT_CHECKED` is a state the dispatcher models precisely because rc 2 means the
gate refused to look. A gate that could not look has no finding to compare, and
its silence is not evidence of absence. So:

  * NOT_CHECKED on ONE side and not the other  -> REFUSE. The two runs disagree
    about whether the gate ran, which is not a subset result.
  * NOT_CHECKED on BOTH sides                  -> disclosed, not a finding. The
    arms agree; neither knows. It cannot manufacture an introduced finding.
  * a gate DECLARED in one arm and absent in the other -> REFUSE. The
    denominators differ, so "absent" cannot be read as "clean".
  * a corpus whose producer FAILED in either arm -> REFUSE. `gate_dispatch_over`
    records PRODUCER_FAILED to say the loop covered an unknown fraction of its
    corpus; absence of a finding under it is not evidence of one.
  * either document `listed_only` (a `--list` run)  -> REFUSE. Nothing executed.

SAME HOST
---------
Findings differ per machine — one of the base's own two findings on 8HD-d is
literally a HOST_DEPENDENT_VERDICT. Comparing a base measured on one host with
a candidate measured on another would subtract findings that were never the
same measurement. The host of each arm is therefore required and must match;
this program will not infer it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Gate states that ARE a finding. `WROTE_CORPUS` is kept separate from `FAIL`
#: by the dispatcher on purpose — the gate may have found nothing; what it did
#: was change the tree every later gate reads. Both block, and they are
#: different findings, so the state is part of the identity rather than folded.
FINDING_STATES = ("FAIL", "WROTE_CORPUS")

#: Not findings, but not clean either. Handled explicitly below.
UNKNOWN_STATES = ("NOT_CHECKED",)

_WS = re.compile(r"\s+")

RC_OK = 0
RC_INTRODUCED = 1
RC_REFUSED = 2


class Refusal(Exception):
    """Cannot answer the subset question. Always blocks; never a pass."""


def normalise(label: str) -> str:
    """Whitespace-only. See the module docstring for why not digits."""
    return _WS.sub(" ", label).strip()


def check_injective(labels: List[str], arm: str) -> None:
    """The normalisation must not merge two genuinely different findings.

    Asserted on the live data rather than argued for, because the argument is
    the part that rots. A collapse is a refusal: this program would otherwise
    be silently answering about a finding it cannot distinguish.
    """
    seen: Dict[str, str] = {}
    for raw in labels:
        key = normalise(raw)
        prior = seen.get(key)
        if prior is not None and prior != raw:
            raise Refusal(
                f"NORMALISATION COLLAPSE in the {arm} run: {prior!r} and "
                f"{raw!r} are different gate labels that normalise to the same "
                f"key {key!r}. Two distinct findings would be compared as one, "
                f"so this run cannot be differenced. Widen the identity (the "
                f"corpus name is already part of it) rather than accepting the "
                f"merge.")
        seen[key] = raw


def load(path: Path, arm: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refusal(
            f"no {arm} hygiene record at {path} — a missing measurement is not "
            f"an empty one, and cannot be differenced against")
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"{arm} hygiene record at {path} is unreadable: {exc}")
    if not isinstance(doc, dict) or "gates" not in doc:
        raise Refusal(
            f"{arm} hygiene record at {path} carries no `gates` array — this is "
            f"not a --summary-json document")
    if doc.get("listed_only"):
        raise Refusal(
            f"the {arm} record is from a `--list` run: every gate is LISTED and "
            f"none executed, so it states what WOULD run and not what was found")
    return doc


def gate_key(g: dict) -> Tuple[str, str, str]:
    """(state, normalised label, corpus). Ordinal and count excluded."""
    return (str(g.get("state", "")),
            normalise(str(g.get("label", ""))),
            str(g.get("corpus", "")))


def ident(g: dict) -> Tuple[str, str]:
    """A gate's identity independent of its outcome — for declared-set drift."""
    return (normalise(str(g.get("label", ""))), str(g.get("corpus", "")))


def _corpus_producer_failures(doc: dict, arm: str) -> List[str]:
    return [c.get("name", "?") for c in (doc.get("corpora") or [])
            if c.get("expansion") == "PRODUCER_FAILED"]


def delta(base: dict, cand: dict) -> dict:
    """Findings the candidate INTRODUCED. Raises Refusal when unanswerable."""
    bg = list(base.get("gates") or [])
    cg = list(cand.get("gates") or [])
    if not bg or not cg:
        raise Refusal(
            "one of the records contains no gates at all — an empty result is "
            "not a zero, it is a run that did not happen")

    check_injective([str(g.get("label", "")) for g in bg], "base")
    check_injective([str(g.get("label", "")) for g in cg], "candidate")

    # A shard split makes each record cover a DIFFERENT declared set on purpose.
    if base.get("shard") != cand.get("shard"):
        raise Refusal(
            f"shard configuration differs — base {base.get('shard')!r} vs "
            f"candidate {cand.get('shard')!r}. Each record then covers a "
            f"different declared set and the difference is meaningless")

    for arm, doc in (("base", base), ("candidate", cand)):
        failed = _corpus_producer_failures(doc, arm)
        if failed:
            raise Refusal(
                f"the {arm} run's corpus producer FAILED for {failed} — that "
                f"loop covered an unknown fraction of its corpus, so a finding "
                f"absent under it is not a finding that is not there")

    # DECLARED-SET DRIFT. Compared as identities, so a gate that merely moved
    # position in a loop is not drift, while a gate that exists on one side only
    # is. "Absent" cannot be read as "clean" when the denominators differ.
    b_ident = Counter(ident(g) for g in bg)
    c_ident = Counter(ident(g) for g in cg)
    only_base = b_ident - c_ident
    only_cand = c_ident - b_ident
    if only_base or only_cand:
        raise Refusal(
            "the two runs declare DIFFERENT gate sets, so neither is a "
            "denominator for the other. "
            f"only on base: {sorted(l for l, _ in only_base)[:6]}; "
            f"only on candidate: {sorted(l for l, _ in only_cand)[:6]}")

    # RAN-DISAGREEMENT. A gate that refused on one side and looked on the other
    # cannot be differenced: the silent side has no finding to subtract.
    b_state = {ident(g): str(g.get("state", "")) for g in bg}
    c_state = {ident(g): str(g.get("state", "")) for g in cg}
    disagree = sorted(
        lbl for (lbl, corpus) in b_ident
        if (b_state.get((lbl, corpus)) in UNKNOWN_STATES)
        != (c_state.get((lbl, corpus)) in UNKNOWN_STATES))
    if disagree:
        raise Refusal(
            "these gate(s) RAN on one side and refused (NOT_CHECKED) on the "
            f"other, so whether they hold is unknown: {disagree[:8]}. "
            "That is not a subset result.")

    b_find = Counter(gate_key(g) for g in bg if g.get("state") in FINDING_STATES)
    c_find = Counter(gate_key(g) for g in cg if g.get("state") in FINDING_STATES)
    introduced = c_find - b_find
    cleared = b_find - c_find

    both_unchecked = sorted(
        lbl for (lbl, corpus) in b_ident
        if b_state.get((lbl, corpus)) in UNKNOWN_STATES
        and c_state.get((lbl, corpus)) in UNKNOWN_STATES)

    return {
        "introduced": sorted((s, l, c) for (s, l, c) in introduced.elements()),
        "carried": sorted((s, l, c) for (s, l, c) in (c_find & b_find).elements()),
        "cleared": sorted((s, l, c) for (s, l, c) in cleared.elements()),
        "unchecked_both_sides": both_unchecked,
        "base_findings": sum(b_find.values()),
        "candidate_findings": sum(c_find.values()),
        "declared": len(bg),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Which hygiene findings did this tree introduce (#1498)?")
    ap.add_argument("--base", required=True, type=Path,
                    help="--summary-json record from the BASE tree")
    ap.add_argument("--candidate", required=True, type=Path,
                    help="--summary-json record from the tree under test")
    ap.add_argument("--base-host", required=True,
                    help="host the base record was measured on")
    ap.add_argument("--candidate-host", required=True,
                    help="host the candidate record was measured on")
    ap.add_argument("--json", type=Path, help="write the delta as JSON")
    a = ap.parse_args(argv)

    try:
        # Host first: the cheapest refusal, and the one whose absence would make
        # every later number a comparison between two different machines.
        if a.base_host != a.candidate_host:
            raise Refusal(
                f"base measured on {a.base_host!r}, candidate on "
                f"{a.candidate_host!r}. Hygiene findings are host-dependent — "
                f"one of the base's own findings is a HOST_DEPENDENT_VERDICT — "
                f"so differencing across hosts subtracts measurements that were "
                f"never the same one")
        if not a.base_host.strip():
            raise Refusal("the base host is empty; it is required, not inferred")
        d = delta(load(a.base, "base"), load(a.candidate, "candidate"))
    except Refusal as exc:
        print("HYGIENE SUBSET: REFUSED — this BLOCKS the landing.")
        print(f"  {exc}")
        print("  A gate that cannot measure must never report that it measured,")
        print("  so this is rc=2 and not a pass.")
        return RC_REFUSED

    if a.json:
        a.json.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")

    for lbl in d["unchecked_both_sides"]:
        print(f"  NOT CHECKED on BOTH sides (no verdict either way): {lbl}")
    for _s, lbl, _c in d["cleared"]:
        print(f"  CLEARED (on the base, gone here): {lbl}")
    for _s, lbl, _c in d["carried"]:
        print(f"  carried from the base (does NOT block): {lbl}")

    if d["introduced"]:
        print(f"HYGIENE SUBSET: {len(d['introduced'])} finding(s) INTRODUCED by "
              f"this tree — these BLOCK:")
        for state, lbl, corpus in d["introduced"]:
            where = f" [over {corpus}]" if corpus else ""
            print(f"  [{state}] {lbl}{where}")
        return RC_INTRODUCED

    print(f"HYGIENE SUBSET: no finding introduced. "
          f"base={d['base_findings']} candidate={d['candidate_findings']} "
          f"carried={len(d['carried'])} cleared={len(d['cleared'])} "
          f"over {d['declared']} declared gate(s).")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
