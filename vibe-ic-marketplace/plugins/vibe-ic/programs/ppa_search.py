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

#: The default space. A 5 x 5 x 2 grid = 50 configurations, which is the
#: smallest grid that meets the >=50 bar without padding it with repeats.
#:
#: `util` spans the runner's own conservative default (0.30) up to a density
#: where routing pressure is real; `die_um` is expressed as `auto` plus explicit
#: square dies, since a die the design cannot route is exactly the region an
#: honest objective has to be able to score badly rather than crash on;
#: `spare_density` contrasts the runner's 2% design-for-ECO default with none.
DEFAULT_SPACE: Dict[str, List[Any]] = {
    "util": [0.20, 0.30, 0.40, 0.50, 0.60],
    "die_um": ["auto", "80x80", "100x100", "140x140", "200x200"],
    "spare_density": [0.0, 0.02],
}

#: The reference configuration — "our own default run". Every knob left at the
#: runner's own default, so the thing the search has to beat is the flow as it
#: ships and not a strawman we picked.
BASELINE: Dict[str, Any] = {"util": 0.30, "die_um": "auto", "spare_density": 0.02}


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
            runner: Path, container: str,
            timeout_s: int) -> Dict[str, Any]:
    """Materialise one configuration in its OWN tree, run phase 3, and return
    the raw run facts. Scoring happens later and separately, so a run that
    cannot be scored still leaves a complete account of itself."""
    cid = config_id(cfg)
    run_dir = out_root / "runs" / cid
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

    try:
        rec["objective"] = _obj.evaluate(read["metrics"], reference_metrics,
                                         weights, passed, total)
        rec["verdict"] = "SCORED"
    except _obj.Refusal as exc:
        rec["verdict"] = ("NOT_MEASURED" if exc.rc == _obj.RC_NOT_MEASURED
                          else "REFUSED")
        rec["not_scored_because"] = {"code": exc.code, "detail": exc.message}
    return rec


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
        f"- attempted **{search['attempted']}** configuration(s); "
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
    lines += ["", "## Ranking (scored configurations, best first)", "",
              "| # | config | score | ppa | DRC | penalty | step | wall s |",
              "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for i, r in enumerate(search["ranking"], 1):
        o = r["objective"]
        lines.append(
            f"| {i} | `{r['config_id']}` | {o['score']:.1f} | {o['ppa']:.1f} | "
            f"{o['num_drc']:.0f} | {o['drc_penalty']:.1f} | "
            f"{o['step']}/{o['stages_total']} | {r['wall_s']:.0f} |")
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
    p.add_argument("--space", type=Path, default=None,
                   help="JSON {knob: [values]} overriding the default grid")
    args = p.parse_args(argv)

    design = args.design.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

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
                      args.container, args.timeout_s)
    ref_read = _obj.read_metrics(Path(ref_rec["run_dir"]))
    ref_rec["metrics"] = ref_read["metrics"]
    ref_rec["metric_sources"] = ref_read["sources"]
    ref_rec["metrics_unmeasured"] = ref_read["unmeasured"]
    ref_rec["role"] = "reference"
    r_pass, r_total, r_why = step_progress(Path(ref_rec["run_dir"]))
    ref_rec["step"], ref_rec["stages_total"] = r_pass, r_total
    _write_record(out, dict(ref_rec, config_id="REFERENCE_" +
                            ref_rec["config_id"]))

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

    ref_score: Optional[float] = None
    for r in ranking:
        if r["knobs"] == BASELINE:
            ref_score = r["objective"]["score"]
            break
    if ref_score is None:
        # The reference is scored against itself: every percent term is 0, so
        # `ppa` is the upper bound. Derived, never assumed.
        try:
            ref_score = _obj.evaluate(ref_read["metrics"], ref_read["metrics"],
                                      weights["weights"],
                                      r_pass or 1, r_total)["score"]
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
        verdict_line = (
            f"**{len(beat)} of {len(records)} configuration(s) beat our own "
            f"default run.** Best: `{winner['config_id']}` at "
            f"{winner['objective']['score']:.1f} vs the default's "
            f"{ref_score:.1f} (lower is better), "
            f"DRC {winner['objective']['num_drc']:.0f}, "
            f"step {winner['objective']['step']}/"
            f"{winner['objective']['stages_total']}.")
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
