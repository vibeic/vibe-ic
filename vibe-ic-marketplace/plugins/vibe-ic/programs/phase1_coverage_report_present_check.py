#!/usr/bin/env python3
"""
phase1_coverage_report_present_check.py — gate (BACKLOG-v13 Wave 5).

Wave 23 (v0.119.55) — extraction coverage is non-waivable. 100% is
the HARD acceptance threshold for Phase 1 (doc-extraction). If a literal cannot be
extracted by the auto-discovery patterns, the agent MUST add a
project-level `extraction_patterns.json` to teach the extractor how
to find it. There is NO "we'll skip this doc" option. The legacy
`phase1_coverage_below_threshold_intentional` waiver has been
removed from this gate.

Why this gate exists
====================
Wave 4 added `phase1_coverage_report_gen.py` which always emits
`<project>/reports/extraction_coverage_report.{md,json}` at end-of-
Phase 1, but the report was never required as a wired gate. A fresh
agent could skip the report-gen invocation entirely and still claim
Phase 1 (doc-extraction) complete. Wave 5 closes that gap: this gate verifies the
report files exist AND the recorded overall coverage percentage is
≥ 95%, the same threshold LL-38 enforces.

Behavior
========
- If `<project>/reports/extraction_coverage_report.md` is missing
  OR `<project>/reports/extraction_coverage_report.json` is missing,
  the gate FAILs with verdict `report_missing` (unless silent-skip
  conditions below apply).
- If both files exist, the gate parses the JSON and reads
  `overall.pct`. Wave 23 (v0.119.55): if pct < 100.0 → HARD FAIL
  with the per-doc breakdown. If pct == 100.0 → PASS.
- Silent-skip when there is no Phase 1 (doc-extraction) output yet (no
  `generated_docs/` AND no `extraction_patterns.json`). This avoids
  false alerts on bare-skeleton projects where Phase 1 (doc-extraction) has not
  been attempted.
- NO WAIVER. The legacy waiver
  `phase1_coverage_below_threshold_intentional` is no longer
  honored; `phase1_no_waivers_used_check` will FAIL if it is even
  present in `<project>/waivers.json`.

Usage
-----
python3 phase1_coverage_report_present_check.py <project_dir>

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

# v1.7.72 — for #499 defect 4. The coverage ratio is computed over
# documents that EXTRACTED, so it cannot see one that did not.
import _input_ingest as _ingest  # noqa: E402


# Wave 23 (v0.119.55) — threshold raised from 95.0 to 100.0; no
# waiver. The legacy `phase1_coverage_below_threshold_intentional`
# key is now actively forbidden by `phase1_no_waivers_used_check`.
DEFAULT_THRESHOLD = 100.0


def _phase1_attempted(project: Path) -> bool:
    """Return True if Phase 1 (doc-extraction) appears to have been attempted.

    Heuristic: either generated_docs/ has *.json files OR an explicit
    extraction_patterns.json exists (project root or under input/).
    """
    gd = _pl.generated_docs_dir(project)
    if gd.is_dir() and any(gd.glob("*.json")):
        return True
    for cand in (_pl.phase1_extraction_patterns_file(project),
                 project / "input" / "extraction_patterns.json"):
        if cand.is_file():
            return True
    return False


def _has_input_docs(project: Path) -> bool:
    in_dir = project / "input" / "docs"
    if not in_dir.is_dir():
        return False
    try:
        return any(in_dir.iterdir())
    except Exception:
        return False


_VENDOR_DOC_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xlsx", ".pptx", ".txt", ".csv",
    ".json", ".xml", ".md",
}
_VENDOR_DOC_NAME_BLACKLIST = {
    "readme.md", ".gitkeep", ".keep", ".placeholder",
}


def _vendor_docs_in_input(project: Path) -> list[Path]:
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
    """Wave 42 (v0.119.70) / MF2 — return (is_genuine, fail_reason).

    A `phase1_skipped_path_a: true` marker only counts when no
    vendor docs are present in input/docs/.  See the matching helper
    in extraction_evidence_schema_check.py for the rationale.
    """
    try:
        from _facts_yaml import (  # type: ignore
            read_facts_yaml,
            get_top_level_truthy,
        )
    except Exception:
        return False, ""
    facts = read_facts_yaml(project)
    flag = get_top_level_truthy(
        facts, "phase1_skipped_path_a", default=False)
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
            f"file(s){more}: {', '.join(rels)}. Path A means no "
            f"vendor docs — Phase 1 (doc-extraction) coverage report is mandatory "
            f"when vendor docs are present."
        )
    return True, ""


def _path_a_skip_marker(project: Path) -> bool:
    is_genuine, _ = _is_genuine_path_a(project)
    return is_genuine


def _check(project: Path) -> tuple[int, str]:
    """Return (exit_code, message). exit 0 PASS / skip / waived,
    1 FAIL, 2 input error."""
    if not project.is_dir():
        return 2, f"FAIL — project dir not found: {project}"

    # Wave 30 (v0.119.62) — fail-closed when vendor input docs exist
    # but the agent never attempted Phase 1 (doc-extraction). Silent-skip remains only
    # for bare-skeleton projects with no input/docs/ at all.
    #
    # Wave 36 (v0.119.68) — Path A (prompt-driven) flows mark
    # `phase1_skipped_path_a: true` in facts.yaml; those are
    # silent-skip even when vendor input docs are present.
    is_path_a, path_a_fail = _is_genuine_path_a(project)
    if path_a_fail:
        # Wave 42 / MF2 — facts.yaml claims Path A but vendor docs exist.
        return 1, path_a_fail
    if not _phase1_attempted(project):
        if _has_input_docs(project) and not is_path_a:
            return 1, (
                "FAIL — Wave 30 (v0.119.62): Phase 1 (doc-extraction) coverage report "
                "not generated — agent must run phase1-orchestrate "
                "skill. input/docs/ contains vendor docs but neither "
                "generated_docs/ nor extraction_patterns.json exists. "
                "NO waiver allowed."
            )
        if is_path_a:
            return 0, (
                "phase1_coverage_report_present_check: SKIP — "
                "facts.yaml marks `phase1_skipped_path_a: true` "
                "(Wave 36 Path A flow)")
        return 0, ("phase1_coverage_report_present_check: SKIP — "
                   "Phase 1 (doc-extraction) not attempted and no input/docs/ "
                   "(bare-skeleton project)")

    md = _pl.report_path(project, "extraction_coverage_report.md")
    js = _pl.report_path(project, "extraction_coverage_report.json")

    if not md.is_file() or not js.is_file():
        # Wave 23 (v0.119.55) — HARD FAIL, no waiver path.
        missing = []
        if not md.is_file():
            missing.append(str(md))
        if not js.is_file():
            missing.append(str(js))
        return 1, (
            "FAIL — Phase 1 (doc-extraction) coverage report missing: "
            + ", ".join(missing)
            + ". Run: python3 plugins/vibe-ic/programs/"
              "phase1_coverage_report_gen.py <project>. "
              "Do NOT add a waiver — there is no waiver for this gate."
        )

    try:
        report = json.loads(js.read_text())
    except Exception as e:
        return 1, f"FAIL — extraction_coverage_report.json unparseable: {e}"

    overall = report.get("overall") or {}
    pct = overall.get("pct")
    hit = overall.get("hit")
    total = overall.get("total")

    # v1.7.72 — for #499 defect 4. This gate demands 100% coverage, but
    # the ratio it reads is built ONLY from documents that extracted:
    # a document the ingester could not render contributes to neither
    # numerator nor denominator, so it cannot lower the number. Measured
    # on a real design: `254/254 = 100.0%` with a 21 KB ground-truth
    # document contributing nothing, and this gate PASSed it.
    #
    # A converter gap is checked BEFORE the ratio, because no percentage
    # computed over the documents that survived can speak for the one
    # that did not. Only the converter-gap subset blocks — a decoder
    # missing from this particular machine is disclosed by the report
    # but is not the plugin's defect and must not hard-fail a user's run
    # with no waiver.
    gaps = _ingest.converter_gap_documents(project)
    if gaps:
        listed = "\n".join(f"  - {g['path']}: {g['reason']}"
                           for g in gaps[:8])
        return 1, (
            f"FAIL — Phase 1 (doc-extraction) left {len(gaps)} staged "
            f"document(s) UNREAD: the ingester has no working converter "
            f"for them, so their content reached no L doc and the "
            f"coverage percentage below was computed without them "
            f"(pct={pct}).\n{listed}\n"
            f"  A coverage figure that cannot notice missing input is "
            f"not measuring coverage of the input. Add a converter "
            f"branch in phase1_doc_one_shot_runner.extract_one() — do "
            f"NOT waive; there is no waiver for this gate."
        )

    if pct is None or total in (None, 0):
        # Report exists but no patterns/L docs were available — treat
        # as silent skip so we don't penalize empty-pattern projects.
        return 0, (
            "phase1_coverage_report_present_check: SKIP — "
            "report present but coverage not measured "
            f"(hit={hit}, total={total})"
        )

    try:
        pct_f = float(pct)
    except (TypeError, ValueError):
        return 1, f"FAIL — overall.pct not numeric: {pct!r}"

    if pct_f >= DEFAULT_THRESHOLD:
        return 0, (
            f"phase1_coverage_report_present_check: PASS — "
            f"{hit}/{total} = {pct_f}% (== {DEFAULT_THRESHOLD}%)"
        )

    # Wave 23 (v0.119.55) — HARD FAIL with per-doc breakdown. No waiver.
    per_doc = report.get("per_doc") or []
    breakdown_lines = []
    for d in per_doc:
        if d.get("pct", 100) < DEFAULT_THRESHOLD:
            breakdown_lines.append(
                f"  - {d.get('doc')}: "
                f"{d.get('hit')}/{d.get('total')} = "
                f"{d.get('pct')}%"
            )
    breakdown = "\n".join(breakdown_lines) or "  (none below threshold)"
    return 1, (
        f"FAIL — Phase 1 (doc-extraction) coverage {pct_f}% < {DEFAULT_THRESHOLD}% "
        f"(Wave 23: 100% required, NO waiver allowed). "
        f"Per-doc gaps:\n{breakdown}\n"
        f"To resolve, add patterns to `<project>/extraction_patterns.json` "
        f"so Phase 1 (doc-extraction) generators emit every input-doc literal into the "
        f"corresponding L*.json. Do NOT add a waiver — there is no "
        f"waiver for this gate."
    )


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: phase1_coverage_report_present_check.py <project_dir>")
        return 2
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: phase1_coverage_report_present_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    code, msg = _check(project)
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
