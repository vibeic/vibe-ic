#!/usr/bin/env python3
"""
l11_otp_lock_dependencies_typed_check.py — Wave 38 / B5

Audit item (PHASE2A_FULL_AUDIT_v0119.67.md, line 57): OTP layouts
declare lock-bits whose meaning is conditional ("0x40 default 00,
write 80 後 0x60-0x7F 無法寫入"). L11.otp_lock_bits[] often only
captures the bit address + name, never the typed dependency
(``affects[]`` byte-range) that spec-to-rtl needs to gate the
write path.

Trigger: L11_OTP_CONTENT.json has ``otp_lock_bits`` (or
``lock_bits`` / ``otp_locks``) array.

Required typed shape: each lock-bit entry MUST have:
  - ``name`` / ``bit`` / ``address``
  - ``affects`` (list of byte-range/register references) OR
    ``protects_range`` (string ``0xNN..0xMM``) OR
    ``locked_addresses`` (list).
  - ``trigger_value`` (e.g. ``0x80``) OR ``arming_pattern`` /
    ``arming_value``.

The gate is chip-AGNOSTIC: only the schema depth is enforced.

Usage:
    python3 l11_otp_lock_dependencies_typed_check.py <project_dir>

Exit codes:
    0 = PASS (no lock_bits OR each typed deeply enough)
    1 = FAIL (lock_bits present but missing affects/trigger_value)
    2 = input-missing (skip)

Honors waiver ``l11_otp_lock_dependencies_intentional`` (>=40
chars).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# OTP lock-bit dependency table is required only for IC classes
# that actually carry an OTP image (AID-class, mixed_signal_otp,
# or any digital-cmd-driven IC whose profile reports has_otp).
# Bare-FPGA scaffolds have no OTP at all; pure-analog parts only
# have OTP when explicitly trimmed (profile.has_otp covers both).
_SKIP_CLASSES = ("bare_fpga",)


_L11_GLOBS = (
    "phase1/generated_docs/L11_OTP_CONTENT.json",
    "phase1/generated_docs/L11*.json",
    "**/L11_OTP_CONTENT.json",
)

_LOCK_KEYS = ("otp_lock_bits", "lock_bits", "otp_locks", "locks",
              "lock_table", "write_lock_bits")

_AFFECTS_KEYS = ("affects", "protects_range", "locked_addresses",
                 "covers", "scope", "address_range",
                 "protected_addresses", "covered_addresses")
_TRIGGER_KEYS = ("trigger_value", "arming_pattern", "arming_value",
                 "lock_value", "set_value", "write_value")
_NAME_KEYS = ("name", "bit", "address", "addr")


def _find_l11(project: Path) -> Optional[Path]:
    for pat in _L11_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _collect_lock_entries(node, out: List[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _LOCK_KEYS and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        out.append(it)
            else:
                _collect_lock_entries(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_lock_entries(it, out)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l11_otp_lock_dependencies_typed_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l11_otp_lock_dependencies_typed_check: "
              f"ic_class={ic_class} (no OTP image expected; "
              f"L11 lock_bits[] not applicable)")
        return 2
    # pure_analog without OTP: also skip cleanly (otherwise
    # behavioral fall-through still SKIPs but the message is less
    # informative).
    if ic_class == "pure_analog" and not profile.get("has_otp"):
        print(f"[SKIP] l11_otp_lock_dependencies_typed_check: "
              f"ic_class={ic_class} and profile.has_otp is False; "
              f"OTP lock-bit dependency table not applicable")
        return 2

    l11 = _find_l11(project)
    if l11 is None:
        print("[SKIP] l11_otp_lock_dependencies_typed_check: "
              "L11_OTP_CONTENT.json not found")
        return 2

    try:
        data = json.loads(l11.read_text())
    except Exception as exc:
        print(f"[FAIL] l11_otp_lock_dependencies_typed_check: "
              f"cannot parse {l11.relative_to(project)}: {exc}")
        return 1

    locks: List[dict] = []
    _collect_lock_entries(data, locks)
    if not locks:
        print("[SKIP] l11_otp_lock_dependencies_typed_check: "
              "no otp_lock_bits[]/lock_bits[] array (gate not "
              "applicable)")
        return 2

    bad: List[str] = []
    for i, e in enumerate(locks):
        label = (e.get("name") or e.get("bit")
                 or e.get("address") or f"lock[{i}]")
        if not any(k in e for k in _NAME_KEYS):
            bad.append(f"{label}: missing name/bit/address")
            continue
        has_affects = any(k in e for k in _AFFECTS_KEYS)
        has_trigger = any(k in e for k in _TRIGGER_KEYS)
        miss = []
        if not has_affects:
            miss.append("affects/protects_range/locked_addresses")
        if not has_trigger:
            miss.append("trigger_value/arming_pattern")
        if miss:
            bad.append(f"{label}: missing {','.join(miss)}")

    if bad:
        print(f"[FAIL] l11_otp_lock_dependencies_typed_check: "
              f"{len(bad)}/{len(locks)} lock entries lack typed "
              f"dependency. Examples: {'; '.join(bad[:5])}")
        return 1

    print(f"[PASS] l11_otp_lock_dependencies_typed_check: "
          f"{len(locks)} lock-bit entries with typed "
          f"affects/trigger_value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
