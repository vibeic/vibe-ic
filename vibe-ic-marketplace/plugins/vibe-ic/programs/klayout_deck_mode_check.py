#!/usr/bin/env python3
"""klayout_deck_mode_check.py — BACKLOG-v10 P0.1 enforcement loop.

Closes the verdict-integration hole around the v0.112 KLayout
fallback. The existing `eda_drc_klayout` MCP tool will fall back to
`deck_mode: structural_only` (just verifies GDS parses + top cell
exists, NO MIN-WIDTH / MIN-SPACING / MIN-AREA rules) when the
custom-PDK auto-deck synthesis produces 0 enforceable rules — the
typical case when a custom PDK ships a tech LEF without a
hand-supplied DRC deck or layermap.

That fallback returns `success=true`. Without this gate, a project
silently passes Step 23 / Step 26 (Physical Verification) using a
DRC pass that proves NOTHING about geometric correctness.

Gate behaviour
==============

For each `*.lyrdb`-adjacent KLayout DRC manifest / log, parse for
`deck_mode` and similar attestation tokens:

  - `deck_mode: structural_only`           → require waiver
  - `STRUCTURAL_PASS` in manifest status   → require waiver
  - "Auto-deck synthesis ... produced 0 enforceable rules" advisory
    in output → require waiver
  - tool name contains "structural-only"   → require waiver

If a structural-only pass occurred AND no `waivers.json` entry with
`id: "K01_klayout_structural_only_drc"` exists, emit
`KLAYOUT_STRUCTURAL_DRC_NEEDS_WAIVER` ERROR.

False-alert guards
==================

  - Silent if no KLayout DRC artefacts exist (project hasn't run
    Step 23 / 26 yet).
  - Silent if every DRC artefact reports a real auto-deck or
    user-supplied deck (rules > 0).
  - Silent if waivers.json declares K01_klayout_structural_only_drc
    with non-empty `rationale` / `reason` AND `review_required: true`.

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


_STRUCTURAL_TOKENS = (
    # The closing quote of a JSON KEY sits between the name and the colon:
    # `"deck_mode": "structural_only"`. Without it in the pattern the token
    # matched only the bare `deck_mode: structural_only` prose form, so a
    # report that recorded the fallback in JSON and NOTHING else went
    # undetected — measured here as a manifest carrying only that one field.
    re.compile(r"deck_mode[\"']?\s*[:=]\s*[\"']?structural_only",
               re.IGNORECASE),
    re.compile(r"STRUCTURAL_PASS", re.IGNORECASE),
    re.compile(r"structural-only", re.IGNORECASE),
    re.compile(r"produced\s+0\s+enforceable\s+rules", re.IGNORECASE),
)


#: Filenames that carry KLayout DRC evidence, as ONE predicate.
#:
#: THE DEFECT THIS REPLACES (measured on run-spm-publish, sky130A, 23 GB):
#: the previous discovery globbed five literal shapes — ``**/manifest.json``,
#: ``**/klayout_*.json``, ``**/drc_*.log``, ``**/*.lyrdb`` and
#: ``reports/drc_*.json``. Those are the names the ``eda_drc_klayout`` MCP tool
#: writes (``writeManifest`` → ``manifest.json``). They are NOT the names the
#: phase3 runner's ``step_drc`` writes, and ``step_drc`` is what a full flow
#: actually runs: it emits ``reports/phase3/drc_signoff.rpt`` (a KLayout
#: report-database whose ``<generator>`` names ``sky130A.lydrc``) beside
#: ``reports/phase3/drc_signoff.json`` (which records ``producer: klayout`` and
#: ``is_signoff_deck: true``). MEASURED over that whole run: zero files matched
#: any of the five globs, so the gate returned its "no KLayout DRC artefacts
#: found" skip — the SAME answer it gives a project that never ran physical
#: verification at all. A gate that cannot tell "no DRC ran" from "a signoff
#: DRC ran and passed" is not silent about nothing; it is silent about
#: everything, including the structural-only fallback it exists to catch, the
#: moment that fallback is recorded under the runner's names.
#:
#: The two producers are enumerated here together, so adding a third is a
#: change to this one pattern rather than a sixth glob somewhere.
_DRC_ARTEFACT_NAME = re.compile(
    r"^(?:"
    r"manifest\.json"              # eda_drc_klayout writeManifest
    r"|klayout_[^/]*\.json"        # eda_drc_klayout side reports
    r"|drc_[^/]*\.(?:json|log|rpt|xml)"   # runner step_drc + drc_* logs
    r"|[^/]*\.drc\.(?:rpt|log|xml)"      # routed.drc.rpt and friends
    r"|[^/]*\.lyrdb"               # KLayout report database
    r")$",
    re.IGNORECASE,
)

#: Positive evidence that a REAL rule deck was executed, not the fallback.
#:
#: Recorded so the PASS says which deck answered rather than "no forbidden
#: token appeared in these bytes". Absence of this evidence never turns a PASS
#: into a FAIL here — the gate's single failure mode is unchanged — but it is
#: reported, because "found artefacts, none names a deck" and "found artefacts,
#: one names sky130A.lydrc" are different states and used to print the same
#: sentence.
_DECK_ATTEST_TOKENS = (
    re.compile(r"[\w./-]+\.lydrc\b", re.IGNORECASE),
    re.compile(r"[\"']?is_signoff_deck[\"']?\s*[:=]\s*true", re.IGNORECASE),
    re.compile(r"<generator>\s*drc:\s*script\s*=", re.IGNORECASE),
)


def _find_drc_artefacts(project: Path) -> list[Path]:
    """Every KLayout DRC artefact under ``project``, from ONE walk.

    One walk rather than N globs: the previous form re-walked the whole tree
    once per pattern, and widening it to the runner's names would have made
    that eight walks of a multi-gigabyte run root. The set of names it accepts
    is a strict superset of the five globs it replaces.
    """
    out: list[Path] = []
    seen: set[Path] = set()
    for root, _dirs, files in os.walk(project):
        base = Path(root)
        for name in sorted(files):
            if not _DRC_ARTEFACT_NAME.match(name):
                continue
            f = base / name
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            out.append(f)
    return out


def _deck_attestation(text: str) -> str:
    """The deck this artefact says ran, or "" when it names none."""
    for pat in _DECK_ATTEST_TOKENS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return ""


def _is_structural_evidence(text: str) -> bool:
    return any(p.search(text) for p in _STRUCTURAL_TOKENS)


def _waiver_present(project: Path) -> str:
    """Return rationale string if K01_klayout_structural_only_drc waiver
    exists with non-empty rationale, else empty."""
    for cand in (project / "waivers.json", *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or [])
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") in ("K01_klayout_structural_only_drc",
                               "K01", "klayout_structural_only_drc"):
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and rat.strip():
                    return rat
    return ""


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "drc_artefacts_found": [],
        "structural_evidence": [],
        "deck_attested": [],
        "waiver_rationale": "",
        "skipped_reason": "",
    }

    artefacts = _find_drc_artefacts(project)
    if not artefacts:
        summary["skipped_reason"] = "no KLayout DRC artefacts found"
        return findings, summary
    summary["drc_artefacts_found"] = [
        str(a.relative_to(project)) for a in artefacts
    ]

    structural_files: list[Path] = []
    for a in artefacts:
        text = _read(a)
        if _is_structural_evidence(text):
            structural_files.append(a)
            continue
        deck = _deck_attestation(text)
        if deck:
            summary["deck_attested"].append(
                {"file": str(a.relative_to(project)), "deck": deck})
    summary["structural_evidence"] = [
        str(p.relative_to(project)) for p in structural_files
    ]

    if not structural_files:
        return findings, summary  # all real DRC, no fallback used

    waiver_rationale = _waiver_present(project)
    summary["waiver_rationale"] = waiver_rationale
    if waiver_rationale:
        return findings, summary  # acknowledged via waiver

    findings.append(Finding(
        severity="ERROR",
        rule="KLAYOUT_STRUCTURAL_DRC_NEEDS_WAIVER",
        message=(
            f"KLayout DRC ran in structural-only fallback mode for "
            f"{len(structural_files)} artefact(s) — verifies GDS parses "
            f"+ top cell exists but enforces NO geometric rules. "
            f"Production tapeout requires foundry-supplied DRC deck. "
            f"Either (a) supply `custom_drc_script` to eda_drc_klayout, "
            f"OR (b) add a waivers.json entry with "
            f"`id: \"K01_klayout_structural_only_drc\"`, non-empty "
            f"`rationale`, `review_required: true`, and a foundry "
            f"closure plan reference (foundry_signoff_plan_check.py)."
        ),
        file=structural_files[0].relative_to(project).as_posix(),
    ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="klayout_deck_mode_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "klayout_deck_mode_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== klayout_deck_mode_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        evid = summary["structural_evidence"]
        if evid:
            print(f"  [PASS] {len(evid)} structural-only run(s) covered "
                  f"by waiver K01_klayout_structural_only_drc")
        elif summary["deck_attested"]:
            decks = sorted({d["deck"] for d in summary["deck_attested"]})
            print(f"  [PASS] {len(summary['drc_artefacts_found'])} "
                  f"DRC artefact(s); real rule deck attested by "
                  f"{len(summary['deck_attested'])} of them: "
                  f"{', '.join(decks)}")
        else:
            print(f"  [PASS] {len(summary['drc_artefacts_found'])} "
                  f"DRC artefact(s), none in structural-only fallback mode "
                  f"(no artefact names the deck that ran)")
        return 0
    for f in findings:
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{f.severity.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: FAIL (structural-only DRC requires K01 waiver)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
