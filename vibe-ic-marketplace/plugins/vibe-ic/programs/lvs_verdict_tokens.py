#!/usr/bin/env python3
"""lvs_verdict_tokens.py — single source of truth for netgen LVS terminal-
verdict classification (ORGANIC #524, extends #507/#477).

WHY THIS MODULE EXISTS
----------------------
#507 added the terminal-verdict gate to `eda_report_audit._check_lvs` with the
explicit goal "gate and runner never disagree" — but the token list was
duplicated by hand across FOUR Python sites and drifted immediately:
`phase3_one_shot_runner.step_lvs` and `mixed_signal_top_lvs_run.run` never
received the `failed pin matching` token, so a report whose only terminal line
is `Final result: Top level cell failed pin matching.` (a CONCLUSIVE netgen
FAIL) was mis-classified as INCOMPLETE ("netgen produced no terminal verdict
token") by the runner while the Step-31 gate called it MISMATCH. #524 is that
drift. This module is the one place the tokens live; every Python consumer
imports it.

The semantics mirror the empirically-validated MCP-EDA classifier
(`mcp-eda/src/lib/netgen_verdict.mjs`), which confirmed in-container
(netgen 1.5.316) that:
  * `Top level cell failed pin matching.` is a terminal FAIL verdict;
  * `Property errors were found.` / `match uniquely with property errors` is a
    REAL FAIL even though netgen ALSO prints `Final result: Circuits match
    uniquely.` on the topology line (a transistor-property delta is an LVS
    fail);
  * a mismatch token is AUTHORITATIVE over any `match uniquely` token.

CLASSES
-------
  MATCH      — a real `Circuits/Netlists match uniquely` verdict and no
               mismatch token.
  MISMATCH   — any terminal mismatch token present (authoritative).
  INCOMPLETE — NEITHER token present: the compare did not run to completion
               (netgen killed mid-run / truncated report). Never upgraded to
               MATCH or MISMATCH (#477 honesty: an incomplete run is not a
               conclusive result in either direction).

chip-AGNOSTIC: pure netgen phrase classification; no design/cell literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List

# Genuine clean-match phrases — netgen's "match uniquely" wording, never the
# bare substring "match" (which also appears inside FAIL phrases like
# "failed pin matching").
MATCHED_RE = re.compile(
    r"Circuits?\s+match\s+uniquely|Netlists?\s+match\s+uniquely", re.I)

# Terminal mismatch phrases — ANY present means a real compare ran and FAILED,
# even if sub-cells (or the topology line) also printed "match uniquely".
MISMATCHED_RE = re.compile(
    r"do\s+not\s+match"
    r"|NET\s+MISMATCH"
    r"|failed\s+pin\s+matching"            # #524: netgen top-level pin FAIL
    r"|property\s+errors?\s+were\s+found"  # #524: netgen property FAIL
    r"|match\s+uniquely\s+with\s+property\s+errors"
    r"|失配", re.I)

# Pin-mismatch evidence lines netgen prints in the pin-correspondence table,
# e.g. `(no pin, node is o_sram_data[7])           |o_sram_wdata[7]`
# or    `o_data[3]                                 |(no matching pin)`.
# The `(no pin, node is …)` shape appears ONLY in the top-level failing table;
# the `(no matching pin)` shape ALSO appears as benign subcell power-pin rows
# (VGND/VPB/… absent from LEF abstracts) by the hundreds in clean reports.
_PIN_NODE_RE = re.compile(r"^.*\(no pin, node is [^)]*\).*$", re.M)
_PIN_NOMATCH_RE = re.compile(r"^.*\(no matching pin\).*$", re.M)

# A COMPLETED netgen compare always ends with a `Final result:` line; a
# `match uniquely` token without it is a per-subcell line of a hierarchical
# run that was killed before the top-level compare (mirrors the
# netgen_verdict.mjs guard).
_FINAL_RESULT_RE = re.compile(r"Final result\s*:", re.I)


def classify(blob: str) -> str:
    """Classify a netgen transcript+report blob → MATCH / MISMATCH / INCOMPLETE.

    A mismatch token is AUTHORITATIVE (checked first). A match token WITHOUT a
    `Final result:` line is a truncated hierarchical run (per-subcell match
    lines print long before the top-level compare) → INCOMPLETE, never MATCH."""
    if MISMATCHED_RE.search(blob):
        return "MISMATCH"
    if MATCHED_RE.search(blob) and _FINAL_RESULT_RE.search(blob):
        return "MATCH"
    return "INCOMPLETE"


# ── ORGANIC (GAP-E2E-9) — sub-classify a MISMATCH: benign OSS power-pin-only
# vs a real signal-net mismatch. The 7-IC end-to-end sweep showed netgen prints
# `Top level cell failed pin matching` (→ MISMATCH) on EVERY sky130 OSS run
# because the yosys gate netlist has NO power ports (VPWR/VGND/VPB/VNB) while the
# extracted layout carries per-cell power pins — a universal power-unaware-netlist
# vs power-extracted-layout SETUP artifact, NOT a design connectivity defect
# (measured: caravel + subservient LVS reports carry ONLY power-pin rows, 0
# signal-net rows). This sub-class lets the sign-off DISCLOSE that benign class
# for a reviewed waiver WITHOUT touching the authoritative MATCH/MISMATCH verdict.
#
# §4.05 NO-LEAK (load-bearing): `POWER_PIN_ONLY` is asserted ONLY when the mismatch
# evidence is EXCLUSIVELY power/tie nets. ANY signal-net evidence — a `(no pin,
# node is …)` row, a NON-power `(no matching pin)` port, or a property error —
# classifies `SIGNAL_NET_MISMATCH` and is NEVER waved through (measured: aes 517 +
# ibex 256 `(no pin, node is …)` rows collapse many top ports onto one node — an
# ambiguous tie-off/short that MUST stay a real mismatch, not a benign waiver).
# The verdict from classify() is UNCHANGED; this is triage metadata only.
_POWER_NET_RE = re.compile(
    r"^(?:VGND|VNB|VPB|VPWR|VCCD\d*|VSSD\d*|VDD[A-Z0-9]*|VSS[A-Z0-9]*"
    r"|VCC[A-Z0-9]*|GND[A-Z0-9]*|HI|LO|TIE_?HI|TIE_?LO)$", re.I)
_PROPERTY_ERR_RE = re.compile(r"property\s+errors?\s+were\s+found", re.I)


def _is_power_token(tok: str) -> bool:
    """True iff `tok` names a power/ground/tie net (sky130 VPWR/VGND/VPB/VNB,
    core/io VCCD*/VSSD*, generic VDD*/VSS*/GND*, or a tie-HI/LO net)."""
    return bool(_POWER_NET_RE.match((tok or "").strip()))


def mismatch_class(blob: str) -> str:
    """Sub-classify a netgen report → for triage ONLY (the classify() verdict is
    authoritative and unchanged). Returns:
      * 'NONE'                 — not a MISMATCH (MATCH / INCOMPLETE).
      * 'SIGNAL_NET_MISMATCH'  — a MISMATCH with real signal-net evidence
                                 (a `(no pin, node is …)` row, a NON-power
                                 `(no matching pin)` port, or a property error).
                                 NEVER a benign class — a reviewed waiver must not
                                 wave this through.
      * 'POWER_PIN_ONLY'       — a MISMATCH whose evidence is EXCLUSIVELY power/tie
                                 nets (the universal power-unaware-netlist OSS
                                 SETUP artifact) — a reviewed-waiver CANDIDATE, not
                                 a silent pass.
    chip-AGNOSTIC: pure netgen phrase + power-net-name classification."""
    if classify(blob) != "MISMATCH":
        return "NONE"
    # Real signal-net evidence → NOT benign (checked FIRST — §4.05 no-leak). The
    # RELIABLE top-level-real-mismatch signatures are the `(no pin, node is …)`
    # rows (netgen's top-level failure-table shape, per this module's established
    # semantics) and a device `property errors` line. A bare `(no matching pin)`
    # row is NOT signal evidence — it is dominated by BENIGN sub-cell abstraction
    # rows (power pins AND standard-cell pins like `Y`/`A`/`B`, absent from LEF
    # abstracts by the hundreds), so it must NOT drive the class.
    if _PROPERTY_ERR_RE.search(blob):
        return "SIGNAL_NET_MISMATCH"
    if _PIN_NODE_RE.search(blob):                 # `(no pin, node is …)` rows
        return "SIGNAL_NET_MISMATCH"
    # No top-level signal-failure rows. Confirm the mismatch carries the
    # power-unaware-netlist SETUP evidence (a power/tie `(no matching pin)` row OR
    # a `disconnected node: V*` line) before calling it the benign class; a
    # MISMATCH with no recognizable benign shape stays conservative (real).
    saw_power_row = bool(re.search(
        r"(?im)^\s*(?:VGND|VNB|VPB|VPWR|VCCD\d*|VSSD\d*|VDD[A-Z0-9]*|VSS[A-Z0-9]*"
        r"|VCC[A-Z0-9]*|GND[A-Z0-9]*|HI|LO)\s+\|\(no matching pin\)", blob))
    saw_power_row = saw_power_row or bool(re.search(
        r"disconnected node:\s*(?:VGND|VNB|VPB|VPWR|VCC|VSS|VDD|GND)",
        blob, re.I))
    return "POWER_PIN_ONLY" if saw_power_row else "SIGNAL_NET_MISMATCH"


def pin_mismatch_evidence(blob: str, max_lines: int = 8) -> List[str]:
    """Extract the netgen pin-correspondence mismatch lines (the readable
    evidence of WHICH pins failed matching) — at most `max_lines`, stripped.

    Prefers the `(no pin, node is …)` rows (top-level-failure-only shape) and
    takes them from the report TAIL, where the top-level table sits — the
    front of a big report is hundreds of benign subcell `(no matching pin)`
    power-pin rows that would otherwise drown the real evidence."""
    node_rows = [m.group(0).strip() for m in _PIN_NODE_RE.finditer(blob)]
    if node_rows:
        return node_rows[-max_lines:]
    nomatch_rows = [m.group(0).strip()
                    for m in _PIN_NOMATCH_RE.finditer(blob)]
    return nomatch_rows[-max_lines:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Classify a netgen LVS report's terminal verdict (#524).")
    ap.add_argument("report", help="netgen lvs report / transcript file")
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    args = ap.parse_args(argv)
    p = Path(args.report)
    if not p.is_file():
        print(f"ERROR: report not found: {p}", file=sys.stderr)
        return 2
    blob = p.read_text(errors="replace")
    verdict = classify(blob)
    out = {
        "report": str(p),
        "verdict": verdict,
        "mismatch_class": mismatch_class(blob),  # GAP-E2E-9 triage sub-class
        "pin_mismatch_evidence": pin_mismatch_evidence(blob),
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    # exit semantics: 0 only on a conclusive clean MATCH; 1 otherwise
    # (MISMATCH and INCOMPLETE both refuse sign-off — but the verdict string
    # distinguishes them for triage).
    return 0 if verdict == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
