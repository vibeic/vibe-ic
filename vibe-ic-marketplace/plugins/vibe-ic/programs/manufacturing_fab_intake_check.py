#!/usr/bin/env python3
"""
manufacturing_fab_intake_check.py — gate (v1.6.13 Wave 88, renumbered
in v1.6.14 Wave 90: Step 35 -> 36; v1.6.15 Wave 91: Step 36 -> 37;
Step 40 in the phase1_phase2_phase3.yaml flow).

Step 40 — Fabrication (foundry mask-set + wafer fab — external)

Two defects fixed here (both measured on v1.7.36)
--------------------------------------------------
1. WRONG SEARCH PATH (declaration / consumer drift).
   flow/phase1_phase2_phase3.yaml step 40 declares the intake artefacts
   under ``phase3/stage5_manufacturing/``, and both sibling stage-5
   checkers (``wafer_sort_yield_check``, ``final_test_attestation_check``)
   already read that prefix.  This gate searched a bare ``manufacturing/``
   prefix that no producer in the repo has ever written.  Measured on a
   project laid out exactly the way the flow specifies, the gate returned
   ``verdict: SKIP`` rc=2 — which ``flow_compliance_check`` maps to
   VACUOUS_PASS and counts into ``pass_count`` (as it then computed
   it), while listing the very files it
   claimed were "not applicable" in its own ``evidence[]``.  Complete,
   correct fab-intake data was scored as a pass on the grounds that it
   did not exist.  Canonical path is now searched first, with the legacy
   ``manufacturing/`` prefix kept as a fallback so no hand-built project
   layout regresses.
   (State AS MEASURED THEN.  ``flow_compliance_check`` has since
   dropped VACUOUS_PASS from the executed-PASS numerator: the tier
   leaves X and stays in Y, so the same skip no longer inflates the
   published number.  The defect this section records — the gate
   answering SKIP on a compliant layout — is unaffected.)

2. NO SUBSTANCE PREDICATE (rc=1 mechanically unreachable).
   The docstring promised ``FAIL (rc=1) — files present but predicate
   fails`` but every code path assigned rc 0 or 2.  Measured: an intake
   file whose entire content was the text ``not json at all -- garbage``
   plus a 0-byte second file produced ``verdict: PASS``, rc=0.  The
   step's own flow notes say it "records lot id, mask set version, and
   foundry status"; the gate now reads those facts and FAILs when the
   artefact cannot supply them.

Behaviour
---------
* SKIP   (rc=2) — required artefacts absent AND step not waived; or the
                  project dir does not exist.  DELIBERATELY UNCHANGED:
                  pre-silicon runs must not start failing, and PR #455's
                  ALL-of-N ``required_outputs`` rule already downgrades
                  that tier to MISSING when the declared files really are
                  absent.
* WAIVED (rc=0) — ``waivers.json`` declares the step waived (evidence +
                  ticket), including the ticket-substring match.
                  UNCHANGED.  A waiver excuses an ABSENT artefact only;
                  it never excuses a present artefact that fails the
                  substance predicate.
* PASS   (rc=0) — every required artefact present, parseable, a non-empty
                  JSON object, and carrying the identifying facts the
                  step exists to record.
* FAIL   (rc=1) — an artefact is present but unparseable / not a JSON
                  object / empty, or the intake data carries no mask-set
                  identity, no wafer-lot identity, or no foundry-fab
                  status.

chip-AGNOSTIC.  No vendor / IC / tool-specific data hard-coded — only
field-name synonym sets (the shape ``final_test_attestation_check`` already
uses) and the predicate "the fact is present and non-empty".  Nested
shapes (``{"lot": {"id": "L-9"}}``) are accepted as well as flat ones,
because foundry intake trackers differ.

Usage
-----
    python3 manufacturing_fab_intake_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text()).get("waived_steps") or [])
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


_GATE_NAME = 'manufacturing_fab_intake_check'
_GATE_LABEL = 'manufacturing_fab_intake'

# Canonical (flow-declared) location first, legacy fallback second — the
# same candidate-list shape wafer_sort_yield_check.py:66-73 already uses.
_MASK_SET_CANDIDATES = [
    'phase3/stage5_manufacturing/mask_set_received.json',
    'manufacturing/mask_set_received.json',
]
_WAFER_LOT_CANDIDATES = [
    'phase3/stage5_manufacturing/wafer_lot_received.json',
    'manufacturing/wafer_lot_received.json',
]
_REQUIRED_FILE_GROUPS = [
    ('mask_set_received', _MASK_SET_CANDIDATES),
    ('wafer_lot_received', _WAFER_LOT_CANDIDATES),
]
# Canonical names, reported in `required_files` and in `missing`.
_REQUIRED_FILES = [c[0] for _, c in _REQUIRED_FILE_GROUPS]
_WAIVER_RATIONALE = 'Manufacturing intake tracker not shipped.'

# ── field-name synonyms (chip-AGNOSTIC; first present wins) ──────────
_MASK_SET_ID_KEYS = (
    "mask_set_id", "maskset_id", "mask_set", "maskset", "mask_id",
    "mask_set_name", "mask_set_version", "maskset_version", "mask_version",
    "mask_set_rev", "mask_rev", "mask_revision", "reticle_id",
    "reticle_set", "reticle", "tapeout_id", "tapeout", "gds_revision",
)
_LOT_ID_KEYS = (
    "lot_id", "lot", "lot_number", "lot_no", "lotid", "wafer_lot",
    "wafer_lot_id", "waferlot", "batch_id", "batch", "batch_no",
    "run_id", "run_number", "lot_name",
)
_FOUNDRY_STATUS_KEYS = (
    "foundry", "fab", "foundry_name", "fab_name", "foundry_status",
    "fab_status", "status", "lot_status", "wafer_status", "state",
    "shipment_status", "delivery_status", "foundry_state", "stage",
)
# When a synonym key holds a container instead of a scalar, these generic
# leaf names are looked up inside it: {"lot": {"id": "L-9"}}.
_GENERIC_LEAF_KEYS = (
    "id", "name", "number", "no", "value", "version", "rev", "revision",
    "status", "state", "code", "label",
)

_NORM_RE = re.compile(r"[^a-z0-9]+")
# Depth guard so a pathological artefact cannot spin this gate.
_MAX_DEPTH = 6


def _norm(key) -> str:
    return _NORM_RE.sub("_", str(key).lower()).strip("_")


def _scalar_fact(value):
    """Return `value` when it is a substantive scalar fact, else None.

    Booleans are rejected on purpose: an identifier or a status is a name
    or a number, never a flag.  ``{"received": true}`` must not read as
    "this artefact identifies a wafer lot".
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def _leaf_in_container(node, path, depth=0):
    """Find a generic identity leaf inside a container held by a synonym key."""
    if depth > _MAX_DEPTH:
        return None, None
    if isinstance(node, dict):
        for k, v in node.items():
            if _norm(k) in _GENERIC_LEAF_KEYS:
                fact = _scalar_fact(v)
                if fact is not None:
                    return f"{path}.{k}", fact
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                p, f = _leaf_in_container(v, f"{path}.{k}", depth + 1)
                if f is not None:
                    return p, f
    elif isinstance(node, list):
        for i, v in enumerate(node):
            fact = _scalar_fact(v)
            if fact is not None:
                return f"{path}[{i}]", fact
            if isinstance(v, (dict, list)):
                p, f = _leaf_in_container(v, f"{path}[{i}]", depth + 1)
                if f is not None:
                    return p, f
    return None, None


def _find_fact(node, keys, path="", depth=0):
    """Depth-first search for the first substantive fact under `keys`.

    Returns (dotted_path, value) or (None, None).  Accepts both the flat
    shape ``{"lot_id": "L-9"}`` and the nested shape
    ``{"lot": {"id": "L-9"}}`` — foundry intake trackers differ and this
    gate is chip-AGNOSTIC.
    """
    if depth > _MAX_DEPTH:
        return None, None
    if isinstance(node, dict):
        for k, v in node.items():
            if _norm(k) in keys:
                fact = _scalar_fact(v)
                if fact is not None:
                    return (f"{path}.{k}".lstrip("."), fact)
                if isinstance(v, (dict, list)):
                    p, f = _leaf_in_container(v, f"{path}.{k}".lstrip("."),
                                              depth + 1)
                    if f is not None:
                        return p, f
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                p, f = _find_fact(v, keys, f"{path}.{k}".lstrip("."), depth + 1)
                if f is not None:
                    return p, f
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, (dict, list)):
                p, f = _find_fact(v, keys, f"{path}[{i}]", depth + 1)
                if f is not None:
                    return p, f
    return None, None


def _resolve(project: Path, candidates):
    """First candidate pattern with at least one file match.

    Glob semantics preserved — the declared patterns may contain
    wildcards.  Returns (matched_pattern, path) or (None, None).
    """
    for pat in candidates:
        hits = sorted(p for p in project.glob(pat) if p.is_file())
        if hits:
            return pat, hits[0]
    return None, None


def _read_doc(rel, path, findings):
    """Parse one intake artefact.  Appends a FAIL finding and returns None
    when the file is unparseable / not an object / empty."""
    try:
        raw = path.read_text()
    except Exception as exc:  # noqa: BLE001
        findings.append({"severity": "ERROR", "rule": "INTAKE_JSON_UNREADABLE",
                         "message": f"{rel}: {exc}"})
        return None
    if not raw.strip():
        findings.append({"severity": "ERROR", "rule": "INTAKE_JSON_EMPTY",
                         "message": f"{rel} is empty (0 bytes of content) — "
                                    f"an empty file attests to nothing"})
        return None
    try:
        doc = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        findings.append({"severity": "ERROR", "rule": "INTAKE_JSON_UNPARSEABLE",
                         "message": f"{rel}: {exc}"})
        return None
    if not isinstance(doc, dict):
        findings.append({"severity": "ERROR", "rule": "INTAKE_JSON_NOT_OBJECT",
                         "message": f"{rel} top-level JSON is "
                                    f"{type(doc).__name__}, not an object"})
        return None
    if not doc:
        findings.append({"severity": "ERROR", "rule": "INTAKE_JSON_EMPTY",
                         "message": f"{rel} is an empty JSON object — "
                                    f"an empty object attests to nothing"})
        return None
    return doc


def _verify_substance(resolved):
    """Independently verify that the intake artefacts carry the facts
    step 40 exists to record: a mask-set identity, a wafer-lot identity,
    and a foundry / fab status.

    `resolved` maps group name -> (matched_pattern, Path).
    Returns (verdict, rc, findings, parsed).
    """
    findings = []
    parsed = {}
    ok = True

    docs = {}
    for group, (rel, path) in resolved.items():
        doc = _read_doc(rel, path, findings)
        if doc is None:
            ok = False
        docs[group] = doc

    mask_doc = docs.get("mask_set_received")
    lot_doc = docs.get("wafer_lot_received")

    if mask_doc is not None:
        mk, mv = _find_fact(mask_doc, _MASK_SET_ID_KEYS)
        parsed["mask_set_id_key"] = mk
        parsed["mask_set_id"] = mv
        if mv is None:
            ok = False
            findings.append({
                "severity": "ERROR", "rule": "MASK_SET_IDENTITY_MISSING",
                "message": "mask-set intake artefact names no mask set "
                           "(mask_set_id / reticle_id / mask_set_version / "
                           "...); step 40 exists to record it",
            })
        else:
            findings.append({"severity": "INFO", "rule": "MASK_SET_IDENTIFIED",
                             "message": f"mask set: {mk}={mv}"})

    if lot_doc is not None:
        lk, lv = _find_fact(lot_doc, _LOT_ID_KEYS)
        parsed["lot_id_key"] = lk
        parsed["lot_id"] = lv
        if lv is None:
            ok = False
            findings.append({
                "severity": "ERROR", "rule": "WAFER_LOT_IDENTITY_MISSING",
                "message": "wafer-lot intake artefact names no lot "
                           "(lot_id / wafer_lot / batch_id / ...); step 40 "
                           "exists to record it",
            })
        else:
            findings.append({"severity": "INFO", "rule": "WAFER_LOT_IDENTIFIED",
                             "message": f"wafer lot: {lk}={lv}"})

    # Foundry / fab status may live in either artefact — trackers differ.
    fk = fv = None
    for group in ("wafer_lot_received", "mask_set_received"):
        doc = docs.get(group)
        if doc is None:
            continue
        k, v = _find_fact(doc, _FOUNDRY_STATUS_KEYS)
        if v is not None:
            fk, fv = f"{group}:{k}", v
            break
    parsed["foundry_status_key"] = fk
    parsed["foundry_status"] = fv
    if any(d is not None for d in docs.values()) and fv is None:
        ok = False
        findings.append({
            "severity": "ERROR", "rule": "FOUNDRY_STATUS_MISSING",
            "message": "neither intake artefact records a foundry / fab "
                       "status (foundry / fab / foundry_status / status / "
                       "...); step 40 exists to record it",
        })
    elif fv is not None:
        findings.append({"severity": "INFO", "rule": "FOUNDRY_STATUS_PRESENT",
                         "message": f"foundry status: {fk}={fv}"})

    if ok:
        findings.append({
            "severity": "INFO", "rule": "INTAKE_SUBSTANCE_VERIFIED",
            "message": "fab intake attests mask-set identity, wafer-lot "
                       "identity and foundry status",
        })
        return "PASS", 0, findings, parsed
    return "FAIL", 1, findings, parsed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    resolved = {}
    found = []
    missing = []
    for group, candidates in _REQUIRED_FILE_GROUPS:
        rel, path = _resolve(project, candidates)
        if path is None:
            missing.append(candidates[0])
        else:
            found.append(rel)
            resolved[group] = (rel, path)

    waiver = _step_waived(project, args.step_label)
    parsed = {}
    if missing and not waiver:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                      "message": f"missing: {missing}"}]
    elif missing and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    else:
        verdict, rc, findings, parsed = _verify_substance(resolved)

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": _REQUIRED_FILES,
        "required_file_candidates": {g: c for g, c in _REQUIRED_FILE_GROUPS},
        "found": found,
        "missing": missing,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "parsed": parsed,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    for f in findings:
        if f.get("severity") in ("ERROR", "WARN"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
