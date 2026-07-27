#!/usr/bin/env python3
"""
otp_write_lock_gate_check.py — Static heuristic audit for OTP / fuse / NVM
write-enable assertions being gated by a lock-bit signal.

Rule (derived from v052 rtl/mac.v:280-295 and 358-385):

    A NON-volatile write (OTP/fuse/MTP/NVM) MUST be gated by a lock bit.
    The v052 E0 handler reads OTP[0x2E] LK byte first, decodes per-region
    lock flags (id_lk / imsn_lk / asn_lk), and only then asserts
    ``otp_we <= 1'b1``. Code that drives ``otp_we`` (or equivalent) with
    no ``lock`` / ``lk`` / ``wp`` token nearby is almost certainly unsafe.

NOTE:
    This is a STATIC HEURISTIC, not a formal proof. Every finding must be
    manually reviewed — eng-mode / factory-only RTL legitimately bypasses
    lock gating in controlled test flows.

Static check (IC-agnostic):

  1. Find every assignment of the form::

         <sig> <= 1'b1 ;          (non-blocking)
         <sig>  = 1'b1 ;          (blocking / continuous)

     where ``<sig>`` matches::

         \\b(otp|fuse|nvm|mtp|efuse)_(we|pwe|prog|wr_en|wen|write_en)\\b

  2. For each hit, scan ±30 lines around the hit for ANY of the tokens::

         lock | lk | locked | prot | protected | wp | write_protect
         | unlocked | authorized | eng_mode | key_stage

     ``eng_mode`` and ``key_stage`` explicitly count as lock-gates because
     they are the common "engineering bypass" signal — a site gated by
     eng_mode is NOT unguarded.

  3. Also accept "the enclosing ``if`` / ``case`` condition on the same
     line-block contains one of those tokens" as a gate.

  4. If NO nearby lock token is found, emit a finding at ERROR severity.

#496 — DENOMINATOR DISCLOSURE (classified: TRIGGER ABSENT FROM THIS CORPUS)
--------------------------------------------------------------------------
``write_enable_sites: 0`` on all 107 tracked ``rtl`` directories under
``benchmark-data``. Re-measured for #496 with a probe deliberately LOOSER than
the gate's own — any identifier matching
``(otp|fuse|efuse|nvm|mtp|eeprom|flash|nvram|ee)\\w*_?(we|wen|wr_en|write_en|
prog|pgm|pwe|program)\\w*`` anywhere in any file, with no line-shape, no
``1'b1`` literal and no assignment requirement — and it returns **0 hits in
0/107 directories**. There is no non-volatile memory write path in this corpus
at all, so there is nothing for the extraction to have missed.

This is therefore a valid rule with no coverage HERE, not a broken one. It is
kept, and its PASS now says "examined 0" rather than reading as "no unguarded
non-volatile write was found".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

import _gate_denominator as GD

# #496 — one unit of this gate's denominator, in the gate's own terms.
_DENOM_UNIT = "non-volatile write-enable assertion sites"


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    signal: str = ""
    details: str = ""


# Matches the LHS of a non-volatile write-enable being asserted to 1.
_WE_SET_RE = re.compile(
    r"^\s*"
    r"((?:otp|fuse|nvm|mtp|efuse)_(?:we|pwe|prog|wr_en|wen|write_en))"
    r"\s*(?:<=|=)\s*1'b1\s*;",
    re.IGNORECASE,
)

# Tokens that count as lock evidence. We allow these to appear either as
# a whole-word match OR embedded as a suffix inside a compound identifier
# (e.g. ``id_lk``, ``trim_locked``, ``otp_wp_en``) because Verilog
# designers routinely compose lock signals out of multiple tokens.
_LOCK_TOKEN_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])("
    r"lock|lk|locked|prot|protected|wp|write_protect|"
    r"unlocked|authorized|eng_mode|key_stage|factory|dbg_unlock"
    r")(?=$|[^A-Za-z0-9]|\w)",
    re.IGNORECASE,
)


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        [p for p in rtl_dir.rglob("*")
         if p.is_file() and p.suffix.lower() in (".v", ".sv")]
    )


def _denominator(summary: Dict, findings: List[Finding]) -> GD.Denominator:
    sites = summary.get("sites", 0)
    files = summary.get("files_scanned", 0)
    if sites:
        return GD.Denominator(unit=_DENOM_UNIT, examined=sites,
                              considered=sites,
                              details={"files_scanned": files})
    if any(f.category == "IO" for f in findings):
        reason = ("the RTL directory could not be read — nothing was "
                  "examined, so this is an input error, not a verdict.")
    elif files == 0:
        reason = "no readable .v/.sv file in this directory."
    else:
        reason = (
            f"{files} RTL file(s) read, none of which asserts a non-volatile "
            "write-enable. Searched for a statement of the form "
            "`(otp|fuse|nvm|mtp|efuse)_(we|pwe|prog|wr_en|wen|write_en) "
            "<= 1'b1;`. This design has no OTP / fuse / NVM write path, so "
            "the lock-gating rule has no subject here — this is 'examined 0', "
            "not 'no unguarded write found'.")
    return GD.Denominator(unit=_DENOM_UNIT, examined=0, considered=0,
                          not_applicable_reason=reason,
                          details={"files_scanned": files})


def audit(rtl_dir: Path, window: int = 30) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="IO",
            message=f"RTL directory not found: {rtl_dir}",
        ))
        return findings, {"sites": 0, "guarded": 0, "unguarded": 0,
                          "files_scanned": 0}

    sites = 0
    guarded = 0
    unguarded = 0
    files_scanned = 0

    for p in _find_v_files(rtl_dir):
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError as e:
            findings.append(Finding(
                severity="ERROR",
                category="IO",
                message=f"Cannot read file: {e}",
                file=str(p),
            ))
            continue
        # #496 — count only files actually READ, not the glob size.
        files_scanned += 1

        for i, line in enumerate(lines):
            m = _WE_SET_RE.match(line)
            if not m:
                continue
            sites += 1
            sig = m.group(1)

            lo = max(0, i - window)
            hi = min(len(lines), i + window + 1)
            ctx = "\n".join(lines[lo:hi])

            if _LOCK_TOKEN_RE.search(ctx):
                guarded += 1
                continue

            unguarded += 1
            findings.append(Finding(
                severity="ERROR",
                category="UNGATED_NV_WRITE",
                message=(
                    f"Non-volatile write-enable '{sig}' is asserted to "
                    "1'b1 with no lock/wp/eng_mode/key_stage token "
                    f"within ±{window} lines. Static heuristic — "
                    "manual review required."
                ),
                file=str(p),
                line=i + 1,
                signal=sig,
                details=line.strip(),
            ))

    return findings, {
        "sites": sites, "guarded": guarded, "unguarded": unguarded,
        "files_scanned": files_scanned,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], rtl_dir: Path, summary: Dict) -> Dict:
    return {
        "program": "otp_write_lock_gate_check",
        "version": "1.0.0",
        "note": ("static heuristic — not a formal proof; every finding "
                 "requires manual review"),
        "rtl_dir": str(rtl_dir),
        "summary": GD.attach({
            "write_enable_sites": summary["sites"],
            "guarded_sites": summary["guarded"],
            "unguarded_sites": summary["unguarded"],
            "files_scanned": summary.get("files_scanned", 0),
            "findings_count": len(findings),
            "pass": not any(f.severity == "ERROR" for f in findings),
        }, _denominator(summary, findings)),
        "findings": [asdict(f) for f in findings],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Flag OTP/fuse/NVM write-enable assertions that lack "
                     "a nearby lock-bit token (static heuristic).")
    )
    parser.add_argument("--rtl-dir", required=True,
                        help="Directory containing .v / .sv RTL files")
    parser.add_argument("--window", type=int, default=30,
                        help="Context window (lines) to search for lock "
                             "tokens around each write-enable site "
                             "(default 30).")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Optional path to write machine-readable report")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir, window=args.window)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    report = build_report(findings, rtl_dir, summary)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(report_json)

    print(report_json)
    # IO errors (missing RTL dir etc.) → exit 2 per the gate exit-code contract
    # (0 PASS / 1 FAIL / 2 input-missing).
    if any(getattr(f, "category", "") == "IO" for f in findings):
        return 2
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
