#!/usr/bin/env python3
"""flow_metric_record — record every metric the flow DECLARES, or NOT_MEASURED.

WHY THIS EXISTS
===============
`flow_metric_coverage_check` answers "does any step OWE this axis a number".
This answers the next question: "did this run PRODUCE the numbers its flow said
it owed", and it writes the answer down.

The two must be separate. A declaration nothing reads is a comment, and a
recorder with no declaration to work from has to decide for itself what a run
should have produced — which is how a metrics file grows a number nobody asked
for and loses one nobody noticed.

THE ONE RULE
============
**A field this run did not produce is the literal `NOT_MEASURED`.** Not 0, not
null, not "n/a", not the previous run's value, and not silently absent. A
plausible default hides exactly the hole the declaration exists to expose, and
absence is indistinguishable from a key that was never declared.

`NOT_MEASURED` is therefore WRITTEN, not omitted: a consumer that iterates the
recorded metrics sees the hole without having to know the flow. `--require-measured`
turns any hole into a non-zero exit for a caller that must not proceed on one.

WHERE IT WRITES
===============
`reports/metrics/<step>.json` through `step_metrics.emit` — the repo's one
per-step metrics channel — keyed `<step>__<name>`, plus one run-level roll-up at
`reports/metrics/ppa.json` carrying, per declared metric, the value or
NOT_MEASURED, the source it was read from, and its PROVENANCE.

PROVENANCE IS PART OF THE READING, NOT DECORATION
=================================================
    metric    the value came from a tool's own metrics channel. Strongest.
    artefact  the value came from a structured artefact the tool wrote.
    log       the value was parsed out of a tool LOG.

`step_metrics`' rule 1 is that a metric is emitted by whoever computed it and
never re-parsed from a log, because a log regex is a proxy for the measurement
rather than the measurement. Two of this flow's declared metrics — the placer's
achieved utilization and the router's wirelength — exist ONLY in the OpenROAD
log today, because OpenROAD is not invoked with `-metrics` here. Recording them
is better than not recording them; recording them WITHOUT saying which kind of
reading they are would launder a proxy into a measurement. So the kind is
recorded on every value, and a caller that must not accept a proxy can say so
with `--require-provenance`.

READERS
=======
A declaration's `reader` names how to turn its `source` into a scalar. The flow
declares WHAT; the reader knows HOW, so no regex lives in the flow file.

    json:<dotted.field>              a field of a JSON artefact
    def:die_area                     DIEAREA, scaled by the DEF's own UNITS
    def:core_area                    the placement-row bounding box
    power_rpt:<internal|switching|leakage|total>
                                     the OpenSTA `report_power` Total row
    openroad_log:route_wirelength    the LAST `Total wire length = N um.`
    openroad_log:detailed_placement_utilization
                                     the LAST `[INFO DPL-0009] Utilization: N%`
    step_metrics:<key>               read back a key another step already emitted

"LAST" is load-bearing in both log readers. Measured on a completed run
(spm, 2026-08-03) the router prints its total five times as it iterates
(13033 ... 12704, 12704) and detailed placement prints its utilization seven
times as it re-legalizes (45.6% ... 59.2%). The last line is the achieved value;
taking the first is a 2.6% error on that run with no fixed sign. Each reading
records the line number it came from so the choice is auditable.

EXIT
====
0  every declared metric was recorded (measured or NOT_MEASURED)
1  --require-measured and at least one metric is NOT_MEASURED, or
   --require-provenance and a reading is weaker than required
2  COULD NOT RECORD — no flow, unparseable flow, no project directory, no YAML
   parser. "I could not look" and "I looked and found nothing" are different
   answers and this program never collapses them.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import step_metrics as _sm  # noqa: E402
from _atomic_artefact import write_text as _atomic_write_text  # noqa: E402
from flow_metric_coverage_check import (  # noqa: E402
    declarations, find_flow_def)

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - environment without pyyaml
    yaml = None  # type: ignore

_NAME = "flow_metric_record"

RC_OK = 0
RC_VIOLATION = 1
RC_NOT_RECORDED = 2

#: The one spelling of "this run did not produce it". Shared with
#: `tapeout_docs_gen`, which already refuses to fill a gap with a default and
#: BLOCKS document generation on this literal — see its `release_blockers`.
NOT_MEASURED = "NOT_MEASURED"

#: Provenance kinds, WEAKEST FIRST, so `--require-provenance` is an ordering
#: rather than a set membership test.
PROVENANCE_ORDER: Tuple[str, ...] = ("log", "artefact", "metric")

_NUM = r"([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"

#: The OpenSTA `report_power` Total row: internal, switching, leakage, total.
#: Same row `power_total_vs_budget_check` reads; the components it drops on the
#: floor after its budget comparison are exactly the ones recorded here.
_POWER_TOTAL_ROW = re.compile(
    r"^\s*Total\s+" + _NUM + r"\s+" + _NUM + r"\s+" + _NUM + r"\s+" + _NUM
    + r"\b", re.M)
_POWER_COMPONENT_INDEX = {"internal": 1, "switching": 2, "leakage": 3,
                          "total": 4}

_ROUTE_WIRELENGTH = re.compile(r"^Total wire length\s*=\s*" + _NUM + r"\s*um",
                               re.M)
_DPL_UTILIZATION = re.compile(
    r"^\[INFO DPL-0009\]\s*Utilization:\s*" + _NUM + r"\s*%", re.M)

_DIEAREA = re.compile(
    r"^\s*DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)",
    re.M)
_UNITS = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", re.M)
#: `ROW <name> <site> <x> <y> <orient> DO <n> BY <m> STEP <sx> <sy> ;`
_ROW = re.compile(
    r"^\s*ROW\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)\s+\S+\s+DO\s+(\d+)\s+BY\s+(\d+)"
    r"\s+STEP\s+(\d+)\s+(\d+)", re.M)


class Unread(Exception):
    """The reading did not happen. Carries WHY, which is recorded verbatim."""


def _read_text(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError as exc:
        raise Unread(f"cannot read {p.name}: {exc}") from exc


def _last(rx: "re.Pattern[str]", text: str, what: str) -> Tuple[float, int]:
    """The LAST match of `rx`, with the 1-based line it sits on.

    Last, never first: every log reader here reads a figure a tool reprints as
    it iterates, and only the final print is the achieved value.
    """
    ms = list(rx.finditer(text))
    if not ms:
        raise Unread(f"no line matching {what} in this file")
    m = ms[-1]
    return float(m.group(1)), text.count("\n", 0, m.start()) + 1


def _dig(doc: Any, dotted: str) -> Any:
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise Unread(f"field {dotted!r}: no {part!r} here")
        cur = cur[part]
    return cur


def _units(text: str, name: str) -> float:
    m = _UNITS.search(text)
    if not m:
        raise Unread(f"{name} declares no `UNITS DISTANCE MICRONS`, so its "
                     f"coordinates have no scale and an area read off them "
                     f"would be a number with no unit")
    u = float(m.group(1))
    if u <= 0:
        raise Unread(f"{name}: UNITS DISTANCE MICRONS {m.group(1)} is not "
                     f"positive")
    return u


def _die_area(path: Path) -> Tuple[float, str, str]:
    text = _read_text(path)
    u = _units(text, path.name)
    m = _DIEAREA.search(text)
    if not m:
        raise Unread(f"{path.name} carries no DIEAREA record")
    x0, y0, x1, y1 = (int(g) for g in m.groups())
    w, h = abs(x1 - x0) / u, abs(y1 - y0) / u
    if w <= 0 or h <= 0:
        raise Unread(f"{path.name}: DIEAREA is degenerate ({w} x {h} um)")
    return w * h, "artefact", f"DIEAREA {w:g} x {h:g} um"


def _core_area(path: Path) -> Tuple[float, str, str]:
    """The placement-row bounding box.

    Row HEIGHT is not on the row record; it is the y-pitch between adjacent row
    origins. A DEF holding rows at a single y therefore has no derivable core
    height and this REFUSES rather than assuming one — a core area computed with
    an invented row height is a confident wrong number.
    """
    text = _read_text(path)
    u = _units(text, path.name)
    rows = _ROW.findall(text)
    if not rows:
        raise Unread(f"{path.name} carries no ROW records")
    xs0, xs1, ys = [], [], []
    for x, y, n, by, sx, sy in rows:
        x, y, n, by, sx, sy = (int(x), int(y), int(n), int(by), int(sx),
                               int(sy))
        xs0.append(x)
        xs1.append(x + n * sx)
        for k in range(max(by, 1)):
            ys.append(y + k * sy)
    uniq = sorted(set(ys))
    if len(uniq) < 2:
        raise Unread(
            f"{path.name} holds rows at a single y ({uniq}), so the row height "
            f"— which is the y-pitch between adjacent rows and appears nowhere "
            f"on a ROW record — cannot be derived. Refusing rather than "
            f"assuming a height.")
    pitch = min(b - a for a, b in zip(uniq, uniq[1:]))
    w = (max(xs1) - min(xs0)) / u
    h = ((uniq[-1] - uniq[0]) + pitch) / u
    return w * h, "artefact", (f"{len(rows)} ROW record(s), bbox {w:g} x {h:g} "
                               f"um, row pitch {pitch / u:g} um")


def read_metric(project: Path, decl: Dict[str, Any]) -> Dict[str, Any]:
    """One declared metric, read. Never raises: a refusal is a RESULT."""
    out: Dict[str, Any] = {
        "step": decl["step"], "key": decl["key"], "name": decl["name"],
        "axis": decl["axis"], "unit": decl.get("unit"),
        "source": decl["source"], "reader": decl["reader"],
        "value": NOT_MEASURED, "provenance": None, "detail": None}
    reader = decl["reader"]
    src = project / decl["source"]
    try:
        if reader.startswith("json:"):
            if not src.is_file():
                raise Unread(f"{decl['source']} does not exist in this run")
            try:
                doc = json.loads(_read_text(src))
            except ValueError as exc:
                raise Unread(f"{src.name} is not valid JSON: {exc}") from exc
            v = _dig(doc, reader.split(":", 1)[1])
            if v is None:
                raise Unread(f"{reader.split(':', 1)[1]!r} is present but null")
            out.update(value=v, provenance="artefact",
                       detail=f"{decl['source']}#{reader.split(':', 1)[1]}")
        elif reader.startswith("power_rpt:"):
            comp = reader.split(":", 1)[1]
            if comp not in _POWER_COMPONENT_INDEX:
                raise Unread(f"unknown power component {comp!r}")
            if not src.is_file():
                raise Unread(f"{decl['source']} does not exist in this run")
            text = _read_text(src)
            ms = list(_POWER_TOTAL_ROW.finditer(text))
            if not ms:
                raise Unread(
                    f"{src.name} carries no `report_power` Total row. The file "
                    f"exists, so this is a report that did not tabulate power "
                    f"— not an absent report.")
            m = ms[-1]
            line_no = text.count("\n", 0, m.start()) + 1
            out.update(value=float(m.group(_POWER_COMPONENT_INDEX[comp])),
                       provenance="artefact",
                       detail=f"report_power Total row, line {line_no}")
        elif reader == "openroad_log:route_wirelength":
            if not src.is_file():
                raise Unread(f"{decl['source']} does not exist in this run")
            v, ln = _last(_ROUTE_WIRELENGTH, _read_text(src),
                          "`Total wire length = N um.`")
            out.update(value=v, provenance="log",
                       detail=f"last of the tool's repeated totals, line {ln}")
        elif reader == "openroad_log:detailed_placement_utilization":
            if not src.is_file():
                raise Unread(f"{decl['source']} does not exist in this run")
            v, ln = _last(_DPL_UTILIZATION, _read_text(src),
                          "`[INFO DPL-0009] Utilization: N%`")
            out.update(value=v, provenance="log",
                       detail=f"last of the placer's repeated reports, "
                              f"line {ln}")
        elif reader == "def:die_area":
            if not src.is_file():
                raise Unread(f"{decl['source']} does not exist in this run")
            v, prov, det = _die_area(src)
            out.update(value=v, provenance=prov, detail=det)
        elif reader == "def:core_area":
            if not src.is_file():
                raise Unread(f"{decl['source']} does not exist in this run")
            v, prov, det = _core_area(src)
            out.update(value=v, provenance=prov, detail=det)
        elif reader.startswith("step_metrics:"):
            want = reader.split(":", 1)[1]
            merged, _prov = _sm.collect(project)
            if want not in merged or merged[want] is None:
                raise Unread(
                    f"{want!r} is not in this run's reports/metrics/. The step "
                    f"that owes it either did not run or did not emit.")
            out.update(value=merged[want], provenance="metric",
                       detail=f"emitted by step {decl['step']} itself")
        else:
            raise Unread(f"no reader named {reader!r}")
    except Unread as exc:
        out.update(value=NOT_MEASURED, provenance=None, detail=str(exc))
    return out


def record(project: Path, decls: List[Dict[str, Any]]) -> Dict[str, Any]:
    readings = [read_metric(project, d) for d in decls]
    # Emit into the per-step channel. Keys are already `<step>__<name>` so
    # `step_metrics.emit` passes them through instead of re-prefixing.
    by_step: Dict[str, Dict[str, Any]] = {}
    for r in readings:
        by_step.setdefault(r["step"], {})[r["key"]] = r["value"]
    written: List[str] = []
    for step, kv in sorted(by_step.items()):
        p = _sm.emit_best_effort(project, step, kv)
        if p is not None:
            written.append(str(p))
    measured = [r for r in readings if r["value"] != NOT_MEASURED]
    not_measured = [r for r in readings if r["value"] == NOT_MEASURED]
    return {
        "schema": "vibe-ic/flow-metric-record/1",
        "declared": len(readings),
        "measured": len(measured),
        "not_measured": len(not_measured),
        "not_measured_keys": sorted(r["key"] for r in not_measured),
        "by_axis": {
            a: {"declared": sum(1 for r in readings if r["axis"] == a),
                "measured": sum(1 for r in readings
                                if r["axis"] == a
                                and r["value"] != NOT_MEASURED)}
            for a in sorted({r["axis"] for r in readings})},
        "provenance_counts": {
            k: sum(1 for r in readings if r["provenance"] == k)
            for k in PROVENANCE_ORDER},
        "metrics": readings,
        "step_files_written": written,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="run directory to record metrics for")
    ap.add_argument("--flow-def", default=None)
    ap.add_argument("--json", dest="json_out", default=None,
                    help="roll-up path (default: <project>/reports/metrics/"
                         "ppa.json)")
    ap.add_argument("--require-measured", action="store_true",
                    help="exit 1 if any declared metric is NOT_MEASURED")
    ap.add_argument("--require-provenance", default=None,
                    choices=list(PROVENANCE_ORDER),
                    help="exit 1 if any MEASURED reading is weaker than this")
    a = ap.parse_args(list(argv) if argv is not None else None)

    project = Path(a.project)
    if not project.is_dir():
        print(f"[{_NAME}] NOT RECORDED — no such project directory: "
              f"{project}", file=sys.stderr)
        return RC_NOT_RECORDED
    if yaml is None:
        print(f"[{_NAME}] NOT RECORDED — PyYAML is not importable, so the "
              f"flow's declarations could not be read. This is not a run with "
              f"no metrics.", file=sys.stderr)
        return RC_NOT_RECORDED
    flow = find_flow_def(a.flow_def)
    if flow is None:
        print(f"[{_NAME}] NOT RECORDED — the canonical flow definition was "
              f"not found.", file=sys.stderr)
        return RC_NOT_RECORDED
    try:
        doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[{_NAME}] NOT RECORDED — {flow} did not parse: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_NOT_RECORDED
    decls, defects = declarations(doc if isinstance(doc, dict) else {})
    if not decls:
        print(f"[{_NAME}] NOT RECORDED — {flow} declares no metrics, so there "
              f"is nothing this run was owed. That is a flow with no "
              f"declarations, not a run with no numbers; "
              f"`flow_metric_coverage_check` is the check for it.",
              file=sys.stderr)
        return RC_NOT_RECORDED

    rep = record(project, decls)
    rep["flow"] = str(flow)
    rep["declaration_defects"] = defects
    out = Path(a.json_out) if a.json_out else \
        project / _sm.METRICS_REL / "ppa.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(out, json.dumps(rep, indent=1, sort_keys=True) + "\n")

    print(f"[{_NAME}] {project}")
    print(f"  {rep['measured']}/{rep['declared']} declared metric(s) measured; "
          f"{rep['not_measured']} NOT_MEASURED")
    for axis, d in sorted(rep["by_axis"].items()):
        print(f"    {axis:<12} {d['measured']}/{d['declared']}")
    for r in rep["metrics"]:
        if r["value"] == NOT_MEASURED:
            print(f"    NOT_MEASURED  {r['key']}  <- {r['source']}  "
                  f"({r['detail']})")
        else:
            u = f" {r['unit']}" if r.get("unit") else ""
            print(f"    {r['value']!r}{u}  {r['key']}  "
                  f"[{r['provenance']}] {r['detail']}")
    print(f"  roll-up: {out}")
    for f in rep["step_files_written"]:
        print(f"  step file: {f}")

    rc = RC_OK
    if defects:
        print(f"[{_NAME}] {len(defects)} declaration defect(s) in the flow:",
              file=sys.stderr)
        for d in defects:
            print(f"  {d}", file=sys.stderr)
        rc = RC_VIOLATION
    if a.require_measured and rep["not_measured"]:
        print(f"[{_NAME}] FAIL — {rep['not_measured']} declared metric(s) are "
              f"NOT_MEASURED and this caller requires all of them: "
              f"{', '.join(rep['not_measured_keys'])}", file=sys.stderr)
        rc = RC_VIOLATION
    if a.require_provenance:
        floor = PROVENANCE_ORDER.index(a.require_provenance)
        weak = [r for r in rep["metrics"]
                if r["value"] != NOT_MEASURED
                and PROVENANCE_ORDER.index(r["provenance"]) < floor]
        if weak:
            named = ", ".join(f"{r['key']}({r['provenance']})" for r in weak)
            print(f"[{_NAME}] FAIL — {len(weak)} reading(s) weaker than "
                  f"{a.require_provenance!r}: {named}", file=sys.stderr)
            rc = RC_VIOLATION
    return rc


if __name__ == "__main__":
    sys.exit(main())
