#!/usr/bin/env python3
"""
bit_count_modulo_check.py — M3: Verify that serial RX bit assemblers
validate bit-count alignment at frame boundaries.

General pattern (IC-agnostic):

    Any serial RX path that assembles individual bits into bytes must
    ensure that the total bit count is a multiple of 8 (or the protocol's
    native symbol width) at frame end.  Without this check, a malformed
    frame with N*8+k bits (k>0) produces bit-shifted bytes that may
    spuriously pass CRC validation.

    Correct implementations expose a ``partial_bits_at_frame_end`` or
    ``bit_idx != 0`` flag, and the upstream dispatcher drops the frame
    when this flag is set.

Static heuristic check.  Scans RTL for:
  - Bit-counter signals (bit_cnt, bit_idx, bit_count, etc.)
  - Whether a modulo-8 or ==0 check exists at frame-end transitions
  - Whether the dispatcher references the partial-bits status

Usage:
    python3 bit_count_modulo_check.py --rtl-dir <dir> [--json <report.json>]

Exit: 0 = PASS, 1 = findings, 2 = IO error.

#496 — THE EXTRACTION WAS HIDING A REAL DEFECT
---------------------------------------------
``checked: 0`` on all 107 tracked ``rtl`` directories under ``benchmark-data``.
That zero was not absence. The gate's own bit-counter regex matches 125 times
across 6 of those directories; every one of those candidates was then dropped
by the SECOND conjunct, which required a symbol-valid strobe spelled as one of
exactly five literals (``byte_valid`` / ``byte_done`` / ``byte_rdy`` /
``rx_valid`` / ``rx_byte_valid``). The corpus's serial receivers spell it
``frame_valid``, ``rx_char_valid``, ``rx_bit_valid``, ``rd_valid``,
``left_valid`` — so a design could contain a bit assembler, a frame-end and no
alignment check whatsoever, and this gate would report a clean PASS.

One of them does. ``benchmark-data/evaluation/phase1_parity/hdlc/phase2/
stage1/rtl/hdlc_core.v`` asserts ``frame_valid <= 1'b1`` and computes
``fcs_ok`` the moment it recognises the closing flag, without ever testing
``rx_bit_cnt == 3'd0``. Its only comparison against that counter is
``rx_bit_cnt == 3'd7``, the octet-fill boundary inside RX_RECV — not an
alignment test at the frame boundary. A frame whose de-stuffed payload ends
mid-octet therefore raises ``frame_valid`` with the residual bits silently
discarded, which is verbatim the failure mode in this module's own header:
"produce bit-shifted bytes that may spuriously pass CRC". HDLC (ISO/IEC 13239)
requires a non-octet-aligned frame to be discarded.

The alias set is now the symbol-valid FAMILY — ``<x>_(valid|done|rdy|ready|
stb|strobe|ok)`` for x in byte/char/octet/sym/symbol/word/sample/frame/data —
which is the same generalisation with no protocol, vendor or part name in it.
Measured effect over the 107: selection rises from 0 to 2 directories, and the
verdict changes on exactly one — hdlc, to FAIL, for the reason above.

BECAUSE that FAIL is real, this gate still must NOT be wired into the P0
umbrella by this change: #492's bar requires no new FAIL over the corpus, and
this now has one. Wiring it is a decision about the hdlc defect, not about the
gate, and belongs with whoever owns that design.
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
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

# #496 — one unit of this gate's denominator, in the gate's own terms.
_DENOM_UNIT = "serial RX bit-assembler files"


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


BIT_COUNTER_RE = re.compile(
    r'\b(bit_cnt|bit_idx|bit_count|bit_pos|bit_num|bitcnt|bitidx|rx_bit_cnt|rx_bit_idx)\b',
    re.IGNORECASE,
)

# #496 — the strobe that says "one whole symbol has been assembled". The five
# literal spellings this used to enumerate are a subset of the family below;
# nothing protocol-, vendor- or part-specific is added, only the other nouns a
# designer uses for a symbol (char / octet / word / sample / frame / data) and
# the other verbs for "ready" (ready / stb / strobe / ok).
_SYMBOL_NOUNS = "byte|char|octet|sym|symbol|word|sample|frame|data"
_READY_VERBS = "valid|done|rdy|ready|stb|strobe|ok"
BYTE_VALID_RE = re.compile(
    r'\b\w*(?:' + _SYMBOL_NOUNS + r')_(?:' + _READY_VERBS + r')\w*\b'
    r'|\b\w*rx_valid\w*\b',
    re.IGNORECASE,
)

FRAME_END_RE = re.compile(
    r'\b(frame_end|frame_done|pkt_end|pkt_done|rx_done|rx_complete|'
    r'rx_end|packet_complete|eop|end_of_frame|end_of_packet)\b',
    re.IGNORECASE,
)

MODULO_CHECK_RE = re.compile(
    r'(bit_cnt|bit_idx|bit_count|bit_pos|bit_num|bitcnt|bitidx|rx_bit_cnt|rx_bit_idx)\s*'
    r'(?:==\s*(?:0|3\'d0|3\'b000)|!=\s*(?:0|3\'d0|3\'b000)|'
    r'%\s*8|&\s*3\'b111|&\s*3\'h7|\[\s*2\s*:\s*0\s*\]\s*(?:==|!=)\s*(?:0|3\'d0))',
    re.IGNORECASE,
)

PARTIAL_BITS_RE = re.compile(
    r'\b(partial_bit|partial_byte|bit_remain|bit_residue|'
    r'frame_align_err|bit_align_err|align_error|framing_error)\b',
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


def _denominator(files: int, bit_counter_files: int,
                 checked: int) -> GD.Denominator:
    details = {"files_scanned": files,
               "files_with_a_bit_counter": bit_counter_files}
    if checked:
        return GD.Denominator(unit=_DENOM_UNIT, examined=checked,
                              considered=bit_counter_files, details=details)
    if files == 0:
        reason = "no readable .v/.sv file in this directory."
    elif bit_counter_files == 0:
        reason = (
            f"{files} RTL file(s) read, none naming a bit counter "
            "(bit_cnt / bit_idx / bit_count / bit_pos / bit_num / ...). "
            "Nothing here assembles a serial bit stream into symbols, so "
            "there is no frame boundary at which alignment could be checked.")
    else:
        reason = (
            f"{bit_counter_files} file(s) name a bit counter but none also "
            "carries a symbol-complete strobe "
            f"(<{_SYMBOL_NOUNS}>_<{_READY_VERBS}>). Without one, the counter "
            "is not being used to assemble symbols and the modulo rule has no "
            "frame boundary to apply to. NOTE: this conjunct is what reported "
            "0 across the whole corpus while 125 bit-counter matches existed "
            "(#496) — if this reason appears on a design that plainly does "
            "assemble bytes, the strobe alias set is the thing to widen.")
    return GD.Denominator(unit=_DENOM_UNIT, examined=0,
                          considered=bit_counter_files,
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

    assembler_files: List[str] = []
    checked = 0
    files_scanned = 0
    bit_counter_files = 0

    for p in _find_v_files(rtl_dir):
        try:
            text = _strip_comments(p.read_text(errors="replace"))
        except OSError:
            continue
        files_scanned += 1
        fname = str(p)

        has_bit_cnt = bool(BIT_COUNTER_RE.search(text))
        has_byte_valid = bool(BYTE_VALID_RE.search(text))

        if has_bit_cnt:
            # #496 — count the candidates the second conjunct rejects. 125
            # such matches existed corpus-wide while `checked` read 0.
            bit_counter_files += 1
        if not (has_bit_cnt and has_byte_valid):
            continue

        assembler_files.append(fname)
        checked += 1

        has_frame_end = bool(FRAME_END_RE.search(text))
        has_modulo = bool(MODULO_CHECK_RE.search(text))
        has_partial = bool(PARTIAL_BITS_RE.search(text))

        if not has_frame_end:
            continue

        if not has_modulo and not has_partial:
            bit_cnt_locs = []
            for lineno, line in enumerate(text.split('\n'), 1):
                if BIT_COUNTER_RE.search(line) and BYTE_VALID_RE.search(line):
                    bit_cnt_locs.append(lineno)
                    break
            if not bit_cnt_locs:
                # #496 — a finding reported at line 0 is not actionable. The
                # two tokens frequently live on different lines (they do in
                # every corpus assembler), so fall back to the counter's own
                # first appearance rather than emitting a null location.
                for lineno, line in enumerate(text.split('\n'), 1):
                    if BIT_COUNTER_RE.search(line):
                        bit_cnt_locs.append(lineno)
                        break
            findings.append(Finding(
                "ERROR", "NO_BIT_ALIGNMENT_CHECK",
                "RX bit assembler has a bit counter and frame-end "
                "detection but no bit-count alignment check (modulo-8, "
                "bit_idx==0, or partial_bits flag) at frame boundary. "
                "Malformed frames with non-8-multiple bit counts will "
                "produce bit-shifted bytes that may spuriously pass CRC.",
                file=fname,
                line=bit_cnt_locs[0] if bit_cnt_locs else 0,
            ))

    all_files = _find_v_files(rtl_dir)
    dispatcher_refs_partial = False
    for p in all_files:
        try:
            text = _strip_comments(p.read_text(errors="replace"))
        except OSError:
            continue
        if PARTIAL_BITS_RE.search(text):
            is_dispatcher = bool(re.search(
                r'\bcase[szx]?\s*\(\s*(?:\w+\.)?'
                r'(cmd_op|opcode|cmd|op|cmd_code)\b',
                text, re.IGNORECASE
            )) or len(re.findall(
                r'\bif\s*\(\s*\w*cmd\w*\s*==\s*', text, re.IGNORECASE
            )) >= 3
            if is_dispatcher:
                dispatcher_refs_partial = True
                break

    if assembler_files and any(
        PARTIAL_BITS_RE.search(
            _strip_comments(Path(f).read_text(errors="replace"))
        ) for f in assembler_files
    ) and not dispatcher_refs_partial:
        findings.append(Finding(
            "WARN", "PARTIAL_NOT_CONSUMED",
            "RX assembler exposes a partial-bits / framing-error flag "
            "but the command dispatcher does not reference it. The "
            "dispatcher should drop frames where partial bits remain.",
        ))

    summary: Dict = {
        "assembler_files": assembler_files,
        "checked": checked,
        "files_scanned": files_scanned,
        "files_with_a_bit_counter": bit_counter_files,
    }
    GD.attach(summary, _denominator(files_scanned, bit_counter_files, checked))
    return findings, summary


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify bit-count alignment check at frame boundaries."
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
        "program": "bit_count_modulo_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json_out), out)
    print(out)
    if any(f.category == "IO" for f in findings):
        return 2
    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
