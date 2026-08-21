#!/usr/bin/env python3
"""Verify signal integrity / crosstalk analysis was performed."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


# ---------------------------------------------------------------------------
# v1.7.64 — FAIL-CLOSED advisory disclosure (#437 follow-up, Step 27 / d5).
#
# The pre-v1.7.64 predicate ALLOW-LISTED two emitter verdict strings
# ("ADVISORY_SCREEN_ONLY", "SI_SPEF_SCREEN_PASS") plus the substring
# "advisory" in `method`. Measured on a real converged run, the no-SPEF
# fallback emitter writes a THIRD string, "SCREEN_PASS", whose method text
# says "decoupled-C wire-RC screen ... full coupling-cap crosstalk needs a
# SPEF" and whose note says "this is a structural screen, not a full SI
# sign-off" — and the gate reported a bare `verdict: PASS`,
# `advisory_screen_only: false`, zero findings. An artefact that explicitly
# disclaims sign-off was laundered into sign-off by an allow-list miss.
#
# The predicate is now inverted: an SI artefact is ADVISORY unless it
# POSITIVELY declares timing-window SI sign-off. A new emitter string can no
# longer buy a clean PASS by not being on a list. rc is unchanged (WARNING,
# not ERROR) — this is a disclosure fix, not a new pass/fail rule.
# ---------------------------------------------------------------------------

# An explicit boolean is the canonical positive declaration.
_SIGNOFF_DECL_KEYS = ("timing_window_signoff", "si_signoff", "full_si_signoff")

# Textual positive declaration, for third-party emitters carrying no boolean:
# the artefact must name timing-window / switching-window SI analysis...
_SIGNOFF_TEXT_MARKERS = (
    "timing-window", "timing window",
    "switching-window", "switching window",
)
# ...AND must not describe itself as a screen / bound / watch-list, which is
# what every non-sign-off SI artefact in this codebase calls itself.
_SCREEN_MARKERS = (
    "screen", "advisory", "watch-list", "watchlist",
    "upper bound", "not a full si sign-off", "not a full si signoff",
    "not sign-off", "not signoff", "deferred",
)


def declares_si_signoff(blob: str, data: dict | None = None) -> bool:
    """True only when the artefact POSITIVELY declares timing-window SI
    sign-off. Everything else — including an artefact that says nothing at
    all about its own tier — is treated as an advisory screen."""
    if data is not None and any(bool(data.get(k)) for k in _SIGNOFF_DECL_KEYS):
        return True
    low = blob.lower()
    if any(m in low for m in _SCREEN_MARKERS):
        return False
    return any(m in low for m in _SIGNOFF_TEXT_MARKERS)



# ── D9: the artefact must be COHERENT WITH ITSELF ──────────────────────────
# vibe-ic D9 census scored step 27 EXISTENCE-ONLY: every number in
# si_crosstalk.json could be scaled and sign-flipped and this gate's verdict
# did not move. It read `violations_count` and asked only whether it was > 0,
# so a count of -7 sailed through.
#
# NO ORACLE, and none is needed. Nothing below knows what any value SHOULD be
# for any design — a real run ships no answer key. Every rule here is either a
# DOMAIN bound that holds for any circuit ever built, or an arithmetic relation
# the document asserts BETWEEN ITS OWN FIELDS:
#
#   * a coupling ratio is Cc/(Cc+Cg), a fraction of a capacitance by a larger
#     capacitance, so it lies in [0, 1] for every net in every technology;
#   * a mean cannot exceed the max of the same population;
#   * a count of nets cannot be negative;
#   * nets with ratio > 0.9 are a SUBSET of nets with ratio > 0.5, which are a
#     subset of the nets analysed. That containment is exact, not a heuristic:
#     it follows from the thresholds the field NAMES carry.
#
# A document that breaks one of these was not produced by measuring a circuit,
# so every conclusion drawn from it — including this gate's own — is about
# numbers nobody computed.
_RATIO_FIELDS = ("max_coupling_ratio", "mean_coupling_ratio")
_COUNT_FIELDS = ("nets_analyzed", "nets_elevated_coupling_gt0p5",
                 "nets_coupling_dominated_gt0p9", "violations_count")
#: widest-to-narrowest; each must contain the next
_CONTAINMENT = ("nets_analyzed", "nets_elevated_coupling_gt0p5",
                "nets_coupling_dominated_gt0p9")


def _num(data: dict, key: str):
    """The value at `key` iff it is a real number. `bool` is excluded on
    purpose: it is an int subclass, and reading True as 1 would invent a
    measurement out of a flag."""
    v = data.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _incoherent(data: dict) -> List[Finding]:
    """Every self-consistency / domain violation the document commits."""
    out: List[Finding] = []
    if not isinstance(data, dict):
        return out

    for key in _RATIO_FIELDS:
        v = _num(data, key)
        if v is not None and not (0.0 <= v <= 1.0):
            out.append(Finding("ERROR", "SI_RATIO_OUT_OF_DOMAIN",
                               f"{key}={v} is not a ratio: Cc/(Cc+Cg) lies in "
                               f"[0,1] for every net in every technology"))

    lo, hi = _num(data, "mean_coupling_ratio"), _num(data, "max_coupling_ratio")
    if lo is not None and hi is not None and lo > hi:
        out.append(Finding("ERROR", "SI_MEAN_EXCEEDS_MAX",
                           f"mean_coupling_ratio={lo} exceeds "
                           f"max_coupling_ratio={hi} over the same population"))

    for key in _COUNT_FIELDS:
        v = _num(data, key)
        if v is not None and v < 0:
            out.append(Finding("ERROR", "SI_NEGATIVE_COUNT",
                               f"{key}={v}: a count of nets cannot be negative"))

    for wide, narrow in zip(_CONTAINMENT, _CONTAINMENT[1:]):
        a, b = _num(data, wide), _num(data, narrow)
        if a is not None and b is not None and a >= 0 and b >= 0 and b > a:
            out.append(Finding("ERROR", "SI_SUBSET_EXCEEDS_SUPERSET",
                               f"{narrow}={b} exceeds {wide}={a}, but the "
                               f"first names a strictly narrower threshold "
                               f"than the second"))
    return out


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    rpt = _pl.report_path(project_dir, "si_crosstalk.rpt")
    jsn = _pl.report_path(project_dir, "si_crosstalk.json")
    waiver = project_dir / "waivers.json"
    stats = {"report_found": False, "format": "", "violations": 0}

    if jsn.exists():
        stats["report_found"] = True
        stats["format"] = "json"
        try:
            data = json.loads(jsn.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(Finding("ERROR", "BAD_JSON",
                                    f"Cannot parse si_crosstalk.json: {exc}"))
            return findings, stats

        for key in ("max_crosstalk_noise", "violations_count"):
            if key not in data:
                findings.append(Finding("ERROR", "MISSING_FIELD",
                                        f"si_crosstalk.json missing '{key}'"))

        findings.extend(_incoherent(data))

        violations = data.get("violations_count", 0)
        stats["violations"] = violations

        # ORGANIC-20260606 (#437 follow-up comment) — advisory-screen
        # DISCLOSURE: the open-flow emitters hardwire violations_count=0
        # and honestly say so; the gate must not launder that into a clean
        # sign-off PASS. Surface the tier + the coupling-dominated
        # watch-list. v1.7.64 makes the predicate fail-closed (see the
        # module-level note on `declares_si_signoff`).
        blob = " ".join(str(data.get(k, "")) for k in
                        ("verdict", "method", "mode", "tool", "note"))
        is_advisory = not declares_si_signoff(blob, data)
        stats["advisory_screen_only"] = is_advisory
        dominated = data.get("nets_coupling_dominated_gt0p9")
        if is_advisory:
            findings.append(Finding(
                "WARNING", "SI_ADVISORY_SCREEN_ONLY",
                "SI artifact does not declare timing-window SI sign-off — "
                "treated as an ADVISORY screen (the open-flow screens are "
                "floating-victim capacitive bounds with violations_count "
                "hardwired 0); review required before presenting as "
                "sign-off (#437)",
                details=f"verdict={data.get('verdict', '(absent)')!r}"))
            if isinstance(dominated, (int, float)) and dominated > 0:
                findings.append(Finding(
                    "WARNING", "SI_COUPLING_DOMINATED_WATCHLIST",
                    f"{int(dominated)} net(s) coupling-dominated "
                    f"(Cc/(Cc+Cg) > 0.9) on the advisory watch-list — "
                    f"review with a timing-window SI tool (#437)"))
        if isinstance(violations, (int, float)) and violations > 0:
            has_waiver = False
            if waiver.exists():
                try:
                    w = json.loads(waiver.read_text())
                    waivers = w if isinstance(w, list) else w.get("waivers", [])
                    has_waiver = any(
                        e.get("step") == "si_crosstalk" or
                        e.get("category") == "si_crosstalk"
                        for e in waivers if isinstance(e, dict)
                    )
                except (json.JSONDecodeError, OSError):
                    pass
            if not has_waiver:
                findings.append(Finding("ERROR", "SI_VIOLATIONS",
                                        f"{violations} crosstalk violations without waiver"))

    elif rpt.exists():
        stats["report_found"] = True
        stats["format"] = "rpt"
        if rpt.stat().st_size == 0:
            findings.append(Finding("ERROR", "EMPTY_RPT",
                                    "si_crosstalk.rpt is empty"))
        else:
            # v1.7.64 — the same fail-closed disclosure applies to the .rpt
            # form. Otherwise the JSON tightening is trivially bypassed by
            # emitting only the text report, whose own body says
            # "crosstalk screen: PASS".
            try:
                text = rpt.read_text(errors="replace")[:64 * 1024]
            except OSError:
                text = ""
            rpt_advisory = not declares_si_signoff(text)
            stats["advisory_screen_only"] = rpt_advisory
            if rpt_advisory:
                findings.append(Finding(
                    "WARNING", "SI_ADVISORY_SCREEN_ONLY",
                    "SI artifact does not declare timing-window SI "
                    "sign-off — treated as an ADVISORY screen; review "
                    "required before presenting as sign-off (#437)"))
    else:
        findings.append(Finding("ERROR", "NO_REPORT",
                                "Neither si_crosstalk.rpt nor si_crosstalk.json found"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    ok = all(f.severity != "ERROR" for f in findings)
    advisory = stats.get("advisory_screen_only", False)
    return {
        "program": "si_crosstalk_check",
        "version": "1.1.0",
        "project_dir": project_dir,
        # #437 follow-up: the headline names the tier — an advisory
        # capacitive screen is never presented as plain sign-off PASS.
        "verdict": ("ADVISORY_SCREEN_ONLY" if ok and advisory
                    else "PASS" if ok else "FAIL"),
        "summary": {
            "report_found": stats["report_found"],
            "format": stats["format"],
            "violations": stats["violations"],
            "advisory_screen_only": advisory,
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": ok,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check signal integrity / crosstalk analysis")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
