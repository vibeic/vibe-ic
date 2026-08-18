#!/usr/bin/env python3
"""l6_reject_rules_from_rx_event_check.py — Wave 37 (v0.119.69).

BACKLOG v0.119.70 Item 3b (P2): when L6.wake_gating is present AND
any L3 opcode has `pre_wake_allowed: false`, L6.reject_rules MUST
contain at least one rule describing
"pre-wake + opcode_not_in_pre_wake_whitelist ⇒ reject".

Detection regex (case-insensitive, OR):
    pre[-_ ]wake.*opcode.*not.*whitelist
    pre[-_ ]wake.*reject
    awake_latch.*0.*reject

Applicability guards
====================
- L6 absent → SKIP.
- L6.wake_gating absent → SKIP (the IC has no wake gating, so the
  pre-wake reject rule is not required).
- L3 opcodes absent → SKIP.
- IC class profile in {`pure_analog`, `bare_fpga`} → SKIP.

Wave 37 generality note
=======================
This file is created in Wave 37 (BACKLOG v0.119.70 Item 3b) — the
backlog description references it as if extending an existing gate
because the BACKLOG was written assuming Wave 37 already shipped
the basic skeleton. We ship the skeleton AND the new pre-wake
reject-rule logic in the same Wave 37 commit.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

WAIVER_KEY = "l6_pre_wake_reject_rule_intentional"
WAIVER_MIN_LEN = 40

_PRE_WAKE_REJECT_RE = re.compile(
    r"(?:"
    r"pre[-_ \t]*wake.*opcode.*not.*whitelist|"
    r"pre[-_ \t]*wake.*reject|"
    r"awake_latch.*0.*reject|"
    r"reject.*pre[-_ \t]*wake|"
    r"opcode.*not.*in.*pre[-_ \t]*wake.*whitelist"
    r")",
    re.IGNORECASE | re.DOTALL,
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
    for k in _WAKE_GATING_KEYS:
        if k in l6 and l6[k] not in (None, "", [], {}, False):
            return True
    proto = l6.get("protocol")
    if isinstance(proto, dict):
        for k in _WAKE_GATING_KEYS:
            if k in proto and proto[k] not in (None, "", [], {}, False):
                return True
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


def _has_pre_wake_false(opcodes: List[dict]) -> bool:
    for entry in opcodes:
        v = entry.get("pre_wake_allowed")
        if v is False:
            return True
    return False


def _reject_rules_text(l6: dict) -> str:
    """Concatenate all reject_rules blob text from L6 (handles list,
    dict, or string forms)."""
    rr = l6.get("reject_rules")
    blobs: List[str] = []
    if isinstance(rr, str):
        blobs.append(rr)
    elif isinstance(rr, list):
        for e in rr:
            if isinstance(e, str):
                blobs.append(e)
            elif isinstance(e, dict):
                blobs.append(json.dumps(e))
    elif isinstance(rr, dict):
        blobs.append(json.dumps(rr))
    # Some emitters nest under reject_rules_table / fsm_states[*].rejects
    for k in ("reject_rules_table", "rejects", "frame_rejects"):
        v = l6.get(k)
        if isinstance(v, str):
            blobs.append(v)
        elif isinstance(v, list):
            for e in v:
                if isinstance(e, (str, dict)):
                    blobs.append(json.dumps(e) if isinstance(e, dict)
                                 else e)
    return "\n".join(blobs)


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
        print("Usage: l6_reject_rules_from_rx_event_check.py "
              "<project_dir>")
        return 2

    project = Path(argv[1]).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}")
        return 1

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in ("pure_analog", "bare_fpga"):
        print(f"SKIP — ic_class={ic_class} not applicable")
        return 0

    l6 = _l6_load(project)
    if l6 is None:
        print("SKIP — no L6_CONTROL_LOGIC.json present")
        return 0
    if not _l6_has_wake_gating(l6):
        print("SKIP — L6.wake_gating absent (no wake gating means "
              "pre-wake reject rule is not required)")
        return 0

    l3 = _l3_load(project)
    if l3 is None:
        print("SKIP — no L3_CMD_PROTOCOL.json present")
        return 0
    opcodes = _l3_opcodes(l3)
    if not opcodes:
        print("SKIP — L3 has no opcodes")
        return 0
    if not _has_pre_wake_false(opcodes):
        print("SKIP — no L3 opcode marks pre_wake_allowed=false; "
              "no per-opcode pre-wake reject rule required")
        return 0

    rr_blob = _reject_rules_text(l6)
    if not rr_blob.strip():
        failure = (
            "L6 has wake_gating + L3 has at least one "
            "pre_wake_allowed=false opcode, but L6.reject_rules is "
            "empty / missing. Need a rule of shape: pre-wake + "
            "opcode_not_in_pre_wake_whitelist ⇒ reject."
        )
        is_waived, rationale = _waived(project)
        if is_waived:
            print(f"PASS_WITH_WAIVER — silenced by waivers."
                  f"{WAIVER_KEY}: {rationale[:80]}…")
            print(f"  • {failure}")
            return 0
        print(f"FAIL — {failure}")
        return 1

    if _PRE_WAKE_REJECT_RE.search(rr_blob):
        print(
            "PASS — L6.reject_rules contains a pre-wake "
            "opcode-whitelist reject rule"
        )
        return 0

    failure = (
        "L6 has wake_gating + L3 has pre_wake_allowed=false "
        "opcode(s), but L6.reject_rules does not contain a "
        "matching pre-wake reject rule. Detection regex "
        "(case-insensitive): "
        "`pre[-_ ]wake.*opcode.*not.*whitelist` | "
        "`pre[-_ ]wake.*reject` | "
        "`awake_latch.*0.*reject`."
    )
    is_waived, rationale = _waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        print(f"  • {failure}")
        return 0

    print(f"FAIL — {failure}")
    print()
    print(
        "Or document the alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
