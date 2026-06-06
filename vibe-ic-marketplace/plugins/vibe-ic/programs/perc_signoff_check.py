#!/usr/bin/env python3
"""perc_signoff_check.py — Step 28 PERC / reliability sign-off gate
(v2.3.0 flow-completeness review).

The runner's deterministic PERC-equivalent aggregate
(`reports/phase3/perc_equivalent.json`) already computes the
Calibre-PERC-class categories — ESD pad-ring presence, ESD discharge
topology, latch-up well-tap coverage, cross-voltage-domain protection,
plus the AUTOMATED antenna/IR/EM/floating-net verdicts — but its
conclusive FAILs previously lived only in a memo. This gate makes them
ENFORCED:

  * any AUTOMATED category with result=FAIL  → exit 1 (conclusive
    reliability defect — ESD ring/topology gap, well-tap gap,
    unprotected cross-domain crossing, antenna/IR over budget …)
  * AUTOMATED INCOMPLETE and MANUAL_REVIEW categories are NAMED open
    items (exit 0, verdict PASS_WITH_OPEN_ITEMS) — capability-tier
    measurements (e.g. EM MEASURED) and foundry device-physics sizing
    are review work, not fabricate-a-FAIL material;
  * everything conclusive PASS → exit 0 PASS.

Exit codes: 0 PASS / PASS_WITH_OPEN_ITEMS, 1 FAIL, 2 no
perc_equivalent.json yet (vacuous — run phase3 sign-off first).
chip-AGNOSTIC: consumes only the aggregate's structural fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def audit(project: Path) -> dict:
    src = project / "reports" / "phase3" / "perc_equivalent.json"
    if not src.is_file():
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("reports/phase3/perc_equivalent.json absent — "
                           "run the phase3 sign-off chain first")}
    try:
        data = json.loads(src.read_text(errors="replace"))
    except (OSError, ValueError):
        return {"verdict": "FAIL", "rc": 1,
                "reason": "perc_equivalent.json unparseable"}

    cats = data.get("categories") or []
    automated = [c for c in cats if isinstance(c, dict)
                 and c.get("status") == "AUTOMATED"]
    failed = [c for c in automated if c.get("result") == "FAIL"]
    incomplete = [c for c in automated if c.get("result") == "INCOMPLETE"]
    manual = [c for c in cats if isinstance(c, dict)
              and c.get("status") == "MANUAL_REVIEW"]
    open_items = ([f"INCOMPLETE: {c.get('category')}" for c in incomplete]
                  + [f"MANUAL_REVIEW: {c.get('category')}" for c in manual])

    rep = {
        "source": "reports/phase3/perc_equivalent.json",
        "source_verdict": data.get("verdict"),
        "automated_total": len(automated),
        "automated_failed": [c.get("category") for c in failed],
        "open_items": open_items,
    }
    if failed:
        rep.update(verdict="FAIL", rc=1, reason=(
            "conclusive PERC reliability defect(s): "
            + "; ".join(f"{c.get('category')}: "
                        f"{str(c.get('note') or c.get('source_verdict') or '')[:120]}"
                        for c in failed)))
    elif open_items:
        rep.update(verdict="PASS_WITH_OPEN_ITEMS", rc=0, reason=(
            f"no conclusive reliability defect; {len(open_items)} named "
            f"open item(s) pending review before tapeout"))
    else:
        rep.update(verdict="PASS", rc=0, reason=(
            "all AUTOMATED PERC categories conclusive PASS"))
    return rep


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
    rep = {"program": "perc_signoff_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
