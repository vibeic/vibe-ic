#!/usr/bin/env python3
"""
memory_read_pipeline_check.py — Registered-read memory modules must
document their read latency, and consumers must match it.

Generic pattern (applies to any memory / BRAM / ROM module):
  When a memory module implements its read path as
    always @(posedge clk) rdata <= mem[addr];
  the returned `rdata` lags its `addr` by one clock cycle. This is
  correct BRAM semantics, but consumers often treat the read as
  "combinational" and miss the lag, yielding stale data.

  The companion issue is the OPPOSITE shape: if the memory is
  intended to be combinational (`assign rdata = mem[addr];`) but
  the RTL happens to use `reg` + registered assignment, consumers
  that expect immediate data also break.

This gate is NOT a substitute for `nba_addr_read_race_check` — that
gate checks the CONSUMER side (FSM driving addr and consuming data in
same always block); this gate checks the MEMORY module's own
contract. A consumer-side fix requires knowing the memory's read
latency, which this gate makes explicit.

Real occurrence (v068 <benchmark> fresh-agent):
  otp_reader.v original:
    data_valid <= rd_en;
    if (rd_en) data <= mem[addr];
  Both are NBA → data output is registered → 1-cycle read latency.
  But the module's comment said "Reads are single-cycle combinational
  (synchronous)", which the comment-writer meant "1-cycle latency
  synchronous" but the CONSUMER (cmd_fsm) read as "combinational
  availability". Consumer lost 1 byte per OTP fetch cycle.

Rule enforced
-------------
For each `module M(...) ... endmodule` whose port list contains
`output reg <DATA> [...]` AND whose body assigns `<DATA> <= mem[addr]`
(NBA from a RAM read), require one of:
  - An `output wire <DATA>` with `assign <DATA> = mem[addr];`
    (explicitly combinational — no lag).
  - A comment/docstring near the module header that contains the
    tokens `read latency = 1` / `1-cycle read latency` / `lat=1` /
    `pipeline = 1`.
  - A helper output port named `<DATA>_valid` (1-cycle-delayed
    rd_en strobe — the handshake gives consumer an explicit cue
    about the lag).

If none of these are present the read contract is merely UNSTATED —
`registered_read_undocumented`, severity WARN. An omission is a
documentation debt: the consumer has to read the RTL, but the RTL is
the truth and nothing in the module argues against it.

Two shapes are NOT omissions, and they are the ones this gate exists
to stop. In both, the module STATES something its own RTL contradicts,
so a consumer who does the right thing — believe the module — is
wrong. They are severity FAIL and they gate the flow:

  - `contradictory_read_doc` — the module header affirmatively claims
    a no-lag read ("combinational read", "asynchronous read",
    "zero-cycle read", "no read latency", "read latency = 0") while
    the body registers it (`<DATA> <= mem[addr];`). This is exactly
    the real occurrence below: the words said "combinational
    availability", the flops said otherwise, and the consumer lost a
    byte per fetch cycle. Documenting nothing would have been safer
    than documenting the opposite.
  - `mixed_read_semantics` — the SAME port is both procedurally
    assigned (`<DATA> <= mem[addr];`) and continuously assigned
    (`assign <DATA> = mem[addr];`). Beyond the latency ambiguity this
    is not legal Verilog: a variable may not carry both a procedural
    and a continuous driver. It cannot elaborate, so it can never be
    "the intended design" and there is nothing for an operator to
    weigh.

Severity note (v1.6.125 / #47 Fix 3 kept, and completed): "any finding
=> FAIL" was correctly removed, because escalating a missing comment
into a flow-blocking failure is not proportionate. What that change
left behind was a gate with no FAIL-severity rule at all — every
finding site was hard-coded WARN, so `verdict == "FAIL"` and exit 1
were unreachable and BOTH callers (the step-2
`optional_program_exit_zero` clause and the P0 umbrella's structural
gate runner, which both grade this program purely on its exit status)
recorded an unconditional PASS. The severity split above is what makes
the FAIL side of that verdict expressible again, without making the
omission case loud.

Usage
-----
    memory_read_pipeline_check.py <rtl_file_or_dir> [--json]

Exit codes
----------
    0 = no memory module contradicts its own read contract (an
        UNDOCUMENTED read latency is a WARN and does not gate)
    1 = at least one memory module contradicts its own read contract
        (`contradictory_read_doc` / `mixed_read_semantics`)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Collection routes
# through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the char-level comment strip again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    module: str
    message: str


MODULE_HEAD_RE = re.compile(
    r"module\s+([A-Za-z_][A-Za-z0-9_]*)\b([^;]*);(.*?)\bendmodule\b",
    re.DOTALL,
)

OUTPUT_REG_RE = re.compile(
    r"output\s+reg\s+(?:\[[^\]]*\]\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
)
OUTPUT_WIRE_RE = re.compile(
    r"output\s+(?:wire\s+)?(?:\[[^\]]*\]\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
)

# Registered read form: `<DATA> <= mem[addr];` or `<DATA> <= mem[...];`
REGISTERED_READ_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*<=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[[^\]]+\]\s*;",
)

# Combinational read form: `assign <DATA> = mem[addr];`
COMB_READ_RE = re.compile(
    r"\bassign\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[[^\]]+\]\s*;",
)

LATENCY_DOC_RE = re.compile(
    r"(?i)(?:read[-_ ]?latency\s*=?\s*1"
    r"|1[-_ ]?cycle\s+read"
    r"|lat\s*=\s*1"
    r"|pipeline\s*=\s*1"
    r"|registered\s+read"
    r"|synchronous\s+read)"
)

VALID_PORT_RE = re.compile(
    r"output\s+(?:reg\s+|wire\s+)?([A-Za-z_][A-Za-z0-9_]*?)_valid\b"
)

# An AFFIRMATIVE claim that the read costs no cycle. This is deliberately NOT
# the negation of LATENCY_DOC_RE: silence about latency is an omission (WARN),
# while these phrases are the module asserting the OPPOSITE of a registered
# read, which is what actually misleads a consumer.
#
# Kept narrow on purpose — a FAIL here fails step 2 of the flow. The noun forms
# only admit a short, closed qualifier vocabulary between the adjective and
# `read` (so prose like "combinational logic reads addr_q" is NOT a claim about
# read latency), and the predicate forms allow at most 24 comma/period-free
# characters of qualifier (so "read is registered, so the decode is
# combinational" cannot reach across the sentence).
_READ_QUAL = (r"(?:(?:mem|memory|array|ram|rom|register|regfile|reg|data"
              r"|dual|single|port|word|byte)[-\s]+){0,2}")
_NOT_A_VERB = r"(?!\s+(?:the|a|an|its|this|that|from|into|out|back)\b)"
CONTRADICTORY_READ_DOC_RE = re.compile(
    r"(?i)(?:"
    # "combinational read" / "combinatorial memory read"
    r"combinat(?:ional|orial)(?:ly)?[-\s]+" + _READ_QUAL + r"reads?\b" + _NOT_A_VERB
    # "reads are single-cycle combinational" / "read is purely combinational"
    + r"|reads?\s+(?:are|is)\b[^.,;\n]{0,24}?combinat(?:ional|orial)"
    # "asynchronous read" / "async ram read"
    + r"|async(?:hronous)?[-\s]+" + _READ_QUAL + r"reads?\b" + _NOT_A_VERB
    + r"|reads?\s+(?:are|is)\b[^.,;\n]{0,24}?async(?:hronous)?\b"
    # "zero-cycle read" / "0 cycle read" / "same-cycle read"
    + r"|(?:zero|0|same)[-_\s]?cycle\s+reads?\b"
    + r"|reads?\s+(?:are|is)\b[^.,;\n]{0,24}?(?:zero|0|same)[-_\s]?cycle"
    # "no read latency" / "read latency = 0"
    + r"|no\s+read[-_\s]?latency"
    + r"|read[-_\s]?latency\s*[:=]\s*0\b"
    r")"
)


def _line_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _strip_block_comments(src: str) -> str:
    # Keep line comments (we use those to find latency doc).
    return re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


def _blank_line_comments(src: str) -> str:
    """ORGANIC #798 — blank `// ... <EOL>` comments to spaces, OFFSET-PRESERVING
    (same length, same newline positions). The module-boundary + code detection
    runs over THIS view so a `// ... module spec_ram ; ...` integration-prose
    line cannot create a PHANTOM module (the DOTALL `MODULE_HEAD_RE` would
    otherwise latch onto the word after the first commented `module` token, name
    it the module, and swallow the file — leaving the REAL module unanalysed).
    Because blanking preserves offsets, the latency-doc search still reads the
    comment-PRESERVING `src` at the SAME offsets (the `//` doc-comment view)."""
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), src)


def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(errors="replace")
    src = _strip_block_comments(raw)
    # ORGANIC #798 — detect module boundaries over the `//`-BLANKED view (no
    # phantom modules from comment prose); read latency `//` doc-comments from
    # `src` at the shared offsets.
    scan_src = _blank_line_comments(src)
    findings: list[Finding] = []

    prev_mod_end = 0
    for mod_m in MODULE_HEAD_RE.finditer(scan_src):
        mod_name = mod_m.group(1)
        header = mod_m.group(2)
        body = mod_m.group(3)
        mod_start = mod_m.start()

        # Scan combined header+body for port declarations (both inline
        # in header and as separate statements in body).
        combined = header + ";" + body
        output_regs = {m.group(1) for m in OUTPUT_REG_RE.finditer(combined)}
        output_wires = {m.group(1) for m in OUTPUT_WIRE_RE.finditer(combined)}
        # output_wires includes output reg in some regex greediness; strip.
        output_wires -= output_regs

        # Registered reads in body
        reg_reads = []
        for rm in REGISTERED_READ_RE.finditer(body):
            out_name, arr_name = rm.group(1), rm.group(2)
            if out_name in output_regs:
                reg_reads.append((out_name, arr_name, rm.start()))

        if not reg_reads:
            continue  # no memory-read pattern in this module

        # For each registered-read output, check latency documentation
        # OR presence of a companion *_valid output port.
        # ORGANIC #798 — read the latency doc-comment from the COMMENT-PRESERVING
        # `src` at the shared offsets (the blanked scan_src has no `//` doc to
        # read). The header span maps 1:1 because blanking preserves offsets.
        header_raw = src[mod_m.start(2):mod_m.end(2)]
        # include a few lines ABOVE the module declaration (docstring)
        above_raw = src[max(0, mod_start - 400):mod_start]
        has_latency_doc = bool(LATENCY_DOC_RE.search(header_raw)) or bool(
            LATENCY_DOC_RE.search(above_raw)
        )
        # Read the CONTRADICTION over the same header span, but over a
        # DOCSTRING span clamped at the previous `endmodule`. The 400-char
        # look-back is a heuristic: on a multi-module file it can reach into
        # the module ABOVE, and attributing THAT module's (possibly true)
        # "combinational read" note to THIS one would fail a step of the flow
        # on a sentence about a different module. The clamp is applied only
        # here, so the reassurance window (`has_latency_doc`) keeps its exact
        # historical extent and no project changes WARN/PASS because of it.
        above_own = src[max(0, mod_start - 400, prev_mod_end):mod_start]
        prev_mod_end = mod_m.end()
        _lie = (CONTRADICTORY_READ_DOC_RE.search(header_raw)
                or CONTRADICTORY_READ_DOC_RE.search(above_own))
        comb_claim = _lie.group(0).strip() if _lie else ""

        for out_name, arr_name, off in reg_reads:
            # Check combinational read alternative
            is_also_comb = any(
                cm.group(1) == out_name
                for cm in COMB_READ_RE.finditer(body)
            )
            # Check companion _valid port
            valid_ports = {m.group(1) for m in VALID_PORT_RE.finditer(combined)}
            has_valid = out_name in valid_ports

            if is_also_comb:
                # Both reg and comb. Not merely ambiguous: a variable with a
                # procedural AND a continuous driver is not legal Verilog, so
                # this is never the intended design — FAIL.
                findings.append(Finding(
                    "FAIL", "mixed_read_semantics",
                    str(path), _line_of(src, off), mod_name,
                    f"Port `{out_name}` has both `<= mem[...]` (registered) "
                    f"and `assign {out_name} = mem[...]` (combinational). "
                    f"Consumer cannot know the latency, and a variable "
                    f"driven both procedurally and continuously does not "
                    f"elaborate. Pick one.",
                ))
                continue

            if comb_claim:
                # The module STATES a no-lag read and REGISTERS it. Reported
                # even when a `_valid` strobe or a latency note is also
                # present: a consumer who believes the header is still wrong,
                # and two mutually exclusive statements of the same contract
                # are not a documented contract.
                findings.append(Finding(
                    "FAIL", "contradictory_read_doc",
                    str(path), _line_of(src, off), mod_name,
                    f"Module `{mod_name}` documents a no-lag read "
                    f"({comb_claim!r}) but implements `{out_name} <= "
                    f"{arr_name}[addr];`, which registers the data — "
                    f"`{out_name}` lags `addr` by 1 cycle. A consumer that "
                    f"believes the header reads stale data every fetch. Fix "
                    f"options: (a) make the RTL match the claim with "
                    f"`assign {out_name} = {arr_name}[addr];`; (b) correct "
                    f"the header to '1-cycle read latency' / 'registered "
                    f"read' and pipeline the consumer.",
                ))
                continue

            if has_latency_doc or has_valid:
                continue

            findings.append(Finding(
                "WARN", "registered_read_undocumented",
                str(path), _line_of(src, off), mod_name,
                f"Module `{mod_name}` has registered read `{out_name} "
                f"<= {arr_name}[addr];` which means `{out_name}` lags "
                f"`addr` by 1 cycle. Consumer may incorrectly read it as "
                f"combinational. Fix options: (a) document in module "
                f"header as '1-cycle read latency' / 'registered read'; "
                f"(b) add a companion `output {out_name}_valid` strobe; "
                f"(c) if combinational is intended, use "
                f"`assign {out_name} = {arr_name}[addr];` instead.",
            ))

    return findings


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    # Kimi-scale fix: shared authored-RTL collector. This gate has always
    # also scanned *.vh headers, so the suffix set is widened accordingly.
    return rtl_source_files(path, exts=("*.v", "*.sv", "*.vh"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Require memory modules to document registered-read latency.",
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
        print(f"error: no .v/.sv/.vh under {target}", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    for f in files:
        all_findings.extend(check_file(f))
    warnings = [f for f in all_findings if f.severity == "WARN"]
    fails    = [f for f in all_findings if f.severity == "FAIL"]

    # v1.6.125 (#47 Fix 3) — verdict severity follows finding
    # severity. Earlier logic emitted FAIL whenever any finding
    # existed, escalating WARN to a flow-blocking FAIL. WARN
    # findings should not gate the canonical flow.
    if fails:
        verdict = "FAIL"
    elif warnings:
        verdict = "WARN"
    else:
        verdict = "PASS"

    if args.json:
        _txt = json.dumps({
            "target": str(target),
            "scanned": len(files),
            "total_findings": len(all_findings),
            "warnings": len(warnings),
            # Emitted alongside `warnings` so a reader of the artefact can see
            # WHICH side of the verdict split it landed on without re-deriving
            # it from `findings`.
            "fails": len(fails),
            "findings": [asdict(f) for f in all_findings],
            "verdict": verdict,
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in all_findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line} ({f.module})")
            print(f"    {f.message}")
        print(f"\n{len(warnings)} warning(s), {len(fails)} fail(s) "
              f"across {len(files)} file(s)")
        print(verdict)

    # Exit code (chip-AGNOSTIC): only FAIL gates the flow.
    # WARN-only findings exit 0 — verdict="WARN" is still surfaced
    # via the JSON output for downstream visibility.
    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
