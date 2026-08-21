#!/usr/bin/env python3
"""The measurement contract: build it, validate it, and refuse what it must.

WHAT A CONTRACT IS FOR
======================
"Were these two runs even solving the same problem?" Everything a PPA claim
rests on -- a frontier, a head-to-head, a closure loop that says it improved
something -- is a comparison, and a comparison is meaningless unless the two
sides agree about the problem, the analysis and the toolchain. The contract is
the document that makes that agreement CHECKABLE instead of assumed.

WHAT IT REFUSES, AND WHY EACH ONE IS A REFUSAL AND NOT A WARNING
================================================================
Every clause below exists because the alternative is a number that looks fine.

  a conflicting fact (the SDC and the spec layer disagree about the clock)
      The run measured the design against constraints that are not its
      constraints. The number is real; the claim attached to it is not. This
      contract does not pick a winner -- picking one buries the disagreement
      inside a digest where nothing downstream can ever see it. It NAMES both
      values and both sources and refuses.

  a floating verdict-bearing image reference
      `repo:latest` names different bytes on different days. A verdict that
      cites a tag cites nothing anyone can fetch, so the run is not
      reproducible even by its own author a week later.

  a missing power basis
      Power without a declared activity basis is not a measurement of this
      design; it is a measurement of an assumption. The refusal is REQUIRED
      rather than defaulted precisely because the tempting fix -- assume a
      switching activity -- produces a plausible number for every design.

  a forbidden candidate mutation
      A PPA experiment is allowed to move the implementation. Moving the
      problem and reporting a win is the oldest way to win an experiment.

  an invented numeric default
      A sentinel is worse than a hole, because a hole is visible. `0`, `-1`
      and `""` never mean "not measured" here, and a NOT_MEASURED row carries
      a reason where its value would be.

THE POLICY-ABSENT / POLICY-EMPTY DISTINCTION
============================================
An allow-list that is present and EMPTY permits nothing, and any mutation
against it is a finding. An allow-list that is ABSENT permits nothing to be
CONCLUDED, and the verdict is UNDETERMINED. They are different facts and this
module keeps them different, for the same reason `provenance` keeps "absent"
apart from "empty": a check that cannot see its policy must say so, not report
clean and not report a failure it did not establish.

CONFLICT RESOLUTION IS OPT-IN, NOT OPT-OUT
==========================================
The default for a disagreement is REFUSE. `policy.resolvable_fact_keys` lets a
declaration name specific keys where an authority order may pick a winner --
naming them, not matching a prefix. An opt-in list is a decision somebody made
and a reviewer can read; a prefix wildcard is a hole that widens every time
someone adds a key underneath it.

EXIT PRECEDENCE
===============
FAIL(1) outranks UNDETERMINED(2). A confirmed finding is news; reporting 2
because something ELSE was unchecked would hide it. Both are always listed in
the report, so choosing the rc never removes information.

chip-AGNOSTIC: documents, digests and declared policy. No IC, vendor, foundry
or process appears here or is inferred.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import identity as ident
from . import provenance as prov
from .canonical_json import digest_of

__all__ = [
    "CONTRACT_SCHEMA", "DECLARATION_SCHEMA",
    "SEV_FAIL", "SEV_UNDETERMINED", "SEV_NOTE", "FINDING_CODES",
    "DEFAULT_AUTHORITY_ORDER", "POWER_BASIS_POLICIES",
    "build", "validate", "rc_from", "contract_digest_of", "load_json",
    "format_findings", "marker_for", "denominators",
    "format_denominators",
    "finding",
]

CONTRACT_SCHEMA = "vibeic.ppa.contract.v1"
DECLARATION_SCHEMA = "vibeic.ppa.contract_declaration.v1"

SEV_FAIL = "FAIL"
SEV_UNDETERMINED = "UNDETERMINED"
#: Reported, printed, and NOT a verdict. See `_check_images` for the one thing
#: that carries it and why a gate that can never be GREEN is as broken as one
#: that can never be RED.
SEV_NOTE = "NOTE"

#: Most authoritative first. Used ONLY for keys a declaration opts into via
#: `policy.resolvable_fact_keys`; a key outside that list is never resolved.
#: `sdc` leads because it is what the analysis engine actually read -- the
#: spec layer states what SHOULD have been analysed, and when those two differ
#: the difference is the finding, not something to rank away.
DEFAULT_AUTHORITY_ORDER = ("sdc", "l19_spec", "l1_spec", "runner", "declared")

#: The two answers a declaration may give for "power metrics, no activity
#: basis". There is deliberately no third that means "carry on".
POWER_BASIS_POLICIES = {"REFUSE": SEV_FAIL, "UNDETERMINED": SEV_UNDETERMINED}

#: Statuses a metric may carry a numeric `value` with. Everything else carries
#: a `reason` instead -- see PPA_INTERFACES.md section 2.
_VALUE_BEARING_STATUSES = {"MEASURED", "DERIVED"}


#: Every finding code this package may emit, with the one line that says what
#: it means. THE REGISTRY IS THE SOURCE, not the docstrings: `finding()`
#: refuses an unregistered code, so a new refusal cannot be invented without
#: being written down here, and `test_ppa_contract` asserts every entry is
#: named in a CLI docstring. Measured while writing this: the check's docstring
#: had drifted two codes behind the code that emits them, which is how a report
#: starts carrying identifiers no document explains.
FINDING_CODES = {
    "PPA-C-001": "the contract does not hash to its own stated digest",
    "PPA-C-002": "a verdict-bearing image reference floats",
    "PPA-C-003": "two sources declare one key with two values",
    "PPA-C-004": "a power metric carries a value with no declared activity basis",
    "PPA-C-005": "a candidate mutated something outside the allow-list",
    "PPA-C-006": "an invented number: a default, an assumption, or a sentinel",
    "PPA-C-007": "an identity is NOT_MEASURED or absent",
    "PPA-C-008": "a metric cites an artefact the evidence manifest cannot back",
    "PPA-C-009": "a conflict names a source no authority order ranks",
    "PPA-C-010": "the document is not a contract, or a schema could not be applied",
    "PPA-C-011": "a policy the check depends on was not declared",
    "PPA-C-012": "the problem, analysis or toolchain identity moved between arms",
    "PPA-C-013": "the two arms have the same implementation identity",
    "PPA-C-014": "an image pins bytes but its OCI version label could not be read",
    "PPA-C-015": "a key was resolved by authority; the overridden values are named",
    "PPA-C-016": "an artefact that varies with the implementation is declared under `analysis`",
}

def finding(code: str, severity: str, message: str, **detail: Any) -> Dict[str, Any]:
    """One machine-readable verdict line.

    `code` is stable and greppable so a consumer can act on a class of finding
    without parsing prose, and so a report from six months ago can still be
    read. `message` is for the human who has to fix it and says what is wrong,
    not merely which rule fired.
    """
    if code not in FINDING_CODES:
        raise ValueError(
            f"unregistered finding code {code!r}. Add it to FINDING_CODES with "
            f"the one line that says what it means: a report carrying an "
            f"identifier no document explains cannot be acted on.")
    if severity not in (SEV_FAIL, SEV_UNDETERMINED, SEV_NOTE):
        raise ValueError(f"unknown severity {severity!r}")
    row: Dict[str, Any] = {"code": code, "severity": severity, "message": message}
    row.update(detail)
    return row


def contract_digest_of(document: Mapping[str, Any]) -> str:
    """The contract's own identity: a digest over every key but that digest.

    Self-exclusion rather than a separate sidecar file, so the document cannot
    be separated from its identity by a copy that forgets the sidecar.
    """
    return digest_of({k: v for k, v in document.items() if k != "contract_digest"})


def load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Read a JSON document, returning `(obj, None)` or `(None, reason)`.

    Never raises and never returns an empty object for a file it could not
    read. The caller turns a reason into rc=2 with a marker; an exception here
    would surface as rc=1 through a bare `SystemExit`, which is the defect
    PPA_INTERFACES.md section 1 records as shipped twice.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"{path}: absent"
    except OSError as exc:
        return None, f"{path}: unreadable ({exc.__class__.__name__})"
    try:
        return json.loads(text), None
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"{path}: not valid JSON ({exc.__class__.__name__})"


# ---------------------------------------------------------------------------
# authority order
# ---------------------------------------------------------------------------

def resolve_conflicts(declared_facts: Sequence[Mapping[str, Any]],
                      policy: Mapping[str, Any]
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pick a winner for the keys a declaration OPTED IN, and say who lost.

    Returns `(resolutions, unrankable)`.

    A resolution is never silent. `PPA-C-015` prints it as a NOTE naming the
    winning source, its value, and every value it overrode -- because "the SDC
    won and the spec layer said something else" is precisely the fact a reader
    needs and precisely the fact a silent resolution destroys. That is why the
    DEFAULT is refusal and this runs only for keys named in
    `policy.resolvable_fact_keys`.

    A key whose claims name a source absent from the authority order cannot be
    resolved: nothing ranks it, so there is no winner to pick. It comes back in
    `unrankable` and becomes an UNDETERMINED finding rather than an arbitrary
    choice of whichever claim happened to be first.
    """
    resolvable = set(policy.get("resolvable_fact_keys", []) or [])
    order = list(policy.get("authority_order", DEFAULT_AUTHORITY_ORDER))
    by_key: Dict[str, List[Mapping[str, Any]]] = {}
    for row in declared_facts:
        by_key.setdefault(str(row.get("key", "")), []).append(row)

    resolutions: List[Dict[str, Any]] = []
    unrankable: List[Dict[str, Any]] = []
    for key in sorted(by_key):
        if key not in resolvable:
            continue
        claims = by_key[key]
        if len({digest_of(c.get("value")) for c in claims}) < 2:
            continue
        ranks = [str(c.get("source", "")) for c in claims]
        missing = sorted({r for r in ranks if r not in order})
        if missing:
            unrankable.append({"key": key, "sources": missing,
                               "authority_order": order})
            continue
        ordered = sorted(claims, key=lambda c: (order.index(str(c.get("source", ""))),
                                                digest_of(c.get("value"))))
        winner, losers = ordered[0], ordered[1:]
        resolutions.append({
            "key": key,
            "authority_order": order,
            "winner": {"source": str(winner.get("source", "")),
                       "value": winner.get("value"),
                       "source_path": winner.get("source_path")},
            "overridden": [{"source": str(c.get("source", "")),
                            "value": c.get("value"),
                            "source_path": c.get("source_path")}
                           for c in losers],
        })
    return resolutions, unrankable


def _apply_resolutions(blocks: Dict[str, Dict[str, Any]],
                       resolutions: Sequence[Mapping[str, Any]]) -> None:
    """Collapse each resolved key to its winning value BEFORE the identities.

    The authority order exists so an identity has ONE value for a key. Leaving
    the losing claims in would make `identity` refuse to hash the key it was
    just told how to settle, and the opt-in would do nothing.
    """
    winners = {r["key"]: r["winner"]["value"] for r in resolutions}
    if not winners:
        return
    for block in blocks.values():
        facts = list(block.get("facts", []) or [])
        kept: List[Dict[str, Any]] = []
        seen: set = set()
        for fact in facts:
            key = str(fact.get("key", ""))
            if key not in winners:
                kept.append(fact)
                continue
            if key in seen:
                continue
            seen.add(key)
            settled = dict(fact)
            settled["value"] = winners[key]
            settled["source"] = "authority_resolved"
            kept.append(settled)
        block["facts"] = kept


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _artefact_blocks(declaration: Mapping[str, Any], root: Path
                     ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Hash every declared artefact once, grouped by identity kind."""
    blocks: Dict[str, Dict[str, Any]] = {}
    every: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for kind in ident.IDENTITY_KINDS:
        decl = declaration.get(kind)
        if decl is None:
            continue
        rows = prov.artefact_refs(root, decl.get("artefacts", []) or [])
        blocks[kind] = {"artefacts": rows, "facts": decl.get("facts", []) or []}
        for row in rows:
            every[(row.get("role", ""), row.get("path", ""))] = row
    return blocks, [every[k] for k in sorted(every)]


def build(declaration: Mapping[str, Any],
          root: Path,
          label_reader: Optional[Callable[[str], Optional[str]]] = None
          ) -> Dict[str, Any]:
    """Turn a declaration plus the tree it points at into a contract document.

    The result is a pure function of the declaration and the BYTES under
    `root`. No clock, no hostname, no pid, no absolute path -- which is what
    makes "build it twice, compare the bytes" a meaningful test rather than a
    formality. `test_ppa_contract_stability` runs exactly that, in two
    processes, because a same-process comparison would not catch a hash seed
    or a dict order that happened to be stable within one interpreter.
    """
    root = Path(root)
    blocks, all_artefacts = _artefact_blocks(declaration, root)

    toolchain_decl = declaration.get("toolchain", {}) or {}
    images = [prov.image_record(d, reader=label_reader)
              for d in toolchain_decl.get("images", []) or []]

    # The image DIGESTS enter the toolchain identity; the VERSIONS do not.
    # A version is a label read at some moment from somewhere, and whether the
    # read succeeded is a property of the host, not of the toolchain. Hashing
    # it would make the same toolchain produce two identities depending on
    # whether a registry was reachable -- and then two runs on one image would
    # look like two different toolchains.
    image_facts = [
        {"key": f"image.{row.get('role', '')}", "value": row.get("digest"),
         "source": "declared"}
        for row in images if row.get("digest")
    ]
    tc_block = blocks.setdefault("toolchain", {"artefacts": [], "facts": []})
    tc_block["facts"] = list(tc_block.get("facts", [])) + image_facts

    declared_facts = _declared_facts(declaration)
    resolutions, _unrankable = resolve_conflicts(
        declared_facts, declaration.get("policy", {}) or {})
    _apply_resolutions(blocks, resolutions)

    ids = ident.identities(blocks)

    manifest = prov.run_manifest(
        root_label=str(declaration.get("root_label", "")),
        images=images,
        tools=list(toolchain_decl.get("tools", []) or []),
        artefacts=all_artefacts)

    # ABSENT means "everything the run read backs the verdict", which is the
    # honest default for a declaration that has not narrowed it. PRESENT means
    # EXACTLY the roles named -- including present-and-matching-nothing, which
    # yields an EMPTY evidence manifest and makes every metric's citation a
    # PPA-C-008. A `or all_artefacts` fallback here would turn a filter that
    # matched nothing into a filter over everything, silently, which is the
    # same absent/empty collapse this module refuses everywhere else.
    if "verdict_evidence_roles" in declaration:
        wanted = set(declaration.get("verdict_evidence_roles") or [])
        evidence_rows = [r for r in all_artefacts if r.get("role", "") in wanted]
    else:
        evidence_rows = all_artefacts
    evidence = prov.evidence_manifest(evidence_rows)

    document: Dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "run_label": str(declaration.get("run_label", "")),
        "identities": ids,
        "run_manifest": manifest,
        "evidence_manifest": evidence,
        "policy": declaration.get("policy", {}) or {},
        "declared_facts": declared_facts,
        "resolutions": resolutions,
        "candidate": declaration.get("candidate", {}) or {},
        "metrics": list(declaration.get("metrics", []) or []),
    }
    document["contract_digest"] = contract_digest_of(document)
    return document


def _declared_facts(declaration: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every fact any kind declared, WITH its source, sorted and de-duplicated.

    The identities collapse facts to one value per key; this list keeps them
    apart, because conflict detection needs to know WHO said WHAT. Losing the
    source is losing the ability to name the conflict, and a conflict nobody
    can name is one nobody can fix.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for kind in ident.IDENTITY_KINDS:
        block = declaration.get(kind) or {}
        for fact in block.get("facts", []) or []:
            row = {
                "identity": kind,
                "key": str(fact.get("key", "")),
                "value": fact.get("value"),
                "source": str(fact.get("source", "")),
            }
            if fact.get("source_path"):
                row["source_path"] = str(fact["source_path"])
            for extra in ("origin", "assumed"):
                if extra in fact:
                    row[extra] = fact[extra]
            seen[digest_of(row)] = row
    return [seen[k] for k in sorted(seen)]


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def _check_digest(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    stated = document.get("contract_digest")
    if not stated:
        return [finding("PPA-C-001", SEV_FAIL,
                        "the contract states no contract_digest, so nothing "
                        "downstream can tell whether it is the document that "
                        "was built or one that was edited afterwards")]
    recomputed = contract_digest_of(document)
    if stated != recomputed:
        return [finding("PPA-C-001", SEV_FAIL,
                        "the contract does not hash to its own stated digest: "
                        "it was modified after it was built, so every identity "
                        "in it describes a document that no longer exists",
                        stated=stated, recomputed=recomputed)]
    return []


def _check_identities(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ids = document.get("identities", {}) or {}
    for kind in ident.IDENTITY_KINDS:
        record = ids.get(kind)
        if record is None:
            out.append(finding(
                "PPA-C-007", SEV_UNDETERMINED,
                f"identity {kind!r} is absent from the contract; a contract "
                f"missing an identity cannot support a claim that this run "
                f"and another one agreed about it", identity=kind))
            continue
        if record.get("status") != prov.MEASURED:
            out.append(finding(
                "PPA-C-007", SEV_UNDETERMINED,
                f"identity {kind!r} is NOT_MEASURED: "
                f"{record.get('reason', 'no reason stated')}",
                identity=kind, reason=record.get("reason")))
    return out


def _check_conflicts(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Two sources, one key, two values -- named, never resolved by default."""
    out: List[Dict[str, Any]] = []
    policy = document.get("policy", {}) or {}
    resolvable = set(policy.get("resolvable_fact_keys", []) or [])
    order = list(policy.get("authority_order", DEFAULT_AUTHORITY_ORDER))

    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for row in document.get("declared_facts", []) or []:
        by_key.setdefault(row.get("key", ""), []).append(row)

    for key in sorted(by_key):
        rows = by_key[key]
        distinct = {digest_of(r.get("value")): r for r in rows}
        if len(distinct) < 2:
            continue
        claims = [
            {"source": r.get("source", ""), "value": r.get("value"),
             "source_path": r.get("source_path")}
            for r in sorted(rows, key=lambda x: (str(x.get("source", "")),
                                                 digest_of(x.get("value"))))
        ]
        named = ", ".join(
            f"{c['source'] or 'unnamed source'}={json.dumps(c['value'])}"
            + (f" ({c['source_path']})" if c.get("source_path") else "")
            for c in claims)
        if key not in resolvable:
            out.append(finding(
                "PPA-C-003", SEV_FAIL,
                f"sources disagree about {key}: {named}. The run measured the "
                f"design against one of these and the claim attached to it "
                f"assumes the other; this contract does not choose between "
                f"them because choosing would bury the disagreement inside a "
                f"digest",
                key=key, claims=claims))
            continue
        unrankable = sorted({c["source"] for c in claims
                             if c["source"] not in order})
        if unrankable:
            out.append(finding(
                "PPA-C-009", SEV_UNDETERMINED,
                f"{key} was opted into authority resolution but "
                f"{', '.join(repr(s) for s in unrankable)} is not in the "
                f"declared authority order {order}, so no source can be "
                f"ranked above another and the winner is unknown",
                key=key, claims=claims, authority_order=order))
            continue
        recorded = next((r for r in document.get("resolutions", []) or []
                         if r.get("key") == key), None)
        if recorded is None:
            out.append(finding(
                "PPA-C-009", SEV_UNDETERMINED,
                f"{key} has conflicting claims and is opted into authority "
                f"resolution, but the contract records NO resolution for it — "
                f"a winner was applied somewhere without being written down, "
                f"or none was applied at all",
                key=key, claims=claims))
            continue
        out.append(finding(
            "PPA-C-015", SEV_NOTE,
            f"{key} was resolved by authority: "
            f"{recorded['winner']['source']}="
            f"{json.dumps(recorded['winner']['value'])} wins over "
            + "; ".join(f"{o['source']}={json.dumps(o['value'])}"
                        for o in recorded["overridden"])
            + ". A resolution is printed rather than applied silently: which "
              "source won, and what the others said, is exactly the fact a "
              "silent resolution destroys",
            key=key, resolution=recorded))
    return out


def _check_images(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    policy = document.get("policy", {}) or {}
    manifest = document.get("run_manifest", {}) or {}
    for row in manifest.get("images", []) or []:
        if not row.get("verdict_bearing"):
            continue
        if row.get("floating"):
            out.append(finding(
                "PPA-C-002", SEV_FAIL,
                f"image {row.get('ref')!r} carries a verdict but does not pin "
                f"bytes (form={row.get('form')}); the same reference resolves "
                f"to different content on different days, so the evidence "
                f"behind this verdict cannot be fetched again",
                role=row.get("role"), ref=row.get("ref"), form=row.get("form")))
            continue
        version = row.get("version", {}) or {}
        if version.get("status") != prov.MEASURED:
            # A NOTE by default, and this is a deliberate line. The property a
            # verdict rests on is that the evidence can be FETCHED AGAIN, and
            # the digest already delivers it; the OCI label is the human-
            # readable convenience beside it. Making an unread label
            # UNDETERMINED would mean a gate that can never be green on any
            # host without a registry -- and a gate that can never PASS is the
            # mirror of the gate that can never FAIL which this repository has
            # already shipped twice. A declaration that needs the label can say
            # so with policy.missing_image_version.
            declared = str(policy.get("missing_image_version", "NOTE"))
            severity = {"NOTE": SEV_NOTE,
                        "UNDETERMINED": SEV_UNDETERMINED}.get(declared)
            if severity is None:
                out.append(finding(
                    "PPA-C-011", SEV_UNDETERMINED,
                    f"policy.missing_image_version is {declared!r}, which is "
                    f"neither 'NOTE' nor 'UNDETERMINED'; an unrecognised "
                    f"policy is not a permission to continue",
                    declared=declared))
                continue
            out.append(finding(
                "PPA-C-014", severity,
                f"image {row.get('ref')!r} pins bytes but its "
                f"{prov.IMAGE_VERSION_LABEL} label could not be read, so the "
                f"human-readable version is NOT_MEASURED — not a guess and not "
                f"a remembered number. The digest is the reproduction key and "
                f"it is intact",
                role=row.get("role"), ref=row.get("ref"),
                reason=version.get("reason")))
    return out


def _check_power_basis(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Power without a declared activity basis is a measurement of a guess."""
    metrics = document.get("metrics", []) or []
    power = [m for m in metrics
             if str(m.get("metric", "")).startswith("power.")
             and m.get("status") in _VALUE_BEARING_STATUSES]
    offenders = [m for m in power
                 if not str((m.get("scope") or {}).get("activity_basis", "")).strip()]
    if not offenders:
        return []
    policy = document.get("policy", {}) or {}
    if "missing_power_basis" not in policy:
        return [finding(
            "PPA-C-011", SEV_UNDETERMINED,
            f"{len(offenders)} power metric(s) declare no scope.activity_basis "
            f"and the contract declares no policy.missing_power_basis, so this "
            f"check cannot say whether that is a refusal or an undetermined "
            f"result. It will not pick one: an invented policy is how an "
            f"invented switching activity gets in",
            metrics=[m.get("metric") for m in offenders])]
    declared = str(policy.get("missing_power_basis"))
    severity = POWER_BASIS_POLICIES.get(declared)
    if severity is None:
        return [finding(
            "PPA-C-011", SEV_UNDETERMINED,
            f"policy.missing_power_basis is {declared!r}, which is not one of "
            f"{sorted(POWER_BASIS_POLICIES)}; an unrecognised policy is not a "
            f"permission to continue",
            declared=declared)]
    return [finding(
        "PPA-C-004", severity,
        f"{len(offenders)} power metric(s) carry a value with no declared "
        f"scope.activity_basis: {', '.join(str(m.get('metric')) for m in offenders)}. "
        f"Power computed from an undeclared activity basis is a measurement of "
        f"that assumption, not of this design (policy.missing_power_basis="
        f"{declared})",
        metrics=[m.get("metric") for m in offenders], policy=declared)]


def _matches(pattern: str, target: str) -> bool:
    """Exact key, or a single trailing `.*` prefix. No general globbing.

    A general glob in an allow-list is unreadable at review time: `*` and
    `?` anywhere make the reader simulate a matcher to know what is permitted.
    One explicit trailing form is enough for a namespace and stays legible.
    """
    if pattern.endswith(".*"):
        return target == pattern[:-2] or target.startswith(pattern[:-1])
    return target == pattern


def _check_mutations(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    candidate = document.get("candidate", {}) or {}
    mutations = candidate.get("mutations", []) or []
    if not mutations:
        return []
    policy = document.get("policy", {}) or {}
    forbidden = list(policy.get("mutation_forbidden", []) or [])
    out: List[Dict[str, Any]] = []

    if "mutation_allow_list" not in policy:
        return [finding(
            "PPA-C-011", SEV_UNDETERMINED,
            f"{len(mutations)} candidate mutation(s) are declared and the "
            f"contract declares no policy.mutation_allow_list. An ABSENT "
            f"allow-list is not an empty one: this check cannot see what was "
            f"permitted, so it reports UNDETERMINED rather than a refusal it "
            f"has not established",
            mutations=[str(m.get("target", "")) for m in mutations])]

    allow = list(policy.get("mutation_allow_list") or [])
    for mutation in mutations:
        target = str(mutation.get("target", ""))
        hit = next((p for p in forbidden if _matches(p, target)), None)
        if hit is not None:
            out.append(finding(
                "PPA-C-005", SEV_FAIL,
                f"candidate mutation {target!r} matches the forbidden pattern "
                f"{hit!r}. A candidate that moves this has changed the problem, "
                f"so a win over the baseline is a win in a different contest",
                target=target, pattern=hit,
                **{"from": mutation.get("from"), "to": mutation.get("to")}))
            continue
        if not any(_matches(p, target) for p in allow):
            out.append(finding(
                "PPA-C-005", SEV_FAIL,
                f"candidate mutation {target!r} is not in the declared "
                f"allow-list {allow}. An allow-list is closed: anything it "
                f"does not name is not permitted",
                target=target, allow_list=allow,
                **{"from": mutation.get("from"), "to": mutation.get("to")}))
    return out


def _check_no_invented_numbers(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """No sentinel, no assumption wearing a measurement's clothes."""
    out: List[Dict[str, Any]] = []

    used = list(document.get("policy", {}).get("defaults_used", []) or [])
    if used:
        out.append(finding(
            "PPA-C-006", SEV_FAIL,
            f"the contract declares {len(used)} default value(s) were used: "
            f"{', '.join(str(u) for u in used)}. A default is a number nobody "
            f"measured, and in a PPA comparison it is indistinguishable from "
            f"one somebody did",
            defaults=used))

    for row in document.get("declared_facts", []) or []:
        origin = str(row.get("origin", "")).lower()
        if origin in {"default", "assumed", "fallback"} or row.get("assumed") is True:
            out.append(finding(
                "PPA-C-006", SEV_FAIL,
                f"fact {row.get('key')!r} carries origin={origin or 'assumed'} "
                f"— it was supplied, not measured, and it is entering an "
                f"identity as though it had been",
                key=row.get("key"), source=row.get("source"), origin=origin))

    for metric in document.get("metrics", []) or []:
        name = str(metric.get("metric", "<unnamed>"))
        status = str(metric.get("status", ""))
        if status == "ESTIMATED":
            out.append(finding(
                "PPA-C-006", SEV_FAIL,
                f"metric {name} is ESTIMATED; PPA_INTERFACES.md section 2 "
                f"puts ESTIMATED outside final PPA entirely",
                metric=name, status=status))
            continue
        has_value = "value" in metric
        if status in _VALUE_BEARING_STATUSES and not has_value:
            out.append(finding(
                "PPA-C-006", SEV_FAIL,
                f"metric {name} is {status} but carries no value",
                metric=name, status=status))
        if status not in _VALUE_BEARING_STATUSES and has_value:
            out.append(finding(
                "PPA-C-006", SEV_FAIL,
                f"metric {name} is {status} and still carries a value "
                f"({metric.get('value')!r}). A non-measured row carries a "
                f"reason where its value would be; a number here is a "
                f"sentinel that reads as data",
                metric=name, status=status, value=metric.get("value")))
        if status == "NOT_MEASURED" and not str(metric.get("reason", "")).strip():
            out.append(finding(
                "PPA-C-006", SEV_FAIL,
                f"metric {name} is NOT_MEASURED and states no reason; "
                f"'not measured' without a reason cannot be acted on",
                metric=name))
        if status == "DERIVED" and not str(metric.get("formula", "")).strip():
            out.append(finding(
                "PPA-C-006", SEV_FAIL,
                f"metric {name} is DERIVED and states no formula, so a reader "
                f"cannot recompute it and cannot tell what it derives from",
                metric=name))
    return out


def _check_evidence_backing(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """A metric whose source artefact is not in the evidence manifest."""
    evidence = document.get("evidence_manifest", {}) or {}
    rows = {str(r.get("path", "")): r for r in evidence.get("artefacts", []) or []}
    out: List[Dict[str, Any]] = []
    for metric in document.get("metrics", []) or []:
        if metric.get("status") not in _VALUE_BEARING_STATUSES:
            continue
        path = str((metric.get("source") or {}).get("path", "")).strip()
        if not path:
            out.append(finding(
                "PPA-C-008", SEV_FAIL,
                f"metric {metric.get('metric')} carries a value and names no "
                f"source artefact, so its provenance is undeclared",
                metric=metric.get("metric")))
            continue
        row = rows.get(path)
        if row is None:
            out.append(finding(
                "PPA-C-008", SEV_FAIL,
                f"metric {metric.get('metric')} cites {path!r}, which is not "
                f"in the evidence manifest — the contract hashed a different "
                f"set of artefacts than the numbers were read from",
                metric=metric.get("metric"), path=path))
            continue
        if row.get("status") != prov.MEASURED:
            out.append(finding(
                "PPA-C-008", SEV_FAIL,
                f"metric {metric.get('metric')} carries a value read from "
                f"{path!r}, and that artefact is NOT_MEASURED "
                f"({row.get('reason', 'no reason stated')}). The number exists "
                f"and the file behind it does not hash, so nothing can confirm "
                f"the number came from this run",
                metric=metric.get("metric"), path=path,
                reason=row.get("reason")))
    return out


def validate(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every refusal, in one list, ordered by code so a diff of two reports
    lines up. An empty list is the only PASS."""
    if str(document.get("schema", "")) != CONTRACT_SCHEMA:
        return [finding(
            "PPA-C-010", SEV_UNDETERMINED,
            f"document declares schema {document.get('schema')!r}, not "
            f"{CONTRACT_SCHEMA!r}; this validator has not established anything "
            f"about it")]
    out: List[Dict[str, Any]] = []
    for check in (_check_digest, _check_identities, _check_conflicts,
                  _check_images, _check_power_basis, _check_mutations,
                  _check_no_invented_numbers, _check_evidence_backing):
        out.extend(check(document))
    return sorted(out, key=lambda f: (f["code"], f["message"]))


def rc_from(findings: Sequence[Mapping[str, Any]]) -> int:
    """0 clean, 1 at least one FAIL, 2 otherwise-undetermined. See EXIT
    PRECEDENCE in the module docstring: a confirmed finding outranks an
    unchecked one, and the report lists both regardless."""
    if any(f.get("severity") == SEV_FAIL for f in findings):
        return 1
    if any(f.get("severity") == SEV_UNDETERMINED for f in findings):
        return 2
    return 0  # SEV_NOTE rows land here: reported, printed, not a verdict.


def format_findings(findings: Sequence[Mapping[str, Any]]) -> List[str]:
    """Human lines for a report, one finding each, code first.

    Shared by all three `ppa_*` CLIs so the three cannot drift into three
    dialects of the same verdict -- a reader who has learned to read one
    report has learned to read all of them.
    """
    lines: List[str] = []
    for f in findings:
        lines.append(f"  [{f.get('severity')}] {f.get('code')}: {f.get('message')}")
    return lines


def marker_for(rc: int) -> str:
    """The stdout/stderr marker a verdict must print.

    An rc alone is invisible in a log; PPA_INTERFACES.md section 1 requires a
    marker so a 2 can never be read as a silent skip.
    """
    return {0: "[PASS]", 1: "[REFUSE]", 2: "[CANNOT CHECK]"}.get(rc, "[ERROR]")

def denominators(document: Mapping[str, Any]) -> Dict[str, int]:
    """What the validator actually LOOKED AT, so "0 findings" says what it is.

    A clean report over an empty document and a clean report over a full one
    print the same `0`. This repository has a standing rule about that -- a
    zero with no denominator beside it is indistinguishable from a check that
    ran over nothing -- and a contract is exactly the kind of document that can
    be trivially clean by being trivially empty.

    Reported, never asserted on: how many metrics a contract SHOULD carry is
    not this module's question, and inventing a floor here would be a threshold
    in a module whose job is identity.
    """
    manifest = document.get("run_manifest", {}) or {}
    evidence = document.get("evidence_manifest", {}) or {}
    metrics = document.get("metrics", []) or []
    ids = document.get("identities", {}) or {}
    return {
        "identities_measured": sum(
            1 for k in ident.IDENTITY_KINDS
            if (ids.get(k) or {}).get("status") == prov.MEASURED),
        "identities_total": len(ident.IDENTITY_KINDS),
        "artefacts_measured": sum(
            1 for r in manifest.get("artefacts", []) or []
            if r.get("status") == prov.MEASURED),
        "artefacts_declared": len(manifest.get("artefacts", []) or []),
        "evidence_artefacts": len(evidence.get("artefacts", []) or []),
        "images": len(manifest.get("images", []) or []),
        "images_verdict_bearing": sum(
            1 for r in manifest.get("images", []) or []
            if r.get("verdict_bearing")),
        "declared_facts": len(document.get("declared_facts", []) or []),
        "resolutions": len(document.get("resolutions", []) or []),
        "candidate_mutations": len(
            (document.get("candidate", {}) or {}).get("mutations", []) or []),
        "metrics": len(metrics),
        "metrics_value_bearing": sum(
            1 for m in metrics if m.get("status") in _VALUE_BEARING_STATUSES),
        "metrics_power": sum(
            1 for m in metrics
            if str(m.get("metric", "")).startswith("power.")),
    }


def format_denominators(counts: Mapping[str, int]) -> List[str]:
    """The disclosure lines that go beside a verdict."""
    return [
        f"   examined: {counts['identities_measured']}/"
        f"{counts['identities_total']} identities MEASURED, "
        f"{counts['artefacts_measured']}/{counts['artefacts_declared']} "
        f"declared artefacts hashed, {counts['evidence_artefacts']} in the "
        f"evidence manifest",
        f"   examined: {counts['images']} image(s) "
        f"({counts['images_verdict_bearing']} verdict-bearing), "
        f"{counts['declared_facts']} declared fact(s), "
        f"{counts['resolutions']} authority resolution(s), "
        f"{counts['candidate_mutations']} candidate mutation(s)",
        f"   examined: {counts['metrics']} metric(s), "
        f"{counts['metrics_value_bearing']} carrying a value, "
        f"{counts['metrics_power']} of them power",
    ]
