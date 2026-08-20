#!/usr/bin/env python3
"""A >=50-configuration PnR search, scored by the declared PPA objective, with
one published RECORD per configuration. vibe-ic ppa.html section 03, PHASE 3.

WHY A SEARCH, AND WHY IT IS OURS TO BUILD
=========================================
ORFS AutoTuner's own bottleneck is stated in its README: a useful search wants
HUNDREDS of full flow runs, so it ships a Ray cluster to get them. Running many
flows and collating their records is not a feature we would have to invent — it
is the dispatch discipline this project already runs on. That is the structural
reason a search belongs here rather than the other way round.

The unit of work is ONE `phase3_one_shot_runner` invocation over ONE private
copy of the design. MEASURED on this host 2026-08-21: 166 s wall for a complete
14-step phase 3 on a 488-cell design, of which 109 s is PnR. 50 configurations
therefore cost ~2.3 h sequential and fit inside one host at modest concurrency —
so this program does NOT ssh anywhere, and the number of runs it completed is
always printed as `n of N`, never rounded up to "the search".

WHAT A RECORD HAS TO SURVIVE
============================
1. ONE RUN TREE PER RECORD. Each configuration gets its own directory, and every
   number in its record carries the artefact path AND that artefact's sha256.
   Two artefacts wearing the same name is how one design read as both passing
   and failing on 2026-08-20; a sha beside the figure is what makes that
   detectable at the boundary instead of after it.

2. UNMEASURED IS NOT CLEAN. A configuration whose run did not produce a metric
   is recorded `NOT_MEASURED` with the reason, and it is NOT RANKED. It does not
   become a zero, it does not become a large number, and it does not quietly
   drop out of the count — `search.json` carries `scored`, `not_measured` and
   `refused` separately, and they sum to the number of configurations attempted.

3. THE WEIGHTS ARE SOMEBODY'S JUDGEMENT. Every record states whether the design
   DECLARED `ppa_weights` or INHERITED ORFS's ratio, in words, and an inherited
   ratio prints the phrase "inherited, not chosen".

4. NO SILENT CAP. If fewer than the requested number of configurations complete,
   the report says which ones did not and why. A search that covered 31 of 50
   and reads as "the search" is the same defect as a check that could not look
   and reported clean.

WHAT IS SEARCHED
================
Only knobs `phase3_one_shot_runner` ALREADY exposes on its own command line:

    --util           global placement density  (the dominant area/timing lever)
    --die-um         die size, or `auto`       (routing-resource supply)
    --spare-density  design-for-ECO spare-cell density (area + leakage)

DELIBERATELY NOT SEARCHED, stated so the coverage is not overread: the ORFS
optimization-class knobs the runner ingests from a design's OWN staged
`input/reference_flow` (TNS_END_PERCENT, CTS_CLUSTER_SIZE, CTS_CLUSTER_DIAMETER,
CTS_DISTANCE_BETWEEN_BUFFERS). They are reachable only through a channel that
means "this design staged a reference recipe", and a search writing that file
would be dressing its own guess up as the design's declaration. Widening the
space is a matter of giving those knobs their own CLI flags; it is not done here.

chip-AGNOSTIC / PDK-AGNOSTIC: the search space is expressed as multipliers and
absolute knob values with no design, PDK, process, node or vendor literal. The
project's own default run is the reference, so the search is anchored to
whatever the design is rather than to a remembered number.
"""
from __future__ import annotations

import argparse
import concurrent.futures as _cf
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ppa_objective as _obj  # noqa: E402

RC_OK = 0
RC_NO_WINNER = 1
RC_REFUSED = 2

#: The step ladder a phase-3 run declares for itself, and the artefact that
#: declares it. `step` in the objective is how many of these PASSED.
STEP_LADDER_SOURCE = "reports/orchestrator/phase3_one_shot.json"

#: The runner CLI flags this search drives, with the type each carries. Nothing
#: outside this table can be varied, which is what keeps a record reproducible
#: from the record alone.
KNOB_FLAGS: Dict[str, str] = {
    "util": "--util",
    "die_um": "--die-um",
    "spare_density": "--spare-density",
}

#: DELIBERATELY NOT A KNOB, and the reason is a measurement.
#:
#: ORFS tunes CLK_PERIOD, and on paper it is the knob this objective most wants:
#: the performance term is `percent(eff_ref, eff_run)` with
#: `eff = clk_period - min(0, worst_slack)`, so a run with POSITIVE slack earns
#: nothing for it, and a design that meets timing everywhere has a FLAT
#: performance axis however hard the search works. MEASURED on the first six
#: configurations of this search: `performance` was 0.0 in every one.
#:
#: It is still not taken. In ORFS the clock target is FLOW configuration; here
#: it is the DESIGN'S OWN declared spec — `_resolve_clock_spec` reads it from
#: the PDK-keyed table in the design's L9 document, and the SDC follows from
#: that. A search that rewrote L9 per configuration would be tuning the
#: SPECIFICATION, not the flow, and — worse — rewriting only the staged SDC
#: would leave `achievable_fmax.json:spec_period_ns` still reporting the L9
#: figure, so each record would state a clock target its own STA did not use.
#: An internally inconsistent record is worse than a flat axis.
#:
#: The flat axis is DISCLOSED instead, per search, by `axis_discrimination()`.

#: The default space. A 5 x 5 x 2 grid = 50 configurations, which is the
#: smallest grid that meets the >=50 bar without padding it with repeats.
#:
#: `util` spans the runner's own conservative default (0.30) up to a density
#: where routing pressure is real; `die_um` is expressed as `auto` plus explicit
#: square dies, since a die the design cannot route is exactly the region an
#: honest objective has to be able to score badly rather than crash on;
#: `spare_density` contrasts the runner's 2% design-for-ECO default with none.
DEFAULT_SPACE: Dict[str, List[Any]] = {
    # Global placement density — the dominant area/DRC lever, and the knob whose
    # own default carries a measured DRC history in the runner's `--util` help.
    "util": [0.20, 0.30, 0.40, 0.50, 0.60],
    # Routing-resource supply: the flow's own auto-sizing, plus fixed dies
    # spanning "comfortable" to "the design cannot route in this".
    "die_um": ["auto", "80x80", "100x100", "140x140", "200x200"],
    # Design-for-ECO spare cells: the runner's 2% default against none.
    "spare_density": [0.0, 0.02],
}

#: The reference configuration — "our own default run". Every knob left at the
#: runner's own default, so the thing the search has to beat is the flow as it
#: ships and not a strawman we picked.
BASELINE: Dict[str, Any] = {"util": 0.30, "die_um": "auto",
                            "spare_density": 0.02}


def _expand(space: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Full cartesian product, in a stable declared order."""
    keys = list(space)
    out: List[Dict[str, Any]] = [{}]
    for k in keys:
        out = [dict(c, **{k: v}) for c in out for v in space[k]]
    return out


def config_id(cfg: Dict[str, Any]) -> str:
    """A name a reader can decode without the record: every knob, in the
    declared order, value included."""
    return "_".join(
        f"{k}-{str(cfg[k]).replace('.', 'p').replace('/', '-')}"
        for k in KNOB_FLAGS if k in cfg)


def step_progress(project: Path) -> Tuple[Optional[int], Optional[int],
                                          Optional[str]]:
    """``(passed, total, None)`` from the run's OWN declared step ladder, or
    ``(None, None, reason)``.

    This is the `step` the objective's `(step/100)**-1` term consumes. It is
    read from the artefact the runner wrote about its own run — not counted from
    a log, and not inferred from which files happen to exist, because "the file
    is there" and "the step passed" are different claims and a search is exactly
    where that difference gets exploited.
    """
    path = project / STEP_LADDER_SOURCE
    if not path.exists():
        return None, None, f"{STEP_LADDER_SOURCE} absent — the run declared no "
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"{STEP_LADDER_SOURCE}: {exc}"
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, None, (f"{STEP_LADDER_SOURCE} declares no `steps[]`, so "
                            "how far this run got is unknown — which is not "
                            "the same as it having got nowhere")
    passed = sum(1 for s in steps
                 if isinstance(s, dict) and s.get("status") == "PASS")
    return passed, len(steps), None


def run_one(design: Path, out_root: Path, cfg: Dict[str, Any], top: str,
            runner: Path, container: str, timeout_s: int,
            dir_prefix: str = "") -> Dict[str, Any]:
    """Materialise one configuration in its OWN tree, run phase 3, and return
    the raw run facts. Scoring happens later and separately, so a run that
    cannot be scored still leaves a complete account of itself.

    `dir_prefix` keeps the REFERENCE run in a directory of its own. Without it
    the reference and the identically-configured member of the search space
    resolve to the same path, the second run deletes the first, and two records
    end up naming one tree — the "two artefacts wearing the same name" failure
    that made one design read as both passing and failing on 2026-08-20.
    """
    cid = config_id(cfg)
    run_dir = out_root / "runs" / (dir_prefix + cid)
    rec: Dict[str, Any] = {"config_id": cid, "knobs": dict(cfg),
                           "run_dir": str(run_dir)}
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(design, run_dir, symlinks=True)
    # A configuration must not inherit the previous configuration's silicon.
    for stale in ("phase3", "reports/phase3", "reports/orchestrator",
                  "reports/density.json"):
        p = run_dir / stale
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    argv = [sys.executable, str(runner), ".", "--top-name", top,
            "--container", container]
    for knob, flag in KNOB_FLAGS.items():
        if knob in cfg:
            argv += [flag, str(cfg[knob])]
    rec["argv"] = argv

    log = out_root / "logs" / f"{cid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(argv, cwd=run_dir, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=timeout_s)
        rec["rc"] = proc.returncode
        rec["timed_out"] = False
    except subprocess.TimeoutExpired:
        rec["rc"] = None
        rec["timed_out"] = True
    rec["wall_s"] = round(time.time() - t0, 2)
    rec["log"] = str(log.relative_to(out_root))
    return rec


def score_one(rec: Dict[str, Any], reference_metrics: Dict[str, Any],
              weights: Dict[str, float]) -> Dict[str, Any]:
    """Attach the objective to a run record, or attach the reason there is no
    score. Never both, and never neither."""
    if rec.get("setup_failed"):
        rec["verdict"] = "REFUSED"
        rec["not_scored_because"] = {"code": "CONFIG_NOT_APPLIED",
                                     "detail": rec["setup_failed"]}
        return rec
    run_dir = Path(rec["run_dir"])
    read = _obj.read_metrics(run_dir)
    rec["metrics"] = read["metrics"]
    rec["metric_sources"] = read["sources"]
    rec["metrics_unmeasured"] = read["unmeasured"]
    rec["unreadable_declared_channel"] = read["unreadable_declared_channel"]

    passed, total, why = step_progress(run_dir)
    rec["step"] = passed
    rec["stages_total"] = total
    if passed is None:
        rec["verdict"] = "NOT_MEASURED"
        rec["not_scored_because"] = {"code": "STEP_UNKNOWN", "detail": why}
        return rec

    pct = _obj.progress_step(passed, total or 0)
    rec["step_pct"] = pct
    try:
        rec["objective"] = _obj.evaluate(read["metrics"], reference_metrics,
                                         weights, pct, total)
        rec["objective"]["stages_passed"] = passed
        rec["verdict"] = "SCORED"
    except _obj.Refusal as exc:
        rec["verdict"] = ("NOT_MEASURED" if exc.rc == _obj.RC_NOT_MEASURED
                          else "REFUSED")
        rec["not_scored_because"] = {"code": exc.code, "detail": exc.message}
    return rec


def axis_discrimination(scored: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How many DISTINCT values each weighted axis actually took across the
    search — and therefore which axes contributed to the ranking at all.

    THIS IS THE HONESTY THAT A CONFIGURATION SEARCH MOST NEEDS AND THAT ORFS
    DOES NOT HAVE. A three-axis objective whose report shows three weights reads
    as three axes considered. MEASURED here, on a real 50-configuration search:

      * `performance` was 0.0 in EVERY record. Not because the search failed,
        but because ORFS's own term is `percent(eff_ref, eff_run)` with
        `eff = clk_period - min(0, worst_slack)` — a run with POSITIVE slack is
        not rewarded for it, and every configuration met timing at the same
        declared clock target.
      * `power` was identical in every record, because the step that computes it
        times the PRE-PnR synthesis netlist, so no placement choice can move it.

    Two of the three axes were therefore inert, and the ranking came from AREA
    plus the DRC penalty alone. A reader who was not present cannot deduce that
    from the score, and would reasonably assume the 10000-weight axis did the
    work. So it is COMPUTED and stated, per axis, per search.

    An axis with `distinct == 1` is reported `INERT` with its constant value.
    `INERT` is not a failure — it is a fact about this design and this space —
    but it must never be silent, which is the same rule as `NOT_MEASURED`
    applied one level up: "we varied it and it did not move" and "it could not
    move" must not read alike, and neither may read as "it was optimised".
    """
    out: Dict[str, Any] = {}
    for axis in _obj.AXES:
        vals = [r["objective"]["terms"][axis] for r in scored
                if r.get("objective")]
        uniq = sorted({round(v, 9) for v in vals})
        out[axis] = {
            "samples": len(vals),
            "distinct": len(uniq),
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "status": ("NO_SAMPLES" if not vals
                       else "INERT" if len(uniq) == 1 else "DISCRIMINATING"),
            "constant_value": uniq[0] if len(uniq) == 1 else None,
        }
    return out


def _write_record(out_root: Path, rec: Dict[str, Any]) -> str:
    path = out_root / "records" / f"{rec['config_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return str(path.relative_to(out_root))


def report_md(search: Dict[str, Any]) -> str:
    w = search["weights"]
    lines = [
        f"# PPA configuration search — `{search['design_name']}`",
        "",
        f"- attempted **{search['attempted']} of "
        f"{search.get('space_size', search['attempted'])}** configuration(s) "
        f"in the declared space; "
        f"**{search['scored']}** scored, "
        f"**{search['not_measured']}** NOT_MEASURED, "
        f"**{search['refused']}** refused",
        f"- objective: ORFS `PPAImprov`, ported; lower score is better",
        f"- weights **{w['source'].upper()}** — "
        + ", ".join(f"{a}={w['weights'][a]:g}" for a in _obj.AXES),
        f"- weight provenance: {w['provenance']}",
        f"- `step` semantics: {_obj.STEP_SEMANTICS}",
        "",
    ]
    if w["source"] == "inherited":
        lines += [
            f"> The weights above are **{_obj.INHERITED_PHRASE}**. This design "
            "declares no `ppa_weights`, so the ratio comes from ORFS. A "
            "100:1 preference for speed over power is a judgement about a "
            "market; nobody on this run made it.",
            "",
        ]
    ref = search.get("reference") or {}
    lines += [
        "## Reference — our own default run",
        "",
        f"`{ref.get('config_id', '?')}` — "
        + ", ".join(f"{k}={v}" for k, v in (ref.get("knobs") or {}).items()),
        "",
        "| metric | value |",
        "|---|---|",
    ]
    for k, v in (ref.get("metrics") or {}).items():
        lines.append(f"| `{k}` | {v} |")
    axes = search.get("axis_discrimination") or {}
    if axes:
        lines += ["", "## Which axes actually moved", "",
                  "A three-axis objective whose report shows three weights "
                  "reads as three axes considered. This table says which ones "
                  "the ranking could have come from.", "",
                  "| axis | weight | status | distinct values | range |",
                  "|---|---:|---|---:|---|"]
        for axis in _obj.AXES:
            a = axes.get(axis) or {}
            rng = ("—" if a.get("min") is None
                   else f"{a['min']:.3f} … {a['max']:.3f}")
            lines.append(
                f"| `{axis}` | {w['weights'][axis]:g} | **{a.get('status')}** "
                f"| {a.get('distinct')} | {rng} |")
        inert = [ax for ax in _obj.AXES
                 if (axes.get(ax) or {}).get("status") == "INERT"]
        if inert:
            lines += ["",
                      f"> **{', '.join('`'+i+'`' for i in inert)} took ONE "
                      "value across every scored configuration and therefore "
                      "contributed nothing to the ranking.** The ranking came "
                      "from the remaining axes and the DRC penalty. This is a "
                      "fact about this design and this search space, not a "
                      "failure — but a reader who assumed the heaviest axis "
                      "did the work would be wrong."]

    lines += ["", "## Ranking (scored configurations, best first)", "",
              "| # | config | score | ppa | DRC | penalty | step | wall s |",
              "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(search["ranking"], 1):
        o = r["objective"]
        lines.append(
            f"| {i} | `{r['config_id']}` | {o['score']:.1f} | {o['ppa']:.1f} | "
            f"{o['num_drc']:.0f} | {o['drc_penalty']:.1f} | "
            f"{o.get('stages_passed', '?')}/{o['stages_total']}"
            f" ({o['step']}%) | {r['wall_s']:.0f} |")
    unscored = search.get("unscored") or []
    lines += ["", f"## Not ranked ({len(unscored)}) — named, not dropped", ""]
    if unscored:
        lines += ["| config | verdict | why |", "|---|---|---|"]
        for r in unscored:
            why = (r.get("not_scored_because") or {})
            lines.append(f"| `{r['config_id']}` | {r['verdict']} | "
                         f"{why.get('code', '?')}: "
                         f"{str(why.get('detail', ''))[:160]} |")
    else:
        lines.append("_none — every attempted configuration was scored._")
    space = search.get("space_size")
    if isinstance(space, int) and search["attempted"] < space:
        lines += ["",
                  f"> **This run covered {search['attempted']} of {space} "
                  "configurations in the declared space.** The remainder were "
                  "not attempted. A search reported without its denominator "
                  "reads as \"we covered everything\" when it did not."]
    lines += ["", "## Verdict", "", search["verdict_line"], ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("design", type=Path,
                   help="a project tree that has already reached phase 2")
    p.add_argument("--out", type=Path, required=True,
                   help="where the runs, the records and the report go")
    p.add_argument("--top-name", default="chip_top")
    p.add_argument("--container", default="vibeic-eda")
    p.add_argument("--runner", type=Path,
                   default=Path(__file__).with_name("phase3_one_shot_runner.py"))
    p.add_argument("--jobs", type=int, default=4,
                   help="concurrent configurations (each is one full phase 3)")
    p.add_argument("--limit", type=int, default=None,
                   help="run only the first N configurations of the space. "
                        "The report still names the total, so a limited run "
                        "cannot read as a complete one.")
    p.add_argument("--timeout-s", type=int, default=3600)
    p.add_argument("--rerender", action="store_true",
                   help="re-render SEARCH_REPORT.md from an existing "
                        "search.json and stop. Runs nothing and measures "
                        "nothing: the report is a VIEW of the record, so it "
                        "must be reproducible from the record alone — "
                        "including after the renderer changes.")
    p.add_argument("--space", type=Path, default=None,
                   help="JSON {knob: [values]} overriding the default grid")
    args = p.parse_args(argv)

    design = args.design.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    if args.rerender:
        src = out / "search.json"
        if not src.exists():
            print(f"[ppa_search] no {src} to re-render from", file=sys.stderr)
            return RC_REFUSED
        search = json.loads(src.read_text(encoding="utf-8"))
        (out / "SEARCH_REPORT.md").write_text(report_md(search),
                                              encoding="utf-8")
        print(f"[ppa_search] re-rendered {out / 'SEARCH_REPORT.md'} from "
              f"{src} — no run was made and no metric was re-read")
        return RC_OK

    l19, l19_rel, unreadable = _obj.load_l19(design)
    if unreadable:
        print(f"[ppa_search] REFUSED: {unreadable}", file=sys.stderr)
        return RC_REFUSED
    try:
        weights = _obj.resolve_weights(l19, l19_rel)
    except _obj.Refusal as exc:
        print(f"[ppa_search] REFUSED {exc.code}: {exc.message}", file=sys.stderr)
        return RC_REFUSED
    print(f"[ppa_search] weights {weights['source'].upper()}: "
          + ", ".join(f"{a}={weights['weights'][a]:g}" for a in _obj.AXES))
    if weights["source"] == "inherited":
        print(f"[ppa_search] {_obj.INHERITED_PHRASE}")

    space = (json.loads(args.space.read_text(encoding="utf-8"))
             if args.space else DEFAULT_SPACE)
    configs = _expand(space)
    total_space = len(configs)
    if args.limit is not None:
        configs = configs[:args.limit]

    # The reference runs FIRST and alone: nothing can be scored until the thing
    # the search has to beat exists, and a reference sharing the machine with 8
    # concurrent flows is a different measurement.
    print(f"[ppa_search] reference (our own default run): {BASELINE}")
    ref_rec = run_one(design, out, dict(BASELINE), args.top_name, args.runner,
                      args.container, args.timeout_s, dir_prefix="REFERENCE_")
    ref_read = _obj.read_metrics(Path(ref_rec["run_dir"]))
    ref_rec["metrics"] = ref_read["metrics"]
    ref_rec["metric_sources"] = ref_read["sources"]
    ref_rec["metrics_unmeasured"] = ref_read["unmeasured"]
    ref_rec["role"] = "reference"
    r_pass, r_total, r_why = step_progress(Path(ref_rec["run_dir"]))
    ref_rec["step"], ref_rec["stages_total"] = r_pass, r_total
    ref_rec["config_id"] = "REFERENCE_" + ref_rec["config_id"]
    _write_record(out, ref_rec)

    blocking = sorted(k for k, v in ref_read["unmeasured"].items()
                      if not v.get("non_blocking"))
    if blocking:
        search = {
            "design_name": design.name, "design": str(design),
            "weights": weights, "attempted": 1, "scored": 0,
            "not_measured": 1, "refused": 0, "space_size": total_space,
            "reference": ref_rec, "ranking": [], "unscored": [ref_rec],
            "verdict_line": (
                "**REFUSED — the reference run did not produce "
                f"{blocking}.** Nothing can be scored against a reference that "
                "was not measured, and scoring the configurations against each "
                "other instead would silently change the question from 'better "
                "than our default' to 'better than the others'."),
        }
        (out / "search.json").write_text(
            json.dumps(search, indent=2) + "\n", encoding="utf-8")
        (out / "SEARCH_REPORT.md").write_text(report_md(search),
                                              encoding="utf-8")
        print(f"[ppa_search] REFUSED: reference unmeasured: {blocking}",
              file=sys.stderr)
        return RC_REFUSED

    print(f"[ppa_search] {len(configs)} of {total_space} configuration(s), "
          f"jobs={args.jobs}")
    records: List[Dict[str, Any]] = []
    with _cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = {pool.submit(run_one, design, out, cfg, args.top_name,
                            args.runner, args.container, args.timeout_s): cfg
                for cfg in configs}
        for n, fut in enumerate(_cf.as_completed(futs), 1):
            rec = fut.result()
            rec = score_one(rec, ref_read["metrics"], weights["weights"])
            rec["weights"] = weights
            rec["reference_config_id"] = ref_rec["config_id"]
            rec["record_path"] = _write_record(out, rec)
            records.append(rec)
            o = rec.get("objective")
            print(f"[ppa_search] {n}/{len(configs)} {rec['config_id']} "
                  f"{rec['verdict']}"
                  + (f" score={o['score']:.1f} drc={o['num_drc']:.0f}"
                     if o else ""), flush=True)

    scored = [r for r in records if r["verdict"] == "SCORED"]
    unscored = [r for r in records if r["verdict"] != "SCORED"]
    ranking = sorted(scored, key=lambda r: r["objective"]["score"])

    # The reference scored against ITSELF: every percent term is 0, so `ppa` is
    # the upper bound and the score is that times the reference's own progress
    # multiplier. Derived from the same code path as every other record — a
    # hand-written "the default scores X" is exactly the number a search would
    # be tempted to get wrong.
    ref_score: Optional[float] = None
    if ref_score is None:
        try:
            ref_score = _obj.evaluate(
                ref_read["metrics"], ref_read["metrics"], weights["weights"],
                _obj.progress_step(r_pass or 0, r_total or 0) or 1,
                r_total)["score"]
        except _obj.Refusal:
            ref_score = None

    winner = ranking[0] if ranking else None
    beat = ([r for r in ranking if r["objective"]["score"] < ref_score]
            if ref_score is not None else [])
    if winner is None:
        verdict_line = ("**NO WINNER — no configuration produced a scorable "
                        f"run.** {len(unscored)} of {len(records)} attempted "
                        "configurations are named above with their reason.")
        rc = RC_NO_WINNER
    elif ref_score is None:
        verdict_line = ("**NO COMPARISON — the reference could not be scored**, "
                        f"so `{winner['config_id']}` is the best of the search "
                        "and NOT a claim that it beats our default run.")
        rc = RC_NO_WINNER
    elif not beat:
        verdict_line = (
            f"**NO IMPROVEMENT.** The best configuration "
            f"`{winner['config_id']}` scores {winner['objective']['score']:.1f} "
            f"against the default run's {ref_score:.1f} (lower is better), so "
            "the default is not beaten. Reported as the result it is.")
        rc = RC_NO_WINNER
    else:
        _ax = axis_discrimination(scored)
        _inert = [a for a in _obj.AXES if _ax[a]["status"] == "INERT"]
        verdict_line = (
            f"**{len(beat)} of {len(records)} configuration(s) beat our own "
            f"default run.** Best: `{winner['config_id']}` at "
            f"{winner['objective']['score']:.1f} vs the default's "
            f"{ref_score:.1f} (lower is better), "
            f"DRC {winner['objective']['num_drc']:.0f}, progress "
            f"{winner['objective'].get('stages_passed', '?')}/"
            f"{winner['objective']['stages_total']}."
            + (f" NOTE: {', '.join(_inert)} took one value across every "
               "configuration and contributed nothing to this ranking."
               if _inert else ""))
        rc = RC_OK

    search = {
        "program": "ppa_search",
        "design_name": design.name, "design": str(design),
        "weights": weights,
        "objective": "ORFS PPAImprov, ported; lower is better",
        "orfs_source": _obj.ORFS_SOURCE,
        "step_semantics": _obj.STEP_SEMANTICS,
        "space": space, "space_size": total_space,
        "attempted": len(records),
        "scored": len(scored), "not_measured":
            sum(1 for r in unscored if r["verdict"] == "NOT_MEASURED"),
        "refused": sum(1 for r in unscored if r["verdict"] == "REFUSED"),
        "reference": ref_rec, "reference_score": ref_score,
        "axis_discrimination": axis_discrimination(scored),
        "ranking": ranking, "unscored": unscored,
        "beat_reference": [r["config_id"] for r in beat],
        "verdict_line": verdict_line,
    }
    (out / "search.json").write_text(json.dumps(search, indent=2) + "\n",
                                     encoding="utf-8")
    (out / "SEARCH_REPORT.md").write_text(report_md(search), encoding="utf-8")
    print(f"[ppa_search] {verdict_line}")
    print(f"[ppa_search] records: {out / 'records'}  report: "
          f"{out / 'SEARCH_REPORT.md'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
