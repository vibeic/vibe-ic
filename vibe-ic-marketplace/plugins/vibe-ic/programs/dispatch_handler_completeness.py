#!/usr/bin/env python3
"""dispatch_handler_completeness.py — Wave 58 / BACKLOG-v12 P0.2 plugin gate.

For every opcode declared in L3 (`opcodes[]`), verify that the dispatch
FSM in rtl/ has either:
  (a) an explicit `<HEX>:` case arm in the dispatch state, OR
  (b) the opcode is documented as silent-reject via a waiver.

The previous (v0.121-vendor) RTL had only 0x70 / 0x72 / 0x74 case arms
and a `default:` branch that fell back to a GET_ID-equivalent reply
for ANY validated opcode — which mass-passed 0xE0 / 0xE2 / 0x76 / 0x78
frames as 0x75+OTP responses (Wave 56 column-D Issue 4 + 0xE0/0xE2
silent failures).

Detection (chip-AGNOSTIC)
=========================
1. Read `<project>/generated_docs/L3_*.json` `opcodes[]` array — each
   entry has `hex` (e.g. "0x70") field.
2. Find the dispatch state in rtl/ — heuristic: any `case (op)` /
   `case (cmd[0])` / `case (cmd_buf[0])` block whose state arm name
   contains `dispatch` / `decode` / `cmd` / `route`.
3. PASS when every L3 opcode has a matching `8'hNN:` case arm.
4. WARN (still PASS) when the default arm is a silent reject
   (`state <= S_DROP` / `state <= S_IDLE` / no tx_start assertion)
   — that's the spec-compliant catch-all.
5. FAIL when an L3 opcode is NOT in any case arm AND the default
   arm contains a `tx_start` / `<= S_TX_*` / `<= S_OTP_*` /
   `<= S_BUILD_TX` transition — i.e. the default is a GET_ID-like
   spam-responder that will mass-PASS unhandled opcodes.

Honors waiver `dispatch_handler_intentionally_default_routed` (≥40 chars).

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
from typing import List, Tuple, Set
import _path_layout as _pl

# Wave 78 — explicit class applicability. Dispatch / opcode-table
# completeness applies to any command-driven IC (AID half-duplex,
# UART/SPI/I2C cmd, mixed-signal-OTP). Pure-analog / bare-FPGA have
# no L3.opcodes[] and the gate already SKIPs there.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

_APPLICABLE_CLASSES = (
    "aid_class_half_duplex",
    "digital_cmd_driven",
    "mixed_signal_otp",
)

WAIVER_KEY = "dispatch_handler_intentionally_default_routed"
WAIVER_MIN_LEN = 40


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


def load_l3_opcodes(project_dir: Path) -> List[str]:
    """Return list of opcode hex strings (e.g. ['0x70', '0xE0']).

    Empty list when L3 is missing.
    """
    gd = _pl.generated_docs_dir(project_dir)
    if not gd.is_dir():
        return []
    for path in gd.glob("L3_*.json"):
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        opcodes_raw = d.get("opcodes", [])
        out: List[str] = []
        for entry in opcodes_raw:
            if isinstance(entry, dict):
                h = entry.get("hex") or entry.get("opcode_hex") or \
                    entry.get("opcode")
            elif isinstance(entry, str):
                h = entry
            else:
                continue
            if h:
                # Normalise to canonical form 0xNN.
                hs = str(h).strip().lower().replace("8'h", "0x")
                if hs.startswith("0x"):
                    hs_norm = "0x" + hs[2:].upper()
                    out.append(hs_norm)
        return out
    return []


def find_case_arms(src_no_cmt: str) -> Tuple[Set[str], List[str]]:
    """Find opcode case arms.  Returns (set_of_hex, default_arm_body_list).

    A 'case arm' is any `8'hNN:` or `'hNN:` or `8'bNNNNNNNN:` literal
    appearing inside a `case (op)` / `case (cmd[0])` / `case (cmd_buf[0])`
    / `case (opcode)` block.
    """
    arms: Set[str] = set()
    default_bodies: List[str] = []

    case_re = re.compile(
        r"case\s*\(\s*(?:op|opcode|cmd|cmd\s*\[\s*0\s*\]|"
        r"cmd_buf\s*\[\s*0\s*\]|cmd_buf0|rx_op|received_op)\s*\)"
        r"(?P<body>.+?)endcase",
        re.DOTALL | re.IGNORECASE,
    )
    arm_re = re.compile(
        r"8\s*'\s*h\s*([0-9a-fA-F]{1,2})\s*:",
    )
    default_re = re.compile(
        r"default\s*:\s*(?:begin\s*)?(?P<db>.{1,2000}?)"
        r"(?:end(?=case)|;|(?=8\s*'\s*h)|(?=default))",
        re.DOTALL,
    )
    for cm in case_re.finditer(src_no_cmt):
        body = cm.group("body")
        for am in arm_re.finditer(body):
            hex_val = "0x" + am.group(1).upper().zfill(2)
            arms.add(hex_val)
        for dm in default_re.finditer(body):
            default_bodies.append(dm.group("db"))
    return arms, default_bodies


def default_is_spam_responder(default_body: str) -> bool:
    """A 'spam responder' default is one that drives a TX or starts an
    OTP/BUILD_TX state machine — i.e. it WILL emit a reply for every
    unhandled opcode.
    """
    bad_patterns = [
        r"\btx_start\s*<=\s*1\b",
        r"<=\s*S_TX_",
        r"<=\s*S_OTP_REQ",
        r"<=\s*S_BUILD_TX",
        r"<=\s*S_TURNAROUND",
        r"tx_buf\s*\[",
        r"\bwake_arm\s*<=\s*1\b",
    ]
    for pat in bad_patterns:
        if re.search(pat, default_body):
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
        print("Usage: dispatch_handler_completeness.py <project_dir>")
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    # Wave 78 — explicit class gate. `unknown` falls through to FAIL
    # logic (fail-closed).
    profile = detect_ic_class(project_dir)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class not in _APPLICABLE_CLASSES and ic_class != "unknown":
        print(f"SKIP — not applicable to ic_class={ic_class}")
        return 0

    rtl_files = find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    l3_opcodes = load_l3_opcodes(project_dir)
    if not l3_opcodes:
        print("SKIP — no L3 opcodes declared")
        return 0

    # Aggregate case arms + default bodies across all RTL files.
    all_arms: Set[str] = set()
    all_defaults: List[str] = []
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        arms, defaults = find_case_arms(src)
        all_arms |= arms
        all_defaults.extend(defaults)

    # If no case arms were found at all, the FSM either uses an
    # if-elif chain or no dispatch at all.  We can't make a strong
    # claim — skip.
    if not all_arms:
        print(
            "SKIP — no opcode dispatch case arms detected; "
            "FSM may use if-elif chain or external decoder"
        )
        return 0

    missing = [op for op in l3_opcodes if op not in all_arms]

    is_waived, rationale = waived(project_dir)

    # Default-arm verdict.
    spam_default = any(
        default_is_spam_responder(db) for db in all_defaults
    )

    if not missing:
        print(
            f"PASS — all {len(l3_opcodes)} L3 opcode(s) have explicit "
            f"case arms; default arm "
            f"{'is silent-reject' if not spam_default else 'is spam-responder (no missing opcodes, but check intent)'}"
        )
        return 0

    # Missing opcodes exist.  If default arm is silent-reject, it's a
    # WARN class — emit findings but still PASS.
    if not spam_default:
        print(
            f"PASS — {len(missing)} L3 opcode(s) missing dedicated "
            f"handlers, but default arm is silent-reject (acceptable)"
        )
        for op in missing:
            print(f"  • {op} → default (silent reject)")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(missing)} L3 opcode(s) routed to "
            f"a TX-emitting default arm, silenced by waivers."
            f"{WAIVER_KEY}: {rationale[:80]}…"
        )
        for op in missing:
            print(f"  • {op} → default (spam-responder)")
        return 0

    print(
        f"FAIL — {len(missing)} L3 opcode(s) lack dedicated handlers AND "
        f"default arm contains TX/dispatch — opcodes will mass-PASS as "
        f"a generic reply (Wave 56 column-D 0xE0/0xE2 root cause)."
    )
    for op in missing:
        print(f"  • {op}")
    print()
    print("Fix: add explicit `8'hNN:` case arms in the dispatch state, ")
    print("OR change `default:` to `state <= S_DROP;` (silent reject).")
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
