#!/usr/bin/env python3
"""
extraction_evidence_schema_check.py — gate (LL-40, v0.119.39).

Wave 23 (v0.119.55) — extraction coverage is non-waivable. 100% is
the HARD acceptance threshold for Phase 1 (doc-extraction). If a literal cannot be
extracted by the auto-discovery patterns, the agent MUST add a
project-level `extraction_patterns.json` to teach the extractor how
to find it. There is NO "we'll skip this doc" option. The legacy
`extraction_evidence_schema_alternative` waiver has been removed,
and the soft/hard distinction has been removed — every L1-L23 doc
that exists must carry a schema-valid `extraction_evidence` field.

BACKLOG-v13 Wave 7. The Wave 2 / Wave 5 / Wave 7 SKILL.md updates
require every Phase 1 (doc-extraction)-emitted L*.json to carry a top-level
`extraction_evidence` field of shape:

  {"<source_doc_filename>": [
       {"literal": "<verbatim quote>", "label": "<short description>"},
       ... | "<verbatim string>"
  ]}

LL-38 (`extraction_coverage_check`) only does substring matching
across the union of L*.json text. It does NOT verify the
structural shape of the `extraction_evidence` field itself, so a
fresh agent could emit a malformed value (e.g. a single string
instead of a dict, or a list of ints) and still pass LL-38.

This gate fixes that:
  1. For each `<project>/generated_docs/L*.json`, parse the JSON.
  2. For each L doc whose name maps to a skill that mandates the
     field (the 8 Wave 2 + Wave 5 skills, plus the 6 Wave 7 skills
     = 14 mandated total), verify:
       - top-level `extraction_evidence` exists, is a dict
       - each value is a list
       - each list entry is either:
           (a) a string, OR
           (b) a dict with `literal` (required) + `label` (optional)
  3. Verdict:
       - silent-skip when `<project>/generated_docs/` is absent
         (Phase 1 (doc-extraction) hasn't run yet)
       - PASS when all required L docs that exist on disk carry a
         schema-valid `extraction_evidence` field
       - FAIL with per-doc breakdown otherwise
  4. Wave 23 (v0.119.55): NO WAIVER. The legacy waiver
     `extraction_evidence_schema_alternative` is no longer honored;
     `phase1_no_waivers_used_check` will FAIL if it is even
     present in `<project>/waivers.json`.

Required L docs (must have `extraction_evidence` to PASS)
=========================================================
Wave 23 (v0.119.55): every L1-L23 doc that exists in
`generated_docs/` must carry a schema-valid `extraction_evidence`
field — no soft prefixes, no WARN-only path. Missing field or
malformed shape on any L1-L23 doc → HARD FAIL.

Usage
-----
    python3 extraction_evidence_schema_check.py <project_dir>

Returns 0 PASS / silent-skip / waived, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import _path_layout as _pl

# Wave 42 — make sibling imports (`_facts_yaml`) work from any caller.
_PROG_DIR = str(Path(__file__).resolve().parent)
if _PROG_DIR not in sys.path:
    sys.path.insert(0, _PROG_DIR)


# Wave 23 (v0.119.55) — every L1-L23 doc is hard-required. The
# soft-prefix WARN tier and the
# `extraction_evidence_schema_alternative` waiver are gone; the
# legacy waiver is now actively forbidden by
# `phase1_no_waivers_used_check`.
_REQUIRED_PREFIXES = (
    "L1_", "L2_", "L3_", "L4_", "L5_", "L6_", "L7_",
    "L8_", "L9_", "L10_", "L11_", "L12_", "L13_",
)


def _classify(name: str) -> str | None:
    """Return 'required'|None for a given L*.json basename.

    Wave 23 collapses the previous 'required'|'soft'|None tri-state
    into 'required'|None: every L1-L23 doc that exists is hard-
    required.
    """
    for pref in _REQUIRED_PREFIXES:
        if name.startswith(pref):
            return "required"
    return None


def _validate_evidence(value) -> tuple[bool, str, list[str]]:
    """Return (ok, reason, structured_details).

    v1.6.94 (issue #25 Bug 3): in addition to the legacy single-line
    ``reason`` (preserved for backward compatibility), return a list
    of structured per-field detail lines using the field-agent's
    requested taxonomy:

        ``field <field_name> shape mismatch: expected <X>, got <Y>``
        ``field <field_name> missing`` (required, non-empty)
        ``field <field_name> empty`` (required, non-empty)

    Each detail line is unprefixed; the caller wraps it with the
    ``[L<NN>_<NAME>]`` doc marker.
    """
    details: list[str] = []
    if not isinstance(value, dict):
        msg = (f"top-level extraction_evidence must be a dict, "
               f"got {type(value).__name__}")
        details.append(
            f"field extraction_evidence shape mismatch: "
            f"expected dict, got {type(value).__name__}"
        )
        return False, msg, details
    if not value:
        # Empty dict allowed (covers L13 stub case where lab data
        # is tbd:true but field still present).
        return True, "", details
    ok = True
    first_reason = ""
    for src, entries in value.items():
        if not isinstance(src, str):
            r = f"key {src!r} is not a string"
            details.append(
                f"field extraction_evidence shape mismatch: "
                f"expected str key, got {type(src).__name__}"
            )
            if ok:
                ok, first_reason = False, r
            continue
        if not isinstance(entries, list):
            r = (f"value for {src!r} is {type(entries).__name__}, "
                 f"expected list")
            details.append(
                f"field extraction_evidence[{src!r}] shape mismatch: "
                f"expected list, got {type(entries).__name__}"
            )
            if ok:
                ok, first_reason = False, r
            continue
        for i, e in enumerate(entries):
            if isinstance(e, str):
                continue
            if isinstance(e, dict):
                if "literal" not in e:
                    r = (f"{src!r} entry [{i}] missing required "
                         f"`literal` key")
                    details.append(
                        f"field extraction_evidence[{src!r}][{i}].literal "
                        f"missing (required, non-empty)"
                    )
                    if ok:
                        ok, first_reason = False, r
                    continue
                if not isinstance(e["literal"], str):
                    r = (f"{src!r} entry [{i}] `literal` must be a "
                         f"string, got {type(e['literal']).__name__}")
                    details.append(
                        f"field extraction_evidence[{src!r}][{i}].literal "
                        f"shape mismatch: expected str, "
                        f"got {type(e['literal']).__name__}"
                    )
                    if ok:
                        ok, first_reason = False, r
                    continue
                if "label" in e and not isinstance(e["label"], str):
                    r = (f"{src!r} entry [{i}] `label` must be a "
                         f"string, got {type(e['label']).__name__}")
                    details.append(
                        f"field extraction_evidence[{src!r}][{i}].label "
                        f"shape mismatch: expected str, "
                        f"got {type(e['label']).__name__}"
                    )
                    if ok:
                        ok, first_reason = False, r
                continue
            r = (f"{src!r} entry [{i}] is {type(e).__name__}, "
                 "expected string or dict with `literal`")
            details.append(
                f"field extraction_evidence[{src!r}][{i}] shape mismatch: "
                f"expected str or dict, got {type(e).__name__}"
            )
            if ok:
                ok, first_reason = False, r
    return ok, first_reason, details


_VENDOR_DOC_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xlsx", ".pptx", ".txt", ".csv",
    ".json", ".xml", ".md",
}
_VENDOR_DOC_NAME_BLACKLIST = {
    "readme.md", ".gitkeep", ".keep", ".placeholder",
}


def _vendor_docs_in_input(project: Path) -> list[Path]:
    """List the candidate vendor-doc files under input/docs/.

    Used by `_is_genuine_path_a` to verify a Path-A claim. README and
    placeholder files don't count.
    """
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return []
    out: list[Path] = []
    for f in docs_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in _VENDOR_DOC_SUFFIXES:
            continue
        if f.name.lower() in _VENDOR_DOC_NAME_BLACKLIST:
            continue
        out.append(f)
    return out


def _is_genuine_path_a(project: Path) -> tuple[bool, str]:
    """Return (is_genuine, fail_reason).

    Wave 42 (v0.119.70) / MF2 — fault-injection hardening.

    A facts.yaml that sets `phase1_skipped_path_a: true` only counts
    as a genuine Path A flow when input/docs/ is effectively empty
    (no vendor docs).  If the marker is set but vendor docs are
    present, the project mis-claims Path A (likely fault-injection)
    and the gate must FAIL with a clear reason instead of SKIPping.

    Returns:
        (True,  "")                -> genuine Path A — caller should SKIP
        (False, "")                -> marker absent — caller proceeds
        (False, "<fail message>")  -> marker present but contradicted by
                                       input/docs/ — caller must FAIL
    """
    # Lazy import to avoid a hard dep when this helper isn't invoked.
    try:
        from _facts_yaml import (  # type: ignore
            read_facts_yaml,
            get_top_level_truthy,
        )
    except Exception:
        return False, ""
    facts = read_facts_yaml(project)
    flag = get_top_level_truthy(facts, "phase1_skipped_path_a", default=False)
    if not flag:
        return False, ""
    vendor_docs = _vendor_docs_in_input(project)
    if vendor_docs:
        rels = []
        for vd in vendor_docs[:5]:
            try:
                rels.append(str(vd.relative_to(project)))
            except ValueError:
                rels.append(vd.name)
        more = (
            f" (+{len(vendor_docs) - 5} more)"
            if len(vendor_docs) > 5 else ""
        )
        return False, (
            f"FAIL — Wave 42 / MF2: facts.yaml claims "
            f"`phase1_skipped_path_a: true` (Path A flow), but "
            f"input/docs/ contains {len(vendor_docs)} vendor "
            f"file(s){more}: {', '.join(rels)}. "
            f"Path A means no vendor docs — Phase 1 (doc-extraction) is mandatory "
            f"when vendor docs are present. Either remove the "
            f"facts.yaml marker (this is Path B) or remove the "
            f"vendor docs (this is genuinely Path A)."
        )
    return True, ""


def _path_a_skip_marker(project: Path) -> bool:
    """Back-compat shim — returns True iff Path A is genuine.

    Old callers used substring grep; Wave 42 redirects them through
    the YAML-parser-backed `_is_genuine_path_a` helper so a
    fault-injected marker no longer escapes the cross-check.
    """
    is_genuine, _ = _is_genuine_path_a(project)
    return is_genuine


def _check(project: Path) -> tuple[int, list[str]]:
    """Return (exit_code, message_lines)."""
    if not project.is_dir():
        return 2, [f"FAIL — project dir not found: {project}"]

    # Wave 30 (v0.119.62) — fail-closed when vendor input docs exist
    # but Phase 1 (doc-extraction) was never run. The previous silent-skip path let
    # 35th-attempt projects with input/docs/ but no generated_docs/
    # pass this gate.
    #
    # Wave 36 (v0.119.68) — relax to a triple-AND condition: only
    # FAIL when (a) generated_docs/ empty/missing AND (b) input/docs/
    # has vendor docs AND (c) facts.yaml does NOT mark a Path A skip.
    # Path A (prompt-driven) flows produce facts.yaml with
    # `phase1_skipped_path_a: true` and skip Phase 1 (doc-extraction) entirely.
    in_dir = project / "input" / "docs"
    has_input_docs = in_dir.is_dir() and any(in_dir.iterdir())
    is_path_a, path_a_fail = _is_genuine_path_a(project)
    if path_a_fail:
        # Wave 42 / MF2 — facts.yaml lies about Path A.
        return 1, [path_a_fail]
    # has_input_docs collapses to False when Path A is in use.
    has_input_docs = has_input_docs and not is_path_a

    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        if has_input_docs:
            return 1, [
                "FAIL — Wave 30 (v0.119.62): generated_docs/ absent "
                "but input/docs/ has vendor docs. Phase 1 (doc-extraction) was not "
                "run; required L1-L23 docs cannot carry "
                "extraction_evidence. NO waiver allowed."
            ]
        return 0, [
            "extraction_evidence_schema_check: SKIP — "
            "generated_docs/ absent and no input/docs/ "
            "(bare-skeleton project)"
        ]

    files = sorted(gd.glob("*.json"))
    if not files:
        if has_input_docs:
            return 1, [
                "FAIL — Wave 30 (v0.119.62): generated_docs/ has no "
                "*.json files but input/docs/ has vendor docs. Phase "
                "2a was not run. NO waiver allowed."
            ]
        return 0, [
            "extraction_evidence_schema_check: SKIP — "
            "generated_docs/ has no *.json files and no input/docs/ "
            "(bare-skeleton project)"
        ]

    # Wave 23 (v0.119.55) — every L1-L23 is hard-required; no WARN
    # tier; no waiver path.
    # v1.6.94 (issue #25 Bug 3) — every failure is now emitted as a
    # structured per-doc per-field marker line of shape:
    #   [L<NN>_<NAME>] field <name> missing (required, non-empty)
    #   [L<NN>_<NAME>] field <name> shape mismatch: expected <X>, got <Y>
    #   [L<NN>_<NAME>] field <name> empty (required, non-empty)
    # so the field agent can file targeted emitter fixes. The top-level
    # PASS / FAIL marker line and exit code stay machine-readable for
    # the runner consumer.
    failures: list[str] = []          # legacy single-line summaries
    detail_lines: list[str] = []      # v1.6.94 verbose per-field markers
    checked = 0
    passed = 0

    for f in files:
        cls = _classify(f.name)
        if cls is None:
            continue
        checked += 1
        doc_tag = f"[{f.stem}]"  # e.g. [L11_OTP_CONTENT]
        try:
            data = json.loads(f.read_text())
        except Exception as e:
            failures.append(f"{f.name}: JSON unparseable ({e})")
            detail_lines.append(
                f"{doc_tag} field <root> shape mismatch: "
                f"expected valid JSON, got parse error ({e})"
            )
            continue
        if not isinstance(data, dict):
            failures.append(f"{f.name}: top-level not an object")
            detail_lines.append(
                f"{doc_tag} field <root> shape mismatch: "
                f"expected dict, got {type(data).__name__}"
            )
            continue
        if "extraction_evidence" not in data:
            failures.append(
                f"{f.name}: missing top-level `extraction_evidence` field")
            detail_lines.append(
                f"{doc_tag} field extraction_evidence missing "
                f"(required, non-empty)"
            )
            continue
        ok, reason, struct_details = _validate_evidence(
            data["extraction_evidence"])
        if not ok:
            failures.append(
                f"{f.name}: malformed `extraction_evidence` — {reason}")
            for d in struct_details:
                detail_lines.append(f"{doc_tag} {d}")
            continue
        passed += 1

    out: list[str] = []
    out.append(
        f"extraction_evidence_schema_check: checked {checked} L doc(s), "
        f"{passed} PASS, {len(failures)} FAIL")

    if failures:
        out.append("")
        out.append("FAIL — required L docs lack schema-valid "
                   "`extraction_evidence` (Wave 23: NO waiver allowed):")
        for fmsg in failures:
            out.append(f"  - {fmsg}")
        # v1.6.94 (issue #25 Bug 3) — emit per-doc per-field structured
        # marker lines so the field agent can file targeted emitter
        # fixes without having to grep the JSON.
        if detail_lines:
            out.append("")
            out.append("details:")
            for d in detail_lines:
                out.append(f"  {d}")
        out.append("")
        out.append(
            "To resolve, in each L*.json above, add top-level "
            "`extraction_evidence` of shape "
            "{<src_doc>: [{literal, label}, ...]}. If the literal "
            "cannot be auto-discovered, add patterns to "
            "`<project>/extraction_patterns.json`. Do NOT add a "
            "waiver — there is no waiver for this gate.")
        return 1, out

    if checked == 0:
        # Wave 30 (v0.119.62) — fail-closed when vendor input docs
        # exist but no L1-L23 doc was produced.
        if has_input_docs:
            out.insert(
                0,
                "FAIL — Wave 30 (v0.119.62): no L*.json matched "
                "required L1-L23 prefixes but input/docs/ has vendor "
                "docs. Phase 1 (doc-extraction) generators were not run. NO waiver "
                "allowed.")
            return 1, out
        out.insert(
            0,
            "extraction_evidence_schema_check: SKIP — no L*.json "
            "files matched required L1-L23 prefixes")
        return 0, out

    out.insert(0, "PASS — extraction_evidence schema valid for all "
                  "required L docs")
    return 0, out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: extraction_evidence_schema_check.py <project_dir>")
        return 2
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: extraction_evidence_schema_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    code, lines = _check(project)
    for ln in lines:
        print(ln)
    return code


if __name__ == "__main__":
    sys.exit(main())
