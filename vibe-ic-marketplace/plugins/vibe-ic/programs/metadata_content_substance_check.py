#!/usr/bin/env python3
"""
metadata_content_substance_check.py — guard against empty / near-empty
phase1 metadata JSON files that satisfy the v1.6.26 canonical-taxonomy
gate by location alone.

The v1.6.26 taxonomy gate verifies that whitelisted phase1 JSON files
live at canonical paths. It does NOT inspect their content. An agent
under verdict pressure can satisfy taxonomy by emitting:

    phase1/extraction_patterns.json       → {}                    (empty)
    phase1/extraction_patterns.auto.json  → {"patterns": []}      (no patterns)
    phase1/completeness_check_config.json → {"version":1,"checks":[]}
    phase1/ai_deep_review_patches.json    → {} or []              (no patches)

Every downstream gate that consumes these files becomes vacuously high:
the phase1 coverage report has no patterns to evaluate, no checks to
enforce, no patches to apply. `extraction_coverage_check` returns
vacuously high because the denominator is zero.

This gate is the substance counterpart: each existing whitelisted file
must satisfy a per-file minimum-population schema. Backlog reference:
  community/backlogs/ORGANIC-20260508-metadata-content-substance.yaml

Schema requirements (declarative, chip-AGNOSTIC)
-------------------------------------------------
Each entry in `_SUBSTANCE_REQUIREMENTS`:

    "shape"          — how the content is structured
    "min_entries"    — minimum total entries the file must declare
    "rationale"      — why the minimum exists (cited in failure msg)

Shape vocabulary:
* `list_or_dict_with_patterns_key` — top level is either a JSON array
  of pattern entries OR a JSON object with a "patterns" key containing
  a list. Counts list length.
* `dict_with_checks_array` — JSON object with a "checks" key whose
  value is a list. Counts list length.
* `patches_dict_or_list` — JSON object `{"patches": {<layer>: [...]}}`
  OR a flat JSON array (legacy). Empty is permitted (`min_entries=0`)
  because the sidecar may legitimately have no AI patches to apply.

Honest zero-unpromoted N/A (ORGANIC-20260606 #494)
--------------------------------------------------
`phase1/extraction_patterns.auto.json` is the *unpromoted remainder*
written by phase1's `_seed_canonical_from_backfilled_subset`. When EVERY
auto-discovered literal got backfilled into typed L*.json (zero
unpromoted), the writer LEGITIMATELY emits an otherwise-empty companion
carrying ONLY its explicit zero-unpromoted marker `_comment`:

    {"_comment": "Auto-discovered extraction patterns NOT yet backfilled
                  into typed L*.json fields. v1.6.7 keeps these out of
                  the canonical denominator ..."}

That is the runner's own honest output — there is nothing to populate.
A hard `min_entries:1` here would make a clean run FAIL its own gate, so
the runner would be pressured to stuff fake patterns. The substance gate
therefore recognises the WRITER'S explicit STRUCTURAL marker (not mere
emptiness) as honest-N/A → a named SKIP (exit 0). The marker is required
verbatim-substring; an empty companion WITHOUT it, or one whose entries
lack substance, still FAILs.

Verdict tiers
-------------
PASS         — every existing whitelisted file meets its substance
               threshold (or has `min_entries=0` and is empty).
SKIP         — a companion whose only content is the writer's explicit
               zero-unpromoted marker (honest N/A; exit 0), and no other
               file fails.
VACUOUS_PASS — none of the whitelisted files exist (project has not
               reached Phase 1 (doc-extraction) yet).
FAIL         — at least one file exists but is below its minimum or
               is malformed for its declared shape.

Failure modes
-------------
* `EMPTY_OR_BELOW_MIN`     — file parses but entry count < min_entries.
* `BROKEN_SCHEMA`          — file parses but does not match declared
                              shape (e.g. completeness_check_config.json
                              missing the "checks" key).
* `INVALID_JSON`           — file exists but is not valid JSON.

Usage
-----
    python3 metadata_content_substance_check.py <project_dir>
                                                 [--json <out>]

Exit codes
    0  PASS / VACUOUS_PASS / SKIP (honest zero-unpromoted N/A)
    1  one or more files fail the substance check
    2  argument or I/O error

chip-AGNOSTIC. The schema-requirements dict is the only configuration;
no chip / vendor / specific protocol-name is hardcoded.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ORGANIC-20260606 #494 — honest zero-unpromoted N/A marker.
#
# `extraction_patterns.auto.json` is the *unpromoted remainder* the phase1
# writers stamp: it is first written by `_autodiscover_patterns`
# (phase1_coverage_report_gen) and then REWRITTEN by
# `_seed_canonical_from_backfilled_subset` (phase1_doc_one_shot_runner) on
# every run with whatever literals were NOT backfilled into typed L*.json.
# When zero literals remain unpromoted (all backfilled), the companion is
# emitted with ONLY a writer-authored provenance `_comment` and no entries.
#
# BOTH writers stamp that `_comment` with the SAME stable, distinctive
# provenance prefix, so we key the honest-N/A SKIP on that STRUCTURAL marker
# — a required verbatim-substring of the `_comment` value — NOT on mere
# emptiness. A file empty WITHOUT this writer signature still FAILs.
#
# Writer source of truth (verbatim `_comment` prefixes):
#   * phase1_coverage_report_gen._autodiscover_patterns:
#       "Auto-discovered extraction patterns (Wave 5). ..."
#   * phase1_doc_one_shot_runner._seed_canonical_from_backfilled_subset:
#       "Auto-discovered extraction patterns NOT yet backfilled into typed ..."
# Their common, distinctive prefix is the structural signature below.
#
# The marker maps {whitelisted rel path → required `_comment` substring}.
_ZERO_UNPROMOTED_MARKER: Dict[str, str] = {
    "phase1/extraction_patterns.auto.json":
        "Auto-discovered extraction patterns",
}


def _has_zero_unpromoted_marker(rel: str, data: Any) -> bool:
    """True iff `data` is the writer's honest zero-unpromoted companion for
    `rel`: a JSON object whose `_comment` carries the explicit marker
    substring AND which declares NO real (non-underscore) pattern entries.

    Requiring BOTH (the structural marker AND zero substantive entries)
    means an attacker cannot smuggle a substance-missing file past the gate
    by pasting the marker onto a half-populated file — if any real entry
    exists this returns False and the normal min_entries path runs.
    """
    needle = _ZERO_UNPROMOTED_MARKER.get(rel)
    if needle is None:
        return False
    if not isinstance(data, dict):
        return False
    comment = data.get("_comment")
    if not isinstance(comment, str) or needle not in comment:
        return False
    # No real (non-underscore) keys carrying pattern entries.
    for k, v in data.items():
        if k.startswith("_"):
            continue
        # Any non-metadata key with a non-empty list is a real entry; a
        # marker on top of real content is NOT honest-N/A.
        if isinstance(v, list) and len(v) > 0:
            return False
        if not isinstance(v, list):
            # Unexpected non-list payload alongside the marker — let the
            # normal shape handler classify it (don't grant the SKIP).
            return False
    return True


# Per-file substance requirements. Add a new whitelisted phase1 JSON
# slot here; the rest of the gate logic adapts automatically.
_SUBSTANCE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "phase1/extraction_patterns.json": {
        "shape": "list_or_dict_with_patterns_key",
        "min_entries": 1,
        "rationale": (
            "phase1 coverage / completeness gates compute "
            "denominator from the patterns declared here. An empty "
            "pattern list yields vacuously-high coverage (no "
            "patterns to miss = no misses)."),
    },
    "phase1/extraction_patterns.auto.json": {
        "shape": "list_or_dict_with_patterns_key",
        "min_entries": 1,
        "rationale": (
            "Companion auto-discovered patterns. Same vacuous-"
            "coverage risk as extraction_patterns.json if empty."),
    },
    "phase1/completeness_check_config.json": {
        "shape": "dict_with_checks_array",
        "min_entries": 1,
        "rationale": (
            "completeness_check_config drives the per-doc "
            "completeness gate. Empty checks[] = no enforcement; "
            "every input doc passes vacuously."),
    },
    "phase1/ai_deep_review_patches.json": {
        "shape": "patches_dict_or_list",
        "min_entries": 0,  # zero is permitted, see rationale
        "rationale": (
            "AI deep-review patches are inherently optional — if the "
            "deterministic harvester captured every input-doc fact, "
            "the sidecar may legitimately be empty. Substance check "
            "verifies only schema shape, not minimum entries."),
    },
}


@dataclass
class SubstanceFinding:
    rel_path: str
    rule: str  # EMPTY_OR_BELOW_MIN | BROKEN_SCHEMA | INVALID_JSON
    declared_shape: str
    observed_entries: Optional[int]
    min_entries: int
    rationale: str


def _count_list_or_patterns_dict(data: Any) -> Tuple[Optional[int], bool]:
    """Return (entry_count, schema_ok). For shape
    `list_or_dict_with_patterns_key`. Three accepted variants:

      1. flat list:                    [<entry>, <entry>, ...]
      2. patterns-key dict:            {"patterns": [<entry>, ...]}
      3. dict-of-lists keyed arbitrarily, typically by source filename
         (the canonical phase1 layout):
             {"<source.txt>": [<entry>, ...], "<other.txt>": [...]}

    Underscore-prefixed top-level keys are treated as metadata
    (e.g. `_comment`, `_schema_version`) and skipped from the count.
    """
    if isinstance(data, list):
        return len(data), True
    if isinstance(data, dict):
        if "patterns" in data:
            v = data["patterns"]
            if isinstance(v, list):
                return len(v), True
            return None, False
        # Variant 3 — dict-of-lists. Skip metadata keys (underscore-
        # prefixed). Every remaining value must be a list, and the
        # total count is the sum of their lengths.
        payload = {k: v for k, v in data.items() if not k.startswith("_")}
        if not payload:
            # Only metadata keys present, no actual entries.
            return 0, True
        if all(isinstance(v, list) for v in payload.values()):
            return sum(len(v) for v in payload.values()), True
        return None, False
    return None, False


def _count_dict_with_checks_array(data: Any) -> Tuple[Optional[int], bool]:
    """Shape `dict_with_checks_array`."""
    if not isinstance(data, dict):
        return None, False
    if "checks" not in data:
        return None, False
    v = data["checks"]
    if not isinstance(v, list):
        return None, False
    return len(v), True


def _count_patches_dict_or_list(data: Any) -> Tuple[Optional[int], bool]:
    """Shape `patches_dict_or_list`. Sums entries across all layers
    in the dict form."""
    if isinstance(data, list):
        return len(data), True
    if isinstance(data, dict):
        if "patches" not in data:
            # An empty dict {} is malformed for this slot — must
            # at minimum declare the "patches" key (even if its
            # value is {}).
            return None, False
        v = data["patches"]
        if isinstance(v, list):
            return len(v), True
        if isinstance(v, dict):
            if not all(isinstance(lst, list) for lst in v.values()):
                return None, False
            return sum(len(lst) for lst in v.values()), True
        return None, False
    return None, False


_SHAPE_HANDLERS = {
    "list_or_dict_with_patterns_key": _count_list_or_patterns_dict,
    "dict_with_checks_array": _count_dict_with_checks_array,
    "patches_dict_or_list": _count_patches_dict_or_list,
}


def audit(project: Path) -> Tuple[str, List[SubstanceFinding], Dict[str, Any]]:
    """Audit `project`. Return (verdict, findings, summary).

    summary carries per-file counts so the JSON report can show
    every check, not just the failures (helpful for human review)."""
    findings: List[SubstanceFinding] = []
    summary: Dict[str, Any] = {}
    files_present = 0
    skipped: List[str] = []

    for rel, spec in _SUBSTANCE_REQUIREMENTS.items():
        f = project / rel
        if not f.is_file():
            summary[rel] = {"present": False}
            continue
        files_present += 1
        try:
            data = json.loads(f.read_text(
                encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            findings.append(SubstanceFinding(
                rel_path=rel,
                rule="INVALID_JSON",
                declared_shape=spec["shape"],
                observed_entries=None,
                min_entries=spec["min_entries"],
                rationale=f"json parse error: {e.msg} at line {e.lineno}"))
            summary[rel] = {"present": True, "valid_json": False}
            continue

        # ORGANIC-20260606 #494 — honest zero-unpromoted N/A. The phase1
        # writer rewrites this companion on every run; when EVERY auto
        # literal was backfilled into typed L*.json the remainder is empty
        # and the file carries ONLY the writer's explicit marker `_comment`.
        # That is the runner's own honest output, so a hard min_entries:1
        # must not FAIL it. Recognise the STRUCTURAL marker (not mere
        # emptiness) → named SKIP, exit 0.
        if _has_zero_unpromoted_marker(rel, data):
            skipped.append(rel)
            summary[rel] = {
                "present": True, "valid_json": True,
                "shape_ok": True, "entries": 0,
                "skipped": "ZERO_UNPROMOTED_MARKER",
                "skip_reason": (
                    "writer's explicit zero-unpromoted marker present and "
                    "no substantive entries — honest N/A (every "
                    "auto-discovered literal was backfilled into typed "
                    "L*.json; nothing remains unpromoted)."),
            }
            continue

        handler = _SHAPE_HANDLERS.get(spec["shape"])
        if handler is None:
            findings.append(SubstanceFinding(
                rel_path=rel,
                rule="BROKEN_SCHEMA",
                declared_shape=spec["shape"],
                observed_entries=None,
                min_entries=spec["min_entries"],
                rationale=(f"unknown shape {spec['shape']!r} (gate "
                           f"misconfiguration)")))
            summary[rel] = {"present": True, "valid_json": True,
                            "shape_ok": False}
            continue

        count, shape_ok = handler(data)
        summary[rel] = {
            "present": True, "valid_json": True,
            "shape_ok": shape_ok, "entries": count}
        if not shape_ok:
            # v1.6.52 — surface a concrete migration hint when the
            # project carries an old-shape file. The most common case
            # is `completeness_check_config.json` with only the
            # legacy `reference_docs` key (the plugin reader has used
            # it for ages but the v1.6.51 substance gate now expects
            # `checks[]`). Detecting the legacy key lets the user
            # know this is a known pre-v1.6.51 layout, not a broken
            # config.
            hint = ""
            if (rel == "phase1/completeness_check_config.json"
                    and isinstance(data, dict)
                    and "reference_docs" in data
                    and "checks" not in data):
                hint = (" Migration hint (v1.6.52): legacy "
                        "`reference_docs`-only config detected. "
                        "Add `\"version\": 1` and `\"checks\": [{...}]` "
                        "alongside `reference_docs` to satisfy the "
                        "v1.6.51 substance gate; the original "
                        "`reference_docs` key is still honoured by the "
                        "completeness gate, both keys can coexist.")
            findings.append(SubstanceFinding(
                rel_path=rel,
                rule="BROKEN_SCHEMA",
                declared_shape=spec["shape"],
                observed_entries=count,
                min_entries=spec["min_entries"],
                rationale=spec["rationale"] + hint))
            continue
        if (count is None) or (count < spec["min_entries"]):
            findings.append(SubstanceFinding(
                rel_path=rel,
                rule="EMPTY_OR_BELOW_MIN",
                declared_shape=spec["shape"],
                observed_entries=count,
                min_entries=spec["min_entries"],
                rationale=spec["rationale"]))

    if files_present == 0:
        return "VACUOUS_PASS", [], summary
    if findings:
        return "FAIL", findings, summary
    # No failures. If any file was honest-N/A SKIPed, surface SKIP so the
    # caller knows a clean run's own marker was honoured (still exit 0).
    if skipped:
        return "SKIP", [], summary
    return "PASS", [], summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify whitelisted phase1 metadata JSON files "
                    "have non-empty content per declarative schema.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings, summary = audit(project)
    report = {
        "gate": "metadata_content_substance_check",
        "verdict": verdict,
        "project": str(project),
        "requirements": _SUBSTANCE_REQUIREMENTS,
        "per_file": summary,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("none of the whitelisted phase1 metadata "
                            "files present; project has not reached "
                            "Phase 1 (doc-extraction) yet.")
    if verdict == "SKIP":
        skipped = [k for k, v in summary.items()
                   if v.get("skipped") == "ZERO_UNPROMOTED_MARKER"]
        report["skipped"] = skipped
        report["reason"] = (
            "honest N/A: companion(s) carry the phase1 writer's explicit "
            "zero-unpromoted marker with no substantive entries (every "
            "auto-discovered literal was backfilled into typed L*.json). "
            "A clean run's own honest output is not a substance failure.")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "SKIP":
        skipped = report.get("skipped", [])
        print(f"SKIP: {len(skipped)} companion(s) are honest zero-"
              f"unpromoted N/A (writer's explicit marker, no entries).")
        for k in skipped:
            print(f"  - {k}  (ZERO_UNPROMOTED_MARKER)")
        # Any non-skipped present file that passed substance, list it too.
        for k, v in summary.items():
            if (v.get("present") and not v.get("skipped")
                    and v.get("shape_ok") and v.get("entries") is not None):
                print(f"  - {k}  entries={v.get('entries')}")
        return 0
    if verdict == "PASS":
        present = [k for k, v in summary.items() if v.get("present")]
        print(f"PASS: {len(present)} whitelisted phase1 metadata file(s) "
              f"meet substance requirements.")
        for k in present:
            v = summary[k]
            print(f"  - {k}  entries={v.get('entries')}")
        return 0
    print(f"FAIL: {len(findings)} whitelisted phase1 metadata file(s) "
          f"lack substance:", file=sys.stderr)
    for f in findings:
        print(f"  [{f.rule}] {f.rel_path}", file=sys.stderr)
        print(f"      shape={f.declared_shape}  "
              f"observed={f.observed_entries}  "
              f"min={f.min_entries}", file=sys.stderr)
        print(f"      reason: {f.rationale}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
