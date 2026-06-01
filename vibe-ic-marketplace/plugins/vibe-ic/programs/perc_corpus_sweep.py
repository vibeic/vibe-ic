#!/usr/bin/env python3
"""perc_corpus_sweep.py — run the v0.2.4-2.11 PERC-equivalent sign-off chain across a CORPUS
of already-routed designs, deterministically, with NO container needed.

Captured v0.2.12 from the 2026-06-01 Shape-A 21-IC benchmark_ic sweep
(benchmark_ic/RESULT_PERC_CORPUS_v0211.md): that sweep was driven by an ad-hoc /tmp script.
This promotes it to a first-class, tested plugin capability so any corpus PERC sweep is one
command — `python3 perc_corpus_sweep.py <dir1> [<dir2> ...]` — instead of a throwaway.

For each design directory it finds the most-routed DEF (prefers `*routed*` > `chip_top` >
`post_hold`) under `<dir>/phase3/**` and runs the SHIPPED pure structural checks from
`phase3_one_shot_runner.py` (imported, NOT re-implemented):
  - well-tap presence (latch-up)         → _welltap_presence_check
  - ESD pad-ring presence                → _esd_pad_ring_presence
  - ESD discharge-path topology          → _esd_discharge_topology (only if a pad ring exists)
  - cross-voltage-domain                 → _xdomain_levelshifter_check

HONESTY (inherited from the checks): these are open-source STRUCTURAL screens, NOT a commercial
PERC run. A WELLTAP_GAP / XDOMAIN_GAP is a conclusive structural exposure; PRESENT/OK results are
NECESSARY-BUT-NOT-SUFFICIENT (device-physics stays MANUAL). A corpus-wide GAP is NOT proof of a
current-runner bug — validate against a FRESH same-version control before triaging (the
stale-artifact lesson from the v0.2.11 sweep, where 14/14 0-tap were pre-tapcell-fix DEFs).

Usage:
    python3 perc_corpus_sweep.py <design_dir> [<design_dir> ...]   # JSONL per IC + summary
    python3 perc_corpus_sweep.py --json <dir> ...                  # JSON array only, no summary
    python3 perc_corpus_sweep.py --def <routed.def> --name <id>    # single explicit DEF
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase3_one_shot_runner as _p  # noqa: E402  (shipped PERC functions — single source)


def _pick_routed_def(design_dir: str) -> Optional[str]:
    """Find the most-routed DEF under <design_dir>/phase3/**. Prefers a routed DEF, then a
    chip_top DEF, then post_hold, then any DEF. Returns None if the dir has no phase3 DEF."""
    cands = glob.glob(os.path.join(design_dir, "phase3", "**", "*.def"), recursive=True)
    if not cands:
        return None

    def _score(f: str) -> int:
        b = os.path.basename(f).lower()
        return (("routed" in b) * 4 + ("chip_top" in b) * 2 + ("post_hold" in b) * 1
                - ("floorplan" in b) * 3)   # floorplan DEF is pre-tapcell → deprioritise
    return sorted(cands, key=_score, reverse=True)[0]


def sweep_one(def_path: str, name: Optional[str] = None) -> Dict[str, Any]:
    """Run the full PERC structural chain on ONE routed DEF. Pure; no container."""
    p = Path(def_path)
    out: Dict[str, Any] = {"name": name or p.stem, "def": str(def_path)}
    if not p.is_file():
        out["error"] = "DEF not found"
        return out
    comps = _p._parse_def_components(p)
    out["components"] = len(comps)
    esd = _p._esd_pad_ring_presence(comps)
    out["esd_presence"] = {"status": esd["status"],
                           "esd_presence": esd.get("esd_presence"),
                           "pads": esd["pad_count"], "esd_cells": esd["esd_count"]}
    if esd["status"] != "N/A":
        nt = _p._parse_def_net_terminals(p.read_text(errors="ignore"))
        topo = _p._esd_discharge_topology(comps, nt)
        out["esd_topology"] = {"status": topo["status"], "gaps": len(topo["gaps"]),
                               "unrated": topo["unrated_clamps"][:4]}
    wt = _p._welltap_presence_check(comps)
    out["welltap"] = {"status": wt["status"], "n_tap": wt["n_tap"],
                      "reason": wt.get("reason", "")}
    xd = _p._xdomain_levelshifter_check(p, comps)
    out["xdomain"] = {"status": xd["status"], "result": xd["result"],
                      "n_power_domains": len(xd["power_domains"]),
                      "n_ground_domains": len(xd["ground_domains"]),
                      "n_crossing": xd["n_crossing"], "source": xd["domain_source"]}
    return out


def sweep_dirs(dirs: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in dirs:
        name = os.path.basename(d.rstrip("/"))
        dp = _pick_routed_def(d)
        if dp is None:
            rows.append({"name": name, "def": None, "error": "no routed DEF"})
            continue
        rows.append(sweep_one(dp, name=name))
    return rows


def summarize(rows: List[Dict[str, Any]]) -> str:
    """Human summary + systemic counts (the corpus-scale signal)."""
    swept = [r for r in rows if "error" not in r]
    no_def = [r for r in rows if r.get("error")]
    lines = [f"{'IC':28s} {'comps':>7s}  {'ESD':9s} {'welltap':14s} xdomain(pwr/gnd,cross)"]
    for r in sorted(swept, key=lambda x: -x.get("components", 0)):
        e = r.get("esd_presence", {}); w = r.get("welltap", {}); x = r.get("xdomain", {})
        lines.append(f"{r['name']:28s} {r.get('components', 0):7d}  "
                     f"{str(e.get('status', '')):9s} {str(w.get('status', '')):14s} "
                     f"{x.get('status', '')}({x.get('n_power_domains', '')}/"
                     f"{x.get('n_ground_domains', '')},{x.get('n_crossing', '')})")
    gap = sum(1 for r in swept if r.get("welltap", {}).get("status") == "WELLTAP_GAP")
    na = sum(1 for r in swept if r.get("esd_presence", {}).get("status") == "N/A")
    xna = sum(1 for r in swept if r.get("xdomain", {}).get("status") == "N/A")
    xinc = sum(1 for r in swept if r.get("xdomain", {}).get("status") == "INCOMPLETE")
    lines += [
        "", "=== systemic ===",
        f"  swept: {len(swept)}   no-DEF (excluded): {len(no_def)}",
        f"  welltap WELLTAP_GAP (0-tap latch-up exposure): {gap}/{len(swept)}",
        f"  ESD N/A (core macro, no pad ring): {na}/{len(swept)}",
        f"  xdomain N/A (single supply): {xna}/{len(swept)}   INCOMPLETE: {xinc}/{len(swept)}",
        "  NOTE: a corpus-wide GAP is NOT a current-runner bug until checked vs a FRESH",
        "        same-version control (stale-artifact lesson, RESULT_PERC_CORPUS_v0211.md).",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dirs", nargs="*", help="design directories (each with phase3/**/*.def)")
    ap.add_argument("--def", dest="def_path", help="a single explicit routed DEF")
    ap.add_argument("--name", help="name for the single --def design")
    ap.add_argument("--json", action="store_true", help="emit a JSON array only (no summary)")
    args = ap.parse_args(argv)

    if args.def_path:
        rows = [sweep_one(args.def_path, name=args.name)]
    elif args.dirs:
        rows = sweep_dirs(args.dirs)
    else:
        ap.error("give one or more design dirs, or --def <routed.def>")
        return 2

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(json.dumps(r))
        print("\n" + summarize(rows), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
