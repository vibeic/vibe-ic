#!/usr/bin/env python3
"""
nba_addr_read_race_check.py — FSM consuming addressed data without pipelining.

Generic pattern (applies to any memory-backed FSM):
  When an FSM drives `<X>_addr_o` to an external memory / peripheral
  AND consumes the resulting `<X>_data_i` in the SAME always block
  without a pipeline stage between them, the consumer reads STALE
  data whenever the address was just updated.

  Ports using `_addr_o` / `_data_i` / `_valid_i` are the typical
  shape (vendor IP, RAM blocks, peripheral slaves). The NBA
  semantics of Verilog mean an assignment to `_addr_o <= NEW_ADDR`
  in cycle N doesn't appear at the peripheral until cycle N+1, and
  the resulting data doesn't propagate back until cycle N+2 (or
  cycle N+1 for combinational-read peripherals). Consuming
  `_data_i` in cycle N+1 therefore gets the PREVIOUS address's
  data, not the new address's.

Real occurrence (v068 <benchmark> fresh-agent):
  cmd_fsm.v S_OTP_FETCH did
      otp_addr_o <= {2'b00, otp_step};
      if (otp_valid_i) begin
          rsp_bytes[otp_step + 1] <= otp_data_i;
          otp_step <= otp_step + 5'd1;
      end
  The same always block updates otp_addr_o AND consumes otp_data_i
  AND increments otp_step. After the first fetch (otp_step=0 reads
  mem[0]=0x10), the next cycle reads mem[0] AGAIN instead of mem[1]
  because otp_addr_o's NBA update to {0,1} only took effect at end
  of that cycle, so otp_reader was still serving mem[0].

  Observable symptom on hardware: DUT response carries repeated
  OTP[0] byte instead of OTP[0],OTP[1],OTP[2]... Tester rejects.

Rule enforced (heuristic)
-------------------------
In each always block, detect:
  1. An output port assignment `<PREFIX>_addr[_o]? <= ...`
  2. A read of `<PREFIX>_data[_i]?` — either stored to another reg
     or compared/used in an if-condition
If both appear in the same always block, warn UNLESS the addr
assignment inside the data-consume branch uses `(reg + N)` form,
which is the documented pre-advance workaround that fixes the race.

This is a lint heuristic, not a formal proof. Teams can silence
individual warnings with a `// nba-addr-race-ok` trailing comment
on the relevant always block's begin.

Usage
-----
    nba_addr_read_race_check.py <rtl_file_or_dir> [--json]

Exit codes
----------
    0 = no suspicious patterns
    1 = one or more races detected
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    prefix: str
    message: str


# always @(posedge ...) ... begin — find the `begin` start.
ALWAYS_HEAD_RE = re.compile(
    r"always\s*@\s*\(\s*posedge\b[^)]*\)\s*begin\b",
)


def _find_always_blocks(src: str):
    """Yield (body_start, body_end) indexes for each always @(posedge...) begin ... end.

    Uses a simple begin/end counter to handle nested blocks. Strings and
    comments should be pre-stripped before calling.
    """
    for head in ALWAYS_HEAD_RE.finditer(src):
        body_start = head.end()
        depth = 1
        pos = body_start
        for tok in re.finditer(r"\b(begin|end)\b", src[pos:]):
            if tok.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    yield body_start, pos + tok.start()
                    break

# Address-port suffix variants seen in real RTL:
#   _addr, _addr_o            (vendor IP convention)
#   _raddr, _waddr            (memory-module read/write port convention)
#   _addr_in, _addr_a/_addr_b (dual-port RAM)
# v076 <benchmark> fresh-agent regression: `otp_raddr <= addr` + `otp_rdata` was
# not caught by the original `_addr(?:_o)?` regex because `raddr` ≠ `_addr`.
ADDR_ASSIGN_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*?)_(?:[rw])?addr(?:_o|_in|_a|_b)?\s*<=\s*([^;]+);"
)

# Data-port suffix variants:
#   _data, _data_i, _data_o
#   _rdata, _wdata, _dout, _din
DATA_READ_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*?)_(?:[rw])?(?:data|dout|din)(?:_i|_o|_a|_b)?\b"
)

# Pre-advance override: the addr assignment somewhere in the block
# contains `+ 1` or `+ N'dK` or `+ 1'b1` — an explicit unity increment
# indicating the author pre-advances for the next-cycle fetch. Base-
# offset additions like `7'h06 + reg` don't count (they're region
# offsets, not pre-advances).
PRE_ADVANCE_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*?)_(?:[rw])?addr(?:_o|_in|_a|_b)?\s*<=\s*[^;]*\+\s*(?:\d+\s*'[bhdBHD]\s*1\b|1\b|1\s*'[bhdBHD]\s*1\b)"
)

SILENCE_RE = re.compile(r"//\s*nba-addr-race-ok\b")


def _strip_comments_keep_silence(src: str) -> tuple[str, set[int]]:
    """Strip block comments, return (src_without_block_comments, silence_line_set).

    Single-line comments are kept; we use them to find silence markers.
    """
    src_no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    silence_lines = set()
    for i, line in enumerate(src_no_block.splitlines(), start=1):
        if SILENCE_RE.search(line):
            silence_lines.add(i)
    # Now strip line comments for analysis
    analysis = re.sub(r"//[^\n]*", "", src_no_block)
    return analysis, silence_lines


def _line_number_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(errors="replace")
    src, silence_lines = _strip_comments_keep_silence(raw)

    findings: list[Finding] = []

    # Capture full identifier (with suffix) for accurate diagnostics.
    ADDR_FULL_RE = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*?_(?:[rw])?addr(?:_o|_in|_a|_b)?)\s*<=\s*"
    )
    DATA_FULL_RE = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*?_(?:[rw])?(?:data|dout|din)(?:_i|_o|_a|_b)?)\b"
    )
    # Exclude write-side data signals (LHS): `otp_wdata <= ...` is the FSM
    # DRIVING the memory write port — not a memory read race.
    DATA_LHS_RE = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*?_(?:[rw])?(?:data|dout|din)(?:_i|_o|_a|_b)?)\s*<=\s*"
    )

    def _strip_known_suffix(name: str) -> str:
        for suf in ("_addr_o", "_addr_in", "_addr_a", "_addr_b", "_addr",
                    "_raddr", "_waddr",
                    "_data_i", "_data_o", "_data_a", "_data_b", "_data",
                    "_rdata", "_wdata",
                    "_dout", "_din"):
            if name.endswith(suf):
                return name[: -len(suf)]
        return name

    for bs, be in _find_always_blocks(src):
        body = src[bs:be]
        block_start = bs

        # Collect (prefix, full_name) pairs so we can report exact ports.
        addr_signals = {}  # prefix -> first full name
        data_signals = {}  # prefix -> first full name
        # Names that appear as LHS of a NBA → write-side, not a read race.
        data_lhs_names = {m.group(1) for m in DATA_LHS_RE.finditer(body)}
        for m in ADDR_FULL_RE.finditer(body):
            full = m.group(1)
            pre = _strip_known_suffix(full)
            addr_signals.setdefault(pre, full)
        for m in DATA_FULL_RE.finditer(body):
            full = m.group(1)
            if full in data_lhs_names:
                continue  # FSM is driving this signal (write port), not reading
            pre = _strip_known_suffix(full)
            data_signals.setdefault(pre, full)

        shared = set(addr_signals.keys()) & set(data_signals.keys())
        for prefix in sorted(shared):
            addr_name = addr_signals[prefix]
            data_name = data_signals[prefix]

            # Check for pre-advance override: ANY addr assignment in the
            # block that uses `reg + N` form. Presence suggests the
            # author is already handling the race.
            has_pre_advance = any(
                pa.group(1) == prefix
                for pa in PRE_ADVANCE_RE.finditer(body)
            )
            if has_pre_advance:
                continue

            # If ANY addr assignment for this prefix carries the silence
            # comment, the entire prefix is silenced (developer attests
            # the memory is combinational / handshake correct).
            silenced = any(
                _line_number_of(src, block_start + am.start()) in silence_lines
                for am in ADDR_ASSIGN_RE.finditer(body)
                if am.group(1) == prefix
            )
            if silenced:
                continue

            # Otherwise report on the first addr assignment line.
            for am in ADDR_ASSIGN_RE.finditer(body):
                if am.group(1) != prefix:
                    continue
                line_no = _line_number_of(src, block_start + am.start())
                findings.append(Finding(
                    "WARN", "addr_data_no_pipeline",
                    str(path), line_no, prefix,
                    f"always block writes `{addr_name}` and reads "
                    f"`{data_name}` without any pre-advance form "
                    f"`{addr_name} <= X + 1`. If the memory's read path is "
                    f"REGISTERED (`<=`-driven rdata), there is a 2-cycle "
                    f"effective latency from `{addr_name} <=` to valid "
                    f"`{data_name}`, but consumers usually only wait 1 "
                    f"cycle → stale read of mem[PREVIOUS addr]. Fix "
                    f"options: (a) make the memory read combinational "
                    f"(`assign rdata = mem[raddr];`) — recommended for "
                    f"OTP/ROM shadow reads; (b) pre-advance the addr "
                    f"(`{addr_name} <= <new>+1` in the store branch); "
                    f"(c) wait for an explicit `*_valid` handshake before "
                    f"sampling `{data_name}`. Silence with "
                    f"`// nba-addr-race-ok` only if you have verified the "
                    f"memory is truly combinational AND the consumer's "
                    f"timing is correct.",
                ))
                break

    return findings


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file() and p.suffix in (".v", ".sv", ".vh")
        )
    return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lint for addr/data pipeline races in RTL FSMs.",
    )
    ap.add_argument("target", help="RTL file or directory.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"error: not found: {target}", file=sys.stderr)
        return 2

    files = collect_files(target)
    if not files:
        print(f"error: no .v/.sv/.vh files under {target}", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    for f in files:
        all_findings.extend(check_file(f))
    warnings = [f for f in all_findings if f.severity == "WARN"]

    if args.json:
        _txt = json.dumps({
            "target": str(target),
            "scanned": len(files),
            "total_findings": len(all_findings),
            "warnings": len(warnings),
            "findings": [asdict(f) for f in all_findings],
            "verdict": "PASS" if not warnings else "FAIL",
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in all_findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line} ({f.prefix}_*)")
            print(f"        {f.message}")
        print(f"\n{len(warnings)} warning(s) across {len(files)} file(s)")
        print("PASS" if not warnings else "FAIL")

    return 0 if not warnings else 1


if __name__ == "__main__":
    sys.exit(main())
