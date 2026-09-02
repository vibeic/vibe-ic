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

WHAT IS NOT DONE HERE, stated so a green run is not read as coverage
====================================================================
This ships the schema, the emitter, the collector, the differ, the conformance
check, the RECONCILIATION that makes a consuming step fail on disagreement,
and a coverage CENSUS.

THE COVERAGE SENTENCE THAT USED TO LIVE HERE WAS WRONG, AND THAT IS THE POINT.
It read: "It wires ONE gate (`coverage_metric_check`) as a worked example. The
other 61 gate-carrying steps DO NOT emit yet." Measured on v1.10.92:
`coverage_metric_check` is named NOWHERE in `flow/phase1_phase2_phase3.yaml`
and IS listed in `programs/gate_is_wired_baseline.json` under `unwired` —
"gates no automatic verdict consults". The gate offered as the worked example
is the one gate that is not wired. A coverage claim written once in prose rots
exactly like the log-parsed number this module exists to replace.

So the number is no longer written down. `coverage()` re-derives it from the
canonical flow plus the program sources; `EMITTING_STEPS`, `CONSUMING_STEPS`
and `GATE_CARRYING_STEPS` are the declared expectation; and
`step_metrics.py coverage` (plus `tests/test_step_metrics_coverage.py`) FAILS
when the two disagree. Wiring a gate without declaring it fails. Un-wiring one
fails. Adding a gate-carrying step to the flow fails.

EMITTING IS NOT CONSUMING, and only the second changes a verdict. Run
`python3 step_metrics.py coverage` for the current split.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import ast
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


def emit_best_effort(project: Path, step: Any, metrics: Dict[str, Any],
                     *, domain: str = "flow") -> Optional[Path]:
    """`emit`, but a metrics-sink failure can never change a gate's verdict.

    The first wired gate (`coverage_metric_check`) hand-rolled this
    try/except at its call site with the comment "a metrics-sink failure must
    not change this gate's verdict, which is about coverage, not about
    bookkeeping". That reasoning is true of EVERY gate, so it is named once
    here instead of being copied into each one — a swallow-everything block
    repeated per call site is how one of the copies quietly grows a different
    meaning.

    Returns the written path, or None when nothing could be written. None is
    a real answer and callers may log it; what they must NOT do is fail on it.

    The swallow is deliberately total (`Exception`), because the set of ways a
    filesystem can refuse a write is open-ended and none of them is evidence
    about the design under test. It does NOT swallow `BaseException`, so a
    KeyboardInterrupt or SystemExit still propagates.

    IT IS SILENT ABOUT NOTHING. The failure is always reported on stderr, and
    that is not decoration — it is the whole difference between a wiring that
    works and a wiring that only looks wired. MEASURED while wiring step 17:
    `summary["check_placement_violations"]` is a LIST of violations, not a
    count, so `emit` correctly refused it as non-scalar; with a silent swallow
    the gate still exited 0, the census still reported the step as wired
    (the call is really there in the AST), and NO metric file was ever
    written. A caller cannot fix what it is never told about, and a coverage
    number counting call sites rather than files would have been a lie told by
    the very module that exists to stop that.
    """
    try:
        return emit(Path(project), step, metrics, domain=domain)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        print(f"[step_metrics] EMIT FAILED (step={step}, domain={domain}): "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return None


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


# --------------------------------------------------------------------------- #
# Reconcile — BOTH readings run, and a disagreement FAILS naming both numbers
# --------------------------------------------------------------------------- #
# This is the clause the whole substrate rests on. Emitting a metric is only
# the supply side; a metric nobody consults changes no verdict, and a step that
# still decides from a log regex is still one release note away from going
# blind while reporting PASS.
#
# So a consuming step runs BOTH readings and this function decides:
#
#   AGREE       the tool's number and the log's number are the same. Pass.
#   DISAGREE    they differ. FAIL, and the message names BOTH numbers. This
#               function will NOT pick a winner. Preferring the metric hides a
#               parser that has gone blind; preferring the prose keeps exactly
#               the blindness the substrate exists to remove. One of the two is
#               wrong and that is a bug to FIX, not a tie to break.
#   NO_METRIC   the log parsed but the tool emitted nothing. NOT silently
#               green: the value is a proxy, the step says so, and
#               `require_metric` makes it fatal for callers that must not
#               accept one.
#   PROSE_BLIND the tool emitted but the log matched nothing — i.e. the wording
#               changed. The verdict is unaffected BECAUSE it no longer depends
#               on the parser, which is the point; the dead parser is still
#               named so nobody keeps trusting it.
#   NEITHER     no reading at all. UNDETERMINED, never zero. "Could not read"
#               must never become "clean".

AGREE = "AGREE"
DISAGREE = "DISAGREE"
NO_METRIC = "NO_METRIC"
PROSE_BLIND = "PROSE_BLIND"
NEITHER = "NEITHER"


class Reconciliation:
    """One quantity, read twice. `.ok` is False only where a step must FAIL.

    `.value` is None whenever `.ok` is False, so a caller that ignores `.ok`
    and uses `.value` gets NO reading rather than the wrong one of two.
    """

    __slots__ = ("name", "status", "value", "metric", "prose", "ok", "detail")

    def __init__(self, name, status, value, metric, prose, ok, detail):
        self.name, self.status, self.value = name, status, value
        self.metric, self.prose, self.ok, self.detail = metric, prose, ok, detail

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "status": self.status, "value": self.value,
                "metric": self.metric, "prose": self.prose, "ok": self.ok,
                "detail": self.detail}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Reconciliation {self.name} {self.status} value={self.value}>"


def reconcile(name: str, metric: Optional[Any], prose: Optional[Any], *,
              require_metric: bool = False) -> Reconciliation:
    """Cross-check a tool-emitted metric against the log-parsed reading."""
    if metric is not None and prose is not None:
        if metric == prose:
            return Reconciliation(
                name, AGREE, metric, metric, prose, True,
                f"{name}: tool and log agree ({metric!r})")
        return Reconciliation(
            name, DISAGREE, None, metric, prose, False,
            f"{name}: METRIC={metric!r} but LOG={prose!r}. The tool computed "
            f"one number and its log reads as another; one of them is wrong. "
            f"This check will not choose between them — preferring either side "
            f"is how a measurement quietly becomes a guess. Fix the emitter or "
            f"the parser; do not widen a tolerance.")
    if metric is not None:
        return Reconciliation(
            name, PROSE_BLIND, metric, metric, None, True,
            f"{name}: {metric!r} from the tool's own metric. The log parser "
            f"matched NOTHING and is blind to this number now — the verdict is "
            f"unaffected because it no longer depends on that parser.")
    if prose is not None:
        return Reconciliation(
            name, NO_METRIC, prose, None, prose, not require_metric,
            f"{name}: {prose!r} came from PARSING THE LOG — the tool emitted no "
            f"metric for it, so this value is a proxy for the measurement, not "
            f"the measurement. This step is NOT clean on this number; it is "
            f"unverified.")
    return Reconciliation(
        name, NEITHER, None, None, None, True,
        f"{name}: NOT DETERMINED — neither the tool's metrics nor its log "
        f"carried this number. That is not a reading of zero.")


# --------------------------------------------------------------------------- #
# Coverage census — how many gate-carrying steps actually emit, IN THE CODE
# --------------------------------------------------------------------------- #
# This module's own header says it "wires ONE gate as a worked example. The
# other 61 gate-carrying steps DO NOT emit yet." That sentence was true when it
# was written and it is PROSE: nothing recomputes it, so it rots silently the
# first time somebody wires a gate or the flow gains a step. A coverage claim
# that cannot be re-derived is the same defect this module exists to remove,
# one level up — a number stated once and thereafter believed.
#
# So the remainder is COUNTED, not described. `coverage()` derives the real
# state from the canonical flow plus the program sources; the two literals
# below are the DECLARED expectation, and `test_step_metrics_coverage.py`
# fails when derived and declared disagree. Wiring a gate without updating
# WIRED_STEPS fails. Un-wiring one fails. Adding a gate-carrying step to the
# flow fails. The count cannot drift away from the tree without something red.

#: Every step in `flow/phase1_phase2_phase3.yaml` that carries a `gate:` key.
#: Measured on v1.10.92: 63 step entries, of which `P0` alone carries no gate.
# 62 -> 67: the canonical flow gained five retained gate-carrying steps
# (0.5ic, 15.5ic, 26.5ic, 37.5ic and 37.5ip).  The former 1.6x gate is now
# owned by Step 2, so it no longer contributes a separate step to this census.
# 67 -> 68 (2026-09-03): canonical step 37.4, sign-off metrics aggregation.
# ONE step arrives and it carries a `gate:` key, so this census moves by exactly
# one. It is an ADDITION and not a rename: the flow's own id set goes 68 -> 69,
# '37.4' is the single member gained and no existing id changed spelling, so no
# step left this census to make room for it.
# Re-derived, not typed: `coverage()` counts 68 against the shipped flow.
GATE_CARRYING_STEPS: int = 68

#: EMITTING — gate-carrying steps whose gate runs a program that calls `emit`.
#: Supply side only: emitting a number changes no verdict.
EMITTING_STEPS: Tuple[str, ...] = ("17", "20", "31", "34")

#: CONSUMING — steps whose VERDICT reconciles a tool metric against the log
#: parse and FAILS when they disagree. This is the number that matters: a
#: metric nobody consults leaves the step exactly as blind as before.
#:
#: Step 21 (Routing) is implemented by `phase3_one_shot_runner.step_pnr`
#: rather than by a gate program, so it cannot be derived from the flow's
#: `gate:` blob; it is declared here with the file that implements it, and
#: `test_step_metrics_coverage.py` fails if that file stops calling
#: `reconcile`.
CONSUMING_STEPS: Dict[str, str] = {"21": "phase3_one_shot_runner.py"}


def _program_calls(path: Path, names: Tuple[str, ...]) -> bool:
    """Does this program CALL one of `names`?

    Parsed with `ast`, never grepped. This file and several gate programs
    mention `emit` and `reconcile` in prose, and a census that counted its own
    docstring would report coverage it does not have — which is precisely the
    failure mode it exists to catch. A comment cannot create a Call node.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return False
    imported = any(
        (isinstance(n, ast.Import)
         and any(a.name == "step_metrics" for a in n.names))
        or (isinstance(n, ast.ImportFrom) and n.module == "step_metrics")
        for n in ast.walk(tree))
    if not imported:
        return False
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nm = f.attr if isinstance(f, ast.Attribute) else (
            f.id if isinstance(f, ast.Name) else "")
        if nm in names:
            return True
    return False


def _program_emits(path: Path) -> bool:
    """Does this program call `step_metrics.emit` / `emit_best_effort`?

    Parsed with `ast`, never grepped. This file and several gate programs
    mention `emit` in prose, and a censor that counted its own docstring would
    report coverage it does not have — which is precisely the failure mode the
    census exists to catch. A comment cannot create a Call node.
    """
    return _program_calls(path, ("emit", "emit_best_effort"))


def _program_consumes(path: Path) -> bool:
    """Does this program's VERDICT reconcile a metric against a log parse?"""
    return _program_calls(path, ("reconcile",))


def _gate_programs(gate: Any, programs_dir: Path) -> List[str]:
    """The program stems a step's gate actually runs.

    Read off the gate blob rather than off any hand-kept table, so a gate that
    swaps its program is followed automatically. Only names that resolve to a
    real file in `programs/` are returned — a `.py` mentioned in a prose
    `reason:` field is not a program this gate runs.
    """
    blob = json.dumps(gate)
    names = set(re.findall(r"([a-z0-9_]+)\.py", blob))
    names |= set(re.findall(r'"program_exit_zero":\s*"([a-z0-9_]+)', blob))
    return sorted(n for n in names if (programs_dir / f"{n}.py").is_file())


def coverage(flow_def: Path, programs_dir: Path) -> Dict[str, Any]:
    """Derive, for every gate-carrying step, whether its gate emits a metric.

    Returns `wired` / `unwired` / `no_program` as SORTED LISTS OF STEP IDS, so
    the remainder is named and not merely subtracted. `no_program` is kept
    apart from `unwired` on purpose: a step whose gate is `files_exist` runs no
    program that could emit, so counting it as "a program that has not been
    wired yet" would overstate the work outstanding.
    """
    import yaml  # noqa: PLC0415 — optional dep, and only this path needs it
    doc = yaml.safe_load(Path(flow_def).read_text(encoding="utf-8"))
    steps = [s for s in (doc.get("steps") or []) if s.get("gate")]
    wired: List[str] = []
    unwired: List[str] = []
    no_program: List[str] = []
    emits_cache: Dict[str, bool] = {}
    for s in steps:
        sid = str(s["id"])
        progs = _gate_programs(s["gate"], Path(programs_dir))
        if not progs:
            no_program.append(sid)
            continue
        hit = False
        for name in progs:
            if name not in emits_cache:
                emits_cache[name] = _program_emits(Path(programs_dir) / f"{name}.py")
            hit = hit or emits_cache[name]
        (wired if hit else unwired).append(sid)
    consuming = sorted(
        sid for sid, f in CONSUMING_STEPS.items()
        if _program_consumes(Path(programs_dir) / f))
    return {
        "gate_carrying": len(steps),
        "emitting": sorted(set(wired)),
        "not_emitting": sorted(set(unwired)),
        "no_program": sorted(set(no_program)),
        "emitting_programs": sorted(k for k, v in emits_cache.items() if v),
        "consuming": consuming,
        "not_consuming": sorted(
            (set(str(s["id"]) for s in steps) - set(consuming)),
            key=lambda x: (len(x), x)),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="merge every per-step metrics file")
    c.add_argument("project")
    c.add_argument("--json", dest="json_out", default=None)
    k = sub.add_parser("check", help="schema conformance over a run")
    k.add_argument("project")
    cov = sub.add_parser(
        "coverage",
        help="how many gate-carrying steps emit, and WHICH do not")
    cov.add_argument("--flow-def", default=None,
                     help="flow/phase1_phase2_phase3.yaml (default: located "
                          "the same way flow_compliance_check locates it)")
    cov.add_argument("--json", dest="json_out", default=None)
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

    if args.cmd == "coverage":
        here = Path(__file__).resolve().parent
        if args.flow_def:
            flow = Path(args.flow_def)
        else:
            # ONE resolver in the tree. `flow_compliance_check` owns the
            # multi-layout search; importing it is heavier than a local copy
            # but a second copy is how two answers to "where is the flow"
            # start to disagree.
            from flow_compliance_check import _find_flow_def  # noqa: PLC0415
            flow = _find_flow_def()
        rep = coverage(flow, here)
        rep["declared_gate_carrying"] = GATE_CARRYING_STEPS
        rep["declared_emitting"] = list(EMITTING_STEPS)
        rep["declared_consuming"] = sorted(CONSUMING_STEPS)
        if args.json_out:
            atomic_write_text(Path(args.json_out),
                              json.dumps(rep, indent=1, sort_keys=True) + "\n")
        gc = rep["gate_carrying"]
        print(f"gate-carrying steps in the canonical flow : {gc}")
        print(f"  CONSUMING a metric (verdict reconciles) : "
              f"{len(rep['consuming'])}  {rep['consuming']}")
        print(f"  NOT consuming — verdict still decided")
        print(f"  by parsing, or by nothing measurable    : "
              f"{len(rep['not_consuming'])}")
        print(f"  emitting a metric (supply side only)    : "
              f"{len(rep['emitting'])}  {rep['emitting']}")
        print(f"  gate runs no program that could emit    : "
              f"{len(rep['no_program'])}  {rep['no_program']}")
        print(f"  emitting programs                       : "
              f"{rep['emitting_programs']}")
        drift = []
        if gc != GATE_CARRYING_STEPS:
            drift.append(f"gate-carrying steps {gc} != declared "
                         f"{GATE_CARRYING_STEPS}")
        if tuple(rep["emitting"]) != tuple(EMITTING_STEPS):
            drift.append(f"emitting {rep['emitting']} != declared "
                         f"{list(EMITTING_STEPS)}")
        if tuple(rep["consuming"]) != tuple(sorted(CONSUMING_STEPS)):
            drift.append(f"consuming {rep['consuming']} != declared "
                         f"{sorted(CONSUMING_STEPS)}")
        if drift:
            print("[FAIL] the code's declared coverage no longer matches the "
                  "tree:", file=sys.stderr)
            for d in drift:
                print(f"  {d}", file=sys.stderr)
            print("  Update EMITTING_STEPS / CONSUMING_STEPS / "
                  "GATE_CARRYING_STEPS in step_metrics.py, or restore the "
                  "call that went missing.", file=sys.stderr)
            return RC_VIOLATION
        print("[PASS] declared coverage matches the tree")
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
