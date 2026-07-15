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

Exit: 0 PASS/NOT_APPLICABLE · 1 FAIL (violated sign-off corner) · 2 arg error.
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
        "reasons": (["all analyzed sign-off corners MET "
                     f"(governing worst-slack {governing:+.3f} ns)"]
                    if passed else violated),
        "corners_available": corners_available,
        "setup_worst_slack_ns": setup_ws,
        "hold_worst_slack_ns": hold_ws,
        "governing_worst_slack_ns": governing,
        "slack_tol_ns": slack_tol,
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
    res = evaluate(text, slack_tol=slack_tol)
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
