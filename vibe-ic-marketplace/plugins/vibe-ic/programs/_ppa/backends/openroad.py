#!/usr/bin/env python3
"""OpenROAD -> canonical PPA metric records. Parsing only; no judgement.

WHAT THIS MODULE IS FOR
-----------------------
OpenROAD writes the post-route facts — die and core area, the several different
utilisations, cell area, congestion and overflow, the resizer's DRV counts, and
the router's own DRC counts. This module turns what it ACTUALLY writes into
records of the one canonical shape (`docs/PPA_INTERFACES.md` §2) so that
`_ppa/area.py`, `_ppa/feasibility.py` and the rest can decide what they mean
without any of them learning OpenROAD's log grammar.

It contains no threshold, no comparison against a target and no verdict, and it
never exits 1. rc=1 is a claim about silicon; a parser has none to make.

THE THREE THINGS THAT GO WRONG IN A FILE LIKE THIS, AND WHAT IS DONE ABOUT EACH
------------------------------------------------------------------------------

1. **"The report was empty" and "the design was clean" both look like zero.**
   Every metric here is emitted with an explicit status, and a figure that is
   not present is NEVER a 0. The discriminator, measured against 103 real
   `openroad.log` files on this host spanning 12 distinct OpenROAD builds, is:

   * the file does not exist, is empty, or is not an OpenROAD log at all
     -> NO records at all, a REFUSAL, and rc=2 from the CLI. A caller that
     cannot see its input must not be handed a document full of zeros;
   * the file is an OpenROAD log and the stage that would have printed the
     figure never ran (no `[INFO DRT-0194] Start detail routing`, no
     `[INFO DPL-`, ...) -> `NOT_MEASURED` with reason `STAGE_NOT_RUN`. Three
     real logs on this host are exactly this: build 26Q3-1472 aborted after
     `check_placement`, 578-761 bytes, banner and `[INFO ODB-...]` present and
     not one routing figure;
   * the stage DID run and the figure is still absent or unparseable ->
     `INVALID` with reason `FIGURE_ABSENT_THOUGH_STAGE_RAN`. §2's definition of
     INVALID is "the artefact exists but cannot support the metric", and that is
     precisely this case.

2. **OpenROAD's output shape changes between builds.** Measured, not assumed —
   detailed placement reports its utilisation TWO incompatible ways:

       26Q3-155 and older:
         [INFO DPL-0006] Core area: 23224.32 um^2, Instances area: 5865.96 um^2, Utilization: 25.3%
       26Q3-951 and newer:
         [INFO DPL-0006] Core area: 12294.37 um^2
         [INFO DPL-0007] Movable instances area: 7135.13 um^2
         [INFO DPL-0008] Fixed instances area within core: 146.36 um^2
         [INFO DPL-0009] Utilization: 59.2%

   `DPL-0007/0008/0009` do not exist at all in the older build. A parser written
   against either alone finds nothing in the other and, if it defaults, publishes
   a false zero. So both dialects are accepted, the one that matched is reported
   in `dialects`, and the tool version is recorded on EVERY record
   (`source.tool_commit`) so a number can always be traced to the build that
   produced it. A `DPL-0006` line matching NEITHER dialect is a refusal for the
   detailed-placement metrics, not a guess at which field is which.

3. **Utilisation is a ratio and area is a quantity, and OpenROAD prints FOUR
   different utilisations in ONE log, in TWO units.** From a single real run:

       [INFO IFP-0104] Effective utilization: 0.383      <- ratio, unit "1"
       [INFO GPL-0019] Utilization:    44.379 %          <- percent
       [INFO DPL-0009] Utilization: 59.2%   (last of 6)  <- percent
       Design area 12294 um^2 100% utilization.          <- percent, INTEGER-rounded

   Those are FOUR METRICS, not four readings of one, and they are emitted under
   four names with their printed units unconverted. The last one is printed
   AFTER `[INFO DPL-0001] Placed 288 filler instances`, so its percentage is
   post-filler and was 100 on a design that is 59.2 % utilised; its `scope`
   therefore carries `fill: "post_fill"` and `rounding: "integer"` so that §2's
   "two numbers are comparable only if their scope matches" keeps it away from
   the others by construction.

A FOURTH THING, WHICH BELONGS TO THE READER RATHER THAN THE WRITER
-----------------------------------------------------------------
Every figure OpenROAD prints to the log is REPRINTED as the tool iterates. On
one measured run `Total wire length` appears 5 times (13033 first, 12704 last —
2.6 % apart) and `[INFO DPL-0009] Utilization` 6 times (45.6 -> 59.2). Only the
LAST describes the geometry that ships. `re.search` returns the FIRST. Every
selection here is therefore the last match, and the record says so:
`source.occurrences` is how many times the figure appeared and
`source.selection` is `"last"`, so the reprint is visible in the document
instead of invisible in the parser.

The same trap exists, worse, in OpenROAD's `-metrics` JSON: measured on four
real runs, `openroad.metrics.json` is an APPEND LOG with duplicate keys — 247
key/value pairs for 89 distinct keys — and `json.load` keeps the last only by
CPython dict semantics, not by any contract. On one run
`detailedroute__antenna__violating__nets` holds `[5, 5, 5, 0, 0, 0, 0]`: a
reader that took the first would report five antenna violations on a design that
ends with none. This module parses that file with `object_pairs_hook`, takes the
last EXPLICITLY, and records the occurrence count.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
* It does not DECIDE which of the log and the metrics JSON is right. Measured
  on four independent runs of build 26Q3-1535 they DISAGREE — e.g. JSON
  wirelength 39925 where the log's last total says 39887, JSON vias 4079 where
  the log says 4046. A parser that silently picked one would delete the evidence
  that there was ever a question.

  What it DOES do, from v1.11.69, is APPLY a decision somebody else wrote down.
  `_ppa/contract.py:METRIC_ARTEFACT_AUTHORITY` names three metrics, the artefact
  order for each, and the measurement behind it (the JSON's last entry matches
  the `routed.def` that ships in 10 of 10 uncontaminated run trees; the log's
  last total matches in 6, and in none of the 4 where they differ). `parse_run`
  reads that table, keeps the authoritative reading, and writes the overridden
  one into `source.overridden_by_authority` beside it. Nothing is deleted and
  nothing outside those three metrics is touched — those are still emitted
  twice with different `source.path` and still refused by the index.
* It does not report a post-repair DRV residual. `[INFO RSZ-00xx] Found N slew
  violations` is printed by `repair_design` BEFORE it repairs, and no build on
  record re-prints a count afterwards; the metric names therefore end in
  `.pre_repair` and `drv.residual.violation.count` is emitted `NOT_MEASURED`
  with that as its reason.
* It does not invent a macro area. No OpenROAD line states one.
  `[INFO GPL-0021] Large instances area` is the global placer's own
  size-threshold proxy, so it is emitted under that literal name and
  `area.macro.um2` is `NOT_MEASURED`.
* It does not map a `-metrics` JSON key whose unit it could not establish from
  evidence. Unmapped keys are COUNTED and listed in the diagnostics, never
  guessed into a metric.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import (Any, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

_HERE = Path(__file__).resolve()
_PROGRAMS = _HERE.parents[2]                       # plugins/vibe-ic/programs
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from _ppa import canonical_json as _cj             # noqa: E402
# THE DECLARATION, not a policy this module invented. `_ppa/contract.py` names
# which artefact of this tool is authoritative for which metric and states the
# measurement that decided it; `parse_run` reads that table. The dependency is
# a backend importing a DECLARATION, not a backend importing a domain rule: it
# gains no ability to decide anything, only to obey something written down.
from _ppa import contract as _contract            # noqa: E402
# ONE implementation of the router's iterative DRC trajectory, shared with
# `signoff_audit` and `phase3_one_shot_runner`. Re-deriving the regex here would
# create a second reader that can disagree with them about one number, which is
# the exact class of defect the PPA contract exists to remove. If this import
# fails the module is mis-installed -- that is an internal error (rc=3), never a
# quiet fallback to a private copy.
from _signoff_drc_format import router_iter_counts  # noqa: E402

__all__ = [
    "SCHEMA", "TOOL", "PARSER",
    "ParseOutcome", "parse_log", "parse_metrics_json", "parse_run", "main",
]

SCHEMA = "vibeic.ppa.metric.v1"
TOOL = "openroad"
PARSER = "_ppa/backends/openroad.py"

# rc contract (docs/PPA_INTERFACES.md §1). 1 is ABSENT on purpose: see module
# docstring.
RC_OK = 0
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

_STATUS_WITH_VALUE = ("MEASURED", "DERIVED")
_STATUS_WITH_REASON = ("NOT_MEASURED", "NOT_APPLICABLE", "INVALID")


# ── identity ────────────────────────────────────────────────────────────────
_PARSER_SHA: Optional[str] = None


def _parser_sha256() -> str:
    """`sha256:` of this module's own source bytes.

    Read from the .py rather than from `__loader__` so that a stale .pyc can
    never make two runs of different code claim the same parser identity.
    """
    global _PARSER_SHA
    if _PARSER_SHA is None:
        _PARSER_SHA = "sha256:" + hashlib.sha256(_HERE.read_bytes()).hexdigest()
    return _PARSER_SHA


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# ── the record constructor ──────────────────────────────────────────────────
class RecordError(ValueError):
    """A record was built that violates §2. Always an internal error (rc=3)."""


def _record(metric: str, status: str, unit: str, scope: Dict[str, Any],
            source: Dict[str, Any], *,
            value: Any = None, reason: Optional[str] = None,
            formula: Optional[str] = None) -> Dict[str, Any]:
    """Build one `vibeic.ppa.metric.v1` record, refusing the shapes §2 forbids.

    The rules enforced here, each because its opposite is what a hurried author
    writes: a MEASURED record must carry a value and must NOT carry a reason; a
    NOT_MEASURED / NOT_APPLICABLE / INVALID record must carry a reason and must
    NOT carry a value -- not 0, not -1, not "" (§2, "no numeric sentinels"); a
    DERIVED record must state its formula, because a number nobody can recompute
    is not evidence; and no value may be NaN or an infinity, which
    `canonical_json` would refuse at serialization time anyway but which is
    better refused at the point it was invented.
    """
    if status in _STATUS_WITH_VALUE:
        if value is None:
            raise RecordError(f"{metric}: status {status} needs a value")
        if reason is not None:
            raise RecordError(f"{metric}: status {status} must not carry a reason")
        if isinstance(value, float) and not math.isfinite(value):
            raise RecordError(f"{metric}: {value!r} is not a JSON number")
    elif status in _STATUS_WITH_REASON:
        if reason is None:
            raise RecordError(f"{metric}: status {status} needs a reason")
        if value is not None:
            raise RecordError(
                f"{metric}: status {status} must not carry a value "
                f"({value!r}) -- a sentinel is how a not-measured metric "
                f"becomes a number in a comparison")
    else:
        raise RecordError(f"{metric}: unknown status {status!r}")
    if status == "DERIVED" and not formula:
        raise RecordError(f"{metric}: DERIVED needs a formula")

    rec: Dict[str, Any] = {
        "schema": SCHEMA,
        "metric": metric,
        "status": status,
        "unit": unit,
        "scope": dict(scope),
        "source": dict(source),
    }
    if status in _STATUS_WITH_VALUE:
        rec["value"] = value
    else:
        rec["reason"] = reason
    if formula:
        rec["formula"] = formula
    return rec


class ParseOutcome:
    """What a backend hands back: records, refusals, and how it was read.

    `refusals` is never empty when `records` is empty -- "I could not read it"
    and "I read it and there was nothing" must not produce the same object.
    """

    def __init__(self) -> None:
        self.tool_version: Optional[str] = None
        self.records: List[Dict[str, Any]] = []
        self.refusals: List[Dict[str, str]] = []
        self.diagnostics: List[Dict[str, Any]] = []
        self.dialects: Dict[str, str] = {}
        self.sources: List[Dict[str, str]] = []

    # -- accessors used by callers and tests --------------------------------
    @property
    def ok(self) -> bool:
        """True when at least one metric was actually MEASURED or DERIVED.

        A document of nothing but NOT_MEASURED rows is honest but is not a
        measurement, and the CLI's rc reflects that.
        """
        return any(r["status"] in _STATUS_WITH_VALUE for r in self.records)

    def refuse(self, code: str, detail: str, marker: str = "[CANNOT CHECK]") -> None:
        self.refusals.append({"code": code, "detail": detail, "marker": marker})

    def note(self, code: str, **kw: Any) -> None:
        d: Dict[str, Any] = {"code": code}
        d.update(kw)
        self.diagnostics.append(d)

    def by_metric(self, metric: str) -> List[Dict[str, Any]]:
        return [r for r in self.records if r["metric"] == metric]

    def one(self, metric: str) -> Optional[Dict[str, Any]]:
        """The single record for `metric`, or None. Raises if there are several
        -- a caller that says `one` and gets two has a conflict to handle, and
        silently returning the first is how a conflict becomes a fact."""
        hits = self.by_metric(metric)
        if not hits:
            return None
        if len(hits) > 1:
            raise KeyError(f"{metric}: {len(hits)} records; use by_metric()")
        return hits[0]

    def document(self) -> Dict[str, Any]:
        return {
            "schema": "vibeic.ppa.backend_records.v1",
            "tool": TOOL,
            "tool_version": self.tool_version,
            "parser": PARSER,
            "parser_sha256": _parser_sha256(),
            "dialects": dict(self.dialects),
            "sources": list(self.sources),
            "records": list(self.records),
            "refusals": list(self.refusals),
            "diagnostics": list(self.diagnostics),
        }


# ── log grammar ─────────────────────────────────────────────────────────────
# Every pattern below was written against a real specimen on this host. Nothing
# here is extrapolated from OpenROAD's source: the lane rule is to refuse a
# shape rather than guess a field, and a regex written for a line nobody has
# seen is a guess that reports numbers.
_RE_BANNER = re.compile(r"^OpenROAD\s+(\S+)")
_RE_MSG_CODE = re.compile(r"\[(?:INFO|WARNING|ERROR) [A-Z]{2,4}-\d{4}\]")

_RE_IFP_DIE = re.compile(
    r"\[INFO IFP-0100\]\s*Die BBox:\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)"
    r"\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)\s*um")
_RE_IFP_CORE_BBOX = re.compile(
    r"\[INFO IFP-0101\]\s*Core BBox:\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)"
    r"\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)\s*um")
_RE_IFP_CORE_AREA = re.compile(r"\[INFO IFP-0102\]\s*Core area:\s*([\d.]+)\s*um\^2")
_RE_IFP_INST_AREA = re.compile(
    r"\[INFO IFP-0103\]\s*Total instances area:\s*([\d.]+)\s*um\^2")
_RE_IFP_EFF_UTIL = re.compile(r"\[INFO IFP-0104\]\s*Effective utilization:\s*([\d.]+)")
_RE_IFP_NINST = re.compile(r"\[INFO IFP-0105\]\s*Number of instances:\s*(\d+)")

_RE_GPL_UTIL = re.compile(r"\[INFO GPL-0019\]\s*Utilization:\s*([\d.]+)\s*%")
_RE_GPL_LARGE = re.compile(
    r"\[INFO GPL-0021\]\s*Large instances area:\s*([\d.]+)\s*um\^2")
_RE_GPL_OVERFLOW = re.compile(
    r"\[INFO GPL-0041\]\s*Total routing overflow:\s*([\d.]+)")
_RE_GPL_OVTILES = re.compile(
    r"\[INFO GPL-0042\]\s*Number of overflowed tiles:\s*(\d+)\s*\(([\d.]+)%\)")

# Dialect A (26Q3-155 and older): one line, three figures.
_RE_DPL_COMBINED = re.compile(
    r"\[INFO DPL-0006\]\s*Core area:\s*([\d.]+)\s*um\^2,\s*"
    r"Instances area:\s*([\d.]+)\s*um\^2,\s*Utilization:\s*([\d.]+)\s*%")
# Dialect B (26Q3-951 and newer): four lines. The `$` matters -- without it this
# also matches the dialect-A line's prefix and the two dialects stop being
# distinguishable. `[WARNING DPL-0006] Site aligned check failed (1).` is a real
# line on this host and must match NEITHER, which is why the INFO tag and the
# literal `Core area:` are both required.
_RE_DPL_CORE = re.compile(r"\[INFO DPL-0006\]\s*Core area:\s*([\d.]+)\s*um\^2\s*$", re.M)
_RE_DPL_MOVABLE = re.compile(
    r"\[INFO DPL-0007\]\s*Movable instances area:\s*([\d.]+)\s*um\^2")
_RE_DPL_FIXED = re.compile(
    r"\[INFO DPL-0008\]\s*Fixed instances area within core:\s*([\d.]+)\s*um\^2")
_RE_DPL_UTIL = re.compile(r"\[INFO DPL-0009\]\s*Utilization:\s*([\d.]+)\s*%")
_RE_DPL_ANY_0006 = re.compile(r"\[INFO DPL-0006\]")
_RE_DPL_FILLER = re.compile(r"\[INFO DPL-0001\]\s*Placed\s+(\d+)\s+filler instances")

_RE_DESIGN_AREA = re.compile(
    r"^Design area\s+([\d.]+)\s*um\^2\s+([\d.]+)\s*%\s*utilization", re.M)

_RE_WL_TOTAL = re.compile(r"^Total wire length = ([\d.]+) um", re.M)
_RE_WL_LAYER = re.compile(r"^Total wire length on LAYER (\S+) = ([\d.]+) um", re.M)
_RE_VIAS = re.compile(r"^Total number of vias = (\d+)", re.M)

_RE_ANT_NET = re.compile(r"\[INFO ANT-0002\]\s*Found (\d+) net violations")
_RE_ANT_PIN = re.compile(r"\[INFO ANT-0001\]\s*Found (\d+) pin violations")
_RE_GRT_ANT = re.compile(r"\[INFO GRT-0012\]\s*Found (\d+) antenna violations")

_RE_RSZ_SLEW = re.compile(r"\[INFO RSZ-\d{4}\]\s*Found (\d+) slew violations")
_RE_RSZ_CAP = re.compile(r"\[INFO RSZ-\d{4}\]\s*Found (\d+) capacitance violations")
_RE_RSZ_FANOUT = re.compile(r"\[INFO RSZ-\d{4}\]\s*Found (\d+) fanout violations")

_RE_GRT_CONGESTION = re.compile(r"\[INFO GRT-0096\]\s*Final congestion report:")
# One table row of the GRT-0096 report:
#   met1            258243         19924            7.72%             3 /  0 / 60
_RE_GRT_ROW = re.compile(
    r"^(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s*%\s+(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$")

# Which marker proves a stage RAN. This is the whole NOT_MEASURED-vs-INVALID
# discriminator: absent stage marker => the step never happened; present marker
# with the figure missing => the artefact cannot support the metric.
_STAGE_MARKERS: Dict[str, re.Pattern] = {
    "floorplan": re.compile(r"\[INFO IFP-\d{4}\]"),
    "global_placement": re.compile(r"\[INFO GPL-\d{4}\]"),
    "detailed_placement": re.compile(r"\[INFO DPL-\d{4}\]"),
    "global_route": re.compile(r"\[INFO GRT-\d{4}\]"),
    "detailed_route": re.compile(r"\[INFO DRT-0194\]\s*Start detail routing"),
    "antenna": re.compile(r"\[INFO ANT-000[12]\]"),
    "resizer": re.compile(r"\[INFO RSZ-\d{4}\]"),
    "design_area_report": _RE_DESIGN_AREA,
}

# What each stage marker LOOKS LIKE, in words. A reason string is read by a
# person in a report; pasting the raw regex there ("no \\[INFO GRT-\\d{4}\\] in this
# log") is how a status message stops being an explanation.
_STAGE_HUMAN: Dict[str, str] = {
    "floorplan": "any `[INFO IFP-nnnn]` line",
    "global_placement": "any `[INFO GPL-nnnn]` line",
    "detailed_placement": "any `[INFO DPL-nnnn]` line",
    "global_route": "any `[INFO GRT-nnnn]` line",
    "detailed_route": "`[INFO DRT-0194] Start detail routing`",
    "antenna": "any `[INFO ANT-0001/0002]` line",
    "resizer": "any `[INFO RSZ-nnnn]` line",
    "design_area_report": "a `Design area N um^2 P% utilization` line",
}


def _last(pattern: re.Pattern, text: str) -> Tuple[Optional[re.Match], int]:
    """The LAST match and how many there were.

    `re.search` returns the first, which on every iterative OpenROAD figure is
    the state BEFORE the tool converged. Returning the count alongside is what
    lets the record say the figure was reprinted rather than pretending it was
    stated once.
    """
    hits = list(pattern.finditer(text))
    return (hits[-1] if hits else None), len(hits)


def _f(s: str) -> float:
    return float(s)


class _LogEmitter:
    """Bound to one log; every emit carries that log's provenance."""

    def __init__(self, outcome: ParseOutcome, text: str, source: Dict[str, Any]):
        self.o = outcome
        self.t = text
        self.src = source
        self.ran = {k: bool(p.search(text)) for k, p in _STAGE_MARKERS.items()}

    def _source(self, occurrences: int) -> Dict[str, Any]:
        s = dict(self.src)
        s["occurrences"] = occurrences
        s["selection"] = "last"
        return s

    def absent(self, metric: str, unit: str, scope: Dict[str, Any],
               stage_key: str, what: str) -> None:
        """The one place a missing figure becomes a status, so the rule cannot
        drift between metrics."""
        src = self._source(0)
        if not self.ran.get(stage_key, False):
            self.o.records.append(_record(
                metric, "NOT_MEASURED", unit, scope, src,
                reason=(f"STAGE_NOT_RUN: this log carries "
                        f"{_STAGE_HUMAN[stage_key]} nowhere, so OpenROAD never "
                        f"reached the step that prints {what}")))
        else:
            self.o.records.append(_record(
                metric, "INVALID", unit, scope, src,
                reason=(f"FIGURE_ABSENT_THOUGH_STAGE_RAN: the {stage_key} stage "
                        f"ran but this log carries no parseable {what}")))

    def emit(self, metric: str, pattern: re.Pattern, unit: str,
             scope: Dict[str, Any], stage_key: str, what: str,
             group: int = 1, cast=_f) -> None:
        m, n = _last(pattern, self.t)
        if m is None:
            self.absent(metric, unit, scope, stage_key, what)
            return
        self.o.records.append(_record(
            metric, "MEASURED", unit, scope, self._source(n),
            value=cast(m.group(group))))


def _scope(stage: str, **kw: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {"stage": stage, "tool": TOOL}
    s.update(kw)
    return s


def parse_log(path) -> ParseOutcome:
    """Parse one `openroad.log` into canonical records.

    Refuses -- with no records at all -- when the file is absent, empty, or not
    an OpenROAD log. Everything after that point is a per-metric status.
    """
    o = ParseOutcome()
    p = Path(path)
    if not p.exists():
        o.refuse("ARTEFACT_ABSENT", f"{p}: no such file")
        return o
    if p.is_dir():
        o.refuse("ARTEFACT_NOT_A_FILE", f"{p}: is a directory")
        return o
    try:
        raw = p.read_bytes()
    except OSError as exc:
        o.refuse("ARTEFACT_UNREADABLE", f"{p}: {exc}")
        return o
    if not raw.strip():
        # An empty report is not a clean report. This is the single most
        # expensive confusion in this repository's history and it is refused
        # here rather than smoothed over into a document of zeros.
        o.refuse("ARTEFACT_EMPTY",
                 f"{p}: {len(raw)} bytes, nothing to parse -- an empty log is "
                 f"NOT a clean run")
        return o
    text = raw.decode("utf-8", "replace")

    banner = _RE_BANNER.match(text)
    if banner:
        o.tool_version = banner.group(1)
    elif not _RE_MSG_CODE.search(text):
        o.refuse("NOT_AN_OPENROAD_LOG",
                 f"{p}: no `OpenROAD <version>` banner and no OpenROAD message "
                 f"code (`[INFO XXX-nnnn]`) anywhere in {len(raw)} bytes")
        return o
    else:
        # Message codes but no banner: readable, but no build to attribute the
        # numbers to. Say so; do not silently publish unattributed figures.
        o.note("TOOL_VERSION_UNKNOWN", detail=(
            "OpenROAD message codes present but no `OpenROAD <version>` banner; "
            "every record's source.tool_commit is null"))

    source = {
        "path": str(p),
        "sha256": _file_sha256(p),
        "tool": TOOL,
        "tool_commit": o.tool_version,
        "parser": PARSER,
        "parser_sha256": _parser_sha256(),
        # WHICH ARTEFACT OF THIS TOOL. A fact about where the bytes came from,
        # which a backend IS entitled to state -- and the key the declared
        # authority in `_ppa/contract.py` is keyed on. Without it a resolution
        # would have to infer the artefact from a filename.
        "kind": "log",
    }
    o.sources.append({"path": str(p), "sha256": source["sha256"], "kind": "log"})
    e = _LogEmitter(o, text, source)
    o.diagnostics.append({"code": "STAGES_SEEN",
                          "stages": sorted(k for k, v in e.ran.items() if v)})

    _emit_floorplan(o, e, text)
    _emit_global_placement(o, e, text)
    _emit_detailed_placement(o, e, text)
    _emit_design_area_report(o, e, text)
    _emit_route(o, e, text)
    _emit_congestion(o, e, text)
    _emit_antenna(o, e, text)
    _emit_drv(o, e, text)
    return o


def _emit_floorplan(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    sc = _scope("floorplan")
    m, n = _last(_RE_IFP_DIE, text)
    if m is None:
        e.absent("area.die.um2", "um^2", sc, "floorplan",
                 "`[INFO IFP-0100] Die BBox:` line")
    else:
        x0, y0, x1, y1 = (_f(m.group(i)) for i in (1, 2, 3, 4))
        src = e._source(n)
        o.records.append(_record(
            "area.die.um2", "DERIVED", "um^2",
            dict(sc, bbox_um=[x0, y0, x1, y1]), src,
            value=(x1 - x0) * (y1 - y0),
            formula="(x1-x0)*(y1-y0) from [INFO IFP-0100] Die BBox"))
    e.emit("area.core.um2", _RE_IFP_CORE_AREA, "um^2", sc, "floorplan",
           "`[INFO IFP-0102] Core area:` line")
    e.emit("area.instances.total.um2", _RE_IFP_INST_AREA, "um^2", sc, "floorplan",
           "`[INFO IFP-0103] Total instances area:` line")
    # A RATIO, in [0,1], and the only one OpenROAD prints that way. Left
    # unconverted: §3 of the interface says hash the value you PARSED.
    e.emit("utilization.floorplan.effective", _RE_IFP_EFF_UTIL, "1", sc,
           "floorplan", "`[INFO IFP-0104] Effective utilization:` line")
    e.emit("design.instance.count", _RE_IFP_NINST, "1", sc, "floorplan",
           "`[INFO IFP-0105] Number of instances:` line", cast=int)


def _emit_global_placement(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    sc = _scope("global_placement")
    e.emit("utilization.global_placement.pct", _RE_GPL_UTIL, "%", sc,
           "global_placement", "`[INFO GPL-0019] Utilization:` line")
    e.emit("area.instances.large.um2", _RE_GPL_LARGE, "um^2", sc,
           "global_placement", "`[INFO GPL-0021] Large instances area:` line")
    # OpenROAD prints no macro area. GPL-0021 is the placer's own size-threshold
    # proxy and is NOT the same question, so the honest answer is a reason.
    o.records.append(_record(
        "area.macro.um2", "NOT_MEASURED", "um^2", sc, e._source(0),
        reason=("NO_SUCH_FIGURE: no OpenROAD log line states a macro area. "
                "`[INFO GPL-0021] Large instances area` is the global placer's "
                "size-threshold proxy and is emitted as area.instances.large.um2; "
                "substituting it here would answer a different question")))


def _emit_detailed_placement(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    """The two dialects, and the field that does NOT mean the same thing in both.

    It is tempting to map the old dialect's `Instances area` onto the new
    dialect's `Movable instances area` and be done. They are different
    quantities, and each log proves it against its OWN printed utilisation:

        26Q3-155 combined:  6660.66 / 23224.32                = 28.68 %  (prints 28.7 %)
        26Q3-951 split:    11465.53 / 40751.69                = 28.14 %  (prints 32.8 %)
                          (11465.53 + 1898.85) / 40751.69     = 32.79 %  (prints 32.8 %)
        26Q3-984 split:     7135.13 / 12294.37                = 58.04 %  (prints 59.2 %)
                          (7135.13 + 146.36) / 12294.37       = 59.23 %  (prints 59.2 %)

    So the old dialect's single figure is movable PLUS fixed, and the new
    dialect's `Movable instances area` is movable ALONE. Mapping them to one
    metric would put an 11465 next to a 13364 and call them the same number.
    They get separate names; the comparable total is DERIVED in the split
    dialect and states its formula, and the movable/fixed split is NOT_MEASURED
    in the combined dialect because that dialect does not state it.
    """
    sc = _scope("detailed_placement")
    combined, n_comb = _last(_RE_DPL_COMBINED, text)
    core, n_core = _last(_RE_DPL_CORE, text)
    util, n_util = _last(_RE_DPL_UTIL, text)

    if combined is not None:
        o.dialects["detailed_placement"] = "DPL-0006-combined"
        src = e._source(n_comb)
        o.records.append(_record("area.core.um2", "MEASURED", "um^2",
                                 sc, src, value=_f(combined.group(1))))
        o.records.append(_record("area.instances.placed.um2", "MEASURED", "um^2",
                                 sc, src, value=_f(combined.group(2))))
        o.records.append(_record("utilization.detailed_placement.pct", "MEASURED",
                                 "%", sc, src, value=_f(combined.group(3))))
        for metric in ("area.instances.movable.um2",
                       "area.instances.fixed_in_core.um2"):
            o.records.append(_record(
                metric, "NOT_MEASURED", "um^2", sc, src,
                reason=("DIALECT_DOES_NOT_STATE_IT: this OpenROAD build reports "
                        "detailed placement as a single `[INFO DPL-0006] Core "
                        "area: ..., Instances area: ..., Utilization: ...` line. "
                        "Its `Instances area` is movable PLUS fixed (checked "
                        "against the same line's own utilisation) and is emitted "
                        "as area.instances.placed.um2; the build does not "
                        "separate the two")))
        return

    if core is not None or util is not None:
        o.dialects["detailed_placement"] = "DPL-0006/0007/0008/0009-split"
        e.emit("area.core.um2", _RE_DPL_CORE, "um^2", sc, "detailed_placement",
               "`[INFO DPL-0006] Core area:` line")
        e.emit("area.instances.movable.um2", _RE_DPL_MOVABLE, "um^2", sc,
               "detailed_placement", "`[INFO DPL-0007] Movable instances area:` line")
        e.emit("area.instances.fixed_in_core.um2", _RE_DPL_FIXED, "um^2", sc,
               "detailed_placement",
               "`[INFO DPL-0008] Fixed instances area within core:` line")
        e.emit("utilization.detailed_placement.pct", _RE_DPL_UTIL, "%", sc,
               "detailed_placement", "`[INFO DPL-0009] Utilization:` line")
        mov, n_mov = _last(_RE_DPL_MOVABLE, text)
        fix, n_fix = _last(_RE_DPL_FIXED, text)
        if mov is not None and fix is not None:
            o.records.append(_record(
                "area.instances.placed.um2", "DERIVED", "um^2", sc,
                e._source(min(n_mov, n_fix)),
                value=_f(mov.group(1)) + _f(fix.group(1)),
                formula=("[INFO DPL-0007] Movable instances area + [INFO "
                         "DPL-0008] Fixed instances area within core -- the "
                         "quantity the older DPL-0006-combined dialect prints "
                         "as a single `Instances area`")))
        else:
            o.records.append(_record(
                "area.instances.placed.um2", "INVALID", "um^2", sc, e._source(0),
                reason=("COMPONENT_ABSENT: the split dialect states this total "
                        "only as movable + fixed, and this log is missing "
                        + ("the movable" if mov is None else "the fixed")
                        + " component")))
        return

    # Neither dialect. If a DPL-0006 INFO line is nevertheless present, this is a
    # THIRD shape and guessing which number is which is exactly what the lane
    # brief forbids -- so it is refused by name, with the offending line quoted.
    if _RE_DPL_ANY_0006.search(text):
        offending = next((ln.strip() for ln in text.splitlines()
                          if _RE_DPL_ANY_0006.search(ln)), "")
        o.dialects["detailed_placement"] = "UNRECOGNISED"
        o.refuse("DPL_DIALECT_UNRECOGNISED",
                 f"[INFO DPL-0006] present but matches neither known dialect; "
                 f"refusing to guess a field. Offending line: {offending!r}",
                 marker="[REFUSE]")
        reason = (f"UNRECOGNISED_DIALECT: this build prints a `[INFO DPL-0006]` "
                  f"line in a shape this parser does not know ({offending!r}); "
                  f"guessing which figure is which is how a parser invents a "
                  f"number")
        status = "INVALID"
    elif not e.ran["detailed_placement"]:
        reason = ("STAGE_NOT_RUN: no `[INFO DPL-` line in this log, so detailed "
                  "placement never ran")
        status = "NOT_MEASURED"
    else:
        reason = ("FIGURE_ABSENT_THOUGH_STAGE_RAN: `[INFO DPL-` lines are "
                  "present but none of them state a core area or utilisation")
        status = "INVALID"
    src = e._source(0)
    for metric, unit in (("area.core.um2", "um^2"),
                         ("area.instances.placed.um2", "um^2"),
                         ("area.instances.movable.um2", "um^2"),
                         ("area.instances.fixed_in_core.um2", "um^2"),
                         ("utilization.detailed_placement.pct", "%")):
        o.records.append(_record(metric, status, unit, sc, src, reason=reason))


def _emit_design_area_report(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    """`Design area N um^2 P% utilization.` -- and why its scope says so much.

    On one measured run this line reads `Design area 12294 um^2 100%
    utilization.` while the design is 59.2 % utilised, because OpenROAD emits it
    AFTER filler insertion; and its P is integer-rounded (a real log on this host
    prints `0%` for a global-placement utilisation of 0.025 %). Both facts go in
    `scope`, so §2's rule that two numbers are comparable only if their scope
    matches keeps this figure away from the others without anyone remembering to.
    """
    m, n = _last(_RE_DESIGN_AREA, text)
    filler, _ = _last(_RE_DPL_FILLER, text)
    if m is None:
        sc = _scope("post_route", rounding="integer")
        e.absent("area.design_report.um2", "um^2", sc, "design_area_report",
                 "`Design area N um^2 P% utilization` line")
        e.absent("utilization.design_report.pct", "%", sc, "design_area_report",
                 "`Design area N um^2 P% utilization` line")
        return
    fill = "unknown"
    if filler is not None:
        fill = "post_fill" if filler.start() < m.start() else "pre_fill"
    sc_area = _scope("post_route", fill=fill)
    sc_util = _scope("post_route", fill=fill, rounding="integer")
    src = e._source(n)
    o.records.append(_record("area.design_report.um2", "MEASURED", "um^2",
                             sc_area, src, value=_f(m.group(1))))
    o.records.append(_record("utilization.design_report.pct", "MEASURED", "%",
                             sc_util, src, value=_f(m.group(2))))


def _emit_route(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    sc = _scope("detailed_route")
    e.emit("route.wirelength.um", _RE_WL_TOTAL, "um", sc, "detailed_route",
           "`Total wire length = N um.` line")
    e.emit("route.via.count", _RE_VIAS, "1", sc, "detailed_route",
           "`Total number of vias = N.` line", cast=int)

    # Per-layer wirelength belongs to the LAST total block, not to whichever
    # block happened to be scanned first.
    total_hits = list(_RE_WL_TOTAL.finditer(text))
    if total_hits:
        start = total_hits[-1].end()
        stop = len(text)
        nxt = _RE_VIAS.search(text, start)
        if nxt:
            stop = nxt.start()
        block = text[start:stop]
        rows = _RE_WL_LAYER.findall(block)
        src = e._source(len(total_hits))
        for layer, val in rows:
            o.records.append(_record(
                "route.wirelength.by_layer.um", "MEASURED", "um",
                _scope("detailed_route", layer=layer), src, value=_f(val)))
        if not rows:
            # NAME THE WINDOW, not just the pattern. "no rows matched" and
            # "the window I matched in was empty" print the same way and are
            # different findings — the second is a bug in the block bounds
            # above, and a reader cannot tell them apart without the offsets.
            o.note("ROUTE_WIRELENGTH_BY_LAYER_ABSENT",
                   searched_in=(f"the router log, chars [{start}:{stop}] — the "
                                f"window after the LAST of {len(total_hits)} "
                                f"`Total wire length` match(es) and before the "
                                f"next `Total number of vias`"),
                   searched_window_chars=stop - start,
                   detail="no `Total wire length on LAYER` rows follow the last total")

    # The router's own DRC trajectory, through the ONE shared reader.
    counts = router_iter_counts(text)
    if counts:
        o.records.append(_record(
            "route.drc.violation.count", "MEASURED", "1", sc,
            dict(e._source(len(counts)), trajectory_len=len(counts)),
            value=counts[-1]))
    else:
        e.absent("route.drc.violation.count", "1", sc, "detailed_route",
                 "router violation count (`[INFO DRT-0199] Number of violations "
                 "= N` / `Completing 100% with N violations`)")


def _emit_congestion(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    sc_gpl = _scope("global_placement")
    e.emit("route.congestion.overflow.total", _RE_GPL_OVERFLOW, "1", sc_gpl,
           "global_placement", "`[INFO GPL-0041] Total routing overflow:` line")
    m, n = _last(_RE_GPL_OVTILES, text)
    if m is None:
        e.absent("route.congestion.overflowed_tiles.count", "1", sc_gpl,
                 "global_placement",
                 "`[INFO GPL-0042] Number of overflowed tiles:` line")
        e.absent("route.congestion.overflowed_tiles.pct", "%", sc_gpl,
                 "global_placement",
                 "`[INFO GPL-0042] Number of overflowed tiles:` line")
    else:
        src = e._source(n)
        o.records.append(_record("route.congestion.overflowed_tiles.count",
                                 "MEASURED", "1", sc_gpl, src,
                                 value=int(m.group(1))))
        o.records.append(_record("route.congestion.overflowed_tiles.pct",
                                 "MEASURED", "%", sc_gpl, src,
                                 value=_f(m.group(2))))

    # The global router's own table, when it printed one.
    heads = list(_RE_GRT_CONGESTION.finditer(text))
    if not heads:
        for metric, unit in (("route.congestion.resource.count", "1"),
                             ("route.congestion.demand.count", "1"),
                             ("route.congestion.usage.pct", "%"),
                             ("route.congestion.max_h.count", "1"),
                             ("route.congestion.max_v.count", "1"),
                             ("route.congestion.total_congestion.count", "1")):
            e.absent(metric, unit, _scope("global_route"), "global_route",
                     "`[INFO GRT-0096] Final congestion report:` table")
        return
    src = e._source(len(heads))
    block = text[heads[-1].end():]
    rows = 0
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            if rows:
                break
            continue
        # The table's own furniture: the column header, and the dashed rules
        # that sit ABOVE the aggregate row. Breaking on the second rule was the
        # first version of this loop and it silently dropped the `Total` line,
        # which is the one figure a congestion report is usually read for.
        if set(stripped) <= set("-"):
            continue
        if "Resource" in stripped and "Demand" in stripped:
            continue
        row = _RE_GRT_ROW.match(line.rstrip())
        if row is None:
            if rows:
                break
            continue
        name = row.group(1)
        aggregate = (name.lower() == "total")
        sc = _scope("global_route", layer=name, aggregate=aggregate)
        for metric, unit, grp, cast in (
                ("route.congestion.resource.count", "1", 2, int),
                ("route.congestion.demand.count", "1", 3, int),
                ("route.congestion.usage.pct", "%", 4, _f),
                ("route.congestion.max_h.count", "1", 5, int),
                ("route.congestion.max_v.count", "1", 6, int),
                ("route.congestion.total_congestion.count", "1", 7, int)):
            o.records.append(_record(metric, "MEASURED", unit, sc, src,
                                     value=cast(row.group(grp))))
        rows += 1
    o.note("GRT_CONGESTION_ROWS", rows=rows, tables=len(heads))


def _emit_antenna(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    sc = _scope("post_route")
    e.emit("antenna.net.violation.count", _RE_ANT_NET, "1", sc, "antenna",
           "`[INFO ANT-0002] Found N net violations` line", cast=int)
    e.emit("antenna.pin.violation.count", _RE_ANT_PIN, "1", sc, "antenna",
           "`[INFO ANT-0001] Found N pin violations` line", cast=int)
    m, n = _last(_RE_GRT_ANT, text)
    if m is not None:
        o.records.append(_record(
            "antenna.violation.count", "MEASURED", "1",
            _scope("global_route", repair_pass="pre_repair"), e._source(n),
            value=int(m.group(1))))


def _emit_drv(o: ParseOutcome, e: _LogEmitter, text: str) -> None:
    """Resizer DRV counts -- all of them PRE-repair, and the names say so.

    `repair_design` prints `Found N <kind> violations` before it repairs and no
    OpenROAD build on this host re-prints a count afterwards. A metric called
    `drv.max_slew.violation.count` would therefore be read as a residual and be
    wrong; these are named `.pre_repair`, and the residual is emitted as a
    NOT_MEASURED row with that as its reason so it appears in a report instead
    of being silently missing (§2: a report prints the literal NOT_MEASURED row,
    it does not omit it).
    """
    sc = _scope("post_place", repair_pass="pre_repair")
    for metric, pat, kind in (
            ("drv.max_slew.violation.count.pre_repair", _RE_RSZ_SLEW, "slew"),
            ("drv.max_capacitance.violation.count.pre_repair", _RE_RSZ_CAP,
             "capacitance"),
            ("drv.max_fanout.violation.count.pre_repair", _RE_RSZ_FANOUT,
             "fanout")):
        m, n = _last(pat, text)
        if m is not None:
            o.records.append(_record(metric, "MEASURED", "1", sc, e._source(n),
                                     value=int(m.group(1))))
        elif not e.ran["resizer"]:
            o.records.append(_record(
                metric, "NOT_MEASURED", "1", sc, e._source(0),
                reason=("STAGE_NOT_RUN: this log carries no `[INFO RSZ-nnnn]` "
                        "line, so the resizer never ran")))
        else:
            # ABSENCE IS NOT ZERO, and here that is a measurement rather than a
            # scruple. OpenROAD guards these three lines on a non-zero count.
            # Across 103 real openroad.log files on this host there are 703
            # `[INFO RSZ-00{34,35,36}] Found N <kind> violations` lines and NOT
            # ONE has N=0 -- while the control, `[INFO ANT-0002] Found 0 net
            # violations`, occurs 159 times, so a zero-valued "Found ...
            # violations" line is something OpenROAD's grammar does print when
            # it means it. The line's absence is therefore indistinguishable, IN
            # THIS ARTEFACT, from a genuine zero, and reporting 0 would be
            # inferring a number from a silence.
            o.records.append(_record(
                metric, "INVALID", "1", sc, e._source(0),
                reason=(f"ABSENCE_IS_NOT_ZERO: the resizer ran but printed no "
                        f"`Found N {kind} violations` line. OpenROAD emits that "
                        f"line only when N > 0 (measured: 703 such lines over "
                        f"103 real logs, none with N=0), so this artefact "
                        f"cannot distinguish 'zero {kind} violations' from "
                        f"'repair_design was never called'")))
    o.records.append(_record(
        "drv.residual.violation.count", "NOT_MEASURED", "1",
        _scope("post_route", repair_pass="post_repair"), e._source(0),
        reason=("NO_SUCH_FIGURE: OpenROAD's resizer states DRV counts only "
                "BEFORE repair_design repairs them and no build on record "
                "re-prints a residual. The post-repair residual is an OpenSTA "
                "`report_check_types -max_slew -max_capacitance -max_fanout` "
                "question and belongs to the opensta backend")))


# ── the -metrics JSON ───────────────────────────────────────────────────────
# Only keys whose unit could be established from evidence are mapped. Every
# other key is COUNTED and listed, never guessed into a metric.
#
# `utilization__before__dpl` carries no unit in the file. It is mapped as a
# PERCENT because it was cross-checked against the log's last
# `[INFO DPL-0009] Utilization: N%` on four independent runs -- 1.67797 vs 1.7 %,
# and 5.05804 vs 5.1 % on the other three. Without that check it would have
# stayed unmapped.
_JSON_MAP: Dict[str, Tuple[str, str, str]] = {
    "detailedroute__route__drc_errors":
        ("route.drc.violation.count", "1", "detailed_route"),
    "detailedroute__route__wirelength":
        ("route.wirelength.um", "um", "detailed_route"),
    "detailedroute__route__vias":
        ("route.via.count", "1", "detailed_route"),
    "detailedroute__route__vias__singlecut":
        ("route.via.singlecut.count", "1", "detailed_route"),
    "detailedroute__route__vias__multicut":
        ("route.via.multicut.count", "1", "detailed_route"),
    "detailedroute__route__net":
        ("route.net.count", "1", "detailed_route"),
    "detailedroute__route__net__special":
        ("route.net.special.count", "1", "detailed_route"),
    "detailedroute__antenna__violating__nets":
        ("antenna.net.violation.count", "1", "detailed_route"),
    "detailedroute__antenna__violating__pins":
        ("antenna.pin.violation.count", "1", "detailed_route"),
    "detailedroute__antenna_diodes_count":
        ("antenna.diode.count", "1", "detailed_route"),
    "global_route__wirelength":
        ("route.wirelength.um", "um", "global_route"),
    "global_route__vias":
        ("route.via.count", "1", "global_route"),
    "utilization__before__dpl":
        ("utilization.before_detailed_placement.pct", "%", "detailed_placement"),
    "design__violations":
        ("placement.violation.count", "1", "detailed_placement"),
    "floorplan__design__io":
        ("design.io.count", "1", "floorplan"),
    "flow__errors__count":
        ("flow.error.count", "1", "flow"),
    "flow__warnings__count":
        ("flow.warning.count", "1", "flow"),
}

# At least one of these must be present for the file to be OpenROAD's own.
# These prefixes are emitted by the OpenROAD binary itself; an ORFS or LibreLane
# metrics file is a DIFFERENT document that also uses `design__`-style keys, and
# reading one as the other is how a number gets attributed to the wrong tool.
_JSON_SIGNATURE = (
    "detailedroute__", "global_route__fastroute__", "dpl__hpwl__",
    "negotiation__converge__", "utilization__before__dpl",
    "flow__warnings__count",
)
# Keys that PROVE the file belongs to another tool.
_JSON_FOREIGN = ("klayout__", "magic__", "yosys__", "netgen__", "openlane__",
                 "librelane__")


def parse_metrics_json(path) -> ParseOutcome:
    """Parse an `openroad.metrics.json` written by `openroad -metrics`.

    The file is NOT a single-valued JSON object. Measured on four real runs it
    holds 247 key/value pairs for 89 distinct keys: OpenROAD appends a fresh
    block at each internal checkpoint. `json.load` keeps the last by CPython
    dict semantics -- an accident, not a contract, and a reader that kept the
    first would report 5 antenna net violations on a design that ends with 0.
    So it is read as PAIRS, the last is taken explicitly, and every record says
    how many times its key appeared.
    """
    o = ParseOutcome()
    p = Path(path)
    if not p.exists():
        o.refuse("ARTEFACT_ABSENT", f"{p}: no such file")
        return o
    try:
        raw = p.read_bytes()
    except OSError as exc:
        o.refuse("ARTEFACT_UNREADABLE", f"{p}: {exc}")
        return o
    if not raw.strip():
        o.refuse("ARTEFACT_EMPTY",
                 f"{p}: {len(raw)} bytes -- an empty metrics file is NOT a run "
                 f"with no metrics")
        return o
    try:
        pairs = json.loads(raw.decode("utf-8", "replace"),
                           object_pairs_hook=lambda kv: kv)
    except (ValueError, UnicodeError) as exc:
        o.refuse("METRICS_JSON_UNPARSEABLE", f"{p}: {exc}")
        return o
    if not isinstance(pairs, list):
        o.refuse("METRICS_JSON_NOT_AN_OBJECT",
                 f"{p}: top level is {type(pairs).__name__}, expected an object")
        return o

    keys = [k for k, _ in pairs]
    foreign = sorted({k.split("__")[0] + "__" for k in keys
                      if any(k.startswith(f) for f in _JSON_FOREIGN)})
    if foreign:
        o.refuse("METRICS_JSON_FOREIGN_TOOL",
                 f"{p}: carries {foreign} keys -- this is another tool's metrics "
                 f"document, not OpenROAD's", marker="[REFUSE]")
        return o
    if not any(k.startswith(_JSON_SIGNATURE) or k in _JSON_SIGNATURE for k in keys):
        o.refuse("METRICS_JSON_UNRECOGNISED_SHAPE",
                 f"{p}: {len(set(keys))} distinct keys, none of them an OpenROAD "
                 f"signature key ({', '.join(_JSON_SIGNATURE)}); refusing to "
                 f"guess which of them is a metric", marker="[REFUSE]")
        return o

    source = {
        "path": str(p),
        "sha256": _file_sha256(p),
        "tool": TOOL,
        "tool_commit": None,
        "parser": PARSER,
        "parser_sha256": _parser_sha256(),
        "kind": "metrics_json",          # see the note in `parse_log`
    }
    o.sources.append({"path": str(p), "sha256": source["sha256"],
                      "kind": "metrics_json"})
    o.note("METRICS_JSON_SHAPE", pairs=len(pairs), distinct_keys=len(set(keys)),
           duplicated_keys=len(keys) - len(set(keys)))

    trail: Dict[str, List[Any]] = {}
    for k, v in pairs:
        trail.setdefault(k, []).append(v)

    unmapped = sorted(k for k in trail if k not in _JSON_MAP)
    for key, (metric, unit, stage) in _JSON_MAP.items():
        vals = trail.get(key)
        src = dict(source)
        src["key"] = key
        if vals is None:
            src["occurrences"] = 0
            src["selection"] = "last"
            o.records.append(_record(
                metric, "NOT_MEASURED", unit, _scope(stage), src,
                reason=(f"KEY_ABSENT: this metrics document does not carry "
                        f"`{key}`; the build that wrote it did not emit that "
                        f"figure")))
            continue
        src["occurrences"] = len(vals)
        src["selection"] = "last"
        value = vals[-1]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            o.records.append(_record(
                metric, "INVALID", unit, _scope(stage), src,
                reason=(f"NON_NUMERIC: `{key}` last value is "
                        f"{type(value).__name__} {value!r}")))
            continue
        if isinstance(value, float) and not math.isfinite(value):
            o.records.append(_record(
                metric, "INVALID", unit, _scope(stage), src,
                reason=f"NON_FINITE: `{key}` last value is {value!r}"))
            continue
        o.records.append(_record(metric, "MEASURED", unit, _scope(stage), src,
                                 value=value))
    o.note("METRICS_JSON_UNMAPPED_KEYS", count=len(unmapped), keys=unmapped)
    return o


def _apply_declared_authority(o: "ParseOutcome") -> None:
    """Collapse the identities a DECLARATION settles, and name what it overrode.

    THIS IS NOT THE PARSER PICKING A WINNER. `_ppa/contract.py` names three
    metrics, the artefact order for each, and the measurement that decided it;
    this function reads that table and does what it says. A metric absent from
    it is untouched and the index goes on refusing the conflict, which is why
    the table is opt-in BY NAME rather than by prefix.

    NOTHING IS DELETED. The losing reading -- its value, its artefact, its
    hash -- is written into the winner's `source.overridden_by_authority`, so
    "these two artefacts disagreed and here is which one this project believes
    and why" survives in the document. A resolution that made the loser vanish
    would destroy the evidence that there was ever a question, and that is the
    whole objection to a parser settling anything.
    """
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for rec in o.records:
        # EVERY status, not only MEASURED. "the log could not read this figure
        # and the JSON reports 1" is the same disagreement wearing a different
        # spelling, and the index refuses it identically (different `status` is
        # a conflict). `resolve_metric_conflict` is what refuses to let a
        # reading with no number WIN.
        if rec.get("metric") not in _contract.METRIC_ARTEFACT_AUTHORITY:
            continue
        groups.setdefault(
            (str(rec.get("metric")), _cj.digest_of(rec.get("scope") or {})),
            []).append(rec)

    def _is(rec: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
        """Whether `rec` is the original of the COPY `other`.

        `resolve_metric_conflict` returns copies -- deliberately, so a caller
        cannot mutate the declaration's answer -- which means `rec is other` is
        always False here and would be a dead condition rather than a test.
        The reading itself is the identity: which artefact, which status, which
        number.
        """
        return ((rec.get("source") or {}).get("path")
                == (other.get("source") or {}).get("path")
                and rec.get("status") == other.get("status")
                and ("value" in rec) == ("value" in other)
                and rec.get("value") == other.get("value"))

    drop: List[int] = []
    for (metric, _), recs in sorted(groups.items()):
        winner, overridden = _contract.resolve_metric_conflict(recs)
        if winner is None:
            continue
        keep = next((rec for rec in recs if _is(rec, winner)), None)
        if keep is None:                                     # pragma: no cover
            # The declaration returned a reading this group does not contain.
            # That cannot happen -- it ranks what it was handed -- and if it
            # ever does, dropping records on the strength of it would be worse
            # than leaving the conflict for the index to refuse.
            continue
        for rec in recs:
            if rec is not keep:
                drop.append(id(rec))
        keep["source"]["overridden_by_authority"] = [
            {"path": lost["source"].get("path"),
             "sha256": lost["source"].get("sha256"),
             "kind": lost["source"].get("kind"),
             "status": lost.get("status"),
             # ABSENT, not null, when the overridden reading carried no number
             # -- the same no-sentinel rule the records themselves obey.
             **({"value": lost["value"]} if "value" in lost else
                {"reason": lost.get("reason")})}
            for lost in overridden]
        keep["source"]["authority"] = {
            "declared_in": "_ppa/contract.py:METRIC_ARTEFACT_AUTHORITY",
            "order": list(_contract.METRIC_ARTEFACT_AUTHORITY[metric]),
            "reason": _contract.METRIC_AUTHORITY_REASON[metric],
        }
        o.note("METRIC_AUTHORITY_RESOLVED", metric=metric,
               winner=winner["source"].get("kind"),
               winning_value=winner.get("value"),
               overridden=[{"kind": lost["source"].get("kind"),
                            "status": lost.get("status"),
                            "value": lost.get("value")}
                           for lost in overridden],
               declared_in="_ppa/contract.py:METRIC_ARTEFACT_AUTHORITY")
    if drop:
        dropped = set(drop)
        o.records[:] = [r for r in o.records if id(r) not in dropped]


def parse_run(pnr_dir, *, log_name: str = "openroad.log",
              metrics_name: str = "openroad.metrics.json",
              apply_authority: bool = True) -> ParseOutcome:
    """Parse a PnR output directory: the log, and the metrics JSON if present.

    A missing metrics JSON is a diagnostic, not a refusal: most builds do not
    write one.

    THE TWO SOURCES ARE STILL NOT RECONCILED BY THIS PARSER. What changed at
    v1.11.69 is that a DECLARATION now exists (`_ppa/contract.py`,
    `METRIC_ARTEFACT_AUTHORITY`) for three named metrics, and this function
    applies it -- reading a decision, not making one. Everything outside that
    table is emitted twice exactly as before and refused by the index exactly
    as before. Pass `apply_authority=False` to see the unsettled records, which
    is what the regression test for this behaviour does.
    """
    o = ParseOutcome()
    d = Path(pnr_dir)
    if not d.is_dir():
        o.refuse("RUN_DIR_ABSENT", f"{d}: not a directory")
        return o
    log = parse_log(d / log_name)
    o.tool_version = log.tool_version
    o.records.extend(log.records)
    o.refusals.extend(log.refusals)
    o.diagnostics.extend(log.diagnostics)
    o.dialects.update(log.dialects)
    o.sources.extend(log.sources)

    mj = d / metrics_name
    if mj.exists():
        js = parse_metrics_json(mj)
        o.records.extend(js.records)
        o.refusals.extend(js.refusals)
        o.diagnostics.extend(js.diagnostics)
        o.sources.extend(js.sources)
        for rec in js.records:
            rec["source"]["tool_commit"] = o.tool_version
    else:
        o.note("METRICS_JSON_NOT_PRESENT", path=str(mj))
    if apply_authority:
        _apply_declared_authority(o)
    return o


# ── CLI ─────────────────────────────────────────────────────────────────────
def _write_json(path: str, obj: Any) -> None:
    from _atomic_artefact import write_text  # lazy: only the CLI needs it
    write_text(path, _cj.dumps(obj))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """rc: 0 measured something, 2 could not, 3 bad invocation. Never 1.

    A backend has no finding about the design to report, and rc=1 in this
    repository means a hard finding about silicon. Anything this module can go
    wrong about is "I could not look", which is a 2 with a printed marker.
    """
    ap = argparse.ArgumentParser(
        prog="_ppa.backends.openroad",
        description="Parse OpenROAD output into canonical PPA metric records.")
    ap.add_argument("--log", help="path to openroad.log")
    ap.add_argument("--metrics-json", help="path to openroad.metrics.json")
    ap.add_argument("--run-dir", help="a phase3/stage3/pnr directory")
    ap.add_argument("--json", help="write the records document here")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:                       # argparse's own rc=2 is NOT ours
        return RC_BAD_INVOCATION if exc.code else RC_OK

    chosen = [x for x in (args.log, args.metrics_json, args.run_dir) if x]
    if len(chosen) != 1:
        print("[REFUSE] give exactly one of --log / --metrics-json / --run-dir",
              file=sys.stderr)
        return RC_BAD_INVOCATION

    if args.run_dir:
        out = parse_run(args.run_dir)
    elif args.log:
        out = parse_log(args.log)
    else:
        out = parse_metrics_json(args.metrics_json)

    doc = out.document()
    if args.json:
        try:
            _write_json(args.json, doc)
        except OSError as exc:
            print(f"[REFUSE] cannot write {args.json}: {exc}", file=sys.stderr)
            return RC_BAD_INVOCATION

    measured = sum(1 for r in out.records if r["status"] in _STATUS_WITH_VALUE)
    print(f"openroad backend: tool_version={out.tool_version or 'UNKNOWN'} "
          f"records={len(out.records)} measured={measured} "
          f"refusals={len(out.refusals)}")
    for r in out.refusals:
        print(f"{r['marker']} {r['code']}: {r['detail']}", file=sys.stderr)
    if not out.ok:
        # No MEASURED row. Never a 0 and never a 1: nothing was established.
        if not out.refusals:
            print("[CANNOT CHECK] parsed the artefact and established no metric",
                  file=sys.stderr)
        return RC_UNDETERMINED
    return RC_OK


if __name__ == "__main__":                          # pragma: no cover
    sys.exit(main())


# ── the driver seam (`_ppa/backends/__init__.py`) ───────────────────────────
def extract_records(path, **_opts) -> List[Dict[str, Any]]:
    """Canonical records from an OpenROAD artefact, or a run directory of them.

    A DIRECTORY is a PnR output directory and is read with `parse_run`, which
    opens the log and, if present, the metrics JSON -- and emits BOTH readings
    when they disagree (module docstring, "WHAT THIS MODULE DELIBERATELY DOES
    NOT DO"). A FILE is read as the metrics JSON when its name ends
    `.metrics.json` and as a log otherwise.

    Refusals stay refusals: this returns whatever `ParseOutcome` produced,
    including the NOT_MEASURED and INVALID rows, and it never converts an
    unreadable artefact into an empty list.
    """
    p = Path(path)
    if p.is_dir():
        return list(parse_run(p).records)
    if p.name.endswith(".metrics.json"):
        return list(parse_metrics_json(p).records)
    return list(parse_log(p).records)
