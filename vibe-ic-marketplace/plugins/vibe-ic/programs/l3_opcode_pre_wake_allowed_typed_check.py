#!/usr/bin/env python3
"""l3_opcode_pre_wake_allowed_typed_check.py — Wave 37 (v0.119.69).

BACKLOG v0.119.70 Item 3a (P2): when the IC has wake gating
(`L6.wake_gating` present), every opcode entry in
`L3_CMD_PROTOCOL.json::opcodes[]` MUST carry a typed
`pre_wake_allowed: bool` field.

- `true`  → opcode in `awake_latch=0` is still dispatched (typically
            the identification / wake opcode such as GET_ID).
- `false` → opcode in `awake_latch=0` MUST be rejected.

If `L6.wake_gating` does not exist (the IC has no wake gating), this
field is OPTIONAL and the gate SKIPs cleanly.

Applicability
=============
- IC class profile: `aid_class_half_duplex`, `digital_cmd_driven`,
  `mixed_signal_otp` (every cmd-driven IC class) — `pure_analog` /
  `bare_fpga` SKIP.
- L3.opcodes / L3.commands present (otherwise SKIP — pure_analog
  always falls through here).
- L6.wake_gating present somewhere in the L6 doc (any of:
  top-level `wake_gating`, `awake_latch_on`, `wake_gate`,
  `pre_wake_period`, `wake_required` — any of these triggers
  applicability). If none → SKIP.

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL (one or more opcodes missing or wrong-typed)
2  — usage error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

WAIVER_KEY = "l3_opcode_pre_wake_allowed_typed_intentional"
WAIVER_MIN_LEN = 40

_APPLICABLE_CLASSES = (
    "aid_class_half_duplex", "digital_cmd_driven", "mixed_signal_otp",
)

_WAKE_GATING_KEYS = (
    "wake_gating", "awake_latch_on", "wake_gate",
    "pre_wake_period", "wake_required",
)


def _l3_load(project: Path) -> Optional[dict]:
    p = _pl.generated_docs_dir(project) / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _l6_load(project: Path) -> Optional[dict]:
    p = _pl.generated_docs_dir(project) / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _l6_has_wake_gating(l6: Optional[dict]) -> bool:
    if not isinstance(l6, dict):
        return False
    # Direct top-level keys
    for k in _WAKE_GATING_KEYS:
        if k in l6 and l6[k] not in (None, "", [], {}, False):
            return True
    # Check `protocol.wake_required: true`
    proto = l6.get("protocol")
    if isinstance(proto, dict):
        for k in _WAKE_GATING_KEYS:
            if k in proto and proto[k] not in (None, "", [], {}, False):
                return True
    # Recursive scan one level deep for nested dicts
    for v in l6.values():
        if isinstance(v, dict):
            for k in _WAKE_GATING_KEYS:
                if k in v and v[k] not in (None, "", [], {}, False):
                    return True
    return False


def _l3_opcodes(l3: dict) -> List[dict]:
    for key in ("opcodes", "commands"):
        v = l3.get(key)
        if isinstance(v, list):
            return [e for e in v if isinstance(e, dict)]
        if isinstance(v, dict):
            return [
                {**e, "_dict_key": k} for k, e in v.items()
                if isinstance(e, dict)
            ]
    return []


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
        print("Usage: l3_opcode_pre_wake_allowed_typed_check.py "
              "<project_dir>")
        return 2

    project = Path(argv[1]).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}")
        return 1

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")

    if ic_class in ("pure_analog", "bare_fpga"):
        print(f"SKIP — ic_class={ic_class} not applicable to "
              f"L3 pre_wake_allowed gate")
        return 0
    if ic_class not in _APPLICABLE_CLASSES and ic_class != "unknown":
        print(f"SKIP — ic_class={ic_class} not in applicable set")
        return 0

    l3 = _l3_load(project)
    if l3 is None:
        print("SKIP — no L3_CMD_PROTOCOL.json present")
        return 0

    opcodes = _l3_opcodes(l3)
    if not opcodes:
        print("SKIP — L3 has no opcodes / commands")
        return 0

    l6 = _l6_load(project)
    if not _l6_has_wake_gating(l6):
        print("SKIP — L6.wake_gating absent (IC has no wake gating; "
              "pre_wake_allowed is optional)")
        return 0

    failures: List[str] = []
    for entry in opcodes:
        hex_v = (entry.get("hex") or entry.get("opcode")
                 or entry.get("opcode_hex") or entry.get("code")
                 or entry.get("_dict_key") or "?")
        name = entry.get("name") or entry.get("command_name") or ""
        if "pre_wake_allowed" not in entry:
            failures.append(
                f"opcode {hex_v} ({name!r}) — missing typed field "
                f"`pre_wake_allowed: bool`"
            )
            continue
        v = entry["pre_wake_allowed"]
        if not isinstance(v, bool):
            failures.append(
                f"opcode {hex_v} ({name!r}) — `pre_wake_allowed` "
                f"must be bool (got {type(v).__name__}: {v!r})"
            )

    is_waived, rationale = _waived(project)

    if not failures:
        print(
            f"PASS — all {len(opcodes)} opcode(s) carry typed "
            f"`pre_wake_allowed: bool`"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} pre_wake_allowed "
            f"issue(s) silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(
        f"FAIL — {len(failures)} L3 opcode(s) missing typed "
        f"`pre_wake_allowed: bool`:"
    )
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  Wake-gated ICs reject most opcodes when awake_latch=0.")
    print("  The L6 reject rule encodes the global gating, but the")
    print("  per-opcode `pre_wake_allowed` field is what makes the")
    print("  rule schema-driven and toolable. RTL gen / dispatcher")
    print("  generation, simulator scenarios, and lab oracle scripts")
    print("  all read this typed field.")
    print()
    print(
        "Or document the alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
