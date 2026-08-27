#!/usr/bin/env python3
"""
placement_legality_check.py — Step 17 (Placement) SUBSTANCE gate.

Anti-fabrication hardening
--------------------------
The flow gate for Step 17 previously read ``files_exist:
["phase3/stage3/pnr/placed.def"]`` ONLY — it passed the moment a file
named ``placed.def`` appeared, with ZERO inspection of its content. That
is a vacuous-PASS hole: a renamed/copied ``floorplan.def`` (where every
component is still UNPLACED — it carries no ``+ PLACED`` status), or a
placement run that silently left cells unplaced, would sail through.

This program parses the REAL OpenROAD/Innovus DEF and verifies SUBSTANCE:

  1. COMPONENTS section is present and its declared count > 0.
  2. The number of parsed component records equals the declared
     ``COMPONENTS <n>`` count (catches truncated / malformed DEFs).
  3. EVERY component carries a placement status of PLACED, FIXED, or
     COVER. A component with an explicit ``+ UNPLACED`` status — or with
     NO placement status keyword at all (the LEF/DEF default, which is
     exactly the shape of a pre-placement floorplan.def) — is UNPLACED
     and is a hard FAIL. (LEF/DEF 5.8 §COMPONENTS: a component is placed
     only if it states PLACED, FIXED, or COVER with a location.)
  4. The PLACER'S OWN legality verdict, from OpenROAD `check_placement`,
     as recorded by the runner in the stage logs. This is the only input
     that can see an overlap, a padding violation or an off-site instance —
     items 1-3 read the DEF STATUS FIELD, and an illegally placed instance
     still carries `+ PLACED ( x y ) N`. A non-zero violation count, or the
     DPL-33 raise that a non-zero count produces, is a hard FAIL. A run that
     records no such verdict leaves legality NOT DETERMINED, disclosed as
     such — items 1-3 do NOT stand in for it.
  5. Placement density (occupied-site-area / core-area) is verified to be
     in the universal sanity range (0, 100]% — but ONLY when it is
     derivable from an artefact the flow actually produced (an OpenROAD
     placement/density report JSON, or a ``DENSITY`` / utilization
     comment carried in the DEF). Per-cell areas are NOT in the DEF
     itself (they live in the LEF), so when no density artefact exists
     the check does NOT fabricate one — it records density as
     "not-derivable (informational)" and does not fail on it. A density
     that IS present and is > 100% (overlap / illegal placement) or <= 0
     is a hard FAIL.

The only numeric bounds applied are universal structural facts, not
chip-specific fabricated numbers:
  * COMPONENTS count must be > 0,
  * every instance must be PLACED/FIXED/COVER (not UNPLACED),
  * the placer's own violation count must be 0,
  * a derivable placement density must be in (0, 100]%.
No PDK/IC/tool-specific threshold is invented.

Verdicts
--------
* PASS  (rc=0) — placed.def parses; COMPONENTS > 0; declared count ==
                 parsed count; zero UNPLACED instances; no placer legality
                 failure recorded; any derivable density in (0, 100]%.
* FAIL  (rc=1) — placed.def absent / empty / unparseable, OR COMPONENTS
                 missing/zero, OR declared-vs-parsed count mismatch, OR
                 >= 1 UNPLACED instance, OR `check_placement` reported a
                 non-zero violation count / raised DPL-33, OR a
                 `*_LEGALIZE_FAILED` marker, OR a derivable density out of
                 (0, 100]%. (Step 17's precondition — placement was run —
                 means an absent placed.def is a real failure, never a
                 vacuous pass.)
* WAIVED (rc=0) — ``waivers.json`` declares this step waived.
* SKIP  (rc=2) — project dir not found (operational, not a placement
                 result).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 placement_legality_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402


_GATE_NAME = "placement_legality_check"
_GATE_LABEL = "placement_legality"

# Canonical placed.def location (Step 17 output).
_PLACED_DEF_REL = "phase3/stage3/pnr/placed.def"

# Placement-status keywords that mean a component HAS a legal location.
# Per LEF/DEF 5.8, a COMPONENT placement status is one of:
#   FIXED / COVER / PLACED   → has a location (legal)
#   UNPLACED                 → no location
#   (none stated)            → default = unplaced
_PLACED_STATUSES = ("PLACED", "FIXED", "COVER")

# Optional density artefacts the runner may emit (parsed only if present;
# never required, never fabricated). Keys searched for a fractional or
# percentage placement-density / utilization value.
_DENSITY_JSON_CANDIDATES = [
    "reports/phase3/density.json",
    "reports/density.json",
    "phase3/stage3/pnr/place_density.json",
    "phase3/stage3/pnr/placement.json",
]
_DENSITY_KEYS = (
    "placement_density_pct", "placement_density", "place_density",
    "utilization_pct", "utilization", "core_utilization",
    "density_pct", "density",
)


def _load_waivers(project: Path):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text()).get("waived_steps") or []
    except Exception:
        return []


def _step_waived(project: Path, step_label: str):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


def _split_components(path: Path) -> Tuple[Optional[int], List[str]]:
    """Return (declared_count, records).

    declared_count is the integer from ``COMPONENTS <n> ;`` (None if the
    section header is absent). records is a list of strings, one per
    component, each the full (possibly multi-line) text from the leading
    ``-`` up to and including its terminating ``;``. A record is the unit
    the DEF terminates with ``;`` — a component statement may legally span
    several physical lines, so we accumulate until the ``;`` that closes
    it.
    """
    declared: Optional[int] = None
    records: List[str] = []
    in_comp = False
    cur: List[str] = []

    with path.open(errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            s = line.strip()
            if not in_comp:
                m = re.match(r"COMPONENTS\s+(\d+)\s*;", s)
                if m:
                    declared = int(m.group(1))
                    in_comp = True
                continue
            # inside COMPONENTS section
            if s.startswith("END COMPONENTS"):
                if cur:
                    records.append(" ".join(cur))
                    cur = []
                in_comp = False
                continue
            if not s:
                continue
            if s.startswith("-") and cur:
                # New record begins before previous closed (defensive):
                # flush the previous accumulation.
                records.append(" ".join(cur))
                cur = []
            cur.append(s)
            if s.endswith(";"):
                records.append(" ".join(cur))
                cur = []
    if cur:  # unterminated trailing record (malformed DEF)
        records.append(" ".join(cur))
    return declared, records


def _record_is_placed(record: str) -> bool:
    """A component record is PLACED iff it states ``+ PLACED|FIXED|COVER``.

    An explicit ``+ UNPLACED`` or no status keyword at all → unplaced.
    """
    if re.search(r"\+\s*UNPLACED\b", record):
        return False
    for st in _PLACED_STATUSES:
        if re.search(r"\+\s*" + st + r"\b", record):
            return True
    return False


def _coerce_density_pct(val) -> Optional[float]:
    """Coerce a density/utilization value to a percentage.

    Accepts a fraction (0..1] → *100, or an already-percentage value.
    Returns None if not a usable number. A value in (0,1] is treated as a
    fraction; > 1 is treated as already a percentage. (A real placement
    utilization is never legitimately in the ambiguous 0<x<=1 *percent*
    band, so this heuristic is safe and stated in honest_notes.)
    """
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return f  # let caller flag <= 0 as FAIL
    if f <= 1.0:
        return f * 100.0
    return f


def _read_density(project: Path) -> Tuple[Optional[float], Optional[str]]:
    """Return (density_pct, source_rel) from any present artefact, else
    (None, None). Never fabricates."""
    for rel in _DENSITY_JSON_CANDIDATES:
        p = project / rel
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        for k in _DENSITY_KEYS:
            if k in doc and doc[k] is not None:
                pct = _coerce_density_pct(doc[k])
                if pct is not None:
                    return pct, rel
    return None, None


def _read_def_density_comment(path: Path) -> Optional[float]:
    """Some flows stamp a placement density into the DEF as a comment
    (``# DENSITY 0.63`` / ``# PLACEMENT_DENSITY 63.0``). Parse it if present;
    return None otherwise. Never fabricates."""
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                m = re.search(
                    r"#\s*(?:PLACEMENT_)?DENSITY\s*[:=]?\s*([0-9]*\.?[0-9]+)",
                    line, re.IGNORECASE)
                if m:
                    return _coerce_density_pct(m.group(1))
    except OSError:
        return None
    return None


# The runner's PnR Tcl runs OpenROAD's own `check_placement` after each
# legalization attempt and condenses the result to one marker per site:
#     <SITE>_LEGALIZE_OK disp=<rung>     check_placement returned clean
#     <SITE>_LEGALIZE_FAILED             every escalation rung exhausted
# `check_placement` is the placer's OWN legality verdict — it is what detects
# an overlap, a padding violation or an off-site instance. This gate is named
# `placement_legality_check` and, before the two readers below, never read it.
_LEGALIZE_FAILED_SUFFIX = "_LEGALIZE_FAILED"
_LEGALIZE_OK_SUFFIX = "_LEGALIZE_OK"
_LEGALIZE_MARKER_RE = re.compile(
    r"\b([A-Z0-9_]+_LEGALIZE_(?:OK|FAILED))\b")


# --- The placer's OWN verdict, as a NUMBER -----------------------------------
# The markers above are a BOOLEAN condensation of the legalization ladder, and
# they only exist for the rungs inside that ladder. The `check_placement` calls
# OUTSIDE it — after spare-cell insertion, and after the repair's own legalization
# — wrapped the RAISING form in a `catch` and printed the tool's refusal as a
# warning string:
#
#     [WARNING DPL-0005] Overlap check failed (1).
#     [WARNING DPL-0011] Padding check failed (1).
#     [ERROR   DPL-0033] detailed placement checks failed during check placement.
#     SPARE_CHECK_PLACEMENT_WARN: DPL-0033
#
# Nothing read that line. Measured on a DEF whose ONLY edit is one instance
# moved from site 3 to site 1, with that log beside it: this gate returned
# `verdict: PASS`, exit 0.
#
# OpenROAD's own `info body check_placement` says why that is not survivable:
#
#     # Returns the violation count. Without -no_abort a non-zero count raises
#     # DPL-33 instead of returning, so an illegal placement can never be
#     # mistaken for a legal one by a caller that ignores the result.
#
# The runner now asks for that count (`-no_abort` returns it instead of
# raising) and prints it structurally. This gate refuses on the NUMBER:
#     <SITE>_CHECK_PLACEMENT_VIOLATIONS <n>      n > 0 -> FAIL
#     <SITE>_CHECK_PLACEMENT_RAISED: <err>       DPL-33 -> FAIL
#     <SITE>_CHECK_PLACEMENT_WARN: <err>         the LEGACY shape, still FAIL,
#                                                so logs already on disk from
#                                                before this change are read
#                                                the way the tool meant them
#     <SITE>_CHECK_PLACEMENT_UNAVAILABLE: <err>  NOT DETERMINED — disclosed,
#                                                never scored as legal
#
# chip-AGNOSTIC: an OpenROAD command's own output grammar plus the runner's
# marker prefix; no chip, PDK, library or design literal.
_CP_VIOLATIONS_RE = re.compile(
    r"\b([A-Z0-9_]+)_CHECK_PLACEMENT_VIOLATIONS\s+(\d+)\b")
_CP_RAISED_RE = re.compile(
    r"\b([A-Z0-9_]+)_CHECK_PLACEMENT_(?:RAISED|WARN)\s*:\s*(.*)")
_CP_UNAVAILABLE_RE = re.compile(
    r"\b([A-Z0-9_]+)_CHECK_PLACEMENT_UNAVAILABLE\s*:\s*(.*)")


# WHERE the runner's placement verdicts are written. The legalization ladder
# and the spare-cell check run inside the P&R script, whose transcript lands in
# `phase3/stage3/pnr/`; the timing repair is a SEPARATE OpenROAD invocation and its
# transcript lands in `phase3/stage3/postroute_timing_repair/postroute_timing_repair.log`. Scanning only `pnr/`
# — which is what the marker reader did — is blind to every verdict the repair
# emits, including its own `POSTROUTE_TIMING_REPAIR_DPL_LEGALIZE_FAILED`. CTS is listed for the same
# reason: a stage that writes its own log must not be a hole.
_VERDICT_LOG_DIRS = (
    ("phase3", "stage3", "pnr"),
    ("phase3", "stage3", "cts"),
    ("phase3", "stage3", "postroute_timing_repair"),
)


def _verdict_logs(project: Path) -> List[Path]:
    """Every stage transcript that can carry a placement verdict, sorted and
    de-duplicated. Missing directories are simply absent, not an error."""
    out: List[Path] = []
    for parts in _VERDICT_LOG_DIRS:
        d = project.joinpath(*parts)
        if not d.is_dir():
            continue
        for log in sorted(d.rglob("*.log")):
            if log not in out:
                out.append(log)
    return out


def _check_placement_verdicts(project: Path) -> dict:
    """Collect `check_placement`'s own verdicts from the PnR logs.

    Returns {"counts": [[site, n], ...], "raised": [[site, err], ...],
             "unavailable": [[site, err], ...]}, each de-duplicated and in
    first-seen order. Empty everywhere when the run recorded no such verdict.
    """
    counts: List[List] = []
    raised: List[List] = []
    unavailable: List[List] = []
    for log in _verdict_logs(project):
        try:
            with log.open(errors="replace") as fh:
                for line in fh:
                    m = _CP_VIOLATIONS_RE.search(line)
                    if m:
                        rec = [m.group(1), int(m.group(2))]
                        if rec not in counts:
                            counts.append(rec)
                        continue
                    m = _CP_RAISED_RE.search(line)
                    if m:
                        rec = [m.group(1), m.group(2).strip()]
                        if rec not in raised:
                            raised.append(rec)
                        continue
                    m = _CP_UNAVAILABLE_RE.search(line)
                    if m:
                        rec = [m.group(1), m.group(2).strip()]
                        if rec not in unavailable:
                            unavailable.append(rec)
        except OSError:
            continue
    return {"counts": counts, "raised": raised, "unavailable": unavailable}


def _legalizer_markers(project: Path) -> tuple[List[str], List[str]]:
    """Return (failed_markers, ok_markers) found in the PnR logs.

    Chip-AGNOSTIC: the markers are the runner's own structural output, not a
    chip, PDK or library literal.
    """
    failed: List[str] = []
    ok: List[str] = []
    # Every stage transcript, not just `pnr/`: the repair runs OpenROAD again and
    # writes `POSTROUTE_TIMING_REPAIR_DPL_LEGALIZE_FAILED` into its OWN log, which a `pnr/`-only
    # scan never saw.
    for log in _verdict_logs(project):
        try:
            with log.open(errors="replace") as fh:
                for line in fh:
                    for m in _LEGALIZE_MARKER_RE.finditer(line):
                        tok = m.group(1)
                        if tok.endswith(_LEGALIZE_FAILED_SUFFIX):
                            if tok not in failed:
                                failed.append(tok)
                        elif tok.endswith(_LEGALIZE_OK_SUFFIX):
                            if tok not in ok:
                                ok.append(tok)
        except OSError:
            continue
    return failed, ok


def inspect(project: Path):
    """Return (verdict, rc, findings, summary)."""
    findings: List[dict] = []
    summary = {
        "placed_def": _PLACED_DEF_REL,
        "legalizer_failed_markers": [],
        "legalizer_ok_markers": [],
        # `check_placement`'s OWN result, as the tool reports it.
        "check_placement_violations": [],
        "check_placement_raised": [],
        "check_placement_unavailable": [],
        "placer_legality_verdict": "NOT DETERMINED",
        "declared_components": None,
        "parsed_components": None,
        "placed": None,
        "unplaced": None,
        "density_pct": None,
        "density_source": None,
    }

    placed_path = project / _PLACED_DEF_REL

    # ---- Honest FAIL on missing / empty artefact ------------------------
    if not placed_path.is_file():
        findings.append({
            "severity": "FAIL", "rule": "PLACED_DEF_MISSING",
            "message": f"required placement artefact absent: {_PLACED_DEF_REL} "
                       f"(Step 17 ran placement, so this is a real failure)",
        })
        return "FAIL", 1, findings, summary
    if placed_path.stat().st_size == 0:
        findings.append({
            "severity": "FAIL", "rule": "PLACED_DEF_EMPTY",
            "message": f"{_PLACED_DEF_REL} is zero bytes",
        })
        return "FAIL", 1, findings, summary

    # ---- Parse the COMPONENTS section -----------------------------------
    try:
        declared, records = _split_components(placed_path)
    except Exception as e:  # noqa: BLE001
        findings.append({
            "severity": "FAIL", "rule": "PLACED_DEF_UNPARSEABLE",
            "message": f"cannot parse {_PLACED_DEF_REL}: {e}",
        })
        return "FAIL", 1, findings, summary

    if declared is None:
        findings.append({
            "severity": "FAIL", "rule": "NO_COMPONENTS_SECTION",
            "message": f"{_PLACED_DEF_REL} has no `COMPONENTS <n> ;` section "
                       f"— not a placed DEF",
        })
        return "FAIL", 1, findings, summary

    summary["declared_components"] = declared
    summary["parsed_components"] = len(records)

    if declared == 0 or not records:
        findings.append({
            "severity": "FAIL", "rule": "EMPTY_COMPONENTS",
            "message": f"COMPONENTS count is {declared} with {len(records)} "
                       f"parsed records — placed DEF has no instances",
        })
        return "FAIL", 1, findings, summary

    # Declared count must match the number of records we actually parsed.
    if len(records) != declared:
        findings.append({
            "severity": "FAIL", "rule": "COMPONENT_COUNT_MISMATCH",
            "message": f"COMPONENTS declares {declared} but {len(records)} "
                       f"records parsed — truncated/malformed DEF",
        })
        return "FAIL", 1, findings, summary

    # ---- Placement-status check (the core substance) --------------------
    unplaced_examples: List[str] = []
    placed_n = 0
    for rec in records:
        if _record_is_placed(rec):
            placed_n += 1
        else:
            if len(unplaced_examples) < 5:
                # First token after the leading '-' is the instance name.
                m = re.match(r"-\s*(\S+)", rec)
                unplaced_examples.append(m.group(1) if m else rec[:60])
    unplaced_n = len(records) - placed_n
    summary["placed"] = placed_n
    summary["unplaced"] = unplaced_n

    if unplaced_n > 0:
        findings.append({
            "severity": "FAIL", "rule": "UNPLACED_INSTANCES",
            "message": f"{unplaced_n}/{len(records)} component(s) are UNPLACED "
                       f"(no PLACED/FIXED/COVER status). examples: "
                       f"{unplaced_examples}. A placed.def with unplaced "
                       f"instances is illegal — likely a floorplan.def copy "
                       f"or an aborted placement.",
        })
        # Do not early-return: still record density info below for the report.
        verdict, rc = "FAIL", 1
    else:
        findings.append({
            "severity": "INFO", "rule": "ALL_PLACED",
            "message": f"all {placed_n} component(s) carry PLACED/FIXED/COVER "
                       f"status",
        })
        verdict, rc = "PASS", 0

    # ---- The placer's OWN legality verdict ------------------------------
    # Everything above is read from `placed.def`, the PRE-CTS snapshot, and
    # its predicate is a DEF status TOKEN. Neither can see the failure this
    # gate is named for:
    #   * the window — CTS and hold repair insert instances AFTER placed.def
    #     is written, so an instance that is illegal is not in the file this
    #     gate reads; and
    #   * the predicate — an overlapping or off-site instance still carries
    #     `+ PLACED ( x y ) N`. The token is written regardless of legality,
    #     so `unplaced == 0` is compatible with a design the placer could not
    #     legalize at all.
    # OpenROAD's `check_placement` is the verdict that does see it, the runner
    # already runs it, and its result is in the log. Read it.
    failed_markers, ok_markers = _legalizer_markers(project)
    summary["legalizer_failed_markers"] = failed_markers
    summary["legalizer_ok_markers"] = ok_markers
    if failed_markers:
        findings.append({
            "severity": "FAIL", "rule": "LEGALIZER_REPORTED_FAILURE",
            "message": (
                f"the placer's own legality check FAILED in this run: "
                f"{failed_markers} in the PnR log"
                + (f" (succeeded at: {ok_markers})" if ok_markers else "")
                + f". {_PLACED_DEF_REL} is the PRE-CTS snapshot and a DEF "
                  f"status token cannot express an overlap, so the checks "
                  f"above cannot see this: they report "
                  f"{placed_n} placed / {unplaced_n} unplaced and are "
                  f"correct about the file they read. An unlegalized design "
                  f"loses pin access at detailed routing, and the resulting "
                  f"unrouted layout is then measured by DRC, LVS and EM as "
                  f"though it were the design."),
        })
        verdict, rc = "FAIL", 1
    elif ok_markers:
        findings.append({
            "severity": "INFO", "rule": "LEGALIZER_REPORTED_OK",
            "message": f"the placer's own legality check passed: {ok_markers}",
        })
    else:
        findings.append({
            "severity": "INFO", "rule": "LEGALIZER_VERDICT_ABSENT",
            "message": (
                "no `*_LEGALIZE_OK` / `*_LEGALIZE_FAILED` marker in the PnR "
                "log — this run records no placer legality verdict, so the "
                "status-token checks above stand alone. Not fabricated as a "
                "pass."),
        })

    # ---- `check_placement`'s OWN violation COUNT -------------------------
    # The ladder markers above are a boolean, and they cover only the rungs
    # inside the legalization ladder. This reads the tool's NUMBER, from every
    # site the runner calls `check_placement` — including the two that used to
    # print DPL-33 as a warning nobody read.
    cp = _check_placement_verdicts(project)
    summary["check_placement_violations"] = cp["counts"]
    summary["check_placement_raised"] = cp["raised"]
    summary["check_placement_unavailable"] = cp["unavailable"]

    nonzero = [[site, n] for site, n in cp["counts"] if n > 0]
    if nonzero:
        summary["placer_legality_verdict"] = "ILLEGAL"
        total = sum(n for _s, n in nonzero)
        findings.append({
            "severity": "FAIL", "rule": "CHECK_PLACEMENT_VIOLATIONS",
            "message": (
                f"OpenROAD `check_placement` reported {total} violation(s) in "
                f"this run: "
                + ", ".join(f"{site}={n}" for site, n in nonzero)
                + ". That is the placer's OWN verdict on the database it "
                  "actually placed — an overlap, a padding violation or an "
                  "off-site instance. The DEF status-token checks above cannot "
                  "see any of those: an illegally placed instance still "
                  "carries `+ PLACED ( x y ) N`, so they report "
                  f"{placed_n} placed / {unplaced_n} unplaced and are correct "
                  "about the file they read."),
        })
        verdict, rc = "FAIL", 1
    elif cp["raised"]:
        summary["placer_legality_verdict"] = "ILLEGAL"
        findings.append({
            "severity": "FAIL", "rule": "CHECK_PLACEMENT_RAISED",
            "message": (
                "OpenROAD `check_placement` RAISED rather than returning: "
                + "; ".join(f"{site}: {err}" for site, err in cp["raised"])
                + ". Per the command's own definition, the raising form throws "
                  "DPL-33 exactly when the violation count is non-zero, so a "
                  "raise IS an illegal placement. It was previously caught and "
                  "printed as a warning that no gate read."),
        })
        verdict, rc = "FAIL", 1
    elif cp["counts"]:
        summary["placer_legality_verdict"] = "LEGAL"
        findings.append({
            "severity": "INFO", "rule": "CHECK_PLACEMENT_CLEAN",
            "message": (
                "OpenROAD `check_placement` reported 0 violations at: "
                + ", ".join(site for site, _n in cp["counts"])),
        })
    else:
        # NOT DETERMINED. Disclosed as such: the DEF checks above are a
        # different axis and are NOT a legality verdict.
        findings.append({
            "severity": "INFO", "rule": "CHECK_PLACEMENT_NOT_RUN",
            "message": (
                "no `*_CHECK_PLACEMENT_VIOLATIONS` / `_RAISED` / `_WARN` "
                "record in the PnR log — this run carries NO placer legality "
                "verdict, so legality is NOT DETERMINED here. The "
                "COMPONENTS/status-token and density checks in this gate "
                "verify a different property and do not stand in for it."),
        })
        if cp["unavailable"]:
            findings.append({
                "severity": "INFO", "rule": "CHECK_PLACEMENT_UNAVAILABLE",
                "message": (
                    "`check_placement` could not produce a verdict: "
                    + "; ".join(f"{site}: {err}"
                                for site, err in cp["unavailable"])
                    + ". Recorded as NOT DETERMINED, never as legal."),
            })

    # ---- Placement density (only if derivable; never fabricated) --------
    density_pct, dsrc = _read_density(project)
    if density_pct is None:
        c = _read_def_density_comment(placed_path)
        if c is not None:
            density_pct, dsrc = c, _PLACED_DEF_REL

    if density_pct is None:
        findings.append({
            "severity": "INFO", "rule": "DENSITY_NOT_DERIVABLE",
            "message": "placement density not derivable from DEF alone "
                       "(per-cell areas live in the LEF) and no density "
                       "report present — density check skipped, NOT "
                       "fabricated",
        })
    else:
        summary["density_pct"] = round(density_pct, 4)
        summary["density_source"] = dsrc
        if density_pct <= 0:
            findings.append({
                "severity": "FAIL", "rule": "DENSITY_NONPOSITIVE",
                "message": f"placement density {density_pct:.3f}% from {dsrc} "
                           f"is <= 0 — impossible / corrupt",
            })
            verdict, rc = "FAIL", 1
        elif density_pct > 100.0 + 1e-6:
            findings.append({
                "severity": "FAIL", "rule": "DENSITY_OVER_100",
                "message": f"placement density {density_pct:.3f}% from {dsrc} "
                           f"exceeds 100% — cell-area overlap / illegal "
                           f"placement",
            })
            verdict, rc = "FAIL", 1
        else:
            findings.append({
                "severity": "INFO", "rule": "DENSITY_OK",
                "message": f"placement density {density_pct:.3f}% from {dsrc} "
                           f"is within (0, 100]%",
            })

    return verdict, rc, findings, summary


def _emit(args, project, verdict, summary, findings, waiver):
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": _GATE_LABEL,
        "placed_def": summary["placed_def"],
        "declared_components": summary["declared_components"],
        "parsed_components": summary["parsed_components"],
        "placed": summary["placed"],
        "unplaced": summary["unplaced"],
        "density_pct": summary["density_pct"],
        "density_source": summary["density_source"],
        "placer_legality_verdict": summary.get("placer_legality_verdict"),
        "check_placement_violations": summary.get("check_placement_violations"),
        "check_placement_raised": summary.get("check_placement_raised"),
        "check_placement_unavailable":
            summary.get("check_placement_unavailable"),
        "legalizer_failed_markers": summary.get("legalizer_failed_markers"),
        "legalizer_ok_markers": summary.get("legalizer_ok_markers"),
        "waiver": waiver,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if summary["declared_components"] is not None:
        print(f"  components: declared={summary['declared_components']} "
              f"parsed={summary['parsed_components']} "
              f"placed={summary['placed']} unplaced={summary['unplaced']}")
    if summary["density_pct"] is not None:
        print(f"  density: {summary['density_pct']}% "
              f"({summary['density_source']})")
    for f in findings:
        if f["severity"] in ("FAIL", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")

    # vibe-ic#1080 — emit the per-step metric HERE, at the one point this gate
    # publishes its numbers, so a later reader gets the count the gate COMPUTED
    # instead of re-deriving it from the report above or from a DEF. This is
    # the whole of the wiring: the numbers already exist, they were simply
    # never handed to anyone. Best-effort by construction — see
    # `step_metrics.emit_best_effort`.
    import step_metrics as _sm  # noqa: PLC0415
    _sm.emit_best_effort(project, "17", {
        "verdict": verdict,
        "declared_components": summary.get("declared_components"),
        "parsed_components": summary.get("parsed_components"),
        "placed": summary.get("placed"),
        "unplaced": summary.get("unplaced"),
        "density_pct": summary.get("density_pct"),
        # These summary fields are LISTS of offenders, not counts. Emitting
        # `len()` is the measurement; emitting the list would be refused by
        # the flat schema, which is how this was caught.
        "violation_count": len(summary.get("check_placement_violations") or []),
        "legalizer_failed_marker_count":
            len(summary.get("legalizer_failed_markers") or []),
        "findings_count": len(findings),
    }, domain="design")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    waiver = _step_waived(project, args.step_label)

    # Waiver path: explicit, recorded — only honored when the artefact is
    # genuinely absent (non-production runs). A present-but-failing DEF is
    # NOT waivable here, so substance is always checked when the file exists.
    placed_path = project / _PLACED_DEF_REL
    if waiver and not placed_path.is_file():
        findings = [{
            "severity": "WAIVED", "rule": "STEP_WAIVED",
            "message": f"waiver={waiver.get('ticket', '?')}: "
                       f"{waiver.get('reason', '?')}",
        }]
        summary = {
            "placed_def": _PLACED_DEF_REL, "declared_components": None,
            "parsed_components": None, "placed": None, "unplaced": None,
            "density_pct": None, "density_source": None,
        }
        _emit(args, project, "WAIVED", summary, findings, waiver)
        return 0

    verdict, rc, findings, summary = inspect(project)
    _emit(args, project, verdict, summary, findings, waiver)
    return rc


if __name__ == "__main__":
    sys.exit(main())
