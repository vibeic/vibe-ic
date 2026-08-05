#!/usr/bin/env python3
"""
hold_corner_coverage_check.py — confirm hold is analysed at the FAST (FF)
corner, the worst-case corner for hold.

From `skills/hold-fix/SKILL.md` Step 1 + Step 6:
  "Run STA at the FF corner (fast process, high voltage, low temperature)."
  "Hold must be verified across all fast corners: FF, high voltage, low
   temperature (worst hold). ... If using MCMM, the hold analysis view must use
   the FF corner."

This is the narrow, hold-SPECIFIC corner rule — distinct from the broad PVT
presence audit in `corner_coverage_audit.py` (which only checks that SS/TT/FF
Liberty files exist somewhere in the tree). Here we verify that the LIBERTY /
operating-condition actually consumed by the HOLD analysis is a FAST corner.
A flow can have FF `.lib` files present (corner_coverage_audit PASS) yet still
read the SS/TT Liberty for its hold check — that is the real defect this gate
catches: hold analysed at the WRONG (non-FF) corner under-reports hold
violations and ships a hold-broken chip.

What it scans
-------------
A hold-analysis Tcl/SDC/log artefact (the file that drives the hold check).
It looks for the Liberty / operating-condition that the hold path consumes:
  * `read_liberty ...ff...lib`            (OpenSTA)
  * `report_checks -path_delay min ...`   (the hold-report invocation)
  * `set_operating_conditions ... ff...`  (MCMM hold view)
  * any explicit "hold corner = ff" / "min view = ff" assignment.

A process corner is FAST when its designator is `ff` / `fast_fast` / `fast`.
SS / TT (slow / typical) used for the hold (min) analysis is the FAIL.

HOW THE CORNER IS DECIDED (rewritten when this gate was first wired)
--------------------------------------------------------------------
The first version demanded that EVERY corner designator on EVERY
`read_liberty` line classify FF. Measured against the flow's own emitter, that
is wrong on correct work: `phase3_one_shot_runner._emit_mcorner_ocv_sta._pass`
writes the sign-off corner liberty and then interpolates `macro_libs_tcl` — one
`read_liberty` per HARD-MACRO liberty — into the same hold script, and the
runner deliberately narrows multi-corner macro libs to the TYPICAL ones. So any
design carrying a hard macro (SRAM, an analog A8 hardmacro, vendor IP) produced
`read_liberty …ff….lib` + `read_liberty …_tt_….lib` and was failed
`HOLD_NOT_AT_FF ['FF','TT']` for a hold sign-off that was in fact at FF. The
corpus hid this: the only two runs that retained the script belong to a
macro-free design.

The decision is now layered, strongest evidence first:

  1. DECLARED STANCE. `reports/phase3/mcorner_ocv_stance.json` records
     `hold_process_corner` — the label the run actually assigned to the hold
     role. It is durable (it survives when the Tcl is pruned from a published
     run) and unambiguous (no parsing). Judged directly.
     It is NOT a tie-breaker over the script — see A DECLARED FIELD DOES NOT
     OUTRANK THE EVIDENCE below.
  2. EXPLICIT HOLD-VIEW LINES. Lines that tie hold/min to a corner — the
     emitter's own `=== HOLD corner: process=FF liberty=… ===` banner, or an
     MCMM `set_hold_view` / `-corner` assignment. When any exist, ONLY they are
     judged; a macro liberty read elsewhere in the file cannot outvote the
     script's own statement of which corner the hold analysis runs at.
  3. LIBERTY / OPERATING-CONDITION FEED. Otherwise the union of designators on
     `read_liberty` / `set_operating_conditions` / hold-view lines is taken and
     the rule is: a FAST designator anywhere in that set means a fast corner
     feeds the hold analysis -> PASS, and the remaining designators are
     DISCLOSED as `extra_library_corners` (they are additional models, not the
     process corner of the sign-off). No FF anywhere -> FAIL: the hold analysis
     was run with only slow/typical libraries, which is the defect.

A DECLARED FIELD DOES NOT OUTRANK THE EVIDENCE IT CLAIMS TO SUMMARISE
---------------------------------------------------------------------
The first wiring of this gate read the stance and STOPPED: in project-directory
mode `_discover` returned the moment `reports/phase3/mcorner_ocv_stance.json`
existed and the hold Tcl was never opened. MEASURED false PASS that produced —
a stance saying

    "hold_process_corner": "FF"

beside a hold script whose only `read_liberty` is `…__ss_100C_1v60.lib` and
whose own banner reads `=== HOLD corner: process=SS … ===`:

    project directory  -> rc=0 PASS   (stance believed, script discarded)
    the identical Tcl  -> rc=1 FAIL   HOLD_NOT_AT_FF

Every non-rc=2 verdict this gate produced over the published corpus came from
the stance, and two published roots (`sha256/clean_run_v1422_20260715`,
`…v1427…`) carry BOTH artefacts — so the discarded input was not hypothetical.
That is the shape `de8e98b3e` had just repaired elsewhere: a DECLARED field
standing in for the measurement it names.

So project-directory mode now judges EVERY source it finds and takes the WORST:

    FAIL   >   PASS   >   NOT CHECKED

read as "worst of the verdicts that were REACHED". FAIL wins outright — a
contradiction between the label and the script is resolved against the label,
in either direction, and both readings are published under `sources` with
`contradiction: true`. PASS outranks NOT CHECKED deliberately and it is the
same rule, not an exception to it: a source that reached NO verdict (an
unreadable stance, a stance with no `hold_process_corner` at all) is not
evidence, and letting it mask a source that DID reach one would discard
evidence in the other direction.

The input SET is unchanged — the same single hold Tcl the fallback would have
picked (most specific candidate first, then the glob). This repair is "stop
discarding the script", not "widen what counts as a script".

  RESIDUALS, disclosed on purpose — two, and neither is closed by the above:

  1. A run that publishes ONLY the stance is still judged on its declared field
     alone, with nothing to corroborate it. MEASURED: 26 of the 34 published
     phase-3 run roots have neither artefact (rc=2), 6 have the stance alone
     and 2 have both — so the corroborated case is 2 roots today. What closes
     this is the flow RETAINING the hold script on a published run, not a
     checker change: with no script there is nothing to read.
  2. A hand-written MCMM script that reads ss/tt/ff libraries and then assigns
     the hold view to ss WITHOUT any hold/min-tagged line reaches rule 3 and
     passes on the presence of the ff library. Rule 2 covers every script that
     says which view is the hold view. The alternative — rule 3 as an
     all-must-be-FF rule — is a FALSE FAIL on every macro-bearing design, which
     is strictly worse.

Verdicts
--------
* PASS (rc=0) — a hold/min analysis is present AND a FAST (FF) corner feeds it.
* FAIL (rc=1) — the hold/min analysis is driven by a NON-fast (SS/TT) corner,
                OR no hold/min analysis is present in an artefact that exists
                (nothing was verified — honest FAIL, not a vacuous pass), OR an
                explicitly NAMED input file is missing/empty/garbage.
* NOT CHECKED (rc=2) — PROJECT-DIRECTORY mode only: the run produced neither a
                multi-corner OCV stance record nor a hold STA script, so there
                is no hold sign-off to judge. rc=2 is the flow's disclosed-skip
                tier. This tier is what lets the gate be wired UNCONDITIONALLY:
                gating it on the very artefact whose absence would be
                interesting is the self-disabling shape
                `flow_condition_reachability_check` refuses, and without the
                tier an unconditional wire reddened 31 of 33 published runs for
                INPUT_MISSING.

chip-AGNOSTIC: corner designators are matched by the same general convention
patterns used by corner_coverage_audit.py; no PDK / vendor cell is hard-coded.

Usage
-----
    python3 hold_corner_coverage_check.py <hold_tcl_or_log> [--json <out>]
    python3 hold_corner_coverage_check.py <project_dir> [--json <out>]
    python3 hold_corner_coverage_check.py --stance <mcorner_ocv_stance.json>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_TOOL = "hold_corner_coverage_check"

# Process-corner designators (subset of corner_coverage_audit.PROCESS_CORNER_MAP).
_FAST = {"ff", "fast_fast", "fastfast", "fast"}
_SLOW = {"ss", "slow_slow", "slowslow", "slow"}
_TYP = {"tt", "typical", "typ", "nom"}

_PROC_RE = re.compile(
    # The boundary class includes ``=`` so a ``key=corner`` token parses. The
    # emitter writes its EXPLICIT hold-view line (Rule 2) as
    # ``=== HOLD corner: process=FF liberty=... ===``; this pattern was copied
    # from corner_coverage_audit.PROCESS_RE, a FILENAME matcher whose class
    # (``_ / - . whitespace : ,``) never included ``=``, so the emitter's OWN
    # banner never matched and a hold sign-off genuinely run at FF was reported
    # NO_FEED_CORNER. The sibling sta_corner_record_completeness_check parses the
    # same banner with ``process=([\w.+-]+)`` and has no such gap. ``=`` cannot
    # turn a non-FF hold green: a ``process=SS`` banner still yields only SS.
    r"(?:^|[_/\-.\s:,=])"
    r"(ss|tt|ff|sf|fs|slow_slow|fast_fast|typical|slowslow|fastfast|"
    r"slow_fast|fast_slow|slowfast|fastslow|slow|fast|typ|nom)"
    r"(?:[_/\-.\s:,=]|$)",
    re.IGNORECASE,
)

# Lines that introduce a Liberty / operating-condition used by the MIN (hold)
# analysis. We mine the Liberty read AND any min-path / hold view assignment.
_LIB_READ_RE = re.compile(r"\bread_liberty\b(.*)$", re.I)
_MIN_VIEW_RE = re.compile(
    r"(?:hold|min)[^\n]*?(?:corner|view|operating_condition|lib)\b(.*)$", re.I)
_SET_OC_RE = re.compile(r"\bset_operating_conditions\b(.*)$", re.I)
# The invocation that runs the hold report (proves a hold analysis exists).
_HOLD_RUN_RE = re.compile(
    r"report_checks[^\n]*-path_delay\s+min|"
    r"report_worst_slack[^\n]*-min|report_tns[^\n]*-min|"
    r"\b-path_delay\s+min\b|\bcheck_hold\b", re.I)


def _classify_corner(token: str) -> str:
    t = token.lower()
    if t in _FAST:
        return "FF"
    if t in _SLOW:
        return "SS"
    if t in _TYP:
        return "TT"
    return "OTHER"


def _corners_in(text: str) -> List[str]:
    out = []
    for m in _PROC_RE.finditer(text):
        c = _classify_corner(m.group(1))
        if c in ("FF", "SS", "TT"):
            out.append(c)
    return out


def evaluate(text: Optional[str]) -> Tuple[str, int, dict]:
    report = {"tool": _TOOL}
    if text is None:
        report.update(verdict="FAIL", reason="INPUT_MISSING",
                      message="hold-analysis artefact missing/unreadable — "
                              "cannot verify the hold corner (honest FAIL)")
        return "FAIL", 1, report
    if not text.strip():
        report.update(verdict="FAIL", reason="INPUT_EMPTY",
                      message="hold-analysis artefact is empty")
        return "FAIL", 1, report

    has_hold_run = bool(_HOLD_RUN_RE.search(text))
    report["hold_analysis_present"] = has_hold_run
    if not has_hold_run:
        report.update(verdict="FAIL", reason="NO_HOLD_ANALYSIS",
                      message="no hold (min-path) analysis found "
                              "(report_checks -path_delay min / "
                              "report_worst_slack -min) — nothing was verified")
        return "FAIL", 1, report

    # Collect the corners that feed the hold/min analysis: every read_liberty,
    # set_operating_conditions, and explicit min/hold view line.
    feed_lines: List[str] = []
    view_lines: List[str] = []
    for line in text.splitlines():
        is_view = bool(_MIN_VIEW_RE.search(line))
        if _LIB_READ_RE.search(line) or _SET_OC_RE.search(line) or is_view:
            feed_lines.append(line)
        if is_view:
            view_lines.append(line)

    # RULE 2 — a line that explicitly ties hold/min to a corner outranks every
    # other liberty in the file (see the module docstring).
    view_corners: List[str] = []
    for line in view_lines:
        view_corners.extend(_corners_in(line))

    feed_corners: List[str] = []
    for line in feed_lines:
        feed_corners.extend(_corners_in(line))
    report["hold_feed_corners"] = sorted(set(feed_corners))
    report["hold_feed_lines"] = feed_lines

    if view_corners:
        judged, basis = sorted(set(view_corners)), "declared_hold_view"
        report["hold_view_lines"] = view_lines
    else:
        judged, basis = sorted(set(feed_corners)), "liberty_feed"
    report["corner_basis"] = basis
    report["judged_corners"] = judged

    if not judged:
        # A hold analysis runs but we cannot find ANY Liberty / OC corner
        # designator feeding it — we cannot certify it is FF. Honest FAIL.
        report.update(verdict="FAIL", reason="NO_FEED_CORNER",
                      message="hold analysis present but no Liberty / operating "
                              "condition corner could be identified feeding it "
                              "— cannot confirm the FF corner is used")
        return "FAIL", 1, report

    if "FF" not in judged:
        non_fast = [c for c in judged if c != "FF"]
        report.update(verdict="FAIL", reason="HOLD_NOT_AT_FF",
                      message=f"hold (min) analysis is driven by a NON-fast "
                              f"corner {non_fast} and by no fast corner at all "
                              f"(basis: {basis}) — hold is worst at FF "
                              f"(fast/high-V/low-T); signing hold off at "
                              f"{non_fast} under-reports hold violations")
        return "FAIL", 1, report

    extra = [c for c in judged if c != "FF"]
    if extra:
        # DISCLOSED, not failed: additional libraries (hard-macro / IP models,
        # which the flow narrows to the typical corner by design) are not the
        # process corner of the hold sign-off.
        report["extra_library_corners"] = extra
    report.update(verdict="PASS", reason="HOLD_AT_FF",
                  message="hold (min) analysis is driven by the FF corner — "
                          "the worst-case corner for hold"
                          + (f" (additional library corners {extra} disclosed, "
                             f"not judged as the sign-off corner)"
                             if extra else ""))
    return "PASS", 0, report


# ───────────────────────── declared-stance mode ──────────────────────────
#: The durable record of which PROCESS corner each sign-off role resolved to.
#: Written by `phase3_one_shot_runner` on every run that reaches multi-corner
#: OCV, INCLUDING the runs that then decline to execute it — which is exactly
#: the case a Tcl-only gate cannot see.
_STANCE_REL = "reports/phase3/mcorner_ocv_stance.json"


def evaluate_stance(data: Optional[dict]) -> Tuple[str, int, dict]:
    """Judge `hold_process_corner` from a multi-corner OCV stance record."""
    report = {"tool": _TOOL, "mode": "stance"}
    if not isinstance(data, dict):
        report.update(verdict="NOT CHECKED", reason="STANCE_UNREADABLE",
                      message="stance record missing or unparseable")
        return "NOT CHECKED", 2, report
    hold = data.get("hold_process_corner")
    report["hold_process_corner"] = hold
    report["setup_process_corner"] = data.get("setup_process_corner")
    report["multi_process_corner"] = data.get("multi_process_corner")
    report["report"] = data.get("report")
    if hold is None:
        report.update(verdict="NOT CHECKED", reason="NO_DECLARED_HOLD_CORNER",
                      message="the run declared no hold process corner at all "
                              "(no SS/TT/FF liberty resolved) — there is no "
                              "hold sign-off corner to judge")
        return "NOT CHECKED", 2, report
    cls = _classify_corner(str(hold))
    report["hold_corner_class"] = cls
    if cls == "FF":
        report.update(verdict="PASS", reason="HOLD_AT_FF",
                      message=f"hold sign-off role is declared at "
                              f"{hold} — the fast corner, worst-case for hold")
        return "PASS", 0, report
    report.update(
        verdict="FAIL", reason="HOLD_NOT_AT_FF",
        message=f"the run declares hold_process_corner={hold!r} — hold is "
                f"worst at FF (fast/high-V/low-T), so a hold role assigned to "
                f"{hold!r} under-reports hold violations. multi_process_corner="
                f"{data.get('multi_process_corner')!r}, report="
                f"{data.get('report')!r}: no fast-corner hold analysis was "
                f"performed on this run.")
    return "FAIL", 1, report


#: Hold STA scripts a project-directory run may have produced, most specific
#: first. The multi-corner OCV hold pass is the one that carries a declared
#: hold corner; the glob is the fallback for a hand-run script.
_HOLD_TCL_CANDIDATES = (
    "phase3/stage3/sta/sta_mcorner_ocv_hold.tcl",
    "phase3/stage3/sta/sta_spef_hold.tcl",
)
_HOLD_TCL_GLOB = "phase3/stage3/sta/*hold*.tcl"


def _find_hold_tcl(project: Path) -> Optional[Path]:
    """The ONE hold script this gate reads: most specific candidate first,
    then the glob. Unchanged by the worst-of repair on purpose — that repair
    stops the script being DISCARDED, it does not widen what counts as one."""
    for rel in _HOLD_TCL_CANDIDATES:
        c = project / rel
        if c.is_file():
            return c
    hits = sorted(project.glob(_HOLD_TCL_GLOB))
    return hits[0] if hits else None


def _discover(project: Path) -> List[Tuple[str, Path]]:
    """EVERY hold-sign-off source a PROJECT DIRECTORY published, in the order
    they are reported. `[]` when the run published none.

    It returns a LIST, and that is the whole repair: the previous version
    returned the FIRST hit and the stance was first, so a hold script that
    contradicted the declared field was never opened.
    """
    found: List[Tuple[str, Path]] = []
    stance = project / _STANCE_REL
    if stance.is_file():
        found.append(("stance", stance))
    tcl = _find_hold_tcl(project)
    if tcl is not None:
        found.append(("tcl", tcl))
    return found


#: Worst-of ordering. Read as "worst of the verdicts that were REACHED":
#: NOT CHECKED is the ABSENCE of a verdict, so it can neither raise nor mask
#: one — see the module docstring.
_SEVERITY = {"FAIL": 2, "PASS": 1, "NOT CHECKED": 0}


def _judge_source(kind: str, path: Path) -> Tuple[str, int, dict]:
    """Judge ONE discovered source with the mode-appropriate evaluator."""
    if kind == "stance":
        data = None
        try:
            data = json.loads(path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            data = None
        verdict, rc, report = evaluate_stance(data)
    else:
        try:
            text: Optional[str] = path.read_text(errors="replace")
        except OSError:
            text = None
        verdict, rc, report = evaluate(text)
        report["mode"] = "tcl"
    report["artefact"] = str(path)
    report["source"] = kind
    return verdict, rc, report


def judge_project(project: Path) -> Tuple[str, int, dict]:
    """Judge a project directory: every published source, WORST wins.

    The deciding source's report is what the caller sees at top level (so the
    JSON shape a reader already knows is preserved), with every source's
    reading published under `sources` and a `contradiction` flag when two
    sources disagree.
    """
    sources = _discover(project)
    if not sources:
        # DISCLOSED SKIP — this run produced no hold sign-off record at all.
        # Not a pass (nothing was verified) and not a failure (nothing claims
        # otherwise); rc=2 is the flow's tier for that.
        return "NOT CHECKED", 2, {
            "tool": _TOOL, "mode": "project",
            "verdict": "NOT CHECKED",
            "reason": "NO_HOLD_SIGNOFF_ARTEFACT",
            "artefact": str(project),
            "project": str(project),
            "sources": [],
            "message": f"no multi-corner OCV stance record ({_STANCE_REL}) "
                       f"and no hold STA script under phase3/stage3/sta — "
                       f"this run has no hold sign-off corner to judge"}

    judged = [(k, *_judge_source(k, p)) for k, p in sources]
    worst = max(judged, key=lambda j: _SEVERITY.get(j[1], 0))
    _kind, verdict, rc, report = worst
    report = dict(report)
    report["deciding_source"] = _kind
    report["sources"] = [
        {"source": k, "artefact": r.get("artefact"), "verdict": v,
         "reason": r.get("reason"), "message": r.get("message")}
        for k, v, _rc, r in judged]
    distinct = {v for _k, v, _rc, _r in judged}
    if len(distinct) > 1:
        report["contradiction"] = True
        pairs = ", ".join(f"{k}={v}" for k, v, _rc, _r in judged)
        report["message"] = (
            f"{report.get('message', '')} "
            f"[CONTRADICTION — this run's hold sign-off sources DISAGREE "
            f"({pairs}); the worst reading decides, because a declared field "
            f"does not outrank the evidence it claims to summarise]").strip()
    report["project"] = str(project)
    return verdict, rc, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Confirm hold analysis uses the FF (fast) corner. The "
                    "positional may be a hold-analysis artefact OR a project "
                    "directory (in which case EVERY hold sign-off source the "
                    "run published — the declared multi-corner OCV stance AND "
                    "its hold STA script — is judged and the WORST decides).")
    ap.add_argument("hold_artefact", nargs="?",
                    help="hold-analysis Tcl / SDC / log that drives the "
                         "min-path (hold) check, or a project directory")
    ap.add_argument("--stance",
                    help="judge hold_process_corner from this "
                         "mcorner_ocv_stance.json directly")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    if not args.hold_artefact and not args.stance:
        ap.error("supply a hold artefact / project directory, or --stance")

    report: dict
    if args.stance:
        sp = Path(args.stance)
        data = None
        if sp.is_file():
            try:
                data = json.loads(sp.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError):
                data = None
        verdict, rc, report = evaluate_stance(data)
        report["artefact"] = str(sp)
    else:
        p = Path(args.hold_artefact)
        if p.is_dir():
            verdict, rc, report = judge_project(p)
        else:
            text: Optional[str]
            if not p.is_file():
                text = None
            else:
                try:
                    text = p.read_text(errors="replace")
                except OSError:
                    text = None
            verdict, rc, report = evaluate(text)
            report["artefact"] = str(p)

    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"=== {_TOOL} === verdict: {verdict}")
    if rc == 2:
        # The flow reads rc=2 as the disclosed-skip tier; print the sentinel so
        # a human reading the log sees the same thing the aggregator does.
        print(f"VACUOUS_PASS: {_TOOL} — NOT CHECKED "
              f"[{report.get('reason')}]: {report.get('message')}")
    if report.get("judged_corners"):
        print(f"  judged corners: {report['judged_corners']} "
              f"(basis: {report.get('corner_basis')})")
    if report.get("extra_library_corners"):
        print(f"  extra library corners (disclosed, not judged): "
              f"{report['extra_library_corners']}")
    if report.get("hold_process_corner") is not None:
        print(f"  declared hold_process_corner: "
              f"{report['hold_process_corner']!r}")
    # Every source that was read, whether or not it decided — a reader who
    # only ever sees the winning line cannot tell a corroborated verdict from
    # an uncorroborated one, which is the distinction this repair added.
    for s in report.get("sources") or []:
        mark = " <- DECIDES" if s["source"] == report.get(
            "deciding_source") else ""
        print(f"  source[{s['source']}] {s['verdict']} "
              f"[{s.get('reason')}] {s.get('artefact')}{mark}")
    if report.get("contradiction"):
        print("  CONTRADICTION: the sources disagree; the WORST reading "
              "decides — a declared field does not outrank the evidence it "
              "claims to summarise")
    if verdict == "FAIL":
        print(f"  FAIL [{report.get('reason')}]: {report.get('message')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
