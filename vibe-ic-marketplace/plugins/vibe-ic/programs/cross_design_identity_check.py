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


def audit(projects, allow) -> dict:
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
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("projects", nargs="+", type=Path,
                    help=">= 2 project dirs to cross-compare")
    ap.add_argument("--allow", default="ir_drop.json,power.json",
                    help="comma-separated wrapper basenames (conditional "
                         "exemption: evidence targets must differ)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    for p in args.projects:
        if not p.is_dir():
            print(f"ERROR: not a directory: {p}", file=sys.stderr)
            return 2
    allow = {t.strip() for t in args.allow.split(",") if t.strip()}
    rep = audit(args.projects, allow)
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
