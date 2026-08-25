#!/usr/bin/env python3
"""
analog_hil_convergence_log_check.py — verify that at least one analog
block ships a hardware-in-the-loop tuning-loop log demonstrating real
SPICE→hardware→corner→post-layout convergence.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Real-world inspiration: phase2+3_v10619-vendor/analog/A8_hardmacro/
ldo_default/hil_log/convergence_log.json carried 7 iterations spanning
stages SPICE_TT → SPICE_TT_after_resize → HW_TT_27C →
HW_TT_27C_after_trim → HW_SS_-40C → HW_FF_125C → post_layout_resim_TT,
final_verdict CONVERGED. That methodology — measuring the analog block
on real silicon at multiple corners and feeding results back into
sizing iteration — is qualitatively different from a single
uncalibrated SPICE pass. v1.6.24 promotes the methodology check from
convention to gate.

Required schema (chip-AGNOSTIC, no specific corner / freq / Vout
expectations hardcoded):
    {
      "block": "<block_name>",
      "loop_kind": "<free-text>",                  # informational
      "iterations": [
        { "iter": 1, "stage": "SPICE_TT", "verdict": "FAIL...", ... },
        { "iter": 2, "stage": "...",       "verdict": "PASS...", ... },
        ...
      ],
      "final_verdict": "CONVERGED" | "DIVERGED" | "INCOMPLETE"
    }

Acceptance bar (block-level):
  - iter count >= MIN_ITERATIONS (default 5)
  - distinct `stage` values >= MIN_STAGES (default 3)
  - stages must include at least one SPICE-prefixed AND at least one
    HW-prefixed entry (case-insensitive); see _has_spice / _has_hw
  - final_verdict == "CONVERGED"

Project-level acceptance: at least one block under analog/ satisfies
the block-level bar.

VACUOUS_PASS contract:
  * No analog/analog_block_list.json or empty → digital-only project,
    HIL gate inapplicable. Emit VACUOUS_PASS, exit 0.

Usage:
    python3 analog_hil_convergence_log_check.py <project_dir> [--json <out>]
                                                   [--min-iters N] [--min-stages N]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  no block satisfies the convergence bar
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


_DEFAULT_MIN_ITERS = 5
_DEFAULT_MIN_STAGES = 3
_FINAL_VERDICT_OK = "CONVERGED"
_HIL_LOG_GLOBS = (
    # Canonical location only: per-block hil_log/ alongside the other
    # A1-A7 deliverables. Non-canonical variants (e.g.
    # analog/A8_hardmacro/<block>/hil_log/) are not honoured — the
    # plugin no longer carries backward-compat to non-canonical paths.
    "phase3/analog/*/hil_log/convergence_log.json",
)
_RE_SPICE = re.compile(r"\bspice", re.IGNORECASE)
_RE_HW = re.compile(r"\bhw|\bhardware", re.IGNORECASE)


@dataclass
class BlockResult:
    block: str
    log_path: str
    converged: bool
    reasons: List[str] = field(default_factory=list)


def _load_log(path: Path) -> Optional[dict]:
    """Tolerant JSON loader: accepts JSON with leading `+` on numbers
    (which strict JSON disallows but appeared in the v10619-vendor log).
    Returns None on irrecoverable parse errors."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        try:
            text = path.read_text(encoding="utf-8")
            text = re.sub(r":\s*\+(\d)", r": \1", text)
            return json.loads(text)
        except Exception:
            return None


def _evaluate_log(data: dict, min_iters: int, min_stages: int
                  ) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    iters = data.get("iterations") or data.get("history") or []
    if not isinstance(iters, list):
        return False, ["iterations field missing or not a list"]
    if len(iters) < min_iters:
        reasons.append(f"only {len(iters)} iter(s); need ≥ {min_iters}")
    stages = {it.get("stage", "") for it in iters if isinstance(it, dict)}
    stages.discard("")
    if len(stages) < min_stages:
        reasons.append(f"only {len(stages)} distinct stage(s) "
                       f"({sorted(stages)}); need ≥ {min_stages}")
    if not any(_RE_SPICE.search(s) for s in stages):
        reasons.append("no SPICE-prefixed stage in iterations")
    if not any(_RE_HW.search(s) for s in stages):
        reasons.append("no HW-prefixed stage in iterations")
    final = data.get("final_verdict") or data.get("verdict")
    if final != _FINAL_VERDICT_OK:
        reasons.append(f"final_verdict={final!r}; need {_FINAL_VERDICT_OK!r}")
    return (not reasons), reasons


def _has_block_list(project: Path) -> bool:
    bl = project / "phase3" / "analog" / "analog_block_list.json"
    if not bl.is_file():
        return False
    try:
        data = json.loads(bl.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(data.get("blocks"))


def audit(project: Path, min_iters: int, min_stages: int
          ) -> tuple[str, List[BlockResult]]:
    if not _has_block_list(project):
        return "VACUOUS_PASS", []
    results: List[BlockResult] = []
    for pat in _HIL_LOG_GLOBS:
        for log_path in sorted(project.glob(pat)):
            block = log_path.parent.parent.name
            data = _load_log(log_path)
            if data is None:
                results.append(BlockResult(
                    block=block,
                    log_path=str(log_path.relative_to(project)),
                    converged=False,
                    reasons=["log file unreadable / malformed JSON"]))
                continue
            ok, reasons = _evaluate_log(data, min_iters, min_stages)
            results.append(BlockResult(
                block=block,
                log_path=str(log_path.relative_to(project)),
                converged=ok,
                reasons=reasons))
    if not results:
        return "FAIL", []
    return ("PASS" if any(r.converged for r in results) else "FAIL"), results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify ≥1 analog block has a converged HIL tuning log.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--min-iters", type=int, default=_DEFAULT_MIN_ITERS)
    ap.add_argument("--min-stages", type=int, default=_DEFAULT_MIN_STAGES)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, results = audit(project, args.min_iters, args.min_stages)
    converged_count = sum(1 for r in results if r.converged)

    report = {
        "gate": "analog_hil_convergence_log_check",
        "verdict": verdict,
        "project": str(project),
        "min_iterations": args.min_iters,
        "min_distinct_stages": args.min_stages,
        "expected_final_verdict": _FINAL_VERDICT_OK,
        "blocks_with_log": len(results),
        "blocks_converged": converged_count,
        "results": [asdict(r) for r in results],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("phase3/analog/analog_block_list.json missing or "
                            "empty; HIL convergence gate inapplicable.")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        print(f"PASS: {converged_count}/{len(results)} block(s) have a "
              f"converged HIL tuning log "
              f"(min_iters={args.min_iters}, min_stages={args.min_stages}, "
              f"final_verdict={_FINAL_VERDICT_OK!r})")
        return 0
    if not results:
        print("FAIL: analog blocks declared but no hil_log/convergence_log.json "
              "found under analog/ — HIL methodology not demonstrated.",
              file=sys.stderr)
    else:
        print(f"FAIL: 0/{len(results)} analog block(s) reached "
              f"final_verdict={_FINAL_VERDICT_OK!r}:", file=sys.stderr)
        for r in results:
            print(f"  [{r.block}] {r.log_path}: "
                  f"{', '.join(r.reasons)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
