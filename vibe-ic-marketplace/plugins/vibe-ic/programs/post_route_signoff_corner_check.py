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

ONE AXIS IS NOT THE SIGN-OFF (vibe-ic#913)
==========================================
The report above sweeps ONE sign-off axis: the RC/parasitic corners
(`corners_available: max,min,nom`). The run's OTHER declared sign-off axis —
process (the per-corner / OCV reports) — is not in it. So a setup violation
that lives only on the process axis is invisible to this gate BY
CONSTRUCTION, and the sentence "all analyzed sign-off corners MET" was
rendered over a number that never saw that axis.

MEASURED, the run that filed #913: this gate PASS with
`setup_worst_slack_ns 6.77` while `per_corner/sta_SS.rpt`, in the SAME run
directory, carried setup `-2.850 ns`. Two gates, opposite verdicts, one design.
The word "analyzed" was carrying the entire disclosure and carrying it
silently — and a PASS whose scope is undisclosed is indistinguishable from a
PASS whose scope is complete, which is worse than no check at all because it
occupies the slot a real check would have gone in.

So after judging its own axis this gate RECONCILES SCOPE against the rest of
the run:

  * no sign-off evidence outside this gate's axis      -> PASS, unchanged.
  * evidence on another axis, all MET                  -> SINGLE_AXIS_ONLY.
        rc 0 (nothing is violated), but NEVER printed as PASS — the banner
        carries the limitation, exactly as the sibling gate's
        `SINGLE_CORNER_ONLY` does, so no downstream summary can quote a bare
        "PASS" and have it read as an all-axis sign-off.
  * a VIOLATED sign-off corner on another axis         -> FAIL.
        This gate's own predicate ("FAIL when ANY sign-off corner's
        worst-slack is negative"), applied to a corner it was skipping. It is
        not a new judgement and not a second opinion: the corner rows are read
        THROUGH the sibling gate `sta_corner_record_completeness_check`, so the
        two gates cannot disagree about the same corner — the disagreement was
        the defect.

The axis set is DISCOVERED, never enumerated here: "outside this gate's scope"
means every axis the sibling's record reader returns that is not
`sta_corner_record_completeness_check.AXIS_RC`. An axis added there is picked
up without an edit here. A row whose slack resolved from a PRE-LAYOUT basis is
DISCLOSED but never escalated to FAIL — a pre-layout estimate is not a sign-off
measurement, and the sibling already records which basis won per field.

Exit: 0 PASS/NOT_APPLICABLE/SINGLE_AXIS_ONLY · 1 FAIL · 2 arg error.
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

# The ONE reader of a per-corner timing record, borrowed rather than re-derived.
# Re-implementing the corner discovery here is how the two gates would come to
# disagree about the same corner again — the #913 defect — one emitter suffix or
# one report-path variant later. Importing it also means the axis VOCABULARY is
# discovered from its source of truth instead of typed out as a second copy.
try:
    import sta_corner_record_completeness_check as _rec  # noqa: E402  sibling gate
except Exception:  # pragma: no cover - defensive
    _rec = None

_PROGRAM = "post_route_signoff_corner_check"

#: The single sign-off axis this gate's report covers, taken from the sibling's
#: own constant so the two cannot drift. The literal is a last-resort fallback
#: for an import that failed, in which case scope is reported UNASSESSED anyway
#: and the value is only ever rendered as prose.
SWEPT_AXIS = getattr(_rec, "AXIS_RC", "rc")

#: Not a failure — nothing this gate read is violated — but never a full
#: sign-off either. The verdict STRING carries the limitation, the same device
#: and the same reason as the sibling gate's `SINGLE_CORNER_ONLY`.
SINGLE_AXIS_ONLY = "SINGLE_AXIS_ONLY"

#: Verdicts that exit 0. `SINGLE_AXIS_ONLY` is here and is deliberately absent
#: from `_BANNER_PASS` below: green, and never the word PASS.
_RC_ZERO_VERDICTS = ("PASS", "NOT_APPLICABLE", SINGLE_AXIS_ONLY)
_BANNER_PASS = ("PASS", "NOT_APPLICABLE")

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


def evaluate(report_text: str, slack_tol: float = _DEFAULT_SLACK_TOL_NS
             ) -> Dict[str, object]:
    """Pure evaluator over the multicorner sign-off report body. Records the
    per-section worst-slacks and the governing (minimum) slack; a governing
    slack below -slack_tol is a FAIL. Independent of any written verdict."""
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
    return {
        "verdict": "PASS" if passed else "FAIL",
        "status": "PASS" if passed else "FAIL",
        "reasons": ([f"all analyzed sign-off corners MET "
                     f"(governing worst-slack {governing:+.3f} ns; "
                     f"corners analyzed: {_scope_phrase(corners_available)})"]
                    if passed else violated),
        "corners_available": corners_available,
        "setup_worst_slack_ns": setup_ws,
        "hold_worst_slack_ns": hold_ws,
        "governing_worst_slack_ns": governing,
        "slack_tol_ns": slack_tol,
    }


def _row_violations(rec: Dict[str, object], slack_tol: float
                    ) -> List[Dict[str, object]]:
    """The VIOLATED sign-off datapoints on one per-corner record row.

    Only a value the sibling resolved from the SIGN-OFF basis can escalate a
    verdict: a pre-layout estimate of the same corner is a measurement of a
    different thing, and reading it as sign-off slack is the defect the
    sibling's own `_resolve` exists to prevent. A pre-layout miss is still
    reported — as disclosure, on the row — never as this gate's FAIL.
    """
    out: List[Dict[str, object]] = []
    basis = rec.get("basis_used") or {}
    for field, role in (("setup_wns_ns", "setup"), ("hold_wns_ns", "hold")):
        val = rec.get(field)
        if not isinstance(val, (int, float)) or val >= -slack_tol:
            continue
        out.append({
            "axis": rec.get("axis"), "corner": rec.get("corner"),
            "role": role, "slack_ns": float(val),
            "basis": basis.get(field),
            "source": rec.get("source"),
            "signoff_basis": (getattr(_rec, "BASIS_SIGNOFF", "SIGNOFF")
                              == basis.get(field)),
        })
    return out


def other_axis_evidence(project: Path, slack_tol: float = _DEFAULT_SLACK_TOL_NS
                        ) -> Dict[str, object]:
    """Sign-off corner evidence THIS run carries on axes this gate never reads.

    Returns `assessed=False` when the sibling record reader is unavailable —
    which is NOT the same fact as "there is no other axis", and the caller must
    not collapse the two. Discovery is by set difference against
    `SWEPT_AXIS`, so a third axis needs no edit here.
    """
    if _rec is None:  # pragma: no cover - defensive
        return {"assessed": False, "axes": [], "corners": [], "violated": [],
                "why": "sta_corner_record_completeness_check could not be "
                       "imported, so the run's other sign-off axes were not "
                       "read"}
    try:
        recs = _rec.read_records(project, _rec.read_declarations(project))
    except Exception as e:  # pragma: no cover - defensive
        return {"assessed": False, "axes": [], "corners": [], "violated": [],
                "why": f"the run's per-corner record could not be read: {e}"}

    corners: List[Dict[str, object]] = []
    violated: List[Dict[str, object]] = []
    for rec in recs.values():
        if rec.get("axis") == SWEPT_AXIS:
            continue
        corners.append({
            "axis": rec.get("axis"), "corner": rec.get("corner"),
            "setup_wns_ns": rec.get("setup_wns_ns"),
            "hold_wns_ns": rec.get("hold_wns_ns"),
            "source": rec.get("source"),
            "basis_used": rec.get("basis_used"),
        })
        violated += _row_violations(rec, slack_tol)
    axes = sorted({str(c["axis"]) for c in corners})
    return {"assessed": True, "axes": axes,
            "corners": sorted(corners, key=lambda c: (str(c["axis"]),
                                                      str(c["corner"]))),
            "violated": violated, "why": None}


def _corner_list(corners: List[Dict[str, object]], axis: str) -> str:
    names = [str(c["corner"]) for c in corners if c["axis"] == axis]
    srcs = sorted({str(c["source"]) for c in corners if c["axis"] == axis})
    return f"{','.join(names) or 'unnamed'} via {'; '.join(srcs) or 'unknown'}"


def reconcile_scope(project: Path, res: Dict[str, object],
                    slack_tol: float) -> Dict[str, object]:
    """Fold the rest of the run's sign-off evidence into this gate's verdict.

    Mutates and returns `res`. A verdict that judged NOTHING (NOT_APPLICABLE,
    IO_ERROR) is left alone: it makes no scope claim to qualify, and widening
    it here would be a different change with a different blast radius.
    """
    if res.get("verdict") not in ("PASS", "FAIL"):
        return res
    ev = other_axis_evidence(project, slack_tol)
    res["scope_axis_swept"] = SWEPT_AXIS
    res["scope_other_axis_evidence"] = ev
    prior = [str(r) for r in (res.get("reasons") or [])]

    if not ev["assessed"]:
        # UNKNOWN is not CLEAR. An unqualified PASS here would assert a scope
        # this gate just failed to establish.
        if res["verdict"] == "PASS":
            res["verdict"] = res["status"] = SINGLE_AXIS_ONLY
            res["reasons"] = prior + [
                f"scope NOT RECONCILED: sign-off corners MET on the "
                f"{SWEPT_AXIS} axis, but whether this run carries sign-off "
                f"evidence on any OTHER axis could not be established "
                f"({ev['why']}) — so this is a one-axis result, not a "
                f"sign-off"]
        return res

    if not ev["axes"]:
        # The only sign-off evidence in the run is on the axis this gate read.
        res["reasons"] = prior + [
            f"scope reconciled: this run carries no sign-off corner evidence "
            f"outside the {SWEPT_AXIS} axis, so this verdict covers every "
            f"axis the run reported"]
        return res

    detail = "; ".join(f"{ax} axis ({_corner_list(ev['corners'], ax)})"
                       for ax in ev["axes"])

    if ev["violated"]:
        hard = [v for v in ev["violated"] if v["signoff_basis"]]
        soft = [v for v in ev["violated"] if not v["signoff_basis"]]
        found = [
            f"a SIGN-OFF corner on the {v['axis']} axis — which this gate's "
            f"report does not cover — is VIOLATED: corner '{v['corner']}' "
            f"{v['role']} {float(v['slack_ns']):+.3f} ns "
            f"(source {v['source']}) — read through "
            f"sta_corner_record_completeness_check, so this gate and that one "
            f"cannot disagree about this corner"
            for v in hard]
        found += [
            f"corner '{v['corner']}' on the {v['axis']} axis is "
            f"{v['role']} {float(v['slack_ns']):+.3f} ns, but that value "
            f"resolved from a {v['basis']} basis, not a sign-off measurement "
            f"(source {v['source']}) — DISCLOSED, not counted as this gate's "
            f"violation"
            for v in soft]
        if hard:
            # The MET sentence is REPLACED, not dropped: a FAIL that still
            # reads "all analyzed sign-off corners MET" is the contradiction
            # this change exists to remove, and a FAIL that says nothing about
            # this gate's own axis loses the fact that the axis it DID sweep
            # was clean — which is exactly the scope disclosure being added.
            kept = [r for r in prior if not r.startswith("all analyzed")]
            if len(kept) != len(prior):
                kept = [f"this gate's own {SWEPT_AXIS}-axis corners are MET "
                        f"(governing worst-slack "
                        f"{float(res['governing_worst_slack_ns']):+.3f} ns; "
                        f"corners analyzed: "
                        f"{_scope_phrase(res.get('corners_available'))}) — "
                        f"which is a statement about that axis alone"] + kept
            res["verdict"] = res["status"] = "FAIL"
            res["reasons"] = kept + found
            return res
        res["reasons"] = prior + found
        if res["verdict"] == "PASS":
            res["verdict"] = res["status"] = SINGLE_AXIS_ONLY
        return res

    if res["verdict"] == "PASS":
        res["verdict"] = res["status"] = SINGLE_AXIS_ONLY
    res["reasons"] = prior + [
        f"SCOPE: this verdict covers the {SWEPT_AXIS} axis ONLY. The same run "
        f"also reports sign-off corners on {detail}, which this gate's report "
        f"does not contain — those corners are MET where this run records "
        f"them, but they were judged by another gate, not by this one"]
    return res


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
    res = evaluate(text, slack_tol=slack_tol)
    res["report"] = str(rpt)
    return reconcile_scope(project, res, slack_tol)


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

    tag = str(res["verdict"])
    reasons = "; ".join(str(r) for r in res.get("reasons", []))
    # SINGLE_AXIS_ONLY exits 0 — this gate found nothing violated — but is
    # NEVER printed as PASS. The banner is the only part of this line a reader
    # scans, so a limitation that does not reach it has not been disclosed.
    print(f"[{'PASS' if tag in _BANNER_PASS else tag}] "
          f"{_PROGRAM}: {tag} — {reasons}")
    if tag == "IO_ERROR":
        return 2
    return 0 if tag in _RC_ZERO_VERDICTS else 1


if __name__ == "__main__":
    sys.exit(main())
