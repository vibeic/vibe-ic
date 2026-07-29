#!/usr/bin/env python3
"""
dispatcher_awake_gate_check.py — v0.114 (BACKLOG-v7 P2.2).

For wake-required protocols (declared in L2 / L9), verify that the
dispatcher RTL gates non-wake commands behind the awake state — i.e.
only the wake/identify command (typically 0x74 GET_ID for <chip-class>-class
ICs) dispatches when awake_q == 0; all others silently drop until
awake_q transitions to 1.

Skipping this gate caused subtle v103/v104 race-conditions where a
host probe command landed before wake handshake completed, generating
phantom replies that confused tester state.

Static check (chip-AGNOSTIC):

  1. Find dispatcher RTL (any .v/.sv with `case (cmd_op | opcode | op | op_q | cmd_byte)`).
  2. Find a wake-state register: `awake_q | wake_q | woken_q | is_awake | wake_state`.
  3. Find the wake-immune opcode either by:
       (a) `cmd_wake_immune(...)` function in package, OR
       (b) `if (awake_q || op == <opcode>)` / `if (op == <opcode> || awake_q)` pattern.
  4. Verify that non-wake-immune opcodes are gated. Two acceptable patterns:
       (a) `if (!awake_q && op != <wake_op>) <drop / state <= IDLE>`
       (b) explicit `if (awake_q || op == <wake_op>) ... else ...` wrapping
           the opcode case.
  5. If neither pattern is found in the dispatcher's main case block →
     ERROR with actionable message.

Skips gracefully if dispatcher absent OR L2/L9 declares the protocol
does not require wake (`protocol.wake_required: false`).

Usage:
  python3 dispatcher_awake_gate_check.py <project_dir> [--json [PATH]]
Exit 0 PASS, 1 FAIL, 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


_OPCODE_CASE_RE = re.compile(
    r"\bcase\s*\(\s*(?:\w+\s*\.\s*)?(cmd_op|opcode|op|op_q|cmd_byte|cmd_code)\b",
    re.IGNORECASE,
)
_AWAKE_SIGNAL_RE = re.compile(
    r"\b(awake_q|wake_q|woken_q|is_awake|wake_state|awake_state)\b",
)
_WAKE_IMMUNE_FN_RE = re.compile(
    r"\b(cmd_wake_immune|wake_immune|is_wake_cmd)\s*\(",
)
_AWAKE_GATE_PATTERNS = [
    # (a) drop-non-wake form
    re.compile(r"if\s*\(\s*!\s*\w*awake\w*\s*&&", re.IGNORECASE),
    re.compile(r"if\s*\(\s*\w*awake\w*\s*==\s*1\s*'\s*[bd]\s*0", re.IGNORECASE),
    # (b) wrap form: `if (awake || op == GET_ID)`
    re.compile(r"if\s*\(\s*\w*awake\w*\s*\|\|", re.IGNORECASE),
    re.compile(r"if\s*\(\s*\w*\s*==\s*\w*GET_ID\w*\s*\|\|\s*\w*awake", re.IGNORECASE),
]


def _l2_l9_wake_required(project: Path) -> Optional[bool]:
    """Returns True if spec declares wake_required, False if explicitly
    declared not-required, None if no declaration found."""
    for layer_name in ("L2_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json", "L1_DATASHEET.json"):
        p = _pl.generated_docs_dir(project) / layer_name
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        # Look for protocol.wake_required: bool
        proto = d.get("protocol") or {}
        if isinstance(proto, dict) and "wake_required" in proto:
            return bool(proto["wake_required"])
        # Or top-level wake_required
        if "wake_required" in d:
            return bool(d["wake_required"])
        # Or protocol.requires_wake
        if isinstance(proto, dict) and "requires_wake" in proto:
            return bool(proto["requires_wake"])
    return None


def _find_dispatcher(project: Path) -> Optional[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return None
    for path in sorted(rtl_dir.rglob("*")):
        if path.suffix.lower() not in (".v", ".sv"):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if _OPCODE_CASE_RE.search(text):
            return path
    return None


def main(argv=None) -> int:
    # `argv` injectable, matching the 200 other gates here that take it. This
    # one read `sys.argv` unconditionally, so `main()` could not be driven from
    # a test at all — and `gate_cli_mutation_probe` reported it SILENT for
    # exactly that reason: nothing could exercise the path from verdict to exit
    # code, because nothing could call it with arguments.
    ap = argparse.ArgumentParser(description=(
        "Verify dispatcher RTL gates non-wake commands behind awake state."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    findings: List[Finding] = []

    # Skip if spec declares wake not required
    wake_req = _l2_l9_wake_required(project)
    if wake_req is False:
        result = {
            "program": "dispatcher_awake_gate_check",
            "version": "1.0.0",
            "project": str(project),
            "summary": {"skip": True, "reason": "spec declares wake_required=false", "pass": True},
            "findings": [],
        }
        if args.json is None:
            print("[PASS] dispatcher_awake_gate_check (skip — spec declares wake not required)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
            print(f"json: {args.json}")
        return 0

    dispatcher = _find_dispatcher(project)
    if dispatcher is None:
        result = {
            "program": "dispatcher_awake_gate_check",
            "version": "1.0.0",
            "project": str(project),
            "summary": {"skip": True, "reason": "no dispatcher RTL found", "pass": True},
            "findings": [],
        }
        if args.json is None:
            print("[PASS] dispatcher_awake_gate_check (skip — no dispatcher)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
            print(f"json: {args.json}")
        return 0

    rtl_text = dispatcher.read_text(errors="replace")

    # Verify dispatcher even mentions an awake-class signal
    has_awake = bool(_AWAKE_SIGNAL_RE.search(rtl_text))
    if not has_awake:
        findings.append(Finding(
            severity="ERROR",
            category="NO_AWAKE_SIGNAL",
            message=(
                f"Dispatcher RTL ({dispatcher.relative_to(project)}) has a "
                f"command opcode case but references no awake/wake state "
                f"register (awake_q / wake_q / woken_q / is_awake / "
                f"wake_state). Wake-required protocols must gate "
                f"non-wake-immune commands behind such a signal."
            ),
        ))
    else:
        # Look for any of the awake-gate patterns
        gate_match = any(p.search(rtl_text) for p in _AWAKE_GATE_PATTERNS)
        wake_immune_fn = bool(_WAKE_IMMUNE_FN_RE.search(rtl_text))
        if not gate_match and not wake_immune_fn:
            findings.append(Finding(
                severity="ERROR",
                category="NO_AWAKE_GATE",
                message=(
                    f"Dispatcher RTL references awake-class signals but "
                    f"the opcode case is not wrapped in an awake-gate "
                    f"pattern (e.g. `if (!awake_q && op != GET_ID)` drop, "
                    f"or `if (awake_q || op == GET_ID)` allow). Without "
                    f"this, non-wake commands dispatch on first arrival "
                    f"and can reply before the wake handshake completes."
                ),
            ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)
    result = {
        "program": "dispatcher_awake_gate_check",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "dispatcher_file": str(dispatcher.relative_to(project)),
            "wake_required_in_spec": wake_req,
            "awake_signal_referenced": has_awake,
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] dispatcher_awake_gate_check")
        print(f"  dispatcher: {dispatcher.relative_to(project)}")
        print(f"  spec wake_required: {wake_req}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
