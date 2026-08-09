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
    1 = FAIL — ungated dispatcher (NO_AWAKE_GUARD), a flag driven awake and
        never cleared (NO_CLEAR_PATH), or a flag with exactly one clear path
        (SINGLE_CLEAR_PATH). NO_CLEAR_PATH was unreachable until the clear-path
        audit stopped drawing its subject list from clear paths; see `audit`.
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

_AWAKE_FAMILY = r'(awake|is_awake|wakeup|wake_done)'
_SLEEP_FAMILY = r'(sleep|is_sleep|sleeping|in_sleep|sleep_mode)'

# One-bit literals, anchored so a WIDER literal that merely BEGINS with the
# digit cannot satisfy them. The un-anchored `(?:1'b1|1|1'd1)` did: on
# `sleep <= 1'b0` the bare `1` alternative matched the SIZE field, so a write
# that WAKES the device was recorded as a clear path. Two such lines scored a
# design "2 clear paths -> PASS" while it had none — and, since the sleep
# family reached the clear-path store on every polarity, no sleep-polarity
# design could ever present zero clear paths for NO_CLEAR_PATH to see.
_ONE = r"(?:1'[bdh]1|1(?!\s*'|[0-9]))"
_ZERO = r"(?:1'[bdh]0|0(?!\s*'|[0-9]))"

# A write that returns the flag to the NON-awake state, under either polarity.
AWAKE_CLEAR_RE = re.compile(
    _AWAKE_FAMILY + r'\s*<=\s*' + _ZERO,
    re.IGNORECASE,
)

SLEEP_SET_RE = re.compile(
    _SLEEP_FAMILY + r'\s*<=\s*' + _ONE,
    re.IGNORECASE,
)

# The mirror image of the two above: a write that drives the flag INTO the
# awake state. `awake <= 1` and `sleep <= 0` are the same event under the two
# polarities, exactly as `awake <= 0` and `sleep <= 1` are the same event in
# AWAKE_CLEAR_RE / SLEEP_SET_RE. These exist so the clear-path audit has a
# subject universe that does NOT come from clear paths — see `audit`.
AWAKE_SET_RE = re.compile(
    _AWAKE_FAMILY + r'\s*<=\s*' + _ONE,
    re.IGNORECASE,
)

SLEEP_CLEAR_RE = re.compile(
    _SLEEP_FAMILY + r'\s*<=\s*' + _ZERO,
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
    awake_enter_paths: Dict[str, List[Tuple[str, int, str]]] = {}

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
            for m in AWAKE_SET_RE.finditer(line):
                awake_enter_paths.setdefault(m.group(1), []).append(
                    (fname, lineno, line.strip())
                )
            for m in SLEEP_CLEAR_RE.finditer(line):
                awake_enter_paths.setdefault(m.group(1), []).append(
                    (fname, lineno, line.strip())
                )

    if not awake_files:
        return findings, {
            "awake_signals": {},
            "dispatchers": dispatcher_files,
            "clear_paths": {},
            "enter_paths": {},
            "denominator": {"examined": 0, "signals": []},
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

    # The subject universe used to be `awake_clear_paths.keys()` — derived from
    # the evidence of the very property being audited. Every key there is born
    # of `setdefault(sig, []).append(...)`, so a key exists only once the signal
    # has at least one clear path, and `len(paths) < 2` could only ever observe
    # len == 1. The zero-clear-path case — the flag that is driven awake and
    # never returned, which is the WORST outcome this gate exists to catch —
    # removed its own signal from the universe and was scored PASS. That made
    # the gate non-monotonic: RTL that clears the flag once FAILED, RTL that
    # never clears it at all PASSED.
    #
    # The universe now also carries every signal this RTL drives INTO the awake
    # state. That is independent evidence, and it is deliberately narrower than
    # "every signal AWAKE_SIGNAL_RE matched": those matches include input ports
    # and wires a module merely READS (a block that receives `sleep_mode` has no
    # business clearing it), so enumerating them would invent FAILs. A write of
    # the awake polarity proves the signal is a wake-state element this RTL owns
    # and is therefore answerable for returning.
    subject_signals = sorted(set(awake_clear_paths) | set(awake_enter_paths))
    for sig in subject_signals:
        paths = awake_clear_paths.get(sig, [])
        enters = awake_enter_paths.get(sig, [])
        unique_files = set(p[0] for p in paths)
        # Membership in the union guarantees at least one of the two is
        # non-empty, so this indexes something real — no `if paths else ""`.
        anchor = paths[0] if paths else enters[0]
        if not paths:
            findings.append(Finding(
                "ERROR", "NO_CLEAR_PATH",
                f"Wake signal '{sig}' is driven INTO the awake state in "
                f"{len(enters)} location(s) and is cleared in NONE. Once the "
                f"device wakes it never returns to the non-awake state, so "
                f"EVERY wake-clearing stimulus the spec defines (power-on "
                f"reset, soft reset, timeout, brownout) is ignored — a "
                f"strictly worse defect than the single-clear-path case "
                f"below. Add a clear path for each spec-defined stimulus.",
                file=anchor[0],
                line=anchor[1],
                details=anchor[2],
            ))
        elif len(paths) < 2:
            findings.append(Finding(
                "ERROR", "SINGLE_CLEAR_PATH",
                f"Wake signal '{sig}' is only cleared in {len(paths)} "
                f"location(s) across {len(unique_files)} file(s). "
                f"Protocols with wake/sleep states require multiple "
                f"wake-clearing stimuli (power-on reset, soft reset, "
                f"timeout, brownout). A single clear path is a known-"
                f"broken implementation — any test scenario that "
                f"toggles a non-reset wake-clear stimulus will fail.",
                file=anchor[0],
                line=anchor[1],
            ))

    def _sites(store: Dict[str, List[Tuple[str, int, str]]]) -> Dict:
        # Keyed on the whole subject universe, so a signal with an EMPTY clear
        # list is visible in the report as an empty list rather than by being
        # absent — the absence is what made the zero case invisible.
        return {
            sig: [
                {"file": f, "line": ln, "code": c}
                for f, ln, c in store.get(sig, [])
            ]
            for sig in subject_signals
        }

    return findings, {
        "awake_signals": awake_files,
        "dispatchers": dispatcher_files,
        "dispatcher_awake_guard": dispatcher_has_awake_guard,
        "clear_paths": _sites(awake_clear_paths),
        "enter_paths": _sites(awake_enter_paths),
        "denominator": {
            "examined": len(subject_signals),
            "signals": subject_signals,
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
