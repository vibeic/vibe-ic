#!/usr/bin/env python3
"""run_metrics.py — one per-step metrics schema, and "better or worse than last time".

WHY THIS EXISTS (vibe-ic#1080)
==============================
We could not mechanically answer "is this run better or worse than the last
one". OpenROAD-flow-scripts answers it with one `diff`, because every stage
emits metrics through the same wrapper into one flat namespace:

    flow/scripts/flow.sh:15   $OPENROAD_CMD ... -metrics "$LOG_DIR/$1.json"
    flow/scripts/detail_route.tcl:1   utl::set_metrics_stage "detailedroute__{}"

giving `<stage>__<domain>__<...>__<name>`:

    "cts__timing__setup__ws": -1.39289
    "cts__design__instance__area": 4795.85
    "cts__timing__drv__setup_violation_count": 67

and their aggregator does almost nothing (`flow/util/genMetrics.py` is
glob-and-merge). We had 129 gate invocations already writing
`--json reports/.../x.json` and no schema, no aggregator and no differ over any
of them.

WHAT THIS DOES NOT DO, AND WHY THAT IS THE POINT
================================================
It is ORACLE-FREE. It records what happened; it does not assert what should have
happened. Nothing here has an opinion about whether 67 violations is acceptable
— only about whether it was 67 last time and is 71 now. Every gate in this repo
already owns the "should" question; not one of them owned the "changed" one.

WHY IT HARVESTS RATHER THAN REQUIRING 62 STEPS TO EMIT
======================================================
#1080 proposes "require every step to emit it". The cheaper and stricter route
is available because the steps ALREADY emit: 129 declared `--json` outputs,
written by the program that computed the number. Harvesting those is not the
thing #1080 forbids — that is re-parsing a LOG, which is a proxy for the
measurement rather than the measurement (lie-shape #12). Reading the structured
artefact the tool itself wrote is the measurement.

So `harvest` REFUSES a declared output that is not `.json`, rather than falling
back to a regex. A metric this program cannot get honestly is one it does not
report, and it says which.

THE SCHEMA
==========
    <step>__<key>__<subkey>__…__<leaf>

`<step>` is the flow's own step id, so the prefix is fixed by the flow and not
by a name anybody types. Nesting flattens on `__`. Values are kept as:

    int / float        a number
    bool               a number (0/1) — a verdict that flips IS a QoR change
    str                a state, compared for equality only
    list               its LENGTH, as `<…>__count`

DIRECTION IS DECLARED, NEVER GUESSED
====================================
"Better or worse" needs polarity, and polarity is the one place a metrics tool
can quietly become an oracle. `_POLARITY` is an explicit, auditable table keyed
on the LAST segment of the metric name. Anything it does not match is reported
as `CHANGED (direction not declared)` — printed, never silently scored as
neutral, because a silent neutral is how a regression hides.

chip-AGNOSTIC: it reads JSON the flow declares. No design, PDK, vendor or IC
name appears anywhere.

USAGE
    run_metrics.py harvest --project P [--flow F] [--out OUT]
    run_metrics.py diff BEFORE.json AFTER.json [--json OUT] [--fail-on-regression]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RC_OK = 0
RC_REGRESSED = 1
RC_NOT_CHECKED = 2

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent
FLOW_YAML = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

#: `--json <path>` as the flow declares it inside a gate clause.
_JSON_ARG = re.compile(r"--json\s+(\S+)")

#: Direction, keyed on the LAST `__` segment. Stated here and nowhere else, so a
#: reader can audit every claim of "better" in one place. Absence is not
#: neutrality — an unmatched name is reported as direction-not-declared.
_POLARITY: Dict[str, int] = {
    # smaller is better
    "count": -1, "violations": -1, "violation": -1, "errors": -1, "error": -1,
    "warnings": -1, "warning": -1, "failures": -1, "failed": -1, "area": -1,
    "power": -1, "wirelength": -1, "drc": -1, "unproven": -1, "stubs": -1,
    "todo": -1, "skipped": -1, "missing": -1,
    # larger is better
    "slack": 1, "ws": 1, "tns": 1, "coverage": 1, "passed": 1, "proven": 1,
    "compared": 1, "checked": 1, "examined": 1, "equivalent": 1, "present": 1,
}

#: Prefixes that INVERT the word they qualify. Without these, last-word keying
#: cannot tell `compared_points` (up is better) from `non_equivalent_points`
#: (up is worse): both end in `points`, and both were reported as
#: direction-not-declared on the first real harvest — the two most obviously
#: directional metrics in the sample.
_NEGATORS = ("non", "un", "not", "no", "in")

UP, DOWN, FLAT = "BETTER", "WORSE", "SAME"
NEW, GONE, UNDECLARED = "NEW", "GONE", "CHANGED"


def _flatten(prefix: str, node: Any, out: Dict[str, Any]) -> None:
    """`{"a": {"b": 1}}` under prefix `s` becomes `s__a__b = 1`.

    A list contributes its LENGTH rather than its contents: `findings: [...]`
    is a QoR number (how many), and its elements are evidence rather than
    metrics. Recording both would double-count every finding.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            _flatten(f"{prefix}__{k}" if prefix else str(k), v, out)
    elif isinstance(node, list):
        out[f"{prefix}__count"] = len(node)
    elif isinstance(node, bool):
        out[prefix] = int(node)
    elif isinstance(node, (int, float)):
        out[prefix] = node
    elif isinstance(node, str):
        out[prefix] = node
    # None is dropped: "this field was not computed" is not a measurement, and
    # recording it as 0 would make an absent number look like a good one.


def declared_outputs(flow: Path) -> List[Tuple[str, str]]:
    """`[(step_id, json_path)]` the flow's gate clauses declare.

    Read from the YAML STRUCTURE where possible and from the clause command
    string only for the `--json` argument, which is where the flow states it.
    """
    try:
        import yaml  # noqa: PLC0415
        doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    except Exception as exc:                                  # pragma: no cover
        raise RuntimeError(f"cannot read the flow: {exc}") from exc
    pairs: List[Tuple[str, str]] = []

    def walk(node: Any, step: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("program_exit_zero", "advisory_program_exit_zero") \
                        and isinstance(v, str):
                    m = _JSON_ARG.search(v)
                    if m:
                        pairs.append((step, m.group(1)))
                else:
                    walk(v, step)
        elif isinstance(node, list):
            for v in node:
                walk(v, step)

    for st in (doc or {}).get("steps", []) or []:
        if not isinstance(st, dict):
            continue
        walk(st.get("gate"), str(st.get("id", "?")))
    return pairs


def harvest(project: Path, flow: Path) -> Dict[str, Any]:
    """Read every declared per-step JSON that exists and flatten it.

    Returns `{"metrics": {...}, "sources": [...], "refused": [...],
    "absent": [...]}`. All four are reported: a harvest that quietly dropped
    half the steps and printed a confident number would be the check-that-lies
    shape this repo removes one at a time.
    """
    metrics: Dict[str, Any] = {}
    sources: List[str] = []
    refused: List[str] = []
    absent: List[str] = []
    for step, rel in declared_outputs(flow):
        if not rel.endswith(".json"):
            # #1080: emit from the tool, never by re-parsing a log. A non-JSON
            # artefact would have to be regexed, and a regex over a log is a
            # PROXY for the measurement rather than the measurement.
            refused.append(f"step {step}: {rel} is not .json — would need a "
                           f"log regex, which is a proxy for the measurement")
            continue
        p = project / rel
        if not p.is_file():
            absent.append(f"step {step}: {rel}")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError) as exc:
            refused.append(f"step {step}: {rel} unreadable ({exc})")
            continue
        before = len(metrics)
        _flatten(str(step), data, metrics)
        sources.append(f"step {step}: {rel} (+{len(metrics) - before})")
    return {"metrics": metrics, "sources": sources,
            "refused": refused, "absent": absent}


def _polarity(key: str) -> int:
    """+1 larger-is-better, -1 smaller-is-better, 0 NOT DECLARED.

    Scans the leaf's WORDS rather than only its last one, because the last word
    is often the unit (`points`, `count`) and the direction lives earlier
    (`compared_points`, `non_equivalent_points`). A `_NEGATORS` word standing
    immediately before the match inverts it.

    0 is a real answer and the default. A metric this table does not recognise
    is reported as `CHANGED (direction not declared)`, never scored as neutral
    — silently calling an unknown movement "no change" is how a regression
    hides, and that is the shape this file exists to remove.
    """
    leaf = key.rsplit("__", 1)[-1].lower()
    if leaf in _POLARITY:
        return _POLARITY[leaf]
    words = [w for w in re.split(r"[_\W]+", leaf) if w]
    for i, w in enumerate(words):
        if w in _POLARITY:
            pol = _POLARITY[w]
            if i and words[i - 1] in _NEGATORS:
                pol = -pol
            return pol
    return 0


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Per key: what changed, by how much, and in which direction if declared."""
    rows: List[Dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key), after.get(key)
        if key not in after:
            rows.append({"metric": key, "verdict": GONE, "before": b, "after": None})
            continue
        if key not in before:
            rows.append({"metric": key, "verdict": NEW, "before": None, "after": a})
            continue
        if b == a:
            continue
        row: Dict[str, Any] = {"metric": key, "before": b, "after": a}
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) \
                and not isinstance(b, bool) and not isinstance(a, bool):
            row["delta"] = a - b
            pol = _polarity(key)
            row["verdict"] = (UNDECLARED if pol == 0
                              else UP if (a - b) * pol > 0 else DOWN)
        else:
            row["verdict"] = UNDECLARED
        rows.append(row)
    return {
        "rows": rows,
        "better": sum(1 for r in rows if r["verdict"] == UP),
        "worse": sum(1 for r in rows if r["verdict"] == DOWN),
        "changed_undeclared": sum(1 for r in rows if r["verdict"] == UNDECLARED),
        "new": sum(1 for r in rows if r["verdict"] == NEW),
        "gone": sum(1 for r in rows if r["verdict"] == GONE),
        "compared": len(set(before) & set(after)),
    }


def format_diff(res: Dict[str, Any]) -> str:
    lines: List[str] = []
    for r in res["rows"]:
        if r["verdict"] == UP:
            mark = "  BETTER"
        elif r["verdict"] == DOWN:
            mark = "  WORSE "
        elif r["verdict"] == NEW:
            mark = "  NEW   "
        elif r["verdict"] == GONE:
            mark = "  GONE  "
        else:
            mark = "  CHANGED"
        d = f"  ({r['delta']:+g})" if "delta" in r else ""
        lines.append(f"{mark}  {r['metric']}: {r['before']!r} -> {r['after']!r}{d}"
                     + ("   [direction not declared]"
                        if r["verdict"] == UNDECLARED and "delta" in r else ""))
    # THE DENOMINATOR, always. "0 worse" over 0 compared metrics is not a
    # result, and this repo refuses that shape everywhere else.
    lines.append(
        f"[run_metrics] compared {res['compared']} metric(s) present in both "
        f"runs: {res['better']} better, {res['worse']} worse, "
        f"{res['changed_undeclared']} changed with no declared direction, "
        f"{res['new']} new, {res['gone']} gone")
    if res["compared"] == 0:
        lines.append("[run_metrics] NOT CHECKED: the two runs share no metric, "
                     "so nothing was compared — this is NOT 'no regressions'")
    return "\n".join(lines)


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="flatten every declared per-step JSON")
    h.add_argument("--project", type=Path, default=Path("."))
    h.add_argument("--flow", type=Path, default=FLOW_YAML)
    h.add_argument("--out", type=Path, help="write the metrics JSON here")

    d = sub.add_parser("diff", help="compare two harvests")
    d.add_argument("before", type=Path)
    d.add_argument("after", type=Path)
    d.add_argument("--json", dest="json_out", type=Path)
    d.add_argument("--fail-on-regression", action="store_true",
                   help="exit 1 when any metric moved in a declared-worse "
                        "direction (off by default: this tool records what "
                        "happened, it does not assert what should have)")
    a = ap.parse_args(argv)

    if a.cmd == "harvest":
        try:
            res = harvest(a.project.resolve(), a.flow)
        except RuntimeError as exc:
            print(f"[NOT CHECKED] run_metrics: {exc}", file=sys.stderr)
            return RC_NOT_CHECKED
        payload = {"schema": "vibe-ic/run-metrics/1", "metrics": res["metrics"]}
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
        for s in res["sources"]:
            print(f"  read  {s}")
        for s in res["refused"]:
            print(f"  REFUSED  {s}")
        for s in res["absent"][:10]:
            print(f"  absent  {s}")
        if len(res["absent"]) > 10:
            print(f"  absent  … and {len(res['absent']) - 10} more")
        print(f"[run_metrics] harvested {len(res['metrics'])} metric(s) from "
              f"{len(res['sources'])} of "
              f"{len(res['sources']) + len(res['absent']) + len(res['refused'])} "
              f"declared per-step JSON output(s); "
              f"{len(res['absent'])} absent, {len(res['refused'])} refused")
        if not res["metrics"]:
            print("[run_metrics] NOT CHECKED: no declared per-step JSON output "
                  "existed under this project, so nothing was harvested — this "
                  "is NOT an empty-but-clean run", file=sys.stderr)
            return RC_NOT_CHECKED
        return RC_OK

    try:
        b = json.loads(a.before.read_text(encoding="utf-8")).get("metrics", {})
        c = json.loads(a.after.read_text(encoding="utf-8")).get("metrics", {})
    except (OSError, ValueError) as exc:
        print(f"[NOT CHECKED] run_metrics: cannot read a harvest: {exc}",
              file=sys.stderr)
        return RC_NOT_CHECKED
    res = diff(b, c)
    print(format_diff(res))
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(res, indent=1) + "\n")
    if res["compared"] == 0:
        return RC_NOT_CHECKED
    if a.fail_on_regression and res["worse"]:
        return RC_REGRESSED
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(_main())
