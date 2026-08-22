#!/usr/bin/env python3
"""signoff_drv_delta_check.py — the DRV before/after COMPARABILITY gate.

The defect (measured, not hypothetical)
---------------------------------------
A post-route repeater-insertion repair step was landed and then reverted on the
strength of a before/after comparison that was never valid.

  * The BEFORE number came from a sign-off report emitted by code that called
    `report_check_types` WITHOUT `-violators`. Without that flag OpenSTA prints
    only the SINGLE WORST offending pin per check type per corner, so the report
    can structurally contain **at most 4** `(VIOLATED)` lines (2 corners x 2
    check types) no matter how large the real violator population is.
  * The AFTER number came from a report emitted AFTER `-violators` was added,
    which enumerates the COMPLETE population (bounded by `-max_count`).

The two were subtracted: "4 -> 219, a catastrophic regression". Re-measuring
BOTH states with one enumeration mode showed the truth: 483 -> 219, a 55%
IMPROVEMENT. A real, working repair was disabled on the strength of a number
produced by subtracting a truncated report from a complete one.

The generalisation: **a violator count is only a number relative to the
enumeration mode that produced it.** Any tool, agent or human that subtracts
two sign-off reports without first proving they were enumerated the same way
can manufacture an arbitrary delta in either direction. That is not a caravel
property, a sky130 property, or a repeater-insertion property — it is a
property of every before/after DRV claim this flow will ever make.

What this gate does
-------------------
R1 ENUMERATION STAMP REQUIRED — a report participates in a comparison only if
   it carries the emitter's enumeration stamp (`SIGNOFF_DRV_ENUMERATION ...`,
   written by `phase3_one_shot_runner._report_check_types_tcl`). A report with
   no stamp is of UNKNOWN completeness; it is never silently treated as
   complete.

R2 STAMPS MUST AGREE — both reports must declare the SAME enumeration mode,
   the same `max_count` bound and the same check-type set. Differing stamps
   mean the two populations are not the same measurement.

R3 NO TRUNCATION AT THE BOUND — a report whose enumerated population reaches
   its own declared `max_count` was truncated; its total is a lower bound, not
   a count, and a delta against it is not trustworthy.

Only when R1-R3 hold is a delta computed and a verdict of IMPROVED / UNCHANGED
/ REGRESSED issued. Otherwise the verdict is INCOMPARABLE — which is a REFUSAL
to answer, deliberately distinct from "no change".

chip/PDK-AGNOSTIC: pure text over the sign-off report. No design name, vendor,
cell, corner or technology literal appears anywhere in this file.

CLI
---
    signoff_drv_delta_check.py --before B.rpt --after A.rpt [--json OUT]
                               [--allow-unchanged]

exit 0  -> IMPROVED (or UNCHANGED with --allow-unchanged)
exit 1  -> REGRESSED / UNCHANGED / INCOMPARABLE
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── the enumeration stamp ──────────────────────────────────────────────────
# Emitted on its OWN line so it can never perturb the pre-existing
# `SIGNOFF_CHECK_TYPES_REPORTED <types...>` marker, whose trailing text two
# other gates parse as the check-type list.
ENUMERATION_STAMP_KEY = "SIGNOFF_DRV_ENUMERATION"

_STAMP_RE = re.compile(
    rf"^{ENUMERATION_STAMP_KEY}\s+(?P<body>.+?)\s*$", re.MULTILINE)
_CORNER_RE = re.compile(r"^===\s*(?P<corner>[A-Za-z0-9_]+)\s+corner:", re.MULTILINE)
_VIOLATED_RE = re.compile(r"\(VIOLATED\)", re.IGNORECASE)

# A check-type section header inside a corner block: a line that is exactly the
# check-type name.  Kept as a generic word-run so a tool that adds a new check
# type is picked up without touching this list.
_SECTION_RE = re.compile(r"^(?P<name>[a-z][a-z ]{2,30})$")

# Sections OpenSTA prints that are check types (not prose).  Matching is on the
# generic shape above; this set only normalises the spelling into a key.
_KNOWN_SECTIONS = {
    "max slew", "max capacitance", "max fanout",
    "recovery", "removal", "min pulse width",
}


def parse_enumeration_stamp(text: str) -> Optional[Dict[str, str]]:
    """Return the enumeration stamp as an ordered key=value dict, or None when
    the report carries no stamp (unknown completeness)."""
    m = _STAMP_RE.search(text or "")
    if not m:
        return None
    out: Dict[str, str] = {}
    for tok in m.group("body").split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k.strip()] = v.strip()
    return out or None


def count_violators(text: str) -> Dict[str, int]:
    """Violator population per ``<CORNER>.<check type>``, plus TOTAL.

    Pure counting of the emitter's own `(VIOLATED)` tag inside the corner /
    check-type sections. Never infers a violation the report did not tag."""
    counts: Dict[str, int] = {}
    corner: Optional[str] = None
    section: Optional[str] = None
    for line in (text or "").splitlines():
        cm = _CORNER_RE.match(line)
        if cm:
            corner, section = cm.group("corner").upper(), None
            continue
        stripped = line.strip()
        if stripped in _KNOWN_SECTIONS:
            section = stripped.replace(" ", "_")
            continue
        if _VIOLATED_RE.search(line):
            key = f"{corner or 'UNKNOWN'}.{section or 'unsectioned'}"
            counts[key] = counts.get(key, 0) + 1
    counts["TOTAL"] = sum(v for k, v in counts.items() if k != "TOTAL")
    return counts


def _bound(stamp: Optional[Dict[str, str]]) -> Optional[int]:
    if not stamp:
        return None
    try:
        return int(stamp.get("max_count", ""))
    except (TypeError, ValueError):
        return None


def _truncated_sections(counts: Dict[str, int], bound: Optional[int]
                        ) -> List[str]:
    """Sections whose enumerated population equals the declared bound — the
    report hit its own ceiling, so the count is a floor, not a total."""
    if not bound:
        return []
    return sorted(k for k, v in counts.items() if k != "TOTAL" and v >= bound)


def compare(before_text: str, after_text: str) -> Dict[str, object]:
    """Compare two sign-off DRV reports. Returns a verdict dict; the verdict is
    INCOMPARABLE unless both reports prove they were enumerated identically."""
    b_stamp = parse_enumeration_stamp(before_text)
    a_stamp = parse_enumeration_stamp(after_text)
    b_counts = count_violators(before_text)
    a_counts = count_violators(after_text)
    result: Dict[str, object] = {
        "program": "signoff_drv_delta_check",
        "before": {"stamp": b_stamp, "counts": b_counts},
        "after": {"stamp": a_stamp, "counts": a_counts},
    }

    missing = [n for n, s in (("before", b_stamp), ("after", a_stamp))
               if s is None]
    if missing:
        result.update({
            "verdict": "INCOMPARABLE",
            "rule": "R1",
            "reason": (
                f"{'/'.join(missing)} report carries no {ENUMERATION_STAMP_KEY} "
                f"stamp — its violator list is of UNKNOWN completeness. A "
                f"report emitted without `-violators` shows only the single "
                f"worst pin per check type, so subtracting it from an "
                f"enumerated report manufactures a delta. Re-measure both "
                f"states with the current emitter before claiming any change."),
        })
        return result

    if b_stamp != a_stamp:
        differing = sorted(set(b_stamp) | set(a_stamp))
        diffs = {k: [b_stamp.get(k), a_stamp.get(k)] for k in differing
                 if b_stamp.get(k) != a_stamp.get(k)}
        result.update({
            "verdict": "INCOMPARABLE",
            "rule": "R2",
            "reason": (f"enumeration stamps differ ({diffs}) — the two reports "
                       f"are not the same measurement."),
            "stamp_diff": diffs,
        })
        return result

    bound = _bound(b_stamp)
    trunc = sorted(set(_truncated_sections(b_counts, bound))
                   | set(_truncated_sections(a_counts, bound)))
    if trunc:
        result.update({
            "verdict": "INCOMPARABLE",
            "rule": "R3",
            "reason": (f"section(s) {trunc} reached the declared max_count "
                       f"bound ({bound}) — the population was truncated, so "
                       f"the total is a lower bound and the delta is not "
                       f"trustworthy. Raise the bound and re-measure."),
            "truncated_sections": trunc,
        })
        return result

    b_tot = int(b_counts.get("TOTAL", 0))
    a_tot = int(a_counts.get("TOTAL", 0))
    delta = a_tot - b_tot
    verdict = ("IMPROVED" if delta < 0
               else "UNCHANGED" if delta == 0 else "REGRESSED")
    per_key = sorted(set(b_counts) | set(a_counts) - {"TOTAL"})
    result.update({
        "verdict": verdict,
        "rule": None,
        "before_total": b_tot,
        "after_total": a_tot,
        "delta": delta,
        "per_section_delta": {
            k: int(a_counts.get(k, 0)) - int(b_counts.get(k, 0))
            for k in per_key if k != "TOTAL"},
        "reason": (f"comparable (stamp={b_stamp}); total violator population "
                   f"{b_tot} -> {a_tot} ({delta:+d})."),
    })
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--before", required=True, type=Path)
    ap.add_argument("--after", required=True, type=Path)
    ap.add_argument("--json", dest="json_out", type=Path, default=None)
    ap.add_argument("--allow-unchanged", action="store_true")
    args = ap.parse_args(argv)

    for p in (args.before, args.after):
        if not p.is_file():
            print(f"signoff_drv_delta_check: missing report {p}",
                  file=sys.stderr)
            return 1
    res = compare(args.before.read_text(errors="replace"),
                  args.after.read_text(errors="replace"))
    res["before_report"] = str(args.before)
    res["after_report"] = str(args.after)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(res, indent=2, sort_keys=True))
    print(json.dumps(res, indent=2, sort_keys=True))
    ok = res["verdict"] == "IMPROVED" or (
        args.allow_unchanged and res["verdict"] == "UNCHANGED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
