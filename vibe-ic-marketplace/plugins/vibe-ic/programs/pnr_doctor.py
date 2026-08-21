"""v0.1.96 — OpenROAD P&R-log error classifier (synth-doctor Pattern-B → program).

Doctrine: `skills/synth-doctor/SKILL.md` documents a 10-pattern OpenROAD P&R-log
classifier (the PnR analog of `synth_doctor.py`). The SKILL.md table names 7
patterns and `PRACTICAL_NOTES.md` §5 adds 3 more (the v0.37 ASIC-pilot patterns),
for the documented 10. This program makes that table run identically every time.

Chip-AGNOSTIC: every signature matches generic OpenROAD / TritonRoute / DRC tool
message text (incl. the documented `XXX-NNNN` message codes) — no benchmark
name, chip-specific net, macro, or coordinate.

The 10 canonical patterns:
    GPL_DIVERGE       — global placement diverged (skip on trivial design)
    DRT_POWER_NET     — power/ground net handed to the signal router (global only)
    FLOORPLAN_FAIL    — wrong site name (IFP-0018) -> read site from cell LEF
    DRC_SPACING       — routing DRC spacing/short -> reduce utilization
    TIMING_FAIL       — negative slack -> relax clock / re-arch the long path
    NO_CLOCK          — no clock defined -> add a (virtual) clock
    CONGESTION        — routing congestion -> reduce density
    DRT_ZERO_NET      — DRT-0305 zero_ ground net -> tie-cell pass (hilomap)
    SITE_NOT_FOUND    — IFP-0018 site not found -> correct site name from LEF
    MISSING_TRACKS    — PPL-0021 no routing tracks -> add make_tracks

Each finding carries `{matched_pattern, canonical_fix, confidence}`. `confidence`
is a deterministic per-pattern value: 1.0 for the two-step recipes documented at
100 % success (DRT_ZERO_NET, FLOORPLAN_FAIL/SITE_NOT_FOUND), lower where the fix
needs a parameter judgement, 0.0 where the SKILL.md marks it non-auto-fixable
(DRT_POWER_NET = manual floorplan).

No-false-alert contract: identical to synth_doctor.py — deny-list of benign
progress lines, a length-floor, and UNKNOWN emitted only for an unrecognised
real error (never for a clean log).

CLI:
    python3 pnr_doctor.py pnr.log              # human diagnosis
    python3 pnr_doctor.py pnr.log --drc drc.rpt # also scan a DRC report
    python3 pnr_doctor.py pnr.log --json        # machine output
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


PATTERNS = (
    "GPL_DIVERGE",
    "DRT_POWER_NET",
    "FLOORPLAN_FAIL",
    "DRC_SPACING",
    "TIMING_FAIL",
    "NO_CLOCK",
    "CONGESTION",
    "DRT_ZERO_NET",
    "SITE_NOT_FOUND",
    "MISSING_TRACKS",
)

CANONICAL_FIX: Dict[str, str] = {
    "GPL_DIVERGE": (
        "Global placement diverged — usually a trivial/under-constrained "
        "design; skip GPL or seed with a valid floorplan and re-run."),
    "DRT_POWER_NET": (
        "A power/ground net was handed to the detailed signal router. Route it "
        "with the global/PDN router only (manual floorplan/PDN fix — NOT "
        "auto-fixable)."),
    "FLOORPLAN_FAIL": (
        "Wrong floorplan site name. Read the correct SITE from the cell LEF "
        "(`grep '^SITE ' cell_macro.lef`) and pass it to initialize_floorplan."),
    "DRC_SPACING": (
        "Routing DRC spacing/short violation. Reduce placement utilization / "
        "core density and re-route; spread congested regions."),
    "TIMING_FAIL": (
        "Negative slack after route. If the spec clock is FIXED, re-architect "
        "the long path (carry-save/select, pipeline) — do NOT silently relax "
        "the clock period; otherwise relax the constraint per spec."),
    "NO_CLOCK": (
        "No clock defined for CTS/STA. Add a (virtual) clock via create_clock "
        "in the SDC so timing-driven steps have a reference."),
    "CONGESTION": (
        "Routing congestion. Reduce core density / utilization, add routing "
        "blockage relief, or upsize the core area, then re-route."),
    "DRT_ZERO_NET": (
        "TritonRoute DRT-0305: a constant `zero_` net is typed GROUND and is "
        "not routable. Run a tie-cell pass in Yosys before PnR: "
        "`setundef -zero; hilomap -hicell TIEHI Y -locell TIELO Y; splitnets; "
        "clean` (do NOT opt_clean after hilomap — it deletes the tie cells)."),
    "SITE_NOT_FOUND": (
        "IFP-0018 unable to find site. The site name is PDK-specific — read it "
        "from the cell LEF (`grep '^SITE ' cell_macro.lef`) and use that name."),
    "MISSING_TRACKS": (
        "PPL-0021 routing tracks not found. The tech LEF lacks track defs — add "
        "`make_tracks <LAYER> -x_pitch <p> -y_pitch <p>` using the LEF PITCH."),
    "UNKNOWN": (
        "No known OpenROAD signature matched — present the raw error to a human "
        "for manual review (do not auto-apply a fix)."),
}

# Deterministic per-pattern confidence. 1.0 = documented 100 % recipe;
# 0.0 = SKILL.md marks it not-auto-fixable / manual.
CONFIDENCE: Dict[str, float] = {
    "GPL_DIVERGE": 0.50,      # "skip (trivial design)" — judgement call
    "DRT_POWER_NET": 0.0,     # PRACTICAL_NOTES §4: not auto-fixable
    "FLOORPLAN_FAIL": 1.0,    # read site from LEF — deterministic
    "DRC_SPACING": 0.70,      # reduce utilization — needs a value
    "TIMING_FAIL": 0.0,       # re-arch / spec call — not a blind auto-fix
    "NO_CLOCK": 0.90,         # add virtual clock — near-mechanical
    "CONGESTION": 0.70,       # reduce density — needs a value
    "DRT_ZERO_NET": 1.0,      # PRACTICAL_NOTES §5: 100 % two-step recipe
    "SITE_NOT_FOUND": 1.0,    # read from LEF — deterministic
    "MISSING_TRACKS": 0.90,   # make_tracks from LEF PITCH
    "UNKNOWN": 0.0,
}

# Signatures in priority order — the specific OpenROAD message codes first so a
# coded line never falls through to a broad keyword pattern.
SIGNATURES: List = [
    # DRT_ZERO_NET — TritonRoute DRT-0305 zero_/GROUND not routable.
    ("DRT_ZERO_NET", re.compile(
        r"DRT-0305|zero_\s+of\s+signal\s+type\s+GROUND|"
        r"net\s+zero_\b.*not\s+routable", re.I)),
    # SITE_NOT_FOUND / FLOORPLAN_FAIL — IFP-0018 unable to find site.
    ("SITE_NOT_FOUND", re.compile(
        r"IFP-0018|unable\s+to\s+find\s+site|site\s+\S+\s+not\s+found", re.I)),
    # MISSING_TRACKS — PPL-0021 routing tracks not found.
    ("MISSING_TRACKS", re.compile(
        r"PPL-0021|routing\s+tracks?\s+not\s+found|no\s+routing\s+tracks?",
        re.I)),
    # NO_CLOCK — no clock defined for CTS/STA.
    ("NO_CLOCK", re.compile(
        r"no\s+clock(?:s)?\s+(?:found|defined|specified)|"
        r"clock\s+\S*\s*not\s+(?:found|defined)|"
        r"design\s+has\s+no\s+clocks", re.I)),
    # DRT_POWER_NET — power/ground net in the detailed signal router.
    ("DRT_POWER_NET", re.compile(
        r"(?:power|ground|special)\s+net.*(?:signal\s+rout|detailed\s+rout)|"
        r"net\s+\S+\s+of\s+signal\s+type\s+(?:POWER|GROUND)\b(?!.*zero_)",
        re.I)),
    # GPL_DIVERGE — global placement diverged.
    ("GPL_DIVERGE", re.compile(
        r"GPL-\d+|placement\s+diverged|global\s+placement\s+.*diverg|"
        r"HPWL\s+is\s+(?:nan|inf)|cannot\s+converge.*placement", re.I)),
    # CONGESTION — routing congestion / overflow.
    ("CONGESTION", re.compile(
        r"congest|routing\s+overflow|GRT-\d+.*overflow|"
        r"\d+\s+(?:gcells?|nets?)\s+(?:over|with)\s+overflow", re.I)),
    # DRC_SPACING — DRC spacing / short violations after route.
    ("DRC_SPACING", re.compile(
        r"(?:min|metal)?\s*spacing\s+violation|short\s+violation|"
        r"DRC\s+violation|\d+\s+(?:DRC|spacing|short)\s+(?:errors?|violations?)",
        re.I)),
    # TIMING_FAIL — negative slack / timing not met (kept after structural ones).
    ("TIMING_FAIL", re.compile(
        r"negative\s+slack|setup\s+violation|hold\s+violation|"
        r"timing\s+(?:not\s+met|violation|failed)|WNS\s*[:=]?\s*-\d|"
        r"worst\s+slack\s*[:=]?\s*-\d", re.I)),
    # FLOORPLAN_FAIL — generic floorplan/init failure (broad — kept last so the
    # specific IFP/site signature wins first).
    ("FLOORPLAN_FAIL", re.compile(
        r"floorplan\s+(?:fail|error)|initialize_floorplan.*(?:fail|error)|"
        r"IFP-\d+|die\s+area\s+.*invalid", re.I)),
]

_BENIGN = re.compile(
    r"^\s*(?:===|---|\|)|"
    r"\bExecuting\b|\bRunning\b|\bStarting\b|"
    # a ZERO count of anything (errors / violations / DRC / spacing / shorts)
    # is success, not a finding — allow optional words between "0" and the noun
    # (e.g. "0 DRC violations", "0 spacing violations found").
    r"\b0\s+(?:\w+\s+){0,2}(?:errors?|violations?|shorts?|drc)\b|"
    r"\bWarnings:\s*0\b|"
    r"\bno\s+(?:DRC|drc)\s+violations?\b|"
    r"successfully\s+(?:finished|completed)|"
    r"\bDone\b|\bEnd\s+of", re.I)

_PROBLEM = re.compile(
    r"\b(?:error|warning|fatal|abort|fail(?:ed|ure)?|violation)\b|"
    r"\b[A-Z]{2,4}-\d{3,4}\b|^\s*ERROR:|^\s*\[ERROR\]", re.I)

MIN_LOG_CHARS = 8


@dataclass
class Diagnosis:
    matched_pattern: str
    canonical_fix: str
    confidence: float
    auto_fixable: bool
    evidence_line: str
    line_no: int
    source: str = "pnr_log"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_line(line: str) -> Optional[str]:
    """Return the pattern name for a single P&R-log line, or None. Never raises."""
    if not line or _BENIGN.search(line):
        return None
    for name, pat in SIGNATURES:
        if pat.search(line):
            return name
    return None


def _scan(text: str, source: str) -> tuple[Dict[str, Diagnosis], bool, str, int]:
    matched: Dict[str, Diagnosis] = {}
    saw_unknown = False
    u_line, u_no = "", 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        name = classify_line(line)
        if name:
            if name not in matched:
                matched[name] = Diagnosis(
                    matched_pattern=name,
                    canonical_fix=CANONICAL_FIX[name],
                    confidence=CONFIDENCE[name],
                    auto_fixable=CONFIDENCE[name] > 0.0,
                    evidence_line=line.strip()[:240],
                    line_no=lineno,
                    source=source,
                )
            continue
        if _BENIGN.search(line):
            continue
        if _PROBLEM.search(line) and not saw_unknown:
            saw_unknown = True
            u_line, u_no = line.strip()[:240], lineno
    return matched, saw_unknown, u_line, u_no


def classify_log(text: str, drc_text: str = "") -> List[Diagnosis]:
    """Classify an OpenROAD P&R log (and optionally a DRC report).

    Deduplicated per pattern, UNKNOWN only for an unrecognised real error,
    [] for a clean/short log."""
    combined_len = len((text or "").strip()) + len((drc_text or "").strip())
    if combined_len < MIN_LOG_CHARS:
        return []

    matched: Dict[str, Diagnosis] = {}
    any_unknown = False
    u_line, u_no = "", 0
    for blob, src in ((text, "pnr_log"), (drc_text, "drc_report")):
        if not blob:
            continue
        m, su, ul, un = _scan(blob, src)
        for k, v in m.items():
            matched.setdefault(k, v)
        if su and not any_unknown:
            any_unknown, u_line, u_no = True, ul, un

    findings = list(matched.values())
    if any_unknown and not findings:
        findings.append(Diagnosis(
            matched_pattern="UNKNOWN",
            canonical_fix=CANONICAL_FIX["UNKNOWN"],
            confidence=CONFIDENCE["UNKNOWN"],
            auto_fixable=False,
            evidence_line=u_line,
            line_no=u_no,
        ))
    findings.sort(key=lambda d: (d.source, d.line_no))
    return findings


def diagnose(text: str, drc_text: str = "") -> Dict[str, Any]:
    findings = classify_log(text, drc_text)
    if not findings:
        verdict = "CLEAN"
    elif all(f.matched_pattern == "UNKNOWN" for f in findings):
        verdict = "MANUAL_REVIEW"
    else:
        verdict = "DIAGNOSED"
    return {
        "tool": "pnr_doctor",
        "verdict": verdict,
        "findings": [f.as_dict() for f in findings],
        "count": len(findings),
        "emitted_by": _pmd.emitted_by("pnr_doctor"),
    }


def report_to_text(result: Dict[str, Any], with_fix: bool) -> str:
    out = [f"pnr_doctor: {result['verdict']} "
           f"({result['count']} pattern(s) matched)"]
    for f in result["findings"]:
        out.append(
            f"  [{f['matched_pattern']}] conf={f['confidence']:.2f} "
            f"auto_fixable={f['auto_fixable']} "
            f"({f['source']} line {f['line_no']}): {f['evidence_line']}")
        if with_fix:
            out.append(f"      FIX: {f['canonical_fix']}")
    if result["verdict"] == "CLEAN":
        out.append("  No known error/violation signatures found.")
    return "\n".join(out)


def _cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="OpenROAD P&R-log error classifier (synth-doctor PnR analog).")
    p.add_argument("log", type=Path, help="OpenROAD P&R log file")
    p.add_argument("--drc", type=Path, help="Optional DRC report to also scan")
    p.add_argument("--fix", action="store_true",
                   help="Include the canonical fix recipe per finding")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.add_argument("--out-json", type=Path, help="Write JSON to this file")
    args = p.parse_args(argv)

    if not args.log.is_file():
        print(f"pnr_doctor: MISSING — log not found: {args.log}", file=sys.stderr)
        result = {"tool": "pnr_doctor", "verdict": "MISSING",
                  "findings": [], "count": 0,
                  "emitted_by": _pmd.emitted_by("pnr_doctor")}
        if args.json:
            print(json.dumps(result, indent=2))
        return 2

    drc_text = ""
    if args.drc:
        if args.drc.is_file():
            drc_text = args.drc.read_text(errors="replace")
        else:
            print(f"pnr_doctor: NOTE — DRC report not found, skipping: "
                  f"{args.drc}", file=sys.stderr)

    text = args.log.read_text(errors="replace")
    result = diagnose(text, drc_text)
    if args.out_json:
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(report_to_text(result, with_fix=args.fix))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
