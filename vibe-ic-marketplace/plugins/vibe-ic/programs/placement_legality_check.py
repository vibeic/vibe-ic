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

Two independent things are checked, and NEITHER stands in for the other.

(A) The placer's OWN legality verdict — `check_placement`'s violation
    count. It is the only reading here that can see an overlap, a padding
    violation or an off-site instance, because none of those change the
    DEF status token: an overlapping instance still says
    `+ PLACED ( x y ) N`. The runner runs `check_placement` at every
    placement-mutating site; this gate reads the count it returns and
    refuses on a non-zero one. A count that was caught and printed as a
    warning is itself a FAIL — a discarded count is not a legal placement,
    it is an unknown one that exited 0.

(B) The DEF structural checks below. They catch a DIFFERENT failure — a
    renamed floorplan.def, a truncated DEF, an aborted placement that left
    instances UNPLACED — which the placer's verdict does not speak to,
    and they are kept for exactly that reason.

For (B), this program parses the REAL OpenROAD/Innovus DEF and verifies
SUBSTANCE:

  1. COMPONENTS section is present and its declared count > 0.
  2. The number of parsed component records equals the declared
     ``COMPONENTS <n>`` count (catches truncated / malformed DEFs).
  3. EVERY component carries a placement status of PLACED, FIXED, or
     COVER. A component with an explicit ``+ UNPLACED`` status — or with
     NO placement status keyword at all (the LEF/DEF default, which is
     exactly the shape of a pre-placement floorplan.def) — is UNPLACED
     and is a hard FAIL. (LEF/DEF 5.8 §COMPONENTS: a component is placed
     only if it states PLACED, FIXED, or COVER with a location.)
  4. Placement density (occupied-site-area / core-area) is verified to be
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
  * a derivable placement density must be in (0, 100]%.
No PDK/IC/tool-specific threshold is invented.

Verdicts
--------
* PASS  (rc=0) — placed.def parses; COMPONENTS > 0; declared count ==
                 parsed count; zero UNPLACED instances; any derivable
                 density in (0, 100]%; and the placer's own
                 `check_placement` reported no violation it could not
                 legalize.
* FAIL  (rc=1) — placed.def absent / empty / unparseable, OR COMPONENTS
                 missing/zero, OR declared-vs-parsed count mismatch, OR
                 >= 1 UNPLACED instance, OR a derivable density out of
                 (0, 100]%, OR the placer's own verdict says the design is
                 illegal (see below). (Step 17's precondition — placement
                 was run — means an absent placed.def is a real failure,
                 never a vacuous pass.)
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
# an overlap, a padding violation or an off-site instance. These markers are
# the ESCALATION LOOP's condensed form of it; the loop's final count, and the
# counts from the other call sites, are read separately below.
_LEGALIZE_FAILED_SUFFIX = "_LEGALIZE_FAILED"
_LEGALIZE_OK_SUFFIX = "_LEGALIZE_OK"
_LEGALIZE_MARKER_RE = re.compile(
    r"\b([A-Z0-9_]+_LEGALIZE_(?:OK|FAILED))\b")


def _legalizer_markers(project: Path) -> tuple[List[str], List[str]]:
    """Return (failed_markers, ok_markers) found in the PnR logs.

    Chip-AGNOSTIC: the markers are the runner's own structural output, not a
    chip, PDK or library literal.
    """
    failed: List[str] = []
    ok: List[str] = []
    pnr_dir = project / "phase3" / "stage3" / "pnr"
    if not pnr_dir.is_dir():
        return failed, ok
    for log in sorted(pnr_dir.rglob("*.log")):
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


# ---------------------------------------------------------------------------
# The placer's OWN verdict: `check_placement`'s violation COUNT.
#
# From the installed binary's own proc body (`info body check_placement`):
#     "Returns the violation count. Without `-no_abort` a non-zero count
#      raises DPL-33 instead of returning, so an illegal placement can never
#      be mistaken for a legal one by a caller that ignores the result."
#
# The runner calls `check_placement` at FINAL sites — after spare insertion,
# after ECO repair, and in the ship-convergence loop. Each of those sites used
# to wrap the call in `catch` and print the caught string as a WARN. That is
# the count being demoted to a warning: the tool exits 0, the WARN is read by
# nothing, and this gate — the one named for placement legality — passed the
# run. MEASURED on a two-instance fixture: `check_placement -no_abort` returns
# 2 and logs `DPL-0040 ... 2 violation(s) returned to caller`; the same
# database under a bare `check_placement` logs `[ERROR DPL-0033]`, the catch
# prints `..._CHECK_PLACEMENT_WARN: DPL-0033`, and the process exits 0.
#
# Only the FINAL sites are scored here. The escalating legalizer deliberately
# catches DPL-33 on each displacement rung and retries the next one, so DPL-33
# lines appear in fully converged runs; that loop's verdict is the
# `*_LEGALIZE_OK` / `*_LEGALIZE_FAILED` pair read above, not these markers.
#
# Two shapes are read, because a log written by an older runner is still a log:
#   * CURRENT — `CHECK_PLACEMENT_VIOLATIONS <scope> <n>` carries the count that
#     `check_placement -no_abort` returned; `CHECK_PLACEMENT_CLEAN <scope> 0`
#     is the certified-legal counterpart, and
#     `CHECK_PLACEMENT_NOT_DETERMINED <scope> <err>` says the call itself did
#     not produce a verdict (never a pass).
#   * LEGACY — `<SCOPE>_CHECK_PLACEMENT_WARN` / `SHIP_CP_WARN` /
#     `SHIP_CVG_CP_WARN` is a caught DPL-33: a non-zero count that was thrown
#     away. It fails on its own; the count is recovered from the tool's own
#     diagnostic lines that precede it and quoted when they are present.
#
# chip-AGNOSTIC: the tool's own diagnostic IDs and the runner's own marker
# grammar. No chip, PDK, library or design literal.
_CP_VIOLATIONS_RE = re.compile(
    r"\bCHECK_PLACEMENT_VIOLATIONS\s+([A-Z0-9_]+)\s+(\d+)\b")
_CP_CLEAN_RE = re.compile(
    r"\bCHECK_PLACEMENT_CLEAN\s+([A-Z0-9_]+)\s+(\d+)\b")
_CP_NOT_DETERMINED_RE = re.compile(
    r"\bCHECK_PLACEMENT_NOT_DETERMINED\s+([A-Z0-9_]+)\s*(.*)$")
# A caught DPL-33 at a final site, under any of the runner's scope prefixes.
_CP_DEMOTED_RE = re.compile(
    r"\b([A-Z0-9_]*(?:CHECK_PLACEMENT|CP)_WARN)\b")
# The tool's own words. DPL-40 is the `-no_abort` return path (it states the
# count); DPL-33 is the abort path (it does not, so the per-category
# `... check failed (n)` warnings above it are what carry the numbers).
_DPL_RETURNED_COUNT_RE = re.compile(
    r"\bDPL-0*40\b[^\n]*?(\d+)\s+violation", re.IGNORECASE)
_DPL_ABORT_RE = re.compile(r"\bDPL-0*33\b")
_DPL_CATEGORY_COUNT_RE = re.compile(
    r"\b(DPL-\d+)\]\s*(.+?)\s+check failed\s*\((\d+)\)", re.IGNORECASE)
# Any of these ends one `check_placement` invocation's diagnostic window, so
# evidence is never attributed to the wrong call.
_CP_BOUNDARY_RE = re.compile(
    r"\bCHECK_PLACEMENT_(?:VIOLATIONS|CLEAN|NOT_DETERMINED)\b"
    r"|[A-Z0-9_]*(?:CHECK_PLACEMENT|CP)_(?:WARN|PASS)\b"
    r"|[A-Z0-9_]+_LEGALIZE_(?:OK|FAILED)\b")


def _cp_log_dirs(project: Path) -> List[Path]:
    """Directories the runner writes PnR-stage OpenROAD logs into.

    The ECO repair deck runs `check_placement` too and tees its log into
    `phase3/stage3/eco/`, so a scan pinned to `pnr/` alone would miss that
    site's verdict entirely.
    """
    return [project / "phase3" / "stage3" / "pnr",
            project / "phase3" / "stage3" / "eco"]


def _check_placement_verdicts(project: Path) -> dict:
    """Read the placer's own `check_placement` verdict out of the run logs.

    Returns a dict with `violations`, `demoted`, `not_determined`, `clean`
    and `logs_scanned`. Absence of every marker is reported as absence — it is
    never turned into either a pass or a failure.
    """
    res: dict = {
        "violations": [],
        "demoted": [],
        "not_determined": [],
        "clean": [],
        "logs_scanned": [],
    }
    for d in _cp_log_dirs(project):
        if not d.is_dir():
            continue
        for log in sorted(d.rglob("*.log")):
            try:
                text = log.open(errors="replace")
            except OSError:
                continue
            rel = str(log.relative_to(project))
            res["logs_scanned"].append(rel)
            evidence: List[str] = []
            with text as fh:
                for raw in fh:
                    line = raw.rstrip("\n")
                    # A marker CLOSES the diagnostic window it belongs to, so
                    # markers are matched before the window is appended to —
                    # otherwise the marker line (which names DPL-33 itself)
                    # would be filed as its own evidence.
                    is_marker = bool(_CP_VIOLATIONS_RE.search(line)
                                     or _CP_CLEAN_RE.search(line)
                                     or _CP_NOT_DETERMINED_RE.search(line)
                                     or _CP_DEMOTED_RE.search(line)
                                     or _CP_BOUNDARY_RE.search(line))
                    if not is_marker and (
                            _DPL_RETURNED_COUNT_RE.search(line)
                            or _DPL_CATEGORY_COUNT_RE.search(line)
                            or _DPL_ABORT_RE.search(line)):
                        ev = line.strip()
                        if ev and ev not in evidence:
                            evidence.append(ev)

                    m = _CP_VIOLATIONS_RE.search(line)
                    if m:
                        n = int(m.group(2))
                        entry = {"scope": m.group(1), "count": n,
                                 "log": rel, "tool_evidence": list(evidence)}
                        if n > 0:
                            res["violations"].append(entry)
                        else:
                            # A marker that names itself VIOLATIONS with a zero
                            # count is a contradiction; record the scope as
                            # clean rather than invent a failure.
                            res["clean"].append(
                                {"scope": m.group(1), "count": 0, "log": rel})
                        evidence = []
                        continue
                    m = _CP_CLEAN_RE.search(line)
                    if m:
                        res["clean"].append({"scope": m.group(1),
                                             "count": int(m.group(2)),
                                             "log": rel})
                        evidence = []
                        continue
                    m = _CP_NOT_DETERMINED_RE.search(line)
                    if m:
                        res["not_determined"].append(
                            {"scope": m.group(1),
                             "detail": (m.group(2) or "").strip(),
                             "log": rel})
                        evidence = []
                        continue
                    m = _CP_DEMOTED_RE.search(line)
                    if m:
                        res["demoted"].append({"marker": m.group(1),
                                               "line": line.strip(),
                                               "log": rel,
                                               "tool_evidence": list(evidence)})
                        evidence = []
                        continue
                    if _CP_BOUNDARY_RE.search(line):
                        evidence = []
    return res


def _cp_count_from_evidence(evidence: List[str]) -> Optional[int]:
    """The tool's own violation count, recovered from its own log lines.

    Prefers the `-no_abort` return line (which states the total); otherwise
    sums the per-category `... check failed (n)` warnings, which is how the
    total is composed on the abort path. Returns None when the tool said
    nothing countable — NOT DETERMINED beats a guess.
    """
    for ev in evidence:
        m = _DPL_RETURNED_COUNT_RE.search(ev)
        if m:
            return int(m.group(1))
    total = 0
    seen = False
    for ev in evidence:
        m = _DPL_CATEGORY_COUNT_RE.search(ev)
        if m:
            total += int(m.group(3))
            seen = True
    return total if seen else None


def inspect(project: Path):
    """Return (verdict, rc, findings, summary)."""
    findings: List[dict] = []
    summary = {
        "placed_def": _PLACED_DEF_REL,
        "legalizer_failed_markers": [],
        "legalizer_ok_markers": [],
        "check_placement_violations": [],
        "check_placement_demoted": [],
        "check_placement_not_determined": [],
        "check_placement_clean": [],
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

    # ---- The placer's own violation COUNT, not a warning ----------------
    # The legalizer markers above are the escalation loop's condensed verdict.
    # They are emitted only by that loop. `check_placement` is also run at the
    # FINAL sites — after spare insertion, after ECO repair, in the ship
    # convergence loop — and a non-zero count there was printed as a WARN and
    # read by nobody. It is the placer refusing the design; refuse on it.
    cpv = _check_placement_verdicts(project)
    summary["check_placement_violations"] = cpv["violations"]
    summary["check_placement_demoted"] = cpv["demoted"]
    summary["check_placement_not_determined"] = cpv["not_determined"]
    summary["check_placement_clean"] = cpv["clean"]

    for v in cpv["violations"]:
        findings.append({
            "severity": "FAIL", "rule": "CHECK_PLACEMENT_VIOLATIONS",
            "message": (
                f"the placer's own `check_placement` returned "
                f"{v['count']} violation(s) at site {v['scope']} "
                f"({v['log']}). That is OpenROAD's own count of overlapping, "
                f"off-site or padding-violating instances; a non-zero count "
                f"is what DPL-33 is raised for. The DEF status-token checks "
                f"above cannot see it — an overlapping instance still carries "
                f"`+ PLACED ( x y ) N`."
                + (f" tool said: {v['tool_evidence']}"
                   if v["tool_evidence"] else "")),
        })
        verdict, rc = "FAIL", 1

    for d in cpv["demoted"]:
        n = _cp_count_from_evidence(d["tool_evidence"])
        findings.append({
            "severity": "FAIL", "rule": "CHECK_PLACEMENT_DEMOTED_TO_WARNING",
            "message": (
                f"`{d['marker']}` in {d['log']}: the placer raised DPL-33 and "
                f"the caller caught it and printed it as a warning, so the "
                f"violation count was discarded and the tool exited 0. "
                + (f"the tool's own count for this call is {n}. "
                   if n is not None else
                   "the tool's own count for this call is NOT DETERMINED from "
                   "this log — the abort path does not state a total. ")
                + f"verbatim: {d['line']!r}."
                + (f" tool said: {d['tool_evidence']}"
                   if d["tool_evidence"] else "")),
        })
        verdict, rc = "FAIL", 1

    for nd in cpv["not_determined"]:
        findings.append({
            "severity": "FAIL", "rule": "CHECK_PLACEMENT_NOT_DETERMINED",
            "message": (
                f"`check_placement` was invoked at site {nd['scope']} "
                f"({nd['log']}) and did not return a verdict: "
                f"{nd['detail'] or 'no detail recorded'}. Placement legality "
                f"is therefore unknown for this run, which is not a pass."),
        })
        verdict, rc = "FAIL", 1

    if not (cpv["violations"] or cpv["demoted"] or cpv["not_determined"]):
        if cpv["clean"]:
            findings.append({
                "severity": "INFO", "rule": "CHECK_PLACEMENT_CLEAN",
                "message": (
                    "the placer's own `check_placement` returned 0 violations "
                    "at: "
                    + ", ".join(f"{c['scope']} ({c['log']})"
                                for c in cpv["clean"])),
            })
        else:
            findings.append({
                "severity": "INFO", "rule": "CHECK_PLACEMENT_VERDICT_ABSENT",
                "message": (
                    "no `CHECK_PLACEMENT_*` marker in the "
                    f"{len(cpv['logs_scanned'])} scanned log(s) — this run "
                    "records no final `check_placement` count, so the checks "
                    "above stand alone. Absence is stated, not scored as a "
                    "pass."),
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
        "legalizer_failed_markers": summary.get("legalizer_failed_markers", []),
        "legalizer_ok_markers": summary.get("legalizer_ok_markers", []),
        "check_placement_violations": summary.get(
            "check_placement_violations", []),
        "check_placement_demoted": summary.get("check_placement_demoted", []),
        "check_placement_not_determined": summary.get(
            "check_placement_not_determined", []),
        "check_placement_clean": summary.get("check_placement_clean", []),
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
