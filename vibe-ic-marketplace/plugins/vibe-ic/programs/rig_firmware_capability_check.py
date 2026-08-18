#!/usr/bin/env python3
"""rig_firmware_capability_check.py — Wave 58 / BACKLOG-v12 P0.5 plugin gate.

When test-rig firmware is the bottleneck for a HW-verification step
(e.g. <half-duplex-tester> driver lacks `force_low_pulse` mode required to verify
the 500 ms long-LOW unwake reset), the plugin must mark an EXPLICIT
WAIVER instead of silently SKIPping.  Otherwise a "RIG_BLOCKED"
column-D row reads as "RTL bug" in audit dashboards.

Two trigger paths
=================
A. `<project>/rig_capabilities.json` exists.  Schema:
       {
         "rig_id": "<half-duplex-tester>-1.2",
         "supported_modes": ["connect_test", "send_raw"],
         "required_modes": ["connect_test", "force_low_pulse"]
       }
B. Any file under `<project>/reports/**/*.json` carries
   `verdict == "NEEDS_FIRMWARE_SUPPORT"` or
   `status == "RIG_BLOCKED"`.

In either case the project's `waivers.json` MUST carry an entry whose
key starts with `rig_firmware_*` (or is exactly
`rig_firmware_blocker`) AND whose rationale ≥40 chars cites the
unsupported capability.  Without that explicit waiver, FAIL — so the
operator is forced to record the rig-firmware gap rather than let it
masquerade as silent SKIP.

Detection (chip-AGNOSTIC)
=========================
1. SKIP when neither trigger path applies — projects with fully
   capable rigs see no findings.
2. PASS when an explicit `rig_firmware_*` waiver exists.
3. FAIL when a trigger fires AND no waiver is present.

Honors waiver `rig_firmware_blocker` (≥40 chars), or any key matching
the prefix `rig_firmware_`.

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple, Optional

# Wave 78 — explicit class applicability. Rig-firmware capability
# applies to any IC that needs a host-tester / programmer for HW
# verification (AID-class half-duplex, digital cmd-driven, mixed-
# signal OTP). `unknown` is included so a profile that fails to
# classify still triggers the fail-closed check.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

_APPLICABLE_CLASSES = (
    "aid_class_half_duplex",
    "digital_cmd_driven",
    "mixed_signal_otp",
    "unknown",
)

WAIVER_PREFIX = "rig_firmware_"
WAIVER_MIN_LEN = 40


def load_rig_caps(project_dir: Path) -> Optional[dict]:
    p = project_dir / "rig_capabilities.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def scan_reports_for_blockers(project_dir: Path) -> List[Tuple[Path, str]]:
    """Return [(report_path, blocker_message), ...]"""
    out: List[Tuple[Path, str]] = []
    rep = project_dir / "reports"
    if not rep.is_dir():
        return out
    for path in rep.rglob("*.json"):
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            continue
        if "NEEDS_FIRMWARE_SUPPORT" not in content and \
           "RIG_BLOCKED" not in content and \
           "rig_blocked" not in content.lower() and \
           "firmware_unsupported" not in content.lower():
            continue
        try:
            d = json.loads(content)
        except Exception:
            continue
        # Walk dict for occurrences of the trigger strings.
        msg = _walk_for_blocker(d)
        if msg:
            out.append((path, msg))
    return out


def _walk_for_blocker(node, path: str = "") -> Optional[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            r = _walk_for_blocker(v, f"{path}.{k}" if path else k)
            if r:
                return r
    elif isinstance(node, list):
        for i, item in enumerate(node):
            r = _walk_for_blocker(item, f"{path}[{i}]")
            if r:
                return r
    elif isinstance(node, str):
        for trigger in (
            "NEEDS_FIRMWARE_SUPPORT",
            "RIG_BLOCKED",
            "rig_blocked",
            "firmware_unsupported",
        ):
            if trigger.lower() in node.lower():
                return f"{path}: {node[:120]}"
    return None


def find_rig_firmware_waiver(project_dir: Path) -> Tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    if not isinstance(d, dict):
        return False, ""
    for key, value in d.items():
        if not (key == "rig_firmware_blocker" or
                key.startswith(WAIVER_PREFIX)):
            continue
        if isinstance(value, str) and len(value.strip()) >= WAIVER_MIN_LEN:
            return True, f"{key}: {value.strip()[:80]}…"
        if isinstance(value, dict):
            r = value.get("rationale") or value.get("reason") or ""
            if isinstance(r, str) and len(r.strip()) >= WAIVER_MIN_LEN:
                return True, f"{key}: {r.strip()[:80]}…"
    return False, ""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: rig_firmware_capability_check.py <project_dir>")
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    # Wave 78 — explicit class gate. `unknown` is in the applicable
    # set (fail-closed: an unclassified project that ships a rig
    # capability file still gets audited).
    profile = detect_ic_class(project_dir)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class not in _APPLICABLE_CLASSES:
        print(f"SKIP — not applicable to ic_class={ic_class}")
        return 0

    findings: List[str] = []

    # Trigger A: rig_capabilities.json.
    caps = load_rig_caps(project_dir)
    if caps:
        supported = set(caps.get("supported_modes", []))
        required = set(caps.get("required_modes", []))
        missing = sorted(required - supported)
        if missing:
            findings.append(
                f"rig_capabilities.json: required modes "
                f"{missing} missing from supported_modes"
            )

    # Trigger B: report scan.
    for path, msg in scan_reports_for_blockers(project_dir):
        try:
            rel = path.relative_to(project_dir)
        except ValueError:
            rel = path
        findings.append(f"{rel}: {msg}")

    if not findings:
        print(
            "SKIP — no rig firmware blocker advertised "
            "(no rig_capabilities.json gap, no NEEDS_FIRMWARE_SUPPORT "
            "verdict in reports/)"
        )
        return 0

    is_waived, rationale = find_rig_firmware_waiver(project_dir)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(findings)} rig firmware "
            f"blocker(s), explicit waiver present: {rationale}"
        )
        for f in findings:
            print(f"  • {f}")
        return 0

    print(
        f"FAIL — {len(findings)} rig firmware blocker(s) advertised "
        f"but no `{WAIVER_PREFIX}*` waiver in waivers.json"
    )
    for f in findings:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  Without an explicit rig_firmware waiver, RIG_BLOCKED")
    print("  steps SILENTLY appear as SKIP in the audit dashboard,")
    print("  which is indistinguishable from `RTL bug, agent gave up`.")
    print("  Force the operator to record the blocker so reviewers can")
    print("  differentiate firmware gaps from chip bugs.")
    print()
    print(
        "Fix template (waivers.json):\n"
        '    {"rig_firmware_blocker": "<rig_id> firmware build <ver> '
        'lacks mode <name>; ticket <id>; pending firmware update."}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
