#!/usr/bin/env python3
"""post_route_signoff_corner_check.py — Step-23 multi-corner sign-off SLACK gate.

Closes the #147 gate hole: Step 23 ("Post-route STA, multi-corner multi-mode
sign-off") derived its verdict only from the NOMINAL-corner report + the
SI/crosstalk MCF check — never from the ABSOLUTE worst-setup / worst-hold slack
across ALL analyzed corners. So a design could ship a slow-corner (max-RC)
setup violation as a PASS: the tapeout-signoff multicorner report showed
`worst slack max -1.71` (VIOLATED) yet Step 23 said PASS.

This gate parses the flow's own TAPEOUT-SIGNOFF multicorner SPEF STA report
(`sta_spef_multicorner.rpt`, header "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF
P1)") and FAILs when ANY sign-off corner's worst-slack is negative — setup at
the max-RC corner OR hold at the min-RC corner. A design that is MET at every
sign-off corner PASSes; a design MISSING the multicorner report is NOT judged
here (the step's nominal gate still applies) — the flow wires this as an
OPTIONAL gate conditioned on the report existing, so it is backward-compatible.

Report format consumed (emitted by phase3_one_shot_runner `_emit_multicorner`):

    # Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
    # SETUP corner: max-RC   HOLD corner: min-RC
    # corners_available: max,min,nom
    === SETUP (max-RC corner, SPEF=max) ===
    worst slack max -1.71
    tns max -10.91
    === HOLD (min-RC corner, SPEF=min) ===
    worst slack min 0.54
    tns max -1.82

Verdict rule (chip-AGNOSTIC, no chip/vendor literal):
  * governing_worst_slack = min over every `worst slack {max|min} <ns>` line.
  * FAIL  when governing_worst_slack < -slack_tol  (a violated sign-off corner).
  * PASS  when all sign-off-corner worst-slacks are >= -slack_tol.
  * NOT_APPLICABLE (rc 0) when the report exists but carries no parseable
    `worst slack` line (an empty / errored STA — a different gate's concern),
    or the report is absent (nothing to sign off here).

A reviewed acceptance of a slow-corner miss is handled by the flow's existing
waiver machinery (waivers.json) at the audit layer — this gate never
self-waives.

SIGN-OFF SCOPE: A PASS MAY NOT BE NARROWER THAN THE RUN'S OWN RECORD (#913)
--------------------------------------------------------------------------
The rule above judges ONE axis — the RC/parasitic axis of the multicorner SPEF
report (`max,min,nom`). v1.10.22 made the PASS line SAY so. Disclosure is not
enough on its own: a sign-off verdict that reads PASS is quoted as sign-off no
matter what qualifier trails it.

MEASURED, and this is the defect: this gate returned PASS with
`setup_worst_slack_ns: 6.77` on a run whose OWN process-axis record — written
by the same flow, in the same run — carried a VIOLATED setup corner at
-2.850 ns. Reproduced across this corpus 12 times (governing RC slack +0.38 to
+1.13 ns while the recorded process-axis setup ran -0.09 to -38.23 ns). The
gate was not wrong about the RC axis. It was wrong to call a one-axis result
"sign-off".

So the PASS is now CONDITIONAL on scope, decided from the run's own declaration
artifacts and never from a corner-name, PDK or design literal:

  * every `*_stance.json` under `reports/phase3[/sta]` that records a sign-off
    axis (`corner_library_resolution.axis` / `signoff_dimension`) is read;
  * the stance describing THIS gate's own report is its own axis and is skipped;
  * any remaining axis is OUT OF THIS GATE'S SCOPE, and its recorded outcome
    decides whether a one-axis PASS may be published:

      - out-of-scope axis analysed and MET   -> PASS. The verdict line names
        both axes, so the PASS states how wide it is.
      - out-of-scope axis analysed and VIOLATED -> FAIL
        (`OUT_OF_SCOPE_AXIS_VIOLATED`). This is #913. A sign-off gate may not
        publish PASS while the run it is signing off records a violated
        sign-off corner, even on an axis this gate does not read.
      - out-of-scope axis DECLARED but carrying no slack at all -> FAIL
        (`DECLARED_AXIS_NOT_SWEPT`). An entire declared sign-off axis that was
        never swept is exactly the unreported-corner disease: indistinguishable
        from a met one until someone looks.

WHY `FAIL` AND NOT A SOFTER TIER. The obvious alternative was a non-PASS tier
at rc 0 (the repo's `VACUOUS_PASS` / `NOT_APPLICABLE` shape). It does not work
HERE, and the reason is measured in the caller rather than argued:
`phase3_one_shot_runner._run_declared_signoff_gate` maps rc 0 -> StepResult
"PASS" and rc 1 -> "FAIL" and routes every other rc to BLOCKED/NOT-CHECKED —
"Exactly two exit codes are verdicts about the design". A new rc-0 tier would
therefore be recorded by the flow as a PASS step no matter what string this
gate wrote into its JSON, which is the very "mistaken for sign-off" outcome the
tier was meant to prevent. BLOCKED is equally wrong: something WAS checked.
Both remaining honest options are rc 1, so the tier lives in the JSON's
`signoff_scope` field for triage while the exit code stays fail-closed.

WHAT DELIBERATELY DOES **NOT** FAIL. A `pvt_matrix.json` listing several
liberty corners is an AVAILABILITY list, not a run list — the sibling record
gate documents that treating availability as configuration "would make this
gate fire on every run in the corpus". So a run with no out-of-scope stance
artifact at all declares no second axis HERE, and this gate invents no FAIL
from an availability list; the unconditional
`sta_corner_record_completeness_check` R2 owns that case. The pvt corner count
is carried into the JSON as context only, driving nothing.

Exit: 0 PASS/NOT_APPLICABLE · 1 FAIL (violated sign-off corner, or a sign-off
scope narrower than the run's own record) · 2 arg error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _path_layout as _pl  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _pl = None

_PROGRAM = "post_route_signoff_corner_check"

# A default float-noise guard: a slack this close to zero (1 ps) is treated as
# met, so STA rounding never produces a phantom FAIL. Real sign-off violations
# (e.g. -1.71 ns) are orders of magnitude larger.
_DEFAULT_SLACK_TOL_NS = 0.001

# `worst slack max -1.71` / `worst slack min 0.54` (OpenSTA max=setup, min=hold).
_WORST_SLACK_RE = re.compile(
    r"worst\s+slack\s+(max|min)\s+(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_SECTION_RE = re.compile(r"===\s*(SETUP|HOLD)\b", re.IGNORECASE)
_CORNERS_RE = re.compile(r"#\s*corners_available:\s*(.+)", re.IGNORECASE)


def _candidate_reports(project: Path, override: Optional[str]) -> List[Path]:
    if override:
        return [Path(override) if Path(override).is_absolute()
                else project / override]
    cands = [
        project / "phase3/stage3/sta/sta_spef_multicorner.rpt",
        project / "reports/phase3/sta_spef_multicorner.rpt",
        project / "reports/phase3/sta/sta_spef_multicorner.rpt",
    ]
    # last resort: any multicorner report anywhere under the sta tree
    sta_dir = project / "phase3/stage3/sta"
    if sta_dir.is_dir():
        cands += sorted(sta_dir.glob("*multicorner*.rpt"))
    return cands


def _resolve_report(project: Path, override: Optional[str]) -> Optional[Path]:
    for c in _candidate_reports(project, override):
        if c.is_file():
            return c
    return None


# ── sign-off SCOPE: which axes exist, and what the run recorded for them ────
#
# Read from the run's own stance artifacts. No corner name, PDK name, vendor or
# design string appears here or drives any verdict: an axis is whatever the run
# called it, and its outcome is whatever the run wrote down.
_STANCE_DIRS = ("reports/phase3", "reports/phase3/sta")
_PVT_CANDIDATES = (
    "phase2/stage2/constraints/pvt_matrix.json",
    "reports/phase3/pvt_matrix.json",
)


def _load_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _stance_axis(doc: dict) -> Optional[str]:
    """The axis a stance artifact says it signs off, or None if it says none."""
    clr = doc.get("corner_library_resolution")
    if isinstance(clr, dict) and clr.get("axis"):
        return str(clr["axis"])
    dim = doc.get("signoff_dimension")
    return str(dim) if dim else None


def _is_own_axis(doc: dict, report_name: str) -> bool:
    """True when this stance describes the very report this gate parsed."""
    cited = doc.get("multicorner_sta_report") or doc.get("report") or ""
    if cited and Path(str(cited)).name == report_name:
        return True
    axis = (_stance_axis(doc) or "").lower()
    dim = str(doc.get("signoff_dimension") or "").lower()
    return axis.startswith("rc") or "spef" in dim


def _axis_scope(project: Path, report: Optional[Path],
                slack_tol: float) -> Dict[str, object]:
    """Sign-off axes OTHER than the one this gate reads, and their recorded
    outcome. Purely descriptive — `evaluate` decides what it means."""
    report_name = report.name if report is not None else ""
    others: List[Dict[str, object]] = []
    for rel in _STANCE_DIRS:
        d = project / rel
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*_stance.json")):
            doc = _load_json(path)
            if doc is None:
                continue
            axis = _stance_axis(doc)
            if axis is None:            # not a sign-off stance artifact
                continue
            if _is_own_axis(doc, report_name):
                continue
            setup = doc.get("setup_worst_slack_ns")
            hold = doc.get("hold_worst_slack_ns")
            nums = [v for v in (setup, hold) if isinstance(v, (int, float))]
            named = [str(c) for c in (doc.get("violated_corners") or [])]
            others.append({
                "axis": axis,
                "source": str(path.relative_to(project))
                          if path.is_relative_to(project) else str(path),
                "analyzed": bool(nums),
                "setup_worst_slack_ns": setup,
                "hold_worst_slack_ns": hold,
                "violated_corners": named,
                "violated": bool(named) or any(v < -slack_tol for v in nums),
            })

    # CONTEXT ONLY — an availability list never drives a verdict here.
    pvt_corner_count = None
    for rel in _PVT_CANDIDATES:
        doc = _load_json(project / rel)
        if doc is not None:
            corners = doc.get("corners")
            pvt_corner_count = (len(corners) if isinstance(corners, list)
                                else doc.get("corner_count"))
            break

    return {"own_report": report_name, "other_axes": others,
            "pvt_corner_count_context_only": pvt_corner_count}


def _scope_phrase(corners_available: Optional[str]) -> str:
    """Render the analyzed-corner scope for the VERDICT LINE, not just the JSON.

    The scope is what makes a PASS interpretable. This gate reads the
    multicorner SPEF report, whose corners are RC/parasitic corners
    (`max,min,nom`); it says nothing about any other declared sign-off axis,
    such as the process axis (SS/TT/FF). A reader must not have to already
    know that in order to read the verdict: a qualifier the reader has to
    supply themselves is not a disclosure.

    An UNDECLARED scope is reported as such rather than omitted — a PASS whose
    scope is unstated is indistinguishable from a PASS whose scope is complete.
    """
    if not corners_available:
        return "UNDECLARED (report declares no `corners_available`)"
    return corners_available


def evaluate(report_text: str, slack_tol: float = _DEFAULT_SLACK_TOL_NS,
             axis_scope: Optional[Dict[str, object]] = None
             ) -> Dict[str, object]:
    """Pure evaluator over the multicorner sign-off report body. Records the
    per-section worst-slacks and the governing (minimum) slack; a governing
    slack below -slack_tol is a FAIL. Independent of any written verdict.

    `axis_scope` (from `_axis_scope`) describes the sign-off axes this report
    does NOT cover. It can only ever turn a PASS into a FAIL — a slack FAIL is
    already a FAIL, and with no scope supplied the result is identical to the
    single-axis evaluation, which is what keeps `evaluate(text)` callers and
    the pure-report fixtures behaving exactly as before.
    """
    section = None
    corners: Dict[str, Dict[str, float]] = {"SETUP": {}, "HOLD": {}}
    corners_available = None
    for raw in report_text.splitlines():
        line = raw.strip()
        ms = _SECTION_RE.search(line)
        if ms:
            section = ms.group(1).upper()
            continue
        mc = _CORNERS_RE.search(line)
        if mc:
            corners_available = mc.group(1).strip()
        mw = _WORST_SLACK_RE.search(line)
        if mw and section in ("SETUP", "HOLD"):
            mode = mw.group(1).lower()   # max=setup, min=hold
            corners[section][mode] = float(mw.group(2))

    # Collect every worst-slack seen (setup + hold across sections).
    all_slacks: List[float] = []
    for sect in ("SETUP", "HOLD"):
        for _mode, val in corners[sect].items():
            all_slacks.append(val)

    setup_ws = corners["SETUP"].get("max")
    hold_ws = corners["HOLD"].get("min")

    if not all_slacks:
        return {
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "reasons": ["multicorner sign-off report present but no `worst "
                        "slack` line parsed — no sign-off slack to judge"],
            "corners_available": corners_available,
            "setup_worst_slack_ns": None, "hold_worst_slack_ns": None,
            "governing_worst_slack_ns": None,
        }

    governing = min(all_slacks)
    violated: List[str] = []
    if setup_ws is not None and setup_ws < -slack_tol:
        violated.append(f"setup worst-slack {setup_ws:+.3f} ns at the sign-off "
                        f"(max-RC) corner is VIOLATED")
    if hold_ws is not None and hold_ws < -slack_tol:
        violated.append(f"hold worst-slack {hold_ws:+.3f} ns at the sign-off "
                        f"(min-RC) corner is VIOLATED")
    # A negative worst-slack anywhere (even if the section labels drift) is a
    # violated sign-off corner — do not let an unlabelled corner escape.
    if not violated and governing < -slack_tol:
        violated.append(f"a sign-off-corner worst-slack {governing:+.3f} ns is "
                        f"VIOLATED")

    passed = not violated

    # ── #913: a PASS may not be narrower than the run's own sign-off record ──
    others = list((axis_scope or {}).get("other_axes") or [])
    breached = [a for a in others if a.get("violated")]
    unswept = [a for a in others if not a.get("analyzed")]
    # The scope label states the FACTS about the other axes, and is therefore
    # computed whether or not the in-scope slack passed. Deriving it only on
    # the PASS path would let a slack-FAIL run publish
    # `MULTI_AXIS_CORROBORATED` beside an out-of-scope axis that is itself
    # violating or unswept — a second, quieter version of this very bug.
    if not others:
        signoff_scope = "SINGLE_AXIS"
    elif breached:
        signoff_scope = "OUT_OF_SCOPE_AXIS_VIOLATED"
    elif unswept:
        signoff_scope = "DECLARED_AXIS_NOT_SWEPT"
    else:
        signoff_scope = "MULTI_AXIS_CORROBORATED"

    scope_reasons: List[str] = []
    if passed and others:
        if breached:
            for a in breached:
                named = ", ".join(a.get("violated_corners") or []) or "unnamed"
                scope_reasons.append(
                    f"this gate swept the "
                    f"`{_scope_phrase(corners_available)}` axis and MET it "
                    f"(governing {governing:+.3f} ns), but the run's own "
                    f"`{a['axis']}` sign-off record ({a['source']}) carries a "
                    f"VIOLATED corner [{named}] — setup "
                    f"{a.get('setup_worst_slack_ns')} ns / hold "
                    f"{a.get('hold_worst_slack_ns')} ns. A one-axis MET is not "
                    f"sign-off while another declared axis is violating")
        elif unswept:
            for a in unswept:
                scope_reasons.append(
                    f"this gate swept the "
                    f"`{_scope_phrase(corners_available)}` axis and MET it "
                    f"(governing {governing:+.3f} ns), but the declared "
                    f"`{a['axis']}` sign-off axis ({a['source']}) records no "
                    f"worst-slack at all — an entire declared axis was never "
                    f"swept, and an unswept corner is indistinguishable from a "
                    f"met one")
    if scope_reasons:
        passed = False

    if passed and others:
        corroborated = "; ".join(
            f"{a['axis']} setup {a.get('setup_worst_slack_ns')} / hold "
            f"{a.get('hold_worst_slack_ns')}" for a in others)
        pass_reason = (f"all analyzed sign-off corners MET (governing "
                       f"worst-slack {governing:+.3f} ns; corners analyzed: "
                       f"{_scope_phrase(corners_available)}; other declared "
                       f"sign-off axes MET: {corroborated})")
    else:
        pass_reason = (f"all analyzed sign-off corners MET (governing "
                       f"worst-slack {governing:+.3f} ns; corners analyzed: "
                       f"{_scope_phrase(corners_available)})")

    return {
        "verdict": "PASS" if passed else "FAIL",
        "status": "PASS" if passed else "FAIL",
        "reasons": ([pass_reason] if passed else (violated + scope_reasons)),
        "corners_available": corners_available,
        "setup_worst_slack_ns": setup_ws,
        "hold_worst_slack_ns": hold_ws,
        "governing_worst_slack_ns": governing,
        "slack_tol_ns": slack_tol,
        "signoff_scope": signoff_scope,
        "out_of_scope_axes": others,
    }


def check(project: Path, report_override: Optional[str],
          slack_tol: float) -> Dict[str, object]:
    rpt = _resolve_report(project, report_override)
    if rpt is None:
        return {
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "reasons": ["no multicorner sign-off report "
                        "(sta_spef_multicorner.rpt) found — nothing to gate"],
            "report": None,
        }
    try:
        text = rpt.read_text(errors="replace")
    except OSError as e:
        return {"verdict": "IO_ERROR", "status": "IO_ERROR",
                "reasons": [f"cannot read {rpt}: {e}"], "report": str(rpt)}
    res = evaluate(text, slack_tol=slack_tol,
                   axis_scope=_axis_scope(project, rpt, slack_tol))
    res["report"] = str(rpt)
    return res


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--report", default=None,
                   help="explicit sta_spef_multicorner.rpt path (else "
                        "auto-discovered under phase3/stage3/sta)")
    p.add_argument("--slack-tol", type=float, default=_DEFAULT_SLACK_TOL_NS,
                   help="float-noise guard (ns); a worst-slack below "
                        "-slack_tol is a violation (default 0.001)")
    p.add_argument("--json", default=None, help="write the verdict JSON here")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2

    res = check(project, args.report, args.slack_tol)

    out_path = None
    if args.json:
        out_path = Path(args.json)
        if not out_path.is_absolute():
            out_path = project / args.json
    elif _pl is not None:
        try:
            out_path = _pl.report_path(project, "phase3/sta/"
                                       "post_route_signoff_corner.json")
        except Exception:
            out_path = None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(res, indent=2) + "\n")

    tag = res["verdict"]
    reasons = "; ".join(str(r) for r in res.get("reasons", []))
    print(f"[{'PASS' if tag in ('PASS', 'NOT_APPLICABLE') else tag}] "
          f"{_PROGRAM}: {tag} — {reasons}")
    if res["verdict"] == "IO_ERROR":
        return 2
    return 0 if res["verdict"] in ("PASS", "NOT_APPLICABLE") else 1


if __name__ == "__main__":
    sys.exit(main())
