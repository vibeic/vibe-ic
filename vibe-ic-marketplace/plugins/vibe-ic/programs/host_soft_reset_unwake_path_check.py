#!/usr/bin/env python3
"""
host_soft_reset_unwake_path_check.py — Verify that any soft-reset / abort
handling path in RTL also clears the wake-state flag.

THE PROBLEM
-----------
When a host issues a soft-reset command, the IC must return to the idle/un-awake
state. A common bug is that the reset handler clears protocol registers (counters,
byte buffers, FSM state) but forgets to deassert the `awake` / `woken` / `active`
flag. The IC ends up in a zombie state: it thinks it's still awake but has lost
all session context. The next legitimate wake command may then be ignored ("already
awake") or cause undefined behavior.

Heuristic
---------
For each module that declares a wake-state register (assigned via `<=` or `=`):
  - Detect whether the module has a soft-reset handling path:
    patterns like `cmd_op == CMD_RST`, `soft_reset`, `cmd_rst`, `cmd_abort`,
    or FSM state names containing `S_RESET` / `S_RST` / `S_ABORT`.
  - In the reset-handling path, check that the wake-state register is
    explicitly cleared (assigned to `0` / `1'b0` / `1'd0`).
  - FLAG (ERROR) if a reset path exists but doesn't clear the wake flag.
  - PASS silently if no soft-reset path is found (gate is conditional on the
    protocol declaring soft-reset).

USAGE
-----
    python3 host_soft_reset_unwake_path_check.py rtl/

EXIT CODES
----------
    0 — PASS (every soft-reset path clears the wake flag, or no soft-reset path)
    1 — FAIL (at least one reset path forgets the wake flag)
    2 — argument / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Collection routes
# through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the comment-strip/regex scan again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files

_STATE_TOKENS = (
    "awake", "woken", "active", "enable", "enabled", "started", "live",
    "running", "armed", "ready_lock", "on_state",
)

_RESET_TOKENS_RE = re.compile(
    r"\b(?:soft_reset|cmd_rst|cmd_reset|cmd_abort|"
    r"CMD_RST|CMD_RESET|CMD_ABORT|"
    r"S_RESET|S_RST|S_ABORT|ST_RESET|ST_RST|"
    r"STATE_RESET|STATE_RST|STATE_ABORT|"
    r"RESET_CMD|RST_CMD|ABORT_CMD)\b"
)

_RESET_CMP_RE = re.compile(
    r"cmd_op\s*==\s*\w*(?:RST|RESET|ABORT)\w*",
    re.IGNORECASE,
)


@dataclass
class Finding:
    severity: str
    file: str
    module: str
    line: int
    wake_flag: str
    reset_pattern: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _list_rtl_files(rtl_dir: Path) -> List[Path]:
    # Kimi-scale fix: shared authored-RTL collector (both audit() and
    # _build_report()'s files_scanned count go through this single point).
    return rtl_source_files(rtl_dir)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _modules_in(text: str):
    out = []
    pat_mod = re.compile(r"\bmodule\s+(\w+)\b")
    pat_end = re.compile(r"\bendmodule\b")
    cursor = 0
    while cursor < len(text):
        m = pat_mod.search(text, cursor)
        if not m:
            break
        e = pat_end.search(text, m.end())
        if not e:
            break
        out.append((m.group(1), m.start(), e.end()))
        cursor = e.end()
    return out


def _find_wake_registers(mod_text: str) -> List[str]:
    """Find wake-state registers that are assigned (<=) in the module."""
    found = []
    for tok in _STATE_TOKENS:
        assign_pat = re.compile(
            rf"\b({tok})\s*<=\s*", re.IGNORECASE
        )
        if assign_pat.search(mod_text):
            found.append(tok)
    return found


def _find_reset_regions(mod_text: str):
    """Find text regions that handle soft-reset.
    Returns list of (match_text, region_text, line_offset)."""
    regions = []
    for m in _RESET_TOKENS_RE.finditer(mod_text):
        start = max(0, m.start() - 50)
        end = min(len(mod_text), m.end() + 500)
        regions.append((m.group(), mod_text[start:end], m.start()))
    for m in _RESET_CMP_RE.finditer(mod_text):
        start = max(0, m.start() - 50)
        end = min(len(mod_text), m.end() + 500)
        regions.append((m.group(), mod_text[start:end], m.start()))
    return regions


def _wake_cleared_in_region(region_text: str, wake_flag: str) -> bool:
    """Check if the wake flag is cleared in the reset region."""
    clear_pat = re.compile(
        rf"\b{re.escape(wake_flag)}\s*<=\s*(?:0|1'b0|1'd0)\s*;",
        re.IGNORECASE,
    )
    return bool(clear_pat.search(region_text))


def _line_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def audit(rtl_dir: Path) -> List[Finding]:
    findings: List[Finding] = []
    files = _list_rtl_files(rtl_dir)

    for fpath in files:
        raw = fpath.read_text(errors="replace")
        text = _strip_comments(raw)

        for mod_name, mod_start, mod_end in _modules_in(text):
            mod_text = text[mod_start:mod_end]

            wake_regs = _find_wake_registers(mod_text)
            if not wake_regs:
                continue

            reset_regions = _find_reset_regions(mod_text)
            if not reset_regions:
                continue

            for wake_flag in wake_regs:
                all_cleared = True
                worst_region = None
                for reset_match, region_text, region_offset in reset_regions:
                    if not _wake_cleared_in_region(region_text, wake_flag):
                        all_cleared = False
                        worst_region = (reset_match, region_offset)
                        break

                if not all_cleared and worst_region:
                    reset_match, region_offset = worst_region
                    abs_line = _line_at_offset(text, mod_start + region_offset)
                    findings.append(Finding(
                        severity="ERROR",
                        file=str(fpath),
                        module=mod_name,
                        line=abs_line,
                        wake_flag=wake_flag,
                        reset_pattern=reset_match,
                        message=(
                            f"module `{mod_name}` has soft-reset path "
                            f"(`{reset_match}`) but does not clear "
                            f"wake flag `{wake_flag}` — IC may enter "
                            f"zombie state after host reset"
                        ),
                    ))

    return findings


def _build_report(findings: List[Finding], rtl_dir: Path) -> dict:
    return {
        "program": "host_soft_reset_unwake_path_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {
            "files_scanned": len(_list_rtl_files(rtl_dir)),
            "findings_count": len(findings),
            "pass": len(findings) == 0,
        },
        "findings": [f.as_dict() for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check that soft-reset paths clear wake-state flags.",
    )
    ap.add_argument("rtl_dir",
                    help="Directory of .v / .sv files to scan")
    ap.add_argument("--json", default=None,
                    help="Optional path for JSON report output")
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    if not rtl_dir.is_dir():
        print(f"ERROR: not a directory: {rtl_dir}", file=sys.stderr)
        return 2

    findings = audit(rtl_dir)
    report = _build_report(findings, rtl_dir)
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
