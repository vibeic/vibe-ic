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
`NOT_CHECKED`, `LISTED`, `OTHER_SHARD` and `OUT_OF_SCOPE` are states the
dispatcher models precisely because in each of them the gate reached NO
verdict. A gate that did not look has no finding to compare and its silence is
not evidence of absence:

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

Before subtraction, the redundant top-level counts are recomputed from the gate
rows and every process-bearing row is matched bijectively to one complete
attestation whose rc agrees with the state.  Missing/extra records, unknown
terminal states and count drift are refusals.  The sole exception is the exact
legacy structural EMPTY row described below: it was synthesized by the old
dispatcher without launching a process, and is never generalized by state or
label prefix.

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

ONE NARROW BOOTSTRAP: THE EXTERNAL ROUTED-DEF CORPUS
====================================================
Moving the published routed-DEF population out of this repository necessarily
changes one declaration shape.  The old tree records an EMPTY corpus as one
structural, unexempted ``NOT_CHECKED`` row; the first tree which consumes the
immutable external population declares the per-item gates instead.  Treating
that one replacement as ordinary declared-set drift would make the repair
impossible to land.

This is not a general gate-addition escape hatch.  :func:`_corpus_transition`
recognises only that named corpus, only EMPTY -> positive EXPANDED, and only
against a parent-owned manifest of the exact paths, blobs, gate identities,
commands and independently supervised process outcomes.  Candidate-authored
summary JSON is cross-checked against that evidence; its internally consistent
hashes are not treated as proof that a process ran.  The common declarations
still have to be an exact multiset match.  Any other addition or removal refuses
the whole comparison.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_json  # noqa: E402  vibe-ic#1082 (helper from PR #1094)

#: Gate states that ARE a finding — see the module docstring for the derivation
#: from `gate_dispatch_finish`'s exit code.
FINDING_STATES = ("FAIL", "WROTE_CORPUS")

#: The kind recorded for an `uncheckable_until` past its review date. Not a
#: gate STATE: the dispatcher fails the suite for it independently of any
#: gate's outcome, so it has to be a finding in its own right.
EXPIRED_KIND = "EXEMPTION_EXPIRED"

#: States in which the gate reached NO verdict. Not findings, and not clean
#: either — handled explicitly rather than defaulted to either side.
UNKNOWN_STATES = ("NOT_CHECKED", "LISTED", "OTHER_SHARD", "OUT_OF_SCOPE")

#: The bootstrap is deliberately named rather than inferred from arbitrary
#: ``items: 0 -> N`` metadata.  Inference would turn every newly declared loop
#: into a way around the exact declared-set comparison below.
ROUTED_DEF_CORPUS = "published cells carrying a routed DEF"
BENCHMARK_DATA_ORIGIN = "https://github.com/vibeic/benchmark-data.git"
ROUTED_DEF_EMPTY_LABEL = (
    f'corpus "{ROUTED_DEF_CORPUS}" is EMPTY — nothing was checked over it')
ROUTED_DEF_GATE_LABELS = (
    "macro OBS not crossed ({design})",
    "DRC PASS is not vacuous ({design})",
    "inner FAILs reach the verdict ({design})",
    "new tool diagnostic id ({design})",
)

_FULL_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

TERMINAL_STATES = (
    "PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS", "OUT_OF_SCOPE",
    "LISTED", "OTHER_SHARD",
)
PROCESS_STATES = ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")

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


def _strict_json(text: str) -> object:
    """Parse one unambiguous JSON value (no duplicate keys/non-finite numbers)."""
    def object_no_duplicates(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    def finite_only(token):
        raise ValueError(f"non-finite JSON number {token!r}")

    return json.loads(text, object_pairs_hook=object_no_duplicates,
                      parse_constant=finite_only)


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
        doc = _strict_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refusal(
            f"no {arm} hygiene record at {path} — a missing measurement is not "
            f"an empty one, and cannot be differenced against")
    except (OSError, ValueError) as exc:
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
        wiring = doc["wiring_errors"]
        count = len(wiring) if isinstance(wiring, list) else "malformed"
        raise Refusal(
            f"the {arm} record carries {count} WIRING "
            f"ERROR(s), so in the dispatcher's own words the set was not "
            f"correctly declared and that run certifies NOTHING: "
            f"{list(wiring)[:3] if isinstance(wiring, list) else wiring!r}")
    # `exemption_expired` is written for EVERY gate by the shipped dispatcher.
    # Its absence means the record predates the expiry contract, and a record
    # that cannot report an expired promise would difference one away.
    if any(not isinstance(g, dict) or "exemption_expired" not in g
           for g in doc["gates"]):
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


def _corpus_producer_failures(doc: dict) -> List[str]:
    return [str(c.get("name", "?")) for c in (doc.get("corpora") or [])
            if c.get("expansion") == "PRODUCER_FAILED"]


def _empty_corpora(doc: dict) -> List[str]:
    return [str(c.get("name", "?")) for c in (doc.get("corpora") or [])
            if int(c.get("items") or 0) == 0]


def _exact_int(value: object, what: str, *, minimum: int = 0) -> int:
    """Return an integer field without accepting bool/string lookalikes."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Refusal(f"{what} must be an integer >= {minimum}, got {value!r}")
    return value


def _one_corpus(doc: dict, name: str, arm: str) -> dict:
    corpora = doc.get("corpora")
    if not isinstance(corpora, list) or not all(
            isinstance(row, dict) for row in corpora):
        raise Refusal(f"the {arm} record has no structured `corpora` array")
    rows = [row for row in corpora if row.get("name") == name]
    if len(rows) != 1:
        raise Refusal(
            f"the {arm} record must carry exactly one {name!r} corpus row for "
            f"the EMPTY-to-expanded transition, got {len(rows)}")
    return rows[0]


def _benchmark_oid(doc: dict, arm: str) -> str:
    inputs = doc.get("corpus_inputs")
    if not isinstance(inputs, dict):
        raise Refusal(
            f"the {arm} record has no structured `corpus_inputs`; the external "
            f"routed-DEF population is therefore not bound to an immutable "
            f"benchmark commit")
    oid = inputs.get("benchmark_data_sha")
    if not isinstance(oid, str) or _FULL_GIT_OID.fullmatch(oid) is None:
        raise Refusal(
            f"the {arm} record's `corpus_inputs.benchmark_data_sha` is not a "
            f"full Git object id: {oid!r}")
    return oid


def _attestation_valid_for(row: dict, rec: dict, arm: str) -> None:
    """Validate the process record rather than counting an arbitrary dict."""
    label = str(row.get("label", ""))
    fields = {
        "schema", "complete", "label", "argv_sha256", "returncode",
        "verdict_line", "finding_identities", "semantic_sha256", "state",
    }
    if (not isinstance(rec, dict) or type(rec.get("schema")) is not int
            or rec.get("schema") != 1
            or rec.get("complete") is not True or set(rec) != fields):
        raise Refusal(
            f"the {arm} gate {label!r} has no exact complete schema-1 "
            f"process attestation")
    if rec.get("label") != row.get("label"):
        raise Refusal(
            f"the {arm} gate {label!r} is associated with an attestation "
            f"for {rec.get('label')!r}")
    if (not isinstance(rec.get("argv_sha256"), str)
            or _SHA256.fullmatch(rec["argv_sha256"]) is None):
        raise Refusal(
            f"the {arm} gate {label!r} has an invalid attested argv digest")
    rc = rec.get("returncode")
    findings_ = rec.get("finding_identities")
    if (isinstance(rc, bool) or not isinstance(rc, int)
            or not isinstance(rec.get("verdict_line"), str)
            or not isinstance(findings_, list)
            or not all(isinstance(item, str) for item in findings_)):
        raise Refusal(
            f"the {arm} gate {label!r} has malformed process evidence")
    semantic = {
        "returncode": rc,
        "verdict_line": rec["verdict_line"],
        "finding_identities": findings_,
    }
    expected = hashlib.sha256(json.dumps(
        semantic, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    if rec.get("semantic_sha256") != expected:
        raise Refusal(
            f"the {arm} gate {label!r} has a process-attestation digest "
            f"mismatch")
    stated = rec.get("state", "")
    if stated not in ("", row.get("state")):
        raise Refusal(
            f"the {arm} gate {label!r} says {row.get('state')!r} but its "
            f"process attestation says {stated!r}")
    state = str(row.get("state", ""))
    if state == "PASS" and rc != 0:
        raise Refusal(
            f"the {arm} gate {label!r} claims PASS over process rc {rc}")
    if state == "NOT_CHECKED" and rc != 2:
        raise Refusal(
            f"the {arm} gate {label!r} claims NOT_CHECKED over process rc "
            f"{rc}, not rc 2")
    if state == "FAIL" and rc == 0:
        raise Refusal(
            f"the {arm} gate {label!r} claims FAIL over process rc 0")


def _legacy_structural_empty(row: dict) -> bool:
    """The sole pre-attestation dispatcher row, exact rather than inferred."""
    return (
        row.get("label") == ROUTED_DEF_EMPTY_LABEL
        and row.get("state") == "NOT_CHECKED"
        and row.get("corpus") == ROUTED_DEF_CORPUS
        and row.get("corpus_item") == 0
        and row.get("corpus_items") == 0
        and row.get("exempt_until") in (None, "")
        and row.get("exempt_reason") in (None, "")
        and row.get("exemption_expired") is False
    )


def _validate_record(doc: dict, arm: str) -> Dict[str, dict]:
    """Validate the complete aggregate record before subtracting any finding."""
    if not isinstance(doc, dict) or not isinstance(doc.get("gates"), list):
        raise Refusal(f"the {arm} record is not a hygiene summary")
    gates = doc["gates"]
    if not gates or not all(isinstance(row, dict) for row in gates):
        raise Refusal(f"the {arm} record has no complete gate array")
    if doc.get("listed_only") is not False or doc.get("shard") is not None:
        raise Refusal(
            f"the {arm} record is not a completed aggregate hygiene run")
    if doc.get("wiring_errors") != []:
        raise Refusal(
            f"the {arm} record carries wiring errors and certifies nothing")
    try:
        today = _datetime.date.fromisoformat(str(doc.get("today", "")))
    except ValueError:
        raise Refusal(f"the {arm} record has no valid measurement day")

    raw_labels = []
    counts = Counter()
    for row in gates:
        label, state = row.get("label"), row.get("state")
        if not isinstance(label, str) or not label:
            raise Refusal(f"the {arm} record has a gate without a string label")
        if state not in TERMINAL_STATES:
            raise Refusal(
                f"the {arm} gate {label!r} has non-terminal state {state!r}")
        _exact_int(row.get("seconds"), f"the {arm} gate {label!r} seconds")
        if not isinstance(row.get("exemption_expired"), bool):
            raise Refusal(
                f"the {arm} gate {label!r} has no boolean expiry verdict")
        until, why = row.get("exempt_until"), row.get("exempt_reason")
        if until not in (None, ""):
            if not isinstance(until, str) or not str(why or "").strip():
                raise Refusal(
                    f"the {arm} gate {label!r} has a malformed exemption")
            try:
                due = _datetime.date.fromisoformat(until)
            except ValueError:
                raise Refusal(
                    f"the {arm} gate {label!r} has invalid exemption date "
                    f"{until!r}")
            if row["exemption_expired"] is not (due < today):
                raise Refusal(
                    f"the {arm} gate {label!r} disagrees with its measurement "
                    f"day about exemption expiry")
        elif why not in (None, "") or row["exemption_expired"]:
            raise Refusal(
                f"the {arm} gate {label!r} has inconsistent exemption fields")
        raw_labels.append(label)
        counts[state] += 1
    if len(set(raw_labels)) != len(raw_labels):
        raise Refusal(
            f"the {arm} record repeats a gate label, so label-only process "
            f"attestations cannot be associated bijectively")

    expected_counts = {
        "declared": len(gates),
        "ran": sum(counts[state] for state in PROCESS_STATES),
        "decided": counts["PASS"] + counts["FAIL"],
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "not_checked": counts["NOT_CHECKED"],
        "wrote_corpus": counts["WROTE_CORPUS"],
        "deferred": counts["LISTED"],
        "other_shard": counts["OTHER_SHARD"],
        "out_of_scope": counts["OUT_OF_SCOPE"],
    }
    for field, expected in expected_counts.items():
        if _exact_int(doc.get(field), f"the {arm} record's {field}") != expected:
            raise Refusal(
                f"the {arm} record's {field} count does not equal its gate "
                f"states ({doc.get(field)!r} vs {expected})")
    if (doc["deferred"] != 0 or doc["other_shard"] != 0
            or doc["declared"] != doc["ran"] + doc["out_of_scope"]):
        raise Refusal(
            f"the {arm} record is not an exact completed aggregate: declared "
            f"{doc['declared']}, ran {doc['ran']}, out_of_scope "
            f"{doc['out_of_scope']}")

    expired = [row["label"] for row in gates if row["exemption_expired"]]
    unexempted = [row["label"] for row in gates
                  if row["state"] == "NOT_CHECKED"
                  and row.get("exempt_until") in (None, "")]
    for field, expected in (("exemptions_expired", expired),
                            ("not_checked_unexempted", unexempted)):
        stated = doc.get(field)
        if not isinstance(stated, list) or Counter(stated) != Counter(expected):
            raise Refusal(
                f"the {arm} record disagrees with its gates about {field}")

    corpora = doc.get("corpora")
    if not isinstance(corpora, list) or not all(
            isinstance(row, dict) for row in corpora):
        raise Refusal(f"the {arm} record has no structured corpus denominator")
    names = [row.get("name") for row in corpora]
    if (any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != len(names)):
        raise Refusal(f"the {arm} record has ambiguous corpus names")
    by_corpus = Counter(str(row.get("corpus") or "") for row in gates
                        if row.get("corpus"))
    if set(by_corpus) - set(names):
        raise Refusal(
            f"the {arm} record has gates associated with an undeclared corpus")
    for meta in corpora:
        name = meta["name"]
        items = _exact_int(meta.get("items"),
                           f"the {arm} corpus {name!r} items")
        gate_count = _exact_int(meta.get("gates"),
                                f"the {arm} corpus {name!r} gates")
        if meta.get("expansion") not in ("EXPANDED", "PRODUCER_FAILED"):
            raise Refusal(
                f"the {arm} corpus {name!r} has unknown expansion state")
        associated = [row for row in gates if row.get("corpus") == name]
        if gate_count != len(associated):
            raise Refusal(
                f"the {arm} corpus {name!r} says {gate_count} gate(s), but "
                f"{len(associated)} are associated with it")
        ordinals = set()
        for row in associated:
            total = _exact_int(
                row.get("corpus_items"),
                f"the {arm} gate {row['label']!r} corpus_items")
            ordinal = _exact_int(
                row.get("corpus_item"),
                f"the {arm} gate {row['label']!r} corpus_item")
            if total != items or (items == 0 and ordinal != 0) \
                    or (items > 0 and not 1 <= ordinal <= items):
                raise Refusal(
                    f"the {arm} gate {row['label']!r} does not bind exactly "
                    f"to the {items}-item {name!r} denominator")
            if items:
                ordinals.add(ordinal)
        if associated and items and ordinals != set(range(1, items + 1)):
            raise Refusal(
                f"the {arm} corpus {name!r} does not cover every item ordinal")

    attestations = doc.get("process_attestations")
    if not isinstance(attestations, list):
        raise Refusal(f"the {arm} record has no process-attestation array")
    by_label: Dict[str, List[dict]] = {}
    for rec in attestations:
        if not isinstance(rec, dict) or not isinstance(rec.get("label"), str):
            raise Refusal(f"the {arm} record has a malformed process attestation")
        by_label.setdefault(rec["label"], []).append(rec)
    # Exact legacy compatibility, not a general missing-attestation allowance:
    # the pre-transition dispatcher synthesized this one structural EMPTY row
    # in its arrays and therefore never launched a process for it.  A real
    # 116b summary has 80 gates and 79 attestations for precisely this reason.
    # The newer dispatcher runs that SAME row through its process path, so one
    # valid rc-2 attestation is also accepted.  No other row gets two protocols.
    structural = [row for row in gates if _legacy_structural_empty(row)]
    expected_labels = [row["label"] for row in gates
                       if row["state"] in PROCESS_STATES
                       and not _legacy_structural_empty(row)]
    actual = Counter(rec.get("label") for rec in attestations)
    expected = Counter(expected_labels)
    accepted = [expected]
    if structural:
        accepted.append(expected + Counter({ROUTED_DEF_EMPTY_LABEL: 1}))
    if actual not in accepted:
        raise Refusal(
            f"the {arm} gate/process-attestation sets are not an exact "
            f"bijection")
    gate_by_label = {row["label"]: row for row in gates}
    result = {}
    for label in actual:
        records = by_label[label]
        if len(records) != 1:
            raise Refusal(
                f"the {arm} gate {label!r} has {len(records)} process "
                f"attestations, not one")
        _attestation_valid_for(gate_by_label[label], records[0], arm)
        result[label] = records[0]
    return result


def _bounded_not_checked(row: dict, today: str) -> bool:
    """Whether this NOT_CHECKED is a dated, reasoned, unexpired disclosure."""
    until = row.get("exempt_until")
    why = row.get("exempt_reason")
    if not isinstance(until, str) or not until or not str(why or "").strip():
        return False
    try:
        due = _datetime.date.fromisoformat(until)
        measured = _datetime.date.fromisoformat(today)
    except ValueError:
        return False
    return due >= measured and row.get("exemption_expired") is False


def _trusted_routed_evidence(doc: object) -> dict:
    """Validate parent-owned manifest plus independently supervised receipts."""
    top = {"schema", "complete", "origin", "benchmark_data_sha", "corpora",
           "execution_receipts"}
    if (not isinstance(doc, dict) or set(doc) != top
            or type(doc.get("schema")) is not int or doc.get("schema") != 1
            or doc.get("complete") is not True
            or doc.get("origin") != BENCHMARK_DATA_ORIGIN):
        raise Refusal("no exact complete parent-owned routed-DEF evidence record")
    sha = doc.get("benchmark_data_sha")
    if not isinstance(sha, str) or _FULL_GIT_OID.fullmatch(sha) is None:
        raise Refusal("parent-owned routed-DEF evidence has no full benchmark SHA")
    corpora = doc.get("corpora")
    if not isinstance(corpora, list) or len(corpora) != 1:
        raise Refusal("parent-owned evidence must describe exactly one corpus")
    corpus = corpora[0]
    if (not isinstance(corpus, dict) or set(corpus) != {"name", "items"}
            or corpus.get("name") != ROUTED_DEF_CORPUS
            or not isinstance(corpus.get("items"), list)
            or not corpus["items"]):
        raise Refusal("parent-owned evidence does not name a positive routed-DEF corpus")

    expected: Dict[str, dict] = {}
    paths, designs, ordinals = set(), set(), set()
    for item in corpus["items"]:
        fields = {"ordinal", "path", "mode", "blob", "gates"}
        if not isinstance(item, dict) or set(item) != fields:
            raise Refusal("a parent-owned routed-DEF manifest item is malformed")
        ordinal = _exact_int(item.get("ordinal"), "manifest item ordinal", minimum=1)
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or "\n" in raw_path or "\r" in raw_path:
            raise Refusal("a manifest routed-DEF path is not an exact string")
        path = PurePosixPath(raw_path)
        parts = path.parts
        if (path.is_absolute() or len(parts) != 7 or parts[0] != "ic"
                or parts[3:] != ("phase3", "stage3", "pnr", "routed.def")
                or any(part in ("", ".", "..") for part in parts)):
            raise Refusal(f"unsafe or non-canonical routed-DEF path: {raw_path!r}")
        design = parts[1]
        blob = item.get("blob")
        if (item.get("mode") not in ("100644", "100755")
                or not isinstance(blob, str)
                or _FULL_GIT_OID.fullmatch(blob) is None
                or len(blob) != len(sha)):
            raise Refusal(f"manifest item {raw_path!r} has no exact indexed blob")
        if raw_path in paths or design in designs or ordinal in ordinals:
            raise Refusal("parent-owned routed-DEF identities are not unique")
        paths.add(raw_path); designs.add(design); ordinals.add(ordinal)
        gates = item.get("gates")
        labels = [template.format(design=design)
                  for template in ROUTED_DEF_GATE_LABELS]
        if not isinstance(gates, list) or len(gates) != len(labels):
            raise Refusal(f"manifest item {raw_path!r} lacks its four gate identities")
        for gate, label in zip(gates, labels):
            if (not isinstance(gate, dict)
                    or set(gate) != {"label", "argv_sha256"}
                    or gate.get("label") != label
                    or not isinstance(gate.get("argv_sha256"), str)
                    or _SHA256.fullmatch(gate["argv_sha256"]) is None):
                raise Refusal(f"manifest gate for {raw_path!r} is not exact")
            if label in expected:
                raise Refusal(f"manifest repeats gate identity {label!r}")
            expected[label] = {
                "ordinal": ordinal, "argv_sha256": gate["argv_sha256"]}
    if ordinals != set(range(1, len(corpus["items"]) + 1)):
        raise Refusal("parent-owned routed-DEF manifest ordinals are not contiguous")

    receipts = doc.get("execution_receipts")
    if not isinstance(receipts, list):
        raise Refusal("parent-owned evidence has no execution receipts")
    receipt_by_label = {}
    receipt_fields = {"schema", "complete", "label", "argv_sha256",
                      "returncode", "owned"}
    owned_fields = {"protocol", "rc", "body", "problem", "outcome",
                    "launched", "census_ok", "final_descendants", "observed",
                    "capability_error"}
    for receipt in receipts:
        if (not isinstance(receipt, dict) or set(receipt) != receipt_fields
                or type(receipt.get("schema")) is not int
                or receipt.get("schema") != 1
                or receipt.get("complete") is not True):
            raise Refusal("a parent-owned execution receipt is malformed")
        label, rc, owned = (receipt.get("label"), receipt.get("returncode"),
                            receipt.get("owned"))
        if label not in expected or label in receipt_by_label:
            raise Refusal(f"parent-owned receipt has unexpected label {label!r}")
        if (receipt.get("argv_sha256") != expected[label]["argv_sha256"]
                or isinstance(rc, bool) or not isinstance(rc, int)
                or not isinstance(owned, dict) or set(owned) != owned_fields):
            raise Refusal(f"parent-owned receipt for {label!r} is not exact")
        protocol, owned_rc = owned.get("protocol"), owned.get("rc")
        observed = owned.get("observed")
        if (type(protocol) is not int or protocol != 1
                or type(owned_rc) is not int or owned_rc != rc
                or not isinstance(owned.get("body"), str)
                or owned.get("problem") is not None
                or owned.get("outcome") != "natural"
                or owned.get("launched") is not True
                or owned.get("census_ok") is not True
                or owned.get("final_descendants") != []
                or not isinstance(observed, list)
                or any(not isinstance(identity, dict)
                       or set(identity) != {"pid", "starttime"}
                       or type(identity.get("pid")) is not int
                       or identity["pid"] <= 0
                       or type(identity.get("starttime")) is not int
                       or identity["starttime"] < 0
                       for identity in (observed or []))
                or owned.get("capability_error") != ""):
            raise Refusal(
                f"parent-owned process for {label!r} lacks a natural owned "
                f"terminal result")
        receipt_by_label[label] = receipt
    if set(receipt_by_label) != set(expected):
        raise Refusal("parent-owned execution receipts do not exact-cover the manifest")
    return {
        "sha": sha, "items": len(corpus["items"]), "gates": expected,
        "receipts": receipt_by_label,
        "evidence_sha256": hashlib.sha256(json.dumps(
            doc, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest(),
    }


def _corpus_transition(base: dict, cand: dict, only_base: Counter,
                       only_cand: Counter, cand_attestations: Dict[str, dict],
                       trusted_evidence: Optional[dict]) -> dict:
    """Validate the sole permitted EMPTY-to-expanded declaration addition.

    The returned object is disclosure only.  Findings are still computed by
    :func:`findings`, so a replacement FAIL/WROTE_CORPUS/expired promise remains
    introduced and blocking.
    """
    if trusted_evidence is None:
        raise Refusal(
            "the transition has no parent-owned canonical manifest and "
            "independent execution receipts")
    trusted = _trusted_routed_evidence(trusted_evidence)
    corpus = ROUTED_DEF_CORPUS
    bmeta = _one_corpus(base, corpus, "base")
    cmeta = _one_corpus(cand, corpus, "candidate")
    if (bmeta.get("expansion") != "EXPANDED"
            or _exact_int(bmeta.get("items"), "base corpus items") != 0
            or _exact_int(bmeta.get("gates"), "base corpus gates") != 1):
        raise Refusal(
            "the routed-DEF base corpus is not the exact structural EMPTY "
            "shape (items=0, gates=1, expansion=EXPANDED)")
    items = _exact_int(cmeta.get("items"), "candidate corpus items", minimum=1)
    if cmeta.get("expansion") != "EXPANDED":
        raise Refusal(
            "the routed-DEF candidate corpus did not complete EXPANDED")

    boid, coid = _benchmark_oid(base, "base"), _benchmark_oid(cand, "candidate")
    if boid != coid or boid != trusted["sha"]:
        raise Refusal(
            "the routed-DEF arms and parent manifest do not bind the same "
            f"immutable benchmark commit: base {boid}, candidate {coid}, "
            f"parent {trusted['sha']}")

    base_rows = [g for g in base["gates"] if ident(g)[1] == corpus]
    expected_base = (ROUTED_DEF_EMPTY_LABEL, corpus)
    if (len(base_rows) != 1 or not _legacy_structural_empty(base_rows[0])
            or only_base != Counter({expected_base: 1})):
        raise Refusal(
            "the base-only declarations are not exactly the routed-DEF "
            "structural unexempted EMPTY row; unrelated removals never "
            "transition")
    unexempted = base.get("not_checked_unexempted")
    if (not isinstance(unexempted, list)
            or sum(label == ROUTED_DEF_EMPTY_LABEL for label in unexempted) != 1):
        raise Refusal(
            "the base record does not register exactly one routed-DEF EMPTY "
            "row as unexempted NOT_CHECKED")

    replacement = [g for g in cand["gates"] if ident(g)[1] == corpus]
    if not replacement:
        raise Refusal("the routed-DEF candidate declared no replacement gate")
    expected_idents = Counter((label, corpus) for label in trusted["gates"])
    replacement_idents = Counter(ident(g) for g in replacement)
    if only_cand != expected_idents or replacement_idents != expected_idents:
        raise Refusal(
            "the candidate-only declarations do not exact-cover the "
            "parent-owned routed-DEF manifest; unrelated additions never "
            "transition")
    gates = _exact_int(cmeta.get("gates"), "candidate corpus gates", minimum=1)
    if (items != trusted["items"] or gates != len(trusted["gates"])
            or gates != len(replacement)):
        raise Refusal(
            "candidate corpus counts do not equal the parent-owned manifest")

    bounded = []
    today = str(cand.get("today") or "")
    for row in replacement:
        label = row["label"]
        expected = trusted["gates"][label]
        receipt = trusted["receipts"][label]
        attested = cand_attestations[label]
        if (row.get("corpus_item") != expected["ordinal"]
                or row.get("corpus_items") != items
                or attested["argv_sha256"] != expected["argv_sha256"]
                or attested["returncode"] != receipt["returncode"]):
            raise Refusal(
                f"candidate gate {label!r} does not match its parent-owned "
                f"ordinal, command and OS return-code receipt")
        rc, state = receipt["returncode"], row["state"]
        expected_state = "PASS" if rc == 0 else "NOT_CHECKED" if rc == 2 else "FAIL"
        if state != expected_state and state != "WROTE_CORPUS":
            raise Refusal(
                f"candidate gate {label!r} says {state}, but the independently "
                f"supervised process says {expected_state} (rc {rc})")
        if state == "NOT_CHECKED":
            if row.get("exemption_expired"):
                continue                 # findings() makes this blocking
            if not _bounded_not_checked(row, today):
                raise Refusal(
                    f"replacement gate {label!r} is unexempted NOT_CHECKED; "
                    f"an unknown candidate result cannot replace an EMPTY base")
            bounded.append(label)

    return {
        "corpus": corpus,
        "base_items": 0,
        "candidate_items": items,
        "replacement_gates": len(replacement),
        "benchmark_data_sha": boid,
        "parent_evidence_sha256": trusted["evidence_sha256"],
        "bounded_not_checked": sorted(bounded),
    }


def delta(base: dict, cand: dict,
          trusted_transition_evidence: Optional[dict] = None) -> dict:
    """Findings the candidate INTRODUCED. Raises :class:`Refusal` if unanswerable."""
    base_attestations = _validate_record(base, "base")
    cand_attestations = _validate_record(cand, "candidate")
    bg, cg = list(base["gates"]), list(cand["gates"])
    # Used above to force validation symmetrically even though only the
    # candidate attestation map is additionally consumed by the bootstrap.
    del base_attestations

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

    # DECLARED-SET DRIFT, compared as identity MULTISETS: a gate that merely
    # moved position inside a loop is not drift, while one that exists on a
    # single side is. "Absent" cannot be read as "clean" when the denominators
    # differ.
    b_ident, c_ident = Counter(ident(g) for g in bg), Counter(ident(g) for g in cg)
    only_base, only_cand = b_ident - c_ident, c_ident - b_ident
    transition = None
    if only_base or only_cand:
        # One named, fully attested bootstrap replacement is recognised here.
        # `_corpus_transition` itself proves that these counters contain
        # NOTHING else; all ordinary declaration drift still refuses.
        try:
            transition = _corpus_transition(
                base, cand, only_base, only_cand, cand_attestations,
                trusted_transition_evidence)
        except Refusal as exc:
            raise Refusal(
                "the two runs declare DIFFERENT gate sets, so neither is a "
                "denominator for the other. only on the base: "
                f"{sorted(l for l, _ in only_base)[:6]}; only on the "
                f"candidate: {sorted(l for l, _ in only_cand)[:6]}. The sole "
                f"EMPTY-to-expanded exception also refused: {exc}")

    # RAN-DISAGREEMENT. A gate that reached a verdict on one side and none on
    # the other cannot be differenced: the silent side has nothing to subtract.
    b_state = {ident(g): str(g.get("state", "")) for g in bg}
    c_state = {ident(g): str(g.get("state", "")) for g in cg}
    common = b_ident & c_ident
    disagree = sorted(
        lbl for (lbl, corpus) in common
        if (b_state.get((lbl, corpus)) in UNKNOWN_STATES)
        != (c_state.get((lbl, corpus)) in UNKNOWN_STATES))
    if disagree:
        raise Refusal(
            f"these gate(s) reached a verdict on one side and none on the "
            f"other ({'/'.join(UNKNOWN_STATES)}), so whether they hold is "
            f"unknown: {disagree[:8]}. That is not a subset result.")

    b_find, c_find = findings(base), findings(cand)
    unknown_both = sorted(
        lbl for (lbl, corpus) in common
        if b_state.get((lbl, corpus)) in UNKNOWN_STATES
        and c_state.get((lbl, corpus)) in UNKNOWN_STATES)

    introduced = sorted((c_find - b_find).elements())
    result = {
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
        "declared": len(cg),
    }
    if transition is not None:
        result["corpus_transitions"] = [transition]
    return result


def compare(base_path: Path, cand_path: Path, base_host: str,
            cand_host: str,
            trusted_transition_evidence_path: Optional[Path] = None) -> dict:
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
        evidence = None
        if trusted_transition_evidence_path is not None:
            try:
                evidence = _strict_json(
                    trusted_transition_evidence_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Refusal(
                    f"parent-owned transition evidence at "
                    f"{trusted_transition_evidence_path} is unreadable: {exc}")
        return delta(load(base_path, "base"), load(cand_path, "candidate"),
                     evidence)
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
    ap.add_argument(
        "--trusted-transition-evidence", type=Path,
        help="parent-owned routed-DEF manifest and independently supervised "
             "execution receipts; dormant unless the exact EMPTY-to-expanded "
             "declaration transition occurs")
    ap.add_argument("--json", type=Path, help="write the comparison as JSON")
    a = ap.parse_args(argv)

    d = compare(a.base, a.candidate, a.base_host, a.candidate_host,
                a.trusted_transition_evidence)
    if a.json:
        # vibe-ic#1082 / #1462: this comparison IS the landing evidence — a
        # reader opens it to learn which findings the tree introduced. Under
        # `.write_text` a death mid-write leaves that name pointing at a
        # truncated record, which is indistinguishable from a complete one to
        # every consumer. `ensure_ascii=True` holds the payload byte-identical
        # to the call this replaces.
        write_json(a.json, d, ensure_ascii=True)

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
    for transition in d.get("corpus_transitions", []):
        print(
            f"  exact corpus transition: {transition['corpus']} "
            f"{transition['base_items']} -> {transition['candidate_items']} "
            f"item(s), {transition['replacement_gates']} process-attested "
            f"replacement gate(s), benchmark "
            f"{transition['benchmark_data_sha']}")
        for label in transition["bounded_not_checked"]:
            print(
                "  bounded candidate NOT_CHECKED (disclosed, excuses no "
                f"finding): {label}")
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
