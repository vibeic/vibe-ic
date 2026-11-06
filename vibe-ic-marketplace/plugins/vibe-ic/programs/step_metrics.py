#!/usr/bin/env python3
"""Native per-step metrics, collection, deltas and value reconciliation."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
import _flow_yaml  # F18: one libyaml-backed, once-per-process parse of the flow yaml

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
# A gate's outcome, attributed to the step whose clause ran it
# --------------------------------------------------------------------------- #
#: The options a flow gate clause uses to name the file its verdict goes to.
#: Matching on the program AND that path is what attributes one invocation to
#: one step: `sta_report_check` is step 10's gate and step 23's, and only the
#: `--json` path tells the two apart.
_OUTPUT_OPTS = ("--json", "--check")


def _opt_value(tokens: List[str], names: Tuple[str, ...]) -> Optional[str]:
    for i, tok in enumerate(tokens):
        for name in names:
            if tok == name and i + 1 < len(tokens):
                return tokens[i + 1]
            if tok.startswith(name + "="):
                return tok.split("=", 1)[1]
    return None


def _gate_strings(node: Any) -> List[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [x for v in node.values() for x in _gate_strings(v)]
    if isinstance(node, list):
        return [x for v in node for x in _gate_strings(v)]
    return []


def step_for_invocation(program: str, argv: List[str],
                        flow_yaml: Optional[Path] = None
                        ) -> Tuple[Optional[str], str]:
    """`(step_id, "")` for the ONE step whose gate clause runs `program` with
    this output path, or `(None, why)`.

    Read from the flow yaml, never assumed: a program cannot know which step
    invoked it, and guessing is how a number lands under the wrong step. No
    match, or more than one, is an honest None -- the caller then emits
    nothing and says so.
    """
    import shlex                                          # noqa: PLC0415
    try:
        import yaml  # noqa: F401,PLC0415 - availability probe; _flow_yaml parses
    except ImportError:
        return None, "PyYAML is not importable here"
    flow = flow_yaml or (Path(__file__).resolve().parent.parent / "flow"
                         / "phase1_phase2_phase3.yaml")
    try:
        doc = _flow_yaml.load(flow, encoding="utf-8") or {}
    except (OSError, ValueError) as exc:
        return None, f"cannot read {flow.name}: {exc}"
    want = _opt_value(list(argv), _OUTPUT_OPTS)
    if want and Path(want).is_absolute() and argv and not str(argv[0]).startswith("-"):
        try:
            want = str(Path(want).resolve().relative_to(Path(argv[0]).resolve()))
        except (ValueError, OSError):
            pass
    hits = set()
    for step in doc.get("steps") or []:
        for clause in _gate_strings(step.get("gate")):
            try:
                tokens = shlex.split(clause)
            except ValueError:
                continue
            if not tokens or Path(tokens[0]).stem != program:
                continue
            if want is None or _opt_value(tokens, _OUTPUT_OPTS) == want:
                hits.add(str(step.get("id")))
    if len(hits) == 1:
        return next(iter(hits)), ""
    if not hits:
        return None, (f"no gate clause in {flow.name} runs {program} with "
                      f"output {want!r}")
    return None, (f"{len(hits)} steps ({', '.join(sorted(hits))}) run "
                  f"{program} with output {want!r}; not attributable")


def _metric_name(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_") or "value"


#: THE STEP A GATE PROGRAM WAS RUN FOR, stated by its CALLER (M2). A program
#: cannot know which step invoked it, and inferring it from argv failed on every
#: real call shape: the phase-3 runner passes an ABSOLUTE `--json`, and
#: flow_compliance_check redirects `--json` to `/tmp/gate_receipt_*` when the
#: target already exists -- so steps 23 and 25 never matched and 10/21/37
#: matched only on a project's first run. Every legitimate caller KNOWS the
#: step (the audit is judging it; the runner resolves it once from the
#: canonical clause, `step_for_invocation`), so it says so here. An
#: out-of-flow hand run carries no step and therefore never writes a
#: project's metrics.
GATE_STEP_ENV = "VIBEIC_GATE_STEP"
#: The audit invocation that ran the gate, shared with flow_compliance_check
#: and release_docs_check; stamped on every gate row so a row an earlier run
#: wrote is recognisable as stale.
INVOCATION_ENV = "VIBEIC_FCC_INVOCATION"


def gate_env(step_id: str) -> Dict[str, str]:
    """What a CALLER adds to a gate subprocess's environment to attribute it."""
    return {GATE_STEP_ENV: str(step_id)} if step_id else {}


def _step_runs_program(step_id: str, program: str,
                       flow_yaml: Optional[Path] = None) -> bool:
    """Does `step_id`'s own gate run `program`? An inherited step id reaching a
    grandchild (e.g. step 37.5ic's `tapeout_precheck` spawning
    `drc_report_check`) is not an attribution, and is refused."""
    import shlex                                          # noqa: PLC0415
    try:
        import yaml  # noqa: F401,PLC0415 - availability probe; _flow_yaml parses
    except ImportError:
        return False
    flow = flow_yaml or (Path(__file__).resolve().parent.parent / "flow"
                         / "phase1_phase2_phase3.yaml")
    try:
        doc = _flow_yaml.load(flow, encoding="utf-8") or {}
    except (OSError, ValueError):
        return False
    for step in doc.get("steps") or []:
        if str(step.get("id")) != str(step_id):
            continue
        for clause in _gate_strings(step.get("gate")):
            try:
                tokens = shlex.split(clause)
            except ValueError:
                continue
            if tokens and Path(tokens[0]).stem == program:
                return True
    return False


def emit_gate_outcome(program: str, argv: List[str], rc: int, *,
                      report: Optional[str] = None,
                      flow_yaml: Optional[Path] = None,
                      env: Optional[Dict[str, str]] = None) -> Optional[Path]:
    """Emit what a gate just decided, under the step its CALLER named.

    The numbers are the gate's OWN: its exit code and the scalar facts of the
    verdict document it just wrote (`passed`, `verdict`, every numeric
    `summary` field, finding counts per severity) -- nothing re-derived. Every
    row carries `invocation` (the audit run that asked) and `program`, so a row
    that was NOT refreshed by this run is recognisable beside a fresh
    `__flow__invocation`.

    SILENT when there is nothing to attribute to: no `VIBEIC_GATE_STEP` (a hand
    run), or a step whose own gate does not run this program (an inherited id).
    Silence is correct there -- nothing was asked of this program on a step's
    behalf -- and it keeps the gate's own stderr tail (which evidence readers
    quote) unchanged. A write that WAS owed and failed still says so, through
    `emit_best_effort`.
    """
    e = os.environ if env is None else env
    step = (e.get(GATE_STEP_ENV) or "").strip()
    if not step or not _step_runs_program(step, program, flow_yaml):
        return None
    head = argv[0] if argv and not str(argv[0]).startswith("-") else "."
    project = Path(head)
    metrics: Dict[str, Any] = {"rc": int(rc), "program": program,
                               "invocation": (e.get(INVOCATION_ENV) or "").strip()}
    rel = report or _opt_value(list(argv), _OUTPUT_OPTS)
    payload: Any = None
    if rel:
        path = Path(rel) if Path(rel).is_absolute() else project / rel
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
    if isinstance(payload, dict):
        for k in ("passed", "verdict", "ok", "status"):
            v = payload.get(k)
            if isinstance(v, (bool, int, float, str)):
                metrics[k] = v
        summary = payload.get("summary")
        if isinstance(summary, dict):
            for k, v in summary.items():
                if isinstance(v, (bool, int, float)):
                    metrics["summary_" + _metric_name(k)] = v
        findings = payload.get("findings")
        if isinstance(findings, list):
            counts: Dict[str, int] = {}
            for f in findings:
                sev = (f.get("severity") if isinstance(f, dict) else None) \
                    or "unspecified"
                counts[_metric_name(sev)] = counts.get(_metric_name(sev), 0) + 1
            metrics["findings_count"] = len(findings)
            for sev, n in counts.items():
                metrics["findings_" + sev] = n
    return emit_best_effort(project, step, metrics, domain="gate")


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
