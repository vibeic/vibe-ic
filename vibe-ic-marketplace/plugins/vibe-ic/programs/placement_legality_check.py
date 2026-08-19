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
  4. THE PLACER'S OWN LEGALITY VERDICT. Checks 1-3 read the DEF status
     TOKEN, and that token is written for an overlapping or off-site
     instance exactly as it is for a legal one — so no amount of DEF
     parsing can decide legality. OpenROAD's `check_placement` is the
     verdict that can: it RETURNS the violation count, and without
     `-no_abort` a non-zero count raises DPL-33 rather than returning, so
     "an illegal placement can never be mistaken for a legal one by a
     caller that ignores the result" (the tool's own words, `info body
     check_placement`). The runner records that verdict at every site it
     asks — the legalization ladder (`<SITE>_LEGALIZE_OK` /
     `<SITE>_LEGALIZE_FAILED`) and, with the count, after spare
     insertion / in the ECO repair / twice in the ship-time repair
     (`<SITE>_CHECK_PLACEMENT_VIOLATIONS <n>`). This gate refuses on a
     non-zero count and quotes it. A count that could not be obtained is
     recorded as NOT_DETERMINED and refused too — it is reached only via a
     call that threw, so it means "not clean, size unknown", never zero.
     A site asked repeatedly (the ship-time loop asks once per pass) is
     judged on its LAST reading — the state it left behind — so a loop
     that converged is not called illegal; an earlier non-zero that a
     later pass cleared is DISCLOSED rather than scored or dropped.

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
  * a derivable placement density must be in (0, 100]%.
No PDK/IC/tool-specific threshold is invented.

Verdicts
--------
* PASS  (rc=0) — placed.def parses; COMPONENTS > 0; declared count ==
                 parsed count; zero UNPLACED instances; the placer
                 reported no violation and no legalization failure; any
                 derivable density in (0, 100]%.
* FAIL  (rc=1) — placed.def absent / empty / unparseable, OR COMPONENTS
                 missing/zero, OR declared-vs-parsed count mismatch, OR
                 >= 1 UNPLACED instance, OR the placer reported a NON-ZERO
                 `check_placement` violation count (or a count it could
                 not determine) at any site, OR a `*_LEGALIZE_FAILED`
                 marker, OR a derivable density out of (0, 100]%.
                 (Step 17's precondition — placement was run — means an
                 absent placed.def is a real failure, never a vacuous
                 pass.)
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
# `placement_legality_check` and never read it.
_LEGALIZE_FAILED_SUFFIX = "_LEGALIZE_FAILED"
_LEGALIZE_OK_SUFFIX = "_LEGALIZE_OK"
_LEGALIZE_MARKER_RE = re.compile(
    r"\b([A-Z0-9_]+_LEGALIZE_(?:OK|FAILED))\b")


def _iter_pnr_log_lines(project: Path):
    """Yield (log_name, line) for every line of every PnR log.

    One traversal shared by every log-derived check below, so the marker read
    and the violation-count read can never disagree about which files they saw.
    """
    pnr_dir = project / "phase3" / "stage3" / "pnr"
    if not pnr_dir.is_dir():
        return
    for log in sorted(pnr_dir.rglob("*.log")):
        try:
            with log.open(errors="replace") as fh:
                for line in fh:
                    yield log.name, line
        except OSError:
            continue


# --- The placer's OWN violation COUNT --------------------------------------
# `check_placement` RETURNS the number of violations; without `-no_abort` a
# non-zero count raises DPL-33 instead. The runner asks for the verdict at
# several sites beyond the legalization ladder (after spare insertion, in the
# ECO repair, and twice in the ship-time repair). Each of those sites used to
# wrap the call in `catch` and print the EXCEPTION TEXT:
#
#     SPARE_CHECK_PLACEMENT_WARN: DPL-0033
#
# The count never left the call, and this gate — the one named for placement
# legality — did not read even the warning. MEASURED on a published project
# already in the corpus: its PnR log carries
# `[WARNING DPL-0006] Site aligned check failed (1).` followed by
# `[ERROR DPL-0033]` and that WARN line, and this gate returned PASS.
#
# The runner now emits the measured count at every one of those sites:
#     <SITE>_CHECK_PLACEMENT_VIOLATIONS <n>     n = integer, or NOT_DETERMINED
#     <SITE>_CHECK_PLACEMENT_PASS               n == 0
#     <SITE>_CHECK_PLACEMENT_WARN: ...          n != 0 (the placer refused)
#
# A non-zero count is a FAIL and is quoted. NOT_DETERMINED is reached only
# through a call that THREW, i.e. the placer did not return clean and the size
# of the violation is unknown — that is also a FAIL, stated as NOT DETERMINED
# rather than guessed as zero. A bare `_WARN` with no count line is a log from
# a runner that predates the count and is read the same way.
#
# chip-AGNOSTIC: the runner's own marker grammar; no chip, PDK or tool literal.
_CP_VIOLATIONS_RE = re.compile(
    r"\b([A-Z0-9_]+?)_CHECK_PLACEMENT_VIOLATIONS\s+(\d+|NOT_DETERMINED)\b")
_CP_WARN_RE = re.compile(
    r"\b([A-Z0-9_]+?)_CHECK_PLACEMENT_WARN\b\s*:?[ \t]*(.*)")
_CP_PASS_RE = re.compile(r"\b([A-Z0-9_]+?)_CHECK_PLACEMENT_PASS\b")
_COUNT_NOT_DETERMINED = "NOT_DETERMINED"


def _check_placement_verdicts(lines) -> dict:
    """Return {site: {"count", "worst", "detail"}} from the PnR log lines.

    A site is asked more than once — the ship-time convergence loop asks once
    per pass — so a site has a SEQUENCE of readings, and the two useful facts
    about that sequence are different questions:

    * ``count``  the LAST reading. That is the state this site left behind and
                 it is what the verdict keys on. A loop whose first pass had 3
                 violations and whose last pass has 0 converged; calling that
                 illegal would be a false alarm about a placement that is legal.
    * ``worst``  the first NON-ZERO reading, when a later one cleared it. It is
                 not scored, and it is not dropped either — it is DISCLOSED, so
                 "the placer objected and the next pass fixed it" never reads
                 the same as "the placer never objected".

    Both are the decimal string the placer returned, or NOT_DETERMINED. Never
    fabricates a count: a site seen only through a bare WARN (a log from a
    runner that predates the count) reads NOT_DETERMINED, which the caller
    treats as illegal-with-unknown-size — never as zero.
    """
    sites: dict = {}

    def _rec(site):
        return sites.setdefault(
            site, {"count": None, "worst": None, "detail": "",
                   "readings": 0})

    for _log, line in lines:
        for m in _CP_VIOLATIONS_RE.finditer(line):
            rec = _rec(m.group(1))
            rec["count"] = m.group(2)
            rec["readings"] += 1
            if m.group(2) != "0" and rec["worst"] is None:
                rec["worst"] = m.group(2)
        for m in _CP_PASS_RE.finditer(line):
            rec = _rec(m.group(1))
            # The PASS line accompanies its own VIOLATIONS 0 line; it is only a
            # READING of its own for a log that carries no count at all.
            if rec["readings"] == 0:
                rec["count"] = "0"
        for m in _CP_WARN_RE.finditer(line):
            site, detail = m.group(1), m.group(2).strip()
            rec = _rec(site)
            # Likewise: the WARN accompanies its own count line. It becomes the
            # reading itself only in a log with no count line for this site.
            if rec["readings"] == 0:
                rec["count"] = _COUNT_NOT_DETERMINED
                if rec["worst"] is None:
                    rec["worst"] = _COUNT_NOT_DETERMINED
            if detail and not rec["detail"]:
                rec["detail"] = detail

    for rec in sites.values():
        if rec["count"] is None:
            rec["count"] = _COUNT_NOT_DETERMINED
        rec.pop("readings", None)
    return sites


def _count_is_illegal(count: str) -> bool:
    """True unless the placer returned a measured ZERO violations."""
    return count != "0"


def _legalizer_markers(lines) -> tuple[List[str], List[str]]:
    """Return (failed_markers, ok_markers) found in the PnR logs.

    Chip-AGNOSTIC: the markers are the runner's own structural output, not a
    chip, PDK or library literal.
    """
    failed: List[str] = []
    ok: List[str] = []
    for _log, line in lines:
        for m in _LEGALIZE_MARKER_RE.finditer(line):
            tok = m.group(1)
            if tok.endswith(_LEGALIZE_FAILED_SUFFIX):
                if tok not in failed:
                    failed.append(tok)
            elif tok.endswith(_LEGALIZE_OK_SUFFIX):
                if tok not in ok:
                    ok.append(tok)
    return failed, ok


def inspect(project: Path):
    """Return (verdict, rc, findings, summary)."""
    findings: List[dict] = []
    summary = {
        "placed_def": _PLACED_DEF_REL,
        "legalizer_failed_markers": [],
        "legalizer_ok_markers": [],
        "check_placement_sites": {},
        "check_placement_violations": None,
        "check_placement_recovered": {},
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
    log_lines = list(_iter_pnr_log_lines(project))
    failed_markers, ok_markers = _legalizer_markers(log_lines)
    summary["legalizer_failed_markers"] = failed_markers
    summary["legalizer_ok_markers"] = ok_markers

    # (a) The COUNT. `check_placement` returns the number of violations and
    #     the runner records it at every site it asks. A non-zero count is the
    #     placer stating that this placement is illegal; it is a FAIL and the
    #     number is quoted. This is the reading that catches the sites OUTSIDE
    #     the legalization ladder, where a DPL-0033 abort used to be demoted to
    #     a WARN line no gate read.
    cp_sites = _check_placement_verdicts(log_lines)
    summary["check_placement_sites"] = {
        s: r["count"] for s, r in sorted(cp_sites.items())}
    illegal = {s: r for s, r in sorted(cp_sites.items())
               if _count_is_illegal(r["count"])}
    if illegal:
        measured = [int(r["count"]) for r in illegal.values()
                    if r["count"].isdigit()]
        summary["check_placement_violations"] = (
            sum(measured) if len(measured) == len(illegal)
            else _COUNT_NOT_DETERMINED)
        quoted = "; ".join(
            f"{s}={r['count']}" + (f" ({r['detail']})" if r["detail"] else "")
            for s, r in illegal.items())
        findings.append({
            "severity": "FAIL", "rule": "PLACER_REPORTED_VIOLATIONS",
            "message": (
                f"the placer's own `check_placement` reported a NON-ZERO "
                f"violation count in this run: {quoted}. "
                f"`check_placement` returns the violation count and, without "
                f"`-no_abort`, raises DPL-33 on a non-zero one precisely so an "
                f"illegal placement cannot be mistaken for a legal one by a "
                f"caller that ignores the result. That verdict is the "
                f"legality of this design; the DEF checks above report "
                f"{placed_n} placed / {unplaced_n} unplaced and are correct "
                f"about the file they read, but a `+ PLACED ( x y )` token is "
                f"written for an overlapping or off-site instance too, so it "
                f"cannot express this failure. "
                f"({_COUNT_NOT_DETERMINED} means the placer did not return a "
                f"clean verdict and the size of the violation could not be "
                f"obtained — it is not zero and is not reported as zero.)"),
        })
        verdict, rc = "FAIL", 1
    elif cp_sites:
        summary["check_placement_violations"] = 0
        findings.append({
            "severity": "INFO", "rule": "PLACER_REPORTED_ZERO_VIOLATIONS",
            "message": (
                "the placer's own `check_placement` returned 0 violations at "
                "every site it was asked: "
                + ", ".join(f"{s}={r['count']}"
                            for s, r in sorted(cp_sites.items()))),
        })

    # A violation the NEXT pass cleared is not scored — the design that site
    # left behind is legal — but it is not dropped either. Disclosed, so
    # "objected once and was fixed" never reads as "never objected".
    recovered = {s: r["worst"] for s, r in sorted(cp_sites.items())
                 if r["worst"] is not None and not _count_is_illegal(r["count"])}
    if recovered:
        summary["check_placement_recovered"] = recovered
        findings.append({
            "severity": "INFO", "rule": "PLACER_VIOLATIONS_RECOVERED",
            "message": (
                "the placer reported violations at "
                + ", ".join(f"{s}={c}" for s, c in recovered.items())
                + " and a later pass at the same site returned 0. Not scored "
                  "— the state the site left behind is legal — but recorded, "
                  "because a run that had to converge is not the same as a "
                  "run that never objected."),
        })

    # (b) The legalization LADDER's own terminal verdict.
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
    elif not cp_sites:
        findings.append({
            "severity": "INFO", "rule": "LEGALIZER_VERDICT_ABSENT",
            "message": (
                "no `*_LEGALIZE_OK` / `*_LEGALIZE_FAILED` marker and no "
                "`*_CHECK_PLACEMENT_VIOLATIONS` line in the PnR log — this "
                "run records no placer legality verdict at all, so the "
                "status-token checks above stand alone. Stated, not "
                "fabricated as a pass, and NOT counted as a legal placement."),
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
        "check_placement_sites": summary.get("check_placement_sites", {}),
        "check_placement_violations":
            summary.get("check_placement_violations"),
        "check_placement_recovered":
            summary.get("check_placement_recovered", {}),
        "legalizer_failed_markers": summary.get("legalizer_failed_markers", []),
        "legalizer_ok_markers": summary.get("legalizer_ok_markers", []),
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
    if summary.get("check_placement_sites"):
        print("  check_placement violations: "
              + ", ".join(f"{s}={c}" for s, c
                          in summary["check_placement_sites"].items()))
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
            "check_placement_sites": {}, "check_placement_violations": None,
            "check_placement_recovered": {},
            "legalizer_failed_markers": [], "legalizer_ok_markers": [],
        }
        _emit(args, project, "WAIVED", summary, findings, waiver)
        return 0

    verdict, rc, findings, summary = inspect(project)
    _emit(args, project, verdict, summary, findings, waiver)
    return rc


if __name__ == "__main__":
    sys.exit(main())
