#!/usr/bin/env python3
"""perc_corpus_sweep.py — run the v0.2.4-2.11 PERC-equivalent sign-off chain across a CORPUS
of already-routed designs, deterministically, with NO container needed.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
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

ARTIFACT-VINTAGE GUARD (suggested_fix #4 of ORGANIC-20260601-...-stale-pre-tapcell-fix):
each sweep also runs `artifact_vintage_guard`, which WARNs when a routed DEF with > N std
cells has 0 valid taps AND an older/sibling DEF in the same lineage is ALSO 0-tap — the
structural signature of a STALE pre-tapcell-fix artifact (the whole lineage never ran the
tapcell step), as opposed to a LIVE current-runner regression. It never fails a build; it is
a triage WARN so a corpus PERC number is not mis-cited as a current-quality signal.

REACH (v1.9.79+): a corpus sweep whose targets carry no routed DEF used to print a table of
`no routed DEF` rows and exit 0 — the same exit code, to every automated consumer, as a sweep
that ran the PERC chain on every IC and found nothing wrong. It now accounts for how many
targets actually entered `sweep_one` (`_sweep_reach.SweepReach`) and routes rc 2 +
`VACUOUS_PASS:` through the shipped `_vacuous_exit` convention when that count is ZERO. A
PARTIAL sweep still exits 0: most corpora contain core macros and pre-layout blocks the chain
genuinely cannot reach, and failing those would be a worse defect than the silence it replaces.

Usage:
    python3 perc_corpus_sweep.py <design_dir> [<design_dir> ...]   # JSONL per IC + summary
    python3 perc_corpus_sweep.py --json <dir> ...                  # JSON array only, no summary
    python3 perc_corpus_sweep.py --def <routed.def> --name <id>    # single explicit DEF
    python3 perc_corpus_sweep.py --vintage <routed.def>            # ONLY the vintage guard, JSON
    python3 perc_corpus_sweep.py --no-vintage <dir> ...           # skip the vintage guard
    python3 perc_corpus_sweep.py --report R.json <dir> ...        # rows + reach block, for
                                                                  # sweep_reach_check --report
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
import _sweep_reach as _sr  # noqa: E402  (aggregate reach disclosure)
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


# --------------------------------------------------------------- artifact-vintage guard
# suggested_fix #4 of ORGANIC-20260601-benchmark-ic-corpus-stale-pre-tapcell-fix:
# distinguish a STALE pre-tapcell artifact (a routed DEF whose whole lineage never ran the
# tapcell step) from a LIVE current-runner regression (a one-off 0-tap in an otherwise
# tap-bearing pipeline). Purely structural + chip-AGNOSTIC: no design/vendor literal, no
# version string parsed from the file (none is recorded reliably). The "older-version /
# sibling 0-tap" signal is derived from the DEF lineage itself.
_STALE_STD_CELL_MIN = 200   # below this a 0-tap DEF is a legit small block, not a regression


def _count_std_cells(components: List["tuple"]) -> int:
    """Placed transistor-bearing std cells (same exclusion rule as _welltap_presence_check —
    drop tap/fill/decap/diode/endcap/boundary/antenna physical-only masters)."""
    return sum(1 for _i, m in components
               if not _p._WELLTAP_TOKEN_RE.search(m.lower())
               and not any(t in m.lower() for t in ("decap", "fill", "diode", "tapvpwr",
                                                     "_endcap", "boundary", "antenna")))


def _stage_score(basename: str) -> int:
    """Pipeline-stage ordinal from a DEF basename (floorplan < placed < cts < hold < routed
    < chip_top). Used only to order sibling DEFs oldest→newest for the lineage scan."""
    b = basename.lower()
    for tok, rank in (("floorplan", 0), ("placed", 1), ("cts", 2), ("post_hold", 3),
                      ("hold", 3), ("routed", 4), ("chip_top", 5)):
        if tok in b:
            return rank
    return 2   # unknown mid-pipeline


def artifact_vintage_guard(routed_def: str,
                           sibling_defs: Optional[List[str]] = None,
                           std_cell_min: int = _STALE_STD_CELL_MIN) -> Dict[str, Any]:
    """WARN when a routed DEF with > std_cell_min placed std cells has 0 valid well/substrate
    taps AND an *older* sibling DEF (an earlier pipeline stage, or an older-version artifact of
    the same design) is ALSO 0-tap — the signature of a STALE pre-tapcell-fix artifact whose
    whole lineage never ran the tapcell step (the v0.1.46/v0.1.49 fix), as opposed to a LIVE
    current-runner regression.

    DISCRIMINATOR (chip-AGNOSTIC, purely structural):
      * a CURRENT run inserts taps from the `placed` stage onward (the FRESH spm control:
        floorplan=0 → placed/cts/hold/routed all=67). So in a healthy lineage the routed DEF
        is tap-bearing; a 0-tap routed DEF whose *earlier* sibling stages are ALSO 0-tap means
        the tapcell step never fired anywhere in the lineage = stale pre-fix artifact.
      * if the routed DEF HAS taps → not stale (verdict OK, never warns).
      * if std-cell count <= std_cell_min → legit small / floorplan block where 0 taps is not
        yet a regression signal (a floorplan DEF is pre-tapcell BY DESIGN) → verdict OK.
      * if there is NO 0-tap sibling (e.g. the only DEF is this one, or every sibling is
        tap-bearing) → cannot prove stale-vs-regression from lineage alone → verdict
        SUSPECT_LIVE (treat as a possible live regression: re-run a FRESH control to triage).

    verdict ∈ {OK, STALE_PRE_TAPCELL (warn), SUSPECT_LIVE (warn — needs fresh control), NA}.
    This NEVER fails a build; it is a triage WARN so a corpus PERC number is not mis-cited as a
    current-quality signal (the stale-artifact lesson, RESULT_PERC_CORPUS_v0211.md)."""
    rp = Path(routed_def)
    out: Dict[str, Any] = {"def": str(routed_def), "verdict": "NA", "warn": False}
    if not rp.is_file():
        out["reason"] = "routed DEF not found"
        return out
    comps = _p._parse_def_components(rp)
    wt = _p._welltap_presence_check(comps)
    n_std = _count_std_cells(comps)
    out.update({"n_std_cells": n_std, "n_tap": wt["n_tap"], "welltap": wt["status"]})

    if wt["status"] != "WELLTAP_GAP":
        # PRESENT (taps inserted → not stale) or NA (no std cells → not a placed block)
        out["verdict"] = "OK"
        out["reason"] = ("routed DEF is tap-bearing — not a stale pre-tapcell artifact"
                         if wt["status"] == "WELLTAP_PRESENT"
                         else "no placed std cells — not a placed block (vintage N/A)")
        return out

    if n_std <= std_cell_min:
        out["verdict"] = "OK"
        out["reason"] = (f"only {n_std} std cell(s) (<= {std_cell_min}) — legit small / "
                         "floorplan-class block; 0 taps not yet a regression signal")
        return out

    # routed DEF: many std cells, 0 valid taps. Scan the lineage for an OLDER 0-tap sibling.
    sibs = sibling_defs if sibling_defs is not None else _sibling_defs_for(routed_def)
    routed_rank = _stage_score(rp.name)
    older_zero_tap: List[str] = []
    for sf in sibs:
        sp = Path(sf)
        if sp.resolve() == rp.resolve() or not sp.is_file():
            continue
        if _stage_score(sp.name) > routed_rank:
            continue   # only OLDER-or-equal stages count as the prior-vintage lineage
        scomps = _p._parse_def_components(sp)
        if _p._welltap_presence_check(scomps)["n_tap"] == 0:
            older_zero_tap.append(sp.name)

    if older_zero_tap:
        out["verdict"] = "STALE_PRE_TAPCELL"
        out["warn"] = True
        out["older_zero_tap_siblings"] = sorted(older_zero_tap)
        out["reason"] = (
            f"{n_std} std cells, 0 taps, AND {len(older_zero_tap)} older/sibling DEF(s) "
            f"also 0-tap ({', '.join(sorted(older_zero_tap)[:4])}) — the tapcell step never "
            "ran anywhere in this lineage = STALE pre-tapcell-fix artifact. Regenerate "
            "through the current runner before citing its PERC number as a current-quality "
            "signal; this is NOT proof of a live current-runner bug.")
        return out

    out["verdict"] = "SUSPECT_LIVE"
    out["warn"] = True
    out["reason"] = (
        f"{n_std} std cells, 0 taps, but NO older 0-tap sibling found in the lineage — cannot "
        "prove stale-vs-regression structurally. Treat as a POSSIBLE live regression and "
        "re-run a FRESH same-version control to triage (stale-artifact lesson).")
    return out


def _sibling_defs_for(routed_def: str) -> List[str]:
    """All other DEFs in the same directory as the routed DEF — the design's pipeline-stage
    lineage (floorplan/placed/cts/hold/routed/chip_top). Chip-agnostic: just same-dir DEFs."""
    rp = Path(routed_def)
    return [str(f) for f in sorted(rp.parent.glob("*.def")) if f.resolve() != rp.resolve()]


def sweep_one(def_path: str, name: Optional[str] = None,
              vintage: bool = True) -> Dict[str, Any]:
    """Run the full PERC structural chain on ONE routed DEF. Pure; no container.

    When `vintage` is True (default) it also runs the artifact-vintage guard
    (suggested_fix #4) over the DEF's same-dir lineage and attaches the verdict, so a
    corpus PERC number is auto-flagged as stale-pre-tapcell vs a possible live regression."""
    p = Path(def_path)
    out: Dict[str, Any] = {"name": name or p.stem, "def": str(def_path),
                           "perc_chain_ran": False}
    if not p.is_file():
        out["error"] = "DEF not found"
        return out
    # From here down the PERC decision point IS entered. The flag is set
    # structurally, at the point of entry — never inferred later from the
    # presence or absence of an `error` string, because deriving a reach claim
    # from prose is the same defect one layer down (_vacuous_exit's rule).
    out["perc_chain_ran"] = True
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
    if vintage:
        vg = artifact_vintage_guard(str(p))
        out["vintage"] = {"verdict": vg["verdict"], "warn": vg["warn"],
                          "reason": vg.get("reason", ""),
                          "older_zero_tap_siblings": vg.get("older_zero_tap_siblings", [])}
    return out


def sweep_dirs(dirs: List[str], vintage: bool = True) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in dirs:
        name = os.path.basename(d.rstrip("/"))
        dp = _pick_routed_def(d)
        if dp is None:
            rows.append({"name": name, "def": None, "error": "no routed DEF",
                         "perc_chain_ran": False})
            continue
        rows.append(sweep_one(dp, name=name, vintage=vintage))
    return rows


def reach_of(rows: List[Dict[str, Any]]) -> "_sr.SweepReach":
    """How many corpus targets actually entered the PERC chain.

    Reads each row's structural `perc_chain_ran` flag — set inside `sweep_one`
    at the point of entry — rather than re-deriving the answer from the row's
    prose. A corpus of 21 ICs none of which carries a routed DEF produces 21
    rows, a full table and, before this, rc 0.
    """
    reach = _sr.SweepReach(unit="design directory", decision_points=("perc_chain",))
    for r in rows:
        if r.get("perc_chain_ran"):
            reach.reached(r.get("name") or r.get("def"), point="perc_chain")
        else:
            reach.not_reached(r.get("name") or r.get("def") or "<unnamed>",
                              str(r.get("error") or "no routed DEF found"))
    if not rows:
        reach.declare_empty_corpus(
            "no design directory or --def target was supplied to the sweep")
    return reach


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
    v_stale = sum(1 for r in swept
                  if r.get("vintage", {}).get("verdict") == "STALE_PRE_TAPCELL")
    v_susp = sum(1 for r in swept
                 if r.get("vintage", {}).get("verdict") == "SUSPECT_LIVE")
    lines += [
        "", "=== systemic ===",
        f"  {reach_of(rows).line()}",
        f"  swept: {len(swept)}   no-DEF (excluded): {len(no_def)}",
        f"  welltap WELLTAP_GAP (0-tap latch-up exposure): {gap}/{len(swept)}",
        f"  ESD N/A (core macro, no pad ring): {na}/{len(swept)}",
        f"  xdomain N/A (single supply): {xna}/{len(swept)}   INCOMPLETE: {xinc}/{len(swept)}",
        f"  vintage STALE_PRE_TAPCELL (whole-lineage 0-tap, regenerate before citing): "
        f"{v_stale}/{len(swept)}",
        f"  vintage SUSPECT_LIVE (0-tap routed, no 0-tap sibling — needs fresh control): "
        f"{v_susp}/{len(swept)}",
        "  NOTE: a corpus-wide GAP is NOT a current-runner bug until checked vs a FRESH",
        "        same-version control (stale-artifact lesson, RESULT_PERC_CORPUS_v0211.md).",
        "  NOTE: vintage=STALE_PRE_TAPCELL is the structural proof the lineage predates the",
        "        tapcell-insertion fix; vintage=SUSPECT_LIVE means triage as a possible",
        "        regression (re-run a fresh control) rather than assume stale.",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dirs", nargs="*", help="design directories (each with phase3/**/*.def)")
    ap.add_argument("--def", dest="def_path", help="a single explicit routed DEF")
    ap.add_argument("--name", help="name for the single --def design")
    ap.add_argument("--json", action="store_true", help="emit a JSON array only (no summary)")
    ap.add_argument("--no-vintage", action="store_true",
                    help="skip the artifact-vintage (stale-pre-tapcell) guard")
    ap.add_argument("--vintage", dest="vintage_def",
                    help="run ONLY the artifact-vintage guard on one routed DEF + print JSON")
    ap.add_argument("--report", metavar="PATH",
                    help="write {rows, reach} here — the document "
                         "`sweep_reach_check.py --report` consumes")
    args = ap.parse_args(argv)

    if args.vintage_def:
        # Single-target diagnostic mode, not a corpus sweep: there is no
        # aggregate to be vacuous about, so the reach contract does not apply.
        print(json.dumps(artifact_vintage_guard(args.vintage_def), indent=2))
        return 0

    do_vintage = not args.no_vintage
    if args.def_path:
        rows = [sweep_one(args.def_path, name=args.name, vintage=do_vintage)]
    elif args.dirs:
        rows = sweep_dirs(args.dirs, vintage=do_vintage)
    else:
        ap.error("give one or more design dirs, or --def <routed.def>")
        return 2

    reach = reach_of(rows)
    if args.json:
        # The stdout document stays the ROW ARRAY its consumers already parse;
        # the reach block rides on --report so adopting the contract cannot
        # break a caller that indexes rows by position.
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(json.dumps(r))
        print("\n" + summarize(rows), file=sys.stderr)
    if args.report:
        doc: Dict[str, Any] = {"sweep": "perc_corpus_sweep", "rows": rows}
        _sr.attach(doc, reach)
        Path(args.report).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    # A sweep that entered the PERC chain on NOTHING is not a clean corpus
    # result; rc 2 + the sentinel are the two signals flow_compliance_check
    # actually consumes. A partial sweep (>= 1 target reached) stays rc 0.
    reach.announce("perc_corpus_sweep")
    return reach.exit_code(passed=True)


if __name__ == "__main__":
    raise SystemExit(main())
