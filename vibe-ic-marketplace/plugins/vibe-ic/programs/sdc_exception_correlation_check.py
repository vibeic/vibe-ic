#!/usr/bin/env python3
"""sdc_exception_correlation_check.py — Step 8 SDC EXCEPTION
justification screen (v2.3.0, advisory).

Timing exceptions silently waive real paths — a wrong false_path is a
silicon bug STA can never see. This screen correlates every exception
in the SDC against the design's own evidence:

  * `set_false_path` — justified when its -from/-to clocks correspond
    to a CDC crossing (reports/phase2/cdc/crossing.json) or an L8
    asynchronous-relation entry; otherwise SDC_EXCEPTION_UNJUSTIFIED
    (WARNING — review, this screen never blocks);
  * `set_multicycle_path` — multiplier sanity: N > 4 is flagged
    (WARNING) — large multipliers usually mean a missing clock
    definition rather than a real N-cycle path;
  * wildcard breadth — a bare `*` (or `{*}`) in -from/-to waives
    entire clock domains at once: SDC_EXCEPTION_TOO_BROAD (WARNING).

Exit codes: 0 (advisory — findings reported, never blocks),
1 SDC unreadable, 2 no SDC yet (vacuous).
chip-AGNOSTIC: SDC syntax + structural correlation only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_FP_RE = re.compile(r"^\s*set_false_path\b(.*)$", re.MULTILINE)
_MC_RE = re.compile(r"^\s*set_multicycle_path\s+(\d+)\b(.*)$", re.MULTILINE)
_CLK_TOK_RE = re.compile(r"get_clocks\s+\{?\s*([\w*]+)")
_BROAD_RE = re.compile(r"-(?:from|to|through)\s+(?:\{\s*\*\s*\}|\*)(?:\s|$)")

_MC_SANE_MAX = 4


def _sdc_files(project: Path):
    return sorted((project / "phase2" / "stage2" / "constraints").glob("*.sdc"))


def _known_async_pairs(project: Path):
    """Clock-name pairs the design's own evidence marks asynchronous."""
    pairs = set()
    cdc = project / "reports" / "phase2" / "cdc" / "crossing.json"
    try:
        d = json.loads(cdc.read_text(errors="replace"))
        for c in (d.get("crossings") or []):
            a, b = c.get("from_clock"), c.get("to_clock")
            if a and b:
                pairs.add(frozenset((str(a), str(b))))
    except (OSError, ValueError):
        pass
    l8 = project / "phase1" / "generated_docs" / "L8_TIMING_WAVEFORM.json"
    try:
        d = json.loads(l8.read_text(errors="replace"))
        blob = json.dumps(d).lower()
        for m in re.finditer(r'"async[\w_]*"\s*:\s*\[([^\]]*)\]', blob):
            toks = re.findall(r'"(\w+)"', m.group(1))
            if len(toks) >= 2:
                pairs.add(frozenset(toks[:2]))
    except (OSError, ValueError):
        pass
    return pairs


def audit(project: Path) -> dict:
    sdcs = _sdc_files(project)
    if not sdcs:
        return {"verdict": "SKIP", "rc": 2,
                "reason": "no SDC under phase2/stage2/constraints yet"}
    findings = []
    async_pairs = _known_async_pairs(project)
    n_fp = n_mc = 0
    for sdc in sdcs:
        try:
            txt = sdc.read_text(errors="replace")
        except OSError:
            return {"verdict": "FAIL", "rc": 1,
                    "reason": f"unreadable SDC: {sdc.name}"}
        rel = sdc.name
        for m in _FP_RE.finditer(txt):
            n_fp += 1
            args = m.group(1)
            clks = _CLK_TOK_RE.findall(args)
            if _BROAD_RE.search(args) or "*" in clks:
                findings.append({
                    "severity": "WARNING",
                    "category": "SDC_EXCEPTION_TOO_BROAD",
                    "message": (f"{rel}: false_path with bare wildcard "
                                f"-from/-to waives whole domains at once "
                                f"— scope it: `{m.group(0).strip()[:100]}`")})
            elif len(clks) >= 2 \
                    and frozenset(clks[:2]) not in async_pairs:
                findings.append({
                    "severity": "WARNING",
                    "category": "SDC_EXCEPTION_UNJUSTIFIED",
                    "message": (f"{rel}: false_path between clocks "
                                f"{clks[0]!r}↔{clks[1]!r} has no matching "
                                f"CDC crossing / L8 async relation — "
                                f"justify or remove")})
        for m in _MC_RE.finditer(txt):
            n_mc += 1
            mult = int(m.group(1))
            if mult > _MC_SANE_MAX:
                findings.append({
                    "severity": "WARNING",
                    "category": "SDC_MULTICYCLE_SUSPECT",
                    "message": (f"{rel}: multicycle multiplier {mult} > "
                                f"{_MC_SANE_MAX} — large multipliers "
                                f"usually mask a missing clock "
                                f"definition; verify the real path "
                                f"latency")})
            if _BROAD_RE.search(m.group(2)):
                findings.append({
                    "severity": "WARNING",
                    "category": "SDC_EXCEPTION_TOO_BROAD",
                    "message": (f"{rel}: multicycle with bare wildcard "
                                f"scope — scope it")})
    return {
        "verdict": ("REVIEW" if any(f["severity"] == "WARNING"
                                    for f in findings) else "PASS"),
        "rc": 0,  # advisory — discloses, never blocks
        "false_paths": n_fp,
        "multicycle_paths": n_mc,
        "known_async_pairs": [sorted(p) for p in async_pairs],
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    rep = {"program": "sdc_exception_correlation_check",
           "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
