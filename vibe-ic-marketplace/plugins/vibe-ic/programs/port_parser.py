#!/usr/bin/env python3
"""port_parser.py — the SHARED interface-port reader for the deterministic solvers.

A spec/prompt states the module interface in one of two forms, and the structural
artifact (truth table / FSM table / K-map) is identical across them — only the port
syntax differs (the VerilogEval-v2 twin uses bullets, the VerilogEval-human twin a
Verilog module header). Solvers that parsed only bullets silently SKIPped every
module-header prompt. This one parser reads BOTH, so a solver fires on either twin.

  (a) bullet:  ` - input  clk`  /  ` - output q (4 bits)`  /  ` - input y (3 bits)`
  (b) header:  `module TopModule ( input clk, input [7:0] d, output reg q );`
               (parsed ONLY inside the module-header parens, so prose like
               "the input signal a" never becomes a phantom port).

Returns (ins, outs) as lists of (name, width:int). chip-AGNOSTIC, pure regex.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple

# Verilog direction / net-type keywords that are NEVER a port name — when a bullet
# quotes a full declaration (`- \`input [31:0] num_in\``) the name is the
# identifier AFTER these, not the leading keyword. Kept DELIBERATELY MINIMAL to the
# unambiguous HDL keywords: English words / generic type nouns ("a", "the", "bit",
# "signal", …) are EXCLUDED because a port may legitimately be named `a` / `b` /
# `bit` (adders, GF multipliers, …) and must never be dropped as a stopword.
_DIR_TYPE_KW = frozenset({
    "input", "output", "inout", "wire", "reg", "logic", "signed", "unsigned",
})


def _bullet_port_name(line: str) -> Optional[str]:
    """The port NAME from a single CVDP Inputs/Outputs bullet (the text after the
    -/* marker). Handles every observed CVDP form:

      clk                                  -> clk
      `data_in([DATA_WIDTH-1:0])`: ...     -> data_in   (first ident, paren width)
      `input [31:0] num_in`: ...           -> num_in    (skip the `input` keyword)
      **input_A [BIT_WIDTH-1:0]**: ...      -> input_A
      **i_A** : 1-bit input signal         -> i_A       (bold, no backtick)
      **generate** signal (`o_generate`)   -> o_generate (backticked HDL name)

    Only the DECLARATION part (before the first top-level ':') is considered, so a
    trailing prose reference (`... of size DATA_WIDTH`) never wins over the real
    port. A ':' INSIDE a packed width `[hi:lo]` is NOT the description separator."""
    depth = 0
    cut = len(line)
    for i, ch in enumerate(line):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            cut = i
            break
    decl = line[:cut]
    # (1) a CLEAN single-identifier backtick — `X` or (`X`) — that is not a
    #     direction/type keyword. This is the canonical HDL name after a bold
    #     descriptor (the GP `(\`o_generate\`)` form). A backtick span that holds
    #     a FULL declaration (`\`input [31:0] num_in\``) is NOT clean (it has
    #     spaces/brackets) and is skipped here, falling to (2).
    for m in re.finditer(r"`\s*([A-Za-z_]\w*)\s*`", decl):
        if m.group(1).lower() not in _DIR_TYPE_KW:
            return m.group(1)
    # (2) strip markdown (** and `) and skip leading direction/type keywords; the
    #     port name is the first remaining identifier (num_in / data_in / input_A).
    flat = decl.replace("**", " ").replace("`", " ")
    for tok in re.findall(r"[A-Za-z_]\w*", flat):
        if tok.lower() not in _DIR_TYPE_KW:
            return tok
    return None


def _bullet_ports(text: str) -> Tuple[List[Tuple[str, Optional[int]]], List[Tuple[str, Optional[int]]]]:
    """Parse bullet-style port lists (VerilogEval-v2 / CVDP prose).

    Supports three conventions:
      - classic bullet:      `- input clk` / `- output q (4 bits)`
      - Verilog bullet:      `- output reg [3:0] name`
      - CVDP markdown:       `- `clk`: ...` under `### Inputs:`, and
                             `- `q` (4-bit) — ...` under `### Outputs:`.
    The CVDP form infers direction from the containing section header and width
    from the parenthesized `(N-bit)` token."""
    ins, outs = [], []
    # classic / Verilog bullet, width EITHER before the name (Verilog `[hi:lo]`
    # or a leading `(N bits)`) OR — the classic VerilogEval-v2 form — AFTER the
    # name (`- output q (4 bits)`). The v1.2.51 rewrite added the before-name
    # forms but DROPPED the after-name `(N bits)`, silently defaulting every
    # `- input predict_pc (7 bits)` to width 1 and making the width-sensitive
    # solvers (gshare/vector-ops/conway/moore/…) return None. Both widths are
    # parsed; the first that matched wins. The trailing group uses `[ \t]*` so it
    # cannot cross a newline and steal the next port's `(N bits)`.
    for m in re.finditer(
        r"^\s*-\s*(input|output)\b(?:\s+(?:wire|reg|logic))?"
        r"\s*(?:(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])|(?:\(\s*(\d+)\s*bits?\s*\)))?"
        r"\s*(\w+)"
        r"(?:[ \t]*\(\s*(\d+)\s*bits?\s*\))?", text, re.M):
        d, hi, lo, w_pre, name, w_post = m.groups()
        if hi is not None and lo is not None:
            w = abs(int(hi) - int(lo)) + 1
        elif w_pre is not None:
            w = int(w_pre)
        elif w_post is not None:
            w = int(w_post)
        else:
            w = 1
        (ins if d == "input" else outs).append((name, w))
    if ins or outs:
        return ins, outs
    # CVDP section-bounded form: direction from a "### Inputs/Outputs:" heading.
    # Tolerate any markdown heading level 2-6 (`##`..`######`), an optional section
    # NUMBER (`### 1. Inputs`), and an optional trailing colon — CVDP prompts use
    # `#### Inputs:`, `### 1. Inputs`, `## Outputs`, etc., which a fixed `###?...:`
    # missed. The heading must END at the port word (`\s*$` after an optional colon)
    # so a prose heading like "### Inputs and clocking notes" is not swallowed.
    section_re = re.compile(
        r"^\s*#{2,6}\s*(?:\d+\.\s*)?(Inputs?|Outputs?)\s*:?\s*$.*?\n(?=^\s*#{2,6}|\Z)",
        re.M | re.S)
    for sec in section_re.finditer(text):
        section_kind = "input" if sec.group(1).lower().startswith("input") else "output"
        for bm in re.finditer(r"^\s*[-*]\s+(.+)$", sec.group(0), re.M):
            line = bm.group(1)
            name = _bullet_port_name(line)
            if not name:
                continue
            # width: an explicit `(N-bit)` / `[hi:lo]` / a same-line "N-bit".
            wm = re.search(r"\(\s*(\d+)\s*-?\s*bits?\s*\)", line, re.I) \
                or re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", line) \
                or re.search(r"\b(\d+)\s*-?\s*bits?\b", line, re.I)
            if wm and wm.lastindex == 2:
                w = abs(int(wm.group(1)) - int(wm.group(2))) + 1
            elif wm:
                w = int(wm.group(1))
            else:
                w = 1
            (ins if section_kind == "input" else outs).append((name, w))
    return ins, outs


def _header_ports(text: str) -> Tuple[List, List]:
    m = re.search(r"module\s+\w+\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;", text, re.S)
    if not m:
        return [], []
    body = m.group(1)
    ins, outs = [], []
    for pm in re.finditer(
        r"\b(input|output)\b\s+(?:wire|reg|logic)?\s*"
        r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?(\w+)", body):
        d, hi, lo, name = pm.groups()
        w = abs(int(hi) - int(lo)) + 1 if hi is not None and lo is not None else 1
        (ins if d == "input" else outs).append((name, w))
    return ins, outs


def _prose_declared_width(text: str, name: str) -> Optional[int]:
    """The width of an EXPLICIT HDL register/net declaration of the signal `name`
    stated in the design PROSE (not the port list) — e.g. a description body that
    says "The register is defined as reg [7:0] q". Returns the declared width, or
    None when no such explicit numeric declaration for THIS name is present.

    Matches only `reg|wire|logic [hi:lo] <name>` with NUMERIC bounds and the name
    immediately after the range (a declaration, so an index usage like `q[7]` — name
    BEFORE the bracket — never matches, and a parametric `[WIDTH-1:0]` range is left
    to the port list / solver). The trailing `\\b` keeps `q` from matching `q_r` /
    `queue`. chip-AGNOSTIC: keys on generic Verilog grammar + the port's own name."""
    best: Optional[int] = None
    for m in re.finditer(
        r"\b(?:reg|wire|logic)\s+(?:signed\s+|unsigned\s+)?"
        r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*" + re.escape(name) + r"\b", text):
        w = abs(int(m.group(1)) - int(m.group(2))) + 1
        if best is None or w > best:
            best = w
    return best


def _recover_prose_widths(text: str,
                          ports: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
    """GENERAL width recovery: when a port's width was left UNSPECIFIED by the port
    list (defaulted to 1), but the design prose EXPLICITLY declares that same signal
    as a multi-bit register/net (`reg [7:0] q`), adopt the declared width. An
    explicit port-list width (>1) is authoritative and never overridden; a port the
    prose does not declare is left untouched. Benchmark-agnostic — fires for any
    Phase-1 doc whose body pins a width the interface line omitted."""
    out: List[Tuple[str, int]] = []
    for name, w in ports:
        if w == 1:
            pw = _prose_declared_width(text, name)
            if pw and pw > 1:
                w = pw
        out.append((name, w))
    return out


def parse_ports(text: str) -> Tuple[List, List]:
    """(ins, outs) as [(name, width)]. Bullet form wins; else the Verilog header.
    A port whose width the interface line left unspecified is then recovered from an
    explicit `reg/wire/logic [hi:lo] <name>` declaration in the prose body, if any."""
    ins, outs = _bullet_ports(text)
    if not (ins or outs):
        ins, outs = _header_ports(text)
    ins = _recover_prose_widths(text, ins)
    outs = _recover_prose_widths(text, outs)
    return ins, outs
