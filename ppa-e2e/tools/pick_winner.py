#!/usr/bin/env python3
"""Pick the search winner on the DECLARED objective, and say what it was
allowed to consider. A winner chosen from a set that was silently narrowed is
not a winner; every exclusion below is named and counted."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jppae2e")
OBJ, OBJ_SCOPE, DIR = "area.design_report.um2", {"stage": "post_route"}, "lower"


def main() -> int:
    trials = json.loads((ROOT / "search/trials.json").read_text())
    rows, excluded = [], []
    for t in trials:
        if t["state"] != "COMPLETED":
            excluded.append((t["trial"], f"state={t['state']}")); continue
        if t["completed_stage"] != "post_route_extracted":
            excluded.append((t["trial"],
                             f"completed_stage={t['completed_stage']}")); continue
        hits = [m for m in t["metrics"] if m.get("metric") == OBJ
                and m.get("status") == "MEASURED"
                and all((m.get("scope") or {}).get(k) == v
                        for k, v in OBJ_SCOPE.items())]
        if len(hits) != 1:
            excluded.append((t["trial"],
                             f"{len(hits)} MEASURED {OBJ} records under "
                             f"{OBJ_SCOPE} -- a winner needs exactly one"))
            continue
        rows.append({"trial": t["trial"], "knobs": t["knobs"],
                     "objective": hits[0]["value"], "unit": hits[0].get("unit"),
                     "cost": t["cost"]})
    if not rows:
        print("[CANNOT CHECK] no trial carries the declared objective",
              file=sys.stderr)
        return 2
    rows.sort(key=lambda r: r["objective"], reverse=(DIR == "higher"))
    best = rows[0]
    ties = [r for r in rows if r["objective"] == best["objective"]]
    doc = {"schema": "vibeic.jppae2e.winner.v1",
           "objective": {"metric": OBJ, "scope": OBJ_SCOPE, "better_is": DIR,
                         "declared_by": "this run -- the design declares NO PPA "
                                        "objective (L19 die_area_budget_um=null, "
                                        "power_budget_uw=null)"},
           "considered": len(rows), "excluded": excluded,
           "trial": best["trial"], "knobs": best["knobs"],
           "objective_value": best["objective"], "unit": best["unit"],
           "ties_at_best": [t["trial"] for t in ties],
           "ranking": rows}
    (ROOT / "search/winner.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(f"considered {len(rows)} / {len(trials)} trial(s); "
          f"excluded {len(excluded)}")
    for t, why in excluded[:8]:
        print(f"  excluded {t}: {why}")
    print(f"WINNER {best['trial']} {best['knobs']} -> {OBJ} = "
          f"{best['objective']} {best['unit']}  (ties: {len(ties)})")
    print("worst:", rows[-1]["trial"], rows[-1]["objective"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
