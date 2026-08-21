#!/usr/bin/env python3
"""Drive the SHIPPED `_ppa/backends/openroad.py` over one phase-3 run tree and
publish its canonical records.  A CALLER of the machinery, not a copy of it:
every number below is produced by the shipped library function.

The objective this search declares -- `area.design_report.um2` at
`scope.stage = post_route` -- is the record OpenROAD's own
`report_design_area` produces, and it is read here from the shipped parser so
that "what the tool said" and "what this lane published" cannot diverge.

Usage: extract_area.py <run-dir> <out-dir> [--label L]
Exit codes follow docs/PPA_INTERFACES.md §1: 0 records produced, 2 nothing to
read (NOT_MEASURED -- never a zero).
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

PLUGIN = Path(os.environ.get(
    "JXLAYER_PLUGIN",
    "/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic"))
sys.path.insert(0, str(PLUGIN / "programs"))

from _ppa.backends import openroad as or_be   # noqa: E402
from _ppa.backends import yosys as ys_be      # noqa: E402
from _ppa import canonical_json as cj         # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir"); ap.add_argument("out_dir")
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)
    run, out = Path(a.run_dir).resolve(), Path(a.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    pnr = run / "phase3" / "stage3" / "pnr"
    doc, why, recs = None, [], []
    if pnr.is_dir():
        outcome = or_be.parse_run(str(pnr))
        doc = outcome.document()
        recs = list(outcome.records)
    else:
        why.append(f"no pnr run dir at {pnr}")
    # proxy (pre-PnR) area from the shipped yosys parser, published ALONGSIDE
    # and never mixed with the post-route objective: they are different metrics
    # at different scopes (PPA_INTERFACES §2).
    slog = run / "phase2" / "stage2" / "synth" / "yosys.log"
    ydoc = None
    if slog.is_file():
        try:
            ydoc = ys_be.records_from_stat(
                slog.read_text(errors="replace"), stage="synth_mapped",
                kind="mapped", top="spm", path=str(slog))
        except Exception as exc:                       # noqa: BLE001
            why.append(f"yosys transcript unreadable: {exc}")
    else:
        why.append(f"no yosys transcript at {slog}")

    payload = {"schema": "vibeic.ppa.records.v1", "label": a.label,
               "run_dir": str(run),
               "openroad": doc, "yosys": ydoc,
               "notes": why}
    (out / "records.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    obj = [r for r in recs
           if r.get("metric") == "area.design_report.um2"]
    if not obj:
        print(f"[extract_area] NOT_MEASURED: no area.design_report.um2 record "
              f"({'; '.join(why) or 'parser produced none'})", file=sys.stderr)
        (out / "objective.json").write_text(json.dumps(
            {"metric": "area.design_report.um2", "status": "NOT_MEASURED",
             "reason": "; ".join(why) or "the shipped OpenROAD parser produced "
                       "no such record from this run", "value": None},
            indent=2) + "\n", encoding="utf-8")
        return 2
    r = obj[0]
    (out / "objective.json").write_text(
        json.dumps(r, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[extract_area] {a.label}: area.design_report.um2 = {r.get('value')} "
          f"{r.get('unit')} status={r.get('status')} "
          f"stage={(r.get('scope') or {}).get('stage')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
