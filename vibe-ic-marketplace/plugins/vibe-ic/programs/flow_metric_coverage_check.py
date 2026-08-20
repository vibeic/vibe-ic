#!/usr/bin/env python3
"""flow_metric_coverage_check — does the canonical flow DECLARE a metric per PPA axis?

WHY THIS EXISTS
===============
Nothing downstream can converge on a number nobody records, and the first thing
that has to exist before a number can be recorded is a DECLARATION of which step
owes it. Measured on `flow/phase1_phase2_phase3.yaml` at v1.11.7, per axis:

    performance   4 closed-loop edges (10->7, 20->19, 23->32, 32->32)
    power         1 edge (24->15, IR drop); step 33 measures and feeds nothing
    area          0 edges, and no step declares an area figure at all

The last line understates it. `yaml.safe_load` over EVERY step entry returns
this union of step keys (measured at v1.11.7; the union is what matters here,
not the step count, which moves):

    blocks_on closed_loop condition condition_kind gate id known_gap mcp_tools
    name notes programs required_inputs required_outputs skills stage

There is no `metrics:` key, so the count of steps declaring an AREA metric is
zero for the same reason the count declaring a POWER or a TIMING metric is zero:
the grammar had nowhere to put one. Ten of the figures were being produced
anyway — synthesis area and cell count sit in `stats.json`, the OpenSTA power
report tabulates internal/switching/leakage/total, the DEF carries DIEAREA —
and none of them was named by the step that produced it, so no consumer could
ask for one by name and no absence was detectable.

WHAT A DECLARATION LOOKS LIKE
=============================
On the step that produces the number:

    metrics:
      - name: design__instance__area     # OpenROAD's own name, not ours
        axis: area                       # performance | power | area
        source: "phase2/stage2/synth/stats.json"
        reader: "json:chip_area"         # how flow_metric_record reads it

`name` is deliberately the ORFS / LibreLane spelling so a reader can cross-check
this flow against either without a translation table. The on-disk key that
`step_metrics` writes is the step-qualified form `<step>__<name>` — the prefix is
the file's own attribution and is added by the emitter, not by the declaration.

WHAT THIS CHECKS
================
A1  AXIS COVERAGE.  For each REQUESTED axis, at least one step declares at least
    one WELL-FORMED metric for it.

A2  WELL-FORMEDNESS.  A declaration counts toward A1 only if it carries a
    non-empty `name`, an `axis` drawn from the declared vocabulary, a `source`
    and a `reader`. A malformed entry is reported as a defect and does NOT count
    as coverage — otherwise `metrics: [{}]` would close an axis.

A3  NO DUPLICATE OWNER.  One `<step>__<name>` key is owned by exactly one
    declaration. Two steps claiming the same key is how a merged metrics view
    starts depending on glob order.

Every axis in the vocabulary is REPORTED whether or not it was requested, so the
state of the axes this invocation does not gate on is still visible. Only the
requested ones decide the exit code.

EXIT
====
0  every requested axis is covered, and no defect
1  a requested axis has no well-formed declaration, or a defect was found
2  COULD NOT CHECK — no flow file, unreadable, no YAML parser, or the file
   carries no `steps:`. "I could not read it" and "I read it and it was empty"
   must never produce the same verdict.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text as _atomic_write_text  # noqa: E402

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - environment without pyyaml
    yaml = None  # type: ignore

_NAME = "flow_metric_coverage_check"

RC_OK = 0
RC_VIOLATION = 1
RC_NOT_CHECKED = 2

#: The PPA axes, in the order a report reads best. This is the whole vocabulary:
#: an `axis:` value outside it is a defect, not a new axis, because a typo that
#: silently invented `powers` would close nothing while appearing to.
AXES: Tuple[str, ...] = ("performance", "power", "area")

#: Fields every metric declaration must carry. `unit` and `note` are optional.
REQUIRED_FIELDS: Tuple[str, ...] = ("name", "axis", "source", "reader")


def find_flow_def(explicit: Optional[str]) -> Optional[Path]:
    """The flow file, resolved the ONE way the tree already resolves it."""
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from flow_compliance_check import _find_flow_def  # noqa: PLC0415
    except Exception:  # pragma: no cover - defensive
        p = Path(__file__).resolve().parent.parent / "flow" \
            / "phase1_phase2_phase3.yaml"
        return p if p.is_file() else None
    p = _find_flow_def()
    return p if p.is_file() else None


def declarations(doc: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every metric declaration in the flow, and every defect found reading them.

    Returns (well_formed, defects). A declaration that is not well formed is
    NOT in the first list: A2 exists so that a broken entry cannot close an axis.
    """
    good: List[Dict[str, Any]] = []
    defects: List[str] = []
    owner: Dict[str, str] = {}
    for step in (doc.get("steps") or []):
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id"))
        block = step.get("metrics")
        if block is None:
            continue
        if not isinstance(block, list):
            defects.append(f"step {sid}: `metrics:` must be a list, got "
                           f"{type(block).__name__}")
            continue
        for i, m in enumerate(block):
            where = f"step {sid} metrics[{i}]"
            if not isinstance(m, dict):
                defects.append(f"{where}: entry must be a mapping, got "
                               f"{type(m).__name__}")
                continue
            missing = [f for f in REQUIRED_FIELDS
                       if not str(m.get(f) or "").strip()]
            if missing:
                defects.append(f"{where}: missing/empty {', '.join(missing)}")
                continue
            axis = str(m["axis"]).strip()
            if axis not in AXES:
                defects.append(
                    f"{where}: axis {axis!r} is not one of {list(AXES)}. An "
                    f"unknown axis closes nothing while appearing to.")
                continue
            name = str(m["name"]).strip()
            key = f"{sid}__{name}"
            if key in owner:
                defects.append(
                    f"{where}: metric key {key!r} is already declared by "
                    f"{owner[key]}. One key, one owner — two owners make a "
                    f"merged view depend on glob order.")
                continue
            owner[key] = where
            good.append({"step": sid, "key": key, "name": name, "axis": axis,
                         "source": str(m["source"]).strip(),
                         "reader": str(m["reader"]).strip(),
                         "unit": (str(m["unit"]).strip()
                                  if m.get("unit") is not None else None),
                         "note": m.get("note")})
    return good, defects


def report(flow: Path, requested: Tuple[str, ...]) -> Tuple[Dict[str, Any], int]:
    try:
        text = flow.read_text(encoding="utf-8")
    except OSError as exc:
        return ({"status": "NOT_CHECKED",
                 "reason": f"cannot read {flow}: {exc}"}, RC_NOT_CHECKED)
    if yaml is None:
        return ({"status": "NOT_CHECKED",
                 "reason": "PyYAML is not importable, so the flow could not be "
                           "parsed. This is not a clean flow."}, RC_NOT_CHECKED)
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - any parse failure is NOT_CHECKED
        return ({"status": "NOT_CHECKED",
                 "reason": f"{flow} did not parse: "
                           f"{type(exc).__name__}: {exc}"}, RC_NOT_CHECKED)
    if not isinstance(doc, dict) or not isinstance(doc.get("steps"), list) \
            or not doc["steps"]:
        return ({"status": "NOT_CHECKED",
                 "reason": f"{flow} carries no `steps:` list. A flow with no "
                           f"steps is unreadable input, not an uncovered "
                           f"flow."}, RC_NOT_CHECKED)

    good, defects = declarations(doc)
    per_axis: Dict[str, Any] = {}
    for axis in AXES:
        ms = [m for m in good if m["axis"] == axis]
        per_axis[axis] = {
            "declared_metrics": len(ms),
            "declaring_steps": sorted({m["step"] for m in ms},
                                      key=lambda s: (len(s), s)),
            "keys": sorted(m["key"] for m in ms),
            "covered": bool(ms),
            "requested": axis in requested,
        }
    uncovered = [a for a in requested if not per_axis[a]["covered"]]
    rc = RC_VIOLATION if (uncovered or defects) else RC_OK
    return ({"status": "PASS" if rc == RC_OK else "FAIL",
             "flow": str(flow),
             "step_count": len(doc["steps"]),
             "requested_axes": list(requested),
             "axes": per_axis,
             "uncovered_requested_axes": uncovered,
             "defects": defects,
             "total_declared_metrics": len(good)}, rc)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--axis", action="append", default=None, metavar="AXIS",
                    help=f"axis to GATE on, repeatable; one of {list(AXES)}. "
                         f"Default: every axis. Every axis is REPORTED "
                         f"regardless; only these decide the exit code.")
    ap.add_argument("--flow-def", default=None,
                    help="flow/phase1_phase2_phase3.yaml (default: located the "
                         "same way flow_compliance_check locates it)")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(list(argv) if argv is not None else None)

    requested = tuple(a.axis) if a.axis else AXES
    unknown = [x for x in requested if x not in AXES]
    if unknown:
        print(f"[{_NAME}] unknown axis {unknown}; known axes are {list(AXES)}",
              file=sys.stderr)
        return RC_NOT_CHECKED

    flow = find_flow_def(a.flow_def)
    if flow is None:
        rep: Dict[str, Any] = {
            "status": "NOT_CHECKED",
            "reason": "the canonical flow definition was not found. A checker "
                      "that cannot see its input reports NOT CHECKED, never "
                      "clean."}
        rc = RC_NOT_CHECKED
    else:
        rep, rc = report(flow, requested)

    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # vibe-ic#1082 — a report destination is written atomically, so a
        # reader can never observe a half-written verdict.
        _atomic_write_text(out, json.dumps(rep, indent=1, sort_keys=True)
                           + "\n")

    if rep["status"] == "NOT_CHECKED":
        print(f"[{_NAME}] NOT CHECKED — {rep['reason']}", file=sys.stderr)
        return rc

    print(f"[{_NAME}] {rep['flow']}")
    print(f"  {rep['step_count']} steps, {rep['total_declared_metrics']} "
          f"declared metric(s)")
    for axis in AXES:
        d = rep["axes"][axis]
        mark = "OK  " if d["covered"] else "NONE"
        gate = "gated" if d["requested"] else "reported only"
        print(f"  {mark}  {axis:<12} {d['declared_metrics']} metric(s) on "
              f"step(s) {d['declaring_steps'] or '[]'}   ({gate})")
        for k in d["keys"]:
            print(f"          {k}")
    if rep["defects"]:
        print(f"[{_NAME}] {len(rep['defects'])} declaration defect(s):",
              file=sys.stderr)
        for d in rep["defects"]:
            print(f"  {d}", file=sys.stderr)
    if rep["uncovered_requested_axes"]:
        print(f"[{_NAME}] FAIL — no step declares a metric for: "
              f"{', '.join(rep['uncovered_requested_axes'])}. Nothing "
              f"downstream can converge on a number nobody records.",
              file=sys.stderr)
    if rc == RC_OK:
        print(f"[{_NAME}] PASS — every gated axis is declared by at least one "
              f"step")
    return rc


if __name__ == "__main__":
    sys.exit(main())
