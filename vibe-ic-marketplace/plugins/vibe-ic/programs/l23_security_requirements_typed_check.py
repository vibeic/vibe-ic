#!/usr/bin/env python3
"""
l23_security_requirements_typed_check.py — SEMANTIC gate for
L23_SECURITY_REQUIREMENTS (batch layergate-7).

HONEST FRAMING FIRST
====================
L23 has NO consumer anywhere in the plugin. Verified: only
``programs/l_doc_taxonomy.py``, ``programs/phase1_doc_one_shot_runner.py``
and ``tools/phase1_engine/schema.py`` reference it, and none of them
reads its content. ``NOT_YET_EXTRACTED`` in 24/24 sampled runs.

With no consumer there is no actionable contract to enforce, and a gate
that blocks a flow over a layer nothing reads is ceremony, not
engineering. So this gate is deliberately asymmetric:

  F1 VACUOUS_SECURITY_ASSERTION ........................... BLOCKS
      L23 asserts security posture — ``security_requirements_present:
      true``, or ``secure_boot: true``, or a non-empty ``key_handling``
      — while carrying zero typed records with evidence. This is a
      SELF-contradiction inside the layer: a claim the layer itself
      cannot back. It needs no consumer to be wrong. A false "secure
      boot is required and handled" is worse than silence, because a
      reader downstream (human or program) takes it as fact. This half
      BLOCKS. It fires on ZERO real runs today, because every real run
      honestly says false.

  F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER .................. ADVISES
      The design's OWN inputs declare security-relevant assets — its
      input docs state a security requirement with requirement framing,
      or a sibling L-doc declares one (an L4 register or an L11 OTP
      record whose OWN declared semantics say key / lock / secure /
      tamper) — while L23 says ``security_requirements_present: false``
      with empty typed records. This is the L21 shape. It ADVISES
      rather than BLOCKS purely because no consumer exists: there is no
      downstream step whose contract is violated, so there is nothing
      to protect by stopping. Promote to BLOCKS the moment any step
      consumes L23.

      Note this is derived from the sibling doc's OWN declared field
      semantics — a register whose declared name/description says
      "key" or "lock" — never from a design name or a specific
      chip's register literal.

SINGLE DETERMINISTIC TRACK
==========================
No AI second track — see l_doc_consumer_contract.py.

Usage:
    python3 l23_security_requirements_typed_check.py <project_dir> [--json PATH]

Exit codes:
    0 = PASS (or ADVISE-only findings)
    1 = FAIL (F1) — BLOCKS
    2 = SKIP (no L23, L23 not applicable to this IC class, or the
        design declares no security-relevant asset and L23 asserts none)

Honors waiver ``l23_security_scope_deferred_to_system_integrator``
(>=40 chars).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l_doc_consumer_contract import (  # noqa: E402
    applicability_of,
    framed_hits,
    input_doc_texts,
    is_extraction_claimed,
    l_doc_fields,
    load_l_doc,
    nonempty_str,
    sibling_l_doc_texts,
    waiver_rationale,
    write_report,
)

GATE = "l23_security_requirements_typed_check"
WAIVER_ID = "l23_security_scope_deferred_to_system_integrator"

# Security technology vocabulary. Requirement framing is applied on top
# by framed_hits(), so a passing mention ("detect tampering / attack")
# in a pin-description table does NOT trigger on its own.
_SECURITY_VOCAB_RE = re.compile(
    r"\b(?:secure[ _-]?boot|root[ _-]?of[ _-]?trust|chain[ _-]?of[ _-]?trust|"
    r"side[ _-]?channel|differential\s+power\s+analysis|\bdpa\b|"
    r"fault[ _-]?injection|glitch\s+attack|"
    r"attack[ _-]?surface|threat[ _-]?model|"
    r"key[ _-]?(?:storage|handling|management|derivation|provisioning)|"
    r"private\s+key|secret\s+key|key\s+material|"
    r"anti[- ]?tamper|tamper[ _-]?(?:detect|resist|proof|evident)|"
    r"attestation|secure\s+debug|debug\s+lock|lifecycle\s+state|"
    r"\btrng\b|true\s+random\s+number|crypto\s+(?:engine|accelerator|core))\b",
    re.IGNORECASE,
)

# Sibling layers whose OWN declared semantics can carry a security asset.
_SIBLING_CODES = ("L4", "L11", "L7", "L2", "L24")

_KEY_KEYS = ("key_handling", "keys", "key_management")
_SURFACE_KEYS = ("attack_surface", "threat_model", "threats")
_SIDE_CHANNEL_KEYS = ("side_channel_mitigation", "side_channel",
                      "countermeasures")
_BOOT_KEYS = ("secure_boot", "secure_boot_required", "boot_security")
_PRESENT_KEYS = ("security_requirements_present", "security_present",
                 "security_required")

_RECORD_TEXT_KEYS = ("name", "id", "requirement", "description", "text",
                     "statement", "asset", "vector", "mitigation")
_EVIDENCE_KEYS = ("evidence", "source", "citation", "ref", "reference",
                  "doc_ref", "provenance")


def _get(fields: dict, keys) -> Any:
    for k in keys:
        if k in fields:
            return fields[k]
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _truthy_assertion(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, str):
        t = value.strip().lower()
        if not t:
            return False
        for neg in ("n/a", "na", "none", "not ", "no ", "absent", "false",
                    "unknown", "tbd", "deferred"):
            if t.startswith(neg):
                return False
        return True
    return value is not None and value is not False


def _record_missing_fields(entry: Any) -> List[str]:
    """A typed security record needs a statement AND evidence.

    'with evidence' is the whole point: an unsourced security claim is
    the same class of artifact as an unfalsifiable coverage goal.
    """
    if isinstance(entry, str):
        return [] if len(entry.strip()) >= 12 else ["statement"]
    if not isinstance(entry, dict):
        return ["statement", "evidence"]
    missing: List[str] = []
    if not any(nonempty_str(entry.get(k), 3) for k in _RECORD_TEXT_KEYS):
        missing.append("statement")
    if not any(nonempty_str(entry.get(k), 3) for k in _EVIDENCE_KEYS):
        missing.append("evidence")
    return missing


def _typed_record_count(fields: dict) -> int:
    total = 0
    for keys in (_KEY_KEYS, _SURFACE_KEYS, _SIDE_CHANNEL_KEYS):
        for rec in _as_list(_get(fields, keys)):
            if not _record_missing_fields(rec):
                total += 1
    return total


def _all_records(fields: dict) -> List[Any]:
    out: List[Any] = []
    for keys in (_KEY_KEYS, _SURFACE_KEYS, _SIDE_CHANNEL_KEYS):
        out.extend(_as_list(_get(fields, keys)))
    return out


def inspect(project: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "gate": GATE,
        "project": str(project),
        "verdict": "SKIP",
        "blocking_findings": [],
        "advisory_findings": [],
        "evidence": {},
    }

    l23_path, l23 = load_l_doc(project, "L23")
    if l23_path is None:
        result["reason"] = "no L23 doc in phase1/generated_docs"
        return result
    result["evidence"]["l23_path"] = str(l23_path)

    if l23 is None:
        result["verdict"] = "FAIL"
        result["blocking_findings"].append({
            "id": "UNPARSEABLE_LAYER",
            "detail": f"{l23_path} is not parseable JSON.",
        })
        return result

    applicability = applicability_of(l23)
    result["evidence"]["applicability"] = applicability
    if applicability in ("NOT_APPLICABLE", "N/A", "NA"):
        result["reason"] = (f"L23 applicability={applicability} for "
                            f"ic_class={l23.get('ic_class')}")
        return result

    fields = l_doc_fields(l23)
    present = _get(fields, _PRESENT_KEYS)
    boot = _get(fields, _BOOT_KEYS)
    records = _all_records(fields)
    typed = _typed_record_count(fields)

    result["evidence"]["security_record_count"] = len(records)
    result["evidence"]["typed_record_count"] = typed
    result["evidence"]["security_requirements_present"] = present
    result["evidence"]["secure_boot"] = boot

    # ── F1 VACUOUS_SECURITY_ASSERTION (BLOCKS) ───────────────────────
    asserts_security = (_truthy_assertion(present)
                        or _truthy_assertion(boot)
                        or bool(records)
                        or is_extraction_claimed(l23))
    result["evidence"]["asserts_security"] = asserts_security

    if asserts_security and typed == 0:
        result["blocking_findings"].append({
            "id": "VACUOUS_SECURITY_ASSERTION",
            "detail": (
                f"L23 asserts a security posture "
                f"(security_requirements_present={present!r}, "
                f"secure_boot={boot!r}, {len(records)} record(s), "
                f"extraction_claimed={is_extraction_claimed(l23)}) but "
                f"carries 0 typed records with evidence. key_handling / "
                f"attack_surface / side_channel_mitigation entries must "
                f"each carry a statement AND a source citation. An "
                f"unsourced security claim is read downstream as fact "
                f"and can be refuted by nothing."),
        })
    elif records:
        bad = []
        for i, r in enumerate(records):
            miss = _record_missing_fields(r)
            if miss:
                bad.append(f"record[{i}]: missing {','.join(miss)}")
        if bad:
            result["blocking_findings"].append({
                "id": "VACUOUS_SECURITY_ASSERTION",
                "detail": (
                    f"{len(bad)}/{len(records)} L23 security records lack "
                    f"a statement and/or evidence. "
                    f"Examples: {'; '.join(bad[:5])}"),
            })

    # ── F2 REQUIREMENT_OUTSIDE_CONSUMING_LAYER (ADVISES) ─────────────
    doc_hits = framed_hits(input_doc_texts(project), _SECURITY_VOCAB_RE)
    sib_hits = framed_hits(sibling_l_doc_texts(project, _SIBLING_CODES),
                           _SECURITY_VOCAB_RE)
    result["evidence"]["security_requirement_hits_input_docs"] = len(doc_hits)
    result["evidence"]["security_requirement_hits_sibling_l_docs"] = \
        len(sib_hits)

    if (doc_hits or sib_hits) and typed == 0:
        result["advisory_findings"].append({
            "id": "REQUIREMENT_OUTSIDE_CONSUMING_LAYER",
            "severity": "ADVISE",
            "detail": (
                f"The design's own inputs declare a security requirement "
                f"in {len(doc_hits)} input-doc location(s) and "
                f"{len(sib_hits)} sibling-L-doc location(s), but L23 "
                f"carries 0 typed records "
                f"(security_requirements_present={present!r}). The L21 "
                f"shape: present somewhere, absent from the layer that "
                f"would consume it. ADVISE not BLOCK because L23 has NO "
                f"consumer anywhere in the plugin — there is no "
                f"downstream contract to protect. Promote to BLOCKS the "
                f"moment any step reads L23."),
            "evidence": (doc_hits + sib_hits)[:4],
        })

    if result["blocking_findings"]:
        result["verdict"] = "FAIL"
    elif result["advisory_findings"]:
        result["verdict"] = "PASS_WITH_ADVISORY"
    elif typed:
        result["verdict"] = "PASS"
    else:
        result["verdict"] = "SKIP"
        result["reason"] = ("design declares no security-relevant asset "
                            "and L23 asserts none")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[1]
                                 if __doc__ else "")
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None, metavar="PATH")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE}: {project} is not a directory")
        return 2

    result = inspect(project)

    waiver = waiver_rationale(project, WAIVER_ID)
    if waiver and result["verdict"] == "FAIL":
        result["verdict"] = "WAIVED"
        result["waiver"] = waiver

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2,
                                              ensure_ascii=False))
    write_report(project, GATE, result)

    for f in result["advisory_findings"]:
        print(f"[ADVISE] {GATE}: {f['id']} — {f['detail']}")

    verdict = result["verdict"]
    if verdict == "SKIP":
        print(f"[SKIP] {GATE}: {result.get('reason', 'not applicable')}")
        return 2
    if verdict == "WAIVED":
        print(f"[SKIP] {GATE}: waived via {WAIVER_ID} — {result['waiver'][:90]}")
        return 2
    if verdict == "FAIL":
        for f in result["blocking_findings"]:
            print(f"[FAIL] {GATE}: {f['id']} — {f['detail']}")
        return 1
    print(f"[PASS] {GATE}: {result['evidence'].get('typed_record_count', 0)} "
          f"typed security record(s) with evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
