#!/usr/bin/env python3
"""rx_ibt_frame_end_semantics_check.py — Wave 15 silent-bug gate.

Catches the conflation of byte-boundary detection (use IBT_MIN) vs
frame-end detection (use IBT_MAX) in half-duplex single-wire protocols.

Why this gate exists
====================
A half-duplex bit-bang protocol typically defines TWO inter-byte-time
thresholds:

  - IBT_MIN  — minimum LOW-gap that signals a byte boundary. The RX
               bit assembler uses this to know "we've completed one
               byte; latch the shift register and start a new byte".
  - IBT_MAX  — maximum LOW-gap before the host concludes the frame
               has ended. The frame-end FSM uses this to transition
               from S_RX → S_VALIDATE.

A common silent bug is for the agent to use the SAME threshold for
both, e.g.:

    if (ibt_cnt > IBT_MAX) begin
        byte_done  <= 1'b1;   // byte boundary
        frame_end  <= 1'b1;   // frame end
    end

This collapses byte-boundary and frame-end onto a single condition.
The chip then either:
  (a) waits IBT_MAX (e.g. 40 µs) before recognising any byte boundary
      → host has already moved on by then, and the chip's CRC snapshot
      timing slips, or
  (b) the chip never advances byte_idx mid-frame because the
      threshold is too high → frame stuck.

Detection
=========
1. Find RX RTL files containing `IBT` / `inter_bit` / `inter_byte`
   references.
2. Locate threshold-gated emit statements:
     `if (... THRESHOLD_NAME ...) begin ... <signal> <= 1; ... end`
   where `<signal>` matches byte-boundary or frame-end name families.
3. **FAIL** when the same threshold value (or the same constant
   identifier) is used for BOTH a byte-boundary signal AND a
   frame-end signal.
4. **PASS** when distinct triggers are wired:
     - byte-boundary on an IBT_MIN-class threshold,
     - frame-end on an IBT_MAX-class threshold.
5. Honors waiver `rx_ibt_single_threshold_intentional` (≥40 chars).

Chip-AGNOSTIC: no <chip-class> / <benchmark> / <half-duplex-tester> / VENDOR / specific tick
value hard-coded.

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "rx_ibt_single_threshold_intentional"
WAIVER_MIN_LEN = 40

_BYTE_BOUNDARY_NAMES = (
    "byte_done", "byte_complete", "byte_valid", "byte_ready",
    "byte_boundary", "byte_end", "rx_byte_vld", "rx_byte_done",
    "byte_strobe", "rx_byte", "byte_emit",
)

_FRAME_END_NAMES = (
    "frame_end", "frame_done", "frame_complete", "rx_ibt",
    "frame_eof", "eof", "end_of_frame", "frame_boundary",
    "rx_frame_end", "frame_strobe",
)

_IBT_REF_RE = re.compile(
    r"\b(?:IBT|inter_bit|inter_byte|ibt_)\w*",
    re.IGNORECASE,
)


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def find_rtl_files(project_dir: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    files: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            files.append(p)
    return sorted(files)


def has_ibt_logic(src_no_cmt: str) -> bool:
    return bool(_IBT_REF_RE.search(src_no_cmt))


def _emit_branches(src_no_cmt: str) -> List[Tuple[str, str, int]]:
    """Find `if (<cond>) ... <signal> <= 1` style branches.

    Returns list of (cond, sig_name, char_offset).
    """
    out: List[Tuple[str, str, int]] = []
    for m in re.finditer(
        r"if\s*\(\s*([^)]+?)\s*\)\s*begin\b"
        r"(?P<body>(?:[^\{}]|\{[^}]*\})*?)\bend\b",
        src_no_cmt,
        re.DOTALL,
    ):
        cond = m.group(1)
        body = m.group("body")
        for sm in re.finditer(
            r"\b([A-Za-z_]\w*)\s*<=\s*1'?b?1\b",
            body,
        ):
            sig = sm.group(1)
            out.append((cond, sig, m.start()))
    # Also catch bare-line `signal <= 1'b1;` outside an `if begin/end`
    # but still inside an `if (...)` statement-form. We accept noise:
    # the gate's verdict only cares whether SAME cond drives both.
    return out


def _classify_signal(name: str) -> Optional[str]:
    n = name.lower()
    for h in _BYTE_BOUNDARY_NAMES:
        if h in n:
            return "byte"
    for h in _FRAME_END_NAMES:
        if h in n:
            return "frame"
    return None


def _ibt_constant_in_cond(cond: str) -> Optional[str]:
    """Return the IBT-class THRESHOLD identifier mentioned in cond.

    Walks all identifiers in cond. Prefers identifiers that look like
    thresholds (contain MAX/MIN/THRESHOLD/LIMIT/TICKS as a substring)
    over plain counter identifiers (contain CNT/COUNT/REG without a
    threshold suffix). This avoids treating `ibt_cnt` as the "shared
    threshold" — it's the running counter, not the comparison value.
    """
    candidates: List[str] = []
    for m in re.finditer(
        r"\b([A-Za-z_]\w*)\b",
        cond,
    ):
        ident = m.group(1)
        if re.search(
            r"(?:IBT|INTER_BIT|INTER_BYTE)",
            ident,
            re.IGNORECASE,
        ):
            candidates.append(ident)
    if not candidates:
        return None
    # Prefer threshold-like names.
    threshold_like = [
        c for c in candidates
        if re.search(
            r"(?:MAX|MIN|THRESHOLD|LIMIT|TICKS|CYC|PERIOD)",
            c,
            re.IGNORECASE,
        )
    ]
    if threshold_like:
        return threshold_like[0].lower()
    # Otherwise skip pure counter identifiers — return None to
    # signal "no comparison threshold detected".
    counter_like = [
        c for c in candidates
        if re.search(
            r"(?:CNT|COUNT|REG)",
            c,
            re.IGNORECASE,
        )
    ]
    non_counter = [c for c in candidates if c not in counter_like]
    if non_counter:
        return non_counter[0].lower()
    return None


def waived(project_dir: Path) -> Tuple[bool, str]:
    waivers = project_dir / "waivers.json"
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


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: rx_ibt_frame_end_semantics_check.py <project_dir>"
        )
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    rtl_files = find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    # Look in every RTL file for IBT references; collect emit branches.
    rx_files: List[Tuple[Path, str]] = []
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        if has_ibt_logic(src):
            rx_files.append((path, src))

    if not rx_files:
        print("SKIP — no IBT / inter-bit / inter-byte logic detected")
        return 0

    # For each file, gather (sig_class, ibt_const, cond) tuples.
    failures: List[str] = []
    distinct_pairs_found = False

    for path, src in rx_files:
        try:
            rel = path.relative_to(project_dir)
        except ValueError:
            rel = path
        emits = _emit_branches(src)

        # Bucket by ibt-constant.
        by_const: dict = {}  # const_name -> dict(byte=[(cond,sig)], frame=[(cond,sig)])
        for cond, sig, _ofs in emits:
            const = _ibt_constant_in_cond(cond)
            if const is None:
                continue
            cls = _classify_signal(sig)
            if cls is None:
                continue
            slot = by_const.setdefault(const, {"byte": [], "frame": []})
            slot[cls].append((cond.strip(), sig))

        # SHARED-threshold detection: same constant drives both classes.
        for const, slot in by_const.items():
            if slot["byte"] and slot["frame"]:
                bsig = slot["byte"][0][1]
                fsig = slot["frame"][0][1]
                failures.append(
                    f"SHARED_IBT_THRESHOLD — {rel}: constant "
                    f"`{const}` drives BOTH byte-boundary signal "
                    f"`{bsig}` AND frame-end signal `{fsig}`. "
                    f"IBT_MIN is the byte-boundary threshold; "
                    f"IBT_MAX is the frame-end threshold; they MUST "
                    f"be distinct."
                )

        # PASS hint: distinct min/max constants drive distinct
        # signal classes.
        byte_consts = {
            c for c, s in by_const.items() if s["byte"]
        }
        frame_consts = {
            c for c, s in by_const.items() if s["frame"]
        }
        if byte_consts and frame_consts and \
           byte_consts.isdisjoint(frame_consts):
            distinct_pairs_found = True

    is_waived, rationale = waived(project_dir)

    if failures:
        if is_waived:
            print(
                f"PASS_WITH_WAIVER — {len(failures)} shared-IBT-"
                f"threshold issue(s) silenced by "
                f"waivers.{WAIVER_KEY}: {rationale[:80]}…"
            )
            for f in failures:
                print(f"  • {f}")
            return 0
        print(
            f"FAIL — {len(failures)} shared-IBT-threshold issue(s):"
        )
        for f in failures:
            print(f"  • {f}")
        print()
        print("Why this matters:")
        print("  Conflating IBT_MIN (byte boundary) with IBT_MAX")
        print("  (frame end) onto a single threshold collapses the")
        print("  protocol's two-tier inter-byte timing model. Either")
        print("  the chip waits the full frame-end window before")
        print("  acknowledging each byte (host already moved on), or")
        print("  it terminates frames mid-byte. Use distinct triggers.")
        print()
        print(
            "Or document an alternative in waivers.json:\n"
            f'    {{"{WAIVER_KEY}": '
            '"<≥40-char rationale>"}}'
        )
        return 1

    if distinct_pairs_found:
        print(
            "PASS — distinct IBT thresholds drive byte-boundary vs "
            "frame-end signals"
        )
    else:
        print(
            "PASS — no shared-IBT-threshold conflation detected "
            "(byte-boundary / frame-end emit pattern not matched, "
            "no FAIL conditions met)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
