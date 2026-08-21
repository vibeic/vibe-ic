#!/usr/bin/env python3
"""
l25_reliability_envelope_actionable_check.py — batch-8 / layergate-8
(L25_RELIABILITY_MISSION_PROFILE)

WHAT THIS GATE ENFORCES
=======================
L25 models the qualification / mission-profile envelope: temperature and
lifetime bounds, qual standard, EM budget, NBTI/HCI aging margins.

The consumer contract, stated honestly:

    L25 HAS NO CONSUMER ANYWHERE IN THE PLUGIN TODAY. Nothing derates STA or
    IR-drop by an aging margin; nothing widens a corner set from a mission
    profile. In 24/24 sampled real Phase-1 runs the layer is inert
    (extraction_status=NOT_YET_EXTRACTED, every field null).

So this gate does NOT demand that L25 be populated. It enforces the two
properties that decide whether the layer would be USABLE the day EM/aging
derating is wired into STA or IR-drop:

  (1) ACTIONABLE, not narrative. A margin a consumer can apply is a NUMBER
      BOUND TO A UNIT. ``aging_margin: "significant"`` and ``em_budget: 10``
      are both unusable — the first has no number, the second no unit. A
      temperature/lifetime envelope needs TWO bounds, not one.
      This is the same principle as the motivating defect: a requirement is
      captured only when it lands in the consuming layer IN AN ACTIONABLE
      FORM. The 2026-07 route abort happened because a supply pin was
      "present" as prose in L1/L2 while L21 — the layer the backend consumes —
      had it 0 times.

  (2) TRACEABLE, not invented. Every populated field must bind to an evidence
      record naming a source file inside the project and the literal that was
      read from it, and that literal must still be findable there. An
      un-sourced qual standard or temperature range is a hallucination risk
      with a units-and-standards vocabulary that reads authoritative.

  (3) CONSISTENT with the design's OWN declared operating envelope. If this
      design's other L-docs declare operating temperatures in explicit
      Celsius, an L25 mission profile that does NOT cover them is a
      certificate for a chip other than this one. Derived entirely from the
      design's own inputs — no design/PDK/vendor token is hardcoded, and the
      cross-check is skipped unless the design itself supplies both sides.

BLOCKS OR ADVISES?
------------------
**ADVISES** (it is registered in flow_compliance_check.INFORMATIONAL_GATES,
so a FAIL is reported per-step but excluded from the strict-structural FAIL
count).

Why advisory and not blocking — and exactly when that flips:
  * There is genuinely NO consumer. Nothing downstream is wrong today as a
    consequence of a bad L25, so blocking a tapeout flow on it would be a
    gate asserting an authority it does not have.
  * The actionability rules necessarily interpret free text (is "10 %/khr" a
    margin?), so unlike the L24 and L26 gates in this batch they are not
    purely derivational. An interpretive rule with no consumer should advise.
  * PROMOTION TRIGGER, stated so it is not forgotten: the moment any program
    reads L25 to derate STA/IR-drop or to widen a corner set, delete
    "l25_reliability_envelope_actionable_check" from INFORMATIONAL_GATES. At
    that point an unusable L25 silently produces optimistic timing, and
    advisory becomes the same "FAIL and the flow continued anyway" mistake
    that compounded the motivating defect.

Usage:
    python3 l25_reliability_envelope_actionable_check.py <project_dir>

Exit codes:
    0 = PASS  — every populated reliability field is actionable + traceable
    1 = FAIL  — a populated field is unusable or untraceable (ADVISORY)
    2 = SKIP  — no L25, N/A stub, or the layer is inert (today's real-run
                state)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from l_doc_evidence_util import (  # noqa: E402
    EvidenceVerdict,
    extract_numbers,
    find_layer_files,
    generated_docs_roots,
    has_number_with_unit,
    is_no_information,
    is_populated,
    load_json,
    verify_evidence_binding,
)
# Imported, never re-typed — see _META_KEYS.
from l_doc_generator_stamp import STAMP_KEY as _GENERATOR_STAMP_KEY  # noqa: E402,E501

_STEM = "L25_RELIABILITY_MISSION_PROFILE"

# `_generator` is on this list for the same reason `emitted_by` is: it
# describes the FILE (which plugin release wrote it), not the part. Without
# it an N/A stub — whose whole point is that it carries no content — would
# report one non-metadata key and stop looking empty.
_META_KEYS = frozenset({
    "doc_id", "doc_name", "applicability", "ic_class", "rationale",
    "extraction_hints", "extraction_status", "emitted_by",
    "extraction_evidence", "extraction_strategy", "schema_version",
    "evidence", "evidence_paths",
    _GENERATOR_STAMP_KEY,
})

# Field-shape classification by the field's OWN name. Generic engineering
# nouns, not vendor or design tokens.
_MARGIN_NAME_TOKENS = ("margin", "budget", "derate", "derating", "limit",
                       "headroom", "fit", "rate")
# NOTE: deliberately excludes "profile"/"envelope". A field named
# `mission_profile` is a descriptor ("automotive under-hood, key-on/key-off");
# the numeric envelope lives in the temperature/lifetime fields. Demanding two
# numeric bounds from a descriptor would be a manufactured failure.
_ENVELOPE_NAME_TOKENS = ("temp", "temperature", "lifetime", "life", "range",
                         "hours")

# Celsius must be EXPLICIT for the cross-check. A bare number under a
# temp-named key could be Kelvin or Fahrenheit; guessing would manufacture
# false positives, so an ambiguous unit means "do not cross-check".
_CELSIUS_RE = re.compile(
    r"([-+]?\d+(?:\.\d+)?)\s*(?:°\s*[cC]\b|deg\s*[cC]\b|degrees?\s*[cC]\b"
    r"|celsius\b|\bC\b)")


def _celsius_values(value: Any) -> List[float]:
    """Temperatures in `value` that are EXPLICITLY Celsius."""
    out: List[float] = []
    if isinstance(value, str):
        for m in _CELSIUS_RE.finditer(value):
            try:
                out.append(float(m.group(1)))
            except ValueError:
                pass
        return out
    if isinstance(value, dict):
        unit_txt = " ".join(
            str(v) for k, v in value.items() if "unit" in str(k).lower())
        if _CELSIUS_RE.search(unit_txt) or unit_txt.strip().lower() in (
                "c", "°c", "degc", "celsius"):
            for k, v in value.items():
                if "unit" in str(k).lower():
                    continue
                out.extend(extract_numbers(v))
        for v in value.values():
            out.extend(_celsius_values(v))
        return out
    if isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_celsius_values(v))
        return out
    return out


def _declared_operating_celsius(project: Path,
                                exclude: Path) -> List[Tuple[str, float]]:
    """Operating temperatures this design declares in its OWN other L-docs.

    Only explicit-Celsius values under a temperature-named key are taken, so
    an ambiguous or unitless number never manufactures a cross-check failure.
    Returns ``(source_label, celsius)`` pairs.
    """
    found: List[Tuple[str, float]] = []

    def _walk(node: Any, src: str, key_path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                child = f"{key_path}.{k}" if key_path else str(k)
                if "temp" in kl:
                    for c in _celsius_values(v):
                        found.append((f"{src}:{child}", c))
                _walk(v, src, child)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, src, f"{key_path}[{i}]")

    for root in generated_docs_roots(project):
        for jf in sorted(root.glob("L*.json")):
            try:
                if jf.resolve() == exclude.resolve():
                    continue
            except OSError:
                continue
            doc = load_json(jf)
            if isinstance(doc, (dict, list)):
                _walk(doc, jf.name, "")
    return found


def _classify(key: str) -> str:
    k = key.strip().lower()
    if any(t in k for t in _MARGIN_NAME_TOKENS):
        return "margin"
    if any(t in k for t in _ENVELOPE_NAME_TOKENS):
        return "envelope"
    return "descriptor"


def _bounds_count(value: Any) -> int:
    """How many distinct numeric bounds `value` supplies."""
    if isinstance(value, dict):
        keys = {str(k).lower() for k in value.keys()}
        lo = any(k in keys for k in ("min", "low", "lower", "start", "from"))
        hi = any(k in keys for k in ("max", "high", "upper", "end", "to"))
        if lo and hi:
            return 2
    nums = extract_numbers(value)
    return len(set(nums))


def _check_one(project: Path, layer_path: Path) -> Tuple[str, List[str]]:
    rel = layer_path.relative_to(project) if layer_path.is_relative_to(project) \
        else layer_path
    doc = load_json(layer_path)
    if not isinstance(doc, dict):
        return "SKIP", [f"{rel}: unreadable / non-object JSON"]

    applicability = str(doc.get("applicability", "") or "").strip().upper()
    if applicability in ("N/A", "NA", "NOT_APPLICABLE", "NOT APPLICABLE"):
        if is_no_information(doc.get("rationale")):
            return "FAIL", [
                f"{rel}: applicability=N/A with no `rationale` — a silent-empty "
                f"layer is indistinguishable from a failed extraction"]
        return "SKIP", [f"{rel}: N/A stub with rationale"]

    fields = doc.get("fields")
    scope: Dict[str, Any] = fields if isinstance(fields, dict) else {
        k: v for k, v in doc.items() if k not in _META_KEYS}

    populated = {k: v for k, v in scope.items()
                 if k not in _META_KEYS and is_populated(v)}
    if not populated:
        return "SKIP", [
            f"{rel}: reliability envelope is inert "
            f"(extraction_status={doc.get('extraction_status')!r}) — no "
            f"consumer exists and nothing is claimed"]

    failures: List[str] = []
    passes: List[str] = []

    for key, value in sorted(populated.items()):
        kind = _classify(key)

        # (1) ACTIONABLE
        if kind == "margin":
            if not has_number_with_unit(value):
                failures.append(
                    f"{rel}:fields.{key}={value!r} — a derating margin/budget "
                    f"must be a NUMBER BOUND TO A UNIT for any consumer to "
                    f"apply it; this carries "
                    f"{'no unit' if extract_numbers(value) else 'no number'}")
                continue
        elif kind == "envelope":
            n = _bounds_count(value)
            if n < 2:
                failures.append(
                    f"{rel}:fields.{key}={value!r} — an operating/lifetime "
                    f"envelope needs TWO bounds (min and max); {n} numeric "
                    f"bound(s) found, so no corner set can be derived from it")
                continue
            if not has_number_with_unit(value):
                failures.append(
                    f"{rel}:fields.{key}={value!r} — envelope bounds carry no "
                    f"unit; -40..125 is unusable without knowing of what")
                continue
        else:
            if not isinstance(value, (str, dict, list)) or (
                    isinstance(value, str) and len(value.strip()) < 2):
                failures.append(
                    f"{rel}:fields.{key}={value!r} — not a usable descriptor")
                continue

        # (2) TRACEABLE
        subject = re.sub(r"_(margin|budget|range|profile|standard)$", "",
                         key.strip().lower()) or key.strip().lower()
        v = verify_evidence_binding(project, doc, subject, scope)
        if not v.ok:
            v2 = verify_evidence_binding(project, doc, key.strip().lower(),
                                         scope)
            if v2.ok:
                v = v2
        if not v.ok:
            if v.status == EvidenceVerdict.NO_EVIDENCE:
                why = (f"populated with {value!r} but bound to NO source "
                       f"evidence — an un-sourced qualification figure is a "
                       f"hallucination risk that reads authoritative")
            else:
                why = v.detail
            failures.append(f"{rel}:fields.{key} — {why}")
            continue

        passes.append(f"{rel}:fields.{key}={value!r} — {v.detail}")

    # (3) CONSISTENT with the design's own declared operating temperatures.
    envelope_c: List[float] = []
    for key, value in populated.items():
        if _classify(key) == "envelope" and "temp" in key.lower():
            envelope_c.extend(_celsius_values(value))
    if len(envelope_c) >= 2:
        lo, hi = min(envelope_c), max(envelope_c)
        declared = _declared_operating_celsius(project, layer_path)
        outside = [(s, c) for (s, c) in declared if c < lo or c > hi]
        if outside:
            shown = "; ".join(f"{s}={c}C" for s, c in outside[:4])
            failures.append(
                f"{rel}: mission-profile temperature envelope "
                f"[{lo}C, {hi}C] does NOT cover {len(outside)} operating "
                f"temperature(s) this design declares in its own L-docs "
                f"({shown}) — the envelope certifies a different chip")

    if failures:
        return "FAIL", failures
    return "PASS", passes


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: l25_reliability_envelope_actionable_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"[SKIP] l25_reliability_envelope_actionable_check: "
              f"{project} is not a directory")
        return 2

    layers = find_layer_files(project, _STEM)
    if not layers:
        print(f"[SKIP] l25_reliability_envelope_actionable_check: no "
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
        print(f"[FAIL] l25_reliability_envelope_actionable_check (ADVISORY): "
              f"{len(all_fail)} reliability field(s) unusable by a future "
              f"EM/aging derating consumer — a margin must be a number bound "
              f"to a unit, traceable to this design's own source.")
        for m in all_fail[:12]:
            print(f"  - {m}")
        if len(all_fail) > 12:
            print(f"  ... {len(all_fail) - 12} more")
        return 1

    if all_pass:
        print(f"[PASS] l25_reliability_envelope_actionable_check: "
              f"{len(all_pass)} reliability field(s) actionable "
              f"(number+unit / two bounds) and traceable to source evidence")
        for m in all_pass[:6]:
            print(f"  - {m}")
        return 0

    print(f"[SKIP] l25_reliability_envelope_actionable_check: "
          f"{n_skip}/{len(layers)} {_STEM} layer(s) inert or N/A — no consumer "
          f"exists and nothing is claimed")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
