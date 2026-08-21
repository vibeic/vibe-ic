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

A ROW CONTAINER THIS GATE CANNOT READ IS REFUSED, NEVER A PASS (vibe-ic#991)
    `_rows()` was `v if isinstance(v, list) else []`, so `versions` carrying a
    real version history keyed BY VERSION instead of as a list of rows became
    the empty list, `total` became 0, every row rule iterated nothing, and the
    gate printed `[PASS]` and exited 0. MEASURED: a document declaring two
    version rows in that shape produced output BYTE-IDENTICAL — stdout, exit
    code and JSON report alike — to a document with no `versions` key at all.
    Since 122 of the 197 L14 docs published in this tree legitimately declare
    `EXTRACTION_FOUND_NOTHING` with empty rows, the coerced zero was
    indistinguishable from the commonest honest state in the corpus.

    Now a row container that is PRESENT and is not a JSON array is a REFUSAL
    that NAMES WHAT ARRIVED — its JSON type, its keys, and how many entries
    went unexamined — and the verdict is REFUSED with a non-zero exit.

    WHAT IS DELIBERATELY NOT CHANGED: a zero denominator still PASSES when the
    layer was READ and is honestly empty. `gate_zero_denominator_refuses_check`
    keys on "a zero beside a POPULATION word", and its own governing line is
    "an empty artefact is not a missing one" — the 122 docs above were read and
    are empty, which is a real result. Only an UNREAD container refuses.

RULES  (FAIL severity; blocking only under --strict, EXCEPT the shape refusal)
    l14_parseable                       valid JSON object.
    l14_row_container_shape             every row container that is PRESENT is
                                        a JSON array. REFUSED (exit 1) whether
                                        or not --strict: `--strict` governs
                                        whether DESIGN findings block, and this
                                        one is not a design finding — it is the
                                        gate reporting that it could not read
                                        its own input. Advisory-by-default is
                                        justified below by "L14 has no
                                        consumer", which is a statement about
                                        the CONTENT nobody reads, not a licence
                                        for the gate to report a pass over a
                                        layer it never examined.
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
    1 = FAIL and --strict, OR a row container was REFUSED for its shape
        (#991 — a gate that could not read its input must not exit 0; the only
        wiring is the flow's `advisory_program_exit_zero` slot, which RECORDS
        every non-zero rc as an advisory FINDING and never blocks a step, so
        this cannot fail a run — measured, not assumed)
    2 = L14 not found (skip)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _shape_refusal as _sr     # #991 — the ONE definition of a wrong shape

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


def _rows(l14: Dict[str, Any],
          key: str) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """`(rows, mismatch)`. `mismatch` is None when the container is ABSENT or
    is a JSON array — both real, legitimate zeros — and otherwise NAMES what
    arrived instead. #991: this used to swallow the second value, and the
    caller could not tell a layer that declares nothing from a layer whose
    declarations it failed to read."""
    return _sr.read_list_from(_fields(l14), key)


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

    versions, m_versions = _rows(l14, "versions")
    deprecated, m_deprecated = _rows(l14, "deprecated_features")
    traps, m_traps = _rows(l14, "backward_compat_traps")
    total = len(versions) + len(deprecated) + len(traps)
    status = l14.get("extraction_status")
    anchors = _doc_evidence_anchors(l14)

    # 0. #991 — A CONTAINER THIS GATE CANNOT READ IS REFUSED BEFORE ANY OTHER
    # RULE RUNS. It has to come first: every rule below iterates these three
    # lists, so a coerced empty makes all of them vacuously true, and rule 1
    # would then read `total == 0` and report either nothing at all or
    # "carries zero rows" — a sentence about content, for a document whose
    # content this gate never saw.
    refusals = [m for m in (m_versions, m_deprecated, m_traps) if m]
    for m in refusals:
        fail("l14_row_container_shape", _sr.sentence(m, "L14"))

    # 1. status flag vs content — both directions.
    if status == _FOUND_NOTHING and total > 0:
        fail("l14_status_matches_content",
             f"extraction_status is {_FOUND_NOTHING} while the document "
             f"carries {total} row(s) "
             f"(versions={len(versions)}, deprecated={len(deprecated)}, "
             f"traps={len(traps)}). Any reader that trusts the flag to "
             f"decide whether this layer was populated gets the wrong "
             f"answer; the flag and the content must agree.")
    # `and not refusals`: with a container refused, `total == 0` is this
    # gate's own coercion, not the document's content. Saying "the document
    # carries zero rows" there would be a false statement about the input and
    # would point the remedy at the producer's completeness instead of at the
    # shape — the misnaming half of #991, one rule down.
    if isinstance(status, str) and status.upper().startswith("EXTRACTED") \
            and total == 0 and not refusals:
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
        # THE DENOMINATOR, stated (gate_discloses_denominator_check). `total`
        # is what was EXAMINED; `refused_containers` is what could not be, and
        # the two are separate numbers precisely so no reader can add them or
        # mistake one for the other.
        "examined_rows": total,
        "refused_containers": refusals,
        "entries_not_examined": _sr.not_examined(refusals),
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
    refused = result.get("refused_containers") or []
    result["verdict"] = ("REFUSED" if refused
                         else "PASS" if not fails
                         else "FAIL" if args.strict else "ADVISE")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2))
    for f in result["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")

    # EVERY verdict line states its denominator — how many rows this run
    # actually examined — so no outcome here can be read without it
    # (gate_discloses_denominator_check).
    n = result.get("examined_rows", 0)
    counts = result.get("row_counts") or {}
    denom = (f"examined {n} row(s) "
             f"(versions={counts.get('versions', 0)}, "
             f"deprecated={counts.get('deprecated_features', 0)}, "
             f"traps={counts.get('backward_compat_traps', 0)})")

    # REFUSED OUTRANKS EVERY OTHER OUTCOME, including a completely clean run
    # of the remaining rules — because those rules iterated a list this gate
    # built by discarding the input, so their cleanliness is an artefact of
    # the discard. A fix that only added the finding and left the exit code
    # at 0 would have left the published shape exactly as it was: advisory
    # rc 0, which the flow records as `ok`.
    if refused:
        lost = result.get("entries_not_examined")
        print(f"[REFUSED] l14_protocol_versioning_contract_check: "
              f"{len(refused)} row container(s) are PRESENT in a shape this "
              f"gate cannot read "
              f"({', '.join(sorted(m['field'] for m in refused))}) — "
              f"{denom}, and "
              f"{lost if isinstance(lost, int) else 'an unknown number of'} "
              f"entr{'y' if lost == 1 else 'ies'} went unexamined. This is "
              f"NOT a pass and NOT a reading of zero.")
        return 1
    if not fails:
        print(f"[PASS] l14_protocol_versioning_contract_check: {denom}")
        return 0
    if args.strict:
        print(f"[FAIL] l14_protocol_versioning_contract_check: "
              f"{len(fails)} finding(s), {denom} — BLOCKS (--strict)")
        return 1
    print(f"[ADVISE] l14_protocol_versioning_contract_check: "
          f"{len(fails)} finding(s), {denom} — advisory only (L14 has no "
          f"consumer; re-run with --strict to block)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
