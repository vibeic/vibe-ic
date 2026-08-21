#!/usr/bin/env python3
"""spec_example_smoke_tb.py — ORGANIC #728 [P1, chip-AGNOSTIC]

EXECUTE THE PROMPT'S OWN GOLDEN EXAMPLE as a deterministic, blind-safe,
scorer-independent pre-emit gate.

WHY
  On v1.0.77 convergence forward-verify a functionally-WRONG first draft
  (a MAC that computed 0x0) passed EVERY shipped deterministic gate
  (interface / hygiene / spec-coverage / iverilog-compile / verilator) —
  yet the prompt LITERALLY carried a worked-example table
  (`op_a/op_b -> Expected Result`). No shipped gate extracted those
  example rows and RAN them, so the deterministic chain could not catch a
  first-draft functional miss and leaned on the hidden scorer.

  `spec_coverage_check.py` (#697) LISTS the requirements a prompt states.
  THIS gate EXECUTES the prompt's own worked examples: it drives the exact
  stated input values and asserts the exact stated output value, so a
  prompt-stated golden example becomes a real, blind (prompt-only),
  scorer-independent functional gate.

WHAT IT DOES
  INPUT : --prompt PROMPT  (USER station — the only source of golden rows)
          --rtl    RTL      (the authored RTL under test)
          --top    NAME     (optional; otherwise the RTL's first module)
  STEP 1: parse the RTL ports (name / direction / width) — DETERMINISTIC,
          reusing `_specrtl_common.parse_rtl_ports`.
  STEP 2: extract from the prompt the explicit worked-example rows:
            * markdown table rows  `a | b | sum` with a header row whose
              cells name actual RTL ports;
            * inline sentences  `a=3, b=4 -> sum=7`,
              `for input a=1 b=2 output is sum=3`,
              `a=3,b=4 => sum=7`;
          A row is KEPT only when EVERY left-hand `name=value` resolves to
          an RTL INPUT port AND the right-hand `name=value` resolves to an
          RTL OUTPUT port (names + values unambiguously parsed). Anything
          ambiguous is DROPPED (conservative — never invent a row).
  STEP 3: auto-generate a directed smoke testbench that, for each kept row,
          drives the inputs, waits for combinational settle, and asserts
          the output equals the stated value; compile + run with iverilog.
  STEP 4: BLOCK (exit 1) on a real extracted-example mismatch; PASS (exit 0)
          when all rows match.

REGISTER-MAP / INDIRECTION MODEL (ORGANIC #738)
  Many functionally-rich prompts address the DUT INDIRECTLY: the golden table
  writes operands to memory/register OFFSETS over an access protocol (APB /
  AXI-lite style), pulses a start/control bit, then reads a RESULT register
  back — e.g. `Write operand to offset 0x0, start via 0x8 bit0, read result at
  0x14. Example: mem[0x0]=5, mem[0x4]=7 -> result(0x14)=35.` The direct model
  finds no top-level `input=value -> output` row, so the #728 gate used to
  silently NOT-APPLICABLE on EXACTLY the multi-stage / CSR / RAM class where
  functional regressions hide. When NO direct row is extractable, this gate now
  parses the offset-keyed golden (operand offsets + values, a start register
  offset + bit, a result offset + expected value), maps the RTL bus ports
  STRUCTURALLY by protocol role (addr / wdata / rdata / pwrite / psel /
  penable / pready — protocol signal roles, never a chip SKU), and emits a
  directed write -> start -> readback bus TB that asserts the golden result
  (so a clobbered-CSR or lost-write bug is caught). It stays NOT-APPLICABLE
  unless the protocol parses confidently AND the RTL exposes a resolvable
  memory-mapped interface — never mis-driving.

§4.05 ASYMMETRY (no false-block — the hard guarantee)
  This gate only ever BLOCKs on a REAL extracted-example mismatch (direct row
  OR indirected register-map readback). It exits 0 (NOT-APPLICABLE, never
  blocking) when:
    * iverilog is not on PATH (cannot run — not our place to block); OR
    * NO example rows are extractable from the prompt (no direct row AND no
      confidently-parseable register-map golden), so there is nothing to fail;
      OR
    * a register-map golden is present but the RTL exposes no resolvable
      memory-mapped/APB interface (addr+wdata+rdata) to drive it safely.
  A prompt that states no worked example, or whose example names/values
  don't resolve to RTL ports, is NEVER charged as a failure.

chip-AGNOSTIC: pure prompt-example extraction + structural RTL port parse +
TB generation. NO chip / vendor / SKU literal (enforced by
`programs/source_chip_agnostic_check.py .`).

CLI
    python3 spec_example_smoke_tb.py --prompt PROMPT --rtl RTL [--top NAME]
                                     [--warn] [--json OUT]

Exit codes:
    0  PASS / NOT-APPLICABLE (no rows, or iverilog absent, or --warn)
    1  BLOCK — a real extracted-example row mismatched the RTL output
    2  argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Reuse the canonical Spec<->RTL port parser (module name + port
# direction + width). STRUCTURAL only — same primitive spec_coverage_check
# and spec_rtl_port_fidelity_check use.
try:
    import _specrtl_common as _SRC
except ImportError:  # packaged
    from . import _specrtl_common as _SRC  # type: ignore


# ---------------------------------------------------------------------------
# Example-row extraction (prompt-only, conservative)
# ---------------------------------------------------------------------------
# A `name = value` assignment. value: hex / bin / decimal (optional sign).
_ASSIGN_RE = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*"
    r"((?:[+-]?0[xX][0-9A-Fa-f_]+)"
    r"|(?:[+-]?\d+'[sS]?[bBhHdDoO][0-9A-Fa-fxXzZ_]+)"
    r"|(?:[+-]?0[bB][01_]+)"
    r"|(?:[+-]?\d+))"
)

# Separator between the input (driven) side and the output (asserted) side
# of a worked example. Accept the common arrows + a few English phrasings.
_ARROW_RE = re.compile(
    r"(?:->|→|=>|\bgives?\b|\byields?\b|\bproduces?\b|\bbecomes?\b|"
    r"\bresults?\s+in\b|\boutput\s+is\b|\bexpected(?:\s+result)?\s*:?)",
    re.I,
)


def _norm_value(raw: str) -> Optional[int]:
    """Parse a stated example value into a Python int. Returns None if the
    value is not unambiguously parseable (conservative -> drop the row)."""
    s = raw.strip().replace("_", "")
    neg = False
    if s and s[0] in "+-":
        neg = s[0] == "-"
        s = s[1:]
    try:
        # Verilog-sized literal: <size>'<base><digits>
        m = re.match(r"^\d+'[sS]?([bBhHdDoO])([0-9A-Fa-fxXzZ]+)$", s)
        if m:
            base_ch, digits = m.group(1).lower(), m.group(2)
            if any(c in "xXzZ" for c in digits):
                return None  # x/z value — not a concrete golden number
            base = {"b": 2, "o": 8, "d": 10, "h": 16}[base_ch]
            val = int(digits, base)
        elif s.lower().startswith("0x"):
            val = int(s, 16)
        elif s.lower().startswith("0b"):
            val = int(s, 2)
        else:
            val = int(s, 10)
    except (ValueError, KeyError):
        return None
    return -val if neg else val


@dataclass
class ExampleRow:
    inputs: Dict[str, int]   # input-port name -> driven value
    output: str              # output-port name
    expected: int            # asserted value
    source: str              # 'table' / 'inline'
    raw: str                 # the source text fragment (for the report)


def _line_segments(text: str) -> List[str]:
    """Split the prompt into candidate fragments that may hold one example
    each. A fragment is bounded by line breaks AND sentence terminators so a
    multi-row prose paragraph still yields one row per sentence."""
    segs: List[str] = []
    for line in text.splitlines():
        # split on sentence/clause terminators but keep arrows intact
        for piece in re.split(r"(?<=[.;])\s+|(?<=\))\s+(?=[A-Za-z])", line):
            piece = piece.strip()
            if piece:
                segs.append(piece)
    return segs


def _resolve_row(in_assigns: List[Tuple[str, str]],
                 out_assigns: List[Tuple[str, str]],
                 in_ports: Dict[str, int],
                 out_ports: Dict[str, int],
                 source: str, raw: str) -> Optional[ExampleRow]:
    """Build an ExampleRow ONLY if every LHS name is a real INPUT port, the
    single RHS name is a real OUTPUT port, and all values parse. Else None."""
    if not in_assigns or len(out_assigns) != 1:
        return None
    inputs: Dict[str, int] = {}
    for nm, val in in_assigns:
        if nm not in in_ports:
            return None  # ambiguous / not a driven port -> drop
        v = _norm_value(val)
        if v is None:
            return None
        inputs[nm] = v
    out_nm, out_val = out_assigns[0]
    if out_nm not in out_ports:
        return None
    exp = _norm_value(out_val)
    if exp is None:
        return None
    # Guard: a name can't be both side; require disjoint sets (it already is,
    # by the in/out port classification, but keep it explicit).
    if out_nm in inputs:
        return None
    return ExampleRow(inputs=inputs, output=out_nm, expected=exp,
                      source=source, raw=raw.strip()[:200])


def _extract_inline(text: str, in_ports: Dict[str, int],
                    out_ports: Dict[str, int]) -> List[ExampleRow]:
    rows: List[ExampleRow] = []
    for seg in _line_segments(text):
        m = _ARROW_RE.search(seg)
        if not m:
            continue
        left, right = seg[: m.start()], seg[m.end():]
        in_assigns = _ASSIGN_RE.findall(left)
        out_assigns = _ASSIGN_RE.findall(right)
        row = _resolve_row(in_assigns, out_assigns, in_ports, out_ports,
                           "inline", seg)
        if row:
            rows.append(row)
    return rows


def _split_md_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_md_delim(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def _extract_table(text: str, in_ports: Dict[str, int],
                   out_ports: Dict[str, int]) -> List[ExampleRow]:
    """Markdown example tables whose header cells name RTL ports, e.g.

        | a | b | sum |
        |---|---|-----|
        | 3 | 4 | 7   |
    """
    rows: List[ExampleRow] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if "|" not in lines[i]:
            i += 1
            continue
        header = _split_md_row(lines[i])
        # need a delimiter row right after the header
        if i + 1 >= len(lines) or "|" not in lines[i + 1] \
                or not _is_md_delim(_split_md_row(lines[i + 1])):
            i += 1
            continue
        # Map each header cell (stripped of markdown emphasis) to a port.
        col_role: List[Optional[str]] = []  # 'in' | 'out' | None
        col_name: List[str] = []
        for cell in header:
            nm = re.sub(r"[*_`]", "", cell).strip()
            col_name.append(nm)
            if nm in in_ports:
                col_role.append("in")
            elif nm in out_ports:
                col_role.append("out")
            else:
                col_role.append(None)
        n_in = col_role.count("in")
        n_out = col_role.count("out")
        # require at least one input column and exactly one output column,
        # and EVERY column resolves to a port (no stray columns -> ambiguity).
        if n_in >= 1 and n_out == 1 and all(r is not None for r in col_role):
            j = i + 2
            while j < len(lines) and "|" in lines[j]:
                cells = _split_md_row(lines[j])
                if _is_md_delim(cells):
                    j += 1
                    continue
                if len(cells) == len(header):
                    in_assigns: List[Tuple[str, str]] = []
                    out_assigns: List[Tuple[str, str]] = []
                    ok = True
                    for role, nm, cell in zip(col_role, col_name, cells):
                        v = re.sub(r"[*_`]", "", cell).strip()
                        if role == "in":
                            in_assigns.append((nm, v))
                        else:
                            out_assigns.append((nm, v))
                    if ok:
                        row = _resolve_row(in_assigns, out_assigns,
                                           in_ports, out_ports, "table",
                                           lines[j])
                        if row:
                            rows.append(row)
                j += 1
            i = j
        else:
            i += 1
    return rows


def extract_example_rows(prompt_text: str,
                         in_ports: Dict[str, int],
                         out_ports: Dict[str, int]) -> List[ExampleRow]:
    """All conservatively-resolvable golden rows from the prompt."""
    rows = _extract_table(prompt_text, in_ports, out_ports)
    rows.extend(_extract_inline(prompt_text, in_ports, out_ports))
    # de-dup identical rows (same inputs + output + expected)
    seen = set()
    uniq: List[ExampleRow] = []
    for r in rows:
        key = (tuple(sorted(r.inputs.items())), r.output, r.expected)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


# ---------------------------------------------------------------------------
# Register-map / indirection model (ORGANIC #738)
# ---------------------------------------------------------------------------
# The #728 direct-row model only resolves a top-level `input=value -> output`
# row. A large, functionally-rich class of prompt addresses the DUT INDIRECTLY:
# the golden table writes operands to memory/register OFFSETS over an access
# protocol (APB / AXI-lite style: psel/penable/pwrite/paddr/pwdata + prdata
# readback), pulses a start/control bit, then reads a RESULT register back. The
# direct extractor finds no `port=value -> port=value` row, so the gate silently
# no-ops on EXACTLY the multi-stage / CSR / RAM prompts where bugs hide.
#
# This model reads the prompt's offset-keyed golden (operand offsets + values,
# a start register offset + bit, a result offset + expected value), maps the
# RTL's bus ports STRUCTURALLY by protocol role (no chip / SKU literal), and
# emits a directed write -> start -> readback sequence that asserts the golden
# result. It stays NOT-APPLICABLE unless the protocol parses confidently.

# An offset literal: hex (0x..) or plain decimal. Used for register offsets.
_OFFSET_RE = r"(?:0[xX][0-9A-Fa-f]+|\d+)"

# Operand write: `mem[0x0]=5`, `mem[0x4] = 7`, `reg[0x0]=5`, `write 5 to offset 0x0`,
# `offset 0x0 = 5`. The bracketed form is the canonical golden shape; the
# `offset N = V` / `write V to offset N` prose forms are also accepted.
_MEM_WRITE_RE = re.compile(
    r"(?:mem|reg|ram|csr|register)\s*\[\s*(" + _OFFSET_RE + r")\s*\]\s*=\s*"
    r"([+-]?" + _OFFSET_RE + r")",
    re.I)
_OFFSET_WRITE_RE = re.compile(
    r"(?:write\s+([+-]?" + _OFFSET_RE + r")\s+to\s+(?:offset\s+)?(" + _OFFSET_RE
    + r")"
    r"|offset\s+(" + _OFFSET_RE + r")\s*=\s*([+-]?" + _OFFSET_RE + r"))",
    re.I)

# Start / control register: `start via 0x8 bit0`, `start at 0x8`,
# `control register 0x8 bit 0`, `pulse start (0x8)`.
_START_RE = re.compile(
    r"(?:start|control|go|trigger|enable|kick)\b[^.\n]{0,40}?"
    r"(?:offset\s+|register\s+|at\s+|via\s+|\(|@)\s*(" + _OFFSET_RE + r")"
    r"(?:[^.\n]{0,20}?bit\s*(\d+))?",
    re.I)

# Result readback: `read result at 0x14`, `result(0x14)=35`, `result register 0x14`,
# `read 0x14`. The expected value (`= 35`) is captured when present.
_RESULT_RE = re.compile(
    r"(?:result|output|read\s+result|readback|answer)\b[^.\n]{0,40}?"
    r"(?:offset\s+|register\s+|at\s+|\(|@|\s)\s*(" + _OFFSET_RE + r")\s*\)?"
    r"(?:[^.\n]{0,12}?=\s*([+-]?" + _OFFSET_RE + r"))?",
    re.I)


def _norm_offset(raw: str) -> Optional[int]:
    return _norm_value(raw)


@dataclass
class IndirectionGolden:
    """A directed register-map golden: write operands to offsets, pulse a start
    bit, then read the result offset and assert the expected value."""
    operand_writes: List[Tuple[int, int]]   # (offset, value), in stated order
    start_offset: Optional[int]             # control-register offset
    start_bit: int                          # which bit asserts start (default 0)
    result_offset: int                      # offset to read back
    expected: int                           # asserted readback value
    raw: str


def extract_indirection_golden(prompt_text: str) -> Optional[IndirectionGolden]:
    """Parse a register-map / address-indirected golden from the prompt, or None.

    Confidence floor (stay NOT-APPLICABLE unless ALL are present):
      * ≥1 operand write keyed by an offset with a concrete value;
      * a result offset WITH a concrete expected value;
      * a start/control register offset (so we know how to launch compute).
    The bracketed-offset / `offset N = V` golden cannot be confused with the
    direct `port=value -> port=value` row, so this never steals a #728 row."""
    operand_writes: List[Tuple[int, int]] = []
    for m in _MEM_WRITE_RE.finditer(prompt_text):
        off = _norm_offset(m.group(1))
        val = _norm_value(m.group(2))
        if off is not None and val is not None:
            operand_writes.append((off, val))
    for m in _OFFSET_WRITE_RE.finditer(prompt_text):
        if m.group(1) is not None:          # "write V to offset N"
            val, off = _norm_value(m.group(1)), _norm_offset(m.group(2))
        else:                               # "offset N = V"
            off, val = _norm_offset(m.group(3)), _norm_value(m.group(4))
        if off is not None and val is not None:
            operand_writes.append((off, val))

    # de-dup identical (offset,value) writes while keeping first-seen order
    seen_w: set = set()
    uniq_writes: List[Tuple[int, int]] = []
    for off, val in operand_writes:
        if (off, val) in seen_w:
            continue
        seen_w.add((off, val))
        uniq_writes.append((off, val))

    # The prompt may name the result register twice (a prose "read result at
    # 0x14" with no value, then "result(0x14)=35" in the worked example). Pick
    # the FIRST result match that carries a CONCRETE expected value.
    result_offset = None
    expected = None
    for rm in _RESULT_RE.finditer(prompt_text):
        if rm.group(2) is None:
            continue
        off = _norm_offset(rm.group(1))
        val = _norm_value(rm.group(2))
        if off is not None and val is not None:
            result_offset, expected = off, val
            break
    if result_offset is None or expected is None:
        return None  # no result offset with a concrete expected value

    sm = _START_RE.search(prompt_text)
    start_offset = _norm_offset(sm.group(1)) if sm else None
    start_bit = int(sm.group(2)) if (sm and sm.group(2) is not None) else 0

    # EXCLUDE the start-register and result-register offsets from the operand
    # writes (#738 r2). `_OFFSET_WRITE_RE` also matches the prose `result offset
    # 0x14 = 35` and a `write 1 to offset 0x8 to start` start-pulse line, so the
    # raw scrape double-counts the RESULT and START registers as operand writes —
    # which would make the TB spuriously pre-write the result/control register
    # before compute. The operand writes are exactly the offsets that are NEITHER
    # the start register NOR the result register.
    _reserved = {result_offset, start_offset}
    uniq_writes = [(off, val) for off, val in uniq_writes
                   if off not in _reserved]

    # Confidence floor: need at least one operand write, a start register, AND a
    # result-with-value. Anything short stays NOT-APPLICABLE (don't mis-drive).
    if not uniq_writes or start_offset is None:
        return None
    # The result offset must not collide with the start offset (that would be a
    # mis-parse, not a readback target).
    if result_offset == start_offset:
        return None
    return IndirectionGolden(
        operand_writes=uniq_writes, start_offset=start_offset,
        start_bit=start_bit, result_offset=result_offset, expected=expected,
        raw=prompt_text.strip()[:200])


# ---------------------------------------------------------------------------
# Structural APB / AXI-lite bus-port role mapping (chip-AGNOSTIC)
# ---------------------------------------------------------------------------
# Map the RTL's ports to canonical access-protocol ROLES by structural name
# shape. These are PROTOCOL SIGNAL ROLES (the APB / AXI-lite signal vocabulary),
# never a chip / vendor / SKU literal. A role is matched by a generic regex on
# the port name so any prefixed / suffixed variant (`s_apb_pwrite`, `pwrite_i`)
# still resolves. A bus is recognised ONLY when the minimal write+read set is
# present, else the indirection model declines (stays NOT-APPLICABLE).
@dataclass
class BusPorts:
    clk: Optional[str]
    rst: Optional[str]
    rst_active_low: bool          # back-compat: True iff polarity == 'low'
    rst_polarity: str             # 'low' | 'high' | 'ambiguous'
    addr: str
    wdata: str
    rdata: str
    write_en: Optional[str]      # pwrite / wr
    sel: Optional[str]           # psel
    enable: Optional[str]        # penable
    ready: Optional[str]         # pready / valid-style readback handshake
    family: str                  # 'apb' | 'memmap'
    addr_w: int
    data_w: int


_BUS_ROLE_RES = {
    # role : (regex on the bare port name, re.I)
    "clk": re.compile(r"^(?:.*_)?(?:p?clk|clock|aclk)$", re.I),
    "rst": re.compile(r"^(?:.*_)?(?:p?resetn|p?rst_?n|p?reset|p?rst|aresetn|arst)$", re.I),
    "addr": re.compile(r"^(?:.*_)?(?:paddr|awaddr|araddr|addr|address)$", re.I),
    "wdata": re.compile(r"^(?:.*_)?(?:pwdata|wdata|wr_?data|din|data_?in|wdat)$", re.I),
    "rdata": re.compile(r"^(?:.*_)?(?:prdata|rdata|rd_?data|dout|data_?out|rdat)$", re.I),
    "write_en": re.compile(r"^(?:.*_)?(?:pwrite|wr_?en|we|write|wen)$", re.I),
    "sel": re.compile(r"^(?:.*_)?(?:psel|cs|chip_?sel|sel)$", re.I),
    "enable": re.compile(r"^(?:.*_)?(?:penable|en|enable|valid)$", re.I),
    "ready": re.compile(r"^(?:.*_)?(?:pready|ready|ack|rvalid)$", re.I),
}

_RST_LOW_NAME_RE = re.compile(r"(?:resetn|rst_?n|aresetn|arst_?n)$", re.I)
# An UNAMBIGUOUS active-HIGH reset name: a trailing positive-polarity marker
# (`rst_p`, `reset_pos`, `por_h`) or a bare `por`/`set` that is never active-low.
# A bare `reset` / `rst` carries NO polarity marker and is therefore AMBIGUOUS.
_RST_HIGH_NAME_RE = re.compile(
    r"(?:_(?:p|pos|positive|h|high|hi))$|(?:^|_)por$", re.I)


def _rst_polarity(rst_name: Optional[str]) -> str:
    """Classify a reset port's polarity from its NAME alone.
      'low'        — an unambiguous active-low name (trailing 'n': resetn/rst_n/…)
      'high'       — an unambiguous active-high marker (rst_p/reset_pos/por/…)
      'ambiguous'  — a bare `reset`/`rst` with NO polarity marker either way.
    A bare-name reset must NOT be guessed active-high and then held asserted
    forever (#738 r2): that would keep a correct DUT in reset and false-BLOCK.
    The caller tries BOTH polarities for an ambiguous name."""
    if not rst_name:
        return "high"  # no reset port → the TB's reset block is skipped anyway
    if _RST_LOW_NAME_RE.search(rst_name):
        return "low"
    if _RST_HIGH_NAME_RE.search(rst_name):
        return "high"
    return "ambiguous"


def _match_role(role: str, names: List[str]) -> Optional[str]:
    """First port name that matches the role regex; longest match wins so a
    more-specific protocol name (`pwdata`) beats a generic one (`data`)."""
    rgx = _BUS_ROLE_RES[role]
    hits = [n for n in names if rgx.match(n)]
    if not hits:
        return None
    # prefer the canonical protocol-prefixed name over a generic alias
    hits.sort(key=lambda n: (len(n), n))
    return hits[0]


def resolve_bus_ports(in_ports: Dict[str, int],
                      out_ports: Dict[str, int]) -> Optional[BusPorts]:
    """Resolve the RTL ports to a memory-mapped/APB bus, or None if the minimal
    write+read interface (addr + wdata + rdata) is not present."""
    in_names = list(in_ports)
    out_names = list(out_ports)
    addr = _match_role("addr", in_names)
    wdata = _match_role("wdata", in_names)
    rdata = _match_role("rdata", out_names)
    if not (addr and wdata and rdata):
        return None
    clk = _match_role("clk", in_names)
    rst = _match_role("rst", in_names)
    write_en = _match_role("write_en", in_names)
    sel = _match_role("sel", in_names)
    enable = _match_role("enable", in_names)
    ready = _match_role("ready", out_names)
    family = "apb" if (sel and enable) else "memmap"
    rst_polarity = _rst_polarity(rst)
    rst_active_low = (rst_polarity == "low")
    return BusPorts(
        clk=clk, rst=rst, rst_active_low=rst_active_low,
        rst_polarity=rst_polarity, addr=addr,
        wdata=wdata, rdata=rdata, write_en=write_en, sel=sel, enable=enable,
        ready=ready, family=family,
        addr_w=in_ports.get(addr, 32), data_w=in_ports.get(wdata, 32))


def build_indirection_testbench(top: str, gold: IndirectionGolden,
                                bus: BusPorts,
                                in_ports: Dict[str, int],
                                out_ports: Dict[str, int],
                                force_active_low: Optional[bool] = None) -> str:
    """Emit a self-checking directed bus TB: drive a clock, release reset, write
    each operand to its offset, write the start bit, wait for the compute, read
    the result offset back, and assert the golden value. APB-style if psel +
    penable exist; otherwise a generic synchronous memory-mapped write/read.

    `force_active_low` overrides the reset polarity used in the reset block:
    None  -> use bus.rst_active_low (the name-classified polarity);
    True  -> drive the reset as active-low  (assert 0, deassert 1);
    False -> drive the reset as active-high (assert 1, deassert 0).
    The caller passes an explicit polarity for an AMBIGUOUS reset name and tries
    BOTH, so a bare `reset`/`rst` is never guessed-and-held (#738 r2)."""
    rst_active_low = (bus.rst_active_low if force_active_low is None
                      else force_active_low)
    dw = bus.data_w
    aw = bus.addr_w
    L: List[str] = []
    L.append("`timescale 1ns/1ps")
    L.append("module tb_spec_example_smoke;")
    L.append("  integer __errors = 0;")
    L.append("  reg clk_tb = 1'b0;")
    # declare reg/wire for every DUT port we connect, defaulting unused to 0
    driven = sorted(in_ports)
    checked = sorted(out_ports)
    for nm in driven:
        if nm == bus.clk:
            continue
        w = in_ports.get(nm, 1)
        rng = "" if w <= 1 else f"[{w-1}:0] "
        L.append(f"  reg {rng}{nm} = 0;")
    for nm in checked:
        w = out_ports.get(nm, 1)
        rng = "" if w <= 1 else f"[{w-1}:0] "
        L.append(f"  wire {rng}{nm};")
    # DUT instantiation: connect clk to the TB clock, everything else by name.
    conns = []
    for nm in driven + checked:
        if nm == bus.clk:
            conns.append(f".{nm}(clk_tb)")
        else:
            conns.append(f".{nm}({nm})")
    L.append(f"  {top} dut({', '.join(conns)});")
    L.append("  always #5 clk_tb = ~clk_tb;")

    def at(addr_val: int) -> str:
        return f"{aw}'h{addr_val:x}"

    # an APB write task (PSEL high, then PENABLE high for one cycle)
    if bus.family == "apb":
        L.append("  task apb_write(input [%d:0] a, input [%d:0] d);" % (aw - 1, dw - 1))
        L.append("    begin")
        L.append(f"      @(posedge clk_tb); {bus.addr} = a; {bus.wdata} = d;")
        if bus.write_en:
            L.append(f"      {bus.write_en} = 1'b1;")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b1;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b0;")
        L.append("      @(posedge clk_tb);")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b1;")
        L.append("      @(posedge clk_tb);")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b0;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b0;")
        if bus.write_en:
            L.append(f"      {bus.write_en} = 1'b0;")
        L.append("    end")
        L.append("  endtask")
        L.append("  task apb_read(input [%d:0] a, output [%d:0] d);" % (aw - 1, dw - 1))
        L.append("    begin")
        L.append(f"      @(posedge clk_tb); {bus.addr} = a;")
        if bus.write_en:
            L.append(f"      {bus.write_en} = 1'b0;")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b1;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b0;")
        L.append("      @(posedge clk_tb);")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b1;")
        L.append("      @(posedge clk_tb); #1;")
        L.append(f"      d = {bus.rdata};")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b0;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b0;")
        L.append("    end")
        L.append("  endtask")
    else:
        # generic synchronous memory-mapped write/read
        L.append("  task apb_write(input [%d:0] a, input [%d:0] d);" % (aw - 1, dw - 1))
        L.append("    begin")
        L.append(f"      @(posedge clk_tb); {bus.addr} = a; {bus.wdata} = d;")
        if bus.write_en:
            L.append(f"      {bus.write_en} = 1'b1;")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b1;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b1;")
        L.append("      @(posedge clk_tb);")
        if bus.write_en:
            L.append(f"      {bus.write_en} = 1'b0;")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b0;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b0;")
        L.append("    end")
        L.append("  endtask")
        L.append("  task apb_read(input [%d:0] a, output [%d:0] d);" % (aw - 1, dw - 1))
        L.append("    begin")
        L.append(f"      @(posedge clk_tb); {bus.addr} = a;")
        if bus.write_en:
            L.append(f"      {bus.write_en} = 1'b0;")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b1;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b1;")
        L.append("      @(posedge clk_tb); #1;")
        L.append(f"      d = {bus.rdata};")
        if bus.sel:
            L.append(f"      {bus.sel} = 1'b0;")
        if bus.enable:
            L.append(f"      {bus.enable} = 1'b0;")
        L.append("    end")
        L.append("  endtask")

    L.append(f"  reg [{dw-1}:0] __rd;")
    L.append("  integer __k;")
    L.append("  initial begin")
    # reset
    if bus.rst:
        assert_lvl = "1'b0" if rst_active_low else "1'b1"
        deassert_lvl = "1'b1" if rst_active_low else "1'b0"
        L.append(f"    {bus.rst} = {assert_lvl};")
        L.append("    repeat (3) @(posedge clk_tb);")
        L.append(f"    {bus.rst} = {deassert_lvl};")
        L.append("    @(posedge clk_tb);")
    # operand writes
    for off, val in gold.operand_writes:
        masked = val & ((1 << dw) - 1)
        L.append(f"    apb_write({at(off)}, {dw}'h{masked:x});")
    # start pulse: write a word with the start bit set to the control offset
    start_word = 1 << gold.start_bit
    start_word &= (1 << dw) - 1
    L.append(f"    apb_write({at(gold.start_offset)}, {dw}'h{start_word:x});")
    # allow the pipeline / FSM to compute; poll the ready/result for a bounded
    # number of cycles so a multi-cycle compute still settles deterministically.
    L.append("    repeat (64) @(posedge clk_tb);")
    # readback + assert
    exp_masked = gold.expected & ((1 << dw) - 1)
    L.append(f"    apb_read({at(gold.result_offset)}, __rd);")
    L.append(f"    if (__rd !== {dw}'h{exp_masked:x}) begin")
    L.append(
        f'      $display("SPEC_EXAMPLE_FAIL indirected: result(0x{gold.result_offset:x})'
        f' expected {exp_masked} got %0d (0x%0h)", __rd, __rd);')
    L.append("      __errors = __errors + 1;")
    L.append("    end else begin")
    L.append(
        f'      $display("SPEC_EXAMPLE_PASS indirected: result(0x{gold.result_offset:x})'
        f'={exp_masked}");')
    L.append("    end")
    L.append("    if (__errors != 0)")
    L.append('      $display("SPEC_EXAMPLE_SMOKE_RESULT=FAIL errors=%0d", __errors);')
    L.append("    else")
    L.append('      $display("SPEC_EXAMPLE_SMOKE_RESULT=PASS");')
    L.append("    $finish;")
    L.append("  end")
    # global watchdog so a never-settling DUT cannot hang the gate
    L.append("  initial begin")
    L.append("    #100000;")
    L.append('    $display("SPEC_EXAMPLE_SMOKE_RESULT=FAIL errors=1 (timeout)");')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Testbench generation
# ---------------------------------------------------------------------------
def _mask(width: int) -> str:
    """Verilog-safe expected value masked to the port width (so a stated
    sum=7 on a 9-bit port compares against the low 9 bits)."""
    return str(width)


def build_testbench(top: str, rows: List[ExampleRow],
                    in_ports: Dict[str, int],
                    out_ports: Dict[str, int]) -> str:
    """Emit a self-checking directed TB string. Drives each row's inputs,
    settles combinationally (#1), and asserts the masked output."""
    driven = sorted({nm for r in rows for nm in r.inputs})
    checked = sorted({r.output for r in rows})
    lines: List[str] = []
    lines.append("`timescale 1ns/1ps")
    lines.append("module tb_spec_example_smoke;")
    lines.append("  integer __errors = 0;")
    for nm in driven:
        w = in_ports.get(nm, 1)
        rng = "" if w <= 1 else f"[{w-1}:0] "
        lines.append(f"  reg {rng}{nm};")
    for nm in checked:
        w = out_ports.get(nm, 1)
        rng = "" if w <= 1 else f"[{w-1}:0] "
        lines.append(f"  wire {rng}{nm};")
    # DUT instantiation — named port connections (only driven + checked).
    conns = ", ".join(f".{nm}({nm})" for nm in (driven + checked))
    lines.append(f"  {top} dut({conns});")
    lines.append("  initial begin")
    for idx, r in enumerate(rows):
        for nm in driven:
            if nm in r.inputs:
                lines.append(f"    {nm} = {r.inputs[nm]};")
        lines.append("    #1;")
        ow = out_ports.get(r.output, 1)
        # mask the expected value to the output width
        exp_masked = r.expected & ((1 << ow) - 1)
        in_str = ", ".join(f"{nm}={r.inputs[nm]}" for nm in sorted(r.inputs))
        lines.append(
            f"    if ({r.output} !== {ow}'d{exp_masked}) begin")
        lines.append(
            f'      $display("SPEC_EXAMPLE_FAIL row {idx}: {in_str} -> '
            f'expected {r.output}={exp_masked} got %0d (0x%0h)", '
            f"{r.output}, {r.output});")
        lines.append("      __errors = __errors + 1;")
        lines.append("    end else begin")
        lines.append(
            f'      $display("SPEC_EXAMPLE_PASS row {idx}: {in_str} -> '
            f'{r.output}={exp_masked}");')
        lines.append("    end")
    lines.append("    if (__errors != 0)")
    lines.append('      $display("SPEC_EXAMPLE_SMOKE_RESULT=FAIL errors=%0d", __errors);')
    lines.append("    else")
    lines.append('      $display("SPEC_EXAMPLE_SMOKE_RESULT=PASS");')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
@dataclass
class Result:
    verdict: str             # PASS / BLOCK / NOT_APPLICABLE
    reason: str
    rows: List[dict]
    sim_log: str = ""


def _run_indirection(prompt_text: str, rtl_text: str, top: str,
                     gold: IndirectionGolden,
                     in_ports: Dict[str, int], out_ports: Dict[str, int],
                     warn: bool) -> Result:
    """Execute a register-map / address-indirected golden as a directed
    write -> start -> readback bus TB. Fail-SAFE: if the access protocol can't
    be resolved to RTL bus ports, or iverilog is absent, stay NOT-APPLICABLE."""
    gold_json = [{
        "kind": "indirection",
        "operand_writes": [{"offset": o, "value": v}
                           for o, v in gold.operand_writes],
        "start_offset": gold.start_offset,
        "start_bit": gold.start_bit,
        "result_offset": gold.result_offset,
        "expected": gold.expected,
    }]

    bus = resolve_bus_ports(in_ports, out_ports)
    if bus is None:
        # The prompt described an indirection golden but the RTL does not expose
        # a resolvable memory-mapped/APB interface (addr+wdata+rdata). Don't
        # mis-drive — stay NOT-APPLICABLE rather than risk a false BLOCK.
        return Result("NOT_APPLICABLE",
                      "register-map golden present in the prompt but the RTL "
                      "exposes no resolvable memory-mapped/APB interface "
                      "(need address + write-data + read-data ports) — "
                      "cannot drive the directed sequence safely",
                      gold_json)

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return Result("NOT_APPLICABLE",
                      "iverilog/vvp not on PATH — cannot run the register-map "
                      "indirection smoke TB (a golden was extractable)",
                      gold_json)

    def _build_and_run(force_active_low: Optional[bool]
                       ) -> Tuple[Optional[bool], str, str]:
        """Compile+run the directed bus TB for one reset polarity.
        Returns (passed, compile_error_log, sim_log):
          passed is True  -> readback matched the golden;
                    False -> readback mismatched (a sim ran);
                    None  -> the TB did not compile (compile_error_log set)."""
        tb_text = build_indirection_testbench(
            top, gold, bus, in_ports, out_ports,
            force_active_low=force_active_low)
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            tb_path = tdp / "tb_spec_example_smoke.v"
            rtl_copy = tdp / "dut.v"
            out_vvp = tdp / "smoke.vvp"
            tb_path.write_text(tb_text)
            rtl_copy.write_text(rtl_text)
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
            comp = subprocess.run(
                ["iverilog", "-g2012", "-o", str(out_vvp),
                 str(tb_path), str(rtl_copy)],
                capture_output=True, text=True)
            if comp.returncode != 0:
                return None, (comp.stdout + comp.stderr).strip(), ""
            sim = subprocess.run(["vvp", str(out_vvp)],
                                 capture_output=True, text=True)
            log = (sim.stdout + sim.stderr).strip()
        return ("SPEC_EXAMPLE_SMOKE_RESULT=PASS" in log), "", log

    # For an AMBIGUOUS reset name (bare `reset`/`rst`, no polarity marker) we do
    # NOT guess-and-BLOCK (#738 r2): a wrong guess holds the DUT in reset forever,
    # the result reads 0, and a FUNCTIONALLY-CORRECT DUT gets false-BLOCKed. Try
    # BOTH reset polarities and PASS if EITHER makes the golden readback match;
    # only BLOCK if BOTH polarities mismatch (a genuine functional bug). A clearly
    # active-low (trailing 'n') or clearly active-high name stays single-polarity.
    if bus.rst and bus.rst_polarity == "ambiguous":
        polarities = [True, False]   # active-low release, then active-high
    else:
        polarities = [bus.rst_active_low]

    last_compile_err = ""
    last_sim_log = ""
    for force_low in polarities:
        passed, comp_err, log = _build_and_run(force_low)
        if passed is None:
            last_compile_err = comp_err
            continue
        last_sim_log = log
        if passed:
            note = ""
            if bus.rst and bus.rst_polarity == "ambiguous":
                pol = "active-low" if force_low else "active-high"
                note = (f" (reset name '{bus.rst}' is polarity-ambiguous; "
                        f"matched with {pol} release)")
            return Result("PASS",
                          "the register-map golden (write operands -> start -> "
                          "read result) matches the RTL readback" + note,
                          gold_json, sim_log=log)

    # No polarity compiled at all -> a real interface/compile mismatch.
    if not last_sim_log:
        verdict = "BLOCK" if not warn else "PASS"
        return Result(verdict,
                      "register-map indirection smoke TB failed to compile "
                      "against the RTL (stated bus interface does not "
                      "connect) — see sim_log",
                      gold_json, sim_log=last_compile_err)

    # A sim ran for every attempted polarity and all mismatched -> genuine bug.
    verdict = "BLOCK" if not warn else "PASS"
    extra = ""
    if bus.rst and bus.rst_polarity == "ambiguous":
        extra = (" (tried BOTH reset polarities for the polarity-ambiguous "
                 f"reset name '{bus.rst}'; neither matched — a real functional "
                 "bug, not a reset-polarity guess)")
    return Result(verdict,
                  "the register-map golden readback mismatched the RTL result "
                  "register (clobbered-CSR / lost-write / wrong compute)" + extra
                  + " — see sim_log", gold_json, sim_log=last_sim_log)


def _run(prompt: Path, rtl: Path, top: Optional[str],
         warn: bool) -> Result:
    prompt_text = prompt.read_text(errors="replace")
    rtl_text = rtl.read_text(errors="replace")

    mod_name, ports = _SRC.parse_rtl_ports(rtl_text, top)
    chosen_top = top or mod_name
    in_ports = {p.name: max(1, p.width) for p in ports if p.direction == "input"}
    out_ports = {p.name: max(1, p.width) for p in ports if p.direction == "output"}

    rows = extract_example_rows(prompt_text, in_ports, out_ports)
    rows_json = [asdict(r) for r in rows]

    if not rows:
        # No direct top-level `input=value -> output=value` row. Before declaring
        # NOT-APPLICABLE, try the register-map / address-indirection model (#738):
        # an access-protocol golden that writes operands to offsets, pulses a
        # start bit, and reads a result register back. This is EXACTLY the
        # multi-stage / CSR / RAM class where functional bugs hide.
        gold = extract_indirection_golden(prompt_text)
        if gold is not None:
            return _run_indirection(prompt_text, rtl_text, chosen_top, gold,
                                    in_ports, out_ports, warn)
        return Result("NOT_APPLICABLE",
                      "no extractable golden example rows in the prompt "
                      "(no input=val ... -> output=val row whose names "
                      "resolve to RTL ports, and no offset-keyed register-map "
                      "golden with a start register + result readback) — "
                      "nothing to execute",
                      rows_json)

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return Result("NOT_APPLICABLE",
                      "iverilog/vvp not on PATH — cannot run the example "
                      f"smoke TB ({len(rows)} row(s) were extractable)",
                      rows_json)

    tb_text = build_testbench(chosen_top, rows, in_ports, out_ports)

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        tb_path = tdp / "tb_spec_example_smoke.v"
        rtl_copy = tdp / ("dut" + (rtl.suffix or ".v"))
        out_vvp = tdp / "smoke.vvp"
        tb_path.write_text(tb_text)
        rtl_copy.write_text(rtl_text)
        # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
        comp = subprocess.run(
            ["iverilog", "-g2012", "-o", str(out_vvp),
             str(tb_path), str(rtl_copy)],
            capture_output=True, text=True)
        if comp.returncode != 0:
            # A genuine compile failure of the example TB+RTL is a real
            # mismatch between the stated interface and the RTL -> BLOCK
            # (unless --warn). The compile log is the evidence.
            log = (comp.stdout + comp.stderr).strip()
            verdict = "BLOCK" if not warn else "PASS"
            return Result(verdict,
                          "example smoke TB failed to compile against the RTL "
                          "(stated example ports do not connect) — see sim_log",
                          rows_json, sim_log=log)
        sim = subprocess.run(["vvp", str(out_vvp)],
                             capture_output=True, text=True)
        log = (sim.stdout + sim.stderr).strip()

    if "SPEC_EXAMPLE_SMOKE_RESULT=PASS" in log:
        return Result("PASS",
                      f"all {len(rows)} prompt golden example row(s) match "
                      "the RTL output", rows_json, sim_log=log)
    # any FAIL marker (or missing PASS marker) -> mismatch
    verdict = "BLOCK" if not warn else "PASS"
    return Result(verdict,
                  "at least one prompt golden example row mismatched the RTL "
                  "output (functionally-wrong RTL) — see sim_log",
                  rows_json, sim_log=log)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Execute the prompt's own golden example rows as a "
                    "directed smoke TB (blind, scorer-independent).")
    ap.add_argument("--prompt", required=True,
                    help="USER prompt text file (the ONLY source of golden rows)")
    ap.add_argument("--rtl", required=True, help="authored RTL under test")
    ap.add_argument("--top", default=None,
                    help="top module name (default: first module in the RTL)")
    ap.add_argument("--warn", action="store_true",
                    help="WARN-only: report a mismatch but exit 0")
    ap.add_argument("--json", default=None, help="write the result JSON here")
    args = ap.parse_args(argv)

    prompt = Path(args.prompt)
    rtl = Path(args.rtl)
    if not prompt.is_file():
        print(f"[spec_example_smoke_tb] ERROR: prompt not found: {prompt}",
              file=sys.stderr)
        return 2
    if not rtl.is_file():
        print(f"[spec_example_smoke_tb] ERROR: rtl not found: {rtl}",
              file=sys.stderr)
        return 2

    res = _run(prompt, rtl, args.top, args.warn)

    if args.json:
        try:
            Path(args.json).write_text(json.dumps(asdict(res), indent=2))
        except OSError as e:
            print(f"[spec_example_smoke_tb] WARN: could not write json: {e}",
                  file=sys.stderr)

    tag = {"PASS": "PASS", "BLOCK": "BLOCK",
           "NOT_APPLICABLE": "NOT-APPLICABLE"}[res.verdict]
    print(f"[spec_example_smoke_tb] {tag}: {res.reason}")
    if res.rows:
        print(f"[spec_example_smoke_tb] extracted {len(res.rows)} golden "
              f"example row(s):")
        for r in res.rows:
            if r.get("kind") == "indirection":
                ws = ", ".join(f"mem[0x{w['offset']:x}]={w['value']}"
                               for w in r["operand_writes"])
                print(f"    [indirection] {ws} -> start(0x"
                      f"{r['start_offset']:x} bit{r['start_bit']}) -> "
                      f"result(0x{r['result_offset']:x})={r['expected']}")
            else:
                ins = ", ".join(f"{k}={v}"
                                for k, v in sorted(r["inputs"].items()))
                print(f"    [{r['source']}] {ins} -> "
                      f"{r['output']}={r['expected']}")
    if res.sim_log:
        # echo only the result lines, not the whole dump
        for ln in res.sim_log.splitlines():
            if "SPEC_EXAMPLE" in ln or "error" in ln.lower():
                print(f"    | {ln}")

    return 1 if res.verdict == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
