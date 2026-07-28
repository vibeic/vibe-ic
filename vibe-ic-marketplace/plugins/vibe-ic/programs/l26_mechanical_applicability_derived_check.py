#!/usr/bin/env python3
"""
l26_mechanical_applicability_derived_check.py — batch-8 / layergate-8
(L26_MECHANICAL_TRANSDUCTION)

WHAT THIS GATE ENFORCES
=======================
L26 models the MEMS / analog-physical dimension: movable-structure geometry
(membranes, cantilevers, springs), transduction principle, package/mechanical
stress.

The consumer contract, stated honestly:

    L26 HAS NO CONSUMER. l_doc_taxonomy declares it OPT-IN-ONLY
    (``_OPT_IN_ONLY_CODES``) for a dedicated MEMS class that does not exist
    yet, and ``is_applicable(cls, "L26")`` is False for EVERY registered class
    and for the unknown/fallback path. In 24/24 sampled real runs the layer
    correctly carries ``applicability="N/A"``.

A content gate here would fire on nothing, so this gate does not ask for
content. It enforces the one thing that IS load-bearing about a layer whose
entire output is a verdict about itself:

    THE APPLICABILITY VERDICT MUST BE DERIVED, NOT ASSERTED.

That is the same lesson as the motivating defect, applied to an N/A instead
of a CAPTURED. The 2026-07 route abort came from a completeness verdict that
was asserted from the wrong premise ("the token appears in SOME layer")
rather than derived from the consuming layer. An L26 that asserts
``applicability="N/A"`` from a stale or mismatched ic_class is the identical
shape: a "you don't need this" that nobody re-derived.

THE THREE RULES
---------------
  (R1) NON-STALE PREMISE. The ic_class L26 records must equal the ic_class the
       run actually detected (``reports/ic_class.json``, else the modal
       ic_class across the run's own sibling L-docs). A verdict computed
       against a different class than the run's is void — it may be a verdict
       about a different design entirely.

  (R2) DERIVED VERDICT. ``applicability`` must equal
       ``l_doc_taxonomy.is_applicable(run_ic_class, "L26")``.
         * taxonomy APPLICABLE + layer N/A  → FALSE N/A: the layer declares a
           dimension unnecessary that the run's own class declares necessary.
           This is the dangerous direction and the reason the gate blocks.
         * taxonomy NOT-applicable + layer APPLICABLE → an opt-in-only layer
           opted in for a class that does not want it, which is precisely the
           "empty L26 skeleton on a non-MEMS chip" that ``_OPT_IN_ONLY_CODES``
           exists to prevent.

  (R3) HONEST STUB / ACTIONABLE CONTENT. An N/A must carry a non-empty
       ``rationale`` (a silent-empty doc is indistinguishable from a failed
       extraction). An APPLICABLE L26 must not be inert: a MEMS consumer needs
       movable-structure geometry as numbers bound to units and a named
       transduction principle, not an empty skeleton.

Nothing here is hardcoded to a design, PDK, vendor or signal. The expected
verdict comes from the taxonomy the plugin already ships; the premise comes
from the run's own detected class. The gate reads ``reports/ic_class.json``
READ-ONLY and never calls ``detect_ic_class`` (which persists on inference) —
a gate must not mutate the run it audits.

BLOCKS OR ADVISES?
------------------
**BLOCKS** (exit 1 is a hard FAIL; it is NOT listed in
flow_compliance_check.INFORMATIONAL_GATES).

Why blocking is safe here in a way an interpretive gate would not be: every
rule is purely DERIVATIONAL — an equality against the shipped taxonomy and
against the run's own recorded class. There is no keyword scan, no free-text
interpretation, no threshold. It cannot fire on a legitimately-N/A design: on
all 24/24 sampled real runs the taxonomy verdict and the layer verdict agree,
so it SKIPs. The only way to fail it is to publish an applicability verdict
that the run's own inputs contradict — for which "advise" would repeat the
compounding failure where a gate said FAIL and the flow continued anyway.

NO WAIVER (governance-hard): a waiver would read "let this layer disagree
with the taxonomy it is derived from".

Usage:
    python3 l26_mechanical_applicability_derived_check.py <project_dir>

Exit codes:
    0 = PASS  — verdict derived, premise current, stub honest / content
                actionable
    1 = FAIL  — asserted or stale applicability verdict, silent stub, or an
                APPLICABLE-but-inert layer
    2 = SKIP  — no L26 present, or the run's ic_class cannot be established
                from the run's own artefacts (fail-open only on missing
                premise, never on a wrong one)
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l_doc_taxonomy as tx  # noqa: E402
from l_doc_evidence_util import (  # noqa: E402
    find_layer_files,
    generated_docs_roots,
    has_number_with_unit,
    is_no_information,
    is_populated,
    load_json,
)
# Imported, never re-typed — see _META_KEYS.
from l_doc_generator_stamp import STAMP_KEY as _GENERATOR_STAMP_KEY  # noqa: E402,E501

_STEM = "L26_MECHANICAL_TRANSDUCTION"
_CODE = "L26"

_NA_FORMS = ("N/A", "NA", "NOT_APPLICABLE", "NOT APPLICABLE")
_APPLICABLE_FORMS = ("APPLICABLE", "YES", "TRUE", "REQUIRED")

# `_generator` is on this list for the same reason `emitted_by` is: it
# describes the FILE (which plugin release wrote it), not the part. Without
# it an N/A stub — whose whole point is that it carries no content — would
# report one non-metadata key and stop looking empty.
_META_KEYS = frozenset({
    "doc_id", "doc_name", "applicability", "ic_class", "rationale",
    "extraction_hints", "extraction_status", "emitted_by",
    "extraction_evidence", "extraction_strategy", "schema_version",
    _GENERATOR_STAMP_KEY,
})

# What a MEMS consumer would need if the layer were ever applicable. Derived
# from the taxonomy's own description of L26 (movable structures /
# transduction principle / package-mechanical stress) — generic physical
# vocabulary, never a design or vendor token.
_GEOMETRY_NAME_TOKENS = ("geometry", "structure", "dimension", "membrane",
                         "cantilever", "spring", "gap", "thickness", "mass",
                         "beam", "proof")
_PRINCIPLE_NAME_TOKENS = ("transduction", "principle", "mechanism",
                          "actuation", "sensing")


def _run_ic_class(project: Path, layer_path: Path) -> Tuple[Optional[str], str]:
    """The ic_class this RUN actually detected, from the run's own artefacts.

    READ-ONLY. Never calls ``detect_ic_class`` — that function persists an
    inference to ``reports/ic_class.json``, and a gate must not mutate the run
    it audits. Returns ``(ic_class, provenance)``.
    """
    persisted = project / "reports" / "ic_class.json"
    if persisted.is_file():
        d = load_json(persisted)
        if isinstance(d, dict):
            c = d.get("ic_class")
            if isinstance(c, str) and c.strip():
                return c.strip(), "reports/ic_class.json"

    # Fall back to the modal ic_class across the run's own sibling L-docs.
    counter: Counter = Counter()
    for root in generated_docs_roots(project):
        for jf in sorted(root.glob("L*.json")):
            try:
                if jf.resolve() == layer_path.resolve():
                    continue
            except OSError:
                continue
            doc = load_json(jf)
            if isinstance(doc, dict):
                c = doc.get("ic_class")
                if isinstance(c, str) and c.strip():
                    counter[c.strip()] += 1
    if counter:
        top, n = counter.most_common(1)[0]
        return top, f"modal ic_class across {n} sibling L-doc(s)"
    return None, "unavailable"


def _check_one(project: Path, layer_path: Path) -> Tuple[str, List[str]]:
    rel = layer_path.relative_to(project) if layer_path.is_relative_to(project) \
        else layer_path
    doc = load_json(layer_path)
    if not isinstance(doc, dict):
        return "SKIP", [f"{rel}: unreadable / non-object JSON"]

    run_class, provenance = _run_ic_class(project, layer_path)
    if run_class is None:
        return "SKIP", [
            f"{rel}: the run records no ic_class anywhere "
            f"(no reports/ic_class.json, no sibling L-doc carries one) — the "
            f"premise for a derived applicability verdict is absent; SKIP "
            f"rather than guess"]

    failures: List[str] = []
    notes: List[str] = []

    # (R1) NON-STALE PREMISE
    layer_class = doc.get("ic_class")
    if isinstance(layer_class, str) and layer_class.strip():
        if layer_class.strip() != run_class:
            failures.append(
                f"{rel}: applicability verdict was computed against "
                f"ic_class={layer_class.strip()!r} but this run detected "
                f"ic_class={run_class!r} ({provenance}) — a verdict from a "
                f"stale premise is void")
    else:
        failures.append(
            f"{rel}: records no ic_class, so its applicability verdict cannot "
            f"be re-derived or audited — an unfalsifiable verdict")

    # (R2) DERIVED VERDICT
    try:
        expected_applicable = tx.is_applicable(run_class, _CODE)
    except KeyError:  # pragma: no cover - taxonomy always knows L26
        return "SKIP", [f"{rel}: taxonomy does not know {_CODE}"]

    raw = str(doc.get("applicability", "") or "").strip().upper()
    if raw in _NA_FORMS:
        layer_applicable = False
    elif raw in _APPLICABLE_FORMS:
        layer_applicable = True
    else:
        failures.append(
            f"{rel}: applicability={doc.get('applicability')!r} is neither an "
            f"N/A form nor an APPLICABLE form — an uninterpretable verdict "
            f"cannot be checked against the taxonomy")
        layer_applicable = None  # type: ignore[assignment]

    if layer_applicable is not None and layer_applicable != expected_applicable:
        if expected_applicable and not layer_applicable:
            failures.append(
                f"{rel}: FALSE N/A — l_doc_taxonomy.is_applicable("
                f"{run_class!r}, {_CODE!r}) is True for this run's own class, "
                f"but the layer asserts applicability=N/A. A 'you don't need "
                f"this' that nobody re-derived is how a consuming layer ends "
                f"up empty")
        else:
            failures.append(
                f"{rel}: APPLICABLE asserted while l_doc_taxonomy.is_applicable("
                f"{run_class!r}, {_CODE!r}) is False — {_CODE} is OPT-IN-ONLY "
                f"(_OPT_IN_ONLY_CODES) precisely so a non-MEMS chip never "
                f"carries an empty {_CODE} skeleton")
    elif layer_applicable is not None:
        notes.append(
            f"{rel}: applicability={raw} matches "
            f"is_applicable({run_class!r}, {_CODE!r})={expected_applicable} "
            f"({provenance})")

    # (R3) HONEST STUB / ACTIONABLE CONTENT
    if layer_applicable is False:
        if is_no_information(doc.get("rationale")):
            failures.append(
                f"{rel}: applicability=N/A with no `rationale` — a "
                f"silent-empty layer is indistinguishable from a failed "
                f"extraction")
    elif layer_applicable is True:
        fields = doc.get("fields")
        scope: Dict[str, Any] = fields if isinstance(fields, dict) else {
            k: v for k, v in doc.items() if k not in _META_KEYS}
        populated = {k: v for k, v in scope.items()
                     if k not in _META_KEYS and is_populated(v)}
        if not populated:
            failures.append(
                f"{rel}: applicability=APPLICABLE but every field is empty "
                f"(extraction_status={doc.get('extraction_status')!r}) — an "
                f"APPLICABLE-but-inert layer hands its consumer nothing, "
                f"which is the exact shape of the defect this batch exists "
                f"to prevent")
        else:
            geom = {k: v for k, v in populated.items()
                    if any(t in k.lower() for t in _GEOMETRY_NAME_TOKENS)}
            principle = {k: v for k, v in populated.items()
                         if any(t in k.lower()
                                for t in _PRINCIPLE_NAME_TOKENS)}
            if not geom:
                failures.append(
                    f"{rel}: APPLICABLE but declares no movable-structure "
                    f"geometry field — a MEMS consumer cannot size anything "
                    f"from {sorted(populated)}")
            else:
                unusable = [k for k, v in geom.items()
                            if not has_number_with_unit(v)]
                if unusable:
                    failures.append(
                        f"{rel}: geometry field(s) {sorted(unusable)} carry no "
                        f"number bound to a unit — narrative geometry is not "
                        f"actionable")
            if not principle:
                failures.append(
                    f"{rel}: APPLICABLE but names no transduction principle / "
                    f"mechanism — the layer's defining content is absent")

    if failures:
        return "FAIL", failures
    return "PASS", notes


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: l26_mechanical_applicability_derived_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"[SKIP] l26_mechanical_applicability_derived_check: "
              f"{project} is not a directory")
        return 2

    layers = find_layer_files(project, _STEM)
    if not layers:
        print(f"[SKIP] l26_mechanical_applicability_derived_check: no "
              f"{_STEM}.json under {project}")
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
        print(f"[FAIL] l26_mechanical_applicability_derived_check: "
              f"{len(all_fail)} applicability verdict problem(s). {_CODE}'s "
              f"applicability must be DERIVED from the run's own ic_class via "
              f"l_doc_taxonomy, never asserted.")
        for m in all_fail[:12]:
            print(f"  - {m}")
        if len(all_fail) > 12:
            print(f"  ... {len(all_fail) - 12} more")
        return 1

    if all_pass:
        print(f"[PASS] l26_mechanical_applicability_derived_check: "
              f"{len(all_pass)} {_STEM} layer(s) carry a verdict that "
              f"re-derives from this run's own ic_class")
        for m in all_pass[:6]:
            print(f"  - {m}")
        return 0

    print(f"[SKIP] l26_mechanical_applicability_derived_check: "
          f"{n_skip}/{len(layers)} {_STEM} layer(s) unauditable "
          f"(no ic_class premise recorded by the run)")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
