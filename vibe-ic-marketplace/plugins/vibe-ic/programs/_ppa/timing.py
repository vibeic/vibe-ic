#!/usr/bin/env python3
"""Per-VIEW timing rows out of STA artefacts. The domain half of the split.

WHY PER VIEW, AND NOT PER DESIGN
================================
A design does not have "a" WNS. It has a timing MATRIX — mode x corner x check
— and the worst number in that matrix is a different fact from each cell of it.
Collapsing the matrix to a single WNS is how a multi-corner claim quietly
becomes a single-corner claim: nobody decides to drop the slow corner, the
report simply has one row and the row that would have failed is not in it.

So every row this module emits carries the full `scope` from
`docs/PPA_INTERFACES.md` §2 — stage, mode, process, voltage, temperature,
rc_corner, clock, check — because a number without them cannot be compared with
anything, and two numbers whose scope differs are not a winner and a loser but
an UNDETERMINED comparison.

THE PARSING IS NOT HERE
=======================
`_ppa.backends.opensta` turns text into numbers and decides nothing else. This
module decides what those numbers MEAN: which status a row carries, which view
a section belongs to, and when a number must be withheld. That is the split
`docs/PPA_INTERFACES.md` §4 freezes, and it is what lets a second timing engine
be added by writing one backend and changing no rule here.

WHAT THIS MODULE REFUSES TO DO
==============================
* **Return rc=1.** This is an EXTRACTOR. rc=1 is a claim about silicon, and an
  extractor has no claim to make: whether a design's timing is CLOSED is asked
  by `_ppa.feasibility` and by `sta_corner_record_completeness_check.py`.
  Deciding it a second time here is the duplication the backend/domain split
  exists to prevent, and it would put a verdict in a module a future author
  would have to remember to keep in step with the real gate.
* **Turn a missing view into a passing row.** A view that was not analysed is
  `NOT_MEASURED` with a reason and no `value` key at all. It is never `0`,
  never `-1`, never omitted (§2: "A report prints the literal NOT_MEASURED
  row; it does not omit it").
* **Read the no-paths sentinel as met timing.** See `_withhold_reason`.
* **Guess a scope field.** An unknown stage, mode, voltage or temperature is
  `null` with the reason recorded in `scope_gaps`. A fabricated scope is worse
  than an absent one: it makes two incomparable numbers look comparable, which
  is the exact failure `scope` was introduced to stop.
* **Derive a number and call it measured.** OpenSTA's `wns` is
  `min(0, worst_slack)`. If the report printed no `wns` line, the wns row is
  NOT_MEASURED — it is not computed from the worst slack. §3: hash the value
  you PARSED.

EXIT CODES (`docs/PPA_INTERFACES.md` §1)
  0  at least one MEASURED row was extracted
  2  UNDETERMINED — no STA artefact, or none of them yielded a measurement.
     Printed with a `[CANNOT CHECK]` marker so a 2 can never read as a silent
     skip, and never mapped to PASS by anything downstream.
  3  BAD INVOCATION — the project path does not exist. Never a design FAIL.
  1  never returned; see above.

chip/PDK/vendor-AGNOSTIC: no design, IC, PDK, vendor or corner-name literal
drives any row. Corner identity, roles and PVT all come from the run's own
artefacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _ppa import canonical_json as cj                       # noqa: E402
from _ppa.backends import opensta                           # noqa: E402

try:                                                        # noqa: E402
    import _sta_basis                                       # the ONE stamp reader
except Exception:                                           # pragma: no cover
    _sta_basis = None
try:                                                        # noqa: E402
    from _atomic_artefact import write_text as _atomic_write_text
except Exception:                                           # pragma: no cover
    _atomic_write_text = None

__all__ = [
    "SCHEMA", "RC_OK", "RC_UNDETERMINED", "RC_BAD_INVOCATION",
    "MEASURED", "NOT_MEASURED", "INVALID",
    "Row", "timing_rows", "rows_from_report", "row_digest", "main",
]

SCHEMA = "vibeic.ppa.metric.v1"
UNIT_NS = "ns"

#: The metrics a reported view is expected to carry. Every one of them gets a
#: row for every view, MEASURED or NOT_MEASURED — never an ABSENT row.
#:
#: An omitted row and a met row are not the same fact, but they LOOK the same to
#: anything that scans a table for violations and finds none. `report_wns` being
#: absent from a report means OpenSTA was never asked for it, which is exactly
#: the "unqueried is indistinguishable from met" disease this lane exists to
#: cure — so it is stated, in the table, as a row.
_VIEW_METRIC_KINDS = ("worst_slack", "wns", "tns")

RC_OK, RC_UNDETERMINED, RC_BAD_INVOCATION = 0, 2, 3

MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"
INVALID = "INVALID"

#: `STA_BASIS:` stamp -> measurement STAGE. The stamp is prefix-matched to a
#: coarse basis by `_sta_basis.normalise_basis`, which deliberately maps
#: POST_ROUTE_SPEF and POST_ROUTE_NO_SPEF to one value; those are two different
#: stages for a metric (one has extracted parasitics behind it and one does
#: not), so the fine mapping is made here on the RAW stamp.
_STAGE_BY_STAMP = {
    "POST_ROUTE_SPEF": "post_route_extracted",
    "POST_ROUTE_NO_SPEF": "post_route_no_extraction",
    "PRE_LAYOUT_ESTIMATE": "pre_layout_estimate",
}

#: Where this flow writes sign-off STA. Directories, not files: every
#: `sta*.rpt` under them is read, so a new corner report is picked up without a
#: change here. Ordered, and every hit is globbed and SORTED, so two runs over
#: one tree produce rows in the same order and therefore the same digests.
_STA_DIRS = (
    "phase3/stage3/sta",
    "reports/phase3/sta",
    "reports/phase3",
)
_STA_GLOB = "sta*.rpt"

#: Role-bearing corner declarations. ONLY these are read.
#:
#: `corners_available` / `corners_extracted` / the `pvt_matrix` corner list are
#: AVAILABILITY, not configuration — `nom` is extracted on every run and
#: deliberately never analysed, because setup signs off at the slow corner and
#: hold at the fast one. Treating availability as configuration would emit a
#: NOT_MEASURED row for a corner nobody ever intended to analyse, on every
#: healthy run. That distinction is `sta_corner_record_completeness_check.py`'s
#: measured lesson and it is honoured, not re-derived.
_PROCESS_STANCE = (
    "reports/phase3/mcorner_ocv_stance.json",
    "reports/phase3/sta/mcorner_ocv_stance.json",
)
_RC_STANCE = (
    "reports/phase3/multi_corner_spef_stance.json",
    "reports/phase3/sta/multi_corner_spef_stance.json",
)
_PVT_MATRIX = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "constraints/pvt_matrix.json",
    "phase3/stage3/constraints/pvt_matrix.json",
)

_SCOPE_KEYS = ("stage", "mode", "process", "voltage_v", "temperature_c",
               "rc_corner", "clock", "check")

Row = Dict[str, Any]

_PARSER_DIGEST_CACHE: Dict[str, Optional[str]] = {}


def _parser_identity() -> Tuple[str, Optional[str]]:
    """The parser that produced a row, and the hash of its bytes.

    The backend, not this module: `source.parser` answers "what turned the text
    into this number", and if the answer changes the number can change with it.
    """
    p = Path(opensta.__file__).resolve()
    name = "_ppa/backends/" + p.name
    if name not in _PARSER_DIGEST_CACHE:
        try:
            _PARSER_DIGEST_CACHE[name] = (
                "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest())
        except OSError:                                      # pragma: no cover
            _PARSER_DIGEST_CACHE[name] = None
    return name, _PARSER_DIGEST_CACHE[name]


def _first_existing(project: Path, rels: Sequence[str]) -> Optional[Path]:
    for rel in rels:
        p = project / rel
        if p.is_file():
            return p
    return None


def _load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """A JSON object, or None. An unreadable file and an absent one are both
    None here, but the CALLER never turns either into a clean row — the only
    thing a missing declaration can do is remove a NOT_MEASURED row it would
    otherwise have demanded, never add a passing one."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _rel(project: Path, p: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:                                       # pragma: no cover
        return str(p)


def discover_reports(project: Path) -> List[Path]:
    """Every sign-off STA report under this project, de-duplicated and sorted.

    Sorted because row order feeds document identity: an unsorted glob makes the
    same tree hash two ways on two filesystems.
    """
    seen: Dict[str, Path] = {}
    for rel in _STA_DIRS:
        d = project / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob(_STA_GLOB)):
            if f.is_file():
                seen.setdefault(str(f.resolve()), f)
    return [seen[k] for k in sorted(seen)]


def _stage_for(report: opensta.Report) -> Tuple[Optional[str], Optional[str]]:
    """(stage, gap-reason). Unknown is null and says why — never a guess.

    MEASURED on this checkout (`grep -n 'puts .*STA_BASIS'
    phase3_one_shot_runner.py`): the SINGLE-corner emitter stamps
    `STA_BASIS: POST_ROUTE_SPEF`, and the two MULTI-corner sign-off emitters —
    the ones that write `sta_spef_multicorner.rpt` and `sta_mcorner_ocv.rpt` —
    stamp nothing at all. Inferring `post_route_extracted` from the filename
    would let a pre-layout estimate be compared against sign-off evidence the
    moment somebody adds a pre-layout report to the same directory, so the
    unstamped case degrades LOUDLY instead.
    """
    stamp = report.basis_stamp
    if not stamp:
        return None, "report carries no STA_BASIS stamp"
    fine = _STAGE_BY_STAMP.get(stamp.upper())
    if fine:
        return fine, None
    coarse = (_sta_basis.normalise_basis(stamp)
              if _sta_basis is not None else None)
    if coarse == "PRE_LAYOUT":
        return "pre_layout_estimate", None
    if coarse == "POST_ROUTE":
        # Post-route, but the stamp does not say whether parasitics were
        # extracted. Say exactly that rather than picking the flattering one.
        return "post_route_unspecified_extraction", None
    return None, "unrecognised STA_BASIS stamp %r" % stamp


def _mode_for(project: Path) -> Tuple[Optional[str], Optional[str]]:
    """The run's timing MODE, from `pvt_matrix.json`'s own `modes` list.

    Exactly one declared mode is attributable to a report that never names one.
    Two or more is not: the reports carry no mode marker, so choosing between
    them would be invention. Zero declared modes is likewise null.
    """
    pvt = _load_json(_first_existing(project, _PVT_MATRIX))
    if not pvt:
        return None, "no pvt_matrix.json declaring a mode"
    modes = pvt.get("modes")
    if not isinstance(modes, list) or not modes:
        return None, "pvt_matrix.json declares no modes"
    modes = [str(m) for m in modes]
    if len(set(modes)) != 1:
        return None, ("pvt_matrix.json declares %d modes (%s) and the STA "
                      "reports name none" % (len(set(modes)), ",".join(sorted(set(modes)))))
    return modes[0], None


def _ident(value: Optional[str]) -> Optional[str]:
    """A corner identifier, case-normalised. See `_scope`."""
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _scope(stage: Optional[str], mode: Optional[str], process: Optional[str],
           voltage_v: Optional[float], temperature_c: Optional[float],
           rc_corner: Optional[str], clock: Optional[str],
           check: Optional[str]) -> Dict[str, Any]:
    """The eight scope keys, always all eight, in the frozen order.

    Always all eight because an omitted key and a null key are different claims
    to a reader, and only one of them is true.

    `process` and `rc_corner` are case-normalised. They are IDENTIFIERS, and a
    view the process stance spells `SS` while its liberty stem spells `ss` is
    one view: leaving both spellings in would make §2's rule ("two numbers are
    comparable only if their `scope` matches") report two identical corners as
    incomparable. The verbatim spelling survives in `source.raw`.
    """
    return {"stage": stage, "mode": mode, "process": _ident(process),
            "voltage_v": voltage_v, "temperature_c": temperature_c,
            "rc_corner": _ident(rc_corner), "clock": clock, "check": check}


def _source(project: Path, path: Optional[Path], sha: Optional[str],
            line: Optional[int], raw: Optional[str]) -> Dict[str, Any]:
    parser, parser_sha = _parser_identity()
    return {
        "path": _rel(project, path) if path is not None else None,
        "sha256": sha,
        "tool": opensta.TOOL,
        # The report does not record which build produced it, and this program
        # will not ask a container at parse time to find out — a metric's
        # provenance must be reproducible from the artefact alone.
        "tool_commit": None,
        "parser": parser,
        "parser_sha256": parser_sha,
        "line": line,
        "raw": raw,
    }


def _row(metric: str, status: str, scope: Dict[str, Any],
         source: Dict[str, Any], *, value: Optional[float] = None,
         reason: Optional[str] = None,
         scope_gaps: Optional[Dict[str, str]] = None) -> Row:
    """One canonical metric record.

    A non-MEASURED row carries NO `value` key. Not `null`, not `0`: absent, so
    that a consumer which reads `row["value"]` raises instead of quietly
    comparing a sentinel (§2, "No numeric sentinels").
    """
    row: Row = {"schema": SCHEMA, "metric": metric, "status": status}
    if status == MEASURED:
        if value is None:                                    # pragma: no cover
            raise ValueError("a MEASURED row must carry a value")
        row["value"] = value
        row["unit"] = UNIT_NS
    else:
        row["reason"] = reason or "unspecified"
        row["unit"] = UNIT_NS
    row["scope"] = scope
    if scope_gaps:
        row["scope_gaps"] = dict(sorted(scope_gaps.items()))
    row["source"] = source
    return row


def row_digest(row: Row) -> str:
    """`sha256:<hex>` of a row, via the one serializer (§3)."""
    return cj.digest_of(row)


#: What a `worst_slack` line that IS the infinity sentinel carries.
_SENTINEL_REASON = "no_paths_analysed: OpenSTA reported the infinity sentinel"


def _withhold_reason(check_no_paths: bool, kind: str,
                     value: Optional[float]) -> Optional[str]:
    """Why a parsed number must NOT be published as a measurement.

    THE FOUNDING DEFECT OF THIS CORPUS, and the reason this function exists.
    `worst_slack` starts at infinity and takes the min over the analysed paths,
    so it is still infinity exactly when the path set was EMPTY. Three published
    reports in the tracked corpus had a whole body of::

        No paths found. / tns max 0.00 / wns max 0.00 / worst slack max INF

    The `0.00` there is `min(0, INF)` — arithmetic ABOUT infinity, carrying no
    independent evidence. It reads 0.00 *because nothing was analysed*, not
    because timing was met. Publishing it as a met +0.000 ns is precisely
    "an unreported view is indistinguishable from a met one", reproduced inside
    the reader that is supposed to prevent it.

    MEASURED against the real tool (OpenSTA 2.7.0 f21d4a3878, from the image
    family this checkout anchors), two designs, one liberty, one clock:

        design with real reg-to-reg paths     design with no timing paths
          tns max 0.00                          tns max 0.00
          wns max 0.00                          wns max 0.00
          worst slack max 0.19                  worst slack max INF

    The first two lines are BYTE-IDENTICAL. Timing met with +0.19 ns of slack,
    and nothing analysed at all, print the same summary -- both clamp to zero.
    The `worst slack` line is the ONLY thing that separates them, which is why
    the withholding decision is keyed on it and on nothing else.

    PER CHECK, never per report. A report routinely carries a real setup slack
    beside a hold analysis that found no paths, and withholding the setup
    summary because the HOLD view was empty would suppress a measurement that
    exists. Not hypothetical: that was this function's first shape, and the
    real-tool output above is what exposed it.

    A NEGATIVE summary is never withheld. It cannot be an echo of infinity, and
    suppressing evidence of a violation is the one error worse than publishing
    a phantom pass.
    """
    if not check_no_paths:
        return None
    if value is not None and value < 0:
        return None
    return ("no_paths_analysed_in_view: this view's worst slack was the "
            "infinity sentinel, so a non-negative %s is arithmetic from "
            "infinity and not evidence of met timing" % kind)


def rows_from_report(project: Path, path: Path, report: opensta.Report,
                     *, mode: Optional[str],
                     mode_gap: Optional[str]) -> List[Row]:
    """Every row a single parsed report supports."""
    rows: List[Row] = []
    stage, stage_gap = _stage_for(report)
    parser_src_sha = report.sha256

    if report.empty:
        rows.append(_row(
            "timing.report", INVALID,
            _scope(stage, mode, None, None, None, None, None, None),
            _source(project, path, parser_src_sha, None, None),
            reason="the STA artefact exists but is empty",
            scope_gaps={k: v for k, v in
                        (("stage", stage_gap), ("mode", mode_gap)) if v}))
        return rows

    for sec in report.sections:
        # ── the view's identity ────────────────────────────────────────────
        liberty = sec.liberty
        rc_corner = sec.rc_corner
        process = sec.process
        if sec.banner is None:
            # Dialect C: one implicit section, and the whole-file stamps are
            # what describe it. Relating them is meaning, so the BACKEND left
            # it alone and it happens here.
            liberty = liberty or report.basis_liberty
            process = process or report.signoff_corner
        pvt = opensta.parse_liberty_pvt(liberty)
        gaps: Dict[str, str] = {}
        if stage_gap:
            gaps["stage"] = stage_gap
        if mode_gap:
            gaps["mode"] = mode_gap
        for fld in ("voltage_v", "temperature_c"):
            if pvt.gaps.get(fld):
                gaps[fld] = "liberty %s: %s" % (
                    pvt.stem or "path absent", pvt.gaps[fld])
        # The banner's declared process label wins over the one implied by the
        # liberty stem: the label is what the run SAID it was analysing, and a
        # disagreement between them is information, not noise.
        if process is None and pvt.process is not None:
            process = pvt.process
        elif (process is not None and pvt.process is not None
                and process.lower() != pvt.process.lower()):
            gaps["process"] = (
                "banner declares process=%s but its liberty stem %s reads %s"
                % (process, pvt.stem, pvt.process))
        if rc_corner is None:
            gaps["rc_corner"] = (
                "this report names no RC corner for the section; the RC axis "
                "is reported by the multi-corner SPEF report, not this one")

        # ── which CHECKS analysed nothing? Keyed per check, never per
        # report: an unbannered report carries BOTH checks in one section, and
        # a real setup slack must not be suppressed because hold was empty.
        no_paths_by_check = {
            (m.check or sec.check): True
            for m in sec.measurements if m.kind == "worst_slack" and m.no_paths}

        # Which check(s) this section is about. A banner says so outright; the
        # unbannered dialect is described only by the max/min labels on its own
        # numbers. A section that mentions neither is `unlabelled` — stated,
        # never silently attributed to setup.
        if sec.check is not None:
            checks = [sec.check]
        else:
            checks = sorted({m.check for m in sec.measurements if m.check})
            if not checks:
                checks = ["unlabelled"]

        for check in checks:
            scope = _scope(stage, mode, process, pvt.voltage_v,
                           pvt.temperature_c, rc_corner, None, check)
            for kind in _VIEW_METRIC_KINDS:
                metric = "timing.%s.%s_ns" % (check, kind)
                m = next((x for x in sec.measurements
                          if x.kind == kind
                          and (x.check or sec.check or check) == check), None)
                if m is None:
                    rows.append(_row(
                        metric, NOT_MEASURED, scope,
                        _source(project, path, parser_src_sha, None, None),
                        reason=("not_reported: the artefact carries no %s line "
                                "for this view — the tool was not asked, or the "
                                "query failed" % kind),
                        scope_gaps=gaps))
                    continue
                src = _source(project, path, parser_src_sha, m.line, m.raw)
                if m.no_paths or m.value is None:
                    rows.append(_row(
                        metric, NOT_MEASURED, scope, src,
                        reason=(_SENTINEL_REASON if m.no_paths
                                else "the tool printed no usable number"),
                        scope_gaps=gaps))
                    continue
                why = _withhold_reason(
                    no_paths_by_check.get(check, False), m.kind, m.value)
                if why:
                    rows.append(_row(metric, NOT_MEASURED, scope, src,
                                     reason=why, scope_gaps=gaps))
                else:
                    rows.append(_row(metric, MEASURED, scope, src,
                                     value=m.value, scope_gaps=gaps))

        # ── per-CLOCK rows, from the only per-clock evidence there is ──────
        # `report_worst_slack` is design-wide; these path blocks name a path
        # group. They are a PARTIAL census (the emitter dumps the worst few), so
        # they get their own metric name and can never be mistaken for the
        # design-wide worst.
        for p in sec.paths:
            if p.slack is None or p.clock is None:
                continue
            check = ({"max": "setup", "min": "hold"}.get(p.path_type or "")
                     or sec.check or "unlabelled")
            rows.append(_row(
                "timing.%s.worst_path_slack_ns" % check, MEASURED,
                _scope(stage, mode, process, pvt.voltage_v, pvt.temperature_c,
                       rc_corner, p.clock, check),
                _source(project, path, parser_src_sha, p.line, p.raw),
                value=p.slack, scope_gaps=gaps))
    return rows


def _declared_views(project: Path) -> List[Dict[str, Optional[str]]]:
    """(axis, corner, check) triples the run was CONFIGURED to analyse.

    Role-bearing declarations only — see `_PROCESS_STANCE` / `_RC_STANCE`. An
    availability list is not a configuration and is never read here.
    """
    out: List[Dict[str, Optional[str]]] = []
    proc = _load_json(_first_existing(project, _PROCESS_STANCE))
    if proc:
        for key, check in (("setup_process_corner", "setup"),
                           ("hold_process_corner", "hold")):
            val = proc.get(key)
            if isinstance(val, str) and val.strip():
                out.append({"axis": "process", "corner": val.strip(),
                            "check": check})
    rc = _load_json(_first_existing(project, _RC_STANCE))
    if rc:
        for key, check in (("setup_corner", "setup"), ("hold_corner", "hold")):
            val = rc.get(key)
            if isinstance(val, str) and val.strip():
                out.append({"axis": "rc", "corner": val.strip(),
                            "check": check})
    return out


def _covers(row: Row, decl: Dict[str, Optional[str]]) -> bool:
    """Does this row already account for a declared view?

    ANY status counts, not just MEASURED. A hold corner that WAS analysed and
    found no paths already has a row saying exactly that; adding a second row
    claiming it was "declared but not reported" would be false — it was
    reported, and the accurate reason is the one already on the table. This
    rule fires only for a view with NO row at all.

    Only rows that came from an artefact can cover a declaration
    (`source.path`), so one synthesised row can never satisfy another.
    """
    if not (row.get("source") or {}).get("path"):
        return False
    scope = row.get("scope") or {}
    if (scope.get("check") or "") != decl["check"]:
        return False
    field = "process" if decl["axis"] == "process" else "rc_corner"
    got = scope.get(field)
    return bool(got) and str(got).lower() == str(decl["corner"]).lower()


def timing_rows(project: Path) -> Tuple[List[Row], List[str]]:
    """Every per-view timing row this project's STA artefacts support.

    Returns `(rows, notes)`. `notes` carries what a human needs to read the
    result — which files were opened, and what was declared but never reported.
    """
    notes: List[str] = []
    reports = discover_reports(project)
    mode, mode_gap = _mode_for(project)
    rows: List[Row] = []
    for f in reports:
        try:
            text = f.read_text(errors="replace")
        except OSError as exc:
            # Unreadable is NOT clean. It gets a row that says so.
            rows.append(_row(
                "timing.report", INVALID,
                _scope(None, mode, None, None, None, None, None, None),
                _source(project, f, opensta.file_digest(f), None, None),
                reason="the STA artefact could not be read: %s" % exc))
            notes.append("[CANNOT CHECK] unreadable: %s" % _rel(project, f))
            continue
        rep = opensta.parse_report(text, path=_rel(project, f),
                                   sha256=opensta.file_digest(f))
        rows.extend(rows_from_report(project, f, rep, mode=mode,
                                     mode_gap=mode_gap))
    notes.append("opened %d STA artefact(s): %s" % (
        len(reports), ", ".join(_rel(project, f) for f in reports) or "none"))

    # Declared-but-never-reported views become explicit NOT_MEASURED rows. A
    # view the run was configured to analyse and did not is the defect this
    # whole lane exists to make visible; leaving it out of the table would be
    # the same silence in a new place.
    reported = list(rows)          # snapshot: declared rows cannot cover each other
    for decl in _declared_views(project):
        if any(_covers(r, decl) for r in reported):
            continue
        field = "process" if decl["axis"] == "process" else "rc_corner"
        rows.append(_row(
            "timing.%s.worst_slack_ns" % decl["check"], NOT_MEASURED,
            _scope(None, mode, decl["corner"] if field == "process" else None,
                   None, None,
                   decl["corner"] if field == "rc_corner" else None,
                   None, decl["check"]),
            _source(project, None, None, None, None),
            reason=("declared_but_not_reported: the run declared %s corner %r "
                    "for the %s check on the %s axis and no STA artefact "
                    "reports a slack for it"
                    % (decl["axis"], decl["corner"], decl["check"],
                       decl["axis"]))))
        notes.append("declared but not reported: %s corner %s (%s)"
                     % (decl["axis"], decl["corner"], decl["check"]))
    return rows, notes


def _document(project: Path, rows: List[Row], notes: List[str]) -> Dict[str, Any]:
    measured = [r for r in rows if r.get("status") == MEASURED]
    return {
        "schema": "vibeic.ppa.timing_rows.v1",
        "program": "_ppa.timing",
        "project": str(project),
        "row_count": len(rows),
        "measured_count": len(measured),
        "not_measured_count": len([r for r in rows
                                   if r.get("status") == NOT_MEASURED]),
        "invalid_count": len([r for r in rows if r.get("status") == INVALID]),
        "notes": notes,
        "rows": rows,
        "row_digests": [row_digest(r) for r in rows],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="_ppa.timing",
        description="Per-view timing rows from a project's STA artefacts. "
                    "An extractor: it never returns 1, because it makes no "
                    "claim about the design.")
    ap.add_argument("project", nargs="?", default=".",
                    help="project root to read STA artefacts from")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="write the row document here (atomically)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = Path(args.project)
    if not project.is_dir():
        print("[REFUSE] _ppa.timing: %r is not a directory. Nothing was read, "
              "so nothing is claimed." % str(project), file=sys.stderr)
        return RC_BAD_INVOCATION

    rows, notes = timing_rows(project)
    doc = _document(project, rows, notes)

    if args.json_path:
        # NOT sort_keys. §5 requires `schema` to be the document's FIRST key,
        # and sorting would bury it under `invalid_count`. This is the HUMAN
        # document; every identity in it (`row_digests`) went through
        # `canonical_json`, which sorts — the two orders answer two different
        # questions and only one of them is a hash.
        payload = json.dumps(doc, indent=2, ensure_ascii=False)
        if _atomic_write_text is not None:
            _atomic_write_text(args.json_path, payload + "\n")
        else:                                                # pragma: no cover
            Path(args.json_path).write_text(payload + "\n", encoding="utf-8")

    for n in notes:
        print(n)
    for r in rows:
        s = r["scope"]
        val = ("%.6g" % r["value"]) if r.get("status") == MEASURED \
            else r.get("status")
        print("%-34s %-8s stage=%s mode=%s process=%s V=%s T=%s rc=%s clock=%s "
              "check=%s  %s" % (
                  r["metric"], r["status"], s["stage"], s["mode"],
                  s["process"], s["voltage_v"], s["temperature_c"],
                  s["rc_corner"], s["clock"], s["check"], val))

    if doc["measured_count"] == 0:
        print("[CANNOT CHECK] _ppa.timing: %d STA artefact(s) opened and NOT "
              "ONE measured timing row came out of them. This is UNDETERMINED, "
              "not clean: a run that measured nothing and a run that measured "
              "zero violations are different facts."
              % len(discover_reports(project)), file=sys.stderr)
        return RC_UNDETERMINED
    return RC_OK


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
