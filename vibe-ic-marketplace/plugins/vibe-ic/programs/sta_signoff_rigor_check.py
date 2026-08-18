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
from pathlib import Path
from typing import Dict, List, Optional

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
        # bounded look-ahead: the path's own slack line follows shortly after
        # its Endpoint line, well before the NEXT "Startpoint:" block begins.
        window = report_text[m.end():m.end() + 2000]
        next_start = window.find("Startpoint:")
        scope = window if next_start == -1 else window[:next_start]
        if _SLACK_VIOLATED_RE.search(scope):
            found.append(m.group(0).strip()[:160])
    return found


def _find_report(target: Path) -> Optional[Path]:
    """Resolve the sign-off STA report. Accepts a file or a directory.

    Preference order (most-rigorous sign-off basis first):
      1. the MULTI-CORNER OCV report (``sta_mcorner_ocv*.rpt``) — SETUP @ ss +
         HOLD @ ff, flat-OCV + recovery/removal/MPW. When present this is the
         report the gate evaluates, so a run is judged on its multi-corner
         sign-off, not the single (nom) corner.
      2. the single-corner SPEF-based report (``post_route_timing.rpt`` /
         ``sta_spef_based*.rpt``).
      3. any remaining post_route/sta report."""
    if target.is_file():
        return target
    if target.is_dir():
        for pat in ("sta_mcorner_ocv*.rpt", "*mcorner_ocv*.rpt",
                    "post_route_timing.rpt", "sta_spef_based*.rpt",
                    "*spef*sta*.rpt", "sta.rpt", "*sta*.rpt"):
            hits = sorted(target.rglob(pat))
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
        "missing": missing,
        "ocv_scope": ocv_scope,
    }


def check(target: Path) -> Dict[str, object]:
    rpt = _find_report(target)
    if rpt is None:
        return {"verdict": "IO_ERROR",
                "error": f"no sign-off STA report found at {target}"}
    try:
        text = rpt.read_text(errors="replace")
    except OSError as e:
        return {"verdict": "IO_ERROR", "error": f"cannot read {rpt}: {e}"}
    res = evaluate(text)
    res["report"] = str(rpt)
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
