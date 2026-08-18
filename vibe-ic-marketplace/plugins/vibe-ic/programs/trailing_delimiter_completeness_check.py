#!/usr/bin/env python3
"""
trailing_delimiter_completeness_check.py — Verify each cmd packet stimulus
in a testbench drives the protocol's trailing delimiter, not just idle padding.

THE PROBLEM
-----------
On the v0.99 vendor fresh-agent run (and several earlier runs), bugs in
the dispatcher FSM survived sim because the integration testbench
appended `#500_000` (idle wait) AFTER each cmd packet instead of the
protocol's actual trailing delimiter (BR / EOF / STOP).

When the dispatcher gates on "trailing delimiter seen" and the TB never
sends one, the dispatcher's validation arm never fires — yet the TB
still PASSes byte-stream correctness, and the bug ships to FPGA.

This gate cross-references the L9 / L3 protocol layer (which declares
the canonical end-of-frame symbol) against every cmd-packet stimulus in
the TB and flags any packet that ends in idle padding without the
declared delimiter.

INPUT
-----
1. A testbench file or directory.
2. A protocol descriptor giving the trailing-delimiter token. Sources
   (in order of preference):
     a. ``--delimiter "<token>"`` on the command line.
     b. L3_CMD_PROTOCOL.json key ``trailing_delimiter`` or ``end_of_frame``.
     c. L9_INTEGRATION_SPEC.json key ``protocol.trailing_delimiter``.

USAGE
-----
    # Use spec-derived delimiter
    python3 trailing_delimiter_completeness_check.py sim/ \
        --layer-l3 generated_docs/L3_CMD_PROTOCOL.json

    # Override delimiter
    python3 trailing_delimiter_completeness_check.py sim/tb_top.v \
        --delimiter BR_HIGH

    # JSON output
    python3 trailing_delimiter_completeness_check.py sim/ \
        --layer-l3 generated_docs/L3_CMD_PROTOCOL.json \
        --json reports/gates/trailing_delim.json

EXIT CODES
----------
    0 — every cmd-packet stimulus is followed by the declared delimiter.
    1 — at least one packet ends in idle padding without the delimiter.
    2 — IO / argument error.

HEURISTICS
----------
This is a static text scan, not a full parser. It looks for two patterns
in each TB file:

    PACKET_BOUNDARY = a comment of form // CMD <opcode>... or send_cmd(0x..),
                      or a string assignment of the form `cmd = ...`.
    TRAILING_DELIMITER = the token (case-insensitive) within ~200 chars
                         after the boundary, OR a `#NNN` idle delay only.

The gate flags any packet boundary whose subsequent ~200-char window
contains a `#<digits>` (idle delay) but NOT the delimiter token.

False positives are possible (e.g. agent uses an idiosyncratic delimiter
naming). Either fix the TB to use the canonical token OR override with
``--delimiter`` to teach the gate the project's spelling.
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
    severity: str  # "ERROR" | "WARN" | "INFO"
    rule: str
    file: str
    line: int
    message: str


# Heuristic: find all "send a packet" sites in TB.
# Patterns we look for (case-insensitive in the comment forms):
#   // cmd 0x70 ...
#   // CMD: 0x74
#   // packet: ...
#   send_cmd(0x..);
#   send_packet(0x..);
#   drive_cmd(...);
PACKET_PATTERNS = [
    re.compile(r"//\s*(?:CMD|cmd|PACKET|packet|OPCODE)\s*[:\-]?\s*0x[0-9a-fA-F]"),
    re.compile(r"\b(send_cmd|send_packet|drive_cmd|drive_packet|tx_cmd|tx_packet)\s*\("),
]

IDLE_DELAY_RE = re.compile(r"#\s*[0-9_]+")


def _resolve_delimiter(delim_arg: Optional[str],
                       l3_path: Optional[Path],
                       l9_path: Optional[Path]) -> Optional[str]:
    if delim_arg:
        return delim_arg.strip()
    for p in (l3_path, l9_path):
        if p and p.exists():
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            for key in ("trailing_delimiter", "end_of_frame", "frame_end"):
                v = d.get(key) if isinstance(d, dict) else None
                if isinstance(v, str) and v.strip():
                    return v.strip()
            # Nested: protocol.trailing_delimiter / framing.end_of_frame
            proto = d.get("protocol") if isinstance(d, dict) else None
            if isinstance(proto, dict):
                for key in ("trailing_delimiter", "end_of_frame", "frame_end"):
                    v = proto.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
            framing = d.get("framing") if isinstance(d, dict) else None
            if isinstance(framing, dict):
                for key in ("trailing_delimiter", "end_of_frame", "frame_end",
                            "trailer"):
                    v = framing.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    return None


def _scan_file(path: Path, delimiter: str, window_chars: int = 200) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return findings
    lines = text.splitlines()

    # Find all packet-boundary sites with their absolute char offset
    # (so we can window into the post-boundary text).
    char_offset = 0
    line_offsets = [0]
    for ln in lines:
        char_offset += len(ln) + 1  # +1 for \n
        line_offsets.append(char_offset)

    boundaries: List[tuple[int, int]] = []  # (line_no_1based, char_offset)
    for pat in PACKET_PATTERNS:
        for m in pat.finditer(text):
            # find the line number
            pos = m.start()
            ln_no = next((i for i, lo in enumerate(line_offsets) if lo > pos), len(line_offsets)) - 1
            boundaries.append((ln_no + 1, pos))

    # Sort by char position
    boundaries.sort(key=lambda x: x[1])
    if not boundaries:
        return findings

    delim_lower = delimiter.lower()

    for i, (ln, pos) in enumerate(boundaries):
        # Look at the window between THIS boundary's start and the next
        # boundary (or end of file) — capped at window_chars chars.
        end_pos = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(text)
        window = text[pos:min(end_pos, pos + window_chars * 4)]
        # Truncate to window_chars beyond the FIRST line break,
        # ignoring the boundary line itself.
        nl = window.find("\n")
        body = window[nl + 1:] if nl >= 0 else window
        body = body[:window_chars]

        has_idle = bool(IDLE_DELAY_RE.search(body))
        has_delim = delim_lower in body.lower()

        if has_idle and not has_delim:
            findings.append(Finding(
                severity="ERROR",
                rule="trailing_delimiter_missing",
                file=str(path),
                line=ln,
                message=(
                    f"cmd packet boundary at line {ln} is followed by an idle "
                    f"delay (#NNN) but the trailing delimiter "
                    f"{delimiter!r} is not present in the next "
                    f"{window_chars} chars. The dispatcher under test will "
                    f"never see end-of-frame for this stimulus."
                ),
            ))

    return findings


def audit(tb_target: Path, delimiter: str, window_chars: int = 200) -> List[Finding]:
    findings: List[Finding] = []
    if tb_target.is_file():
        files = [tb_target]
    else:
        files = sorted(
            list(tb_target.rglob("tb_*.v")) +
            list(tb_target.rglob("tb_*.sv")) +
            list(tb_target.rglob("*_tb.v")) +
            list(tb_target.rglob("*_tb.sv"))
        )
    if not files:
        findings.append(Finding(
            "WARN", "no_testbench_files_found", str(tb_target), 0,
            f"no `tb_*.v`, `tb_*.sv`, `*_tb.v`, or `*_tb.sv` found under {tb_target}",
        ))
        return findings

    for f in files:
        findings.extend(_scan_file(f, delimiter, window_chars))

    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("tb", help="Testbench file or directory containing tb_*.v/.sv")
    ap.add_argument("--delimiter", default=None,
                    help="Override trailing delimiter token (case-insensitive)")
    ap.add_argument("--layer-l3", default=None,
                    help="Path to L3_CMD_PROTOCOL.json for delimiter lookup")
    ap.add_argument("--layer-l9", default=None,
                    help="Path to L9_INTEGRATION_SPEC.json for delimiter lookup")
    ap.add_argument("--window", type=int, default=200,
                    help="Chars after each packet boundary to inspect (default: 200)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args(argv)

    # v1.6.7: positional <project> auto-derive (dead-wire fix). When the
    # positional points at a project root (has generated_docs/ + sim/ or tb/),
    # auto-resolve L3 + use sim/ or tb/ as TB target.
    target = Path(args.tb)
    proj_mode = False
    if target.is_dir() and _pl.generated_docs_dir(target).is_dir() and not args.layer_l3:
        proj_mode = True
        l3 = _pl.generated_docs_dir(target) / "L3_CMD_PROTOCOL.json"
        l9 = _pl.generated_docs_dir(target) / "L9_INTEGRATION_SPEC.json"
        if not l3.exists():
            skip = {"verdict": "SKIP", "pass": True,
                    "reason": f"no L3 at {l3}"}
            print(json.dumps(skip, indent=2))
            return 0
        args.layer_l3 = str(l3)
        if l9.exists() and not args.layer_l9:
            args.layer_l9 = str(l9)
        # Pick first existing TB dir
        for sub in ("phase2/stage1/sim", "phase2/stage1/tb", "sim", "tb", "testbench", "verification"):
            cand = target / sub
            if cand.is_dir():
                target = cand
                break

    delim = _resolve_delimiter(
        args.delimiter,
        Path(args.layer_l3) if args.layer_l3 else None,
        Path(args.layer_l9) if args.layer_l9 else None,
    )
    if not delim:
        if proj_mode:
            skip = {"verdict": "SKIP", "pass": True,
                    "reason": "L3 has no delimiter field "
                              "(trailing_delimiter / end_of_frame / frame_end / trailer)"}
            print(json.dumps(skip, indent=2))
            return 0
        # v1.6.7: positional dir without any delimiter source → SKIP rc=0
        if target.is_dir() and not args.delimiter and not args.layer_l3 and not args.layer_l9:
            skip = {"verdict": "SKIP", "pass": True,
                    "reason": "no delimiter source provided "
                              "(no --delimiter / --layer-l3 / --layer-l9, "
                              "and target is not a project root with generated_docs/)"}
            print(json.dumps(skip, indent=2))
            return 0
        print("error: no trailing delimiter resolved (give --delimiter or --layer-l3/--layer-l9)",
              file=sys.stderr)
        return 2

    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, delim, args.window)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "delimiter": delim,
        "total_findings": len(findings),
        "errors": len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
