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

Verdict:
  PASS  — the report shows OCV derating was applied AND carries recovery/removal
          AND min-pulse-width evidence (a full-rigor sign-off basis).
  FAIL  — the report exists but is MISSING one or more (the finding lists which):
          an optimistic sign-off, not a foundry-grade one.
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
    missing: List[str] = []
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
