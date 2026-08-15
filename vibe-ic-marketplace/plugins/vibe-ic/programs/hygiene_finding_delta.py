#!/usr/bin/env python3
"""hygiene_finding_delta.py — which hygiene findings did this tree INTRODUCE?

WHY THIS EXISTS (vibe-ic#1498, re-implemented on current main; refs #1553)
==========================================================================
The two landing tiers disagree about what a RED REFERENCE means.

The TEST tier has the right rule and has had it since vibe-ic#1019: `main` is
red, so a candidate lands when its failures are a SUBSET of the base's — what
must be empty is the DIFFERENCE, not the count. `landing_merge_verdict`
computes that from two junit reports, one per arm.

The HYGIENE tier had no such rule. `gatekeeper-land.sh` prints one line for the
whole suite — `FAIL  repo hygiene gates` — and `landing_merge_verdict` can only
subtract that ONE LABEL. So the hygiene tier is judged at a granularity of one:

  * the base's suite is red  -> the whole label is excused, and a finding this
    branch INTRODUCED under it is invisible. That is the permissive half.
  * the base's suite is green -> the whole label blocks, which is right.

This program supplies the granularity the label cannot: it differences the
`--summary-json` records of the two arms and answers exactly one question —
"which findings exist on the candidate that are not on the base?".

WHAT THIS IS NOT
================
It is not a way to wave findings through. It REFUSES rather than guesses
whenever it cannot answer, and every refusal below BLOCKS exactly like an
introduction. A landing gate that cannot measure must never report that it
measured.

WHAT COUNTS AS A FINDING, AND WHY THE LIST IS DERIVED FROM THE EXIT CODE
=======================================================================
A subset rule that models fewer failure causes than the suite has is a false
green generator: the suite exits 1, the delta finds nothing to blame, and the
tier is excused for a reason nobody looked at. So the finding set is taken
from `tools/ci/_gate_dispatch.sh::gate_dispatch_finish`, which is the only
thing that decides that script's rc:

    rc 1   any gate in state FAIL                       -> FINDING (FAIL)
    rc 1   any gate in state WROTE_CORPUS               -> FINDING (WROTE_CORPUS)
    rc 1   any `uncheckable_until` past its review date -> FINDING (EXEMPTION_EXPIRED)
    rc 2   a wiring error in the declarations           -> REFUSAL (see below)
    rc 2   nothing declared                             -> REFUSAL
    rc 0   everything else

`WROTE_CORPUS` is kept distinct from `FAIL` because the dispatcher keeps it
distinct: the gate may have found nothing, and what it did was change the tree
every later gate reads. Both block, and they are different findings, so the
state is part of the identity rather than folded into one.

`EXEMPTION_EXPIRED` is the row the exit code has and a per-gate STATE does not:
an exemption expires whether or not it fired, so a gate can be PASS and still
fail the suite. Differencing states alone would have excused that silently.

AND THE VERDICT IS CROSS-CHECKED AGAINST THE SUITE'S OWN rc
-----------------------------------------------------------
Even so, this program does not get the last word on its own completeness.
`landing_merge_verdict` refuses when the candidate's suite FAILED, the base's
did not, and this program reports nothing introduced — a difference that
explains nothing cannot excuse anything. That is the guard against this list
being wrong in the permissive direction.

IDENTITY, AND WHY THE NORMALISATION IS DELIBERATELY MINIMAL
===========================================================
A finding is ``(kind, label, corpus)``; a gate's identity is ``(label,
corpus)``. The label is a sound identity because `_gate_dispatch.sh` guarantees
it in those words:

    "The label is the gate's IDENTITY and is recorded UNCHANGED … a denominator
     glued into the label would make every loop-driven record unattributable.
     The denominator is a fact ABOUT this invocation, printed beside the label,
     not part of it."

So counts are outside the label by construction. What the dispatcher keeps
beside it reaches this program as the separate ``corpus_item`` /
``corpus_items`` fields, and BOTH are excluded from identity:

  * ``corpus_item`` is an ORDINAL — adding one published cell renumbers every
    later item, which would present the whole tail of a loop as introduced;
  * ``corpus_items`` is a COUNT of the denominator, which is the thing this
    program exists to stop confusing with a finding.

The corpus NAME is kept, because it says which loop a label belongs to.

Normalisation is whitespace-only: collapse runs of whitespace, strip. It does
NOT mask digits, and that is load-bearing. Masking digits is the obvious way to
make "differs only by a count" collapse, and here the digits ARE the identity —
a loop label is built from the basename of a published cell directory, and
those differ from each other only in their version digits. Digit-masking would
merge two genuinely different cells into one finding, and a batch that broke a
second cell would land: the exact failure mode this program exists to prevent,
arrived at from the other side.

Rather than trusting that the normalisation is injective, :func:`check_injective`
ASSERTS it on the live data of both arms every run. A collapse is a REFUSAL,
never a merge, so the property cannot rot.

"COULD NOT CHECK" NEVER DIFFERENCES TO "CLEAN"
=============================================
`NOT_CHECKED`, `LISTED` and `OTHER_SHARD` are states the dispatcher models
precisely because in each of them the gate reached NO verdict. A gate that did
not look has no finding to compare and its silence is not evidence of absence:

  * unknown on ONE side and not the other -> REFUSE. The arms disagree about
    whether the gate ran, which is not a subset result.
  * unknown on BOTH sides -> disclosed, not a finding. Neither arm knows; it
    cannot manufacture an introduction and it cannot hide one either.
  * a gate DECLARED in one arm and absent in the other -> REFUSE. The
    denominators differ, so "absent" cannot be read as "clean".
  * a corpus whose producer FAILED in either arm -> REFUSE. `gate_dispatch_over`
    records PRODUCER_FAILED to say the loop covered an unknown fraction of its
    corpus; absence of a finding under it is not evidence of one.
  * either record `listed_only` (a `--list` run) -> REFUSE. Nothing executed.
  * either record carrying `wiring_errors` -> REFUSE. The dispatcher's own
    words: "the set was not correctly declared, so this run certifies NOTHING".

SAME HOST, SAME DAY
===================
Findings are host-dependent — `gate_host_independence_check` is itself one of
the gates, and it is exactly the kind that answers differently on two machines.
The host of each arm is therefore REQUIRED and never inferred: a baseline that
does not say where it came from cannot be subtracted from anything.

The DAY matters for the same reason, one dimension over: `EXEMPTION_EXPIRED` is
computed against the dispatcher's `today`. Two arms measured on different days
can differ by a promise coming due rather than by anything this branch did, so
a `today` mismatch is a refusal rather than an attribution.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from _atomic_artefact import write_json  # vibe-ic#1082 (helper from PR #1094)

#: Gate states that ARE a finding — see the module docstring for the derivation
#: from `gate_dispatch_finish`'s exit code.
FINDING_STATES = ("FAIL", "WROTE_CORPUS")

#: The kind recorded for an `uncheckable_until` past its review date. Not a
#: gate STATE: the dispatcher fails the suite for it independently of any
#: gate's outcome, so it has to be a finding in its own right.
EXPIRED_KIND = "EXEMPTION_EXPIRED"

#: States in which the gate reached NO verdict. Not findings, and not clean
#: either — handled explicitly rather than defaulted to either side.
UNKNOWN_STATES = ("NOT_CHECKED", "LISTED", "OTHER_SHARD")

_WS = re.compile(r"\s+")

RC_OK = 0
RC_INTRODUCED = 1
RC_REFUSED = 2

#: What `delta` answers with, so a caller can branch on a value rather than on
#: a printed sentence.
CLEAN = "CLEAN"
INTRODUCED = "INTRODUCED"
REFUSED = "REFUSED"


class Refusal(Exception):
    """Cannot answer the subset question. Always blocks; never a pass."""


def normalise(label: str) -> str:
    """Whitespace-only. See the module docstring for why not digits."""
    return _WS.sub(" ", str(label)).strip()


def check_injective(labels: Iterable[str], arm: str) -> None:
    """The normalisation must not merge two genuinely different findings.

    Asserted on the live data rather than argued for, because the argument is
    the part that rots. A collapse is a refusal: this program would otherwise
    be silently answering about findings it cannot tell apart.
    """
    seen: Dict[str, str] = {}
    for raw in labels:
        key = normalise(raw)
        prior = seen.get(key)
        if prior is not None and prior != raw:
            raise Refusal(
                f"NORMALISATION COLLAPSE in the {arm} record: {prior!r} and "
                f"{raw!r} are different gate labels that normalise to the same "
                f"key {key!r}. Two distinct findings would be compared as one, "
                f"so this run cannot be differenced. Widen the identity (the "
                f"corpus name is already part of it) rather than accepting the "
                f"merge.")
        seen[key] = raw


def load(path: Path, arm: str) -> dict:
    """Read one `--summary-json` record, refusing anything that is not one."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refusal(
            f"no {arm} hygiene record at {path} — a missing measurement is not "
            f"an empty one, and cannot be differenced against")
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"the {arm} hygiene record at {path} is unreadable: {exc}")
    if not isinstance(doc, dict) or not isinstance(doc.get("gates"), list):
        raise Refusal(
            f"the {arm} hygiene record at {path} carries no `gates` array — "
            f"this is not a `--summary-json` document")
    if doc.get("listed_only"):
        raise Refusal(
            f"the {arm} record is from a `--list` run: every gate is LISTED and "
            f"none executed, so it states what WOULD run and not what was found")
    if doc.get("wiring_errors"):
        raise Refusal(
            f"the {arm} record carries {len(doc['wiring_errors'])} WIRING "
            f"ERROR(s), so in the dispatcher's own words the set was not "
            f"correctly declared and that run certifies NOTHING: "
            f"{list(doc['wiring_errors'])[:3]}")
    # `exemption_expired` is written for EVERY gate by the shipped dispatcher.
    # Its absence means the record predates the expiry contract, and a record
    # that cannot report an expired promise would difference one away.
    if any("exemption_expired" not in g for g in doc["gates"]):
        raise Refusal(
            f"the {arm} record has gate(s) with no `exemption_expired` key — it "
            f"predates the expiry contract, so an expired uncheckable exemption "
            f"would be invisible to this comparison")
    return doc


def ident(g: dict) -> Tuple[str, str]:
    """A gate's identity, independent of its outcome. Ordinal/count excluded."""
    return (normalise(g.get("label", "")), str(g.get("corpus", "") or ""))


def findings(doc: dict) -> Counter:
    """(kind, label, corpus) -> multiplicity, for one record."""
    c: Counter = Counter()
    for g in doc["gates"]:
        state = str(g.get("state", ""))
        lbl, corpus = ident(g)
        if state in FINDING_STATES:
            c[(state, lbl, corpus)] += 1
        if g.get("exemption_expired"):
            c[(EXPIRED_KIND, lbl, corpus)] += 1
    return c


def _expired_labels(doc: dict) -> set:
    return {normalise(g.get("label", "")) for g in doc["gates"]
            if g.get("exemption_expired")}


def _corpus_producer_failures(doc: dict) -> List[str]:
    return [str(c.get("name", "?")) for c in (doc.get("corpora") or [])
            if c.get("expansion") == "PRODUCER_FAILED"]


def _empty_corpora(doc: dict) -> List[str]:
    return [str(c.get("name", "?")) for c in (doc.get("corpora") or [])
            if int(c.get("items") or 0) == 0]


def delta(base: dict, cand: dict) -> dict:
    """Findings the candidate INTRODUCED. Raises :class:`Refusal` if unanswerable."""
    bg, cg = list(base["gates"]), list(cand["gates"])
    if not bg or not cg:
        raise Refusal(
            "one of the records declares no gate at all — an empty result is "
            "not a zero, it is a run that did not happen (the dispatcher exits "
            "2 for exactly this)")

    check_injective((g.get("label", "") for g in bg), "base")
    check_injective((g.get("label", "") for g in cg), "candidate")

    # A shard split makes each record cover a DIFFERENT declared set on purpose.
    if base.get("shard") != cand.get("shard"):
        raise Refusal(
            f"shard configuration differs — base {base.get('shard')!r} vs "
            f"candidate {cand.get('shard')!r}. Each record then covers a "
            f"different declared set, and the difference of two different "
            f"questions is not an answer")

    # The DAY, because `exemption_expired` is computed against it. See the
    # module docstring: a promise coming due is not something a branch did.
    if str(base.get("today") or "") != str(cand.get("today") or ""):
        raise Refusal(
            f"the arms were measured on different days — base "
            f"{base.get('today')!r}, candidate {cand.get('today')!r}. An "
            f"uncheckable exemption can expire between them, and that is the "
            f"calendar's doing rather than this branch's")

    for arm, doc in (("base", base), ("candidate", cand)):
        failed = _corpus_producer_failures(doc)
        if failed:
            raise Refusal(
                f"the {arm} run's corpus producer FAILED for {failed} — that "
                f"loop covered an unknown fraction of its corpus, so a finding "
                f"absent under it is not a finding that is not there")

    # The record's own internal consistency: the top-level list and the
    # per-gate flags must name the same promises. A record that disagrees with
    # itself is not a denominator for anything.
    for arm, doc in (("base", base), ("candidate", cand)):
        stated = doc.get("exemptions_expired")
        if stated is None:
            raise Refusal(
                f"the {arm} record has no `exemptions_expired` key, so an "
                f"expired promise cannot be told from none")
        if {normalise(s) for s in stated} != _expired_labels(doc):
            raise Refusal(
                f"the {arm} record disagrees with itself about which "
                f"exemptions expired ({sorted(stated)[:4]} vs "
                f"{sorted(_expired_labels(doc))[:4]}) — it is not a reliable "
                f"denominator")

    # DECLARED-SET DRIFT, compared as identity MULTISETS: a gate that merely
    # moved position inside a loop is not drift, while one that exists on a
    # single side is. "Absent" cannot be read as "clean" when the denominators
    # differ.
    b_ident, c_ident = Counter(ident(g) for g in bg), Counter(ident(g) for g in cg)
    only_base, only_cand = b_ident - c_ident, c_ident - b_ident
    if only_base or only_cand:
        raise Refusal(
            "the two runs declare DIFFERENT gate sets, so neither is a "
            "denominator for the other. only on the base: "
            f"{sorted(l for l, _ in only_base)[:6]}; only on the candidate: "
            f"{sorted(l for l, _ in only_cand)[:6]}")

    # RAN-DISAGREEMENT. A gate that reached a verdict on one side and none on
    # the other cannot be differenced: the silent side has nothing to subtract.
    b_state = {ident(g): str(g.get("state", "")) for g in bg}
    c_state = {ident(g): str(g.get("state", "")) for g in cg}
    disagree = sorted(
        lbl for (lbl, corpus) in b_ident
        if (b_state.get((lbl, corpus)) in UNKNOWN_STATES)
        != (c_state.get((lbl, corpus)) in UNKNOWN_STATES))
    if disagree:
        raise Refusal(
            f"these gate(s) reached a verdict on one side and none on the "
            f"other ({'/'.join(UNKNOWN_STATES)}), so whether they hold is "
            f"unknown: {disagree[:8]}. That is not a subset result.")

    b_find, c_find = findings(base), findings(cand)
    unknown_both = sorted(
        lbl for (lbl, corpus) in b_ident
        if b_state.get((lbl, corpus)) in UNKNOWN_STATES
        and c_state.get((lbl, corpus)) in UNKNOWN_STATES)

    introduced = sorted((c_find - b_find).elements())
    return {
        "status": INTRODUCED if introduced else CLEAN,
        "introduced": [list(k) for k in introduced],
        "carried": [list(k) for k in sorted((c_find & b_find).elements())],
        "cleared": [list(k) for k in sorted((b_find - c_find).elements())],
        "no_verdict_either_side": unknown_both,
        # A loop that expanded over nothing declares no gate, so it is invisible
        # in `gates` by construction — the case a reader most needs told.
        "empty_corpora": sorted(set(_empty_corpora(base)) | set(_empty_corpora(cand))),
        "base_findings": sum(b_find.values()),
        "candidate_findings": sum(c_find.values()),
        "declared": len(bg),
    }


def compare(base_path: Path, cand_path: Path, base_host: str,
            cand_host: str) -> dict:
    """The whole question, refusals included. Never raises :class:`Refusal`.

    Returns a record whose ``status`` is CLEAN, INTRODUCED or REFUSED, so a
    caller (``landing_merge_verdict``) branches on a value instead of on rc.
    """
    try:
        # The host first: the cheapest refusal, and the one whose absence makes
        # every later number a comparison between two different machines.
        if not str(base_host).strip() or not str(cand_host).strip():
            raise Refusal(
                "the host of each arm is REQUIRED and is never inferred; got "
                f"base {base_host!r}, candidate {cand_host!r}")
        if base_host != cand_host:
            raise Refusal(
                f"the base was measured on {base_host!r} and the candidate on "
                f"{cand_host!r}. Hygiene findings are host-dependent — "
                f"`gate_host_independence_check` is itself one of these gates — "
                f"so differencing across hosts subtracts measurements that were "
                f"never the same one")
        return delta(load(base_path, "base"), load(cand_path, "candidate"))
    except Refusal as exc:
        return {"status": REFUSED, "refusal": str(exc), "introduced": [],
                "carried": [], "cleared": [], "no_verdict_either_side": [],
                "empty_corpora": [], "base_findings": None,
                "candidate_findings": None, "declared": None}


def _fmt(finding: Sequence[str]) -> str:
    kind, label, corpus = finding
    return f"[{kind}] {label}" + (f" [over {corpus}]" if corpus else "")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="which hygiene findings did this tree introduce (#1498)?")
    ap.add_argument("--base", required=True, type=Path,
                    help="`--summary-json` record from the BASE tree")
    ap.add_argument("--candidate", required=True, type=Path,
                    help="`--summary-json` record from the tree under test")
    ap.add_argument("--base-host", required=True,
                    help="the host the base record was measured on; REQUIRED "
                         "and never inferred")
    ap.add_argument("--candidate-host", required=True,
                    help="the host the candidate record was measured on")
    ap.add_argument("--json", type=Path, help="write the comparison as JSON")
    a = ap.parse_args(argv)

    d = compare(a.base, a.candidate, a.base_host, a.candidate_host)
    if a.json:
        # vibe-ic#1082/#1470: this comparison BLOCKS a landing, so a reader
        # must never be able to open a half-written one. The final name now
        # appears only once the whole record is on disk.
        write_json(a.json, d)

    if d["status"] == REFUSED:
        print("[FAIL] hygiene_finding_delta: REFUSED — this BLOCKS the landing.")
        print(f"  {d['refusal']}")
        print("  A gate that cannot measure must never report that it measured,")
        print("  so this is rc=2 and not a pass.")
        return RC_REFUSED

    for lbl in d["no_verdict_either_side"]:
        print(f"  no verdict on EITHER side (excuses nothing): {lbl}")
    for name in d["empty_corpora"]:
        print(f"  loop corpus expanded over 0 item(s) on some arm: {name}")
    for f in d["cleared"]:
        print(f"  CLEARED (on the base, gone here): {_fmt(f)}")
    for f in d["carried"]:
        print(f"  carried from the base (does NOT block): {_fmt(f)}")

    if d["status"] == INTRODUCED:
        print(f"[FAIL] hygiene_finding_delta: {len(d['introduced'])} finding(s) "
              f"INTRODUCED by this tree — these BLOCK:")
        for f in d["introduced"]:
            print(f"  {_fmt(f)}")
        return RC_INTRODUCED

    print(f"[PASS] hygiene_finding_delta: no finding introduced. "
          f"base={d['base_findings']} candidate={d['candidate_findings']} "
          f"carried={len(d['carried'])} cleared={len(d['cleared'])} "
          f"over {d['declared']} declared gate(s).")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
