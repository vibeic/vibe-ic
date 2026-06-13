#!/usr/bin/env python3
"""rx_byte_assembler_ibt_flush_recovery_check.py — Wave 15 silent-bug gate.

When a single-bit drop occurs (RX glitch on a half-duplex single-wire
bit-bang protocol), the bit_assembler must have a flush / recovery
path: drop the partial byte and resync at the next BR. Without this,
ANY single-bit miss leaves bit_idx stuck mid-byte forever, the
`rx_byte_vld` strobe never fires, and the entire frame is lost.

Detection
=========
1. Find bit_assembler / byte_assembler RTL files. Heuristic:
     - filename hint `bit_assembler` / `byte_assembler` /
       `rx_assembler` / `rx_bit_assemb` / `rx_serdes`,
     - body heuristic: contains a `bit_idx` / `bit_cnt` counter
       AND an `rx_byte_vld` / `byte_done` / `byte_complete` /
       `rx_byte_done` / `byte_emit` strobe.
2. **PASS** when the file contains an explicit reset / flush of
   `bit_idx` (or partial-byte SR) gated on an IBT-overflow / IBT-
   exceeded / frame-timeout / ibt_max signal AND the gating happens
   when bit_idx is non-zero/incomplete:
     `if (ibt_overflow && bit_idx > 0 && bit_idx < 8) ... bit_idx <= 0;`
     `if (ibt_too_long && partial_byte) bit_idx <= 0;`
3. **FAIL** when the bit_idx counter resets ONLY on `clr` /
   `rx_br` / 8-bit-completion (no IBT-driven flush).
4. Honors waiver `rx_partial_byte_recovery_skipped` (≥40 chars).

Chip-AGNOSTIC.

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
from typing import List, Tuple
import _path_layout as _pl

WAIVER_KEY = "rx_partial_byte_recovery_skipped"
WAIVER_MIN_LEN = 40

_FILENAME_HINTS = (
    "bit_assembler", "byte_assembler", "rx_assembler",
    "rx_bit_assemb", "rx_serdes", "rx_shift",
)

_BYTE_VLD_NAMES = (
    "rx_byte_vld", "byte_done", "byte_complete", "rx_byte_done",
    "byte_emit", "byte_strobe", "byte_valid", "byte_out_vld",
)

_BIT_IDX_RE = re.compile(
    r"\bbit_(?:idx|cnt|n|index|num|count)\b",
    re.IGNORECASE,
)

# IBT-overflow / frame-timeout / frame-recovery class signals.
#
# Wave 35 (v0.119.67) — extended with `rx_br`, `frame_break`,
# `break_pulse`, `bus_br`, `frame_restart`, `frame_drop`. In
# half-duplex single-wire AID-class protocols (id_bus / kline / lin),
# the host issues a Break (BR) at every frame start; flushing the
# bit_assembler on `rx_br` IS the canonical partial-byte recovery
# mechanism — there is no separate "IBT" signal in many designs
# because BR collapses both semantics. Earlier regex missed this and
# false-positive FAILed any agent that didn't expose an IBT-specific
# signal.
_IBT_OVERFLOW_RE = re.compile(
    r"\b(?:"
    r"ibt_overflow|ibt_max|ibt_exceeded|ibt_too_long|"
    r"ibt_timeout|ibt_expired|frame_timeout|frame_end_pulse|"
    r"rx_ibt|ibt_pulse|ibt_now|byte_pending|partial_byte|"
    r"flush|ibt_flush|recovery|"
    r"rx_br|frame_break|break_pulse|bus_br|"
    r"frame_restart|frame_drop|abort_pulse"
    r")\b",
    re.IGNORECASE,
)

# Wave 35 (v0.119.67) — TX-named files (`tx_*`, `*_tx_*`) shouldn't
# count as bit-assemblers even when they accidentally have a
# bit-counter and a byte-strobe. The original body heuristic
# false-positived on `tx_phy.sv` because TX shifts also have
# bit_idx + byte_valid-class strobes.
_TX_FILENAME_HINTS = ("tx_phy", "tx_serdes", "tx_drv", "tx_pad",
                      "tx_shifter", "tx_emit", "tx_send",
                      "transmitter", "txfsm")


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


def is_byte_assembler(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    # Wave 35: positively-identify TX-path files and exclude them.
    if any(h in name for h in _TX_FILENAME_HINTS):
        return False
    if any(h in name for h in _FILENAME_HINTS):
        return True
    # Body fallback: bit_idx + byte_vld strobe pattern.
    if not _BIT_IDX_RE.search(src_no_cmt):
        return False
    return any(n in src_no_cmt for n in _BYTE_VLD_NAMES)


def has_ibt_flush_path(src_no_cmt: str) -> bool:
    """True when the file contains a bit_idx-reset branch gated by an
    IBT-overflow / partial-byte / flush signal."""
    # Search every `<= 0` / `<= '0` / `<= 4'd0` reset of the bit_idx
    # counter, walk backwards through containing if-conditions
    # (~400 chars), and check whether ANY mentions an IBT-overflow
    # class signal.
    for m in re.finditer(
        r"\bbit_(?:idx|cnt|n|index|num|count)\b\s*<=\s*"
        r"(?:'0|0|\d+\s*'\s*[bdh]?\s*0+|\d+)\s*;?",
        src_no_cmt,
        re.IGNORECASE,
    ):
        # Look at the preceding ~400 chars for an `if (...)` whose
        # condition contains an IBT-overflow class identifier.
        preamble = src_no_cmt[max(0, m.start() - 400): m.start()]
        for cm in re.finditer(
            r"(?:else\s+if|if)\s*\(([^)]+)\)",
            preamble,
        ):
            cond = cm.group(1)
            if _IBT_OVERFLOW_RE.search(cond):
                return True
    return False


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
            "Usage: rx_byte_assembler_ibt_flush_recovery_check.py "
            "<project_dir>"
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

    failures: List[str] = []
    assembler_count = 0

    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        if not is_byte_assembler(path, src):
            continue
        assembler_count += 1
        if not has_ibt_flush_path(src):
            try:
                rel = path.relative_to(project_dir)
            except ValueError:
                rel = path
            failures.append(
                f"NO_IBT_FLUSH_PATH — {rel}: bit-assembler counter "
                f"resets only on byte completion or block-clr, with "
                f"no IBT-overflow / partial-byte recovery branch. "
                f"A single-bit RX glitch will leave the bit counter "
                f"stuck mid-byte forever and the entire frame will "
                f"never emit."
            )

    if assembler_count == 0:
        print("SKIP — no bit_assembler / byte_assembler RTL detected")
        return 0

    is_waived, rationale = waived(project_dir)

    if not failures:
        print(
            f"PASS — {assembler_count} bit-assembler file(s) have "
            f"IBT-overflow flush / recovery path"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} missing-flush "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(
        f"FAIL — {len(failures)} bit-assembler missing-flush issue(s):"
    )
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  Without an IBT-driven partial-byte flush, any single-bit")
    print("  RX glitch leaves bit_idx stuck mid-byte. The byte_vld")
    print("  strobe never fires, the frame is lost, and the chip")
    print("  never reaches its CRC validation state. Symptom: silent")
    print("  hang on real silicon; sim PASSes because the TB's clean")
    print("  vectors don't reproduce the glitch.")
    print()
    print(
        "Fix template (inside the bit_assembler always_ff):\n"
        "    if (ibt_overflow && bit_idx > 0 && bit_idx < 8) begin\n"
        "        bit_idx      <= '0;\n"
        "        partial_byte <= '0;\n"
        "    end\n"
    )
    print(
        "Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
