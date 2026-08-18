#!/usr/bin/env python3
"""wake_gen_bus_active_reset_check.py — Wave 15 silent-bug gate.

A periodic wake-pulse generator (typical: 5 ms maintenance heartbeat
on a half-duplex single-wire bus) must SUPPRESS its pulse when the
bus is currently active — otherwise the wake LOW collides with host
BR / TX / RX activity, the OR-of-LOW on the open-drain bus appears
as a long-low to the host, and the host re-classifies BR/IBT and
resets its frame state.

Detection
=========
1. Find wake-pulse generator RTL files. Heuristic:
     - filename hint `wake_gen` / `wake_ctrl` / `wake_pulse` /
       `wake_drv` / `wake_fsm` / `wake_emit`,
     - OR body heuristic: contains a periodic counter pattern
       AND drives a `wake_oe` / `wake_pulse` / `wake_drv` / `wake_o`
       output.
2. **PASS** when wake-pulse-emit logic gates on (or resets the
   counter from) a `bus_active` / `bus_idle` / `bus_busy` /
   `rx_active` / `tx_active` / `rx_byte_vld` / `rx_br` family
   signal. Either:
     (a) the counter is reset under `if (bus_active) cnt <= 0;`,
     (b) the wake_oe-emit branch is gated by `if (bus_idle && ...)`,
     (c) the module exposes a `bus_active` / `rx_active` / `tx_active`
         input port AND that input appears in the wake-emit path.
3. **FAIL** when wake-emit logic is a free-running counter with NO
   reference to any bus-activity / RX-active / TX-active signal.
4. Honors waiver `wake_pulse_collision_acceptable` (≥40 chars).

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

WAIVER_KEY = "wake_pulse_collision_acceptable"
WAIVER_MIN_LEN = 40

_FILENAME_HINTS = (
    "wake_gen", "wake_ctrl", "wake_pulse", "wake_drv",
    "wake_fsm", "wake_emit",
)

_WAKE_OUT_NAMES_RE = re.compile(
    r"\bwake_(?:oe|pulse|drv|o|out|en|emit|active)\b",
    re.IGNORECASE,
)

# Family of "bus is active" / "host activity" signals. Must appear
# somewhere in the wake module to count as gating.
_BUS_ACTIVE_RE = re.compile(
    r"\b(?:bus_active|bus_busy|bus_idle|rx_active|tx_active|"
    r"rx_byte_vld|rx_br|host_active|tester_active|id_bus_low|"
    r"rx_in_progress|tx_in_progress|frame_active|comm_active|"
    r"rx_busy|tx_busy)\b",
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


def is_wake_gen(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in _FILENAME_HINTS):
        return True
    # Body heuristic: a periodic counter + wake_oe/wake_pulse output.
    if not _WAKE_OUT_NAMES_RE.search(src_no_cmt):
        return False
    # Look for a counter that loops on a period.
    if re.search(
        r"\b\w*cnt\w*\s*<=\s*\w*cnt\w*\s*\+\s*\d",
        src_no_cmt,
        re.IGNORECASE,
    ):
        return True
    return False


def has_bus_gating(src_no_cmt: str) -> bool:
    """True when the wake module references a bus-activity signal."""
    return bool(_BUS_ACTIVE_RE.search(src_no_cmt))


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
            "Usage: wake_gen_bus_active_reset_check.py <project_dir>"
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

    wake_files: List[Tuple[Path, str]] = []
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        if is_wake_gen(path, src):
            wake_files.append((path, src))

    if not wake_files:
        print("SKIP — no wake-pulse generator RTL detected")
        return 0

    failures: List[str] = []
    for path, src in wake_files:
        try:
            rel = path.relative_to(project_dir)
        except ValueError:
            rel = path
        if not has_bus_gating(src):
            failures.append(
                f"NO_BUS_ACTIVE_GATING — {rel}: wake-pulse generator "
                f"is a free-running periodic counter with no "
                f"reference to any bus-activity / rx_active / "
                f"tx_active / rx_br / rx_byte_vld signal. Wake LOW "
                f"will collide with host BR / TX / RX on the "
                f"open-drain bus and corrupt frame parsing."
            )

    is_waived, rationale = waived(project_dir)

    if not failures:
        print(
            f"PASS — {len(wake_files)} wake-pulse generator(s) "
            f"reference bus-active gating signal"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} wake collision "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} wake-pulse collision issue(s):")
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  An ungated periodic wake pulse fires on a fixed period")
    print("  regardless of host activity. On an open-drain bus the")
    print("  wake LOW ORs with any concurrent host BR/TX, the host")
    print("  sees a long LOW spanning the wake collision window, and")
    print("  re-classifies it as BR/IBT — resetting frame state and")
    print("  silently corrupting the response window.")
    print()
    print(
        "Fix template:\n"
        "    input  logic bus_active,  // = rx_active | tx_active | rx_br\n"
        "    ...\n"
        "    if (bus_active) cnt <= '0;\n"
    )
    print(
        "Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
