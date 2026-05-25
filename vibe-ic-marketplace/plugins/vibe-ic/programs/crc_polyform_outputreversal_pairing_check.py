#!/usr/bin/env python3
"""crc_polyform_outputreversal_pairing_check.py — Wave 25 hardening gate.

When a CRC engine declares a polynomial form, the bit-feed direction
at the CRC input AND any output-reversal step on the wire must be
consistent. Two known-good pairings:

  - poly = 0x31 (non-reflected, MSB-first input):
      input must be MSB-first AND output MUST NOT have explicit
      bit-reverse (`{crc[0], crc[1], ..., crc[7]}`-style concat,
      or `reverse_bits(crc)` / `{<<{crc}}`).
  - poly = 0x8C (reflected = bit-reverse of 0x31, LSB-first input):
      input must be LSB-first AND output is in normal bit order
      (no reversal).

Detection
=========
1. Walk `<project>/rtl/*.{v,sv}` for files containing CRC-engine
   identifiers (file name or module name has `crc` substring, OR
   the body declares `localparam` / `parameter` whose value is
   8'h31 / 8'h8C).
2. Identify the CRC poly value used:
   - Look for `localparam ... CRC*POLY* = 8'hXX` or
     `parameter ... POLY = 8'hXX` patterns; XX in {31, 8C, 07, E0,
     1D, B8, …} (we only classify 0x31 vs 0x8C; other polynomials
     skip the check).
   - Or look for an inline literal `8'h31` / `8'h8C` used in a
     `feed`/`update`/`crc_step` shift-register expression.
3. Determine input bit-feed direction:
   - For 0x31 (non-reflected): expect left-shift LFSR — body
     contains `crc[6:0]` (or `shift_reg[6:0]`) on RHS of an
     assignment whose LHS is the same shift-register
     (`crc <= {crc[6:0], 1'b0} ^ ...` form).
   - For 0x8C (reflected): expect right-shift LFSR — body
     contains `crc[7:1]` (or `shift_reg[7:1]`) on RHS
     (`crc <= {1'b0, crc[7:1]} ^ ...` form).
4. Determine output reversal: scan the same file (and any sibling
   `tx_phy*` / `main_fsm*` / `mac*` file in `rtl/`) for either:
   - `{crc[0], crc[1], crc[2], ..., crc[7]}` ascending-index
     concat → REVERSED output, OR
   - `reverse_bits(crc)` / `{<<{crc}}` / `{<<1{crc}}` →
     REVERSED output, OR
   - direct assignment `tx_byte <= crc;` / `out_reg <= crc[7:0];` →
     DIRECT output (no reversal).
5. Verdict:
     PASS  — (poly==0x31, input==MSB, output==DIRECT) or
              (poly==0x8C, input==LSB, output==DIRECT) or
              (poly==0x31, input==MSB, output==REVERSED with
               explicit pairing — vendor 0x31 + load-reversal form).
     FAIL  — poly==0x8C with MSB-first input (reflected poly
              expects LSB-first feed; mismatch = wrong wire-level
              CRC). Or poly==0x31 with LSB-first input.
     SKIP  — no CRC files / no recognised poly / cannot classify
              direction.
6. Honors waiver `crc_polyform_intentional_pairing` (≥ 40 chars).

Chip-AGNOSTIC. No protocol / chip identifiers hardcoded.

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER
1 — FAIL
2 — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "crc_polyform_intentional_pairing"
WAIVER_MIN_LEN = 40

_POLY_PARAM_RE = re.compile(
    r"\b(?:localparam|parameter)\b[^;]*?"
    r"\b(?:CRC[A-Z0-9_]*POLY|POLY[A-Z0-9_]*|G[A-Z0-9_]*POLY)"
    r"[A-Z0-9_]*\s*=\s*8'h([0-9A-Fa-f]{1,2})\s*;",
)
_POLY_INLINE_RE = re.compile(r"8'h(31|8C|8c)\b")


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.exists():
        return []
    out: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".v", ".sv", ".svh"):
            out.append(p)
    return sorted(out)


def _is_crc_file(path: Path, text: str) -> bool:
    name = path.stem.lower()
    if "crc" in name:
        return True
    if re.search(r"\bmodule\s+\w*crc\w*\b", text, re.IGNORECASE):
        return True
    return False


def _detect_poly(text: str) -> Optional[str]:
    """Return '0x31' or '0x8C' if recognized, else None."""
    for m in _POLY_PARAM_RE.finditer(text):
        v = m.group(1).upper()
        if v == "31":
            return "0x31"
        if v == "8C":
            return "0x8C"
    # Fallback: inline literal in shift-register XOR expression.
    if re.search(
        r"(?:crc|shift_reg|lfsr|reg_q)\s*\[?[0-9:]*\]?\s*\^\s*8'h31\b",
        text, re.IGNORECASE,
    ):
        return "0x31"
    if re.search(
        r"(?:crc|shift_reg|lfsr|reg_q)\s*\[?[0-9:]*\]?\s*\^\s*8'h8[Cc]\b",
        text, re.IGNORECASE,
    ):
        return "0x8C"
    # Generic: any 8'h31 or 8'h8C in the file's CRC-relevant code.
    inline = _POLY_INLINE_RE.search(text)
    if inline:
        v = inline.group(1).upper()
        if v == "31":
            return "0x31"
        if v in ("8C",):
            return "0x8C"
    return None


def _detect_input_direction(text: str) -> Optional[str]:
    """Return 'MSB' / 'LSB' / None — based on shift LFSR direction.

    Reflected (LSB-first) LFSR: `crc <= {1'b0, crc[7:1]} ^ ...`
    Non-reflected (MSB-first) LFSR: `crc <= {crc[6:0], 1'b0} ^ ...`
    """
    # Right-shift = LSB-first feed.
    if re.search(
        r"\{[^{}]*1'b0[^{}]*,\s*"
        r"(?:crc|shift_reg|lfsr|reg_q|crc_q)\s*\[7:1\][^{}]*\}",
        text,
    ):
        return "LSB"
    # Left-shift = MSB-first feed.
    if re.search(
        r"\{[^{}]*"
        r"(?:crc|shift_reg|lfsr|reg_q|crc_q)\s*\[6:0\]\s*,"
        r"[^{}]*1'b0[^{}]*\}",
        text,
    ):
        return "MSB"
    return None


def _detect_output_reversal(text: str, crc_signal: str = "crc") -> str:
    """Return 'REVERSED', 'DIRECT', or 'UNKNOWN'."""
    # Ascending-index concatenation reverses bit order.
    asc_re = re.compile(
        r"\{[^{}]*\b" + re.escape(crc_signal) + r"\s*\[\s*0\s*\]"
        r"[^{}]*\b" + re.escape(crc_signal) + r"\s*\[\s*7\s*\]"
        r"[^{}]*\}",
    )
    if asc_re.search(text):
        return "REVERSED"
    # Streaming reversal operator.
    if re.search(
        r"\{\s*<<\s*1?\s*\{\s*" + re.escape(crc_signal) + r"\s*\}\s*\}",
        text,
    ):
        return "REVERSED"
    # Function-style.
    if re.search(
        r"(?:reverse_bits|bit_reverse|rev_bits)\s*\(\s*"
        + re.escape(crc_signal) + r"\s*\)",
        text,
    ):
        return "REVERSED"
    # Direct full-byte assignment.
    if re.search(
        r"<=\s*" + re.escape(crc_signal) + r"\s*;",
        text,
    ):
        return "DIRECT"
    if re.search(
        r"<=\s*" + re.escape(crc_signal) + r"\s*\[\s*7\s*:\s*0\s*\]\s*;",
        text,
    ):
        return "DIRECT"
    # v1.6.187 (#72 P0-2 slice 6/8) — canonical reflected-CRC
    # multi-hop pattern: CRC value is stored into a tx_buf[N]
    # entry via the LFSR-update expression, then driven onto
    # tx_byte via `tx_byte <= tx_buf[idx]`. The whole-byte value
    # flows without any bit-reversal step, so the wire-order
    # matches the LFSR output. Recognise this as DIRECT
    # (chip-AGNOSTIC: pattern is structural — a tx-buffer slot
    # receives an LFSR expression whose register name matches the
    # crc-signal alias, with no ascending-index concat in the
    # same RHS).
    multi_hop_lfsr_to_txbuf = re.compile(
        r"\btx_buf\s*\[\s*\d+\s*\]\s*<=\s*"
        r"\{[^{}]*1'b0\s*,\s*"
        + re.escape(crc_signal) + r"\s*\[\s*7\s*:\s*1\s*\]"
        r"[^{}]*\}",
    )
    if multi_hop_lfsr_to_txbuf.search(text):
        return "DIRECT"
    return "UNKNOWN"


def _waived(project: Path) -> Tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        rationale = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def inspect(project: Path) -> Tuple[List[str], List[str], dict]:
    failures: List[str] = []
    warnings: List[str] = []
    summary: dict = {}

    rtl = _find_rtl_files(project)
    if not rtl:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, warnings, summary

    crc_files: List[Tuple[Path, str]] = []
    for f in rtl:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        text = _strip_comments(raw)
        if _is_crc_file(f, text):
            crc_files.append((f, text))

    if not crc_files:
        summary["skip_reason"] = "no CRC RTL file found in rtl/"
        return failures, warnings, summary

    # Combine all RTL text for output-reversal detection — output
    # reversal usually lives in tx_phy / main_fsm, not the CRC file.
    all_text = ""
    for f in rtl:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        all_text += "\n" + _strip_comments(raw)

    summary["crc_files"] = [str(f.relative_to(project))
                            for f, _ in crc_files]

    classified_any = False
    for f, text in crc_files:
        try:
            rel = f.relative_to(project)
        except ValueError:
            rel = f
        poly = _detect_poly(text)
        if poly is None:
            continue
        direction = _detect_input_direction(text)
        if direction is None:
            continue

        classified_any = True

        # Output reversal detection — search both this file and the
        # whole project text for a load of `crc` or `crc_out` /
        # `crc_q` / `crc_result` / `crc_local` (canonical AID-class
        # LFSR alias added v1.6.187 #72 P0-2 slice 6/8).
        out_rev = "UNKNOWN"
        for sig in ("crc_out", "crc_q", "crc_result", "crc8_result",
                    "crc_local", "crc_byte", "crc"):
            r = _detect_output_reversal(all_text, sig)
            if r != "UNKNOWN":
                out_rev = r
                break

        summary.setdefault("classifications", []).append({
            "file": str(rel),
            "poly": poly,
            "input_direction": direction,
            "output_reversal": out_rev,
        })

        # FAIL conditions.
        if poly == "0x8C" and direction == "MSB":
            failures.append(
                f"CRC_POLYFORM_PAIRING_MISMATCH — {rel}: poly = "
                f"0x8C (reflected) declared but input bit-feed is "
                f"MSB-first (left-shift LFSR). Reflected polynomial "
                f"requires LSB-first input — wire-level CRC will "
                f"differ from spec. Either change to non-reflected "
                f"poly (0x31) with MSB-first input, or use "
                f"right-shift LFSR (`crc <= {{1'b0, crc[7:1]}} ^ "
                f"...`) for LSB-first input."
            )
        elif poly == "0x31" and direction == "LSB":
            failures.append(
                f"CRC_POLYFORM_PAIRING_MISMATCH — {rel}: poly = "
                f"0x31 (non-reflected) declared but input bit-feed "
                f"is LSB-first (right-shift LFSR). Non-reflected "
                f"polynomial expects MSB-first feed — wire-level "
                f"CRC will differ from spec."
            )
        # Output reversal pairing check.
        if poly == "0x8C" and direction == "LSB" and out_rev == "REVERSED":
            failures.append(
                f"CRC_POLYFORM_PAIRING_MISMATCH — {rel}: poly = "
                f"0x8C (reflected, LSB-first) with REVERSED output "
                f"load (`{{crc[0], …, crc[7]}}` or `{{<<{{crc}}}}`). "
                f"Reflected algorithm already produces wire-ready "
                f"bit order; an explicit reversal double-flips the "
                f"output."
            )

    if not classified_any:
        summary["skip_reason"] = (
            "no recognised poly (0x31 / 0x8C) + classifiable "
            "shift direction in any CRC RTL file"
        )

    return failures, warnings, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: crc_polyform_outputreversal_pairing_check.py "
            "<project_dir> [--json <out>]"
        )
        return 0 if (len(argv) >= 2 and argv[1] in ("-h", "--help")) else 2

    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    json_out: Optional[Path] = None
    if "--json" in argv:
        idx = argv.index("--json")
        if idx + 1 < len(argv):
            json_out = Path(argv[idx + 1])

    failures, warnings, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program":
                "crc_polyform_outputreversal_pairing_check",
            "passed": not failures,
            "warnings": warnings,
            "summary": summary,
            "failures": failures,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures and not warnings:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures and not warnings:
        cls = summary.get("classifications", [])
        if cls:
            ev = (
                f"{cls[0]['poly']} + {cls[0]['input_direction']}-first "
                f"input + {cls[0]['output_reversal']} output"
            )
            print(f"PASS — CRC poly/direction/output paired: {ev}.")
        else:
            print("PASS — CRC poly/direction/output paired correctly.")
        return 0

    if not failures and warnings:
        for w in warnings:
            print(f"WARN — {w}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        return 0

    print(f"FAIL — {len(failures)} CRC poly-form pairing issue(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
    print()
    print("Why this matters:")
    print(
        "  CRC polynomial form must be paired with the correct\n"
        "  bit-feed direction. Reflected poly (0x8C) expects\n"
        "  LSB-first input; non-reflected poly (0x31) expects\n"
        "  MSB-first input. Mismatch produces wire-level CRC\n"
        "  values that do not match the spec — host CRC residue\n"
        "  ≠ 0, frame rejected, silent FAIL."
    )
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
