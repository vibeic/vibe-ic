#!/usr/bin/env python3
"""cvdp_atomic_bridge.py — a CVDP-prose -> atomic-spec BRIDGE that lets the existing
deterministic registry solvers (spec_artifact_registry) program-SOLVE the
atomic-shaped CVDP "code generation" problems.

WHY (owner directive 2026-06-23): a CVDP "code generation" problem like the 32-bit
Brent-Kung adder is FUNCTIONALLY just `sum = a + b + carry_in` — the cocotb scorer
checks the FUNCTION, not the prefix-tree architecture. So the registry's
deterministic solvers (arithmetic / comparator / counter / mux / encoder /
decoder / shift / parity / ...) can functionally solve a fraction of the
atomic-noun CVDP problems IF the INTERFACE + the OPERATION can be extracted from
the CVDP prose. But the registry's `generate()` fires on 0/302 CVDP prompts,
because CVDP states the interface NOT as bullet ports but as a markdown test-case
table / prose / harness signal list. This bridge supplies exactly the missing
piece: it reads the interface from the BEST available PROMPT+CONTEXT source and
re-emits it as the bullet/prose port block the registry already parses, PREPENDED
to the ORIGINAL prompt prose. The registry then recognizes the operation from the
real prompt and emits the RTL (named per the module name STATED IN THE PROMPT).

DESIGN — the bridge NEVER paraphrases the operation. It supplies a parseable port
block; the operation is recognized by the registry FROM THE ORIGINAL PROMPT. That
keeps every emitted fact grounded in the dataset prose (no fabrication), and the
registry's own §4.05 conservatism is the SKIP enforcement: a composite SoC / a
protocol controller / anything whose function no canonical can emit returns None.

§4.05 NO-LEAK / NO-CHEAT — PROMPT+CONTEXT ONLY (binding, CVDP official rule
arXiv:2506.14074 §2 + README_NON_AGENTIC): the model sees ONLY `input.prompt` +
`input.context`. The ENTIRE hidden harness (the cocotb `dut.<sig>` test, the
`.env` TOPLEVEL / VERILOG_SOURCES, `harness_library.py`) AND `output.*` (the
golden/reference RTL) are OFF-LIMITS oracle and are NEVER read to name the module
or to derive the emitted interface.
  * SKIP (return None) when the design is not a single recognizable atomic function
    OR the module name / interface cannot be extracted from prompt+context. Never
    guess a width, never guess a port direction, never invent a port, and never
    peek at the harness for a name/port the prompt is silent on (that is an honest
    floor, not a recoverable case).
  * Protocol / bus / memory / composite cues (AXI/APB/AHB/Wishbone/FIFO/cache/...)
    short-circuit to SKIP up front — they are not atomic functions.

Module NAME source (prompt+context ONLY — see `toplevel_name`): an input.context
RTL file that DECLARES the module, or a prompt `module <name>` / `<name> module` /
"named/called `<name>`" designation.

Interface-extraction priority (prompt+context ONLY, best source first):
  (a) an input.context RTL skeleton's `module <top> ( ... );` HEADER (HEADER ONLY —
      never the body; input.context is the file the prompt SHOWS the author);
  (b) a markdown test-case table header (columns a/b/carry_in/Sum/carry_out ->
      ports; an `Expected/Actual`-prefixed column is an OUTPUT), which also fixes
      widths from the hex-cell column width;
  (c) the prose "Input/Output ports" description.
Width resolution cross-checks: prose `[hi:lo]`, a "N-bit" description token, and a
test-case-table hex-column width. (The removed harness-derived cocotb source and
`output.context` golden header are the oracle and no longer participate.)

The harness-reading helpers below (`_harness_files` / `_cocotb_*` / `_env_*`) are
retained ONLY for the §3.9 EXTRACTION_GAP DIAGNOSTIC consumed by
`cvdp_complete_extract` (post-hoc: compare our prompt-extraction against what the
hidden TB drives, to find OUR extractor gaps) — they are NEVER called on the
solve/emit path.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC (no design-name keys), pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# NOTE: `spec_artifact_registry` is imported LAZILY inside solve()/family_of(),
# NOT at module scope. The registry's record-level solvers import THIS module for
# the record-adapter helpers (toplevel_name / extract_interface / _COMPOSITE_RE …),
# so a module-scope `import spec_artifact_registry` here would be a circular import
# (bridge → registry → solver → bridge). The lazy import runs after both modules
# are fully defined.
import verilog_width_resolve as _W  # noqa: E402  symbolic/param-expression width reader
import prose_interface_table_read as _tbl  # noqa: E402  markdown signal/direction table reader

# The record-level operation solvers (gf / bcd / crc / hamming / encoder / …) and the
# dispatch over them MOVED to `spec_artifact_registry.generate_from_record()` — the
# SINGLE deterministic-solver dispatch. This module is now the thin record→ports
# ADAPTER + driver: it exposes the record-adapter helpers the solvers reuse
# (`toplevel_name` / `extract_interface[_ex]` / `_COMPOSITE_RE` / `_build_port_block`
# …) and a `solve()` that simply calls `generate_from_record()`. The solvers
# `import cvdp_atomic_bridge` for those helpers, which is why the registry is imported
# LAZILY here (see the module-top note) — registry → solver → bridge must stay acyclic.

Port = Tuple[str, int]  # (name, width)

# Verilog keywords / type words that must never be mistaken for a port NAME when a
# loose prose/header parse grabs the wrong token (e.g. `output signed [7:0] y` ->
# the prose reader may yield `signed`). A port whose "name" is one of these is
# dropped, which forces a §4.05 SKIP rather than a phantom port.
_NOT_A_PORT_NAME = {
    "signed", "unsigned", "wire", "reg", "logic", "input", "output", "inout",
    "for", "if", "begin", "end", "module", "endmodule", "parameter", "localparam",
    "integer", "genvar", "assign", "always", "posedge", "negedge",
}


def _clean_ports(ports: List[Port]) -> List[Port]:
    """Drop keyword/type tokens and de-duplicate by name (keep first width)."""
    seen = set()
    out: List[Port] = []
    for n, w in ports:
        if n.lower() in _NOT_A_PORT_NAME or n in seen:
            continue
        seen.add(n)
        out.append((n, w))
    return out


# --------------------------------------------------------------------------- #
# Composite / non-atomic SKIP cues — a protocol/bus/memory controller is never
# a single registry-emittable atomic function. Keyed on OPERATION/INTERFACE
# vocabulary, never on a design name.
# --------------------------------------------------------------------------- #
_COMPOSITE_RE = re.compile(
    r"""(?xi)
      \baxi\b | \baxi-?lite\b | \baxi-?stream\b | \baxis\b |
      \bapb\b | \bahb\b | \bwishbone\b | \bavalon\b | \btilelink\b |
      \buart\b | \bspi\b | \bi2c\b | \bi2s\b | \bjtag\b | \bpcie\b | \busb\b |
      \bfifo\b | \bfilo\b | \blifo\b | \bmshr\b | \bcache\b | \bsram\b | \bdram\b |
      \bmicrocode\b | \bsequencer\b | \bprocessor\b | \bcpu\b | \bpipeline\b |
      \bbranch\s+predict | \bperceptron\b | \bhebbian\b | \bvga\b | \bsprite\b |
      \breed[-\s]?solomon\b | \bhamming\b | \bmatrix\b | \barbiter\b
    """,
)

# Special-algebra / non-plain-integer SEMANTICS the registry's plain +/-/* ops
# would MIS-EMIT. A Galois-field multiply is NOT `result = A * B`; a saturating /
# modular / fixed-point-with-rounding datapath is NOT the registry's plain op.
# §4.05: "a wrong <op> is far worse than an honest skip" — SKIP these so the
# bridge never lets a functionally-wrong emit through (NO-CHEAT). Keyed on the
# stated SEMANTICS, never on a design name.
_SPECIAL_ALGEBRA_RE = re.compile(
    r"""(?xi)
      \bgalois\b | \bgf\s*\(\s*2 | \bgf\(2 | \birreducible\s+polynomial\b |
      \bpolynomial\s+reduction\b | \bfinite\s+field\b | \bmodular\s+(?:multipl|arithmetic)\b |
      \bmontgomery\b |
      \bfixed[-\s]?point\b | \bfloating[-\s]?point\b | \bsaturat | \bclamp\b |
      \bcarry[-\s]?less\b
    """,
)












# english words / verilog keywords that can follow "module" in prose but are not
# a real module name (the code-delimiter requirement already filters most).
_NAME_STOP = frozenset({
    "the", "a", "an", "is", "named", "called", "name", "this", "that", "which",
    "top", "design", "block", "performs", "implements", "should", "must", "with",
    "module", "instantiates", "contains", "has", "and", "or",
})


def toplevel_name(record: dict) -> Optional[str]:
    """The target module name — derived from `input.prompt` + `input.context` ONLY.

    The harness `.env` TOPLEVEL and the cocotb testbench are the hidden test
    HARNESS = OFF-LIMITS oracle (CVDP official rule, arXiv:2506.14074 §2 +
    README_NON_AGENTIC: the model sees only `input.prompt` + `input.context`).
    When the module name is stated in NEITHER the prompt nor the provided
    context, return None — the bridge then SKIPs (an honest floor, never a
    harness peek)."""
    if not isinstance(record, dict):
        return None
    inp = record.get("input") or {}
    prompt = record.get("prompt") or inp.get("prompt") or ""
    ctx = inp.get("context") or {}

    # Collect the modules DECLARED in input.context, plus the one whose name
    # matches its file leaf (`rtl/<name>.sv`) — the conventional MODIFY target.
    leaf_match: Optional[str] = None
    declared: List[str] = []
    if isinstance(ctx, dict):
        for path, text in ctx.items():
            if not isinstance(text, str) or not text.strip():
                continue
            leaf = re.sub(r"\.\w+$", "", str(path).rsplit("/", 1)[-1])
            for mm in re.finditer(r"\bmodule\s+([A-Za-z_]\w*)", text):
                nm = mm.group(1)
                declared.append(nm)
                if nm == leaf and leaf_match is None:
                    leaf_match = nm
    declared_set = set(declared)

    # (1) STRONG prompt designation — an imperative "module (must be) named/called
    #     `X`", a bare "named/called `X`", or a `module X (` code header. This is
    #     the DELIVERABLE the prompt asks you to build. It OUTRANKS a context
    #     leaf-match when `X` is a NEW module the context does NOT already declare:
    #     a "design a module named `X` that leverages the provided `Y`/`Z`
    #     sub-modules" prompt ships Y/Z in input.context as DEPENDENCIES, not as the
    #     target, so the context leaf (Y) must not shadow the stated deliverable X.
    strong_named: Optional[str] = None
    for pat in (
        r"\bmodule\s+(?:must\s+be\s+)?(?:named|called)\s+[`*\"]([A-Za-z_]\w*)[`*\"]",
        # "module name `X`" / "Module Name: `X`" / "**Module Name:** `X`" — a labelled
        # designation (the name is backtick/quote-delimited right after "module name").
        r"\bmodule\s+name\b[\s:*]*[`\"]([A-Za-z_]\w*)[`\"]",
        r"\b(?:named|called)\s+[`*\"]([A-Za-z_]\w*)[`*\"]",
        r"\bmodule\s+([A-Za-z_]\w*)\s*(?:#\s*\(|\()",
    ):
        m = re.search(pat, prompt, re.I)  # prose often capitalises "Module"
        if m and m.group(1).lower() not in _NAME_STOP:
            strong_named = m.group(1)
            break
    if strong_named and strong_named not in declared_set:
        return strong_named

    # (2) input.context RTL file (a MODIFY prompt shows the module to edit).
    #     Prefer the declared module whose name matches its file leaf
    #     (`rtl/<name>.sv`); else the single module declared across context.
    if leaf_match:
        return leaf_match
    if len(declared_set) == 1:
        return declared[0]

    # (3) prompt prose: any remaining explicit `module <name>` designation. A code
    #     delimiter (backtick / ** / quote) or a `(` header is REQUIRED so a
    #     bare English "module performs ..." is never captured. The weak
    #     descriptive "`X` module" form is tried LAST so a narrative reference to a
    #     helper sub-module never wins over a genuine context module.
    for pat in (
        r"\bmodule\s+(?:named\s+|called\s+)?[`*\"]([A-Za-z_]\w*)[`*\"]",  # module `X`
        r"\bmodule\s+([A-Za-z_]\w*)\s*(?:#\s*\(|\()",                    # module X (
        r"\b(?:named|called)\s+[`*\"]([A-Za-z_]\w*)[`*\"]",              # named `X`
        r"\(([A-Za-z_]\w*)\)\s+module\b",                               # (ABBR) module
        r"[`*\"]([A-Za-z_]\w*)[`*\"]\s+module\b",                        # `X` module
    ):
        m = re.search(pat, prompt, re.I)  # prose often capitalises "Module"
        if m and m.group(1).lower() not in _NAME_STOP:
            return m.group(1)
    return None






# A cocotb PARAMETER is read with `NAME = int(dut.NAME.value)` to CONFIGURE the
# run (then used as a python int — width/loop bound), not asserted as a DUT output.
# Convention across this dataset: parameters are ALL-CAPS snake (DATA_WIDTH, MSHR_SIZE,
# CLK_DIV, SEQUENCE_LENGTH, ...). We drop them so they never become phantom ports.
_PARAM_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$|^[A-Z]{3,}$")

# Standard AMBA/APB/AXI port names are also ALL-CAPS, but they are genuine IO
# ports (often read with `int(dut.PRDATA.value)` into a local variable). They
# must NOT be treated as cocotb parameters. This is a protocol-vocabulary list,
# not a design-specific keyword; it mirrors the generic control-word regexes
# used elsewhere in the bridge.
_BUS_PORT_NAMES = frozenset({
    "PCLK", "PRESETn", "PRESETN", "PADDR", "PWDATA", "PRDATA",
    "PWRITE", "PENABLE", "PREADY", "PSLVERR",
    "HCLK", "HRESETn", "HRESETN", "HADDR", "HWDATA", "HRDATA",
    "HWRITE", "HREADY", "HRESP", "HSIZE", "HBURST", "HTRANS", "HMASTLOCK",
    "ACLK", "ARESETn", "ARESETN", "AWADDR", "AWVALID", "AWREADY",
    "AWID", "AWLEN", "AWSIZE", "AWBURST", "AWLOCK", "AWCACHE", "AWPROT",
    "WDATA", "WVALID", "WREADY", "WSTRB", "WLAST",
    "ARADDR", "ARVALID", "ARREADY",
    "ARID", "ARLEN", "ARSIZE", "ARBURST", "ARLOCK", "ARCACHE", "ARPROT",
    "RDATA", "RVALID", "RREADY", "RRESP", "RID", "RLAST",
    "BVALID", "BREADY", "BRESP", "BID",
})






# --------------------------------------------------------------------------- #
# (a) output['context'] skeleton MODULE HEADER (header-only; never the body)
# --------------------------------------------------------------------------- #
_HEADER_RE = re.compile(r"module\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;", re.S)


def _skeleton_ports(record: dict, top: str,
                    include_input_context: bool = True
                    ) -> Optional[Tuple[List[Port], List[Port]]]:
    """Parse ports from the skeleton RTL's module HEADER only (never any body).
    The skeleton RTL comes from `input.context` (the RTL file the prompt shows
    the author — present for *modification* prompts where the author edits it in
    place). A HEADER-ONLY read, never any body code.

    The reference RTL in `output.context` is the GOLDEN solution = OFF-LIMITS
    oracle and is NEVER read (the CVDP model sees only input.prompt +
    input.context). `include_input_context` is retained for signature
    compatibility but no longer toggles an output.context source (there is none).

    Multi-variant records may declare the target module in only ONE of several
    context files, so we try every file and pick the first header that actually
    declares `module <top> ...` with both input and output ports."""
    sources: Dict[str, str] = {}
    if include_input_context:
        etc = (record.get("input") or {}).get("context") or {}
        try:
            for k, v in etc.items():
                sources.setdefault(k, v)
        except TypeError:
            pass
    best: Optional[Tuple[List[Port], List[Port]]] = None
    for _path, text in sources.items():
        if not isinstance(text, str) or not text.strip():
            continue
        m = _HEADER_RE.search(text)
        if not m or m.group(1) != top:
            continue
        body = _strip_verilog_comments(m.group(2))
        ins: List[Port] = []
        outs: List[Port] = []
        for pm in re.finditer(
            r"\b(input|output)\b\s+(?:wire|reg|logic)?\s*(?:signed\s*)?"
            r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?(\w+)", body):
            d, hi, lo, name = pm.groups()
            w = abs(int(hi) - int(lo)) + 1 if hi is not None and lo is not None else 1
            (ins if d == "input" else outs).append((name, w))
        if ins and outs:
            return ins, outs
        # keep a partial result in case no file has both directions
        if (ins or outs) and best is None:
            best = (ins, outs)
    return best


def _strip_verilog_comments(s: str) -> str:
    """Remove `// ...` and `/* ... */` Verilog comments before parsing a header."""
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"//[^\n]*", " ", s)
    return s


# --------------------------------------------------------------------------- #
# Width resolution from the PROMPT PROSE (used for cocotb-derived port names)
# --------------------------------------------------------------------------- #
_SEQ_PORTS = {"clk", "clock", "rst", "reset", "rstn", "rst_n", "resetn",
              "reset_n", "areset", "aresetn", "clk_en", "clken", "srst"}


# spelled-out small bit-counts: "a one-bit signal", "single-bit", "two-bit value".
# A STATED width (§4.05-safe) — common in design-doc prose where the width is
# narrated rather than bracketed. Only the lengths that actually occur as words.
_WORDNUM = {"one": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "twelve": 12, "sixteen": 16, "twenty-four": 24, "twenty four": 24,
            "thirty-two": 32, "thirty two": 32, "sixty-four": 64, "sixty four": 64}
_BITNUM_ALT = r"(\d+|" + "|".join(re.escape(w) for w in _WORDNUM) + r")"


def _bitnum(tok: str) -> int:
    """A digit string or a spelled-out number token -> int."""
    tok = tok.strip().lower()
    return int(tok) if tok.isdigit() else _WORDNUM[tok]


def _prose_width(prompt: str, name: str) -> Optional[int]:
    """Width of a single port from the prompt prose.
    Order: explicit `name [hi:lo]`, then a same-line `N-bit name` / `name ... N-bit`
    (N digits OR spelled out, e.g. "a one-bit signal"), then a per-row width column
    in a markdown port table. None if not stated."""
    # explicit bus range tied to the name: `name [hi:lo]`
    m = re.search(rf"\b{re.escape(name)}\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", prompt)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    # a markdown port-table row:
    #   | name | <width-expr> | ... |
    #   | [N*WIDTH-1:0] name | <width-expr> | ... |    ← NEW: bracket prefix
    bracket_prefix = rf"(?:\[.*?\]\s+)"
    row_re = rf"^\s*\|\s*(?:{bracket_prefix})?`?{re.escape(name)}`?\s*\|\s*([^|]+)\|"
    for rm in re.finditer(row_re, prompt, re.M):
        cell = rm.group(1)
        # explicit numeric bus in the width cell itself
        wm = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", cell)
        if wm:
            return abs(int(wm.group(1)) - int(wm.group(2))) + 1
        # numeric "32 bits" / "1 bit"
        wm = re.search(r"\b(\d+)\s*-?\s*bits?\b", cell, re.I)
        if wm:
            return int(wm.group(1))
        if re.search(r"\b1\b", cell) and re.search(r"\bbit\b", cell, re.I):
            return 1
        # NEW: if the cell contains ONLY a symbolic expression (no digits
        # except inside a parameter name like DATA_WIDTH), return None so
        # _W.symbolic_width() can resolve `[N*WIDTH-1:0] name` correctly.
        # Examples: "N * WIDTH bits", "N*WIDTH bits".
        if re.search(r"[A-Z_]+", cell) and not re.search(r"\b\d+\b", cell):
            return None
    # a same-line "N-bit <name>" or "<name> ... N-bit" (digit N). UNCHANGED
    for pat in (rf"\b(\d+)\s*-?\s*bits?\b[^\n]*?\b{re.escape(name)}\b",
                rf"\b{re.escape(name)}\b[^\n]*?\b(\d+)\s*-?\s*bits?\b"):
        m = re.search(pat, prompt, re.I)
        if m:
            return int(m.group(1))
    # SPELLED-OUT bit count
    m = re.search(rf"\b{re.escape(name)}\b[^\n,;.]*?\b{_BITNUM_ALT}\s*-?\s*bits?\b",
                  prompt, re.I)
    if m and not m.group(1).isdigit():
        return _bitnum(m.group(1))
    # SHARED-WIDTH conjunct: "a and b are 4-bit", "a, b and c are 4-bit inputs",
    # "both a and b are 4-bit". The width immediately follows the noun list.
    for gm in re.finditer(
            r"(?i)\b(\w+(?:\s*,\s*\w+)*)\s+(?:and|or)\s+(\w+)"
            r"[^.\n]{0,80}?\b(\d+)\s*-?\s*bits?\b",
            prompt):
        group = gm.group(1) + " " + gm.group(3)
        tokens = {t.strip().lower() for t in re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", group)}
        if name.lower() in tokens:
            return int(gm.group(3))
    # SHARED-WIDTH conjunct with the width BEFORE the noun list:
    # "two 4-bit BCD inputs (a and b)", "produce a 4-bit BCD result (sum)".
    for gm in re.finditer(
            r"(?i)\b(\d+)\s*-?\s*bits?\b[^.\n]{0,80}?"
            r"\b(\w+(?:\s*,\s*\w+)*)\s+(?:and|or)\s+(\w+)",
            prompt):
        width = int(gm.group(1))
        group = gm.group(2) + " " + gm.group(3)
        tokens = {t.strip().lower() for t in re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", group)}
        if name.lower() in tokens:
            return width
    return None
def _test_case_table(prompt: str) -> Optional[Dict[str, int]]:
    """Parse a markdown test-case table whose header names the ports (a / b /
    carry_in / Expected Sum / ...) and whose body hex cells fix each column's
    bit-width (#hex_digits * 4 for the widest hex cell). Returns {col_key: width}
    keyed by a normalized column name, or None. Used to corroborate widths."""
    # find a table that has an "Expected" column (the CVDP test-case-table shape).
    lines = prompt.splitlines()
    for i, ln in enumerate(lines):
        if "|" not in ln or not re.search(r"expected", ln, re.I):
            continue
        if i + 1 >= len(lines) or not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            continue
        headers = [h.strip().strip("`") for h in ln.strip().strip("|").split("|")]
        rows = []
        for body in lines[i + 2:]:
            if "|" not in body or not body.strip().startswith("|"):
                break
            cells = [c.strip().strip("`") for c in body.strip().strip("|").split("|")]
            if len(cells) == len(headers):
                rows.append(cells)
        if not rows:
            return None
        widths: Dict[str, int] = {}
        for ci, hname in enumerate(headers):
            key = re.sub(r"^(expected|actual)\s+", "", hname, flags=re.I).strip().lower()
            key = re.sub(r"\s+", "_", key)
            maxhex = 0
            for row in rows:
                cell = row[ci]
                if re.fullmatch(r"[0-9A-Fa-f]+", cell) and len(cell) >= 2:
                    maxhex = max(maxhex, len(cell))
            if maxhex:
                widths[key] = maxhex * 4
        if widths:
            return widths
    return None


# columns of a test-case table that are an index / time / annotation axis, never
# a DUT port.
_TABLE_NONPORT = frozenset({
    "test", "test_case", "testcase", "case", "case_no", "no", "num", "number",
    "index", "idx", "cycle", "cycles", "time", "step", "row", "clk", "clock",
    "description", "comment", "comments", "notes", "note", "scenario",
})


def _table_interface(prompt: str) -> Tuple[List[str], List[str]]:
    """(input_names, output_names) from a CVDP test-case table's HEADER row —
    a PROMPT-sourced interface (legal), replacing the OFF-LIMITS cocotb harness
    as the port-name source. A header column prefixed `Expected`/`Actual`/
    `Output`/`Result` is an OUTPUT; the remaining value columns are INPUTS.
    Index/time/annotation columns are dropped. NAMES ONLY — widths are resolved
    by the caller (table hex cells / prose / the 1-bit rule)."""
    lines = prompt.splitlines()
    for i, ln in enumerate(lines):
        if "|" not in ln or not re.search(r"expected", ln, re.I):
            continue
        if i + 1 >= len(lines) or not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            continue
        headers = [h.strip().strip("`") for h in ln.strip().strip("|").split("|")]
        ins: List[str] = []
        outs: List[str] = []
        for h in headers:
            is_out = bool(re.match(r"(?i)^(expected|actual|output|result)\b", h))
            key = re.sub(r"(?i)^(expected|actual|output|result)\s+", "", h).strip()
            key = re.sub(r"\s+", "_", key).lower()
            if not re.match(r"^[a-z_]\w*$", key) or key in _TABLE_NONPORT:
                continue
            (outs if is_out else ins).append(key)
        ins = list(dict.fromkeys(ins))
        outs = list(dict.fromkeys(outs))
        if ins and outs:
            return ins, outs
    return [], []


# --------------------------------------------------------------------------- #
# (d) prose "Input/Output ports" block — reuse the registry's own prose reader
# --------------------------------------------------------------------------- #
def _prose_ports(prompt: str) -> Tuple[List[Port], List[Port]]:
    # THE CHAIN, not one reader. This called `prose_port_block_read` directly,
    # so it read the indented `Input ports:` form and nothing else — a spec
    # stating its ports as a markdown signal/direction table (the commonest
    # datasheet form there is) parsed to ([], []) here even though a reader for
    # it exists. `prose_interface_bridge` tries every reader in order; each is a
    # no-op on text it does not recognise, and a reader that WOULD recognise the
    # text is skipped when its reading would cost a port the prose already
    # yields (`prose_interface_bridge._claim`).
    #
    # That last clause was claimed here before it was implemented, and the gap
    # was not cosmetic: a reader can recognise a text PARTIALLY, `parse_ports`
    # documents "bullet form wins", so a partial reading REPLACED a complete one
    # rather than adding to it. Six CVDP records were classified COMPLETE on an
    # interface the bridge had deleted most of — `thermostat_0001` came through
    # carrying a single output. MEASURED over the 302-record corpus, this call
    # site: 226 COMPLETE before the chain, 233 after, 0 records lost.
    try:
        import port_parser as _pp
        import prose_interface_bridge as _bridge
        ins, outs = _pp.parse_ports(_bridge.bridge(prompt))
        return ins, outs
    except Exception:
        return [], []


_PROSE_BULLET_RE = re.compile(
    r"^\s*[-*]\s*`(\w+)`\s*(?:\(([^)]*)\))?\s*:", re.MULTILINE)
_BULLET_WIDTH_RE = re.compile(r"(\d+)\s*bit", re.IGNORECASE)


def _prose_bullet_ports(prompt: str, params: Optional[Dict[str, int]] = None
                        ) -> Tuple[List[str], List[str], Dict[str, int]]:
    """(input_names, output_names, widths) from a PROSE BULLET port list of the
    form ``- `name` (input, N bits): description`` — a standard IC-spec port
    declaration convention (§4.05: PROMPT-sourced, never the harness). Direction
    comes from the parenthesised annotation, or — for a clock/reset bullet with no
    annotation — from the IC-domain reading of its description (```pclk`: APB clock
    input`` is an input clock; ```presetn`: … reset signal`` is an input reset).

    Strictly GATED to avoid false ports: activates ONLY when ≥2 bullets carry an
    explicit ``(input|output|inout …)`` annotation (a genuine port-list section);
    all-digit names (enum values like ``- `0`: disabled``) are dropped."""
    ins: List[str] = []
    outs: List[str] = []
    widths: Dict[str, int] = {}
    annotated: List[Tuple[str, str, str]] = []  # (name, dirword, paren)
    loose: List[Tuple[str, str]] = []           # (name, line) with no annotation
    for m in _PROSE_BULLET_RE.finditer(prompt):
        name, paren = m.group(1), (m.group(2) or "")
        if name.isdigit():
            continue
        line = prompt[m.start():prompt.find("\n", m.start()) if
                      prompt.find("\n", m.start()) >= 0 else len(prompt)]
        dm = re.search(r"\b(inout|input|output)\b", paren, re.IGNORECASE)
        if dm:
            annotated.append((name, dm.group(1).lower(), paren))
        else:
            loose.append((name, line))
    if len(annotated) < 2:
        return [], [], {}   # not a genuine port-list section

    def _add(name: str, direction: str, wsrc: str):
        (outs if direction == "output" else ins).append(name)
        wm = _BULLET_WIDTH_RE.search(wsrc)
        if wm:
            widths[name] = int(wm.group(1))
    for name, dirword, paren in annotated:
        _add(name, "output" if dirword == "output" else "input", paren)
    # loose clock/reset bullets in the SAME list are input ports (IC-domain read).
    for name, line in loose:
        low = line.lower()
        is_clk = re.search(r"\bclk|\bclock\b", name.lower() + " " + low)
        is_rst = re.search(r"reset|\brst|resetn|presetn", name.lower() + " " + low)
        if (is_clk and "input" in low) or is_rst or re.search(
                r"\binput\b", low):
            if name not in ins and name not in outs:
                ins.append(name)
                widths.setdefault(name, 1)  # clock/reset are 1-bit
    ins = list(dict.fromkeys(ins))
    outs = list(dict.fromkeys(outs))
    return ins, outs, widths




# --------------------------------------------------------------------------- #
# interface resolution (priority a -> b -> c/d), with width cross-check
# --------------------------------------------------------------------------- #
# Side metadata an interface carries for the PARAMETERIZED emit path:
#   params   — {PARAM_NAME: default_int}   (the parameter table to declare in #())
#   symbolic — {port_name: symbolic_expr}  ("N-1:0", "DATA_WIDTH-1:0")  for ports
#              whose width is a parameter expression; absent for literal-width ports.
def extract_interface_ex(record: dict, top: str
                         ) -> Optional[Tuple[List[Port], List[Port], Dict[str, int], Dict[str, str]]]:
    """Like extract_interface but ALSO returns the parameter-default table and the
    per-port symbolic width expression (for parameterized RTL emit). A port whose
    width is a parameter expression (`[N-1:0]`, `[DATA_WIDTH-1:0]`, `[N*W-1:0]`,
    `[$clog2(DEPTH)-1:0]`) is resolved to its integer default for the registry's
    logic AND carries the symbolic expression so the emit can re-parameterize it.
    §4.05: an unresolvable parameter expression keeps the port UNRESOLVED -> SKIP.
    """
    prompt = record.get("prompt") or (record.get("input") or {}).get("prompt") or ""
    # HARNESS (cocotb TB, .env) + output.context(golden) are OFF-LIMITS oracle.
    # The interface comes ONLY from input.context (skeleton header) + the prompt
    # (test-case table / prose).

    # (a) skeleton header from input.context (header-only).
    sk = _skeleton_ports(record, top)
    if sk:
        ins, outs = _clean_ports(sk[0]), _clean_ports(sk[1])
        return (ins, outs, {}, {}) if ins and outs else None

    # (d-first for completeness) prose port block, if the prompt has one.
    p_ins, p_outs = _prose_ports(prompt)

    # (c) test-case-table-derived port names (Expected/Actual columns => outputs);
    # widths from the table hex cells / prose / the 1-bit rule below. When the
    # prompt has NO test-case table, fall back to the prose-declared port NAMES
    # and resolve their widths through the SAME `_w` path (the prose declares
    # the names, but `A ([3:0], 4-bit)` widths only resolve via the width logic
    # below — the cocotb source did the same before it was removed as oracle).
    # parameter-default table (needed to resolve a `Bit Width` column that names a
    # parameter, e.g. `WIDTH`) + a place to record per-port symbolic widths so the
    # emit can produce a `module M #(parameter N=<default>, ...)` header.
    params = _W.param_defaults(prompt, "")
    symbolic: Dict[str, str] = {}

    c_ins, c_outs = _table_interface(prompt)
    sig_widths: Dict[str, int] = {}
    if not (c_ins and c_outs):
        # a `| Signal | Direction | Bit Width |` interface table (names + explicit
        # directions + widths) — a common CVDP shape the test-case table does not
        # cover. Its Bit-Width column feeds `_w` (via sig_widths) below; a
        # parameter-width cell (`WIDTH`) also records its symbolic form so the emit
        # re-parameterizes.
        s_ins, s_outs, sig_widths, sig_symbolic = _tbl.read_signal_direction_table(
            prompt, params)
        if s_ins and s_outs:
            c_ins, c_outs = s_ins, s_outs
            symbolic.update(sig_symbolic)
    if not (c_ins and c_outs) and p_ins and p_outs:
        c_ins = [n for n, _ in p_ins]
        c_outs = [n for n, _ in p_outs]
    table = _test_case_table(prompt) or {}

    # Unmistakable 1-bit signals (carry/borrow/flag/handshake): 1-bit by
    # definition. We trust a stray "N-bit" prose token for these ONLY if an
    # explicit `name [hi:lo]` bus range is tied to that exact name.
    # Expanded in this revision to also cover go / rst / reset / clk / clock /
    # start / clken / enable (and `_enable`) — the dataset frequently names
    # 1-bit control signals that the old (carry/valid/ready-only) regex missed.
    _ONE_BIT_RE = re.compile(
        r"(?i)^(c_?in|cin|carry_?in|c_?out|cout|carry_?out|b_?out|borrow|"
        r".*_valid|.*_ready|.*_enable|.*_en|enable|valid|ready|start|stop|"
        r"go|done|done_|error|.*_error|.*_flag|overflow|ovf|parity|found|sel|"
        r"mode|load|inc|dec|add|sub|mul|cs|we|wr|rd|oe|wr_en|rd_en|we_n|"
        r"rst|reset|rst_n|reset_n|areset|aresetn|clk|clock|clock_?n|clken|"
        r"clk_en|ap_start|ap_done|ap_idle|ap_ready|interrupt|irq|interrupt_?n|"
        r"trigger|sync_?in|sync_?out|chip_?select|cs_n)$")

    def _explicit_range(name: str) -> Optional[int]:
        m = re.search(rf"\b{re.escape(name)}\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", prompt)
        return abs(int(m.group(1)) - int(m.group(2))) + 1 if m else None

    def _w(name: str) -> Optional[int]:
        er = _explicit_range(name)
        if er is not None:
            return er
        if name in sig_widths:          # authoritative Signal/Direction/Bit-Width cell
            return sig_widths[name]
        if _ONE_BIT_RE.match(name):
            return 1
        pw = _prose_width(prompt, name)
        if pw is not None:
            return pw
        # PARAMETER-EXPRESSION / range-before-name / param-override width: resolve
        # the symbolic form to its integer default AND record the symbolic expr.
        sw = _W.symbolic_width(prompt, name, params)
        if sw is not None:
            sym, default_w, _tag = sw
            # only treat it as a true PARAMETER width (worth re-parameterizing) when
            # the expression carries an identifier; a pure-literal `[1:0] name`
            # range-before-name resolves to a constant width (no #() needed).
            if re.search(r"[A-Za-z_]", sym):
                symbolic[name] = sym
            return default_w
        # table corroboration: column key equals the port name (or sum/carry forms).
        key = name.lower()
        if key in table:
            return table[key]
        # a port DECLARED as a scalar (typed, no bracket range) is explicitly 1-bit.
        if _W.scalar_one_bit(prompt, name):
            return 1
        return None

    if c_ins and c_outs:
        ins: List[Port] = []
        outs: List[Port] = []
        # prefer the prose-declared width for a cocotb name; fall back to a
        # prose-declared port of the same name; else default a clearly 1-bit
        # control/flag signal to 1, else UNRESOLVED.
        prose_w = {n: w for n, w in p_ins + p_outs}
        unresolved = []
        for name in c_ins:
            w = _w(name)
            if w is None:
                w = prose_w.get(name)
            if w is None:
                # control/handshake/flag-style single-bit signals
                if name.lower() in _SEQ_PORTS or re.search(
                        r"(?i)(_en|_n|enable|valid|ready|start|stop|mode|sel|"
                        r"_in_valid|cin|carry_in|load|done)$", name):
                    w = 1
                else:
                    unresolved.append(name)
                    continue
            ins.append((name, w))
        for name in c_outs:
            w = _w(name)
            if w is None:
                w = prose_w.get(name)
            if w is None:
                if re.search(r"(?i)(carry_?out|cout|_out_valid|valid|done|error|"
                             r"flag|parity|found|sync_error|overflow)$", name):
                    w = 1
                else:
                    unresolved.append(name)
                    continue
            outs.append((name, w))
        ins, outs = _clean_ports(ins), _clean_ports(outs)
        # §4.05: if any non-control port's width could not be resolved, SKIP —
        # we never guess a data-path width.
        if unresolved or not ins or not outs:
            return None
        # keep only the symbolic entries that survived as real placed ports.
        kept = {n for n, _ in ins} | {n for n, _ in outs}
        symbolic = {k: v for k, v in symbolic.items() if k in kept}
        # Supplement prose-only control signals (e.g. `clk` that only appears
        # in `Clock(dut.clk, ...)` / `RisingEdge(dut.clk)` without a
        # `dut.clk.value` access). Their absence from the cocotb-side does NOT
        # make them any less of a harness input.
        cocotb_names = {n for n, _ in ins} | {n for n, _ in outs}
        for name, w in p_ins:
            if name not in cocotb_names and name.lower() in _SEQ_PORTS:
                ins.append((name, w))
                cocotb_names.add(name)
        used_params = _params_referenced(symbolic, params)
        return ins, outs, used_params, symbolic

    # (d) prose-only fallback (already parsed by the registry path itself, but if
    # the prose block has explicit widths we can still build the block).
    p_ins, p_outs = _clean_ports(p_ins), _clean_ports(p_outs)
    if p_ins and p_outs:
        return p_ins, p_outs, {}, {}

    return None


def _params_referenced(symbolic: Dict[str, str], params: Dict[str, int]) -> Dict[str, int]:
    """The subset of the parameter table actually referenced by a kept symbolic
    width — those are the params we declare in the emitted `#( ... )` header."""
    used: Dict[str, int] = {}
    for expr in symbolic.values():
        for tok in re.findall(r"[A-Za-z_]\w*", expr):
            if tok in params:
                used[tok] = params[tok]
    return used


def extract_interface(record: dict, top: str) -> Optional[Tuple[List[Port], List[Port]]]:
    """Backward-compatible 2-tuple interface (ports only) — the contract the family
    solvers and the existing tests depend on. Delegates to extract_interface_ex."""
    ex = extract_interface_ex(record, top)
    if ex is None:
        return None
    ins, outs, _params, _sym = ex
    return ins, outs


# --------------------------------------------------------------------------- #
# clean port-block emit (the registry's RTLLM-prose dialect form)
# --------------------------------------------------------------------------- #
def _port_line(name: str, w: int, role: str) -> str:
    if w > 1:
        return f"    {name} [{w-1}:0]: {w}-bit {role}."
    return f"    {name}: 1-bit {role}."


def _build_port_block(top: str, ins: List[Port], outs: List[Port]) -> str:
    lines = [f"Module name: {top}", "", "Input ports:"]
    lines += [_port_line(n, w, "input") for n, w in ins]
    lines += ["Output ports:"]
    lines += [_port_line(n, w, "output") for n, w in outs]
    lines += [""]
    return "\n".join(lines)


def _rename_module(rtl: str, top: str) -> str:
    """Ensure the emitted module is named exactly per the harness TOPLEVEL."""
    return re.sub(r"(\bmodule\s+)\w+", rf"\g<1>{top}", rtl, count=1)


def _parameterize_rtl(rtl: str, top: str, params: Dict[str, int],
                      symbolic: Dict[str, Tuple[int, str]]) -> str:
    """Re-parameterize the registry-emitted RTL: declare the referenced parameters
    in a `module M #( parameter N = <default>, ... )` block, and rewrite each
    symbolic-width port's literal `[default-1:0]` range to its symbolic form
    `[N-1:0]`. The registry emitted CORRECT logic at the default width; this only
    re-expresses the WIDTHS symbolically so the harness's `#(.N(...))` override
    drives a correctly-parameterized module.

    symbolic: {port_name: (default_width_int, symbolic_expr)} — e.g.
              {"i_adc_data_in": (8, "DATA_WIDTH-1:0")}.
    §4.05: only rewrites a literal range that EXACTLY equals the resolved default
    `[w-1:0]` immediately adjacent to the port name, so a same-width unrelated
    literal is never silently swapped.
    """
    if not params or not symbolic:
        return rtl

    # (1) insert the #(parameter ...) block right after `module <top>`.
    decls = ", ".join(f"parameter {p} = {v}" for p, v in sorted(params.items()))
    param_block = f" #(\n    {decls}\n)"
    # only insert if not already parameterized.
    if not re.search(rf"\bmodule\s+{re.escape(top)}\s*#", rtl):
        rtl = re.sub(rf"(\bmodule\s+{re.escape(top)}\b)", rf"\g<1>{param_block}",
                     rtl, count=1)

    # (2) rewrite each symbolic port's literal `[w-1:0] name` range to `[expr] name`.
    for name, (default_w, expr) in symbolic.items():
        if default_w <= 1:
            continue
        lit = rf"\[\s*{default_w - 1}\s*:\s*0\s*\]"
        # `[w-1:0] <name>` — width precedes the port name (declaration site).
        rtl = re.sub(rf"{lit}(\s*{re.escape(name)}\b)",
                     rf"[{expr}]\g<1>", rtl)
    return rtl


# --------------------------------------------------------------------------- #
# the bridge entry point
# --------------------------------------------------------------------------- #
def _strip_oracle(record: dict) -> dict:
    """A COPY of the record with the OFF-LIMITS oracle removed — the hidden test
    harness (`record["harness"]`: cocotb TB, `.env`) and the golden solution
    (`record["output"]`). The deterministic solvers dispatched below must see ONLY
    `input.prompt` + `input.context` (CVDP official rule). Stripping the oracle at
    this single dispatch chokepoint makes the prompt+context-only invariant hold
    BY CONSTRUCTION: no downstream solver — even one that still calls
    `record["harness"]` — can read what is no longer there. (The §3.9 EXTRACTION_GAP
    diagnostic in cvdp_complete_extract deliberately keeps the harness and is not on
    this path.)"""
    return {k: v for k, v in record.items() if k not in ("harness", "output")}


def solve(record: dict) -> Optional[str]:
    """Emit registry-solved RTL (module named per the PROMPT) for an atomic-shaped
    CVDP problem, or None (SKIP) on any ambiguity / non-atomic design. Reads ONLY
    `input.prompt` + `input.context`; the harness + golden are stripped up front."""
    if not isinstance(record, dict):
        return None
    # COMPLIANCE: strip the oracle (harness + output) before ANY downstream solver
    # sees the record — prompt+context-only holds by construction (see _strip_oracle).
    record = _strip_oracle(record)
    # NORMALIZE: some response JSONLs keep the prompt at the record root
    # (`record["prompt"]`) and leave `record["input"]["prompt"]` empty. All
    # downstream record solvers and extractors read `input.prompt`, so copy
    # the root prompt down before dispatching.
    if record.get("prompt") and not (record.get("input") or {}).get("prompt"):
        record = dict(record)
        record["input"] = dict(record.get("input") or {})
        record["input"]["prompt"] = record["prompt"]
    # UNIFIED dispatch: the record-level operation solvers (gf/bcd/crc/…) run
    # FIRST (their declared precedence, inside spec_artifact_registry), then the
    # text-level registry `generate()` is the fall-through. The bridge is now a
    # THIN driver — it owns only the record→ports adaptation the text path needs,
    # supplied as the `text_fallthrough` thunk. Lazy registry import keeps the
    # bridge free of a module-scope dependency on the registry (the registry's
    # record solvers import THIS module for the adapter helpers, so a module-scope
    # `import spec_artifact_registry` here would be a cycle).
    import spec_artifact_registry as _R

    def _text_path() -> Optional[str]:
        top = toplevel_name(record)
        if not top:
            return None
        prompt = record.get("prompt") or (record.get("input") or {}).get("prompt") or ""
        if not prompt.strip():
            return None
        # §4.05 up-front composite / special-algebra SKIP (NO-CHEAT: never let a
        # plain-integer emit stand in for a GF / modular / fixed-point / saturating
        # function the registry's plain op would get wrong).
        if _COMPOSITE_RE.search(prompt) or _SPECIAL_ALGEBRA_RE.search(prompt):
            return None
        # FAST PATH: some text-level registry recognizers (e.g. calendar_counter)
        # parse the prompt AND the interface themselves; they do not need the bridge
        # to fabricate a port block. Let them try the raw prompt first — this keeps
        # their self-contained prose parsers in play for records whose harness does
        # not yield a clean cocotb-derived interface.
        try:
            kind, _rtl = _R.generate(prompt, top)
        except Exception:
            _rtl = None
        if _rtl:
            _rtl = _rename_module(_rtl, top)
            return _rtl
        iface = extract_interface_ex(record, top)
        if not iface:
            return None
        ins, outs, used_params, symbolic = iface
        block = _build_port_block(top, ins, outs)
        # Prepend the clean port block to the ORIGINAL prompt prose. The registry
        # recognizes the OPERATION from the real prompt; the bridge only supplies
        # the parseable interface. We never paraphrase the function.
        spec = block + "\n" + prompt
        try:
            kind, _rtl = _R.generate(spec, top)
        except Exception:
            return None
        if not _rtl:
            return None
        _rtl = _rename_module(_rtl, top)
        if used_params and symbolic:
            widthmap = {n: w for n, w in ins + outs}
            sym_full = {n: (widthmap.get(n, 1), expr) for n, expr in symbolic.items()}
            _rtl = _parameterize_rtl(_rtl, top, used_params, sym_full)
        return _rtl

    rtl = _R.generate_from_record(record, text_fallthrough=_text_path)
    if not rtl:
        return None
    return rtl


def family_of(record: dict, rtl: Optional[str] = None) -> Optional[str]:
    """The registry artifact-type family the bridge solved this record with
    (for reporting). None if unsolved."""
    if not isinstance(record, dict):
        return None
    record = _strip_oracle(record)  # COMPLIANCE: prompt+context only (see solve()).
    top = toplevel_name(record) or "TopModule"
    prompt = record.get("prompt") or (record.get("input") or {}).get("prompt") or ""
    if _COMPOSITE_RE.search(prompt) or _SPECIAL_ALGEBRA_RE.search(prompt):
        return None
    iface = extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    spec = _build_port_block(top, ins, outs) + "\n" + prompt
    import spec_artifact_registry as _R  # lazy — see module-top note (cycle)
    try:
        kind, r = _R.generate(spec, top)
    except Exception:
        return None
    return kind if r else None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true", help="print emitted RTL")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n_emit = 0
    fam: Dict[str, int] = {}
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n_emit += 1
            k = family_of(r)
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  family={k} ===")
                print(rtl)
    print(f"emitted={n_emit}/{len(recs)}  families={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
