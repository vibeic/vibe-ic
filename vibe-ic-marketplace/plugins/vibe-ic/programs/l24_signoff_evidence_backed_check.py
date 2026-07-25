#!/usr/bin/env python3
"""
l24_signoff_evidence_backed_check.py — batch-8 / layergate-8 (L24_SIGNOFF)

WHAT THIS GATE ENFORCES
=======================
L24_SIGNOFF models per-gate sign-off status (drc / lvs / sta / antenna /
ir_drop) plus a tapeout-gate checklist.

The consumer contract, stated honestly:

    L24 HAS NO CONSUMER TODAY. The statuses it models are produced by phase-3
    programs (signoff_ladder_run.py, tapeout_checklist, dft_signoff_check.py)
    which write their OWN reports and never read — or write back to — L24.
    In 24/24 sampled real Phase-1 runs the layer is 100% inert:
    extraction_status=NOT_YET_EXTRACTED, every status null, tapeout_gates [].

So this gate does NOT demand that L24 be filled in. Demanding content for a
layer nobody reads would be exactly the "token appears somewhere" mistake in
reverse: manufacturing work that no consumer needs.

What it enforces is the HAZARD that arrives the instant a consumer IS added:

    A Phase-1-asserted drc_status='PASS' with no evidence path is the
    false-certificate shape. It is the same failure family as the defect that
    motivated this batch — a completeness check that said CAPTURED because a
    token appeared in some layer, while the layer the backend actually
    consumed had it 0 times, and the whole detailed route aborted five steps
    downstream behind an opaque router error.

THE RULE
--------
    A sign-off status is complete when it is DERIVED from an evidence path —
    a report file that exists inside this project, plus the value that was
    read out of it — never when it is an asserted string.

Concretely, for every verdict L24 asserts:
  (1) it must be bound to an evidence record naming a PATH,
  (2) that path must resolve to a file INSIDE the project (evidence outside
      the run is not reproducible evidence),
  (3) the record must name the VALUE that was read back ("I looked at the
      report" is not evidence of WHAT was read), and
  (4) that value must still be findable in that file.

Claims are discovered from the layer's OWN key names (any ``*_status`` /
``status`` / ``verdict`` / ``result`` key, at any depth, including inside
``tapeout_gates[]``). Nothing about any design, PDK, vendor or signal is
hardcoded — this gate has never seen the design it is checking.

Only the ABSENCE of information is enumerated (null, TBD, PENDING,
NOT_YET_EXTRACTED, ...). Everything else counts as a CLAIM. That direction is
deliberate: a whitelist of positive verdicts would let a novel verdict word
through silently, which is the exact class of hole this gate exists to close.

BLOCKS OR ADVISES?
------------------
**BLOCKS** (exit 1 is a hard FAIL; it is NOT listed in
flow_compliance_check.INFORMATIONAL_GATES).

Why blocking is the right call even though L24 has no consumer:
  * The gate can only fire when the layer ASSERTS a sign-off verdict. On the
    inert layer every real run emits today, it exits 2 (SKIP) and costs
    nothing — 24/24 sampled runs SKIP, zero false positives.
  * The only way to make it fail is to publish an unevidenced certificate.
    There is no legitimate reason for Phase 1 — which runs before DRC, LVS
    and STA exist — to certify their outcome. A gate that merely *advised*
    here would repeat compounding failure (b) from the motivating defect: the
    verdict was FAIL and the flow continued anyway.
  * It forecloses the hazard the day a consumer is wired in, instead of
    discovering it five steps downstream like last time.

NO WAIVER (governance-hard). A waiver here would read "let me certify
sign-off without evidence", which is the thing being prevented.

Usage:
    python3 l24_signoff_evidence_backed_check.py <project_dir>

Exit codes:
    0 = PASS  — every asserted verdict traces to a verified evidence read-back
    1 = FAIL  — at least one verdict is asserted without verifiable evidence
    2 = SKIP  — no L24 present, L24 is an N/A stub, or the layer asserts
                nothing (today's real-run state)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from l_doc_evidence_util import (  # noqa: E402
    EvidenceVerdict,
    find_layer_files,
    is_no_information,
    is_populated,
    load_json,
    verify_evidence_binding,
)

_STEM = "L24_SIGNOFF"

# A key carries a sign-off VERDICT when its own name says so. Derived from the
# layer's key names — chip/PDK/vendor-agnostic.
_VERDICT_KEY_SUFFIXES = ("_status", "_verdict", "_result", "_signoff",
                         "_sign_off", "_state")
_VERDICT_KEY_EXACT = ("status", "verdict", "result", "signoff", "sign_off",
                      "outcome", "disposition")

# Keys that are metadata ABOUT the extraction, not sign-off verdicts. Without
# this, `extraction_status: "NOT_YET_EXTRACTED"` would be read as a claim.
_META_KEY_EXACT = ("extraction_status", "applicability", "doc_id", "doc_name",
                   "ic_class", "emitted_by", "schema_version")


def _is_verdict_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    k = key.strip().lower()
    if k in _META_KEY_EXACT:
        return False
    if k in _VERDICT_KEY_EXACT:
        return True
    return any(k.endswith(suf) for suf in _VERDICT_KEY_SUFFIXES)


def _subject_of(key: str, scope: Dict[str, Any]) -> str:
    """The claim's own base name, used to BIND evidence to THIS verdict.

    ``drc_status`` → ``drc``. A bare ``status`` inside a checklist entry takes
    its subject from the entry's own name/id/gate field, so per-gate rows in
    ``tapeout_gates[]`` each demand their own evidence rather than sharing one.
    """
    k = key.strip().lower()
    for suf in _VERDICT_KEY_SUFFIXES:
        if k.endswith(suf):
            base = k[: -len(suf)].strip("_")
            if base:
                return base
    if k in _VERDICT_KEY_EXACT and isinstance(scope, dict):
        for name_key in ("name", "id", "gate", "check", "gate_name", "label"):
            v = scope.get(name_key)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return k


# Containers that HOLD evidence rather than assert verdicts. Walking into
# them would let an evidence record's own "status"-ish key be misread as a
# claim, and would make the gate fail on its own proof.
_EVIDENCE_CONTAINER_KEYS = frozenset({
    "extraction_evidence", "evidence", "evidence_paths", "extraction_hints",
    "extraction_strategy",
})


def _collect_claims(node: Any,
                    out: List[Tuple[str, str, Any, Dict[str, Any]]],
                    path: str = "") -> None:
    """Walk the layer and collect every asserted verdict.

    Appends ``(json_path, subject, value, enclosing_dict)``.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            child_path = f"{path}.{k}" if path else str(k)
            if isinstance(k, str) and k.strip().lower() in \
                    _EVIDENCE_CONTAINER_KEYS:
                continue
            if _is_verdict_key(k):
                if not isinstance(v, (dict, list)):
                    if is_populated(v):
                        out.append(
                            (child_path, _subject_of(str(k), node), v, node))
                    continue
                if isinstance(v, dict):
                    # Nested verdict map: {"status": {"drc": "PASS", ...}}.
                    # Each sub-key names its own subject.
                    for sub_k, sub_v in v.items():
                        sub_path = f"{child_path}.{sub_k}"
                        if isinstance(sub_v, (dict, list)):
                            _collect_claims(sub_v, out, sub_path)
                        elif is_populated(sub_v):
                            out.append(
                                (sub_path, str(sub_k).strip().lower(), sub_v, v))
                    continue
            _collect_claims(v, out, child_path)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_claims(item, out, f"{path}[{i}]")


def _check_one(project: Path, layer_path: Path) -> Tuple[str, List[str]]:
    """Returns (verdict, messages) with verdict in {PASS, FAIL, SKIP}."""
    rel = layer_path.relative_to(project) if layer_path.is_relative_to(project) \
        else layer_path
    doc = load_json(layer_path)
    if not isinstance(doc, dict):
        return "SKIP", [f"{rel}: unreadable / non-object JSON"]

    applicability = str(doc.get("applicability", "") or "").strip().upper()
    if applicability in ("N/A", "NA", "NOT_APPLICABLE", "NOT APPLICABLE"):
        # An honest N/A stub must still say WHY — a silent-empty doc is
        # indistinguishable from a failed extraction.
        if is_no_information(doc.get("rationale")):
            return "FAIL", [
                f"{rel}: applicability=N/A with no `rationale` — a silent-empty "
                f"layer is indistinguishable from a failed extraction"]
        return "SKIP", [f"{rel}: N/A stub with rationale"]

    claims: List[Tuple[str, str, Any, Dict[str, Any]]] = []
    _collect_claims(doc, claims)
    if not claims:
        return "SKIP", [
            f"{rel}: layer asserts no sign-off verdict "
            f"(extraction_status={doc.get('extraction_status')!r}) — nothing "
            f"to certify, nothing to falsify"]

    msgs: List[str] = []
    failures: List[str] = []

    # Contradiction guard: a layer that says it extracted nothing cannot also
    # publish a certificate. This is the shape the motivating defect wore —
    # a verdict emitted by a track that contributed nothing.
    extraction_status = str(doc.get("extraction_status", "") or "").strip().upper()
    if extraction_status in ("NOT_YET_EXTRACTED", "NOT_EXTRACTED", "PENDING"):
        failures.append(
            f"{rel}: extraction_status={extraction_status} but the layer "
            f"asserts {len(claims)} sign-off verdict(s) "
            f"({', '.join(c[0] for c in claims[:4])}) — a layer that extracted "
            f"nothing cannot certify anything")

    for (json_path, subject, value, scope) in claims:
        v = verify_evidence_binding(project, doc, subject, scope)
        if v.ok:
            msgs.append(f"{rel}:{json_path}={value!r} — {v.detail}")
            continue
        if v.status == EvidenceVerdict.NO_EVIDENCE:
            why = (f"asserted verdict {value!r} with NO evidence path — this "
                   f"is the false-certificate shape")
        elif v.status == EvidenceVerdict.PATH_UNRESOLVED:
            why = v.detail
        elif v.status == EvidenceVerdict.NO_READBACK_VALUE:
            why = v.detail
        else:
            why = v.detail
        # Name the SUBJECT as well as the json path: on a checklist row the
        # path (`fields.tapeout_gates[3].status`) does not say which gate is
        # unevidenced, and an operator cannot act on an index.
        failures.append(f"{rel}:{json_path} (subject '{subject}') — {why}")

    if failures:
        return "FAIL", failures
    return "PASS", msgs


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: l24_signoff_evidence_backed_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"[SKIP] l24_signoff_evidence_backed_check: "
              f"{project} is not a directory")
        return 2

    layers = find_layer_files(project, _STEM)
    if not layers:
        print(f"[SKIP] l24_signoff_evidence_backed_check: no {_STEM}.json "
              f"under {project}")
        return 2

    all_fail: List[str] = []
    all_pass: List[str] = []
    n_skip = 0
    for layer in layers:
        verdict, msgs = _check_one(project, layer)
        if verdict == "FAIL":
            all_fail.extend(msgs)
        elif verdict == "PASS":
            all_pass.extend(msgs)
        else:
            n_skip += 1

    if all_fail:
        print(f"[FAIL] l24_signoff_evidence_backed_check: "
              f"{len(all_fail)} unevidenced sign-off assertion(s). A Phase-1 "
              f"sign-off verdict must be DERIVED from a report path + the "
              f"value read from it, never asserted.")
        for m in all_fail[:12]:
            print(f"  - {m}")
        if len(all_fail) > 12:
            print(f"  ... {len(all_fail) - 12} more")
        return 1

    if all_pass:
        print(f"[PASS] l24_signoff_evidence_backed_check: "
              f"{len(all_pass)} sign-off verdict(s) each trace to a resolvable "
              f"evidence path with a verified read-back value")
        for m in all_pass[:6]:
            print(f"  - {m}")
        return 0

    print(f"[SKIP] l24_signoff_evidence_backed_check: "
          f"{n_skip}/{len(layers)} {_STEM} layer(s) assert no sign-off verdict "
          f"(inert / N/A) — nothing to certify")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
