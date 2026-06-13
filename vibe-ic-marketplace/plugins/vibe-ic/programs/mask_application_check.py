#!/usr/bin/env python3
"""
mask_application_check.py — Verify any AND-mask rule the spec declares
is honoured by RTL: the masked value (not the raw byte) is what gets
stored AND echoed back in any response.

THE PROBLEM
-----------
The vendor-class spec said "payload byte1 must be AND'd with 0xE8 before
storing". The agent's RTL stored the raw byte, ignoring the mask.
Read-back commands echoed the raw byte. Lint, sim with masked stimuli,
and CRC all PASSed because the TB happened to feed pre-masked values.

This gate cross-references mask declarations (from a JSON spec or
``--mask`` repeat) against the RTL and reports any storage path or
response builder that doesn't apply the mask.

INPUTS
------
A mask spec — one of:
  a. ``--masks <masks.json>``::
       [
         {"signal": "payload_byte1", "and_mask": "0xE8"},
         {"signal": "cfg_word",      "and_mask": "0x00FF"}
       ]
  b. CLI repeats: ``--mask "payload_byte1 AND 0xE8"`` (may repeat).

RTL HEURISTICS
--------------
For each (signal, mask) pair, scan all assignments to a register or
storage variable that derive from the signal. Allow:
  reg_q <= payload_byte1 & 8'hE8;
  reg_q <= mask_byte(payload_byte1);     // any explicit mask helper
  reg_q <= {payload_byte1[7], payload_byte1[5], ..., 1'b0};  // explicit
                                                              // bit-build

Reject:
  reg_q <= payload_byte1;                // raw, no mask
  rsp_byte = payload_byte1;              // raw echo

USAGE
-----
    python3 mask_application_check.py rtl/ \\
        --mask "payload_byte1 AND 0xE8" \\
        --json reports/gates/mask.json

EXIT CODES
----------
    0 — every named signal is masked before being stored or echoed.
    1 — at least one storage / echo site uses the raw signal.
    2 — IO / argument error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str


def _normalise_mask_arg(s: str) -> Optional[Dict[str, str]]:
    m = re.match(r"^\s*([\w.]+)\s+(?:AND|&|and)\s+(0x[0-9a-fA-F_]+|\d+)\s*$",
                 s)
    if not m:
        return None
    return {"signal": m.group(1), "and_mask": m.group(2)}


def _parse_mask_value(v: str) -> Optional[int]:
    try:
        return int(v.replace("_", ""), 0)
    except Exception:
        return None


def audit(rtl_target: Path,
          masks: List[Dict[str, str]]) -> List[Finding]:
    findings: List[Finding] = []
    if rtl_target.is_file():
        files = [rtl_target]
    else:
        files = sorted(list(rtl_target.rglob("*.v")) + list(rtl_target.rglob("*.sv")))
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files", str(rtl_target), 0,
            f"no .v/.sv under {rtl_target}",
        ))
        return findings

    # Compile per-mask patterns
    compiled: List[Tuple[str, int, re.Pattern]] = []
    for entry in masks:
        sig = entry.get("signal", "").strip()
        mask = entry.get("and_mask", "")
        mask_int = _parse_mask_value(mask) if isinstance(mask, str) else None
        if not sig or mask_int is None:
            continue
        compiled.append((sig, mask_int, re.compile(r"\b" + re.escape(sig) + r"\b")))

    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        bare = re.sub(r"//[^\n]*", "", no_block)
        # Look at every assignment / non-blocking assignment statement
        # whose RHS contains the signal.
        # Pattern A: assign / "<lhs> = / <= /  RHS;"
        for stmt_match in re.finditer(
            r"(?:assign\s+)?\b(\w[\w\.\[\]:]*)\s*(<=|=)\s*([^;]+);",
            bare, re.MULTILINE,
        ):
            lhs = stmt_match.group(1)
            rhs = stmt_match.group(3)
            line_no = bare.count("\n", 0, stmt_match.start()) + 1
            for sig, mask_int, sig_re in compiled:
                if not sig_re.search(rhs):
                    continue
                # Acceptable if RHS contains "<sig> & <num>" or "& <sig>"
                # with the right hex mask.
                mask_seen = False
                for m_and in re.finditer(
                    r"&\s*(?:" + re.escape(sig) + r"|"
                    r"(?:\d+'[bohdBOHD][0-9a-fA-F_]+|0x[0-9a-fA-F_]+|\d+))",
                    rhs,
                ):
                    surround = rhs[max(0, m_and.start() - 40):m_and.end() + 40]
                    if sig in surround:
                        # Look for the mask number in surround
                        for num_m in re.finditer(
                            r"(?:(\d+)'[hH]([0-9a-fA-F_]+)|"
                            r"(\d+)'[bB]([01_]+)|"
                            r"0x([0-9a-fA-F_]+)|"
                            r"\b(\d+)\b)", surround,
                        ):
                            v = None
                            try:
                                if num_m.group(2):
                                    v = int(num_m.group(2).replace("_", ""), 16)
                                elif num_m.group(4):
                                    v = int(num_m.group(4).replace("_", ""), 2)
                                elif num_m.group(5):
                                    v = int(num_m.group(5).replace("_", ""), 16)
                                elif num_m.group(6):
                                    v = int(num_m.group(6))
                            except Exception:
                                v = None
                            if v == mask_int:
                                mask_seen = True
                                break
                # Also accept explicit per-bit reconstruction:
                # `{sig[N], sig[M], 1'b0, ...}` — check each used bit is
                # within the mask's set bits. (Skip for now — reconstruct
                # as WARN.)
                if not mask_seen:
                    findings.append(Finding(
                        severity="ERROR",
                        rule="mask_not_applied",
                        file=str(f),
                        line=line_no,
                        message=(
                            f"assignment '{lhs} {stmt_match.group(2)} ...{sig}...;' "
                            f"references {sig!r} on the RHS but does not apply "
                            f"the spec-required AND-mask 0x{mask_int:X}. The "
                            f"raw value will be stored or echoed; the bug is "
                            f"silent under masked-input TBs."
                        ),
                    ))
                    break  # one finding per signal per stmt is enough
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file or directory")
    ap.add_argument("--masks", help="JSON: list of {signal, and_mask}")
    ap.add_argument("--mask", action="append", default=[],
                    help="Inline 'SIGNAL AND 0xNN' (repeatable)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    masks: List[Dict[str, str]] = []
    if args.masks:
        try:
            payload = json.loads(Path(args.masks).read_text())
            if isinstance(payload, list):
                masks.extend(payload)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    for s in args.mask:
        norm = _normalise_mask_arg(s)
        if norm is None:
            print(f"error: cannot parse --mask {s!r}", file=sys.stderr)
            return 2
        masks.append(norm)

    if not masks:
        print("error: no masks supplied (--masks or --mask)", file=sys.stderr)
        return 2

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, masks)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "masks_checked": len(masks),
        "errors": len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
