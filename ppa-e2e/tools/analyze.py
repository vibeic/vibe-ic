#!/usr/bin/env python3
"""Post-sweep: re-extract every arm, run the shipped gates, publish everything."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jppae2e")
PLUGIN = ROOT / "wt/vibe-ic-marketplace/plugins/vibe-ic"
PROGRAMS = PLUGIN / "programs"
PY = sys.executable
VIEWS = [{"stage": "post_route_extracted", "process": "ss"},
         {"stage": "post_route_extracted", "process": "ff"}]


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          timeout=kw.pop("timeout", 900), cwd=str(PROGRAMS), **kw)


def arms():
    plan = json.loads((ROOT / "search/plan.json").read_text())["plan"]
    out = [("baseline", ROOT / "run/baseline", ROOT / "records/baseline",
            {"die_um": "auto", "placement_density": "0.30",
             "spare_cell_density": "0.02"})]
    for c in plan:
        t = f"t{c['index']:03d}"
        out.append((t, ROOT / f"run/trials/{t}", ROOT / f"records/trials/{t}",
                    c["knobs"]))
    return out


def main() -> int:
    todo = arms()
    print(f"== re-extract + adapt + bridge + contract over {len(todo)} arm(s)")
    fails = []
    for label, rundir, recdir, knobs in todo:
        if not (rundir / "phase3").is_dir():
            fails.append(f"{label}: no phase3 tree"); continue
        recdir.mkdir(parents=True, exist_ok=True)
        for cmd in ([PY, ROOT / "tools/extract_run.py", rundir, recdir, "--label", label],
                    [PY, ROOT / "tools/adapt_records.py", recdir],
                    [PY, ROOT / "tools/signoff_records.py", rundir, recdir],
                    [PY, ROOT / "tools/gen_declaration.py", rundir, recdir, label,
                     *[f"{k}={v}" for k, v in sorted(knobs.items())]]):
            r = run(cmd)
            if r.returncode not in (0, 2):
                fails.append(f"{label}: {Path(str(cmd[1])).name} rc={r.returncode} "
                             f"{r.stderr.strip()[:200]}")
        # feasibility, shipped-records-only and bridged
        try:
            flat = json.loads((recdir / "records_flat.json").read_text())
            bridge = json.loads((recdir / "signoff_bridge_records.json").read_text())
        except Exception as exc:
            fails.append(f"{label}: records unreadable ({exc})"); continue
        for name, recs in (("shipped_only", flat), ("bridged", flat + bridge)):
            p = recdir / f"feasibility_{name}.json"
            p.write_text(json.dumps({"required_views": VIEWS, "candidates": [
                {"candidate_id": label, "metrics": recs}]}, indent=1) + "\n")
            run([PY, PROGRAMS / "ppa_feasibility_check.py", "--candidates", p,
                 "--json", recdir / f"feasibility_{name}_report.json"])
    print(f"   problems: {len(fails)}")
    for f in fails[:20]:
        print("   -", f)
    (ROOT / "records/extract_problems.json").write_text(json.dumps(fails, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
