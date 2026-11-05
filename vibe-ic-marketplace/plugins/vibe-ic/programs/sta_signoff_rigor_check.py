#!/usr/bin/env python3
"""sta_signoff_rigor_check.py — sign-off STA rigor gate for tapeout sign-off.

The tapeout-signoff survey found the SPEF-based STA (the sign-off-grade timing
basis, `phase3_one_shot_runner._emit_spef_sta`) was signed off with NO on-chip
variation (OCV) margin and WITHOUT the recovery/removal + min-pulse-width check
types a foundry sign-off requires. A setup/hold `slack (MET)` report alone is an
OPTIMISTIC sign-off: it omits process variation derating and the async-reset
de-assert (recovery/removal) and runt-pulse (min-pulse-width) arcs.

v1.2.x wired those into the SPEF STA TCL:
  * `set_timing_derate -early 0.95 -late 1.05` (a conservative GENERIC flat-OCV
    margin) + an `OCV_DERATE_APPLIED early=.. late=.. flat-OCV` marker line, and
  * `report_check_types -recovery -removal -max_slew -min_pulse_width`.

This gate verifies a sign-off STA report actually CARRIES that rigor, so a run
cannot claim "timing signed off" on the pre-fix optimistic basis.

ORGANIC #540 added a FOURTH dimension: WORST-PATH EVIDENCE. This gate used to
ask only whether the report carried a derate and the check types — never whether
it carried the PATH behind its own governing slack. It therefore PASSed reports
whose `report_checks` had silently errored inside a `catch`, which over the
tracked corpus was every single multi-corner OCV report (0 of 9 carried a path
dump, against 51 of 106 for the other STA reports). A slack with no path is a
verdict that reads the same whether or not the thing behind it was examined,
which is precisely what this gate exists to stop.

COVERAGE vs CONTENT (v1.10.3) added a FIFTH dimension: earlier versions only
checked that the recovery/removal/min-pulse-width ANALYSIS ran (the marker
line), never whether it actually PASSED. A real violation sitting in
report_check_types' own output — e.g. a genuine min-pulse-width table row
`<pin>  <required>  <actual>  <slack> (VIOLATED)`, or a recovery/removal path
ending `slack (VIOLATED)` on an endpoint marked "(recovery check against ...)"
/ "(removal check against ...)" — is real evidence the design FAILS this
dimension, and a gate that only checks coverage would print PASS over it.
That is exactly the "checks that lie" shape §4.05 forbids: measuring that the
tool ran, not what it found.

Verdict:
  PASS  — the report shows OCV derating was applied, carries recovery/removal
          AND min-pulse-width evidence (coverage), accounts for its own worst
          slack with a path (ORGANIC #540), AND none of the recovery/removal/
          min-pulse-width sections contains an actual (VIOLATED) row/path
          (v1.10.3 content) — a full-rigor sign-off basis.
  FAIL  — the report exists but either (a) is MISSING one or more of the
          coverage/path dimensions, or (b) HAS a real (VIOLATED) recovery/
          removal/min-pulse-width finding (the finding lists which either
          way): an optimistic sign-off, not a foundry-grade one.
  rc=2  — the report path is absent/unreadable (missing-evidence IO error).

AOCV/POCV vs flat-OCV (P1, implemented):
  The gate now DISTINGUISHES the OCV basis and reports `ocv_mode`:
    * "aocv" — a distance/depth AOCV/POCV derate table was ingested (the runner
      emits `AOCV_TABLE_APPLIED file=<name>` after a successful `read_aocv`). The
      RICHER basis.
    * "flat" — the generic flat-OCV ±5% margin (`set_timing_derate` /
      `OCV_DERATE_APPLIED`). The HONEST real basis on the sky130 open PDK, which
      ships NO AOCV/POCV table (and the open OpenSTA build here has no read_aocv).
  BOTH pass the rigor gate — either is a valid on-chip-variation derate; AOCV is
  simply richer. Only the ABSENCE of any derate fails the OCV dimension.

Honest scope (disclosed, not fabricated):
  * When no AOCV/POCV table exists (sky130 open PDK), flat-OCV stays the real
    basis and `ocv_mode` says so — the gate never claims AOCV it did not apply.
  * SI-aware delta-delay is a separate sign-off dimension (si_signoff_timing_aware
    now emits a genuine PASS/FAIL/ADVISORY delta-delay verdict); this gate does
    not cover crosstalk.

§4.05 (no vacuous pass): a report that never applied a derate, or that omits the
recovery/removal / min-pulse-width sections, is NOT a full sign-off — it FAILs
here even if its setup/hold slack is MET. Absent report → rc=2, never PASS.

chip-AGNOSTIC: reads only generic OpenSTA report tokens; no design knowledge.

Usage:
    python3 sta_signoff_rigor_check.py <sta_report_or_dir> [--json OUT]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set
# The plugin's programs are loaded BY PATH, not as a package (#2104), so a
# sibling only resolves once this directory is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The OCV-derate marker line emitted by _emit_spef_sta (native-Tcl file append).
_OCV_MARKER_RE = re.compile(
    r"OCV_DERATE_APPLIED\s+early=([0-9.]+)\s+late=([0-9.]+)", re.IGNORECASE)
# A raw `set_timing_derate` echo (some OpenSTA builds echo the command) is also
# accepted as derate evidence.
_DERATE_CMD_RE = re.compile(r"set_timing_derate\b", re.IGNORECASE)
# AOCV/POCV table evidence: the runner emits `AOCV_TABLE_APPLIED file=<name>`
# when a distance/depth-based derate table was successfully ingested
# (read_aocv), a RICHER on-chip-variation basis than the flat ±5% margin. A raw
# `read_aocv` echo is also accepted. Its presence upgrades ocv_mode to "aocv"
# (still PASS — both are valid OCV bases; AOCV is just richer).
_AOCV_MARKER_RE = re.compile(
    r"AOCV_TABLE_APPLIED\s+file=(\S+)", re.IGNORECASE)
_AOCV_CMD_RE = re.compile(r"\bread_aocv\b", re.IGNORECASE)
# report_check_types section markers. OpenSTA prints per-check-type sections; a
# recovery/removal report contains the words, and min-pulse-width prints a
# "min_pulse_width" / "min pulse width" section header or a "Min Pulse Width"
# check line.
_RECOVERY_RE = re.compile(r"\brecovery\b", re.IGNORECASE)
_REMOVAL_RE = re.compile(r"\bremoval\b", re.IGNORECASE)
_MPW_RE = re.compile(r"min[_ ]pulse[_ ]width", re.IGNORECASE)
# AUTHORITATIVE emitter marker. LIVE-VALIDATED: OpenSTA 3.1.0's
# `report_check_types` output uses "Group Slack" / "Required Width" tables and
# never prints the literal check-type words — so the plain-word regexes above
# both MISS a real sign-off (false FAIL) and can FALSE-PASS on an incidental
# "recovery check against …" path line. The emitter (phase3_one_shot_runner
# _report_check_types_tcl) writes this marker ONLY when report_check_types
# actually ran, naming the check types performed. When present it is the trusted
# signal; the plain-word regexes remain a fallback for other tools / fixtures.
_CHECK_TYPES_MARKER_RE = re.compile(
    r"SIGNOFF_CHECK_TYPES_REPORTED\s+(?P<types>.+)", re.IGNORECASE)

# ORGANIC #540 — WORST-PATH EVIDENCE. `report_worst_slack` prints a NUMBER;
# only `report_checks` prints the startpoint/endpoint/arrival breakdown that
# says WHAT produced it. This gate could not tell those apart: it asked whether
# the report carried a DERATE and the CHECK TYPES, never whether it carried the
# path behind its own governing slack. So a report whose `report_checks` had
# silently errored — which, measured over the tracked corpus, was 9 of 9
# `sta_mcorner_ocv*.rpt` — was byte-indistinguishable to this gate from one that
# dumped its full critical path, and PASSED. The gate enforcing sign-off rigour
# was blind to the one thing that would make its input auditable.
#
# Evidence, most authoritative first:
#   1. the emitter marker (tool-version-independent, and the ONLY signal that
#      distinguishes "queried and this design has no such path" from "never
#      queried" — an empty path table and an errored one look identical),
#   2. an explicit FAILED marker naming the tool's own reason — that is
#      NEGATIVE evidence and must never be read as absence of a problem,
#   3. fallback: a literal path dump in the body, which is how a report from a
#      pre-marker emitter or another tool still counts (`_emit_spef_sta` calls a
#      bare `report_checks` and has always produced one).
_WORST_PATHS_MARKER_RE = re.compile(
    r"SIGNOFF_WORST_PATHS_REPORTED\s+path_delay=(\S+)", re.IGNORECASE)
_WORST_PATHS_FAILED_RE = re.compile(
    r"SIGNOFF_WORST_PATHS_FAILED\s+path_delay=(\S+)\s+reason=(.*)",
    re.IGNORECASE)
# A real OpenSTA/OpenROAD path dump. chip-AGNOSTIC: universal report structure.
_PATH_DUMP_RE = re.compile(
    r"^\s*(?:Startpoint|Endpoint)\s*:|data arrival time", re.IGNORECASE | re.M)

# CONTENT (not just coverage) — a genuine violation inside report_check_types'
# own output, distinct from an ordinary setup/hold PATH violation (which also
# prints "slack (VIOLATED)" but is a different gate's concern entirely) AND
# distinct from max_slew / max_capacitance / max_fanout table violations
# (real findings too, but OUT OF SCOPE for this gate's declared dimensions —
# they are DRV limits covered elsewhere; folding them in here would silently
# widen this gate's contract and retroactively flip unrelated runs' verdicts,
# exactly the kind of scope-creep a repo-gatekeeper should not slip in
# unannounced). Scoped strictly to this gate's own 3 declared dimensions:
# recovery, removal, min_pulse_width.
#
# min_pulse_width prints a flat pin-based TABLE, uniquely identified by its
# two-Width header (LIVE-VALIDATED against real OpenSTA 3.1.0 output; distinct
# from max_slew's "Limit Slew Slack" and max_capacitance's "Limit Cap Slack"
# headers, which do NOT say "Width"):
#     Required  Actual
#Pin                                    Width   Width   Slack
#------------------------------------------------------------
#u_otp.u_otp/PRD (high)                200.00  100.01  -99.99 (VIOLATED)
_MPW_TABLE_HEADER_RE = re.compile(r"Pin\s+Width\s+Width\s+Slack", re.IGNORECASE)

# recovery / removal instead print a full PATH report (Startpoint/Endpoint/...
# slack (MET|VIOLATED)), same shape as an ordinary setup/hold path, but the
# Endpoint line names the check: "(recovery check against ...)" / "(removal
# check against ...)". A violation is real when that marker is followed,
# within the same path block, by "slack (VIOLATED)".
_RECOVERY_REMOVAL_ENDPOINT_RE = re.compile(
    r"\((?:recovery|removal) check against[^)\n]*\)", re.IGNORECASE)
_SLACK_VIOLATED_RE = re.compile(r"slack\s*\(VIOLATED\)", re.IGNORECASE)


def _check_types_violations(report_text: str) -> List[str]:
    """Real (VIOLATED) findings inside report_check_types' own output,
    scoped to this gate's 3 declared dimensions (recovery / removal /
    min_pulse_width — NOT max_slew / max_capacitance / max_fanout).

    Chip-AGNOSTIC: no design/pin names are assumed — the exact violating pin
    or endpoint description is read straight out of the report and quoted
    back verbatim (truncated) so the finding is self-evidencing.
    """
    found: List[str] = []
    for hm in _MPW_TABLE_HEADER_RE.finditer(report_text):
        after = report_text[hm.end():]
        nl = after.find("\n")  # skip the "----" separator line under the header
        block_start = after[nl + 1:] if nl != -1 else after
        end = len(block_start)
        for stopper in ("\n\n", "SIGNOFF_CHECK_TYPES_REPORTED"):
            idx = block_start.find(stopper)
            if idx != -1:
                end = min(end, idx)
        for line in block_start[:end].splitlines():
            if "(VIOLATED)" in line.upper():
                found.append(line.strip()[:160])
    for m in _RECOVERY_REMOVAL_ENDPOINT_RE.finditer(report_text):
        # BOUNDED BY THE NEXT PATH, NOT BY A BYTE COUNT (2026-08-22).
        #
        # This used to take a 2000-character window first and look for the next
        # "Startpoint:" inside it. The structural bound is correct and the byte
        # window was redundant AND lossy: in OpenSTA output the `slack
        # (VIOLATED)` line comes AFTER the whole path detail, so on a long path
        # it sits past 2000 characters and the violation was silently dropped.
        #
        # MEASURED on a synthetic recovery path, slack line unchanged:
        #     10 detail lines   slack  481 bytes after the Endpoint  -> reported
        #     60 detail lines   slack 2681 bytes after               -> MISSED
        #    200 detail lines   slack 8941 bytes after               -> MISSED
        #
        # A real sign-off path routinely exceeds 45 lines, so this reported a
        # clean result over a report containing a genuine recovery/removal
        # violation — a false clean, which is the one direction a sign-off
        # rigor check must never fail in.
        #
        # The MPW loop above already does this correctly: it bounds by its own
        # structural stoppers and uses no byte window at all. Same rule here.
        rest = report_text[m.end():]
        next_start = rest.find("Startpoint:")
        scope = rest if next_start == -1 else rest[:next_start]
        if _SLACK_VIOLATED_RE.search(scope):
            found.append(m.group(0).strip()[:160])
    return found


#: Actions in ``postroute_timing_repair_decision.json`` naming a post-route
#: repair arm the flow RAN and then DECLINED TO ADOPT. ``phase3_one_shot_runner``
#: says it in as many words — "The post-route repair outputs stay on disk under
#: their own names for debug; they are NOT adopted as the shipped artefacts" —
#: so that arm's ``sta_mcorner_ocv_postrepair.rpt`` sits beside the governing
#: ``sta_mcorner_ocv.rpt``, matches the SAME globs below, and NOTHING on disk
#: distinguishes the two except this record.
_NOT_ADOPTED_ACTIONS = frozenset({
    "timing_repair_reverted_regression",
    "timing_repair_blind_to_violation",
})

_DECISION_BASENAME = "postroute_timing_repair_decision.json"

# ---------------------------------------------------------------------------
# R-0915-154 — three stamps the phase-3 runner writes, READ HERE, because this
# is the program that decides whether a report is sign-off timing.
# ---------------------------------------------------------------------------
#: The in-session PnR STA (`pnr/sta.rpt`) states that its RC is unattested --
#: an estimate or an extraction, it does not say which. A report that says so
#: about itself is NEVER a sign-off source. This gate's fallback globs
#: (`sta.rpt`, `*sta*.rpt`) reached it whenever nothing richer existed: MEASURED
#: on the shipped globs, a tree holding only `phase3/stage3/pnr/sta.rpt`
#: resolved to it and was graded as sign-off.
_PNR_SESSION_UNVERIFIED_RE = re.compile(
    r"^[ \t]*(?:#[ \t]*)?STA_PARASITICS_PROVENANCE[ \t]*:[ \t]*"
    r"PNR_SESSION_UNVERIFIED[ \t]*$", re.MULTILINE)
#: `post_route_timing.rpt` written as a COPY of another basis
#: (`# STA_ALIAS_BASIS: <file>`, when the single-corner SPEF STA refused). A copy
#: is judged AS that basis and says so -- it is not a second, independent
#: sign-off STA.
_ALIAS_BASIS_RE = re.compile(
    r"^[ \t]*(?:#[ \t]*)?STA_ALIAS_BASIS[ \t]*:[ \t]*(sta(?:_[a-z0-9]+)*\.rpt)[ \t]*$",
    re.MULTILINE)
#: A path whose setup corner could not be bound to a loaded Liberty. It has no
#: attributable corner, so it is never credited as corner-attributed timing.
_CORNER_BINDING_REFUSED_RE = re.compile(
    r"^[ \t]*(?:#[ \t]*)?STA_CORNER_BINDING_REFUSED[ \t]*:[ \t]*(\S+)", re.MULTILINE)


def _is_unverified_session_report(path: Path) -> bool:
    try:
        return bool(_PNR_SESSION_UNVERIFIED_RE.search(
            path.read_text(errors="replace")))
    except OSError:
        return False


def _unverified_session_reports(target: Path) -> Set[Path]:
    """Resolved candidates that declare `PNR_SESSION_UNVERIFIED` parasitics."""
    if not target.is_dir():
        return set()
    return {p.resolve() for p in target.rglob("*.rpt")
            if p.is_file() and _is_unverified_session_report(p)}


def _non_adopted_reports(target: Path) -> Set[Path]:
    """Resolved STA reports belonging to a repair arm the flow did not adopt.

    Read from the flow's OWN record rather than inferred from a filename: the
    decision carries ``repair_after.report``, the path ``_measure_postrepair_
    mcorner_ocv`` actually wrote, so a rename in the runner cannot silently empty
    this set the way a hard-coded ``*_postrepair*`` pattern would.

    An unreadable or absent record excludes NOTHING. That is the safe direction
    here: this set only ever removes candidates, so failing to read it degrades
    to today's behaviour rather than to a refusal on a run that never repaired.
    """
    out: Set[Path] = set()
    if not target.is_dir():
        return out
    for dec in target.rglob(_DECISION_BASENAME):
        try:
            rec = json.loads(dec.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("action") not in _NOT_ADOPTED_ACTIONS:
            continue
        after = rec.get("repair_after")
        rel = after.get("report") if isinstance(after, dict) else None
        if not isinstance(rel, str) or not rel.strip():
            continue
        rel_p = PurePosixPath(rel.strip())
        # The record is written project-relative, and the gate may be pointed at
        # the project root or at any directory above it, so resolve against the
        # decision file's own ancestors instead of hard-coding the depth.
        for anc in [dec.parent, *dec.parents]:
            cand = anc / rel_p
            if cand.is_file():
                out.add(cand.resolve())
                break
    return out


def _find_report(target: Path,
                 excluded: Optional[Set[Path]] = None) -> Optional[Path]:
    """Resolve the sign-off STA report. Accepts a file or a directory.

    Preference order (most-rigorous sign-off basis first):
      1. the MULTI-CORNER OCV report (``sta_mcorner_ocv*.rpt``) — SETUP @ ss +
         HOLD @ ff, flat-OCV + recovery/removal/MPW. When present this is the
         report the gate evaluates, so a run is judged on its multi-corner
         sign-off, not the single (nom) corner.
      2. the single-corner SPEF-based report (``post_route_timing.rpt`` /
         ``sta_spef_based*.rpt``).
      3. any remaining post_route/sta report.

    A report from a repair arm the flow did NOT adopt is excluded outright, the
    same doctrine ``lvs_tapeout_signoff_check`` applies to an in-tree snapshot.
    Ordering cannot be relied on to do this: ``sta_mcorner_ocv.rpt`` only beats
    ``sta_mcorner_ocv_postrepair.rpt`` because ``.`` sorts under ``_``, and
    ``rglob`` sorts whole PATHS, so a discarded arm one directory over wins on
    the directory component alone. When the discarded arm is the only candidate
    this returns ``None`` rather than letting it be read as sign-off.
    """
    if target.is_file():
        return target
    if target.is_dir():
        if excluded is None:
            excluded = _non_adopted_reports(target)
        for pat in ("sta_mcorner_ocv*.rpt", "*mcorner_ocv*.rpt",
                    "post_route_timing.rpt", "sta_spef_based*.rpt",
                    "*spef*sta*.rpt", "sta.rpt", "*sta*.rpt"):
            hits = [p for p in sorted(target.rglob(pat))
                    if p.resolve() not in excluded]
            if hits:
                return hits[0]
    return None


def evaluate(report_text: str) -> Dict[str, object]:
    """Pure evaluator over a sign-off STA report body. Returns a verdict dict."""
    aocv_m = _AOCV_MARKER_RE.search(report_text)
    aocv = bool(aocv_m or _AOCV_CMD_RE.search(report_text))
    flat_ocv = bool(_OCV_MARKER_RE.search(report_text)
                    or _DERATE_CMD_RE.search(report_text))
    # SOME on-chip-variation derate must be present. AOCV/POCV (distance/depth
    # table) is richer than the flat ±5% margin, but either satisfies the gate.
    ocv = aocv or flat_ocv
    # AUTHORITATIVE marker first (tool-version-independent), plain words fallback.
    marker = _CHECK_TYPES_MARKER_RE.search(report_text)
    marker_types = (marker.group("types").lower() if marker else "")
    recovery = "recovery" in marker_types or bool(_RECOVERY_RE.search(report_text))
    removal = "removal" in marker_types or bool(_REMOVAL_RE.search(report_text))
    mpw = ("min_pulse_width" in marker_types or "min pulse width" in marker_types
           or bool(_MPW_RE.search(report_text)))
    # ORGANIC #540 — worst-path evidence behind the report's own slack.
    path_failures = [f"path_delay={m.group(1)}: {m.group(2).strip()}"
                     for m in _WORST_PATHS_FAILED_RE.finditer(report_text)]
    if _WORST_PATHS_MARKER_RE.search(report_text):
        path_source = "marker"
    elif _PATH_DUMP_RE.search(report_text):
        path_source = "path-dump"
    else:
        path_source = None
    # A pass that ERRORED is negative evidence, and it outranks a sibling pass
    # that succeeded: a report whose hold path dump died still cannot account
    # for its hold slack, so a partial report is not an evidenced one.
    worst_path_evidence = bool(path_source) and not path_failures

    missing: List[str] = []
    if not worst_path_evidence:
        if path_failures:
            missing.append(
                "worst-path evidence — the report's own path query FAILED and "
                "said so: " + "; ".join(path_failures))
        else:
            missing.append(
                "worst-path evidence (report_checks startpoint/endpoint/data "
                "arrival time, or the SIGNOFF_WORST_PATHS_REPORTED marker) — "
                "the report records a slack with nothing behind it")
    if not ocv:
        missing.append("OCV derating (set_timing_derate / OCV_DERATE_APPLIED / "
                       "read_aocv / AOCV_TABLE_APPLIED)")
    if not recovery:
        missing.append("recovery check (report_check_types -recovery)")
    if not removal:
        missing.append("removal check (report_check_types -removal)")
    if not mpw:
        missing.append("min-pulse-width check "
                       "(report_check_types -min_pulse_width)")
    corner_refused = [m.group(1) for m in
                      _CORNER_BINDING_REFUSED_RE.finditer(report_text)]
    if corner_refused:
        missing.append(
            f"corner attribution — {len(corner_refused)} reported path(s) carry "
            f"STA_CORNER_BINDING_REFUSED ({sorted(set(corner_refused))[0]}): a "
            f"path with no attributable corner is not corner-attributed "
            f"sign-off timing")
    violations = _check_types_violations(report_text)
    for v in violations:
        missing.append(f"real (VIOLATED) finding in report_check_types: {v}")
    passed = not missing
    if aocv:
        ocv_mode = "aocv"
        ocv_scope = ("AOCV/POCV distance/depth derate table applied "
                     "(richer than flat-OCV)")
    elif flat_ocv:
        ocv_mode = "flat"
        ocv_scope = ("flat-OCV (±5% generic margin; no AOCV/POCV table was "
                     "supplied — sky130 open PDK ships none, so flat-OCV is "
                     "the honest real basis. AOCV/POCV supersedes when present)")
    else:
        ocv_mode = None
        ocv_scope = "no OCV derate detected"
    return {
        "verdict": "PASS" if passed else "FAIL",
        "ocv_derate_applied": ocv,
        "ocv_mode": ocv_mode,               # "aocv" | "flat" | None
        "aocv_applied": aocv,
        "aocv_table": (aocv_m.group(1) if aocv_m else None),
        "recovery_checked": recovery,
        "removal_checked": removal,
        "min_pulse_width_checked": mpw,
        # ORGANIC #540 — is the slack in this report accountable to a path?
        "worst_path_evidence": worst_path_evidence,
        "worst_path_evidence_source": path_source,   # "marker"|"path-dump"|None
        "worst_path_query_failures": path_failures,
        "check_types_violations": violations,
        "corner_binding_refused": len(corner_refused),
        "missing": missing,
        "ocv_scope": ocv_scope,
    }


def check(target: Path) -> Dict[str, object]:
    if target.is_file() and _is_unverified_session_report(target):
        return {"verdict": "IO_ERROR",
                "error": (f"{target} declares STA_PARASITICS_PROVENANCE: "
                          "PNR_SESSION_UNVERIFIED — an in-session STA whose RC "
                          "is unattested is never a sign-off source (R-0915-154)"),
                "unverified_session_reports": [str(target)]}
    excluded = _non_adopted_reports(target)
    unverified = _unverified_session_reports(target)
    rpt = _find_report(target, excluded | unverified)
    if rpt is None and unverified:
        return {
            "verdict": "IO_ERROR",
            "error": (
                f"no sign-off STA report at {target}: the only candidate(s) "
                "declare STA_PARASITICS_PROVENANCE: PNR_SESSION_UNVERIFIED ("
                + ", ".join(sorted(p.name for p in unverified)) + "). An "
                "in-session STA whose RC is unattested is never a sign-off "
                "source, so this is NOT_MEASURED rather than a result "
                "(R-0915-154)."),
            "unverified_session_reports": sorted(str(p) for p in unverified)}
    if rpt is None:
        if excluded:
            return {
                "verdict": "IO_ERROR",
                "error": (
                    f"no ADOPTED sign-off STA report at {target}: every candidate "
                    "belongs to a post-route repair arm the flow declined to adopt "
                    "(" + ", ".join(sorted(p.name for p in excluded)) + "). A rigor "
                    "verdict computed on a discarded arm is not a sign-off verdict, "
                    "so this is NOT_MEASURED rather than a result."),
                "non_adopted_reports": sorted(str(p) for p in excluded)}
        return {"verdict": "IO_ERROR",
                "error": f"no sign-off STA report found at {target}"}
    try:
        text = rpt.read_text(errors="replace")
    except OSError as e:
        return {"verdict": "IO_ERROR", "error": f"cannot read {rpt}: {e}"}
    alias = _ALIAS_BASIS_RE.search(text)
    alias_note = None
    if alias:
        # JUDGED AS ITS BASIS. The basis is found by name under the target
        # (the alias and its basis live in different stage directories), never
        # the alias itself; when it is not reachable the copied bytes ARE the
        # basis's bytes, and the verdict is attributed to the basis by name.
        name = alias.group(1)
        roots = [target] if target.is_dir() else [rpt.parent]
        basis = next((b for r in roots for b in sorted(r.rglob(name))
                      if b.is_file() and b.resolve() != rpt.resolve()
                      and b.resolve() not in excluded), None)
        if basis is not None:
            try:
                text = basis.read_text(errors="replace")
            except OSError as e:
                return {"verdict": "IO_ERROR",
                        "error": f"{rpt} is a copy of {name}; cannot read {basis}: {e}"}
            alias_note = (f"{rpt.name} is a COPY (STA_ALIAS_BASIS) of "
                          f"{basis.name}; judged as that basis")
        else:
            alias_note = (f"{rpt.name} is a COPY (STA_ALIAS_BASIS) of {name}, "
                          f"which is not under {roots[0]}; judged on the copied "
                          f"content, attributed to {name}")
    res = evaluate(text)
    res["report"] = str(rpt)
    if alias:
        res["alias_of"] = alias.group(1)
        res["alias_basis_report"] = str(basis) if basis is not None else None
        res["alias_note"] = alias_note
    if excluded:
        res["non_adopted_reports_skipped"] = sorted(str(p) for p in excluded)
    if unverified:
        res["unverified_session_reports_skipped"] = sorted(
            str(p) for p in unverified)
    return res


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Sign-off STA rigor gate (OCV derate + recovery/removal + "
                    "min-pulse-width).")
    ap.add_argument("target", help="STA report file or a directory to search")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the verdict JSON to this path")
    ns = ap.parse_args(argv)
    res = check(Path(ns.target))
    out = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(out)
    print(out)
    if res["verdict"] == "IO_ERROR":
        return 2
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
