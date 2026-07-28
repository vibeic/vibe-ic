#!/usr/bin/env python3
"""
packaging_intake_check.py — gate (v1.6.13 Wave 88, renumbered
in v1.6.14 Wave 90: Step 37 -> 38; v1.6.15 Wave 91: Step 38 -> 39;
Step 42 in the phase1_phase2_phase3.yaml flow).

Step 42 — Packaging (assembly: wirebond / FC-CSP / WLCSP)

Two defects fixed here (both measured on v1.7.36)
--------------------------------------------------
1. WRONG SEARCH PATH (declaration / consumer drift).
   flow/phase1_phase2_phase3.yaml step 42 declares
   ``phase3/stage5_manufacturing/packaging_log.json``, and both sibling
   stage-5 checkers (``wafer_sort_yield_check``,
   ``final_test_attestation_check``) already read that prefix.  This gate
   searched a bare ``manufacturing/`` prefix that no producer in the repo
   has ever written.  Measured on a project laid out exactly the way the
   flow specifies, the gate returned ``verdict: SKIP`` rc=2 — which
   ``flow_compliance_check`` maps to VACUOUS_PASS and counts into
   ``pass_count`` (as it then computed it), while listing
   ``phase3/stage5_manufacturing/packaging_log.json`` in its own
   ``evidence[]``.  The gate could never return PASS on a compliant
   layout: it was unreachable code.  Canonical path is now searched
   first, with the legacy ``manufacturing/`` prefix kept as a fallback so
   no hand-built project layout regresses.
   (State AS MEASURED THEN.  ``flow_compliance_check`` has since
   dropped VACUOUS_PASS from the executed-PASS numerator: the tier
   leaves X and stays in Y, so the same skip no longer inflates the
   published number.  The defect this section records — the gate
   answering SKIP on a compliant layout — is unaffected.)

2. NO SUBSTANCE PREDICATE (rc=1 mechanically unreachable).
   The docstring promised ``FAIL (rc=1) — files present but predicate
   fails`` but every code path assigned rc 0 or 2.  Measured: a
   packaging log whose entire content was the token ``null`` produced
   ``verdict: PASS``, rc=0 — the packaging-assembly sign-off certified on
   a JSON null.  The gate now reads the assembly facts step 42 exists to
   record (package type + a unit/lot count > 0) and FAILs when the
   artefact cannot supply them.

Behaviour
---------
* SKIP   (rc=2) — required artefact absent AND step not waived; or the
                  project dir does not exist.  DELIBERATELY UNCHANGED:
                  pre-silicon runs must not start failing, and PR #455's
                  ALL-of-N ``required_outputs`` rule already downgrades
                  that tier to MISSING when the declared file really is
                  absent.
* WAIVED (rc=0) — ``waivers.json`` declares the step waived (evidence +
                  ticket), including the ticket-substring match.
                  UNCHANGED.  A waiver excuses an ABSENT artefact only;
                  it never excuses a present artefact that fails the
                  substance predicate.
* PASS   (rc=0) — artefact present, parseable, a non-empty JSON object,
                  naming a package type and a positive assembled-unit /
                  lot count.
* FAIL   (rc=1) — artefact present but unparseable / not a JSON object /
                  empty / null, or it names no package type, or it
                  records no unit count, or it records zero units
                  assembled (zero packaged parts cannot be signed off).

chip-AGNOSTIC.  No vendor / assembly-house / IC-specific data hard-coded —
only field-name synonym sets (the shape ``final_test_attestation_check``
already uses) and the predicate "the fact is present and the count is
positive".  Nested shapes (``{"package": {"type": "QFN-48"}}``) are
accepted as well as flat ones, because assembly-house logs differ.

Usage
-----
    python3 packaging_intake_check.py <project_dir> [--json <out>]
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


_GATE_NAME = 'packaging_intake_check'
_GATE_LABEL = 'packaging_intake'

# Canonical (flow-declared) location first, legacy fallback second — the
# same candidate-list shape wafer_sort_yield_check.py:66-73 already uses.
_PACKAGING_LOG_CANDIDATES = [
    'phase3/stage5_manufacturing/packaging_log.json',
    'manufacturing/packaging_log.json',
]
_REQUIRED_FILE_GROUPS = [
    ('packaging_log', _PACKAGING_LOG_CANDIDATES),
]
# Canonical names, reported in `required_files` and in `missing`.
_REQUIRED_FILES = [c[0] for _, c in _REQUIRED_FILE_GROUPS]
_WAIVER_RATIONALE = 'Packaging intake tracker not shipped.'

# ── field-name synonyms (chip-AGNOSTIC; first present wins) ──────────
_PACKAGE_TYPE_KEYS = (
    "package_type", "package", "pkg_type", "pkg", "packagetype",
    "assembly_type", "package_style", "package_name", "package_family",
    "body_type", "outline", "package_outline", "form_factor",
    "assembly_process", "bond_type",
)
# Numeric assembled-unit counts.
_UNIT_COUNT_KEYS = (
    "units", "unit_count", "units_assembled", "assembled_units",
    "packaged_units", "parts", "part_count", "parts_assembled",
    "quantity", "qty", "die_count", "dies", "count", "total_units",
    "n_units", "num_units", "lot_count", "lot_size",
)
# Containers whose length is itself the count: {"lots": [...]}.
_UNIT_LIST_KEYS = (
    "lots", "units", "assembly_lots", "packages", "parts", "records",
    "shipments", "trays", "reels",
)
# When a synonym key holds a container instead of a scalar, these generic
# leaf names are looked up inside it: {"package": {"type": "QFN-48"}}.
_GENERIC_LEAF_KEYS = (
    "id", "name", "type", "number", "no", "value", "version", "rev",
    "revision", "status", "state", "code", "label", "style",
)

_NORM_RE = re.compile(r"[^a-z0-9]+")
# Depth guard so a pathological artefact cannot spin this gate.
_MAX_DEPTH = 6


def _norm(key) -> str:
    return _NORM_RE.sub("_", str(key).lower()).strip("_")


def _scalar_fact(value):
    """Return `value` when it is a substantive scalar fact, else None.

    Booleans are rejected on purpose: a package type or a unit count is a
    name or a number, never a flag.
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
    shape ``{"package_type": "QFN-48"}`` and the nested shape
    ``{"package": {"type": "QFN-48"}}`` — assembly-house logs differ and
    this gate is chip-AGNOSTIC.
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


def _find_unit_count(doc):
    """Return (source_path, count) for the assembled-unit population.

    A numeric count under a count synonym wins; otherwise the length of a
    non-empty list under a unit/lot synonym is used.  Returns
    (None, None) when the artefact records no population at all.
    """
    k, v = _find_fact(doc, _UNIT_COUNT_KEYS)
    if v is not None:
        try:
            return k, float(v)
        except (TypeError, ValueError):
            pass
    for key, val in (doc.items() if isinstance(doc, dict) else []):
        if _norm(key) in _UNIT_LIST_KEYS and isinstance(val, list):
            return f"len({key})", float(len(val))
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
    """Parse the packaging log.  Appends a FAIL finding and returns None
    when the file is unparseable / not an object / empty / null."""
    try:
        raw = path.read_text()
    except Exception as exc:  # noqa: BLE001
        findings.append({"severity": "ERROR", "rule": "PACKAGING_LOG_UNREADABLE",
                         "message": f"{rel}: {exc}"})
        return None
    if not raw.strip():
        findings.append({"severity": "ERROR", "rule": "PACKAGING_LOG_EMPTY",
                         "message": f"{rel} is empty (0 bytes of content) — "
                                    f"an empty file attests to nothing"})
        return None
    try:
        doc = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        findings.append({"severity": "ERROR", "rule": "PACKAGING_LOG_UNPARSEABLE",
                         "message": f"{rel}: {exc}"})
        return None
    if not isinstance(doc, dict):
        findings.append({"severity": "ERROR", "rule": "PACKAGING_LOG_NOT_OBJECT",
                         "message": f"{rel} top-level JSON is "
                                    f"{type(doc).__name__}, not an object"})
        return None
    if not doc:
        findings.append({"severity": "ERROR", "rule": "PACKAGING_LOG_EMPTY",
                         "message": f"{rel} is an empty JSON object — "
                                    f"an empty object attests to nothing"})
        return None
    return doc


def _verify_substance(resolved):
    """Independently verify that the packaging log carries the assembly
    facts step 42 exists to record: a package type and a positive
    assembled-unit / lot population.

    `resolved` maps group name -> (matched_pattern, Path).
    Returns (verdict, rc, findings, parsed).
    """
    findings = []
    parsed = {}
    ok = True

    rel, path = resolved["packaging_log"]
    doc = _read_doc(rel, path, findings)
    if doc is None:
        return "FAIL", 1, findings, parsed

    pk, pv = _find_fact(doc, _PACKAGE_TYPE_KEYS)
    parsed["package_type_key"] = pk
    parsed["package_type"] = pv
    if pv is None:
        ok = False
        findings.append({
            "severity": "ERROR", "rule": "PACKAGE_TYPE_MISSING",
            "message": "packaging log names no package type "
                       "(package_type / package / assembly_type / ...); "
                       "step 42 exists to record the assembly performed",
        })
    else:
        findings.append({"severity": "INFO", "rule": "PACKAGE_TYPE_PRESENT",
                         "message": f"package type: {pk}={pv}"})

    ck, cv = _find_unit_count(doc)
    parsed["unit_count_key"] = ck
    parsed["unit_count"] = cv
    if cv is None:
        ok = False
        findings.append({
            "severity": "ERROR", "rule": "UNIT_COUNT_MISSING",
            "message": "packaging log records no assembled-unit / lot "
                       "population (units / quantity / lots / ...); "
                       "cannot attest that anything was assembled",
        })
    elif cv <= 0:
        ok = False
        findings.append({
            "severity": "ERROR", "rule": "ZERO_UNITS_PACKAGED",
            "message": f"packaging log records {ck}={cv:g} assembled units; "
                       f"zero packaged parts cannot be signed off",
        })
    else:
        findings.append({"severity": "INFO", "rule": "UNIT_COUNT_PRESENT",
                         "message": f"assembled units: {ck}={cv:g}"})

    if ok:
        findings.append({
            "severity": "INFO", "rule": "PACKAGING_SUBSTANCE_VERIFIED",
            "message": "packaging log attests package type and a positive "
                       "assembled-unit population",
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
