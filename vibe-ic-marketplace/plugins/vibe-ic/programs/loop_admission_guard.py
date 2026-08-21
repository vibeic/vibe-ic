#!/usr/bin/env python3
"""
loop_admission_guard.py -- Admission guard for Vibe-IC closed-loop skills.

Reusable, chip-AGNOSTIC gate that every iterative *-loop skill (rtl-repair,
hold-fix, analog-sizing-loop, drc-fix, eco-plan) can call once per round,
*before* spending an expensive EDA iteration on a proposed parameter set.

Three independent guards, applied in order:

  1. RUNAWAY   -- a hard iteration budget plus per-field caps that REJECT
                  (not clamp) a proposal, so a loop cannot blow up compute
                  (e.g. stimulus_count / duration_ns above a ceiling).
  2. BOUNDS    -- clamp each numeric field into its [lo, hi] range. A proposal
                  that had to be clamped is still admitted, but the clamped
                  value is returned so the caller acts on a safe value.
  3. FINGERPRINT -- md5 of the canonicalised (post-clamp) proposal; rejects
                  re-running a parameter combination already tried this
                  session. This is the "don't let the agent waste an iteration
                  repeating itself" check.

Design note: the idea of a first-class admission validator with a
fingerprint-dedup gate is borrowed from samirliu/chipagent's
AdmissionValidator; this implementation is independent and chip-agnostic
(proposal keys are opaque strings -- no chip-specific field is assumed).

Usage (library):
    guard = AdmissionGuard(
        bounds={"slack_ps": (-500, 0)},
        caps={"buffer_count": 64},
        max_iterations=20,
    )
    res = guard.admit({"slack_ps": -120, "buffer_count": 8})
    if res.admitted:
        run_iteration(res.proposal)   # proposal is post-clamp / safe

Usage (CLI -- one-shot decision):
    python3 loop_admission_guard.py decision.json
    python3 loop_admission_guard.py decision.json --json out.json

  where decision.json is:
    {
      "bounds": {"slack_ps": [-500, 0]},
      "caps": {"buffer_count": 64},
      "max_iterations": 20,
      "history": [{"slack_ps": -120, "buffer_count": 8}],
      "proposal": {"slack_ps": -120, "buffer_count": 8}
    }

Exit codes:
    0 = ADMITTED
    1 = REJECTED

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
def canonical_fingerprint(proposal: Dict) -> str:
    """Stable md5 of a proposal dict, independent of key order.

    Floats are rounded to 9 significant digits before hashing so that values
    that are equal up to floating-point noise map to the same fingerprint.
    """
    def _norm(value):
        if isinstance(value, float):
            # round to 9 sig-figs; -0.0 -> 0.0
            return float(f"{value:.9g}") + 0.0
        if isinstance(value, dict):
            return {k: _norm(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_norm(v) for v in value]
        return value

    payload = json.dumps(_norm(proposal), sort_keys=True, ensure_ascii=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class AdmissionResult:
    admitted: bool
    reason: str               # ADMITTED | DUPLICATE | RUNAWAY_CAP | RUNAWAY_ITERATION_BUDGET
    fingerprint: str
    proposal: Dict = field(default_factory=dict)   # post-clamp proposal
    clamped_fields: List[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class AdmissionGuard:
    """Stateful admission guard for a single closed-loop session.

    bounds:         {field: (lo, hi)} -- numeric fields are clamped into range.
    caps:           {field: ceiling}  -- a value strictly above the ceiling is
                    REJECTED (runaway protection), not clamped.
    max_iterations: hard ceiling on the number of *admitted* proposals.
    """
    bounds: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    caps: Dict[str, float] = field(default_factory=dict)
    max_iterations: Optional[int] = None

    _seen: set = field(default_factory=set, repr=False)
    _admitted_count: int = field(default=0, repr=False)

    # -- introspection ------------------------------------------------------
    @property
    def admitted_count(self) -> int:
        return self._admitted_count

    def seen_fingerprints(self) -> List[str]:
        return sorted(self._seen)

    # -- core ---------------------------------------------------------------
    def _clamp(self, proposal: Dict) -> Tuple[Dict, List[str]]:
        out = dict(proposal)
        clamped: List[str] = []
        for key, (lo, hi) in self.bounds.items():
            if key not in out:
                continue
            val = out[key]
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            new = min(max(val, lo), hi)
            if new != val:
                out[key] = new
                clamped.append(key)
        return out, clamped

    def _runaway_cap(self, proposal: Dict) -> Optional[str]:
        for key, ceiling in self.caps.items():
            val = proposal.get(key)
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            if val > ceiling:
                return f"{key}={val} exceeds cap {ceiling}"
        return None

    def admit(self, proposal: Dict) -> AdmissionResult:
        """Decide whether to spend an iteration on `proposal`.

        On admission the proposal is recorded so an identical one is rejected
        later; rejected proposals are NOT recorded (so the caller may retry a
        clamped/perturbed variant).
        """
        # 1. RUNAWAY -- iteration budget
        if (self.max_iterations is not None
                and self._admitted_count >= self.max_iterations):
            fp = canonical_fingerprint(proposal)
            return AdmissionResult(
                admitted=False, reason="RUNAWAY_ITERATION_BUDGET",
                fingerprint=fp, proposal=dict(proposal),
                detail=f"iteration budget {self.max_iterations} reached")

        # 1b. RUNAWAY -- per-field caps (checked on raw proposal)
        cap_msg = self._runaway_cap(proposal)
        if cap_msg is not None:
            fp = canonical_fingerprint(proposal)
            return AdmissionResult(
                admitted=False, reason="RUNAWAY_CAP",
                fingerprint=fp, proposal=dict(proposal), detail=cap_msg)

        # 2. BOUNDS -- clamp
        clamped_proposal, clamped_fields = self._clamp(proposal)

        # 3. FINGERPRINT -- dedup on post-clamp proposal
        fp = canonical_fingerprint(clamped_proposal)
        if fp in self._seen:
            return AdmissionResult(
                admitted=False, reason="DUPLICATE",
                fingerprint=fp, proposal=clamped_proposal,
                clamped_fields=clamped_fields,
                detail="proposal already tried this session")

        self._seen.add(fp)
        self._admitted_count += 1
        return AdmissionResult(
            admitted=True, reason="ADMITTED",
            fingerprint=fp, proposal=clamped_proposal,
            clamped_fields=clamped_fields)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _guard_from_spec(spec: Dict) -> AdmissionGuard:
    bounds = {k: tuple(v) for k, v in (spec.get("bounds") or {}).items()}
    return AdmissionGuard(
        bounds=bounds,
        caps=dict(spec.get("caps") or {}),
        max_iterations=spec.get("max_iterations"),
    )


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Admission guard for closed-loop skills (one-shot CLI).")
    parser.add_argument("spec", help="JSON file: bounds/caps/max_iterations/history/proposal")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text())
    guard = _guard_from_spec(spec)

    # Replay history so prior proposals populate the dedup set.
    for prior in (spec.get("history") or []):
        guard.admit(prior)

    result = guard.admit(spec.get("proposal", {}))

    report = asdict(result)
    report["admitted_count"] = guard.admitted_count
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if result.admitted else 1


if __name__ == "__main__":
    sys.exit(main())
