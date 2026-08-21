#!/usr/bin/env python3
"""LibreLane output -> canonical metric records. Parsing only, no verdicts.

WHY THIS BACKEND EXISTS AT ALL
==============================

LibreLane is the opponent in the head-to-head this repository wants to publish
("can this project produce better PPA than a LibreLane baseline?", vibe-ic#1121).
An opponent's numbers have to be read out of the opponent's own artefacts by
code that has no opinion about who should win -- otherwise the comparison starts
with a translation step nobody can audit.

EVERYTHING BELOW WAS READ OUT OF THE INSTALLED TOOL, NOT OUT OF A DOCUMENT
=========================================================================

Measured 2026-08-21 against LibreLane 3.1.0.dev1 as shipped in the pinned runner
image (`landing_pytest_runtime_preflight.RUNNER_IMAGE`), at
`/usr/local/lib/python3.12/dist-packages/librelane`. The version is recorded in
every record this module emits, because all three facts below are facts about a
VERSION and a later one may differ.

  (1) WHERE THE NUMBERS ARE.  `State.save_snapshot` (`state/state.py`) writes
      `metrics.json` and `metrics.csv` (header `Metric,Value`) into the
      snapshot directory; `Flow` writes `signoff/<design>/metrics.csv` and
      `signoff/<design>/openlane-signoff/resolved.json` into the final dir.
      There is NO `final_summary_report.csv` in this version -- that name is
      OpenLane 1's. A parser written from the remembered name finds nothing,
      and per this repository's hard rule, finding nothing must not read as
      finding it clean.

  (2) THE METRIC NAME IS A SCOPE.  These are METRICS2.1 names, and
      `common/metrics/metric.py: Metric.modified_name` builds them as

          "__".join([name] + [f"{k}:{v}" for k, v in modifiers.items()])

      so `timing__setup__ws__corner:<corner>` is a PER-CORNER value while the
      bare `timing__setup__ws` is a CROSS-CORNER AGGREGATE produced by the
      metric's `aggregator` -- the docstring at `metric.py:96` says so in those
      words. The two are different metrics. Feeding an aggregate into a
      comparison against another flow's per-corner number is precisely the
      "same corner/mode" defect, arriving through a name that looks identical.
      `split_modifiers` is therefore not a convenience: it is the thing that
      makes the corner visible to the fairness check.

  (3) LIBRELANE'S POWER IS VECTORLESS, BY CONSTRUCTION.

          grep -rniE "read_vcd|set_power_activity|\\bvcd\\b|saif" \\
               /usr/local/lib/python3.12/dist-packages/librelane \\
               --include=*.tcl --include=*.py | wc -l
          -> 0

      and the only producer of `power__*` is
      `scripts/openroad/sta/corner.tcl:130-142`:

          report_power -corner $corner_name

      with no activity file of any kind. So `power__total` from this version is
      OpenSTA's default-activity estimate. It is not a campaign setting a
      campaign could have chosen differently, which means a record claiming a
      VCD basis for a LibreLane arm is contradicting the tool, and this module
      can say so from evidence instead of trusting the claim.

WHAT THIS MODULE REFUSES TO DO
==============================

It does not decide whether a number is good. It does not compare arms. It does
not read `design__die__bbox` as an area: that metric is a BBOX STRING
("llx lly urx ury") and `design__die__area` does not exist in this version, so
an area derived from it is emitted with `status: DERIVED` and its formula
attached -- never as a MEASURED number, because nobody measured it.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: every name here is a tool metric
name; no design, PDK, process or vendor literal appears or can affect behaviour.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "TOOL", "MEASURED_AGAINST_VERSION", "POWER_ACTIVITY_BASIS",
    "METRICS_FILENAMES", "AREA_METRICS", "TIMING_METRICS", "POWER_METRICS",
    "FEASIBILITY_METRICS",
    "split_modifiers", "read_metrics", "to_records", "power_activity_basis",
    "NotReadable",
]

TOOL = "librelane"

#: The version these facts were measured against. Recorded in every record so a
#: reader can tell whether the parse was made against the tool they ran.
MEASURED_AGAINST_VERSION = "3.1.0.dev1"

#: See (3) in the module docstring. This is the tool's behaviour, measured, not
#: a default this module chose.
POWER_ACTIVITY_BASIS = "vectorless"

#: The files this version actually writes, in the order a caller should try
#: them. `metrics.json` is preferred because the CSV is a rendering of it.
METRICS_FILENAMES = ("metrics.json", "metrics.csv")

#: Names harvested from the installed tool. Grouped by the axis they inform;
#: the grouping carries no threshold and no direction.
AREA_METRICS = ("design__instance__area", "design__instance__count",
                "design__instance__utilization", "design__die__bbox",
                "design__core__bbox")
TIMING_METRICS = ("timing__setup__ws", "timing__hold__ws", "timing__setup__tns",
                  "timing__hold__tns", "timing__setup_vio__count",
                  "timing__hold_vio__count",
                  "design__max_cap_violation__count",
                  "design__max_slew_violation__count")
POWER_METRICS = ("power__internal__total", "power__switching__total",
                 "power__leakage__total", "power__total")
FEASIBILITY_METRICS = ("magic__drc_error__count", "klayout__drc_error__count",
                       "route__drc_errors", "design__lvs_error__count",
                       "antenna__violating__nets", "antenna__violating__pins",
                       "route__antenna_violation__count",
                       "design__power_grid_violation__count")

#: A bbox is four numbers in one string, and an area computed from it is
#: DERIVED. The formula travels with the number.
_BBOX_AREA_FORMULA = "(urx - llx) * (ury - lly), from design__{}__bbox"


class NotReadable(Exception):
    """The input could not be read, which is NOT the same as reading an empty one.

    Hard rule, paid for three times in one day: "I could not read it" and "I read
    it and it was empty" must never produce the same verdict. Every caller of
    this module gets an exception for the first and an empty mapping with a
    stated denominator for the second.
    """

    def __init__(self, path: Any, reason: str):
        super().__init__(f"[CANNOT CHECK] {path}: {reason}")
        self.path = str(path)
        self.reason = reason


def split_modifiers(name: str) -> Tuple[str, Dict[str, str]]:
    """`a__b__corner:X__k:v` -> `("a__b", {"corner": "X", "k": "v"})`.

    METRICS2.1 modifiers are `key:value` segments appended after `__`. A segment
    without a colon is part of the base name, so `timing__setup__ws` splits to
    itself with no modifiers -- which is the honest answer, because that name IS
    the cross-corner aggregate and not a per-corner reading.
    """
    parts = name.split("__")
    base: List[str] = []
    mods: Dict[str, str] = {}
    for i, part in enumerate(parts):
        if ":" in part and base:
            key, _, value = part.partition(":")
            mods[key] = value
        elif mods:
            # A non-modifier segment after a modifier is not a shape this tool
            # emits; keeping it in the base rather than guessing keeps the
            # round-trip honest.
            base.append(part)
        else:
            base.append(part)
    return "__".join(base), mods


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def read_metrics(where: os.PathLike | str) -> Tuple[Dict[str, Any], Path, str]:
    """Read LibreLane's metrics from a file or a run/snapshot directory.

    Returns `(metrics, path_read, sha256_of_that_file)`.

    Raises `NotReadable` when there is nothing to read, when the file is not
    parseable, or when the directory carries none of the names this version
    writes. It never returns `{}` for those cases -- an empty mapping here means
    the tool wrote a metrics file containing no metrics, which is a different
    fact and a caller is entitled to tell them apart.
    """
    p = Path(where)
    if p.is_dir():
        candidates = [p / n for n in METRICS_FILENAMES]
        found = [c for c in candidates if c.is_file()]
        if not found:
            # Say what was looked for AND where. A zero over an unnamed
            # population is not a measurement.
            raise NotReadable(
                p, "carries none of " + ", ".join(METRICS_FILENAMES)
                + f" (searched {len(candidates)} name(s) in this directory; "
                  "LibreLane writes them via State.save_snapshot and "
                  "Flow.<final>/signoff/<design>/)")
        p = found[0]
    if not p.is_file():
        raise NotReadable(p, "no such file")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotReadable(p, f"unreadable: {exc}")
    digest = _sha256_file(p)
    if p.suffix == ".json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NotReadable(p, f"not JSON: {exc}")
        if not isinstance(doc, dict):
            raise NotReadable(p, "top level is not an object")
        return doc, p, digest
    if p.suffix == ".csv":
        rows = list(csv.reader(text.splitlines()))
        if not rows:
            raise NotReadable(p, "empty file, not even a header row")
        header = [c.strip() for c in rows[0]]
        if header[:2] != ["Metric", "Value"]:
            raise NotReadable(
                p, f"header is {header!r}; this version writes "
                   "('Metric', 'Value') from State.metrics_to_csv")
        out: Dict[str, Any] = {}
        for row in rows[1:]:
            if len(row) < 2:
                continue
            out[row[0]] = _coerce(row[1])
        return out, p, digest
    raise NotReadable(p, f"unsupported extension {p.suffix!r}")


def _coerce(raw: str) -> Any:
    """CSV carries everything as text; a number that round-trips is a number.

    A value that does not parse as a number stays a STRING. `design__die__bbox`
    is the case that matters: silently coercing it would turn a bbox into a
    NaN-shaped nothing and lose the fact that it was never an area.
    """
    s = raw.strip()
    if s == "":
        return None
    try:
        i = int(s)
        return i
    except ValueError:
        pass
    try:
        f = float(s)
    except ValueError:
        return s
    # Reject the three floats that are not JSON, per canonical_json's rule.
    if f != f or f in (float("inf"), float("-inf")):
        return s
    return f


def power_activity_basis(metrics: Optional[Mapping[str, Any]] = None) -> str:
    """The activity basis of this tool's power numbers. Always vectorless here.

    It takes `metrics` so a caller can pass what it read, and ignores it, so
    that the day LibreLane grows a `power__activity_basis` metric this function
    is the one place that has to change. Returning a constant today is honest
    because the constant was MEASURED from the tool (docstring (3)), not
    assumed from a default.
    """
    return POWER_ACTIVITY_BASIS


def to_records(metrics: Mapping[str, Any], *, source_path: os.PathLike | str,
               source_sha256: str, tool_version: str = MEASURED_AGAINST_VERSION,
               parser_sha256: Optional[str] = None) -> List[Dict[str, Any]]:
    """Canonical `vibeic.ppa.metric.v1` records, one per LibreLane metric.

    The modifiers become `scope`, so the corner a number was taken at stops
    being a substring of its name and becomes something a fairness check can
    compare. A metric with NO corner modifier gets
    `scope.corner = "__AGGREGATE__"` rather than nothing: the absence of a
    corner on an aggregate is information, and dropping it would let a
    cross-corner aggregate compare equal to a per-corner reading.

    Power records additionally carry `scope.activity_basis`, filled from the
    TOOL and not from the record, for the reason in docstring (3).

    Nothing here decides whether any value is good, and no value is recomputed:
    `status` is MEASURED for what the tool wrote, and the one derived quantity
    (an area from a bbox) is DERIVED and carries its formula.
    """
    out: List[Dict[str, Any]] = []
    source = {"path": str(source_path), "sha256": source_sha256,
              "tool": TOOL, "tool_version": tool_version,
              "parser": "_ppa/backends/librelane.py"}
    if parser_sha256:
        source["parser_sha256"] = parser_sha256
    for name in sorted(metrics):
        value = metrics[name]
        base, mods = split_modifiers(name)
        scope: Dict[str, Any] = {"tool_metric": base}
        scope["corner"] = mods.get("corner", "__AGGREGATE__")
        for k, v in sorted(mods.items()):
            if k != "corner":
                scope[k] = v
        if base in POWER_METRICS:
            scope["activity_basis"] = power_activity_basis(metrics)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append({
                "schema": "vibeic.ppa.metric.v1", "metric": name,
                "status": "INVALID" if value is not None else "NOT_MEASURED",
                "reason": (f"the tool wrote a non-numeric value {value!r}"
                           if value is not None else
                           "the tool wrote no value for this metric"),
                "scope": scope, "source": dict(source),
            })
            if base in ("design__die__bbox", "design__core__bbox") and \
                    isinstance(value, str):
                derived = _bbox_area(base, value, scope, source)
                if derived is not None:
                    out.append(derived)
            continue
        out.append({
            "schema": "vibeic.ppa.metric.v1", "metric": name,
            "status": "MEASURED", "value": value, "scope": scope,
            "source": dict(source),
        })
    return out


def _bbox_area(base: str, raw: str, scope: Mapping[str, Any],
               source: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """An area from a bbox string, marked DERIVED and carrying its formula.

    `design__die__area` does not exist in this LibreLane; the die geometry is a
    bbox string. Emitting the area as MEASURED would state that the tool
    measured something it never reported, so it is DERIVED -- and per the frozen
    contract a derived number carries the formula that produced it, which is
    what makes it recomputable by a reader who distrusts this parser.
    """
    parts = raw.replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        llx, lly, urx, ury = (float(x) for x in parts)
    except ValueError:
        return None
    which = base.split("__")[1]
    return {
        "schema": "vibeic.ppa.metric.v1",
        "metric": f"design__{which}__area__DERIVED",
        "status": "DERIVED",
        "value": (urx - llx) * (ury - lly),
        "formula": _BBOX_AREA_FORMULA.format(which),
        "derived_from": {base: raw},
        "scope": dict(scope),
        "source": dict(source),
    }


# ── the driver seam (`_ppa/backends/__init__.py`) ───────────────────────────
def extract_records(path, **_opts):
    """Canonical records from a LibreLane metrics file, or a run directory.

    `read_metrics` already accepts either and returns the file it actually read
    plus that file's hash, so the record's provenance names the artefact rather
    than the directory it was found under.

    NOTE, and it is not small: the records this returns do NOT yet satisfy
    `_ppa/metrics.validate` -- measured 2026-08-21, every MEASURED row comes
    back BAD_METRIC_NAME (LibreLane's `design__instance__area` is not a dotted
    canonical name), SCOPE_INCOMPLETE (no `stage`) and NO_UNIT (no `unit` key at
    all). Driving this backend is therefore honest about what it produces and
    the assembler will refuse the rows; mapping LibreLane's keys onto canonical
    names and units needs evidence for each unit that this lane does not have,
    and inventing them is the defect `openroad.py` refuses by name ("It does not
    map a `-metrics` JSON key whose unit it could not establish from evidence").
    """
    metrics, read_path, sha = read_metrics(path)
    return to_records(metrics, source_path=read_path, source_sha256=sha)
