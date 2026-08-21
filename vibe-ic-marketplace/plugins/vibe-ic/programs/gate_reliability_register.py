#!/usr/bin/env python3
"""
gate_reliability_register.py -- Self-calibrating per-gate reliability ledger.

Tracks, per compliance gate, an exponential-moving-average (EMA) of its
pass-rate and -- critically -- its false-PASS-rate, fed by the field-agent
loop and compliance-gate-spot-check. The spot-checker can then spend its
sampling budget on the gates that have historically been gamed / false-passed,
instead of sampling uniformly across all gates.

The EMA-updated capability/trust register is borrowed in concept from
ChipAgentix's tool-trust register; this implementation is independent,
chip-AGNOSTIC (gate names are opaque strings) and stores a plain JSON ledger.

A "false PASS" = the gate reported PASS but a deeper review (spot-check,
field-agent verification on the real benchmark, or a later-stage failure)
proved the design was actually wrong. Those are the dangerous ones, so they
dominate the spot-check sampling priority.

Usage (library):
    reg = ReliabilityRegister(Path("capability_register.json"))
    reg.record("drc_report_check", passed=True)
    reg.record("lec_check", passed=True, false_pass=True)   # gate lied
    reg.save()
    for gate, prio in reg.ranked_for_spotcheck():
        ...

Usage (CLI):
    python3 gate_reliability_register.py record LEDGER --gate drc_report_check --pass
    python3 gate_reliability_register.py record LEDGER --gate lec_check --pass --false-pass
    python3 gate_reliability_register.py record LEDGER --gate sta_check --fail
    python3 gate_reliability_register.py report LEDGER
    python3 gate_reliability_register.py rank   LEDGER --top 5

Exit codes:
    0 = success
    1 = error (bad ledger / unknown gate on report)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class GateRecord:
    gate: str
    samples: int = 0
    ema_pass: float = 0.0        # EMA of pass (1.0) / fail (0.0)
    ema_false_pass: float = 0.0  # EMA of false-PASS events (1.0 / 0.0)
    last_updated: str = ""

    def update(self, alpha: float, passed: bool, false_pass: bool) -> None:
        p = 1.0 if passed else 0.0
        fp = 1.0 if false_pass else 0.0
        if self.samples == 0:
            self.ema_pass = p
            self.ema_false_pass = fp
        else:
            self.ema_pass = alpha * p + (1 - alpha) * self.ema_pass
            self.ema_false_pass = alpha * fp + (1 - alpha) * self.ema_false_pass
        self.samples += 1
        self.last_updated = _now_iso()

    def confidence(self) -> float:
        """How much to trust a PASS from this gate: high pass-rate AND low
        false-pass-rate. In [0, 1]."""
        return max(0.0, self.ema_pass * (1.0 - self.ema_false_pass))


class ReliabilityRegister:
    """A JSON-backed ledger of GateRecords with EMA calibration."""

    def __init__(self, path: Path, alpha: float = 0.3):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.path = Path(path)
        self.alpha = alpha
        self.records: Dict[str, GateRecord] = {}
        if self.path.exists():
            self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        raw = self.path.read_text().strip()
        if not raw:
            return  # empty ledger file (e.g. freshly `touch`ed) -> start fresh
        data = json.loads(raw)
        self.alpha = data.get("alpha", self.alpha)
        for name, rec in (data.get("gates") or {}).items():
            self.records[name] = GateRecord(
                gate=name,
                samples=int(rec.get("samples", 0)),
                ema_pass=float(rec.get("ema_pass", 0.0)),
                ema_false_pass=float(rec.get("ema_false_pass", 0.0)),
                last_updated=rec.get("last_updated", ""),
            )

    def save(self) -> None:
        payload = {
            "alpha": self.alpha,
            "updated": _now_iso(),
            "gates": {name: asdict(rec) for name, rec in sorted(self.records.items())},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # -- updates ------------------------------------------------------------
    def record(self, gate: str, passed: bool, false_pass: bool = False) -> GateRecord:
        if false_pass and not passed:
            # A false PASS only makes sense when the gate reported PASS.
            raise ValueError("false_pass=True requires passed=True")
        rec = self.records.get(gate) or GateRecord(gate=gate)
        rec.update(self.alpha, passed, false_pass)
        self.records[gate] = rec
        return rec

    # -- queries ------------------------------------------------------------
    def confidence(self, gate: str) -> float:
        rec = self.records.get(gate)
        return rec.confidence() if rec else 0.0

    def spotcheck_priority(self, gate: str) -> float:
        """Higher = sample this gate first in the spot-check budget.

        Dominated by historical false-PASS rate, with a low-sample bonus so
        that under-observed gates also get attention early.
        """
        rec = self.records.get(gate)
        if rec is None or rec.samples == 0:
            return 1.0  # never seen -> highest priority
        low_sample_bonus = 1.0 / (1.0 + rec.samples)
        return 0.7 * rec.ema_false_pass + 0.3 * low_sample_bonus

    def ranked_for_spotcheck(self) -> List[Tuple[str, float]]:
        ranked = [(g, self.spotcheck_priority(g)) for g in self.records]
        ranked.sort(key=lambda kv: (-kv[1], kv[0]))
        return ranked


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cmd_record(args) -> int:
    reg = ReliabilityRegister(Path(args.ledger), alpha=args.alpha)
    passed = args.result == "pass"
    try:
        reg.record(args.gate, passed=passed, false_pass=args.false_pass)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    reg.save()
    rec = reg.records[args.gate]
    print(json.dumps(asdict(rec) | {"confidence": rec.confidence()},
                     indent=2, ensure_ascii=False))
    return 0


def _cmd_report(args) -> int:
    p = Path(args.ledger)
    if not p.exists():
        print(f"error: ledger not found: {p}", file=sys.stderr)
        return 1
    reg = ReliabilityRegister(p)
    out = {g: asdict(r) | {"confidence": r.confidence()}
           for g, r in sorted(reg.records.items())}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def _cmd_rank(args) -> int:
    p = Path(args.ledger)
    if not p.exists():
        print(f"error: ledger not found: {p}", file=sys.stderr)
        return 1
    reg = ReliabilityRegister(p)
    ranked = reg.ranked_for_spotcheck()
    if args.top:
        ranked = ranked[:args.top]
    print(json.dumps([{"gate": g, "spotcheck_priority": round(prio, 6)}
                      for g, prio in ranked], indent=2, ensure_ascii=False))
    return 0


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-calibrating per-gate reliability ledger (EMA).")
    parser.add_argument("--alpha", type=float, default=0.3,
                        help="EMA smoothing factor (0,1]; default 0.3")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("record", help="Record one gate outcome")
    pr.add_argument("ledger")
    pr.add_argument("--gate", required=True)
    grp = pr.add_mutually_exclusive_group(required=True)
    grp.add_argument("--pass", dest="result", action="store_const", const="pass")
    grp.add_argument("--fail", dest="result", action="store_const", const="fail")
    pr.add_argument("--false-pass", dest="false_pass", action="store_true",
                    help="gate reported PASS but was actually wrong")
    pr.set_defaults(func=_cmd_record)

    prep = sub.add_parser("report", help="Dump the full ledger")
    prep.add_argument("ledger")
    prep.set_defaults(func=_cmd_report)

    prk = sub.add_parser("rank", help="Rank gates by spot-check priority")
    prk.add_argument("ledger")
    prk.add_argument("--top", type=int, default=0)
    prk.set_defaults(func=_cmd_rank)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
