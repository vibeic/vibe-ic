#!/usr/bin/env python3
"""cross_design_identity_check.py — cross-design byte-identity gate
(ORGANIC-20260606 #454).

The 4-IC campaign's canned cross-design reports (coverage / CDC / PERC
memo / handoff members byte-identical across DIFFERENT chips) were only
caught by a MANUAL md5 sweep. #436 fixed that day's emitters; this gate
makes the recurrence class impossible to ship silently: given N project
dirs, any report-class artifact that is byte-identical across two or
more DIFFERENT designs is an ERROR — unless its basename is on the
verdict-wrapper ALLOWLIST (a wrapper may legitimately be self-identical
when the evidence it points to differs per design).

What is scanned (report classes — outputs that should be per-design):
  reports/**            (all emitted reports/manifests)
  phase3/stage4/foundry_handoff/**
  phase2/stage1/sim_full_stack/results.json, coverage manifests

Exempt by construction:
  * 0-byte files (other gates own those), directories
  * files under input/ / inputs/ / pdk/ (shared inputs are expected
    to be identical)
  * allowlisted wrapper basenames (--allow, comma-separated; each must
    carry a path-shaped `evidence`/`source` pointer whose TARGET
    differs per design — a wrapper without a differing target is NOT
    exempt)

Exit codes: 0 clean, 1 cross-design identity found, 2 fewer than two
project dirs (nothing to compare).
chip-AGNOSTIC: relative-path + content-hash comparison only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_SCAN_GLOBS = (
    "reports/**/*",
    "phase3/stage4/foundry_handoff/**/*",
    "phase2/stage1/sim_full_stack/*.json",
)
_INPUT_TOKENS = ("/input/", "/inputs/", "/pdk/", "/vendor_ref/")

# ORGANIC-20260606 #484 (MEDIUM) — STRICT named honest-N/A exemption.
#
# A *verdict-only* manifest whose verdict is an explicit skip / not-applicable
# token carries NO per-design substance — two designs that both honestly
# skipped the same gate emit byte-identical N/A shapes. Those are NOT canned
# cross-design reports. This exemption (opt-in via --allow-honest-na) lets
# such honest shapes pass WITHOUT ever exempting a real PASS/FAIL report:
#   * the verdict field MUST be one of the explicit skip/N-A tokens below;
#   * a PASS / FAIL / PASS_WITH_* / *_PASS verdict is NEVER exempt;
#   * the file must be verdict-only — it must NOT carry any substantive
#     evidence key (scenarios_covered with entries, per_vector PASS rows,
#     vectors_passed>0, a non-empty findings/violations list, …). A report
#     with real per-design substance that happens to be byte-identical is a
#     genuine cross-design-identity violation and stays flagged.
_HONEST_NA_VERDICTS = frozenset({
    "SKIP", "SKIPPED", "SKIPPED-CONDITION", "SKIPPED_CONDITION",
    "N/A", "NA", "NOT_APPLICABLE", "NOT-APPLICABLE",
    "PENDING", "PENDING_FOUNDRY", "SKELETON_EMITTED",
})
# Keys whose non-empty presence proves the report carries real substance,
# so it can NEVER ride the honest-N/A exemption even with a skip-ish verdict.
_SUBSTANCE_KEYS = (
    "scenarios_covered", "per_vector", "findings", "violations",
    "vectors_passed", "passes", "checks",
)


def _is_honest_na_verdict_only(fp: Path) -> bool:
    """True iff `fp` is a verdict-only JSON manifest whose verdict is an
    explicit skip / N-A token AND which carries no substantive per-design
    evidence (so a byte-identical copy across designs is honest, not canned).

    A PASS / FAIL / PASS_WITH_* verdict is NEVER honest-N/A. Any non-empty
    substance key disqualifies the exemption. Non-JSON / list / parse-error
    files are NOT exempt. chip-AGNOSTIC."""
    try:
        d = json.loads(fp.read_text(errors="replace"))
    except (OSError, ValueError):
        return False
    if not isinstance(d, dict):
        return False
    verdict = d.get("verdict") or d.get("status")
    if not isinstance(verdict, str):
        return False
    v = verdict.strip().upper()
    # Hard guard: a PASS/FAIL-bearing verdict is never honest-N/A — this is
    # what keeps a real canned PASS/FAIL report flagged.
    if v in ("PASS", "FAIL") or v.startswith("PASS") or v.endswith("PASS") \
            or "FAIL" in v:
        return False
    if v not in _HONEST_NA_VERDICTS:
        return False
    for key in _SUBSTANCE_KEYS:
        val = d.get(key)
        if isinstance(val, (list, dict, str)) and len(val) > 0:
            return False
        if isinstance(val, (int, float)) and val:
            return False
    return True


def _wrapper_target(project: Path, fp: Path):
    """For an allowlisted wrapper: the path-shaped evidence/source target
    it points to (None when none)."""
    try:
        d = json.loads(fp.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    for key in ("evidence", "source"):
        v = d.get(key) if isinstance(d, dict) else None
        if isinstance(v, str) and "/" in v:
            tgt = project / v
            if tgt.is_file() and tgt.stat().st_size > 0:
                return hashlib.sha256(tgt.read_bytes()).hexdigest()
    return None


def audit(projects, allow, allow_honest_na: bool = False) -> dict:
    projects = [Path(p).resolve() for p in projects]
    if len(projects) < 2:
        return {"verdict": "SKIP", "rc": 2,
                "reason": "need >= 2 project dirs to compare"}
    # relpath -> {digest -> [project names]}
    table: dict = {}
    for proj in projects:
        seen = set()
        for g in _SCAN_GLOBS:
            for fp in proj.glob(g):
                if not fp.is_file() or fp.stat().st_size == 0:
                    continue
                rel = str(fp.relative_to(proj))
                if rel in seen:
                    continue
                seen.add(rel)
                posix = "/" + fp.as_posix() + "/"
                if any(t in posix for t in _INPUT_TOKENS):
                    continue
                digest = hashlib.sha256(fp.read_bytes()).hexdigest()
                table.setdefault(rel, {}).setdefault(digest, []).append(
                    (proj.name, proj))
    findings = []
    allow_ok = []
    honest_na_ok = []
    for rel, by_digest in sorted(table.items()):
        for digest, hits in by_digest.items():
            if len(hits) < 2:
                continue
            names = [n for n, _ in hits]
            base = Path(rel).name
            if base in allow:
                # wrapper exemption is CONDITIONAL: the evidence target
                # must differ per design, else the wrapper is canned too.
                tgts = {_wrapper_target(p, p / rel) for _, p in hits}
                if None not in tgts and len(tgts) == len(hits):
                    allow_ok.append({"path": rel, "projects": names})
                    continue
                findings.append({
                    "severity": "ERROR",
                    "rule": "CROSS_DESIGN_WRAPPER_NOT_EXEMPT",
                    "message": (f"{rel}: allowlisted wrapper is "
                                f"byte-identical across {names} but its "
                                f"evidence targets do NOT differ per "
                                f"design — canned, not a wrapper (#454)"),
                })
                continue
            # #484: STRICT named honest-N/A exemption — a verdict-only
            # manifest with an explicit skip/N-A verdict and NO per-design
            # substance is honest, not canned. EVERY hit must independently
            # satisfy the verdict-only predicate (a single substantive /
            # PASS-FAIL member among the byte-identical copies disqualifies
            # the whole group, so a real canned PASS/FAIL pair is never
            # exempted). Opt-in via --allow-honest-na.
            if allow_honest_na and all(
                    _is_honest_na_verdict_only(p / rel) for _, p in hits):
                honest_na_ok.append({"path": rel, "projects": names})
                continue
            findings.append({
                "severity": "ERROR",
                "rule": "CROSS_DESIGN_IDENTICAL_ARTIFACT",
                "message": (f"{rel}: byte-identical across DIFFERENT "
                            f"designs {names} (sha256 {digest[:12]}…) — a "
                            f"per-design report cannot be canned (#454)"),
            })
    return {
        "verdict": "FAIL" if findings else "PASS",
        "rc": 1 if findings else 0,
        "projects": [str(p) for p in projects],
        "identical_artifacts": len(findings),
        "allowlisted_wrappers_ok": allow_ok,
        "honest_na_exempt": honest_na_ok,
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("projects", nargs="+", type=Path,
                    help=">= 2 project dirs to cross-compare")
    ap.add_argument("--allow", default="ir_drop.json,power.json",
                    help="comma-separated wrapper basenames (conditional "
                         "exemption: evidence targets must differ)")
    ap.add_argument("--allow-honest-na", action="store_true",
                    help="#484: exempt verdict-only manifests whose verdict "
                         "is an explicit skip/N-A token AND which carry no "
                         "per-design substance (a PASS/FAIL report is NEVER "
                         "exempted). Use only where an emitter genuinely "
                         "cannot stamp design identity.")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    for p in args.projects:
        if not p.is_dir():
            print(f"ERROR: not a directory: {p}", file=sys.stderr)
            return 2
    allow = {t.strip() for t in args.allow.split(",") if t.strip()}
    rep = audit(args.projects, allow, allow_honest_na=args.allow_honest_na)
    rc = rep.pop("rc")
    rep = {"program": "cross_design_identity_check",
           "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
