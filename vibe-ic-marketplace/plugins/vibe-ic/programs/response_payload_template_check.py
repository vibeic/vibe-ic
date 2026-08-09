#!/usr/bin/env python3
"""
response_payload_template_check.py — M5: Verify that response payload bytes
are assembled from dynamic data (register values, echoed arguments, computed
results) rather than hardcoded constants.

General pattern (IC-agnostic):

    When a command handler builds a response packet, each payload byte
    should come from a defined data source:
      - Echoed command argument (e.g. address echo in a write-ack)
      - Register or memory read value
      - Computed result (status bits, measurement)

    Hardcoded constant bytes in response assembly — e.g.
        ``fixed_buf[0] <= 8'h00;``
    — are a red flag: they often indicate the developer used a placeholder
    instead of wiring the correct dynamic data path.  The response will
    be structurally valid (right opcode, right length, valid CRC) but
    semantically wrong (wrong payload content).

Static heuristic check.  Scans RTL for:
  - Response buffer assignments (rsp_buf, tx_buf, fixed_buf, etc.)
  - Ratio of constant vs dynamic sources in those assignments
  - Flagging when >50% of payload bytes are hardcoded constants

Usage:
    python3 response_payload_template_check.py --rtl-dir <dir> [--json <report.json>]

Exit codes
----------
    0  PASS      at least one response-payload byte assignment was examined and
                 none of them tripped the ERROR tier below.
    1  FAIL      a response handler assembles its ENTIRE reply from literal
                 constants AND no assignment anywhere in that file takes its
                 value from a dynamic source. See "THE TWO TIERS".
    2  VACUOUS   nothing was examined (no response buffer / no dispatcher / no
                 indexed byte assignment), or the RTL directory is unreadable.
                 rc 2 is this repo's NOT-CHECKED code; it is emitted through
                 ``_vacuous_exit`` so the disclosure reaches the consumer's
                 channel instead of being credited as a PASS.

THE TWO TIERS, AND WHY THE GATE USED TO HAVE ONLY ONE
-----------------------------------------------------
Until this change every finding this program could emit was severity ``WARN``
and ``pass`` was ``not any(severity == "ERROR")``, whose only producer was the
IO error.  So on any readable RTL directory the exit-1 verdict this file's own
usage line advertises ("1 = findings") was STRUCTURALLY UNREACHABLE: the
program printed ``"pass": true`` while printing findings.  Driven, not read:
a synthetic dispatcher whose whole reply is ``8'h00`` — the maximum-severity
input this rule has — exited 0.

The repair is a severity split, not a louder gate:

  * WARN (advisory, rc 0) — MOSTLY_HARDCODED_RESPONSE.  >=50% of one opcode's
    payload bytes are literals while the SAME FILE does write dynamic bytes
    into a response buffer somewhere.  The data path exists and the author
    chose constants for some bytes; a fixed status/ID byte is legitimate, so
    this stays advisory and cannot redden a run.

  * ERROR (rc 1) — RESPONSE_PAYLOAD_NEVER_DYNAMIC.  Every payload byte of an
    opcode's handler is a literal AND the file never assigns a dynamic value
    to ANY response-buffer byte.  That is not "some constants are intentional",
    it is a reply packet that cannot vary with device state at all — the
    placeholder-never-wired shape this rule exists to name.

#496 — DENOMINATOR DISCLOSURE (classified: TRIGGER ABSENT FROM THIS CORPUS)
--------------------------------------------------------------------------
``total_assignments: 0`` on all tracked ``rtl`` directories under
``benchmark-data``. Re-measured for #496 against the corpus rather than against
the exit code:

  * The gate's own buffer-name list matches in only 3 of the directories,
    and in every one of those the file is not a command dispatcher, so the rule
    stops before its body.
  * A LOOSER probe — every file containing an opcode ``case`` AND any
    ``<name>[<integer>] <= ...`` byte-indexed write, regardless of the buffer's
    name — selects exactly ONE file corpus-wide, and its indexed signal is
    ``ch_enable`` (a per-channel enable vector), not a response payload.

So the subject of this rule — a command/response packet handler that assembles
reply bytes into an indexed buffer — does not occur in this corpus. That is
absence, not blindness.  RE-MEASURED after the severity split, with this
program's own CLI over every tracked ``rtl`` directory: 0 new FAIL, and
``denominator.examined == 0`` on every one of them (rc 2 VACUOUS, which used to
be rc 0 PASS — 108 greens over an empty denominator that no longer exist).

WHY THE CALLER WAS NOT ALSO CHANGED.  This gate is registered in
``flow_compliance_check._STRUCTURAL_RTL_GATES``, and the umbrella builds a
positional-project argv that this program's argparse rejects, so it is recorded
in ``p0_gate_invocability_drift_check.KNOWN_NOT_INVOCABLE`` and returns no
verdict in production.  Converting it (an entry in
``_STRUCTURAL_GATE_ARGV_ADAPTERS``) is governed by #492's two-condition bar —
no new FAIL over the corpus AND a non-zero denominator on EVERY project — which
``test_issue492_gate_argv_conversions.test_only_gates_that_cleared_both_bars_
were_converted`` enforces against ``P0_RTL_DIR_GROUP_MEASUREMENT``.  The second
condition is 0/108 here and cannot be cleared without fabricating a
measurement, so the conversion is NOT made.  What this change removes is the
OTHER half of that bar, the half that lived in this file: a gate that cleared
"adds no new FAIL" precisely BECAUSE it was incapable of failing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

import _gate_denominator as GD
import _vacuous_exit as VX

# #496 — one unit of this gate's denominator, in the gate's own terms.
_DENOM_UNIT = "response-payload byte assignments in a command dispatcher"

_GATE = "response_payload_template_check"

#: The advisory tier: some payload bytes are literals, but the file proves the
#: dynamic data path exists by writing at least one dynamic byte.
CAT_MOSTLY_HARDCODED = "MOSTLY_HARDCODED_RESPONSE"

#: The failing tier: an opcode's whole reply is literals and NOTHING in the file
#: ever writes a dynamic byte into a response buffer.
CAT_NEVER_DYNAMIC = "RESPONSE_PAYLOAD_NEVER_DYNAMIC"


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


RSP_BUF_RE = re.compile(
    r'\b(rsp_buf|tx_buf|fixed_buf|resp_buf|response_buf|'
    r'tx_data|rsp_data|resp_data|out_buf|send_buf)\b',
    re.IGNORECASE,
)

RSP_BUF_ASSIGN_RE = re.compile(
    r'(rsp_buf|tx_buf|fixed_buf|resp_buf|response_buf|'
    r'tx_data|rsp_data|resp_data|out_buf|send_buf)'
    r"\s*\[\s*(\d+)\s*\]\s*<=\s*(.+?)\s*;",
    re.IGNORECASE,
)

CONSTANT_VALUE_RE = re.compile(
    r"^(?:8'[hHbBdD][0-9a-fA-F_]+|[0-9]+|8'd[0-9]+|'[hH][0-9a-fA-F]+)$"
)

DISPATCH_RE = re.compile(
    r'\bcase[szx]?\s*\(\s*(?:\w+\.)?'
    r'(cmd_op|opcode|cmd|op|cmd_code|rx_cmd|cmd_byte)\b',
    re.IGNORECASE,
)

IF_CMD_RE = re.compile(
    r'\bif\s*\(\s*\w*(?:cmd|opcode)\w*\s*==\s*',
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


def _is_constant(rhs: str) -> bool:
    rhs = rhs.strip()
    return bool(CONSTANT_VALUE_RE.match(rhs))


def _denominator(files: int, buf_files: int, response_files: int,
                 assignments: int) -> GD.Denominator:
    details = {"files_scanned": files,
               "files_with_a_response_buffer_name": buf_files,
               "response_dispatcher_files": response_files}
    if assignments:
        return GD.Denominator(unit=_DENOM_UNIT, examined=assignments,
                              considered=assignments, details=details)
    if files == 0:
        reason = "no readable .v/.sv file in this directory."
    elif buf_files == 0:
        reason = (
            f"{files} RTL file(s) read, none naming a response buffer — "
            "searched for rsp_buf / tx_buf / fixed_buf / resp_buf / "
            "response_buf / tx_data / rsp_data / resp_data / out_buf / "
            "send_buf. This design assembles no reply packet.")
    elif response_files == 0:
        reason = (
            f"{buf_files} file(s) name a response buffer but none is a "
            "command dispatcher (no `case (cmd/opcode/...)` and fewer than 3 "
            "`if (cmd == ...)` comparisons), so there is no response HANDLER "
            "whose payload bytes could be compared against their sources.")
    else:
        reason = (
            f"{response_files} response-dispatcher file(s), but no byte "
            "assignment of the form `<buf>[<integer>] <= <expr>;` was found "
            "in them. The payload is not assembled through an indexed byte "
            "buffer, which is the only shape this rule can read.")
    return GD.Denominator(unit=_DENOM_UNIT, examined=0, considered=0,
                          not_applicable_reason=reason, details=details)


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding("ERROR", "IO", f"RTL directory not found: {rtl_dir}"))
        return findings, GD.attach({}, GD.Denominator(
            unit=_DENOM_UNIT, examined=0, considered=0,
            not_applicable_reason=(
                f"RTL directory not found: {rtl_dir} — nothing was read, so "
                "this result is an input error, not a verdict.")))

    response_files: List[str] = []
    all_assignments: List[Dict] = []
    files_scanned = 0
    buf_files = 0

    for p in _find_v_files(rtl_dir):
        try:
            text = _strip_comments(p.read_text(errors="replace"))
        except OSError:
            continue
        files_scanned += 1
        fname = str(p)

        if not RSP_BUF_RE.search(text):
            continue
        buf_files += 1

        is_dispatcher = bool(DISPATCH_RE.search(text)) or \
            len(IF_CMD_RE.findall(text)) >= 3
        if not is_dispatcher:
            continue

        response_files.append(fname)

        # Where THIS file's assignments start in the global list. The ERROR
        # tier asks a per-FILE question ("does this dispatcher ever write a
        # dynamic byte into its reply buffer?"), and asking it of the global
        # list would let an unrelated module in the same directory vouch for a
        # dispatcher that never wires one.
        file_start = len(all_assignments)

        lines = text.split('\n')
        per_opcode_blocks: Dict[str, List[Tuple[int, str, str, bool]]] = {}
        current_opcode = None

        for lineno, line in enumerate(lines, 1):
            op_m = re.search(
                r"(?:8'h|8'H)([0-9a-fA-F]{2})", line
            )
            if op_m and (re.search(r'\bcase\b', line, re.IGNORECASE) is None):
                if ':' in line or '==' in line:
                    current_opcode = f"0x{op_m.group(1).upper()}"

            for m in RSP_BUF_ASSIGN_RE.finditer(line):
                buf_name = m.group(1)
                idx = int(m.group(2))
                rhs = m.group(3).strip()
                is_const = _is_constant(rhs)

                entry = {
                    "buf": buf_name, "idx": idx, "rhs": rhs,
                    "constant": is_const, "line": lineno,
                    "opcode": current_opcode,
                }
                all_assignments.append(entry)

                if current_opcode:
                    per_opcode_blocks.setdefault(current_opcode, []).append(
                        (lineno, buf_name, rhs, is_const)
                    )

        # Does this dispatcher EVER take a payload byte from a dynamic source?
        # Counted over every indexed response-buffer write in the file, not
        # only the ones inside a recognised opcode block: one dynamic byte
        # anywhere is enough to prove the data path was wired.
        file_has_dynamic = any(
            not a["constant"] for a in all_assignments[file_start:])

        for opcode, assigns in per_opcode_blocks.items():
            if len(assigns) < 2:
                continue
            const_count = sum(1 for _, _, _, c in assigns if c)
            total = len(assigns)
            details = json.dumps([
                {"idx": a[1], "rhs": a[2], "const": a[3]} for a in assigns
            ])
            if const_count == total and not file_has_dynamic:
                # THE FAILING TIER. Not "some constants may be placeholders" —
                # this file assembles a reply packet and never once sources a
                # byte from device state, so the response cannot carry data at
                # all. A fixed status byte is legitimate; a fixed PACKET, in a
                # module with no dynamic payload path whatsoever, is the
                # placeholder that was never replaced.
                findings.append(Finding(
                    "ERROR", CAT_NEVER_DYNAMIC,
                    f"Response handler for opcode {opcode}: all {total} "
                    f"payload byte assignments are hardcoded constants, and "
                    f"no response-payload byte anywhere in this file is "
                    f"assigned from a dynamic source (echoed argument, "
                    f"register/memory read, computed value). The reply cannot "
                    f"vary with device state — the dynamic data path was "
                    f"never wired.",
                    file=fname,
                    line=assigns[0][0],
                    details=details,
                ))
            elif const_count > 0 and const_count >= total * 0.5 and total >= 2:
                findings.append(Finding(
                    "WARN", CAT_MOSTLY_HARDCODED,
                    f"Response handler for opcode {opcode}: "
                    f"{const_count}/{total} payload byte assignments use "
                    f"hardcoded constants. Verify each constant is "
                    f"intentional (e.g. fixed status) rather than a "
                    f"placeholder for dynamic data (echoed argument, "
                    f"register read, computed value).",
                    file=fname,
                    line=assigns[0][0],
                    details=details,
                ))

    summary: Dict = {
        "response_files": response_files,
        "files_scanned": files_scanned,
        "total_assignments": len(all_assignments),
        "constant_assignments": sum(1 for a in all_assignments if a["constant"]),
        "dynamic_assignments": sum(1 for a in all_assignments if not a["constant"]),
        "error_findings": sum(1 for f in findings if f.severity == "ERROR"),
        "warn_findings": sum(1 for f in findings if f.severity == "WARN"),
        # #496 recorded this program as advisory-only because no finding it
        # could emit was severity ERROR, which made its own advertised exit-1
        # verdict unreachable. The ERROR tier above ends that, and the field
        # stays — as `false` — so a consumer that learned to read it is told
        # the property changed instead of finding the key gone.
        "advisory_only": False,
        # `_vacuous_exit.summary_is_skipped` / `.skip_reason` read these two.
        "skipped": len(all_assignments) == 0,
        "reason": ("no response-payload byte assignment was examined"
                   if not all_assignments else ""),
    }
    GD.attach(summary, _denominator(files_scanned, buf_files,
                                    len(response_files), len(all_assignments)))
    return findings, summary


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Flag response payload bytes assembled from hardcoded "
                    "constants instead of dynamic data sources."
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
    skipped = VX.summary_is_skipped(summary)
    report = {
        "program": _GATE,
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {"pass": is_pass, "findings_count": len(findings),
                    **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    print(out)
    if any(f.category == "IO" for f in findings):
        return VX.RC_VACUOUS
    if is_pass and skipped:
        # Examined nothing. rc 0 here would certify a rule that never ran —
        # the same false green the ERROR tier above was added to make
        # distinguishable. Routed through `_vacuous_exit` so BOTH consumer
        # channels (rc 2 and the line-start sentinel) carry it.
        VX.announce_vacuous(_GATE, VX.skip_reason(summary))
    return VX.exit_code(is_pass, skipped)


if __name__ == "__main__":
    sys.exit(main())
