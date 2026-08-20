#!/usr/bin/env python3
"""The five identities. "Were these two runs even solving the same problem?"

WHY FIVE AND NOT ONE
====================
A single "run hash" answers no useful question. When two runs disagree about a
number, what a reader needs is WHICH of them differed, because each difference
means something different:

  problem          the design, the constraints, the PDK, the target corners.
                   Different here and the two runs are not comparable AT ALL;
                   whichever one "won" won a different contest.
  implementation   the RTL / netlist / the candidate's own source. This is the
                   axis a PPA experiment is ALLOWED to move.
  analysis         how the measurement was taken -- corners, extraction, the
                   activity basis for power. Different here and the numbers
                   are not the same METRIC, even if the design is identical.
  toolchain        the image and tool builds that produced the artefacts.
  agent_execution  what an agent was permitted to do, and under which policy.

A PPA comparison is legitimate exactly when `problem`, `analysis` and
`toolchain` match and `implementation` differs. That sentence is the whole
reason this module exists, and `ppa_problem_integrity_check.py` is it in code.

THE RULE THAT MAKES A DIGEST WORTH ANYTHING
===========================================
**An identity with an unreadable member is NOT_MEASURED, not a digest over the
rest.** Hashing "everything except the file I could not open" produces a
confident 64-hex identity that silently means something narrower than it
claims, and two runs that both failed to read DIFFERENT files would agree. That
is the same defect as a check reporting clean over input it never saw, one
layer up, and it is harder to see because the output looks like success.

CONTENT-ADDRESSED, NOT PATH-ADDRESSED
=====================================
An artefact enters a digest as `{role, sha256}`; its PATH is provenance and
stays out. Two runs in differently-named run directories over byte-identical
inputs ARE solving the same problem, and an identity that said otherwise would
report a difference on every run that was merely moved. The path is still in
the contract document -- it is how a human finds the file -- it just does not
change what the run WAS.

CONFLICTING FACTS DO NOT GET AN IDENTITY
========================================
If two sources declare the same key with different values, this module does not
pick one. It returns NOT_MEASURED naming the key. Choosing a winner here would
bury a conflict inside a hash where nothing downstream could ever see it; the
conflict is a FINDING and it belongs in `contract.py`, which reports it. This
is therefore a second, independent detector of the same defect, and the two
were written not to share code so that one failing cannot silence the other.

chip-AGNOSTIC: hashes over declared records. No IC, vendor or process here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import provenance as prov
from .canonical_json import digest_of

__all__ = [
    "IDENTITY_SCHEMA", "IDENTITY_KINDS",
    "identity", "identities", "compare",
]

IDENTITY_SCHEMA = "vibeic.ppa.identity.v1"

#: Frozen and ordered. A sixth identity is a change to everyone's documents,
#: so it is a v2 of the schema, not an append here.
IDENTITY_KINDS = ("problem", "implementation", "analysis", "toolchain",
                  "agent_execution")


def _normalise_artefact(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The part of an artefact row that IS the identity: role and content."""
    return {"role": str(row.get("role", "")), "sha256": str(row.get("sha256", ""))}


def _fact_value(fact: Mapping[str, Any]) -> Any:
    return fact.get("value")


def _collapse_facts(facts: Sequence[Mapping[str, Any]]):
    """Group declared facts by key; report keys with more than one value.

    Returns `(members, conflicts)`. `members` is the sorted list of
    `{key, value}` that enters the digest; `conflicts` is the list of keys
    whose sources disagreed, which makes the identity NOT_MEASURED.

    Equality is over the CANONICAL ENCODING, not `==`: `1` and `1.0` compare
    equal in Python and serialise differently, so a digest built on `==`
    could accept two facts that hash apart. The encoder is the arbiter of
    sameness everywhere else in this package, and it is here too.
    """
    by_key: Dict[str, List[Any]] = {}
    for fact in facts:
        key = str(fact.get("key", ""))
        by_key.setdefault(key, []).append(_fact_value(fact))
    members: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    for key in sorted(by_key):
        values = by_key[key]
        encoded = {digest_of(v): v for v in values}
        if len(encoded) > 1:
            conflicts.append({"key": key,
                              "values": [encoded[d] for d in sorted(encoded)]})
            continue
        members.append({"key": key, "value": values[0]})
    return members, conflicts


def identity(kind: str,
             artefacts: Sequence[Mapping[str, Any]] = (),
             facts: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """Build one identity record.

    `artefacts` are rows from `provenance.artefact_ref`; `facts` are
    `{key, value, ...}` declarations. The result always carries `kind`,
    `status` and the exact `members` that were (or would have been) hashed, so
    a reader can recompute the digest without this code.
    """
    if kind not in IDENTITY_KINDS:
        raise ValueError(
            f"unknown identity kind {kind!r}; the five are "
            f"{', '.join(IDENTITY_KINDS)}")

    unreadable = [
        {"role": str(r.get("role", "")), "path": str(r.get("path", "")),
         "reason": str(r.get("reason", "unstated"))}
        for r in artefacts if r.get("status") != prov.MEASURED
    ]
    fact_members, conflicts = _collapse_facts(facts)

    artefact_members = sorted(
        (_normalise_artefact(r) for r in artefacts
         if r.get("status") == prov.MEASURED),
        key=lambda m: (m["role"], m["sha256"]))

    record: Dict[str, Any] = {
        "schema": IDENTITY_SCHEMA,
        "kind": kind,
        "members": {"artefacts": artefact_members, "facts": fact_members},
    }

    if unreadable or conflicts:
        record["status"] = prov.NOT_MEASURED
        reasons: List[str] = []
        if unreadable:
            reasons.append(
                "%d declared artefact(s) could not be measured: %s"
                % (len(unreadable),
                   "; ".join(f"{u['role']} ({u['path']}): {u['reason']}"
                             for u in unreadable)))
        if conflicts:
            reasons.append(
                "%d declared fact(s) have conflicting values: %s"
                % (len(conflicts), "; ".join(c["key"] for c in conflicts)))
        record["reason"] = " | ".join(reasons)
        record["unreadable"] = unreadable
        record["conflicts"] = conflicts
        # No `digest` key at all, rather than a null one. A null that the
        # reader has to remember to check is the sentinel this package
        # refuses everywhere else.
        return record

    record["status"] = prov.MEASURED
    record["digest"] = digest_of({"kind": kind, "members": record["members"]})
    return record


def identities(declared: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """All five, from a mapping of kind -> `{"artefacts": [...], "facts": [...]}`.

    A kind the caller did not declare is still present in the result, as
    NOT_MEASURED with the reason "not declared". An absent key and a declared-
    but-empty one are different facts about the run and a table with a missing
    row invites the reader to supply the difference themselves.
    """
    out: Dict[str, Any] = {}
    for kind in IDENTITY_KINDS:
        block = declared.get(kind)
        if block is None:
            out[kind] = {
                "schema": IDENTITY_SCHEMA, "kind": kind,
                "status": prov.NOT_MEASURED,
                "reason": "not declared",
                "members": {"artefacts": [], "facts": []},
            }
            continue
        out[kind] = identity(kind,
                             artefacts=block.get("artefacts", ()) or (),
                             facts=block.get("facts", ()) or ())
    return out


def compare(left: Mapping[str, Any],
            right: Mapping[str, Any]) -> Dict[str, Any]:
    """Do two identity records name the same thing, and if not, where?

    `verdict` is `SAME`, `DIFFERENT`, or `UNDETERMINED`. UNDETERMINED when
    either side is NOT_MEASURED -- two runs that both failed to read something
    are not thereby the same run, and returning SAME for that pair is the
    exact false comfort this package exists to remove.
    """
    lk, rk = left.get("kind"), right.get("kind")
    if lk != rk:
        return {"verdict": "UNDETERMINED", "kind": lk,
                "reason": f"comparing identity kinds {lk!r} and {rk!r}"}
    if (left.get("status") != prov.MEASURED
            or right.get("status") != prov.MEASURED):
        return {"verdict": "UNDETERMINED", "kind": lk,
                "reason": ("at least one side is NOT_MEASURED: "
                           f"left={left.get('status')} "
                           f"({left.get('reason', '')}), "
                           f"right={right.get('status')} "
                           f"({right.get('reason', '')})")}
    if left.get("digest") == right.get("digest"):
        return {"verdict": "SAME", "kind": lk, "digest": left.get("digest")}
    return {"verdict": "DIFFERENT", "kind": lk,
            "left_digest": left.get("digest"),
            "right_digest": right.get("digest"),
            "differing_members": _member_diff(left, right)}


def _member_diff(left: Mapping[str, Any],
                 right: Mapping[str, Any]) -> Dict[str, Any]:
    """Name the members that moved, so a DIFFERENT verdict is actionable.

    A bare "the digests differ" makes a reader diff two whole run trees by
    hand; that is where the answer stops being used.
    """
    lm = left.get("members", {})
    rm = right.get("members", {})
    la = {m["role"]: m["sha256"] for m in lm.get("artefacts", [])}
    ra = {m["role"]: m["sha256"] for m in rm.get("artefacts", [])}
    lf = {m["key"]: m["value"] for m in lm.get("facts", [])}
    rf = {m["key"]: m["value"] for m in rm.get("facts", [])}
    artefacts = [
        {"role": role, "left": la.get(role), "right": ra.get(role)}
        for role in sorted(set(la) | set(ra)) if la.get(role) != ra.get(role)
    ]
    facts = [
        {"key": key, "left": lf.get(key), "right": rf.get(key)}
        for key in sorted(set(lf) | set(rf))
        if digest_of(lf.get(key)) != digest_of(rf.get(key))
    ]
    return {"artefacts": artefacts, "facts": facts}
