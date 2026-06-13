#!/usr/bin/env python3
"""wake_gen_silence_gate.py — Wave 58 / BACKLOG-v12 P0.1 plugin gate.

Detects the canonical "wake-pulse counter starves under continuous host
polling" RTL bug class.  Surfaced in the v0.121-vendor benchmark
(Wave 56 column-D Issue 2 root cause): a periodic-pulse generator
gates its counter under `if (frame_active) ... else <cnt> <= 0;`,
where the counter's job is to span ACROSS frames.  With continuous
host polling at <period_us cadence the counter never reaches its
threshold and the pulse never fires.

Detection (chip-AGNOSTIC)
=========================
1. Find wake-pulse-generator RTL files (filename hint
   `wake_gen` / `wake_pulse` / `wake_drv` / `wake_emit` / `pulse_gen`
   OR a periodic counter pattern feeding a `*_pulse_low|wake_oe|*_drv`
   output).
2. Locate the always-block driving the pulse output.  Identify the
   gating expression (the if-guard around the period counter).
3. Detect a SYMMETRIC counter reset in the gating else-branch:
       if (<gate>) begin
         <cnt> <= <cnt> + 1;
         ...
       end else begin
         <cnt> <= 0;          // ← SMELL
       end
4. FAIL when the counter that gets reset in the else-branch is the
   SAME counter that increments inside the if-branch AND the gating
   signal is a frame-level / bus-active signal (frame_active /
   bus_active / rx_active / tx_active / busy / in_progress).  This
   is the v0.121-vendor pathology.
5. PASS when the counter free-runs across the gating signal (no
   reset in the else-branch) OR the else-branch only resets pulse-
   level state (pulse_active / pulse_cnt / *_low / *_oe), never
   the period-level counter.

Honors waiver `wake_pulse_counter_else_reset_intentional` (>=40 chars).

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

# Wave 78 — explicit class applicability. Wake-gen periodic pulse
# applies to any IC that has a wake-gating mechanism: AID-class half-
# duplex, digital cmd-driven (UART/SPI awake-latch), mixed-signal-OTP
# (analog wake from quiescent). The has_wake_gating profile field
# refines applicability further at runtime.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

_APPLICABLE_CLASSES = (
    "aid_class_half_duplex",
    "digital_cmd_driven",
    "mixed_signal_otp",
)

WAIVER_KEY = "wake_pulse_counter_else_reset_intentional"
WAIVER_MIN_LEN = 40

_FILENAME_HINTS = (
    "wake_gen", "wake_ctrl", "wake_pulse", "wake_drv", "wake_fsm",
    "wake_emit", "pulse_gen", "heartbeat",
)

_PULSE_OUT_RE = re.compile(
    r"\b(?:wake_(?:oe|pulse|drv|o|out|en|emit|active|low)|"
    r"\w*pulse_low|\w*pulse_oe|heartbeat_(?:oe|out|low))\b",
    re.IGNORECASE,
)

# Frame-level / bus-active gating signals — any of these in the
# guard expression, combined with an else-branch counter reset,
# is the v0.121-vendor pathology.
_FRAME_GATE_RE = re.compile(
    r"\b(?:frame_active|bus_active|bus_busy|rx_active|tx_active|"
    r"rx_byte_vld|rx_br|host_active|tester_active|"
    r"rx_in_progress|tx_in_progress|comm_active|"
    r"rx_busy|tx_busy|frame_in_progress|busy)\b",
    re.IGNORECASE,
)

# Counter-name pattern: any reg whose increment + else-reset both
# appear in the same always-block.
_COUNTER_NAME_RE = re.compile(
    r"\b(\w*(?:period|periodic|interval|tick|hb|heartbeat|wake)_?cnt\w*|"
    r"\w*cnt_\w*period\w*|\w*period_\w*)\b",
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


def is_wake_module(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in _FILENAME_HINTS):
        return True
    if not _PULSE_OUT_RE.search(src_no_cmt):
        return False
    # Body heuristic: increments period-class counter
    if re.search(
        r"\b\w*(?:period|interval|tick|hb)\w*cnt\w*\s*<=\s*"
        r"\w*(?:period|interval|tick|hb)\w*cnt\w*\s*\+\s*\d",
        src_no_cmt, re.IGNORECASE,
    ):
        return True
    return False


def find_else_reset_pathology(src_no_cmt: str) -> List[str]:
    """Walk for `if (<frame_gate>) ... else <cnt> <= 0;` smell.

    Returns a list of (counter_name, gate_signal) tuples reported
    as findings.
    """
    findings: List[str] = []

    # Match always-block `if (<expr>) begin ... end else begin ... end`.
    # The gate expression must reference a frame-level signal AND
    # the counter that gets reset in the else-branch must also be
    # incremented in the if-branch.
    pattern = re.compile(
        r"if\s*\(\s*([^)]{1,400}?)\s*\)\s*begin"
        r"(?P<ifbody>.{1,4000}?)"
        r"end\s*else\s*begin"
        r"(?P<elsebody>.{1,2000}?)"
        r"end",
        re.DOTALL,
    )

    for m in pattern.finditer(src_no_cmt):
        guard = m.group(1)
        ifb = m.group("ifbody")
        elseb = m.group("elsebody")

        if not _FRAME_GATE_RE.search(guard):
            continue

        # Find counters reset to zero in the else branch.
        for cm in re.finditer(
            r"(\w+)\s*<=\s*(?:0|1'b0|24'd0|\d+'d0|'0)\s*;",
            elseb,
        ):
            cnt = cm.group(1)
            # Confirm same counter is incremented in the if-branch.
            inc_re = re.compile(
                rf"\b{re.escape(cnt)}\s*<=\s*{re.escape(cnt)}\s*\+\s*\d",
            )
            if inc_re.search(ifb):
                # Skip pulse-level state (pulse_active / pulse_cnt /
                # pulse_low / wake_pulse_low) — those SHOULD reset
                # in else-branch. Only report period-level counters.
                if re.search(
                    r"(period|interval|tick|hb|heartbeat|wake_)\w*cnt",
                    cnt, re.IGNORECASE,
                ) and "pulse" not in cnt.lower():
                    findings.append(
                        f"counter `{cnt}` increments in if-branch under "
                        f"gate referencing a frame-level signal AND is "
                        f"reset to zero in the else-branch — "
                        f"continuous gate-toggling will starve the "
                        f"counter from ever reaching its threshold."
                    )
    return findings


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
        print("Usage: wake_gen_silence_gate.py <project_dir>")
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    # Wave 78 — explicit class gate. `unknown` falls through to the
    # existing rtl-walking logic (fail-closed). The `has_wake_gating`
    # profile field provides finer-grain applicability when present.
    profile = detect_ic_class(project_dir)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class not in _APPLICABLE_CLASSES and ic_class != "unknown":
        print(f"SKIP — not applicable to ic_class={ic_class}")
        return 0
    # Optional finer-grain skip: when the profile explicitly says the
    # IC has no wake-gating mechanism, this gate is inert.
    if profile.get("has_wake_gating") is False:
        print("SKIP — profile.has_wake_gating=False (no wake-pulse mechanism)")
        return 0

    rtl_files = find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    findings: List[str] = []
    inspected = 0
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        if not is_wake_module(path, src):
            continue
        inspected += 1
        for f in find_else_reset_pathology(src):
            try:
                rel = path.relative_to(project_dir)
            except ValueError:
                rel = path
            findings.append(f"{rel}: {f}")

    if inspected == 0:
        print("SKIP — no wake-pulse generator RTL detected")
        return 0

    is_waived, rationale = waived(project_dir)

    if not findings:
        print(
            f"PASS — {inspected} wake-pulse generator(s) inspected; no "
            f"period-counter else-reset pathology detected"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(findings)} wake-counter starvation "
            f"finding(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in findings:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(findings)} wake-counter starvation finding(s):")
    for f in findings:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  When a periodic-pulse counter is reset in the gating")
    print("  else-branch AND the gate toggles at a rate faster than the")
    print("  counter's threshold (e.g. continuous host polling on a")
    print("  half-duplex bus at 5-15 ms cadence vs a 5 ms wake-pulse")
    print("  threshold), the counter never reaches threshold and the")
    print("  pulse never fires.  This was the v0.121-vendor column-D")
    print("  Issue 2 root cause.")
    print()
    print("Fix template:")
    print("  if (~awake) begin")
    print("    if (period_cnt < T_PERIOD) period_cnt <= period_cnt + 1;")
    print("    if (period_cnt == T_PERIOD && ~frame_active) begin ...")
    print("  end")
    print("  // No `period_cnt <= 0` in the frame_active-gated else-branch.")
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
