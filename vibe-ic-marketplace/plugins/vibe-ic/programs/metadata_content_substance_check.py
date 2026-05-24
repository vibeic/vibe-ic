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

Verdict tiers
-------------
PASS         — every existing whitelisted file meets its substance
               threshold (or has `min_entries=0` and is empty).
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
    0  PASS / VACUOUS_PASS
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
    return ("FAIL" if findings else "PASS"), findings, summary


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
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
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
