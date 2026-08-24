#!/usr/bin/env python3
"""OpenSTA report text -> structured observations. Parsing ONLY.

WHAT THIS MODULE IS ALLOWED TO DECIDE, AND WHAT IT IS NOT
=========================================================
It decides what the tool WROTE: which sections a report has, which corner and
liberty each section names, which numbers appear on which lines, and whether a
number was OpenSTA's no-paths sentinel rather than a measurement. All of that
is grammar — facts about the document.

It decides nothing about the DESIGN. No threshold, no verdict, no
"this view is missing", no mapping to MEASURED/NOT_MEASURED. Those are policy
and they live in `_ppa.timing`, which is what lets a second timing engine be
added here without touching a rule (`docs/PPA_INTERFACES.md` §4).

THE THREE DIALECTS THIS FLOW ACTUALLY EMITS
===========================================
Read out of `phase3_one_shot_runner.py`, not assumed — there are no STA report
fixtures in this repository to read instead (the corpus left in v1.10.56).

A. multi-corner SPEF (`sta_spef_multicorner.rpt`)::

     # Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
     # SETUP corner: max-RC   HOLD corner: min-RC
     # corners_available: max,min,nom
     # corner_liberty: max=/pdk/…__ss_100C_1v60.lib
     # distinct_corner_libraries: 2 across 2 reported corner(s)
     === SETUP (max-RC corner, SPEF=max, liberty=/pdk/…) ===
     worst slack max -1.71
     tns max -12.34

B. multi-corner process OCV (`sta_mcorner_ocv.rpt`)::

     === SETUP corner: process=SS liberty=/pdk/…__ss_100C_1v60.lib, SPEF=x.max.spef ===
     OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
     worst slack max -0.93

C. single-corner post-route SPEF (`sta_spef_based.rpt`) — no `===` banner at
   all, and the only dialect that stamps its own basis::

     tns max 0.00
     wns max 0.00
     worst slack max 5.24
     STA_BASIS: POST_ROUTE_SPEF
     STA_SIGNOFF_CORNER: SS
     STA_BASIS_LIBERTY: /pdk/…__ss_100C_1v60.lib
     STA_BASIS_SPEF: x.spef
     STA_BASIS_CORNER: nom

TWO NUMBER-GRAMMAR TRAPS, BOTH ALREADY PAID FOR IN THIS REPOSITORY
==================================================================
1. `worst slack max INF` (printed by some builds as `1e+30`) is OpenSTA's
   NO-PATHS-ANALYSED sentinel: `worst_slack` starts at infinity and takes the
   min over the analysed paths, so it is still infinity exactly when the path
   set was EMPTY. It is not a number. `Measurement.no_paths` records that, and
   `value` is None — the caller cannot accidentally read infinity as slack.
2. A number regex of the shape `-?\\d+(\\.\\d+)?` scrapes a bogus `1` out of
   `1e+30`, and a bogus `1.5` out of any genuine `1.5e-3`. So the token grammar
   here accepts a FULL float including an exponent, and the sentinel test is
   made on the parsed VALUE (|v| >= 1e29) rather than on a spelling. That is
   strictly wider than matching the two spellings the current builds happen to
   print.

`max` is setup (late) and `min` is hold (early), per OpenSTA convention.
chip/PDK/vendor-AGNOSTIC: no design, IC, PDK or corner-name literal appears
below; corner identity is whatever the report itself names.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = [
    "TOOL", "Measurement", "Section", "Header", "Report", "LibertyPVT",
    "parse_report", "parse_liberty_pvt", "file_digest", "SENTINEL_MAGNITUDE",
]

TOOL = "opensta"

#: Above this magnitude a slack is OpenSTA's infinity sentinel, not a slack.
#: Chosen a decade below 1e30 so a build that prints `1.0e+30` or `inf` is
#: caught by the same test, and no plausible real slack (nanoseconds) is.
SENTINEL_MAGNITUDE = 1e29

# ── number grammar ─────────────────────────────────────────────────────────
#: A full float token, exponent included, plus the infinity spellings. Matching
#: the exponent is the point: see trap 2 in the module docstring.
_NUM = r"[-+]?(?:inf(?:inity)?|\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"

_WORST_SLACK_RE = re.compile(
    r"worst\s+slack\s+(max|min)\s+(" + _NUM + r")", re.IGNORECASE)
#: `worst hold slack <v>` / `hold WNS <v>` — the runner relabels
#: `sta::worst_slack -min` into this phrasing so hold-closure consumers can find
#: it (a `report_checks` path line puts the number nowhere near the word hold).
_WORST_HOLD_SLACK_RE = re.compile(
    r"worst\s+hold\s+slack\s+(" + _NUM + r")", re.IGNORECASE)
_HOLD_WNS_RE = re.compile(r"\bhold\s+wns\s+(" + _NUM + r")", re.IGNORECASE)
#: `WNS -0.05` and `WNS = -0.05` are both real dialects; the separator is
#: accepted without being required, which widens neither token nor value.
_WNS_RE = re.compile(
    r"\bwns\s*[:=]?\s*(max|min)?\s*(" + _NUM + r")", re.IGNORECASE)
_TNS_RE = re.compile(
    r"\btns\s*[:=]?\s*(max|min)?\s*(" + _NUM + r")", re.IGNORECASE)

# ── section banners ────────────────────────────────────────────────────────
_BANNER_RE = re.compile(r"^\s*===\s*(SETUP|HOLD)\b.*?===\s*$", re.IGNORECASE)
#: dialect B: `=== SETUP corner: process=SS liberty=…, SPEF=… ===`
_BANNER_PROCESS_RE = re.compile(r"corner:\s*process=([\w.+-]+)", re.IGNORECASE)
#: dialect A: `=== SETUP (max-RC corner, SPEF=max, liberty=…) ===`
_BANNER_RC_RE = re.compile(r"\(\s*([\w.+-]+?)-RC\s+corner", re.IGNORECASE)
_BANNER_SPEF_RE = re.compile(r"SPEF=([^,)]+?)\s*(?:[,)]|===)", re.IGNORECASE)
_BANNER_LIBERTY_RE = re.compile(r"liberty=([^,)\s]+)", re.IGNORECASE)

# ── header lines ───────────────────────────────────────────────────────────
_SIGNOFF_HEADER_RE = re.compile(
    r"#\s*SETUP\s+corner:\s*([\w.+-]+?)(?:-RC)?\s+HOLD\s+corner:\s*"
    r"([\w.+-]+?)(?:-RC)?\s*$", re.IGNORECASE | re.MULTILINE)
_CORNERS_AVAIL_RE = re.compile(r"#\s*corners_available:\s*(.+)", re.IGNORECASE)
_CORNER_LIBERTY_RE = re.compile(
    r"#\s*corner_liberty:\s*([\w.+-]+)\s*=\s*(\S+)", re.IGNORECASE)
_DISTINCT_LIBS_RE = re.compile(
    r"#\s*distinct_corner_libraries:\s*(\d+)\s+across\s+(\d+)", re.IGNORECASE)

# ── whole-file stamps (dialect C) ──────────────────────────────────────────
#: The RAW stamp value. `_sta_basis` is the ONE reader of this stamp's coarse
#: meaning and `_ppa.timing` calls it for that; the raw value is kept here
#: because POST_ROUTE_SPEF and POST_ROUTE_NO_SPEF normalise to one basis and
#: are two different measurement STAGES.
_STA_BASIS_RE = re.compile(
    r"^\s*#?\s*STA_BASIS\s*:\s*([A-Z_]+)", re.MULTILINE)
_SIGNOFF_CORNER_RE = re.compile(
    r"^\s*#?\s*STA_SIGNOFF_CORNER\s*:\s*(\S+)", re.MULTILINE)
_BASIS_LIBERTY_RE = re.compile(
    r"^\s*#?\s*STA_BASIS_LIBERTY\s*:\s*(\S+)", re.MULTILINE)
#: The parasitic file the run READ. Dialect B names it on the section banner
#: (`SPEF=…`) and `Section.spef` already carries it; the unbannered dialect can
#: only state it whole-file, and until now nothing parsed it — so the RC axis of
#: an unbannered report was unreadable even when the artefact spelled it out.
_BASIS_SPEF_RE = re.compile(
    r"^\s*#?\s*STA_BASIS_SPEF\s*:\s*(\S+)", re.MULTILINE)
_BASIS_CORNER_RE = re.compile(
    r"^[ \t]*#?[ \t]*STA_BASIS_CORNER[ \t]*:[ \t]*([^\r\n]*)$",
    re.MULTILINE)
_SIGNOFF_CORNER_COUNT_RE = re.compile(
    r"^\s*#?\s*STA_SIGNOFF_CORNER_COUNT\s*:\s*(\d+)", re.MULTILINE)

# ── the emitter's own attestations that a query RAN ────────────────────────
# Their ABSENCE is what separates "queried and clean" from "never asked", which
# is the same disease as an unreported corner. Parsed as facts; judged nowhere
# in this file.
_WORST_PATHS_OK_RE = re.compile(
    r"SIGNOFF_WORST_PATHS_REPORTED\s+path_delay=(\w+)", re.IGNORECASE)
_WORST_PATHS_FAILED_RE = re.compile(
    r"SIGNOFF_WORST_PATHS_FAILED\s+path_delay=(\w+)\s+reason=(.*)", re.IGNORECASE)
_CHECK_TYPES_OK_RE = re.compile(r"SIGNOFF_CHECK_TYPES_REPORTED\b", re.IGNORECASE)
_CHECK_TYPES_FAILED_RE = re.compile(
    r"SIGNOFF_CHECK_TYPES_FAILED\s+reason=(.*)", re.IGNORECASE)

# ── per-path evidence (the only genuinely per-CLOCK evidence a report has) ──
_PATH_START_RE = re.compile(r"^[ \t]*Startpoint[ \t]*:", re.MULTILINE)
_PATH_GROUP_RE = re.compile(r"^[ \t]*Path Group[ \t]*:[ \t]*(\S+)", re.MULTILINE)
_PATH_TYPE_RE = re.compile(r"^[ \t]*Path Type[ \t]*:[ \t]*(\S+)", re.MULTILINE)
_PATH_SLACK_RE = re.compile(
    r"(" + _NUM + r")\s+slack\s*\((MET|VIOLATED)\)", re.IGNORECASE)
_CLOCKED_BY_RE = re.compile(r"clocked\s+by\s+([^\s)]+)", re.IGNORECASE)
_ENDPOINT_RE = re.compile(r"^[ \t]*Endpoint[ \t]*:[ \t]*(\S+)", re.MULTILINE)
_STARTPOINT_RE = re.compile(r"^[ \t]*Startpoint[ \t]*:[ \t]*(\S+)", re.MULTILINE)

# ── liberty PVT, from the stem the banner names ────────────────────────────
# The PVT of a corner appears NOWHERE in this flow's JSON. The one place it
# exists is the liberty filename, which every corner banner carries in full.
#
# Every token below must be DELIMITED. Undelimited matching is not a style
# preference: in `gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib` the library-family
# fragment `5v0` looks exactly like a supply voltage, and an undelimited search
# returns 5.0 V for a 4.50 V corner.
_LIB_VOLT_V_RE = re.compile(r"(?:^|[_\-.])(\d+)v(\d+)(?:$|[_\-.])", re.IGNORECASE)
_LIB_VOLT_P_RE = re.compile(r"(?:^|[_\-.])(\d+)p(\d+)V(?:$|[_\-.])", re.IGNORECASE)
_LIB_TEMP_RE = re.compile(r"(?:^|[_\-.])([nm]?)(\d+)C(?:$|[_\-.])", re.IGNORECASE)
_LIB_PROCESS_RE = re.compile(
    r"(?:^|[_\-.])(ss|tt|ff|typ|slow|fast|nom)(?:$|[_\-.])", re.IGNORECASE)


def _to_float(tok: str) -> Optional[float]:
    """A matched number token -> float, or None if it is not one."""
    try:
        return float(tok)
    except (TypeError, ValueError):
        return None


def file_digest(path: Path) -> Optional[str]:
    """`sha256:<hex>` of a file's BYTES, or None if it cannot be read.

    Bytes, not `canonical_json`: this is the identity of an artefact on disk,
    which an auditor reproduces with `sha256sum`. `canonical_json.digest_of` is
    for OBJECTS, and using it here would produce an identity nobody outside this
    program could recompute.

    None on an unreadable file rather than a hash of b"": an artefact that could
    not be read and an empty artefact must never produce the same identity.
    """
    try:
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass(frozen=True)
class Measurement:
    """One number the tool printed, with the evidence to find it again."""
    kind: str                    # "worst_slack" | "wns" | "tns"
    check: Optional[str]         # "setup" | "hold" | None (line carried no label)
    value: Optional[float]       # None iff `no_paths`
    raw: str                     # the source line, verbatim
    line: int                    # 1-based, in the report as a whole
    no_paths: bool = False       # the value was OpenSTA's infinity sentinel


@dataclass(frozen=True)
class PathObservation:
    """One `report_checks` path block. The only per-CLOCK evidence a report has.

    `report_worst_slack` prints a number for the whole design; only these blocks
    say which clock (path group) produced a slack. They are a partial census —
    the emitter dumps the worst few — so a consumer must never read them as the
    design-wide worst.
    """
    clock: Optional[str]         # `Path Group:`, else `clocked by <name>`
    path_type: Optional[str]     # `Path Type: max|min`
    slack: Optional[float]
    met: Optional[bool]
    startpoint: Optional[str]
    endpoint: Optional[str]
    raw: str
    line: int


@dataclass(frozen=True)
class Section:
    """A `=== SETUP|HOLD … ===` stanza, or the whole file when it has none."""
    check: Optional[str]
    process: Optional[str]       # dialect B: `process=SS`
    rc_corner: Optional[str]     # dialect A: `(max-RC corner…)`
    spef: Optional[str]
    # Every explicit declaration, in source order. Multiplicity is evidence:
    # reducing this tuple to the first value would hide a conflicting stamp.
    basis_corners: Tuple[str, ...]
    liberty: Optional[str]
    banner: Optional[str]        # None => implicit whole-file section
    line: int
    measurements: Tuple[Measurement, ...] = ()
    paths: Tuple[PathObservation, ...] = ()
    worst_paths_reported: Optional[bool] = None   # None => the report is silent
    worst_paths_failure: Optional[str] = None


@dataclass(frozen=True)
class Header:
    """The `#`-comment preamble of a multi-corner report."""
    setup_corner: Optional[str] = None
    hold_corner: Optional[str] = None
    corners_available: Tuple[str, ...] = ()
    corner_liberty: Dict[str, str] = field(default_factory=dict)
    distinct_library_count: Optional[int] = None
    reported_corner_count: Optional[int] = None


@dataclass(frozen=True)
class Report:
    path: Optional[str]
    sha256: Optional[str]
    header: Header
    sections: Tuple[Section, ...]
    basis_stamp: Optional[str] = None        # RAW, e.g. "POST_ROUTE_SPEF"
    signoff_corner: Optional[str] = None
    basis_liberty: Optional[str] = None
    basis_spef: Optional[str] = None         # the parasitic file, as NAMED
    # Every whole-file declaration, in source order. The timing domain owns
    # validation and reconciliation with per-section/banner declarations.
    basis_corners: Tuple[str, ...] = ()
    signoff_corner_count: Optional[int] = None
    check_types_reported: Optional[bool] = None
    check_types_failure: Optional[str] = None
    empty: bool = False                      # the file had no content at all


@dataclass(frozen=True)
class LibertyPVT:
    """Process / voltage / temperature read out of a liberty FILE NAME."""
    stem: Optional[str] = None
    process: Optional[str] = None
    voltage_v: Optional[float] = None
    temperature_c: Optional[float] = None
    #: Why a field is None, keyed by field name. `ambiguous` means the stem
    #: carried two different delimited candidates and this refused to pick.
    gaps: Dict[str, str] = field(default_factory=dict)


def _one_delimited(matches: List[float]) -> Tuple[Optional[float], Optional[str]]:
    """A single agreed value from delimited matches, or None + why not.

    Refusing on disagreement is the point. A stem with two candidate voltages is
    a stem this cannot read; picking the first (or the last) would put a
    confident wrong number into a metric scope, and a wrong scope is worse than
    an absent one because it makes two incomparable numbers look comparable.
    """
    if not matches:
        return None, "absent"
    uniq = sorted(set(matches))
    if len(uniq) > 1:
        return None, "ambiguous:" + ",".join(repr(u) for u in uniq)
    return uniq[0], None


def parse_liberty_pvt(liberty: Optional[str]) -> LibertyPVT:
    """Read P, V and T out of a liberty path. Never guesses; states its gaps.

    The open PDKs spell the same three facts two ways —
    `…__ss_100C_1v60.lib` and `…_typ_1p20V_25C.lib` — so both orders and both
    voltage spellings are accepted, and `n`/`m` prefix a negative temperature.
    Anything else yields None with the reason recorded in `gaps`, because a
    fabricated corner condition is exactly what `scope` exists to prevent.
    """
    if not liberty:
        return LibertyPVT(gaps={"process": "no_liberty_path",
                                "voltage_v": "no_liberty_path",
                                "temperature_c": "no_liberty_path"})
    stem = Path(str(liberty)).name
    gaps: Dict[str, str] = {}

    volts = [int(a) + int(b) / (10 ** len(b))
             for a, b in _LIB_VOLT_V_RE.findall(stem)]
    volts += [int(a) + int(b) / (10 ** len(b))
              for a, b in _LIB_VOLT_P_RE.findall(stem)]
    voltage, why = _one_delimited(volts)
    if why:
        gaps["voltage_v"] = why

    temps: List[float] = []
    for sign, digits in _LIB_TEMP_RE.findall(stem):
        val = float(int(digits))
        temps.append(-val if sign.lower() in ("n", "m") else val)
    temperature, why = _one_delimited(temps)
    if why:
        gaps["temperature_c"] = why

    procs = sorted({m.lower() for m in _LIB_PROCESS_RE.findall(stem)})
    if not procs:
        process, gaps["process"] = None, "absent"
    elif len(procs) > 1:
        process, gaps["process"] = None, "ambiguous:" + ",".join(procs)
    else:
        process = procs[0]

    return LibertyPVT(stem=stem, process=process, voltage_v=voltage,
                      temperature_c=temperature, gaps=gaps)


def _measure_line(text: str, lineno: int) -> List[Measurement]:
    """Every number a single line carries, as Measurements.

    The sentinel test is made on the parsed VALUE, so `INF`, `inf`, `1e+30` and
    `1.0E30` are one case rather than four spellings to keep matching.
    """
    out: List[Measurement] = []
    raw = text.rstrip("\n")

    def _add(kind: str, check: Optional[str], tok: str) -> None:
        val = _to_float(tok)
        if val is None:
            return
        if val != val or abs(val) >= SENTINEL_MAGNITUDE:   # NaN or infinity
            out.append(Measurement(kind, check, None, raw, lineno, True))
        else:
            out.append(Measurement(kind, check, val, raw, lineno, False))

    for m in _WORST_SLACK_RE.finditer(text):
        _add("worst_slack", "setup" if m.group(1).lower() == "max" else "hold",
             m.group(2))
    for m in _WORST_HOLD_SLACK_RE.finditer(text):
        _add("worst_slack", "hold", m.group(1))
    for m in _HOLD_WNS_RE.finditer(text):
        _add("wns", "hold", m.group(1))
    if not _HOLD_WNS_RE.search(text):
        for m in _WNS_RE.finditer(text):
            lbl = (m.group(1) or "").lower()
            _add("wns", {"max": "setup", "min": "hold"}.get(lbl), m.group(2))
    for m in _TNS_RE.finditer(text):
        lbl = (m.group(1) or "").lower()
        _add("tns", {"max": "setup", "min": "hold"}.get(lbl), m.group(2))
    return out


def _parse_paths(block: str, base_line: int) -> List[PathObservation]:
    """The `report_checks` path blocks inside one section."""
    starts = [m.start() for m in _PATH_START_RE.finditer(block)]
    if not starts:
        return []
    starts.append(len(block))
    out: List[PathObservation] = []
    for i in range(len(starts) - 1):
        chunk = block[starts[i]:starts[i + 1]]
        grp = _PATH_GROUP_RE.search(chunk)
        clk = grp.group(1) if grp else None
        if clk is None:
            cb = _CLOCKED_BY_RE.search(chunk)
            clk = cb.group(1) if cb else None
        ptype = _PATH_TYPE_RE.search(chunk)
        slack_m = None
        for slack_m in _PATH_SLACK_RE.finditer(chunk):
            pass                                  # the LAST is the path's own
        sval = _to_float(slack_m.group(1)) if slack_m else None
        if sval is not None and (sval != sval or abs(sval) >= SENTINEL_MAGNITUDE):
            sval = None
        sp = _STARTPOINT_RE.search(chunk)
        ep = _ENDPOINT_RE.search(chunk)
        out.append(PathObservation(
            clock=clk,
            path_type=ptype.group(1).lower() if ptype else None,
            slack=sval,
            met=(slack_m.group(2).upper() == "MET") if slack_m else None,
            startpoint=sp.group(1) if sp else None,
            endpoint=ep.group(1) if ep else None,
            raw=chunk.strip().splitlines()[0] if chunk.strip() else "",
            line=base_line + block[:starts[i]].count("\n"),
        ))
    return out


def _parse_header(text: str) -> Header:
    m = _SIGNOFF_HEADER_RE.search(text)
    setup_c, hold_c = (m.group(1), m.group(2)) if m else (None, None)
    avail: Tuple[str, ...] = ()
    ma = _CORNERS_AVAIL_RE.search(text)
    if ma:
        avail = tuple(t.strip() for t in ma.group(1).split(",") if t.strip())
    libs = {c: p for c, p in _CORNER_LIBERTY_RE.findall(text)}
    md = _DISTINCT_LIBS_RE.search(text)
    return Header(
        setup_corner=setup_c, hold_corner=hold_c, corners_available=avail,
        corner_liberty=libs,
        distinct_library_count=int(md.group(1)) if md else None,
        reported_corner_count=int(md.group(2)) if md else None,
    )


def parse_report(text: Optional[str], *, path: Optional[str] = None,
                 sha256: Optional[str] = None) -> Report:
    """An OpenSTA report body -> a `Report`. Pure; touches no filesystem.

    A report with no `===` banner (dialect C) yields exactly ONE section with
    `banner=None`. That section is NOT given the file's stamps: relating a
    whole-file stamp to a section is meaning, and meaning is the domain's.
    """
    body = text or ""
    header = _parse_header(body)
    lines = body.splitlines()

    # Section boundaries first, so every measurement lands in exactly one.
    bounds: List[Tuple[int, Optional[str]]] = []
    for idx, ln in enumerate(lines):
        if _BANNER_RE.match(ln):
            bounds.append((idx, ln.strip()))

    def _mk(start: int, end: int, banner: Optional[str]) -> Section:
        chunk_lines = lines[start:end]
        meas: List[Measurement] = []
        for off, ln in enumerate(chunk_lines):
            if banner is not None and off == 0:
                continue                          # the banner is not a datum
            meas.extend(_measure_line(ln, start + off + 1))
        block = "\n".join(chunk_lines)
        wp_ok: Optional[bool] = None
        wp_fail: Optional[str] = None
        if _WORST_PATHS_FAILED_RE.search(block):
            wp_ok = False
            wp_fail = _WORST_PATHS_FAILED_RE.search(block).group(2).strip()
        elif _WORST_PATHS_OK_RE.search(block):
            wp_ok = True
        check = process = rc = spef = lib = None
        if banner is not None:
            check = "setup" if banner.upper().find("SETUP") >= 0 else "hold"
            mp = _BANNER_PROCESS_RE.search(banner)
            process = mp.group(1) if mp else None
            mr = _BANNER_RC_RE.search(banner)
            rc = mr.group(1) if mr else None
            ms = _BANNER_SPEF_RE.search(banner)
            spef = ms.group(1).strip() if ms else None
            ml = _BANNER_LIBERTY_RE.search(banner)
            lib = ml.group(1) if ml else None
        basis_corners = tuple(
            match.group(1).strip()
            for match in _BASIS_CORNER_RE.finditer(block))
        return Section(
            check=check, process=process, rc_corner=rc, spef=spef,
            basis_corners=basis_corners, liberty=lib,
            banner=banner, line=start + 1, measurements=tuple(meas),
            paths=tuple(_parse_paths(block, start + 1)),
            worst_paths_reported=wp_ok, worst_paths_failure=wp_fail,
        )

    sections: List[Section] = []
    if bounds:
        for i, (start, banner) in enumerate(bounds):
            end = bounds[i + 1][0] if i + 1 < len(bounds) else len(lines)
            sections.append(_mk(start, end, banner))
    else:
        sections.append(_mk(0, len(lines), None))

    mb = _STA_BASIS_RE.search(body)
    ms = _SIGNOFF_CORNER_RE.search(body)
    ml = _BASIS_LIBERTY_RE.search(body)
    msp = _BASIS_SPEF_RE.search(body)
    basis_corners = tuple(
        match.group(1).strip()
        for match in _BASIS_CORNER_RE.finditer(body))
    mc = _SIGNOFF_CORNER_COUNT_RE.search(body)
    ct_fail = _CHECK_TYPES_FAILED_RE.search(body)
    ct_ok = _CHECK_TYPES_OK_RE.search(body)
    return Report(
        path=path, sha256=sha256, header=header, sections=tuple(sections),
        basis_stamp=mb.group(1) if mb else None,
        signoff_corner=ms.group(1) if ms else None,
        basis_liberty=ml.group(1) if ml else None,
        basis_spef=msp.group(1) if msp else None,
        basis_corners=basis_corners,
        signoff_corner_count=int(mc.group(1)) if mc else None,
        check_types_reported=(False if ct_fail else (True if ct_ok else None)),
        check_types_failure=ct_fail.group(1).strip() if ct_fail else None,
        empty=not body.strip(),
    )


#: WHY THIS BACKEND IS NOT DRIVEN FROM A PATH (`_ppa/backends/__init__.py`).
#: `parse_report` returns a `Report` -- sections, headers and measurements --
#: and NOT canonical records, because turning a slack into a row means deciding
#: which view it belongs to, whether an infinity is a sentinel, and whether a
#: number may be withheld. Those are domain rules and they live in
#: `_ppa/timing.py`, which is the module that owns per-view timing rows. A
#: record producer bolted on here would be a second implementation of them,
#: free to disagree with the first about one number.
#: The reason names the domain module by FILE PATH and not by import path. The
#: purity guard in `tests/test_ppa_timing.py` bans the import spelling from this
#: file's code, and it is right to: a backend that can name its domain module as
#: a module is one refactor away from importing it, and then a parser has gained
#: the ability to decide what a number means. A path in a help string is
#: documentation and creates no such edge.
NO_DRIVER_REASON = (
    "opensta parses STA reports into a Report, not into records: deciding what "
    "a slack MEANS is a domain rule, and it lives in the timing domain module "
    "(`_ppa/timing.py`). Run that module over the project with --json and read "
    "the `vibeic.ppa.timing_rows.v1` document it writes with --records.")
