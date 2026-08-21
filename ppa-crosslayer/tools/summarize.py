#!/usr/bin/env python3
"""Every figure RESULT.md quotes, computed from the published records.

A number that appears in the prose and nowhere in an artefact is a number
nobody can check, so this writes `records/summary.json` and prints the tables
in the shape RESULT.md uses them."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jxlayer")
TR = ROOT / "records" / "trials"


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def trials():
    out = {}
    for d in sorted(TR.iterdir()):
        if not d.is_dir() or d.name == "t000":
            continue
        run, obj = load(d / "run.json"), load(d / "objective.json")
        if not run:
            continue
        rec = {"trial": d.name,
               "rtl_variant": run["levers"]["rtl_variant"],
               "synthesis_strategy": run["levers"]["synthesis_strategy"],
               **run["pnr_knobs"],
               "runner_rc": run["runner_rc"],
               "cost": run.get("cost", {}),
               "objective_status": (obj or {}).get("status", "ABSENT"),
               "objective_um2": (obj or {}).get("value"),
               "objective_reason": (obj or {}).get("reason")}
        a = load(d / "assembly.json")
        if a:
            rec["feasibility_verdict"] = a["feasibility_verdict"]
            rec["axes"] = a["axes"]
        pw = load(d / "diag" / "power_postroute_records.json")
        if pw:
            t = [r for r in pw["metrics"] if r["metric"] == "power.total_w"
                 and r["scope"].get("group") == "Total"]
            if t:
                rec["power_postroute_w"] = t[0]["value"]
        syn = ROOT / "run" / "trials" / d.name / "phase2/stage2/synth/synth.log"
        if syn.is_file():
            import re
            m = re.findall(r"Chip area for module '\\?spm': ([0-9.]+)",
                           syn.read_text(errors="replace"))
            if m:
                rec["synth_area_um2"] = float(m[-1])
        out[d.name] = rec
    return out


def equivalence():
    out = {}
    for p in sorted((ROOT / "equiv2").glob("*/reports/equiv_*.json")):
        d = load(p)
        if d:
            out[p.parent.parent.name] = {
                "status": d["status"], "exit_code": d["exit_code"],
                "mode": d["mode"], "latency_offset": d["latency_offset_cycles"],
                "compared": d["compared_points"], "proven": d["proven_points"],
                "unproven": d["unproven_points"],
                "counterexample": d["counterexample"],
                "bounded_refutation": d.get("bounded_refutation"),
                "bounded_depth": d.get("bounded_refutation_depth"),
                "elapsed_sec": d.get("elapsed_sec")}
    for p in sorted((ROOT / "equivL").glob("*/reports/equiv_*.json")):
        d = load(p)
        if d:
            out[p.parent.parent.name + " (long budget)"] = {
                "status": d["status"], "exit_code": d["exit_code"],
                "compared": d["compared_points"], "proven": d["proven_points"],
                "unproven": d["unproven_points"],
                "elapsed_sec": d.get("elapsed_sec")}
    return out


def head_to_heads():
    out = {}
    for p in sorted((ROOT / "records").glob("h2h_*_report.json")):
        d = load(p)
        if d is None:
            continue
        out[p.name.replace("_report.json", "")] = {
            k: v for k, v in d.items() if k not in ("record",)}
    return out


def main():
    t = trials()
    ok = {k: v for k, v in t.items() if v["objective_status"] == "MEASURED"}
    doc = {"trials": t, "equivalence": equivalence(),
           "head_to_head": head_to_heads(),
           "counts": {"total": len(t), "measured": len(ok),
                      "not_measured": len(t) - len(ok)}}
    (ROOT / "records" / "summary.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{'trial':6s} {'rtl_variant':14s} {'synth':9s} {'util':5s} {'spare':5s} "
          f"{'objective':>10s} {'synth_area':>10s} {'power_W':>10s}  feas")
    for k, v in sorted(t.items(), key=lambda kv: (kv[1]["objective_um2"] is None,
                                                  kv[1]["objective_um2"] or 0)):
        o = v["objective_um2"]
        print(f"{k:6s} {v['rtl_variant']:14s} {v['synthesis_strategy']:9s} "
              f"{v['placement_density']:5s} {v['spare_cell_density']:5s} "
              f"{(f'{o:.0f}' if o is not None else 'NOT_MEAS'):>10s} "
              f"{(f'{v.get(chr(115)+chr(121)+chr(110)+chr(116)+chr(104)+chr(95)+chr(97)+chr(114)+chr(101)+chr(97)+chr(95)+chr(117)+chr(109)+chr(50)):.1f}' if v.get('synth_area_um2') else '-'):>10s} "
              f"{(f'{v[chr(112)+chr(111)+chr(119)+chr(101)+chr(114)+chr(95)+chr(112)+chr(111)+chr(115)+chr(116)+chr(114)+chr(111)+chr(117)+chr(116)+chr(101)+chr(95)+chr(119)]:.6f}' if v.get('power_postroute_w') else '-'):>10s}  "
              f"{v.get('feasibility_verdict','-')}")
    print()
    print("equivalence:")
    for k, v in sorted(equivalence().items()):
        print(f"  {k:26s} {v['status']:24s} rc={v['exit_code']} "
              f"proven={v['proven']}/{v['compared']} unproven={v['unproven']} "
              f"({v.get('elapsed_sec')}s)")
    print()
    print(f"{doc['counts']['measured']}/{doc['counts']['total']} trials produced "
          f"a MEASURED objective")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
