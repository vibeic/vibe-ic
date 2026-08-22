#!/usr/bin/env python3
"""Emit the trial plan using the SHIPPED _ppa.search proposer, so the knob keys
in the trials file are byte-identical to the ones the manifest will look up."""
import json, sys
from pathlib import Path
PROGRAMS = Path("/home/reyerchu/_jppae2e/wt/vibe-ic-marketplace/plugins/vibe-ic/programs")
sys.path.insert(0, str(PROGRAMS))
from _ppa import search as S
from _ppa import canonical_json as cj

SPACE = json.loads(Path("/home/reyerchu/_jppae2e/search/space.json").read_text())
VALUES = {
    "placement_density":  ["0.30", "0.20", "0.40", "0.50", "0.60"],
    "die_um":             ["auto", "210x210", "240x240", "280x280"],
    "spare_cell_density": ["0.02", "0.00", "0.05"],
}
BUDGET = S.Budget(max_trials=60, max_full_pnr_trials=60, max_cpu_hours=24.0,
                  max_wall_seconds=14400.0, concurrency=8,
                  memory_limit_mb=16384, per_trial_timeout_s=3600.0,
                  failed_trial_policy=S.FAILED_COUNTS, seed=1121,
                  cache_policy=S.CACHE_IGNORE)
problems = BUDGET.problems()
if problems:
    print("[REFUSE] budget:", problems, file=sys.stderr); raise SystemExit(1)
digest = cj.digest_of(SPACE)
values, notes = S.values_from_space(SPACE, VALUES)
cands = S.propose(values, BUDGET, digest)
plan = [{"index": i, "knobs": c.knobs, "identity": c.identity, "note": c.note}
        for i, c in enumerate(cands)]
Path("/home/reyerchu/_jppae2e/search/plan.json").write_text(
    json.dumps({"space_digest": digest, "seed": BUDGET.seed,
                "lever_notes": notes, "plan": plan}, indent=2) + "\n")
print(f"space_digest={digest}")
print(f"candidates={len(plan)} lever_notes={len(notes)}")
for n in notes: print("  NOTE:", n)
for p in plan[:4]: print("  ", p["index"], p["knobs"], p["note"])
