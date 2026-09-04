#!/usr/bin/env python3
"""
packet_length_check_present.py — Static audit for packet-length sanity
checks in any module that dispatches on a received command.

Rule (derived from v052 rtl/mac.v:392 and per-opcode length logic):

    Any RTL module that dispatches to handler/response logic based on an
    incoming command MUST contain at least ONE length-validity comparison
    of the form ``<something>_(len|cnt|count|size) == <literal>`` (or
    similar). Without one, packet length is neither validated nor used to
    steer the FSM — a classic class of bug where a 1-byte opcode and a
    multi-byte opcode share the same response path.

Static check (IC-agnostic):

  A file is considered a "dispatcher" iff any of:

    * contains ``case (cmd_op)`` or ``case (cmd_code)`` — an unambiguous
      command-opcode case,
    * contains ``case (opcode)``, ``case (cmd)`` or ``case (op)`` — names
      reused by instruction decoders and ordinary RTL, taken as a packet
      opcode only when the SAME file also carries byte-wide evidence (an
      ``8'hXX`` literal or an explicit 8-bit declaration of the selector),
    * contains 3+ lines matching ``if\\s*\\(\\s*\\w*cmd\\w*\\s*==\\s*8'h``
      (cascade of per-opcode if-equals comparisons).

  For every such file, look for at least one match of::

      \\b\\w*(_len|_cnt|_count|_size|len|cnt|count|size)\\s*==\\s*[0-9'hbd]

  If none is found, FAIL the file.

Outputs per-file finding; exit 0 clean, 1 on any finding, 2 on IO err.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    details: str = ""


# Case-statement dispatchers: "case (<id>)" where id is a typical opcode name.
#
# TWO tiers, because the names are not equally informative. `cmd_op` and
# `cmd_code` explicitly name a received command. `opcode`, `cmd` and `op` are
# also used by processor instruction decoders and ordinary enum logic, so on
# their own they are not evidence that this module dispatches on a packet.
#
# MEASURED false positive (opentitan_aes, 2026-09-02): `aes_ctrl_reg_shadowed`
# holds a shadowed CONTROL REGISTER and decodes its `aes_op_e` field with
#     unique case (op)
#       AES_ENC: ...
#       AES_DEC: ...
# There is no command, no packet and no length: the run's own class profile
# declares `command_protocol_applicable=false`, and eight sibling gates skip on
# exactly that fact. This gate reported an ERROR against a two-value enum
# decode, and did so TWICE — once directly and once through `rtl_precheck_gate`.
#
# So an AMBIGUOUS selector must be CORROBORATED by the thing this gate is
# actually about: byte-wide packet evidence in the same file. The UNAMBIGUOUS
# command-specific names keep their standalone force.
# v1.15.67 — the rule moved to `_opcode_dispatch_predicate`, written ONCE.
# `dispatcher_awake_gate_check` carried the SAME predicate UNCORRECTED and
# reached the same wrong conclusion on the same file one round later. These
# names are re-exports so this module's call sites and tests read unchanged.
from _opcode_dispatch_predicate import (          # noqa: E402
    CASE_DISPATCH_UNAMBIGUOUS_RE as _CASE_DISPATCH_UNAMBIGUOUS_RE,
    CASE_DISPATCH_AMBIGUOUS_RE as _CASE_DISPATCH_AMBIGUOUS_RE,
    BYTE_OPCODE_LITERAL_RE as _BYTE_OPCODE_LITERAL_RE,
    IF_OPCODE_EQ_RE as _IF_OPCODE_EQ_RE,
    is_opcode_dispatcher as _shared_is_dispatcher,
)

# Any length/count comparison — generous suffix set.
_LEN_EQ_RE = re.compile(
    r"\b\w*"
    r"(?:_len|_length|_cnt|_count|_size|_bytes|_num|_nbytes|_nbyte|payload_len|pkt_len|rsp_len)"
    r"\w*"
    r"\s*(?:==|!=|<=|>=|<|>)\s*"
    r"(?:\d+|\d*'[hbdHBD][0-9a-fA-F_]+|'[hbdHBD][0-9a-fA-F_]+)",
)


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        [p for p in rtl_dir.rglob("*")
         if p.is_file() and p.suffix.lower() in (".v", ".sv")]
    )


def _is_dispatcher(text: str) -> bool:
    return _shared_is_dispatcher(text)


def _has_length_check(text: str) -> bool:
    return bool(_LEN_EQ_RE.search(text))


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="IO",
            message=f"RTL directory not found: {rtl_dir}",
        ))
        return findings, {"dispatchers": [], "checked": 0}

    dispatchers: List[str] = []
    checked = 0

    for p in _find_v_files(rtl_dir):
        try:
            text = p.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                severity="ERROR",
                category="IO",
                message=f"Cannot read file: {e}",
                file=str(p),
            ))
            continue

        if not _is_dispatcher(text):
            continue
        dispatchers.append(str(p))
        checked += 1

        if not _has_length_check(text):
            findings.append(Finding(
                severity="ERROR",
                category="NO_LENGTH_CHECK",
                message=(
                    "Module dispatches on a byte command (case(cmd_op) / "
                    "corroborated case(opcode) / cmd==8'hXX cascade) but has no "
                    "'<...>_(len|cnt|count|size) == <literal>' "
                    "comparison anywhere — received-length validity is "
                    "not asserted."
                ),
                file=str(p),
            ))

    return findings, {"dispatchers": dispatchers, "checked": checked}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], rtl_dir: Path, summary: Dict) -> Dict:
    return {
        "program": "packet_length_check_present",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {
            "dispatcher_files": summary["dispatchers"],
            "files_checked": summary["checked"],
            "findings_count": len(findings),
            "pass": not any(f.severity == "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Flag command-dispatcher modules with no packet-length "
                     "validity comparison.")
    )
    parser.add_argument("--rtl-dir", required=True,
                        help="Directory containing .v / .sv RTL files")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Optional path to write machine-readable report")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    report = build_report(findings, rtl_dir, summary)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(report_json)

    print(report_json)
    # IO errors (missing RTL dir etc.) → exit 2 per the gate exit-code contract
    # (0 PASS / 1 FAIL / 2 input-missing).
    if any(getattr(f, "category", "") == "IO" for f in findings):
        return 2
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
