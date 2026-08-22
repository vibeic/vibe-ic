#!/usr/bin/env python3
"""Turn 60 completed run trees into the `--trials` document ppa_search_run reads.

Every field is DERIVED from the run tree. `completed_stage` in particular: the
fidelity ladder position is read off the artefacts that exist, not asserted from
the fact that the runner was asked for a full flow.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jppae2e")
LADDER = ["synth", "floorplan", "place", "cts", "global_route",
          "detailed_route", "post_route_extracted"]


def completed_stage(run: Path) -> tuple[str | None, str]:
    """The highest ladder rung this tree actually reached, and the evidence."""
    pnr = run / "phase3" / "stage3" / "pnr"
    sta = run / "phase3" / "stage3" / "sta"
    ev = []
    stage = None

    def hit(rung, rel):
        nonlocal stage
        if (run / rel).is_file():
            stage = rung; ev.append(f"{rung}<-{rel}")
            return True
        return False

    hit("synth", "phase2/stage2/synth/spm_synth.v")
    hit("floorplan", "phase3/stage3/pnr/floorplan.def")
    hit("place", "phase3/stage3/pnr/placed.def")
    hit("cts", "phase3/stage3/pnr/post_cts.def")
    hit("global_route", "phase3/stage3/pnr/routed_preantenna.def")
    hit("detailed_route", "phase3/stage3/pnr/spm.def")
    # post_route_extracted needs BOTH a parasitics file AND an STA report that
    # was produced from it. A SPEF with nothing timed against it is extraction,
    # not an extracted measurement.
    spef = sorted(pnr.glob("*.spef")) if pnr.is_dir() else []
    stamped = (sta / "sta_spef_based.rpt")
    if spef and stamped.is_file() and "POST_ROUTE_SPEF" in stamped.read_text(errors="ignore"):
        stage = "post_route_extracted"
        ev.append(f"post_route_extracted<-{spef[0].name}+sta_spef_based.rpt(STA_BASIS:POST_ROUTE_SPEF)")
    if stage is None:
        return None, "no ladder artefact found: the trial reached no declared stage"
    return stage, "; ".join(ev)


#: The metrics a trial publishes. (metric, required scope subset)
WANT = [
    ("area.die.um2", {"stage": "floorplan"}),
    ("area.design_report.um2", {"stage": "post_route"}),
    ("area.instances.total.um2", {"stage": "floorplan"}),
    ("area.instances.fixed_in_core.um2", {"stage": "detailed_placement"}),
    ("route.wirelength.um", {"stage": "detailed_route"}),
    ("route.via.count", {"stage": "detailed_route"}),
    ("route.drc.violation.count", {"stage": "detailed_route"}),
    ("antenna.net.violation.count", {"stage": "detailed_route"}),
    ("antenna.pin.violation.count", {"stage": "detailed_route"}),
    ("placement.violation.count", {"stage": "detailed_placement"}),
    ("design.instance.count", {"stage": "floorplan"}),
    ("power.total_w", {"group": "Total"}),
    ("timing.setup.worst_slack_ns", {"stage": "post_route_extracted", "check": "setup"}),
    ("timing.hold.worst_slack_ns", {"check": "hold", "process": "ff"}),
]


def pick(records, metric, want_scope):
    out = []
    for r in records:
        if r.get("metric") != metric:
            continue
        sc = r.get("scope") or {}
        if all(sc.get(k) == v for k, v in want_scope.items()):
            out.append(r)
    return out


def trial_metrics(d: Path) -> tuple[list, list]:
    f = d / "records_flat.json"
    if not f.is_file():
        return [], [f"{f.name} absent: metrics NOT_MEASURED, not zero"]
    recs = json.loads(f.read_text())
    out, notes = [], []
    for metric, sc in WANT:
        hits = pick(recs, metric, sc)
        if not hits:
            notes.append(f"{metric} under {sc}: no record -- NOT_MEASURED")
            continue
        measured = [h for h in hits if h.get("status") == "MEASURED"]
        if not measured:
            out.append(hits[0]); notes.append(f"{metric}: present but {hits[0].get('status')}")
            continue
        vals = {h.get("value") for h in measured}
        if len(vals) > 1:
            notes.append(f"{metric} under {sc}: {len(vals)} DIFFERENT measured "
                         f"values {sorted(vals)} -- ambiguous, published as INVALID")
            bad = dict(measured[0]); bad["status"] = "INVALID"; bad.pop("value", None)
            bad["reason"] = f"{len(vals)} disagreeing records under one scope"
            out.append(bad); continue
        out.append(measured[0])
    return out, notes


def main() -> int:
    plan = json.loads((ROOT / "search" / "plan.json").read_text())["plan"]
    trials, missing = [], []
    for c in plan:
        t = f"t{c['index']:03d}"
        d = ROOT / "records" / "trials" / t
        rj = d / "run.json"
        if not rj.is_file():
            missing.append(t); continue
        run_rec = json.loads(rj.read_text())
        run_dir = ROOT / "run" / "trials" / t
        stage, ev = completed_stage(run_dir)
        mets, notes = trial_metrics(d)
        state = "COMPLETED" if stage == "post_route_extracted" else "FAILED"
        trials.append({
            "knobs": c["knobs"], "state": state, "completed_stage": stage,
            "metrics": mets, "cost": run_rec["cost"],
            "trial": t, "runner_rc": run_rec["runner_rc"],
            "stage_evidence": ev, "notes": notes,
        })
    (ROOT / "search" / "trials.json").write_text(json.dumps(trials, indent=1) + "\n")
    print(f"trials written: {len(trials)}; missing run.json: {missing}")
    from collections import Counter
    print("  state:", dict(Counter(t["state"] for t in trials)))
    print("  completed_stage:", dict(Counter(str(t["completed_stage"]) for t in trials)))
    print("  runner_rc:", dict(Counter(t["runner_rc"] for t in trials)))
    n = Counter()
    for t in trials:
        for x in t["notes"]:
            n[x.split(":")[0]] += 1
    for k, v in n.most_common(10):
        print(f"  note x{v}: {k}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
