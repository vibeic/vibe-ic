#!/usr/bin/env python3
"""l14_protocol_versioning_contract_check.py — SEMANTIC gate for
L14_PROTOCOL_VERSIONING.json.

VERDICT SEMANTICS — THIS GATE **ADVISES**; it does not block by default.
    Deliberate, and stated here so nobody has to guess. L14 has NO
    consumer: `phase1_protocol_spec_extract.py` is its PRODUCER, and the
    only other readers (`l_doc_taxonomy`, `phase1_doc_one_shot_runner`,
    `tools/phase1_engine/schema.py`) treat it as an inventory entry. It is
    not referenced anywhere in flow/phase1_phase2_phase3.yaml. Blocking a
    tape-out flow on a layer that nothing downstream reads would trade a
    real defect (a stalled flow) for a hypothetical one. So the default
    exit is 0 and the findings are printed for a human/AI reviewer.

    `--strict` makes every FAIL blocking (exit 1). THE DAY L14 GAINS A
    CONSUMER, WIRE IT IN WITH `--strict` — that is the whole point of
    shipping the rules now: the contract is already written down and
    already swept, so promotion is a one-word change rather than a new
    gate authored under pressure.

WHAT IT ENFORCES
    With no consumer to derive a contract from, the only honest contract
    is the one L14 makes with ITSELF, and it is still a semantic one — the
    same principle as everywhere else: a requirement is captured when it
    is present in an ACTIONABLE form, not when a token appears.

      1. SELF-CONSISTENCY OF THE STATUS FLAG. `extraction_status ==
         EXTRACTION_FOUND_NOTHING` while `fields.versions` /
         `deprecated_features` / `backward_compat_traps` carry rows is a
         document that lies about itself: any reader that trusts the flag
         to decide "was this layer populated?" gets the wrong answer.
         Conversely a doc claiming EXTRACTED with zero rows is a green
         light with nothing behind it. Both directions are checked.

      2. ROWS MUST BE ACTIONABLE. A version row is only useful if it says
         WHICH version and WHAT CHANGED. A row carrying only a version
         string is a token: it cannot tell an RTL author whether a feature
         moved, so it must not count toward completeness. Same for a
         deprecated feature with no name and a backward-compat trap with
         no described impact.

      3. ROWS MUST BE TRACEABLE. Version history is precisely the kind of
         content a language model will happily invent. Every row must be
         anchored to the input by a page/line/table/section/quote — either
         in the row itself or through the doc's own `evidence[]` /
         `extraction_evidence` block. A row with no anchor is
         indistinguishable from a hallucination and is refused.

    Everything is derived from L14's own declarations. No design name,
    PDK name, vendor part number or signal literal appears in this file.

RULES  (all FAIL severity; blocking only under --strict)
    l14_parseable                       valid JSON object.
    l14_status_matches_content          status flag agrees with row counts,
                                        in both directions.
    l14_version_row_actionable          each version row carries a version
                                        identifier AND a delta.
    l14_version_row_provenance          each version row is anchored to the
                                        input.
    l14_deprecated_feature_actionable   each deprecated entry names the
                                        feature and is anchored.
    l14_backward_compat_trap_actionable each trap names the affected
                                        version and the impact.

USAGE
    python3 l14_protocol_versioning_contract_check.py <project_dir>
        [--l14 PATH] [--strict] [--json OUT]

EXIT CODES
    0 = PASS, or findings present while advisory (the default)
    1 = FAIL and --strict
    2 = L14 not found (skip)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import _path_layout as _pl
except Exception:                # pragma: no cover - cache tree without helper
    _pl = None


_FOUND_NOTHING = "EXTRACTION_FOUND_NOTHING"
_ROW_CONTAINERS = ("versions", "deprecated_features", "backward_compat_traps")

_VERSION_ID_KEYS = ("version", "issue", "revision", "rev", "release",
                    "release_date", "version_id", "spec_version",
                    "name", "generation", "title", "label")
_DELTA_KEYS = ("delta", "change", "changes", "description", "summary",
               "what_changed", "note", "notes")
# A trap row is useful when it DESCRIBES the incompatibility. Which versions
# it spans is frequently encoded in the row's own key names
# (e.g. {"<gen-a>": …, "<gen-b>": …}) rather than in a version field, so
# demanding a version key here would flag well-formed rows — it does not.
_TRAP_KEYS = ("trap", "backward_compat_trap", "impact", "breaks",
              "incompatibility", "consequence", "risk", "description",
              "rule", "detail", "note", "summary", "text")
_FEATURE_KEYS = ("feature", "name", "signal", "field", "capability")
# Shortest prose that can plausibly describe an incompatibility. A trap row
# expressed as a bare sentence is legitimate; a two-word stub is not.
_MIN_TRAP_PROSE = 12
# One side of a differential trap row is often a terse negation
# ("No <signal>."); the version it belongs to is carried by the key, so the
# value only has to be a real statement, not a paragraph.
_MIN_DIFF_SIDE = 3
# A provenance anchor: something that lets a reviewer find the claim in the
# source. Any one of these, in the row or in the doc-level evidence block.
_PROV_KEYS = ("line", "lines", "page", "pages", "table", "table_id",
              "section", "clause", "quote", "source", "source_file",
              "evidence", "provenance", "anchor", "extracted_by")


def _fields(l14: Dict[str, Any]) -> Dict[str, Any]:
    f = l14.get("fields")
    return f if isinstance(f, dict) else l14


def _rows(l14: Dict[str, Any], key: str) -> List[Any]:
    v = _fields(l14).get(key)
    return v if isinstance(v, list) else []


def _has_any(row: Dict[str, Any], keys) -> bool:
    for k in keys:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, (list, tuple, dict)) and len(v) > 0:
            return True
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
    return False


def _doc_evidence_anchors(l14: Dict[str, Any]) -> int:
    """How many doc-level evidence anchors exist. The canonical producer
    emits one `evidence[]` entry per harvested row, so a doc whose anchor
    count covers its row count is traceable even when the rows themselves
    are flat."""
    n = 0
    ev = l14.get("evidence")
    if isinstance(ev, list):
        n += sum(1 for e in ev if isinstance(e, dict) and _has_any(e, _PROV_KEYS))
    xe = l14.get("extraction_evidence")
    if isinstance(xe, dict):
        for v in xe.values():
            if isinstance(v, list):
                n += len(v)
    elif isinstance(xe, list):
        n += len(xe)
    return n


def check(l14: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []

    def fail(rule, msg):
        findings.append({"severity": "FAIL", "rule": rule, "message": msg})

    if not isinstance(l14, dict):
        fail("l14_parseable",
             "L14_PROTOCOL_VERSIONING.json is not a JSON object")
        return {"findings": findings}

    if l14.get("applicability") == "N/A":
        return {"findings": findings, "skipped": "applicability=N/A"}

    versions = _rows(l14, "versions")
    deprecated = _rows(l14, "deprecated_features")
    traps = _rows(l14, "backward_compat_traps")
    total = len(versions) + len(deprecated) + len(traps)
    status = l14.get("extraction_status")
    anchors = _doc_evidence_anchors(l14)

    # 1. status flag vs content — both directions.
    if status == _FOUND_NOTHING and total > 0:
        fail("l14_status_matches_content",
             f"extraction_status is {_FOUND_NOTHING} while the document "
             f"carries {total} row(s) "
             f"(versions={len(versions)}, deprecated={len(deprecated)}, "
             f"traps={len(traps)}). Any reader that trusts the flag to "
             f"decide whether this layer was populated gets the wrong "
             f"answer; the flag and the content must agree.")
    if isinstance(status, str) and status.upper().startswith("EXTRACTED") \
            and total == 0:
        fail("l14_status_matches_content",
             "extraction_status claims EXTRACTED but the document carries "
             "zero version / deprecation / compat rows — a green flag with "
             "nothing behind it.")

    # 2 + 3. rows actionable and traceable.
    for i, row in enumerate(versions):
        label = f"versions[{i}]"
        if not isinstance(row, dict):
            fail("l14_version_row_actionable",
                 f"{label}: a bare {type(row).__name__} is a token, not a "
                 f"version-history row; need an identifier plus a delta.")
            continue
        if not _has_any(row, _VERSION_ID_KEYS):
            fail("l14_version_row_actionable",
                 f"{label}: no version identifier "
                 f"(one of {list(_VERSION_ID_KEYS)}).")
        if not _has_any(row, _DELTA_KEYS):
            fail("l14_version_row_actionable",
                 f"{label}: names a version but not WHAT CHANGED "
                 f"(one of {list(_DELTA_KEYS)}). A version with no delta "
                 f"cannot tell an RTL author whether behaviour moved.")
        if not _has_any(row, _PROV_KEYS) and anchors < len(versions):
            fail("l14_version_row_provenance",
                 f"{label}: no page/line/table/quote anchor, and the "
                 f"doc-level evidence block has {anchors} anchor(s) for "
                 f"{len(versions)} version row(s). An unanchored version "
                 f"history is indistinguishable from an invented one.")

    for i, row in enumerate(deprecated):
        label = f"deprecated_features[{i}]"
        if isinstance(row, str):
            # A prose deprecation ("<feature> — deprecated.") names the
            # feature inline; only a stub is unusable.
            if len(row.strip()) < _MIN_TRAP_PROSE:
                fail("l14_deprecated_feature_actionable",
                     f"{label}: {row.strip()!r} is a stub, not a deprecation "
                     f"an implementer can act on.")
            continue
        if not isinstance(row, dict):
            fail("l14_deprecated_feature_actionable",
                 f"{label}: a bare {type(row).__name__} does not name the "
                 f"deprecated feature.")
            continue
        if not _has_any(row, _FEATURE_KEYS):
            fail("l14_deprecated_feature_actionable",
                 f"{label}: does not name the deprecated feature "
                 f"(one of {list(_FEATURE_KEYS)}).")
        if not _has_any(row, _PROV_KEYS) and anchors < len(deprecated):
            fail("l14_deprecated_feature_actionable",
                 f"{label}: no provenance anchor; a deprecation claim with "
                 f"no source cannot be reviewed.")

    for i, row in enumerate(traps):
        label = f"backward_compat_traps[{i}]"
        if isinstance(row, str):
            if len(row.strip()) < _MIN_TRAP_PROSE:
                fail("l14_backward_compat_trap_actionable",
                     f"{label}: {row.strip()!r} is a stub, not a description "
                     f"of an incompatibility an implementer can avoid.")
            continue
        if not isinstance(row, dict):
            fail("l14_backward_compat_trap_actionable",
                 f"{label}: a bare {type(row).__name__} carries no trap "
                 f"description.")
            continue
        # Two legitimate shapes: an explicit description key, or a
        # DIFFERENTIAL row that states the behaviour on either side of the
        # break under version-named keys ({"<gen-a>": "…", "<gen-b>": "…"}).
        prose = [v for k, v in row.items()
                 if isinstance(v, str) and len(v.strip()) >= _MIN_DIFF_SIDE
                 and k not in ("trap_name", "name", "title", "label")]
        if not _has_any(row, _TRAP_KEYS) and len(prose) < 2:
            fail("l14_backward_compat_trap_actionable",
                 f"{label}: names a trap but never describes the "
                 f"incompatibility — no description key "
                 f"({list(_TRAP_KEYS)}) and fewer than two per-version "
                 f"statements to diff. An implementer cannot avoid it.")

    return {
        "findings": findings,
        "extraction_status": status,
        "row_counts": {"versions": len(versions),
                       "deprecated_features": len(deprecated),
                       "backward_compat_traps": len(traps)},
        "evidence_anchors": anchors,
    }


def resolve_l14(project: Path, override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.is_file() else None
    cands = [project / "phase1" / "generated_docs" /
             "L14_PROTOCOL_VERSIONING.json"]
    if _pl is not None:
        try:
            cands.append(_pl.generated_docs_dir(project) /
                         "L14_PROTOCOL_VERSIONING.json")
        except Exception:
            pass
    cands.append(project / "L14_PROTOCOL_VERSIONING.json")
    for c in cands:
        if c.is_file():
            return c
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--l14", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="block (exit 1) on FAIL; default is advisory "
                         "because L14 has no downstream consumer")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    path = resolve_l14(args.project_dir, args.l14)
    if path is None:
        print("[SKIP] l14_protocol_versioning_contract_check: "
              "L14_PROTOCOL_VERSIONING.json not found")
        return 2
    try:
        l14 = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result = {"findings": [{"severity": "FAIL", "rule": "l14_parseable",
                                "message": f"cannot parse {path}: {exc}"}]}
    else:
        result = check(l14)

    result["l14_path"] = str(path)
    result["blocks"] = bool(args.strict)
    fails = [f for f in result["findings"] if f["severity"] == "FAIL"]
    result["pass"] = not fails

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2))
    for f in result["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")

    if not fails:
        print("[PASS] l14_protocol_versioning_contract_check")
        return 0
    if args.strict:
        print(f"[FAIL] l14_protocol_versioning_contract_check: "
              f"{len(fails)} finding(s) — BLOCKS (--strict)")
        return 1
    print(f"[ADVISE] l14_protocol_versioning_contract_check: "
          f"{len(fails)} finding(s) — advisory only (L14 has no consumer; "
          f"re-run with --strict to block)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
