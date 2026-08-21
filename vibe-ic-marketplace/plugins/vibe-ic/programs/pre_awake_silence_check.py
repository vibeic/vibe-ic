#!/usr/bin/env python3
"""
pre_awake_silence_check.py — M1: Verify that any protocol with a wake/sleep
state correctly gates command dispatch behind an awake flag, AND that all
spec-defined wake-clearing stimuli actually clear the flag.

General pattern (IC-agnostic):

    Many serial protocols have a "non-awake" / "sleep" / "idle" state where
    the device must silently ignore all incoming commands except the one
    designated wake/identify command.  Two things must be true:

    1. The command dispatcher must have an ``if (!awake)`` (or equivalent)
       guard that rejects non-wake commands.
    2. The awake flag must be CLEARED by every stimulus the spec defines
       (full brownout, soft reset, timeout, etc.) — not just one of them.

    If (1) is missing, the device responds to everything regardless of state.
    If (2) is incomplete, a valid clear-path (e.g. 80µs soft-reset) is ignored
    and the device stays awake when it shouldn't.

Static heuristic check.  Scans RTL for:
  - Signals matching ``awake``, ``wakeup``, ``is_awake``, ``sleep``, etc.
  - Dispatcher modules that reference the awake signal
  - The number of distinct clear/set paths for the awake signal

Usage:
    python3 pre_awake_silence_check.py --rtl-dir <dir> [--json <report.json>]

Exit codes:
    0 = PASS: a wake/sleep signal was found and its gating is correct
    1 = FAIL (ungated dispatcher / incomplete clear paths)
    2 = VACUOUS: nothing was examined — this RTL declares no wake or sleep
        signal at all, so there is no wake state to gate. #521: this used to
        be rc 0. It was one of three leads #515 could not reproduce, because
        a probe that passes a PROJECT directory is rejected by this gate's
        argparse (it takes `--rtl-dir`) and the rc 2 that comes back is the
        parser's, not a verdict. Driven through its documented interface it
        reproduces on 106 of the 107 tracked RTL directories. Also rc 2 for
        an IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

import _vacuous_exit as _vx


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


AWAKE_SIGNAL_RE = re.compile(
    r'\b(awake|is_awake|wakeup|wake_done|sleep_n|not_sleep|active_mode)\b',
    re.IGNORECASE,
)

SLEEP_SIGNAL_RE = re.compile(
    r'\b(sleep|is_sleep|sleeping|in_sleep|sleep_mode)\b',
    re.IGNORECASE,
)

DISPATCH_RE = re.compile(
    r'\bcase[szx]?\s*\(\s*(?:\w+\s*\.\s*)?'
    r'(cmd_op|opcode|cmd|op|cmd_code|rx_cmd|cmd_byte)\b',
    re.IGNORECASE,
)

IF_CMD_RE = re.compile(
    r'\bif\s*\(\s*\w*(?:cmd|opcode)\w*\s*==\s*',
    re.IGNORECASE,
)

AWAKE_CLEAR_RE = re.compile(
    r'(awake|is_awake|wakeup|wake_done)\s*<=\s*(?:1\'b0|0|1\'d0)',
    re.IGNORECASE,
)

SLEEP_SET_RE = re.compile(
    r'(sleep|is_sleep|sleeping|in_sleep|sleep_mode)\s*<=\s*(?:1\'b1|1|1\'d1)',
    re.IGNORECASE,
)


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        p for p in rtl_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".v", ".sv")
    )


def _strip_comments(src: str) -> str:
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding("ERROR", "IO", f"RTL directory not found: {rtl_dir}"))
        return findings, {}

    awake_files: Dict[str, List[str]] = {}
    dispatcher_files: List[str] = []
    dispatcher_has_awake_guard: Dict[str, bool] = {}
    awake_clear_paths: Dict[str, List[Tuple[str, int, str]]] = {}

    for p in _find_v_files(rtl_dir):
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)
        lines = text.split('\n')
        fname = str(p)

        awake_sigs = set()
        for m in AWAKE_SIGNAL_RE.finditer(text):
            awake_sigs.add(m.group(1))
        for m in SLEEP_SIGNAL_RE.finditer(text):
            awake_sigs.add(m.group(1))
        if awake_sigs:
            awake_files[fname] = sorted(awake_sigs)

        is_dispatcher = bool(DISPATCH_RE.search(text)) or len(IF_CMD_RE.findall(text)) >= 3
        if is_dispatcher:
            dispatcher_files.append(fname)
            has_guard = False
            for sig in awake_sigs:
                guard_re = re.compile(
                    rf'\bif\s*\(\s*!?\s*{re.escape(sig)}\b', re.IGNORECASE
                )
                if guard_re.search(text):
                    has_guard = True
                    break
            dispatcher_has_awake_guard[fname] = has_guard

        for lineno, line in enumerate(lines, 1):
            for m in AWAKE_CLEAR_RE.finditer(line):
                awake_clear_paths.setdefault(m.group(1), []).append(
                    (fname, lineno, line.strip())
                )
            for m in SLEEP_SET_RE.finditer(line):
                awake_clear_paths.setdefault(m.group(1), []).append(
                    (fname, lineno, line.strip())
                )

    if not awake_files:
        return findings, {
            "awake_signals": {},
            "dispatchers": dispatcher_files,
            "clear_paths": {},
            "skipped": True,
            "reason": "no wake/sleep signals found — protocol may not have wake state",
        }

    for dfile, has_guard in dispatcher_has_awake_guard.items():
        if not has_guard:
            findings.append(Finding(
                "ERROR", "NO_AWAKE_GUARD",
                "Command dispatcher has no awake/sleep guard — all commands "
                "are processed regardless of wake state. Add an "
                "'if (!awake) drop' gate before opcode dispatch.",
                file=dfile,
            ))

    all_clear_signals = set()
    for sig, paths in awake_clear_paths.items():
        all_clear_signals.add(sig)
    for sig in all_clear_signals:
        paths = awake_clear_paths.get(sig, [])
        unique_files = set(p[0] for p in paths)
        if len(paths) < 2:
            findings.append(Finding(
                "ERROR", "SINGLE_CLEAR_PATH",
                f"Wake signal '{sig}' is only cleared in {len(paths)} "
                f"location(s) across {len(unique_files)} file(s). "
                f"Protocols with wake/sleep states require multiple "
                f"wake-clearing stimuli (power-on reset, soft reset, "
                f"timeout, brownout). A single clear path is a known-"
                f"broken implementation — any test scenario that "
                f"toggles a non-reset wake-clear stimulus will fail.",
                file=paths[0][0] if paths else "",
                line=paths[0][1] if paths else 0,
            ))

    return findings, {
        "awake_signals": awake_files,
        "dispatchers": dispatcher_files,
        "dispatcher_awake_guard": dispatcher_has_awake_guard,
        "clear_paths": {
            sig: [{"file": f, "line": ln, "code": c} for f, ln, c in ps]
            for sig, ps in awake_clear_paths.items()
        },
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify wake/sleep gating on command dispatch and "
                    "completeness of wake-clearing paths."
    )
    ap.add_argument("--rtl-dir", required=True)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    is_pass = not any(f.severity == "ERROR" for f in findings)
    report = {
        "program": "pre_awake_silence_check",
        "version": "1.1.0",
        "rtl_dir": str(rtl_dir),
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    print(out)
    if any(f.category == "IO" for f in findings):
        return 2
    # #521 — routed from the gate's OWN `skipped` flag, never from the report
    # text (which is printed to STDOUT here, so the sentinel goes to stderr to
    # keep that document parseable).
    skipped = _vx.summary_is_skipped(report["summary"])
    if is_pass and skipped:
        _vx.announce_vacuous("pre_awake_silence_check",
                             _vx.skip_reason(report["summary"]))
    return _vx.exit_code(is_pass, skipped)


if __name__ == "__main__":
    sys.exit(main())
