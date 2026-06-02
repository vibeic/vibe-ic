#!/usr/bin/env python3
"""analog_a6_block_pv_check.py — A6 deterministic gate
(Per-Block Physical Verification: DRC + LVS).

Verifies that EVERY analog block listed in
`phase3/analog/analog_block_list.json` has REAL, evidence-backed
per-block physical verification:

  * DRC: zero violations.  Read from one of (first match wins):
      - analog/<block>/drc.report   (Magic / KLayout text DRC report)
      - analog/<block>/*.drc.report / *.lyrdb (KLayout)
      - analog/<block>/drc_clean.flag  (must carry an explicit
        `violations: 0` / `count=0` line — a bare flag is NOT enough)
    PASS only when the parsed violation COUNT == 0.

  * LVS: a match.  Read from one of (first match wins):
      - analog/<block>/lvs.report   (Netgen / Calibre text LVS report)
      - analog/<block>/comp.json    (Netgen JSON comparison)
      - analog/<block>/lvs_match.flag  (must carry an explicit
        `match`/`lvs: match` verdict — a bare flag is NOT enough)
    PASS only when the report declares a MATCH.

Behaviour
---------
* SKIP (rc=2)  — there are genuinely NO analog blocks (block list
                  absent or empty).  Real non-applicability.
* WAIVED (rc=0) — `waivers.json` declares the step waived (evidence
                  + ticket).
* PASS (rc=0)  — every block has DRC violations == 0 AND LVS == match.
* FAIL (rc=1)  — any block has DRC violations > 0, LVS mismatch, OR a
                  missing/empty/garbage DRC or LVS artefact for a block
                  that EXISTS.  NO vacuous PASS on absence.

NO FABRICATION (hard rule): a block that has a directory but is missing
real DRC or LVS evidence is an HONEST FAIL — never a silent PASS.

Preserves the CLI contract:
    python3 analog_a6_block_pv_check.py <project_dir> [--json <out>]
                                                       [--block <name>]
                                                       [--step-label <l>]
module-level main(argv) -> int (0 PASS/SKIP/WAIVED, 1 FAIL, 2 bad dir).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_GATE_NAME = "analog_a6_block_pv_check"
_GATE_LABEL = "analog_block_pv"
_SKILL = "drc-fix + lvs-triage"

# ---------------------------------------------------------------------------
# block list (mirrors _analog_a_check_common.load_block_list — kept local so
# this gate has no hard dependency on import order).
# ---------------------------------------------------------------------------


def _load_block_list(project: Path) -> Optional[List[str]]:
    """Return declared analog block names, or None when no block-list
    file exists at all (digital-only / non-applicable)."""
    candidates = [
        project / "phase3" / "analog" / "analog_block_list.json",
        project / "analog" / "analog_block_list.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if not isinstance(blocks, list):
            return []
        out: List[str] = []
        for entry in blocks:
            if isinstance(entry, str) and entry:
                out.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("block")
                if isinstance(name, str) and name:
                    out.append(name)
        return out
    return None


def _block_dir(project: Path, block: str) -> Optional[Path]:
    """Return the on-disk per-block directory, preferring the
    v2-canonical phase3/analog/<block>/ tree, then the legacy
    analog/<block>/ tree. None when neither exists."""
    for cand in (project / "phase3" / "analog" / block,
                 project / "analog" / block):
        if cand.is_dir():
            return cand
    return None


# ---------------------------------------------------------------------------
# DRC parsing — return (violations:int|None, evidence:str).
#   violations is None when no parseable DRC evidence exists.
# ---------------------------------------------------------------------------

# Common "N violations / errors" phrasings emitted by Magic, KLayout,
# Calibre.  Chip-AGNOSTIC: matches the verb, not any IC/tool brand text.
_DRC_COUNT_RE = re.compile(
    r"(?:total\s+)?(?:drc\s+)?"
    r"(?:violation|error|geometr\w*\s+error)s?\s*[:=]?\s*(\d+)",
    re.IGNORECASE,
)
_DRC_ZERO_PHRASES = (
    "drc clean", "no drc violations", "0 drc errors", "no errors found",
    "drc passed", "violations: 0", "violations=0", "count: 0", "count=0",
    "0 violations", "0 errors",
)


def _parse_drc_count(text: str) -> Optional[int]:
    """Extract a DRC violation count from a DRC report's text.
    Returns the integer count, or None when no count phrase is found.
    A zero-phrase (e.g. 'DRC clean') resolves to 0."""
    low = text.lower()
    counts: List[int] = [int(m.group(1)) for m in _DRC_COUNT_RE.finditer(low)]
    if counts:
        # The worst (max) count is the conservative verdict: any
        # non-zero count anywhere in the report means NOT clean.
        return max(counts)
    if any(p in low for p in _DRC_ZERO_PHRASES):
        return 0
    return None


def _drc_violations(bdir: Path) -> Tuple[Optional[int], str]:
    """Per-block DRC verdict. Returns (count, evidence_rel).
    count is None when there is NO parseable DRC evidence."""
    # 1. Explicit DRC report files (richest evidence).
    report_globs = ["drc.report", "*.drc.report", "*.lyrdb",
                    "drc.rpt", "*.drc"]
    for pat in report_globs:
        for f in sorted(bdir.glob(pat)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            count = _parse_drc_count(text)
            if count is not None:
                return count, f.name
            # Report present but unparseable → treat as no-evidence so
            # the block FAILs honestly (we won't guess clean).
    # 2. drc_clean.flag — but only with an explicit zero-count line.
    flag = bdir / "drc_clean.flag"
    if flag.is_file():
        try:
            text = flag.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        count = _parse_drc_count(text)
        if count is not None:
            return count, flag.name
        # Bare flag with no count line → NOT acceptable evidence.
    return None, ""


# ---------------------------------------------------------------------------
# LVS parsing — return (matched:bool|None, evidence:str).
#   matched is None when no parseable LVS evidence exists.
# ---------------------------------------------------------------------------

_LVS_MATCH_PHRASES = (
    "circuits match uniquely", "netlists match", "lvs match",
    "lvs: match", "lvs passed", "match: true", "match=true",
    "result: match", "the netlists match",
)
_LVS_MISMATCH_PHRASES = (
    "circuits do not match", "netlists do not match", "lvs mismatch",
    "lvs: mismatch", "lvs failed", "match: false", "match=false",
    "result: mismatch", "property errors", "incorrect", "unmatched",
)


def _parse_lvs_match(text: str) -> Optional[bool]:
    """Return True (match), False (mismatch), or None (no verdict)."""
    low = text.lower()
    # Mismatch phrases win over match phrases (a report that mentions
    # both 'match' and 'do not match' is a mismatch).
    has_mismatch = any(p in low for p in _LVS_MISMATCH_PHRASES)
    has_match = any(p in low for p in _LVS_MATCH_PHRASES)
    if has_mismatch:
        return False
    if has_match:
        return True
    return None


def _lvs_match(bdir: Path) -> Tuple[Optional[bool], str]:
    """Per-block LVS verdict. Returns (matched, evidence_rel).
    matched is None when there is NO parseable LVS evidence."""
    # 1. Netgen JSON comparison (comp.json) — structured verdict.
    comp = bdir / "comp.json"
    if comp.is_file():
        try:
            data = json.loads(comp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict):
            # Netgen-style: {"result": "match"|"mismatch"} or a count of
            # mismatched elements.
            res = str(data.get("result", "")).lower()
            if res in ("match", "matched", "pass"):
                return True, comp.name
            if res in ("mismatch", "fail", "failed"):
                return False, comp.name
            mismatches = data.get("mismatches")
            if isinstance(mismatches, int):
                return (mismatches == 0), comp.name
    # 2. Explicit LVS text report.
    for pat in ["lvs.report", "*.lvs.report", "lvs.rpt", "comp.out",
                "*.lvs"]:
        for f in sorted(bdir.glob(pat)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text.strip():
                continue
            verdict = _parse_lvs_match(text)
            if verdict is not None:
                return verdict, f.name
    # 3. lvs_match.flag — but only with an explicit match verdict line.
    flag = bdir / "lvs_match.flag"
    if flag.is_file():
        try:
            text = flag.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        verdict = _parse_lvs_match(text)
        if verdict is not None:
            return verdict, flag.name
        # Bare flag with no verdict line → NOT acceptable evidence.
    return None, ""


# ---------------------------------------------------------------------------
# per-block audit
# ---------------------------------------------------------------------------


def _check_block(project: Path, block: str) -> Tuple[str, List[dict]]:
    """Return (status, findings) where status is PASS or FAIL.
    A block whose directory exists but lacks real DRC/LVS evidence is
    an honest FAIL (never a vacuous PASS)."""
    findings: List[dict] = []
    bdir = _block_dir(project, block)
    if bdir is None:
        findings.append({
            "block": block, "rule": "A6_PV_BLOCK_DIR_MISSING",
            "rel_path": f"analog/{block}/",
            "detail": ("no phase3/analog/<block>/ nor analog/<block>/ "
                       "directory; A5 layout did not run for this block"),
        })
        return "FAIL", findings

    rel = str(bdir.relative_to(project))

    drc_count, drc_ev = _drc_violations(bdir)
    if drc_count is None:
        findings.append({
            "block": block, "rule": "A6_PV_DRC_NO_EVIDENCE",
            "rel_path": f"{rel}/drc.report|drc_clean.flag",
            "detail": ("no parseable DRC result (need drc.report with a "
                       "violation count, or drc_clean.flag carrying an "
                       "explicit `violations: 0` line)"),
        })
    elif drc_count > 0:
        findings.append({
            "block": block, "rule": "A6_PV_DRC_VIOLATIONS",
            "rel_path": f"{rel}/{drc_ev}",
            "detail": f"DRC reports {drc_count} violation(s) (must be 0)",
        })

    lvs_ok, lvs_ev = _lvs_match(bdir)
    if lvs_ok is None:
        findings.append({
            "block": block, "rule": "A6_PV_LVS_NO_EVIDENCE",
            "rel_path": f"{rel}/lvs.report|comp.json|lvs_match.flag",
            "detail": ("no parseable LVS result (need lvs.report / "
                       "comp.json with a match verdict, or lvs_match.flag "
                       "carrying an explicit `match` line)"),
        })
    elif lvs_ok is False:
        findings.append({
            "block": block, "rule": "A6_PV_LVS_MISMATCH",
            "rel_path": f"{rel}/{lvs_ev}",
            "detail": "LVS reports a mismatch (must be a match)",
        })

    return ("FAIL" if findings else "PASS"), findings


# ---------------------------------------------------------------------------
# waivers
# ---------------------------------------------------------------------------


def _load_waivers(project: Path) -> list:
    for p in (project / "phase3" / "analog" / "waivers.json",
              project / "analog" / "waivers.json",
              project / "waivers.json"):
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            return d.get("waived_steps") or d.get("analog_waivers") or []
    return []


def _step_waived(project: Path, step_label: str):
    for w in _load_waivers(project):
        if not isinstance(w, dict):
            continue
        sid = str(w.get("id", "") or w.get("step", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or (step_label and step_label in str(ticket)):
            return w
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _write(json_path, report) -> None:
    if not json_path:
        return
    out = Path(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog=_GATE_NAME, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--block", default=None,
                        help="restrict check to a single block (used by "
                             "analog_one_shot_runner)")
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    blocks_all = _load_block_list(project)

    # SKIP (rc=2) only when genuinely no analog blocks exist.
    if blocks_all is None or (not blocks_all and not args.block):
        report = {
            "gate": _GATE_NAME,
            "verdict": "SKIP",
            "step_label": args.step_label,
            "reason": ("no analog blocks declared (block list absent or "
                       "empty); per-block PV non-applicable"),
            "blocks_checked": 0,
            "blocks_pass": 0,
            "blocks_fail": 0,
            "findings": [],
        }
        _write(args.json, report)
        print(f"=== {_GATE_NAME} ({project.name}) ===")
        print(f"  verdict: SKIP (no analog blocks)")
        return 2

    blocks = [args.block] if args.block else blocks_all

    # Step-level waiver (evidence + ticket) short-circuits to WAIVED.
    waiver = _step_waived(project, args.step_label)

    findings: List[dict] = []
    blocks_pass = 0
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
        else:
            findings.extend(fs)

    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_fail": len({f["block"] for f in findings}),
    }

    if findings and waiver:
        verdict, rc = "WAIVED", 0
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": waiver,
            **summary,
            "findings": [{
                "severity": "WAIVED", "rule": "STEP_WAIVED",
                "message": (f"waiver={waiver.get('ticket', '?')}: "
                            f"{waiver.get('reason', '?')}"),
            }],
            "suppressed_findings": findings,
        }
    elif findings:
        verdict, rc = "FAIL", 1
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": None,
            **summary, "findings": findings,
        }
    else:
        verdict, rc = "PASS", 0
        report = {
            "gate": _GATE_NAME, "verdict": verdict,
            "step_label": args.step_label, "waiver": None,
            **summary, "findings": [],
        }

    _write(args.json, report)
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict} "
          f"({blocks_pass}/{len(blocks)} block(s) DRC-0 + LVS-match)")
    if verdict == "FAIL":
        for f in findings[:8]:
            print(f"  [{f.get('block', '?')}] {f.get('rule', '?')}: "
                  f"{f.get('detail', '')}", file=sys.stderr)
        if len(findings) > 8:
            print(f"  ... and {len(findings) - 8} more", file=sys.stderr)
    if waiver:
        print(f"  waiver:  {waiver.get('ticket', '?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
