#!/usr/bin/env python3
"""One per-step metrics schema, emitted by whoever computed the number. #1080.

Adopted from OpenROAD-flow-scripts. Every ORFS stage runs through the same
21-line wrapper (`flow/scripts/flow.sh:15`) with `-metrics "$LOG_DIR/$1.json"`,
and each stage script sets its namespace on line 1
(`detail_route.tcl:1` is `utl::set_metrics_stage "detailedroute__{}"`). The
result is a flat, fixed-prefix, greppable, diffable schema:

    "cts__timing__setup__ws": -1.39289
    "cts__design__instance__area": 4795.85

and the aggregator does almost nothing — `genMetrics.py` is glob-and-merge.
"Is this run better or worse than the last one" is then one `diff`.

We had 63 declared step entries, 62 carrying a gate, many writing
`--json reports/.../xxx.json`, and every checker chose its own shape. Measured
on v1.10.32: `ls programs/ | grep -iE "metric|qor"` returns no per-step QoR
aggregator and nothing computes a run-to-run delta.

THE TWO RULES THIS MODULE EXISTS TO KEEP
========================================
1. EMITTED BY THE COMPUTER OF THE NUMBER, never re-parsed from a log. A log
   regex is a proxy for the measurement, not the measurement — the same
   substitution this repo keeps finding (a check measuring something adjacent
   to its question). `emit()` is called by the program that already holds the
   value; `collect()` globs and merges and is forbidden, structurally, from
   deriving anything: it never opens a log, and it has no parser.

2. IT RECORDS WHAT HAPPENED; IT DOES NOT ASSERT WHAT SHOULD HAVE. `diff()`
   reports deltas. It labels a change `better`/`worse` ONLY where a direction
   is DECLARED in `DIRECTIONS`, and `undeclared` everywhere else — it never
   guesses which way is good. A metrics differ that silently decided a
   direction would be an oracle wearing a report's clothes, and #1080 is
   explicitly oracle-free.

THE SCHEMA
==========
A flat JSON object of scalar values, keys shaped

    <step>__<domain>__<name>

`step` is the flow step id, lowercased with non-alphanumerics collapsed to `_`
(so `A3`, `14` and `D1` are all legal and stable). `domain` groups by kind —
`timing`, `design`, `drv`, `flow`, `coverage` — and `name` is the measurement.
Nesting beyond three parts is allowed (ORFS uses four) as long as every part is
non-empty; the FIRST part must be the step, which is what makes a merged file
attributable and greppable.

Files live at `reports/metrics/<step>.json`, one per step, so two steps can
never race on one file and a merged view is a glob.

3. A LOG PARSER IS A WITNESS, NOT A PREFERENCE (W5). Rule 1 demotes the
   existing parsers; it does not delete them. A parser that agrees with the
   tool is a second witness worth keeping. `reconcile()` states the four
   possible relations between a metric and a parsed value, and `authoritative()`
   — the only function that hands back a number to gate on — RAISES on
   `disagree`. There is deliberately no flag that makes it return a side,
   because a silent tie-break is the defect, not the ergonomics.

WHAT IS NOT DONE HERE, stated so a green run is not read as coverage
====================================================================
This ships the schema, the emitter, the collector, the differ, the conformance
check and the reconciliation rule. It does NOT claim broad coverage.

The coverage number is no longer written here. It used to read "it wires ONE
gate (`coverage_metric_check`); the other 61 gate-carrying steps DO NOT emit
yet" — true when typed, and with no way of staying true. It now lives in
`step_metrics_coverage_check.py`, which derives both bounds from the canonical
flow file on every run and ratchets them, so the count cannot drift and cannot
quietly fall. `collect()` still reports how many steps are represented, so a
caller sees that number rather than inferring completeness from a non-empty
result.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

METRICS_REL = "reports/metrics"
RC_OK = 0
RC_VIOLATION = 1
RC_UNDETERMINED = 2

_PART = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

# The ONLY places a direction is asserted, and each is a definition rather than
# a judgement: a violation count of 0 is better than 1 by what "violation"
# means. Anything not here is reported as `undeclared` — see rule 2.
DIRECTIONS: Dict[str, str] = {
    "violation_count": "lower",
    "error_count": "lower",
    "warning_count": "lower",
    "drc_count": "lower",
    "failed": "lower",
    "ws": "higher",          # worst slack
    "tns": "higher",         # total negative slack
    "coverage_pct": "higher",
    "passed": "higher",
}


def normalize_step(step: Any) -> str:
    """`A3` -> `a3`, `14` -> `14`, `Step 14` -> `step_14`. Stable and flat."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(step)).strip("_").lower()
    return s or "unknown"


def key_for(step: Any, domain: str, name: str, *extra: str) -> str:
    parts = [normalize_step(step), domain, *extra, name]
    return "__".join(str(p) for p in parts)


def key_defect(key: str) -> Optional[str]:
    """Why `key` is not schema-conformant, or None."""
    parts = key.split("__")
    if len(parts) < 3:
        return (f"{key!r}: needs at least <step>__<domain>__<name>; a key that "
                f"does not lead with its step is not attributable in a merge")
    for p in parts:
        if not p:
            return f"{key!r}: empty path component"
        if not _PART.match(p):
            return (f"{key!r}: component {p!r} must be lowercase "
                    f"alphanumeric/underscore")
    return None


def value_defect(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)) or value is None:
        return None
    return f"value {value!r} is not a scalar; the schema is flat by design"


# --------------------------------------------------------------------------- #
# Emit — called by the program that COMPUTED the number
# --------------------------------------------------------------------------- #
def emit(project: Path, step: Any, metrics: Dict[str, Any],
         *, domain: str = "flow") -> Path:
    """Merge `metrics` into `reports/metrics/<step>.json`. Returns the path.

    `metrics` keys may be bare names (`instance_area`) — they are prefixed with
    `<step>__<domain>__` — or already-qualified full keys, which are kept as
    they are so a caller with ORFS-shaped four-part names is not forced to
    flatten them into three.
    """
    step_n = normalize_step(step)
    out: Dict[str, Any] = {}
    for name, value in metrics.items():
        key = name if name.startswith(step_n + "__") else key_for(
            step, domain, str(name))
        defect = key_defect(key) or value_defect(value)
        if defect:
            raise ValueError(f"step_metrics.emit: {defect}")
        out[key] = value

    d = Path(project) / METRICS_REL
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{step_n}.json"
    prior: Dict[str, Any] = {}
    if f.is_file():
        try:
            loaded = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prior = loaded
        except (OSError, ValueError):
            prior = {}
    prior.update(out)
    f.write_text(json.dumps(prior, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")
    return f


# --------------------------------------------------------------------------- #
# Collect — glob and merge, and NOTHING else
# --------------------------------------------------------------------------- #
def collect(project: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Merge every `reports/metrics/*.json`. Returns (metrics, provenance).

    Deliberately has no parser and never opens a log: a collector that could
    derive a number would be able to disagree with the program that computed
    it, and then "the metric" has two sources.
    """
    d = Path(project) / METRICS_REL
    merged: Dict[str, Any] = {}
    steps: List[str] = []
    collisions: List[str] = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        steps.append(f.stem)
        for k, v in doc.items():
            if k in merged and merged[k] != v:
                collisions.append(k)
            merged[k] = v
    prov = {"steps_represented": sorted(set(steps)),
            "step_count": len(set(steps)),
            "metric_count": len(merged),
            "key_collisions": sorted(set(collisions))}
    return merged, prov


# --------------------------------------------------------------------------- #
# Diff — the "better or worse than last time" command
# --------------------------------------------------------------------------- #
def direction_for(key: str) -> str:
    tail = key.split("__")[-1]
    return DIRECTIONS.get(tail, "undeclared")


def diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Per-key delta. `verdict` is `better`/`worse` ONLY where declared."""
    changed: List[Dict[str, Any]] = []
    for k in sorted(set(old) & set(new)):
        a, b = old[k], new[k]
        if a == b:
            continue
        rec: Dict[str, Any] = {"key": k, "old": a, "new": b,
                               "direction": direction_for(k),
                               "verdict": "changed"}
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                and not isinstance(a, bool) and not isinstance(b, bool):
            rec["delta"] = b - a
            d = rec["direction"]
            if d == "lower":
                rec["verdict"] = "better" if b < a else "worse"
            elif d == "higher":
                rec["verdict"] = "better" if b > a else "worse"
        changed.append(rec)
    return {"changed": changed,
            "added": sorted(set(new) - set(old)),
            "removed": sorted(set(old) - set(new)),
            "better": sum(1 for c in changed if c["verdict"] == "better"),
            "worse": sum(1 for c in changed if c["verdict"] == "worse"),
            "undeclared_changes": sum(
                1 for c in changed if c["direction"] == "undeclared")}


# --------------------------------------------------------------------------- #
# Reconcile — the prose parser is kept as a CROSS-CHECK, never as a preference
# --------------------------------------------------------------------------- #
# Rule 1 says the number is emitted by whoever computed it. That does not delete
# the log parsers this repo already has; it demotes them. A parser that agrees
# with the tool is a second witness and worth keeping. A parser that DISAGREES
# with the tool is the interesting event, and the one shape that must never
# happen is the one that happened before #1080: the two disagree and the gate
# silently believes one of them.
#
# So there is no code path here that returns "the value" after a disagreement.
# `reconcile` returns a VERDICT, and `authoritative` — the only function that
# hands back a number to gate on — RAISES on `disagree`. A caller cannot quietly
# prefer a side because the module does not offer the move.
#
# The asymmetry between METRIC_ONLY and PROSE_ONLY is the substance of W5:
#
#   METRIC_ONLY — the tool emitted its number and the parser found nothing. This
#       is NOT a failure. It is precisely what happens when a tool's log WORDING
#       changes: the regex goes blind while the measurement is untouched. Under
#       the old shape that silence was credited as "no violations found" and the
#       gate went on printing PASS while blind. Here the tool's number is used
#       and the blindness is recorded, not punished.
#
#   PROSE_ONLY — the parser found a number and the tool emitted none. This is
#       the state 61 of our 62 gate-carrying steps are in today. It is NOT
#       agreement and must never be summarised as one; it is UNCORROBORATED, and
#       the whole point of counting it separately is that the count is visible.
AGREE = "agree"
DISAGREE = "disagree"
METRIC_ONLY = "metric_only"
PROSE_ONLY = "prose_only"
NEITHER = "neither"

#: The only verdict that is a defect. Named so a caller cannot spell it wrong.
RECONCILE_FAILURES = frozenset({DISAGREE})


def _numeric(v: Any) -> Optional[float]:
    """`v` as a float, or None. `bool` is NOT a number: True == 1 would make a
    boolean pass/fail flag compare equal to a violation count of one."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def reconcile(key: str, metric: Any, prose: Any,
              *, tolerance: float = 0.0) -> Dict[str, Any]:
    """Compare the tool's own metric against the log-parsed value for `key`.

    `None` on either side means THAT SIDE SAID NOTHING — it is never coerced to
    zero. `tolerance` applies only when both sides are numeric, and is an
    absolute bound, because the quantities this repo gates on (violation counts,
    slack in ns) are not scale-free enough for a relative one to mean the same
    thing in two domains.
    """
    rec: Dict[str, Any] = {"key": key, "metric": metric, "prose": prose}
    if metric is None and prose is None:
        rec.update(verdict=NEITHER, is_failure=False,
                   reason="neither the tool nor the parser produced a value; "
                          "this is NOT CHECKED, not a zero")
        return rec
    if prose is None:
        rec.update(verdict=METRIC_ONLY, is_failure=False,
                   reason="the tool emitted its own number and the log parser "
                          "matched nothing; the metric stands and the parser "
                          "is recorded as blind here")
        return rec
    if metric is None:
        rec.update(verdict=PROSE_ONLY, is_failure=False,
                   reason="only the log parser produced a value; the tool was "
                          "never asked for its own, so this number is "
                          "UNCORROBORATED and must not be reported as agreed")
        return rec

    m, p = _numeric(metric), _numeric(prose)
    if m is not None and p is not None:
        delta = abs(m - p)
        rec["delta"] = delta
        rec["tolerance"] = tolerance
        agreed = delta <= tolerance
    else:
        agreed = str(metric).strip() == str(prose).strip()
    if agreed:
        rec.update(verdict=AGREE, is_failure=False,
                   reason="the tool and the log parser agree")
    else:
        rec.update(verdict=DISAGREE, is_failure=True,
                   reason=f"the tool computed {metric!r} and the log parser "
                          f"read {prose!r} for the same quantity; one of the "
                          f"two is wrong and neither may be preferred silently")
    return rec


def authoritative(rec: Dict[str, Any]) -> Any:
    """The value to gate on, or raise.

    RAISES `ValueError` on `disagree` — deliberately the only exit. Returning a
    side here, under any flag, would reintroduce exactly the silent preference
    this module exists to prevent.
    """
    verdict = rec.get("verdict")
    if verdict in RECONCILE_FAILURES:
        raise ValueError(f"step_metrics.authoritative: {rec.get('reason')}")
    if verdict in (AGREE, METRIC_ONLY):
        return rec.get("metric")
    if verdict == PROSE_ONLY:
        return rec.get("prose")
    return None


def reconcile_report(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll up `reconcile` records. `uncorroborated` is published on its own
    because a run where every number came from a log parser is not a checked
    run, and a summary that folded it into `agree` would say it was."""
    counts: Dict[str, int] = {v: 0 for v in
                              (AGREE, DISAGREE, METRIC_ONLY, PROSE_ONLY, NEITHER)}
    for r in records:
        counts[r.get("verdict", NEITHER)] = counts.get(r.get("verdict", NEITHER), 0) + 1
    failures = [r for r in records if r.get("is_failure")]
    return {"records": records,
            "counts": counts,
            "corroborated": counts[AGREE],
            "uncorroborated": counts[PROSE_ONLY],
            "not_checked": counts[NEITHER],
            "metric_only": counts[METRIC_ONLY],
            "failures": failures,
            "passed": not failures}


# --------------------------------------------------------------------------- #
# Conformance
# --------------------------------------------------------------------------- #
def conformance_defects(project: Path) -> List[str]:
    out: List[str] = []
    d = Path(project) / METRICS_REL
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out.append(f"{f.name}: unreadable ({exc})")
            continue
        if not isinstance(doc, dict):
            out.append(f"{f.name}: top level must be a flat object")
            continue
        for k, v in doc.items():
            for defect in (key_defect(k), value_defect(v)):
                if defect:
                    out.append(f"{f.name}: {defect}")
            if not k.startswith(f.stem + "__"):
                out.append(f"{f.name}: key {k!r} does not lead with the step "
                           f"{f.stem!r} the file is named for")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="merge every per-step metrics file")
    c.add_argument("project")
    c.add_argument("--json", dest="json_out", default=None)
    k = sub.add_parser("check", help="schema conformance over a run")
    k.add_argument("project")
    df = sub.add_parser("diff", help="run-to-run delta")
    df.add_argument("old_project")
    df.add_argument("new_project")
    df.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "collect":
        merged, prov = collect(Path(args.project))
        if args.json_out:
            atomic_write_text(Path(args.json_out), 
                json.dumps({"metrics": merged, "provenance": prov},
                           indent=1, sort_keys=True) + "\n")
        print(f"collected {prov['metric_count']} metric(s) from "
              f"{prov['step_count']} step(s): "
              f"{', '.join(prov['steps_represented']) or '(none)'}")
        if prov["key_collisions"]:
            print(f"[WARN] {len(prov['key_collisions'])} key(s) emitted by "
                  f"more than one step with different values: "
                  f"{prov['key_collisions'][:5]}", file=sys.stderr)
        if not prov["step_count"]:
            print("[INFO] no step emitted metrics — this run cannot be "
                  "compared to another", file=sys.stderr)
            return RC_UNDETERMINED
        return RC_OK

    if args.cmd == "check":
        defects = conformance_defects(Path(args.project))
        merged, prov = collect(Path(args.project))
        print(f"schema check over {prov['step_count']} step file(s), "
              f"{prov['metric_count']} metric(s)")
        if defects:
            print(f"[FAIL] {len(defects)} schema defect(s):", file=sys.stderr)
            for d in defects[:20]:
                print(f"  {d}", file=sys.stderr)
            return RC_VIOLATION
        if not prov["step_count"]:
            print("[NOT CHECKED] no metrics files — nothing was examined, "
                  "which is not a pass", file=sys.stderr)
            return RC_UNDETERMINED
        print("[PASS] every emitted metric is schema-conformant")
        return RC_OK

    old, _ = collect(Path(args.old_project))
    new, _ = collect(Path(args.new_project))
    rep = diff(old, new)
    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps(rep, indent=1) + "\n")
    if not old and not new:
        print("[NOT CHECKED] neither run emitted metrics; there is nothing to "
              "compare and that is not 'no change'", file=sys.stderr)
        return RC_UNDETERMINED
    print(f"{len(rep['changed'])} changed, {len(rep['added'])} added, "
          f"{len(rep['removed'])} removed  "
          f"[better {rep['better']}, worse {rep['worse']}, "
          f"undeclared-direction {rep['undeclared_changes']}]")
    for c in rep["changed"][:40]:
        d = f"  ({c['delta']:+g})" if "delta" in c else ""
        print(f"  {c['verdict']:>10}  {c['key']} : {c['old']} -> {c['new']}{d}")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
