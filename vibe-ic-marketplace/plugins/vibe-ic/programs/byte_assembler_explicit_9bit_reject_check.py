#!/usr/bin/env python3
"""byte_assembler_explicit_9bit_reject_check.py — Wave 37 (v0.119.69).

BACKLOG v0.119.70 Item 1 (P0): the byte_assembler in a half-duplex
single-wire bit-bang protocol MUST have an *explicit* 9-bit reject
path (also catches generic bit-overflow / oversized-byte cases). Some
fresh-agent RTL only relies on the cmd_len mismatch dropping the
emergent path silently — that is *not* an explicit reject and is
fragile against wave-shape changes (jitter / noise / off-by-one
classifier).

Detection
=========
1. **Applicability guard** — only runs when the IC class is in
   {`aid_class_half_duplex`} OR the project has bit-bang byte-
   assembler RTL evidence (any RTL file with a `bit_idx` /
   `bit_count` / `bit_cnt` register that aggregates into a byte
   strobe). SPI / UART / I2C ICs (hardware byte boundary) → SKIP.
   `pure_analog` / `bare_fpga` / `unknown` → SKIP (no RTL → SKIP
   following the existing plugin convention).

2. **Find byte-assembler RTL** — file is a byte-assembler iff:
     - filename matches `bit_assembler` / `byte_assembler` / `rx_assembler`
       / `rx_serdes` / `rx_shift`, OR
     - body contains a `bit_idx` / `bit_cnt` counter AND a byte-strobe
       (`byte_valid` / `byte_done` / `rx_byte_vld` etc.) AND it is NOT
       a TX-named file (`tx_phy`, `tx_serdes`, ...).

3. **Reject signal** — at least one of these regex tokens MUST appear
   in the byte-assembler text *or* in the dispatcher / main_fsm RTL:
       ninth_bit_detected | frame_reject | bit_count_violation
       bit_overflow      | byte_overflow | bit_too_many

4. **Cross-check main_fsm** — when a reject signal is present in the
   byte-assembler, at least one main_fsm-class RTL file MUST contain a
   matching state arm or assignment:
       S_DROP | S_REJECT | drop_frame | reject_frame

Verdicts
========
- PASS  — byte-assembler emits an explicit reject signal and main_fsm
          consumes it.
- FAIL  — byte-assembler exists, IC class is applicable, but no
          explicit reject signal is found (silent reliance on
          cmd-length mismatch is the silent-bug pattern that this
          gate is designed to catch).
- SKIP  — IC class not applicable; no RTL; no byte-assembler RTL.

The gate honors waiver `byte_assembler_implicit_reject_intentional`
(≥40 chars) for designs that are *deliberately* relying on emergent
path drop — the rationale must explain why explicit 9-bit detection
is not required.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

WAIVER_KEY = "byte_assembler_implicit_reject_intentional"
WAIVER_MIN_LEN = 40

_FILENAME_HINTS = (
    "bit_assembler", "byte_assembler", "rx_assembler",
    "rx_bit_assemb", "rx_serdes", "rx_shift",
)
_TX_FILENAME_HINTS = (
    "tx_phy", "tx_serdes", "tx_drv", "tx_pad", "tx_shifter",
    "tx_emit", "tx_send", "transmitter", "txfsm",
)
_BYTE_VLD_NAMES = (
    "rx_byte_vld", "byte_done", "byte_complete", "rx_byte_done",
    "byte_emit", "byte_strobe", "byte_valid", "byte_out_vld",
    "byte_committed", "rx_byte_valid",
)
_BIT_IDX_RE = re.compile(
    r"\bbit_(?:idx|cnt|n|index|num|count)\b",
    re.IGNORECASE,
)

_REJECT_SIGNAL_RE = re.compile(
    r"\b("
    r"ninth_bit_detected|frame_reject|bit_count_violation|"
    r"bit_overflow|byte_overflow|bit_too_many|"
    r"too_many_bits|extra_bit|frame_drop"
    r")\b",
    re.IGNORECASE,
)

_FSM_REJECT_PATH_RE = re.compile(
    r"\b("
    r"S_DROP|S_REJECT|S_BAD_FRAME|"
    r"drop_frame|reject_frame|frame_drop|frame_reject_q"
    r")\b",
    re.IGNORECASE,
)

# Class applicability — half-duplex single-wire bit-bang where each
# byte boundary is software-detected.
_APPLICABLE_CLASSES = ("aid_class_half_duplex",)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project_dir: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    files: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            files.append(p)
    return sorted(files)


def _is_byte_assembler(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in _TX_FILENAME_HINTS):
        return False
    if any(h in name for h in _FILENAME_HINTS):
        return True
    if not _BIT_IDX_RE.search(src_no_cmt):
        return False
    return any(n in src_no_cmt for n in _BYTE_VLD_NAMES)


def _is_main_fsm(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    if any(t in name for t in ("main_fsm", "fsm", "control",
                                "dispatcher", "ctrl")):
        return True
    # Body fallback: contains a `state <=` and an opcode case.
    if re.search(r"\bstate\s*<=\s*S_", src_no_cmt) and \
       re.search(r"\bcase\s*\(.*\bop", src_no_cmt, re.IGNORECASE):
        return True
    return False


def _waived(project_dir: Path) -> Tuple[bool, str]:
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
        print("Usage: byte_assembler_explicit_9bit_reject_check.py "
              "<project_dir>")
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    profile = detect_ic_class(project_dir)
    ic_class = profile.get("ic_class", "unknown")

    rtl_files = _find_rtl_files(project_dir)

    # Gather (path, src) tuples once.
    bodies: list[tuple[Path, str]] = []
    for p in rtl_files:
        try:
            bodies.append((p, _strip_comments(p.read_text(errors="ignore"))))
        except Exception:
            continue

    # Detect any byte-assembler RTL evidence to decide applicability.
    asm_files = [(p, s) for (p, s) in bodies if _is_byte_assembler(p, s)]

    # Applicability rules
    if ic_class in ("pure_analog", "bare_fpga"):
        print(f"SKIP — ic_class={ic_class} not applicable to "
              f"byte_assembler 9-bit reject gate")
        return 0
    # SPI / UART / I2C → hardware byte boundary, no software 9-bit
    # detection needed.
    proto_class = profile.get("protocol_class", "none")
    if proto_class in ("spi", "uart", "i2c") and not asm_files:
        print(f"SKIP — protocol_class={proto_class} (hardware byte "
              f"boundary; no software bit_idx assembly)")
        return 0
    # If applicability isn't aid_class and we have no byte_assembler
    # RTL evidence, SKIP — but never SKIP on `unknown`: that class is
    # the fail-closed default and must run the full inspection logic
    # (Wave 42 / MF1 — fault-injection hardening).
    if (
        ic_class not in _APPLICABLE_CLASSES
        and ic_class != "unknown"
        and not asm_files
    ):
        print(f"SKIP — ic_class={ic_class} and no bit-bang "
              f"byte_assembler RTL evidence")
        return 0

    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0
    if not asm_files:
        print("SKIP — no bit_assembler / byte_assembler RTL detected")
        return 0

    # Aggregate text scope for reject-signal lookup. The reject
    # signal MAY be defined in a main_fsm or a header file separate
    # from the byte_assembler — so we search the union.
    asm_text = "\n".join(s for (_, s) in asm_files)
    full_text = "\n".join(s for (_, s) in bodies)

    reject_in_asm = bool(_REJECT_SIGNAL_RE.search(asm_text))
    reject_in_full = bool(_REJECT_SIGNAL_RE.search(full_text))

    fsm_files = [(p, s) for (p, s) in bodies if _is_main_fsm(p, s)]
    fsm_text = "\n".join(s for (_, s) in fsm_files)
    fsm_path_present = bool(_FSM_REJECT_PATH_RE.search(fsm_text))

    failures: list[str] = []

    if not reject_in_full:
        rels = []
        for p, _ in asm_files:
            try:
                rels.append(str(p.relative_to(project_dir)))
            except ValueError:
                rels.append(str(p))
        failures.append(
            f"NO_EXPLICIT_REJECT_SIGNAL — byte-assembler file(s) "
            f"{rels} have no explicit ninth_bit_detected / "
            f"frame_reject / bit_count_violation / bit_overflow / "
            f"byte_overflow / bit_too_many signal. The chip is "
            f"silently relying on the cmd_len mismatch dropping "
            f"the emergent path, which is fragile against wave-"
            f"shape changes."
        )
    elif reject_in_asm and fsm_files and not fsm_path_present:
        failures.append(
            f"REJECT_SIGNAL_WITHOUT_FSM_PATH — reject signal "
            f"present in byte-assembler but main_fsm has no "
            f"S_DROP / S_REJECT / drop_frame / reject_frame "
            f"path. The reject signal will be raised but the "
            f"FSM never transitions to a clean drop state."
        )

    is_waived, rationale = _waived(project_dir)

    summary = {
        "byte_assembler_files": len(asm_files),
        "main_fsm_files": len(fsm_files),
        "reject_signal_in_assembler": reject_in_asm,
        "reject_signal_anywhere": reject_in_full,
        "fsm_reject_path_present": fsm_path_present,
        "ic_class": ic_class,
        "protocol_class": proto_class,
    }

    if not failures:
        print(
            f"PASS — byte-assembler explicit 9-bit reject signal "
            f"present (asm={summary['reject_signal_in_assembler']}, "
            f"fsm_path={fsm_path_present})"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} 9-bit reject "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} byte-assembler 9-bit reject issue(s):")
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  Without an explicit ninth-bit / bit-overflow reject")
    print("  signal, a noise glitch that injects an extra bit is")
    print("  swallowed silently. The byte_assembler then commits a")
    print("  byte at offset+1, the FSM rejects on cmd_len mismatch")
    print("  (emergent), and the host saw garbage. Explicit reject")
    print("  catches this at the bit-classifier boundary.")
    print()
    print(
        "Fix template (inside byte_assembler always_ff):\n"
        "    reg ninth_bit_detected;\n"
        "    always_ff @(posedge clk) begin\n"
        "        if (rst | byte_committed) ninth_bit_detected <= 1'b0;\n"
        "        else if (bit_vld && bit_idx == 4'd8)\n"
        "            ninth_bit_detected <= 1'b1;\n"
        "    end\n"
    )
    print(
        "And in main_fsm:\n"
        "    if (ninth_bit_detected) state <= S_DROP;\n"
    )
    print(
        "Or document the alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
