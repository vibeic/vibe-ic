#!/usr/bin/env python3
"""Build the head-to-head record for (default configuration) vs (search winner),
then hand it to the SHIPPED ppa_head_to_head_check.py and print what it says.

Every field is read from the arms' own published records and contracts. Nothing
is asserted that an artefact does not carry -- including the two facts that
decide the outcome: the stage the power number really belongs to, and whether
either arm is feasible.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jppae2e")
PROGRAMS = ROOT / "wt/vibe-ic-marketplace/plugins/vibe-ic/programs"
PY = sys.executable

#: The DECLARED objective of this search. Declared HERE and in RESULT.md
#: because the design declares none: L19_CONSTRAINTS_PDK.json carries
#: die_area_budget_um=null and power_budget_uw=null.
OBJECTIVE = ("area.design_report.um2", {"stage": "post_route"}, "lower")


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def pick(recs, metric, want):
    return [r for r in recs if r.get("metric") == metric
            and all((r.get("scope") or {}).get(k) == v for k, v in want.items())]


def one_measured(recs, metric, want):
    hits = [r for r in pick(recs, metric, want) if r.get("status") == "MEASURED"]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    vals = {r.get("value") for r in hits}
    return hits[0] if len(vals) == 1 else None


def axis_records(recdir: Path):
    recs = load(recdir / "records_flat.json") or []
    area = one_measured(recs, *OBJECTIVE[:2])
    # timing: the ONLY stage-stamped post-route setup view this flow produces
    timing = one_measured(recs, "timing.setup.wns_ns",
                          {"stage": "post_route_extracted", "process": "ss",
                           "check": "setup"})
    power = one_measured(recs, "power.total_w", {"group": "Total"})
    return recs, area, timing, power


def metric_block(r, unit_override=None, scale=1.0):
    if r is None:
        return None
    out = {"status": r["status"], "unit": unit_override or r.get("unit", ""),
           "scope": dict(r.get("scope") or {})}
    if r.get("status") == "MEASURED":
        out["value"] = r["value"] * scale
    if r.get("reason"):
        out["reason"] = r["reason"]
    if r.get("source"):
        out["source"] = {k: v for k, v in r["source"].items()
                         if k in ("path", "sha256", "tool", "parser")}
    return out


def feas_checks(recdir: Path):
    """The `checks` block, derived from the BRIDGED feasibility adjudication --
    the more generous of the two runs. NOT_CHECKED where the axis was
    UNDETERMINED: an axis nobody could decide is not a clean one."""
    rep = load(recdir / "feasibility_bridged_report.json")
    if not rep or not rep.get("candidates"):
        return {"_unavailable": {"status": "NOT_CHECKED",
                                 "source": "no feasibility report"}}, "UNDETERMINED"
    c = rep["candidates"][0]
    floor = ("drc", "lvs", "antenna", "setup", "hold", "drv")
    # `_ppa/benchmark.derive_feasibility` requires an INTEGER `violations` on
    # every floor check; a bare `status: CLEAN` is counted as NOT_CHECKED. The
    # counts below come from the bridge records, which read the sign-off
    # artefacts -- and LVS, which is a verdict and not a count, can only be
    # expressed to that function as `violations: 0`. See RESULT.md F-18.
    counts = {}
    bridge = load(recdir / "signoff_bridge_records.json") or []
    by = {}
    for r in bridge:
        if r["status"] == "MEASURED":
            by.setdefault(r["metric"], r)
    if "physical.drc.violations" in by:
        counts["drc"] = int(by["physical.drc.violations"]["value"])
    if "physical.antenna.violations" in by:
        counts["antenna"] = int(by["physical.antenna.violations"]["value"])
    if "physical.lvs.verdict" in by:
        counts["lvs"] = 0 if by["physical.lvs.verdict"]["value"] in ("MATCH", "CLEAN") else 1
    out = {}
    for a in c["axes"]:
        if a["axis"] not in floor:
            continue
        st = {"SATISFIED": "CLEAN", "VIOLATED": "VIOLATIONS"}.get(
            a["status"], "NOT_CHECKED")
        row = {"status": st,
               "source": f"ppa_feasibility_check: {a['status']} "
                         f"({','.join(a['codes'])})"}
        if a["axis"] in counts and st != "NOT_CHECKED":
            row["violations"] = counts[a["axis"]]
        out[a["axis"]] = row
    return out, c["verdict"]


def arm(label, recdir: Path, role, config_source, tuned, knobs,
        power_override=None):
    contract = load(recdir / "contract.json")
    if contract is None:
        raise SystemExit(f"[CANNOT CHECK] {label}: no contract.json")
    problem = contract["identities"]["problem"]["digest"]
    recs, area, timing, power = axis_records(recdir)
    checks, verdict = feas_checks(recdir)
    return {
        "flow": label, "role": role,
        "design": {"spec_sha256": problem, "pdk": "sky130A",
                   "clock_target_ns": 10.0, "corners": ["ss", "tt", "ff"]},
        "contract": {"sha256": problem,
                     "source": str(recdir / "contract.json")},
        "measurement_basis": "post_route_sta",
        "config_source": config_source,
        "tuned_by_this_project": tuned,
        "ppa": {"area_um2": metric_block(area),
                "timing_wns_ns": metric_block(timing),
                "power_mw": metric_block(power_override if power_override is not None
                                         else power,
                                         unit_override="mW", scale=1000.0)},
        "feasibility": {"checks": checks},
        "tuning": {"supported": False},
        "_knobs": knobs, "_feasibility_verdict": verdict,
    }


def diagnostic_power(recdir: Path):
    """The labelled post-route power diagnostic for this arm, if one exists."""
    d = load(recdir / "power_postroute_records.json")
    if not d:
        return None
    for r in d.get("metrics", []):
        if r["metric"] == "power.total_w" and (r.get("scope") or {}).get("group") == "Total":
            return r
    return None


def build(tag, use_diagnostic_power):
    win = load(ROOT / "search/winner.json")
    if win is None:
        print("[CANNOT CHECK] search/winner.json absent", file=sys.stderr); return 2
    bdir = ROOT / "records/baseline"
    sdir = ROOT / f"records/trials/{win['trial']}"
    bp = diagnostic_power(bdir) if use_diagnostic_power else None
    sp = diagnostic_power(sdir) if use_diagnostic_power else None
    if use_diagnostic_power and (bp is None or sp is None):
        print(f"[CANNOT CHECK] {tag}: a diagnostic power record is missing "
              f"(baseline={bp is not None}, subject={sp is not None})",
              file=sys.stderr)
        return 2
    b = arm("vibe-ic-phase3-defaults", bdir, "baseline",
            "phase3_one_shot_runner.py argparse defaults, unchanged: "
            "--die-um auto --util 0.30 --spare-density 0.02", False,
            {"die_um": "auto", "placement_density": "0.30",
             "spare_cell_density": "0.02"}, power_override=bp)
    s = arm("vibe-ic-phase3-searched", sdir, "subject",
            f"winner of the 60-point PnR search published in "
            f"search/manifest.json ({win['knobs']})", True, win["knobs"],
            power_override=sp)
    doc = {"schema": "vibeic.ppa.comparison.v2", "arms": [b, s]}
    out = ROOT / f"records/{tag}.json"
    out.write_text(json.dumps(doc, indent=1) + "\n")
    r = subprocess.run([PY, str(PROGRAMS / "ppa_head_to_head_check.py"), str(out),
                        "--json", str(ROOT / f"records/{tag}_report.json")],
                       capture_output=True, text=True, timeout=300,
                       cwd=str(PROGRAMS))
    print("=" * 70)
    print(f"### {tag}")
    print(r.stdout.strip())
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    print(f"ppa_head_to_head_check rc={r.returncode}")
    return 0


def main() -> int:
    a = build("head_to_head", False)
    b = build("head_to_head_diagnostic_power", True)
    return max(a or 0, b or 0)


if __name__ == "__main__":
    raise SystemExit(main())
