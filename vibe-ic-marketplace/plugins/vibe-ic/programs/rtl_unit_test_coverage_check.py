#!/usr/bin/env python3
"""rtl_unit_test_coverage_check.py — v0.50.2 plugin gate

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verifies every FSM-bearing RTL module has a corresponding per-module unit
testbench under sim_unit/. Catches the failure mode from <benchmark> v0.50
where end-to-end sim PASSed but real hardware FAILed because per-module
behaviour (pulse-classifier, frame-end timing, trailing-delimiter handling)
was never isolated.

Heuristics for "needs a tb":
  - Module file contains `case (st)` / `case (state)` / `localparam S_*`
    → state machine, needs tb
  - Module file contains `low_cnt`/`high_cnt`/`pulse`/`width` regs
    → pulse classifier, needs tb
  - Module is named `rx_phy` / `tx_phy` / `dispatcher` / `mac` / `ctrl`
    → protocol-bearing, needs tb

Each candidate must have a matching `sim_unit/tb_<module>.v` file.

Usage:
    python3 rtl_unit_test_coverage_check.py <project_dir>
        [--rtl-dir <path>]    (default: <proj>/rtl)
        [--sim-dir <path>]    (default: <proj>/sim_unit)
        [--json <out>]
        [--strict]

Exit codes:
    0 — every FSM-bearing module has a tb
    1 — one or more missing
    2 — input error
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
import _path_layout as _pl

# Patterns indicating module needs a unit tb
_FSM_PATTERNS = [
    re.compile(r"case\s*\(\s*st\s*\)"),
    re.compile(r"case\s*\(\s*state\s*\)"),
    re.compile(r"localparam\s+S_\w+\s*=", re.IGNORECASE),
    re.compile(r"reg\s+\[\s*\d+\s*:\s*0\s*\]\s*(?:state|st)\b"),
]
_PHY_PATTERNS = [
    re.compile(r"\b(low_cnt|high_cnt)\b"),
    re.compile(r"pulse_(?:low|high|width)"),
    re.compile(r"_(?:rx|tx|dispatcher|mac|ctrl)\.v$", re.IGNORECASE),
]
# Module names that always need tb regardless of patterns
_MUST_TB_NAMES = {
    "rx_phy", "tx_phy", "dispatcher", "cmd_dispatcher",
    "mac", "rx_chk", "rx_cmd", "ctl_top", "tx_chk",
    "frame_assembler", "byte_assembler", "fsm",
}


def needs_tb(rtl_path: Path) -> tuple[bool, list[str]]:
    """Return (needs_tb, reasons)."""
    name = rtl_path.stem.lower()
    reasons = []

    # Must-tb names (substring or exact)
    for must in _MUST_TB_NAMES:
        if must in name:
            reasons.append(f"name contains '{must}'")
            return True, reasons

    try:
        text = rtl_path.read_text()
    except Exception:
        return False, ["unreadable"]

    for pat in _FSM_PATTERNS:
        if pat.search(text):
            reasons.append(f"FSM pattern: {pat.pattern[:40]}")

    for pat in _PHY_PATTERNS:
        if pat.search(text) or pat.search(rtl_path.name):
            reasons.append(f"PHY pattern: {pat.pattern[:40]}")

    return bool(reasons), reasons


def has_tb(module_name: str, sim_dir: Path) -> Path | None:
    """Look for sim_unit/tb_<module>.v with stem variants:
       module 'aid_rx_phy' matches tb_aid_rx_phy.v OR tb_rx_phy.v."""
    candidates = {module_name}
    # Also strip leading prefixes
    for prefix in ("aid_", "as3616_", "u_", "i_"):
        if module_name.startswith(prefix):
            candidates.add(module_name[len(prefix):])
    # Common aliases (cmd_dispatcher → dispatcher)
    if module_name.startswith("cmd_"):
        candidates.add(module_name[len("cmd_"):])
    if module_name.endswith("_dispatcher"):
        candidates.add("dispatcher")
        candidates.add("disp")
    for nm in candidates:
        for ext in (".v", ".sv"):
            cand = sim_dir / f"tb_{nm}{ext}"
            if cand.exists():
                return cand
    return None


def check(project: Path, rtl_dir: Path, sim_dir: Path) -> dict:
    findings = []
    coverage = []
    if not rtl_dir.exists():
        return {"pass": False, "error": f"rtl dir {rtl_dir} not found", "findings": []}

    rtl_files = sorted(list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv")))
    rtl_files = [r for r in rtl_files if not r.name.endswith(".vh")]

    n_total = 0
    for rtl in rtl_files:
        if rtl.name.endswith("_pkg.vh") or rtl.name.endswith("_params.vh"):
            continue
        need, reasons = needs_tb(rtl)
        if not need:
            continue
        n_total += 1
        tb = has_tb(rtl.stem, sim_dir)
        entry = {"module": rtl.name, "reasons": reasons, "tb_path": str(tb) if tb else None}
        coverage.append(entry)
        if not tb:
            findings.append({
                "severity": "FAIL",
                "rule": "missing_unit_tb",
                "module": rtl.name,
                "reasons": reasons,
                "expected_tb": f"{sim_dir}/tb_{rtl.stem}.v",
                "message": (f"{rtl.name} needs a per-module unit testbench "
                            f"but {sim_dir}/tb_{rtl.stem}.v is missing. "
                            f"Reasons: {reasons}. See "
                            "rtl-unit-testbench-gen SKILL.md."),
            })

    return {
        "rtl_dir": str(rtl_dir),
        "sim_dir": str(sim_dir),
        "candidates_total": n_total,
        "candidates_covered": n_total - len(findings),
        "candidates_missing": len(findings),
        "coverage": coverage,
        "findings": findings,
        "pass": len(findings) == 0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--rtl-dir", default=None)
    ap.add_argument("--sim-dir", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    proj = Path(args.project_dir)
    if not proj.exists():
        print(f"ERROR: project_dir {proj} not found", file=sys.stderr)
        return 2
    rtl = Path(args.rtl_dir) if args.rtl_dir else _pl.rtl_dir(proj)
    sim = Path(args.sim_dir) if args.sim_dir else proj / "sim_unit"

    result = check(proj, rtl, sim)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
