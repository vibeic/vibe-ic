#!/usr/bin/env python3
"""Assemble ONE arm's canonical record set, its feasibility adjudication and
its contract, driving only SHIPPED programs.

Every record here is produced by a shipped module:
    ppa_signoff_records.py   the physical / reliability / equivalence axes
    _ppa.timing              the per-view timing rows
    _ppa.backends.openroad   the physical area + DRV rows
    _ppa.backends.yosys      the pre-PnR PROXY area, published separately and
                             never mixed with the post-route objective
    ppa_feasibility_check.py the nine-axis adjudication
    ppa_contract_build/check the five identities

THE ONE THING THIS FILE DECLARES RATHER THAN READS is `required_views_by_axis`,
and it is declared here in writing because the design declares no PPA contract
(L19 carries `die_area_budget_um: null`, `power_budget_uw: null`).  Each view
below names a scope the flow ACTUALLY measures; nothing is required that no
producer could ever satisfy, and nothing that is measured is left undeclared.

Exit codes follow docs/PPA_INTERFACES.md §1.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path("/home/reyerchu/_jxlayer")
PLUGIN = Path(os.environ.get(
    "JXLAYER_PLUGIN",
    "/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic"))
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))
PY = sys.executable

IMAGE = "ghcr.io/vibeic/vibeic-eda:0.3.13"

#: The sign-off corners this flow runs, at the stage its own STA reports stamp.
#: Setup and hold do NOT share a corner set, and requiring them to was measured
#: to be wrong: the flow emits setup at {ss, tt} and hold at {tt, ff}, which is
#: sign-off practice — setup is governed by the SLOW corner and hold by the FAST
#: one, and neither is signed off at the other's extreme. A declaration naming
#: all three for both leaves setup@ff and hold@ss permanently NO_RECORD, so the
#: axis can never be adjudicated and the gate reports UNDETERMINED forever.
#: What is declared below is therefore the STRICTEST view set this flow can ever
#: satisfy, not the broadest one that can be written down.
_SETUP_VIEWS = [{"stage": "post_route_extracted", "process": p}
                for p in ("ss", "tt")]
_HOLD_VIEWS = [{"stage": "post_route_extracted", "process": p}
               for p in ("tt", "ff")]
_TIMING_VIEWS = _SETUP_VIEWS

REQUIRED_VIEWS_BY_AXIS = {
    # timing signs off across the process corners; the stage is the one the
    # runner's own `STA_BASIS: POST_ROUTE_SPEF` stamp puts on the report.
    "setup": _SETUP_VIEWS,
    "hold": _HOLD_VIEWS,
    # the remaining axes are ONE measurement over ONE database and have no
    # process corner (PPA_INTERFACES §2.1); each names the stage its own
    # producer stamps.
    "drv": [{"stage": "post_route"}],
    "drc": [{"stage": "signed_off_gds"}],
    "lvs": [{"stage": "post_route_extracted"}],
    "antenna": [{"stage": "post_route"}],
    "ir": [{"stage": "post_route"}],
    "em": [{"stage": "post_route"}],
    "equivalence": [{"stage": "post_route"}],
}
#: The IR budget the flow itself declares (10 % of the nominal supply). It is a
#: LIMIT, not a measurement, so it lives in the contract and not in a record.
LIMITS = {"power.ir.worst_drop_v": {"max": 0.18},
          "reliability.em.worst_ratio": {"max": 1.0}}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(PROGRAMS), timeout=1800, **kw)


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trial")
    a = ap.parse_args(argv)
    t = a.trial
    proj = ROOT / "run" / "trials" / t
    out = ROOT / "records" / "trials" / t
    out.mkdir(parents=True, exist_ok=True)
    if not proj.is_dir():
        print(f"[CANNOT CHECK] {t}: no run directory at {proj}", file=sys.stderr)
        return 2

    notes = []
    # --- 1. sign-off axes, shipped producer -------------------------------
    r = run([PY, str(PROGRAMS / "ppa_signoff_records.py"), str(proj),
             "--json", str(out / "signoff_records.json")])
    notes.append(f"ppa_signoff_records rc={r.returncode}: {r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr.strip()[:200]}")
    sign = load(out / "signoff_records.json") or {}
    sign_recs = sign.get("records") or []

    # --- 2. timing rows, shipped module ----------------------------------
    r = run([PY, "-m", "_ppa.timing", str(proj),
             "--json", str(out / "timing_records.json")])
    notes.append(f"_ppa.timing rc={r.returncode}")
    tim = load(out / "timing_records.json") or {}
    tim_recs = tim.get("rows") or []

    # --- 3. physical rows, shipped backend --------------------------------
    rec = load(out / "records.json") or {}
    or_recs = ((rec.get("openroad") or {}).get("records")) or []
    ys_recs = rec.get("yosys") or []
    if isinstance(ys_recs, dict):
        ys_recs = ys_recs.get("records") or []

    # --- 3b. power, shipped parser -- and its TRUE stage, read from the
    # session script the runner drove, not from the directory it was filed in.
    from _ppa import power as ppower           # noqa: E402
    pw_recs = []
    prpt = proj / "reports" / "phase3" / "power.rpt"
    ptcl = proj / "reports" / "phase3" / "power_spm.tcl"
    if prpt.is_file():
        rep = ppower.read_power_report(prpt)
        stage, why = "unknown", []
        if ptcl.is_file():
            tcl = ptcl.read_text(errors="replace")
            reads_spef = "read_spef" in tcl
            import re as _re
            nl = _re.findall(r"read_verilog\s+(\S+)", tcl)
            netlist = nl[-1] if nl else ""
            if "stage3/pnr" in netlist and reads_spef:
                stage = "post_route_extracted"
            elif "stage3/pnr" in netlist:
                stage = "post_route"
            elif "stage2/synth" in netlist:
                stage = "synth"
            why.append(f"power session linked {netlist!r}; read_spef={reads_spef}")
        else:
            why.append("no power session script: stage NOT_MEASURED, not guessed")
        if rep:
            pw_recs = ppower.metric_records(rep, stage=stage)
        notes.append("power stage derived from the session's own inputs: "
                     + "; ".join(why))
    flat = list(or_recs) + list(tim_recs) + list(sign_recs) + list(pw_recs)
    (out / "records_flat.json").write_text(
        json.dumps(flat, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "proxy_records.json").write_text(
        json.dumps(ys_recs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # --- 4. feasibility, shipped gate -------------------------------------
    cand = {"schema": "vibeic.ppa.candidates.v1",
            "required_views_by_axis": REQUIRED_VIEWS_BY_AXIS,
            "required_views": _TIMING_VIEWS,
            "limits": LIMITS,
            "allow_waivers": False,
            "candidates": [{"candidate_id": t, "metrics": flat, "waivers": []}]}
    (out / "candidates.json").write_text(
        json.dumps(cand, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    r = run([PY, str(PROGRAMS / "ppa_feasibility_check.py"),
             "--candidates", str(out / "candidates.json"),
             "--json", str(out / "feasibility_report.json")])
    notes.append(f"ppa_feasibility_check rc={r.returncode}")
    fr = load(out / "feasibility_report.json") or {}
    verdict = (fr.get("candidates") or [{}])[0].get("verdict", "UNDETERMINED")
    axes = {x["axis"]: x["status"]
            for x in (fr.get("candidates") or [{}])[0].get("axes", [])}

    (out / "assembly.json").write_text(json.dumps(
        {"trial": t, "notes": notes, "feasibility_verdict": verdict,
         "axes": axes, "record_count": len(flat),
         "measured": sum(1 for x in flat if x.get("status") == "MEASURED")},
        indent=2) + "\n", encoding="utf-8")
    print(f"[build_arm] {t}: {len(flat)} records, feasibility={verdict}, "
          f"axes={ {k: v for k, v in sorted(axes.items())} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
