#!/usr/bin/env python3
"""Every figure RESULT.md quotes, computed once, so the prose and the artefacts
cannot drift apart."""
from __future__ import annotations
import json, glob, statistics, collections
from pathlib import Path

ROOT = Path("/home/reyerchu/_jppae2e")


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def total_power(recdir):
    d = load(Path(recdir) / "power.json")
    if not d:
        return None
    for r in d["metrics"]:
        if r["metric"] == "power.total_w" and r["scope"].get("group") == "Total":
            return r["value"]
    return None


def objective(recdir):
    d = load(Path(recdir) / "records_flat.json") or []
    hits = [r for r in d if r["metric"] == "area.design_report.um2"
            and r["status"] == "MEASURED"
            and (r.get("scope") or {}).get("stage") == "post_route"]
    return hits[0]["value"] if len(hits) == 1 else None


def main():
    out = {}
    trials = load(ROOT / "search/trials.json") or []
    win = load(ROOT / "search/winner.json") or {}
    man = load(ROOT / "search/manifest.json") or {}
    plan = {f"t{c['index']:03d}": c["knobs"]
            for c in (load(ROOT / "search/plan.json") or {}).get("plan", [])}

    costs = [t["cost"] for t in trials]
    w = [c["wall_seconds"] for c in costs if c.get("wall_seconds")]
    cp = [c["cpu_seconds"] for c in costs if c.get("cpu_seconds")]
    rss = [c["peak_rss_mb"] for c in costs if c.get("peak_rss_mb")]
    out["sweep"] = {
        "trials": len(trials),
        "states": dict(collections.Counter(t["state"] for t in trials)),
        "completed_stage": dict(collections.Counter(str(t["completed_stage"]) for t in trials)),
        "runner_rc": dict(collections.Counter(t["runner_rc"] for t in trials)),
        "wall_s": {"min": min(w), "median": statistics.median(w), "max": max(w),
                   "sum_h": round(sum(w) / 3600, 3)},
        "cpu_s": {"min": min(cp), "median": statistics.median(cp), "max": max(cp),
                  "sum_h": round(sum(cp) / 3600, 3)},
        "peak_rss_mb": {"min": min(rss), "median": statistics.median(rss), "max": max(rss)},
    }

    base_obj = objective(ROOT / "records/baseline")
    objs = {}
    for t in trials:
        v = objective(ROOT / f"records/trials/{t['trial']}")
        if v is not None:
            objs[t["trial"]] = v
    out["objective"] = {
        "metric": "area.design_report.um2", "unit": "um^2",
        "stage": "post_route", "better_is": "lower",
        "baseline": base_obj, "n": len(objs),
        "distinct_values": len(set(objs.values())),
        "min": min(objs.values()), "max": max(objs.values()),
        "median": statistics.median(objs.values()),
        "spread_pct": round((max(objs.values()) / min(objs.values()) - 1) * 100, 2),
        "winner": win.get("trial"), "winner_knobs": win.get("knobs"),
        "winner_value": win.get("objective_value"),
        "vs_baseline_pct": (round((win.get("objective_value") - base_obj) / base_obj * 100, 2)
                            if base_obj and win.get("objective_value") else None),
    }

    p = {t["trial"]: total_power(ROOT / f"records/trials/{t['trial']}") for t in trials}
    pv = collections.Counter(v for v in p.values() if v is not None)
    out["power_invariance"] = {
        "n": sum(pv.values()), "distinct_values": len(pv),
        "values": dict(pv),
        "baseline": total_power(ROOT / "records/baseline"),
        "diagnostic_postroute": (lambda d: (
            [r["value"] for r in d["metrics"] if r["metric"] == "power.total_w"
             and r["scope"].get("group") == "Total"][0]) if d else None)(
            load(ROOT / "records/baseline/power_postroute_records.json")),
    }

    lev = {}
    for name in ("die_um", "placement_density", "spare_cell_density"):
        g = collections.defaultdict(list)
        for t, v in objs.items():
            g[plan[t][name]].append(v)
        lev[name] = {k: {"n": len(v), "mean": round(statistics.mean(v), 1),
                         "min": min(v), "max": max(v)} for k, v in sorted(g.items())}
    out["lever_effect"] = lev

    fs = collections.Counter(); fb = collections.Counter()
    axes_b = collections.defaultdict(collections.Counter)
    for d in [ROOT / "records/baseline"] + [ROOT / f"records/trials/{t['trial']}" for t in trials]:
        r1, r2 = load(d / "feasibility_shipped_only_report.json"), load(d / "feasibility_bridged_report.json")
        if r1: fs[r1["verdict"]] += 1
        if r2:
            fb[r2["verdict"]] += 1
            for a in r2["candidates"][0]["axes"]:
                axes_b[a["axis"]][a["status"]] += 1
    out["feasibility"] = {"shipped_only": dict(fs), "bridged": dict(fb),
                          "bridged_axes": {k: dict(v) for k, v in axes_b.items()}}

    out["manifest"] = {
        "candidates": len(man.get("candidates", [])),
        "budget_spent": man.get("budget_spent"),
        "sentence": (man.get("what_the_budget_bought") or {}).get("sentence"),
        "frontier_included": len((man.get("frontier_input") or {}).get("included", [])),
        "frontier_excluded": dict(collections.Counter(
            x.get("code") for x in (man.get("frontier_input") or {}).get("excluded", []))),
        "feasibility_source": (man.get("toolchain") or {}).get("feasibility_source"),
    }
    (ROOT / "records/summary.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
