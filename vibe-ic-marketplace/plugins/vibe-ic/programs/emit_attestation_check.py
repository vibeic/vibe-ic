#!/usr/bin/env python3
"""emit_attestation_check.py — score-time GATE-AS-SOLE-EMIT-PATH enforcement.

Asserts that EVERY scoreable sample in a run's `samples/` is CANONICAL: it was produced by
the deterministic emit path (`gates_atomic.py` / `shape_b_sample_export.py`) — carrying a
valid `emit_attestation` whose sha256 matches the on-disk bytes AND whose Phase-1 provenance
shows the RTL flowed through `(doc|prompt) → Phase1(L*.json) → Phase2`. A sample authored
directly into `samples/` (bypassing the emit gates + port-reorder), mutated after emit, OR
authored with Phase 1 skipped is NOT canonical: its number measures the raw author, not the
runner.

Wired into `benchmark_dispatch.py --score`. Modes:
  default  : WARN + rc 1 — the score is reported but flagged NON-CANONICAL (ungated samples
             listed). Use when an exploratory direct-author run is acceptable but must be
             disclosed.
  --strict : the same FAIL, intended to HARD-BLOCK a published/official run.

If NO attestation file exists at all AND no samples are present → SKIP (rc 0, nothing to gate).

CLI:
    emit_attestation_check.py --samples <dir> [--strict] [--json OUT]
    rc 0 = every scoreable sample is emit-path-attested;  rc 1 = ungated samples present.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import emit_attestation as _ea  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True, type=Path,
                    help="the run's samples/ directory (the host scorer's input)")
    ap.add_argument("--strict", action="store_true",
                    help="treat ungated samples as a hard FAIL of an official run")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not a.samples.is_dir():
        print(f"ERROR: no such samples dir {a.samples}", file=sys.stderr)
        return 2
    # Phase-1 provenance is REQUIRED for canonical (a Phase-1-skipping sample is
    # non-canonical), alongside the emit-path attestation.
    ok, ungated, total = _ea.verify(a.samples)
    res = {"ok": ok, "total": total, "ungated_count": len(ungated),
           "ungated": ungated, "strict": a.strict,
           "verdict": "PASS" if ok else ("FAIL" if a.strict else "NON-CANONICAL")}
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    if total == 0:
        print("SKIP: no scoreable samples to attest.")
        return 0
    if ok:
        print(f"PASS: all {total} scoreable samples carry a valid emit-path attestation "
              f"(GATE-AS-SOLE-EMIT-PATH honored).")
        return 0
    head = "FAIL" if a.strict else "NON-CANONICAL"
    print(f"{head}: {len(ungated)}/{total} sample(s) are NOT canonical — no valid emit-path "
          f"attestation (authored directly into samples/ bypassing the emit gates + "
          f"port-reorder / mutated after emit) OR no Phase-1 provenance (RTL authored with "
          f"Phase 1 skipped). This run's number measures the raw author, NOT the runner. "
          f"Re-run through the emit path "
          f"(gates_atomic.py / shape_b_sample_export.py). Ungated: {ungated[:15]}"
          + (" …" if len(ungated) > 15 else ""))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
