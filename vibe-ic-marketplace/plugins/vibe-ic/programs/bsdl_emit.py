#!/usr/bin/env python3
"""bsdl_emit.py — IEEE 1149.1 BSDL + boundary-scan-cell-per-pad plan emitter.

The 1149.1 TAP controller itself is inserted by `eda_dft add_jtag`
(Fault `fault tap`), but a TAP alone is not enough for a foundry/ATE DFT
sign-off: a padded design must also ship a Boundary-Scan Description
Language (BSDL) file plus one boundary-scan cell (BSC) per external I/O
PAD so board-level ATE can run EXTEST / SAMPLE / PRELOAD interconnect
tests. This program reads the design's TOP module I/O port list and emits:

  <project>/phase2/stage2/dft/<entity>.bsdl   (1149.1 BSDL description)
  <project>/reports/phase2/dft/bsdl_plan.json (machine-readable per-pad BSC
                                               insertion plan + verdict)

§4.05 honesty (no UNDISCLOSED pass on absence — one disclosed exception, the
step-11 skip sentinel described at `main(argv)` below):
  * A design with NO I/O ports, or a bare CORE with no pad ring, has no
    boundary to scan → verdict "N_A" (honest not-applicable, exit 0). A
    bare core legitimately has no boundary scan.
  * A PADDED design (pad-ring cells detected, bidirectional `inout` pads,
    or forced via --padded) → BSDL + per-pad BSC plan are emitted; verdict
    "PASS" (exit 0). If a padded design cannot be parsed / has no usable
    boundary pins → verdict "FAIL" (exit 1) — missing evidence, never a
    fake pass. The COMPANION gate (dft_signoff_check.py) is what FAILs a
    padded design whose BSDL is *missing*.

Padded-ness is decided chip-AGNOSTICALLY:
  * --padded / --bare force the classification.
  * --auto (default): padded IFF the netlist instantiates recognisable I/O
    pad cells (gf180mcu_fd_io__* / sky130_*_io__* / *iopad* / *bondpad* /
    IOPAD*) OR the top has bidirectional `inout` ports (bidir pads must go
    through I/O pads). Otherwise the top is treated as a core → N_A. This
    is the only honest default: a plain RTL top with input/output ports and
    no pad ring is indistinguishable from a core, so it is N_A until a real
    pad ring appears (or --padded is passed for a known chip-top).

Usage:
    python3 bsdl_emit.py <project_dir> \\
        --netlist phase2/stage2/dft/scan_netlist.v \\
        [--top chip_top] [--padded|--bare|--auto] \\
        [--ir-length 4] [--json <out>] [--bsdl <out>]

main(argv) -> int : 0 PASS/N_A / 1 FAIL / 2 IO-or-arg error OR disclosed
                    SKIPPED-CONDITION (rc=2 is overloaded; the stdout line and
                    the --json `verdict` field distinguish them). The
                    SKIPPED-CONDITION path is taken when the step-11 scan
                    netlist is absent and the runner left a
                    `dft_atpg_not_run.json` sentinel disclosing why — see
                    `dft_signoff_common.disclosed_atpg_skip`.

chip-AGNOSTIC: reads only the generic Verilog port list + pad-cell name
conventions; no design-specific knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None

try:
    import dft_signoff_common
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dft_signoff_common  # type: ignore


_PROGRAM = "bsdl_emit"
_VERSION = "1.0.0"

# TAP / linkage / supply pins are NOT boundary-scanned (they are the test
# access port itself, or power) — excluded from the boundary register.
_TAP_PINS = {"tck", "tms", "tdi", "tdo", "trst", "trstn", "trst_n", "tclk",
             "tck_i", "tms_i", "tdi_i", "tdo_o", "trst_i", "trst_ni"}
_SUPPLY_PREFIXES = ("vdd", "vss", "gnd", "vcc", "vpwr", "vgnd", "avdd", "avss",
                    "dvdd", "dvss", "vddio", "vssio", "vbat", "vref")

# Pad-cell instantiation name conventions (chip-AGNOSTIC). Matched against the
# *cell type* of an instantiation, not against arbitrary signal names.
_PAD_CELL_RE = re.compile(
    r"(?:gf180mcu_fd_io__\w+"
    r"|sky130_(?:fd|ef)_io__\w+"
    r"|\w*io_?pad\w*"
    r"|\w*bond_?pad\w*"
    r"|IOPAD\w*"
    r"|PAD[A-Z0-9_]+"
    r"|PDDW\w*|PDID\w*|PDO\w*|PDU\w*|PRB\w*)",  # common std pad-lib prefixes
    re.IGNORECASE,
)

_VERILOG_KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "assign", "always", "begin", "end", "parameter", "localparam", "genvar",
    "generate", "endgenerate", "if", "else", "case", "endcase", "for",
    "function", "endfunction", "task", "endtask", "supply0", "supply1",
    "signed", "unsigned", "integer", "real", "initial", "posedge", "negedge",
    "default", "specify", "endspecify", "defparam",
}


@dataclass
class Port:
    direction: str        # input / output / inout
    name: str
    width: int            # bits (>=1)
    msb: Optional[int] = None
    lsb: Optional[int] = None


@dataclass
class BSC:
    """A single boundary-scan cell in the boundary register."""
    num: int
    cell: str             # BC_1 / BC_2 / BC_4 ...
    port: str             # pad pin name (bus bit expanded)
    function: str         # input / output2 / output3 / control ...
    safe: str = "X"
    ccell: Optional[int] = None   # controlling cell number (for output3)
    disval: Optional[int] = None  # disable value of the control cell
    rslt: Optional[str] = None    # disable result (Z)


# ── Verilog parsing ────────────────────────────────────────────────────

def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _module_names(text: str) -> List[str]:
    return re.findall(r"\bmodule\s+([A-Za-z_]\w*)", text)


def find_top_module(text: str, explicit: Optional[str]) -> Optional[str]:
    """Pick the top module: --top if given & present, else the module that is
    not instantiated by any other module, else the last-defined module."""
    names = _module_names(text)
    if not names:
        return None
    if explicit:
        return explicit if explicit in names else explicit  # trust user
    if len(names) == 1:
        return names[0]
    # Instantiated names: `<CellType> <inst> ( ... )` where CellType is a
    # known module and not a keyword.
    name_set = set(names)
    instantiated = set()
    for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s+(?:#\s*\([^;]*?\)\s*)?"
                         r"[A-Za-z_]\w*\s*\(", text, re.M):
        ct = m.group(1)
        if ct in name_set and ct not in _VERILOG_KEYWORDS:
            instantiated.add(ct)
    roots = [n for n in names if n not in instantiated]
    if len(roots) == 1:
        return roots[0]
    if roots:
        # Multiple roots — prefer one whose name hints "top", else first root.
        for n in roots:
            if "top" in n.lower() or "chip" in n.lower():
                return n
        return roots[0]
    return names[-1]


def _module_body(text: str, top: str) -> Optional[Tuple[str, str]]:
    """Return (header_paren_content, full_body_between_header_and_endmodule)."""
    m = re.search(
        rf"\bmodule\s+{re.escape(top)}\b\s*(?:#\s*\((?P<params>.*?)\)\s*)?"
        r"\((?P<ports>.*?)\)\s*;(?P<body>.*?)\bendmodule",
        text, re.DOTALL)
    if not m:
        # module with empty/implicit port list
        m2 = re.search(
            rf"\bmodule\s+{re.escape(top)}\b(?P<body>.*?)\bendmodule",
            text, re.DOTALL)
        if not m2:
            return None
        return "", m2.group("body")
    return m.group("ports"), m.group("body")


def _width(range_str: Optional[str]) -> Tuple[int, Optional[int], Optional[int]]:
    if not range_str:
        return 1, None, None
    m = re.match(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", range_str.strip())
    if not m:
        return 1, None, None
    hi, lo = int(m.group(1)), int(m.group(2))
    return abs(hi - lo) + 1, hi, lo


# An identifier is EITHER a plain Verilog identifier OR an IEEE-1364 §3.7.1
# ESCAPED identifier: a backslash, then any run of non-whitespace, terminated
# by whitespace. Escaped identifiers are not an exotic corner — they are the
# ORDINARY shape of a gate-level netlist port in this flow, because
# `yosys ... splitnets -ports; write_verilog` emits every bus bit as
# `\bus_name[3] `. A pattern that only accepts `[A-Za-z_]\w*` silently drops
# every one of them (vibe-ic: measured on a real sky130-mapped OpenTitan AES
# core — 1995 declared top ports parsed as 14).
_IDENT_RE = re.compile(r"\\\S+|[A-Za-z_]\w*")

_ANSI_SEG_RE = re.compile(
    r"^\s*(?:(input|output|inout)\b)?\s*"
    r"(?:wire|reg|logic|signed|unsigned|\s)*?"
    r"(\[[^\]]+\])?\s*"
    r"(\\\S+|[A-Za-z_]\w*)\s*$")

# The name blob is captured permissively (anything up to the `;`) and then
# TOKENISED with _IDENT_RE, so escaped names carrying `[`, `]`, `$`, `.` etc.
# survive. The optional width group still binds first, and cannot mis-capture
# an escaped name's own `[..]` because that name begins with a backslash.
_BODY_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*"
    r"(?:wire|reg|logic|signed|unsigned|\s)*?"
    r"(\[[^\]]+\])?\s*"
    r"([^;]*?)\s*;",
    re.DOTALL)

# `\bus[3] ` → ("bus", 3). Used to coalesce splitnets-style per-bit ports back
# into one vector Port, so the boundary register gets one BSC per pad bit AND
# the BSDL port declaration stays legal (`bus : inout bit_vector(3 downto 0)`)
# instead of an illegal `bus[3] : inout bit`.
_BIT_SELECT_RE = re.compile(r"^(.+?)\[(\d+)\]$")


def _normalise_ident(tok: str) -> str:
    """Strip the leading backslash of an IEEE-1364 escaped identifier. The
    trailing whitespace terminator is already consumed by the tokeniser."""
    return tok[1:] if tok.startswith("\\") else tok


def _coalesce_bit_selects(ports: List["Port"]) -> List["Port"]:
    """Fold per-bit ports (`bus[0]`..`bus[N]`) emitted by `splitnets -ports`
    back into a single vector Port, preserving first-appearance order.

    Only a COMPLETE contiguous index set is folded. An incomplete set is left
    as individual bits rather than folded into a range that would silently
    invent pads the netlist does not declare — over-counting a boundary
    register is the same class of error as under-counting it."""
    groups: dict = {}
    order: List[str] = []
    for p in ports:
        m = _BIT_SELECT_RE.match(p.name)
        key = (m.group(1), p.direction) if (m and p.width == 1) else None
        if key is None:
            order.append(p.name)
            groups[p.name] = p
            continue
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append((int(m.group(2)), p))

    out: List[Port] = []
    for key in order:
        g = groups[key]
        if isinstance(g, Port):
            out.append(g)
            continue
        idxs = sorted(i for i, _ in g)
        if idxs == list(range(idxs[0], idxs[-1] + 1)):
            base, direction = key
            out.append(Port(direction, base, len(idxs), idxs[-1], idxs[0]))
        else:  # incomplete range — keep the bits exactly as declared
            out.extend(p for _, p in sorted(g, key=lambda t: t[0]))
    return out


def parse_top_ports(text: str, top: str) -> List[Port]:
    """Parse the TOP module I/O ports (ANSI header + non-ANSI body decls).
    Handles bus widths and comma-separated multi-name declarations. Direction
    is sticky across ANSI header segments. Returns ports in declaration order,
    de-duplicated by name (first direction/width seen wins)."""
    text = _strip_comments(text)
    parts = _module_body(text, top)
    if parts is None:
        return []
    header, body = parts

    ordered: List[Port] = []
    seen = set()

    def _add(direction: str, width: int, hi, lo, name: str) -> None:
        if name in seen or name in _VERILOG_KEYWORDS:
            return
        seen.add(name)
        ordered.append(Port(direction, name, width, hi, lo))

    # 1) ANSI header ports (sticky direction).
    if header.strip():
        current_dir = None
        for seg in header.split(","):
            sm = _ANSI_SEG_RE.match(seg)
            if not sm:
                continue
            d, rng, name = sm.group(1), sm.group(2), sm.group(3)
            if d:
                current_dir = d
            if current_dir is None:
                # non-ANSI style header (bare names) — resolved from body.
                continue
            w, hi, lo = _width(rng)
            _add(current_dir, w, hi, lo, _normalise_ident(name))

    # 2) Non-ANSI (and any body-level) direction declarations.
    for bm in _BODY_DECL_RE.finditer(body):
        d, rng, names_blob = bm.group(1), bm.group(2), bm.group(3)
        w, hi, lo = _width(rng)
        for tok in _IDENT_RE.findall(names_blob):
            # net-type / sign keywords may still lead the blob; _add filters
            # them via _VERILOG_KEYWORDS.
            _add(d, w, hi, lo, _normalise_ident(tok))

    return _coalesce_bit_selects(ordered)


# ── Pad-ring detection ─────────────────────────────────────────────────

def detect_pad_ring(text: str) -> Tuple[bool, List[str]]:
    """Return (pad_cells_present, evidence). Scans instantiations for I/O
    pad-cell types (chip-AGNOSTIC name conventions)."""
    text = _strip_comments(text)
    evidence: List[str] = []
    for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*\(", text, re.M):
        ct = m.group(1)
        if ct in _VERILOG_KEYWORDS:
            continue
        if _PAD_CELL_RE.fullmatch(ct):
            if ct not in evidence:
                evidence.append(ct)
    return (len(evidence) > 0), evidence[:20]


def classify(ports: List[Port],
             pad_cells_present: bool,
             force: str) -> Tuple[str, List[str]]:
    """Return (classification, reasons). classification ∈ {PADDED, BARE, EMPTY}.

    EMPTY = no I/O ports at all → N/A.
    """
    io_ports = [p for p in ports
                if p.name.lower() not in _SUPPLY_PREFIXES
                and not p.name.lower().startswith(_SUPPLY_PREFIXES)]
    reasons: List[str] = []
    if not io_ports:
        reasons.append("top module has no I/O ports (bare core / testbench "
                       "wrapper) — no boundary to scan")
        return "EMPTY", reasons

    if force == "padded":
        reasons.append("classification forced via --padded")
        return "PADDED", reasons
    if force == "bare":
        reasons.append("classification forced via --bare (treated as core)")
        return "BARE", reasons

    # auto
    has_inout = any(p.direction == "inout" for p in ports)
    if pad_cells_present:
        reasons.append("I/O pad-ring cells instantiated in the netlist "
                       "→ padded chip")
        return "PADDED", reasons
    if has_inout:
        reasons.append("bidirectional `inout` port(s) present — bidir pads "
                       "require an I/O pad ring → padded chip")
        return "PADDED", reasons
    reasons.append("no pad-ring cells and no bidirectional pads detected — "
                   "top treated as a CORE (boundary scan inserted at the "
                   "pad ring, not present here). Pass --padded for a known "
                   "chip-top.")
    return "BARE", reasons


# ── Boundary register construction ─────────────────────────────────────

def _is_scan_pin(name: str) -> bool:
    n = name.lower()
    if n in _TAP_PINS:
        return False
    if n.startswith(_SUPPLY_PREFIXES):
        return False
    return True


def build_boundary_cells(ports: List[Port]) -> Tuple[List[BSC], List[str]]:
    """Build one BSC per external I/O PAD (bus bits expanded to per-pad
    cells). Returns (cells, scanned_pad_pin_names).

      * input pad   → 1 cell  (BC_4, function input)
      * output pad  → 1 cell  (BC_1, function output2)
      * inout pad   → 3 cells (input observe + output3 driver + control)

    Cells are numbered so the first declared pad gets the highest num
    (conventional TDI-nearest-first ordering); numbering is internally
    consistent (control cell precedes its controlled output cell)."""
    # First materialise per-pad cell specs in declaration order.
    specs: List[Tuple[str, str, str]] = []  # (pad_pin, cell, function)
    ctrl_links: List[Optional[int]] = []     # placeholder, resolved after
    scanned: List[str] = []

    def _pins(p: Port) -> List[str]:
        if p.width <= 1 or p.msb is None:
            return [p.name]
        hi, lo = p.msb, p.lsb if p.lsb is not None else 0
        rng = range(hi, lo - 1, -1) if hi >= lo else range(hi, lo + 1)
        return [f"{p.name}[{i}]" for i in rng]

    # We build a flat list of (pad_pin, cell, function, is_control_for_next)
    flat: List[dict] = []
    for p in ports:
        if not _is_scan_pin(p.name):
            continue
        for pin in _pins(p):
            scanned.append(pin)
            if p.direction == "input":
                flat.append({"pin": pin, "cell": "BC_4",
                             "function": "input"})
            elif p.direction == "output":
                flat.append({"pin": pin, "cell": "BC_1",
                             "function": "output2"})
            else:  # inout — observe + control + driver
                flat.append({"pin": pin, "cell": "BC_4",
                             "function": "input"})
                flat.append({"pin": "*", "cell": "BC_2",
                             "function": "control"})
                flat.append({"pin": pin, "cell": "BC_1",
                             "function": "output3",
                             "_controlled": True})

    n = len(flat)
    cells: List[BSC] = []
    # num assignment: descending from n-1 by flat index.
    for idx, f in enumerate(flat):
        num = n - 1 - idx
        bsc = BSC(num=num, cell=f["cell"], port=f["pin"],
                  function=f["function"])
        if f.get("_controlled"):
            # the immediately-preceding flat entry is its control cell
            ctrl_num = n - 1 - (idx - 1)
            bsc.ccell = ctrl_num
            bsc.disval = 0
            bsc.rslt = "Z"
        cells.append(bsc)
    return cells, scanned


# ── BSDL rendering ─────────────────────────────────────────────────────

def _bsdl_port_decls(ports: List[Port]) -> List[str]:
    decls = []
    for p in ports:
        dir_map = {"input": "in", "output": "out", "inout": "inout"}
        d = dir_map.get(p.direction, "in")
        if p.width > 1 and p.msb is not None:
            lo = p.lsb if p.lsb is not None else 0
            decls.append(f"    {p.name} : {d} bit_vector({p.msb} downto {lo})")
        else:
            decls.append(f"    {p.name} : {d} bit")
    return decls


def _find_tap(ports: List[Port]) -> dict:
    tap = {"tck": None, "tms": None, "tdi": None, "tdo": None, "trst": None}
    for p in ports:
        n = p.name.lower()
        if n in ("tck", "tck_i", "tclk"):
            tap["tck"] = p.name
        elif n in ("tms", "tms_i"):
            tap["tms"] = p.name
        elif n in ("tdi", "tdi_i"):
            tap["tdi"] = p.name
        elif n in ("tdo", "tdo_o"):
            tap["tdo"] = p.name
        elif n in ("trst", "trstn", "trst_n", "trst_i", "trst_ni"):
            tap["trst"] = p.name
    return tap


def render_bsdl(entity: str,
                ports: List[Port],
                cells: List[BSC],
                ir_length: int) -> str:
    tap = _find_tap(ports)
    tck = tap["tck"] or "TCK"
    tms = tap["tms"] or "TMS"
    tdi = tap["tdi"] or "TDI"
    tdo = tap["tdo"] or "TDO"

    lines: List[str] = []
    lines.append(f"-- BSDL (IEEE Std 1149.1-2001) — auto-generated by "
                 f"{_PROGRAM}.py v{_VERSION}")
    lines.append(f"-- DO NOT HAND-EDIT — regenerate from the top-module port "
                 f"list if the pad ring changes.")
    lines.append(f"entity {entity} is")
    lines.append("  generic (PHYSICAL_PIN_MAP : string := \"GENERIC\");")
    lines.append("  port (")
    lines.append(",\n".join(_bsdl_port_decls(ports)))
    lines.append("  );")
    lines.append("")
    lines.append("  use STD_1149_1_2001.all;")
    lines.append("")
    lines.append(f"  attribute COMPONENT_CONFORMANCE of {entity} : entity is")
    lines.append("    \"STD_1149_1_2001\";")
    lines.append("")
    # TAP linkage
    lines.append(f"  attribute TAP_SCAN_IN    of {tdi} : signal is true;")
    lines.append(f"  attribute TAP_SCAN_MODE  of {tms} : signal is true;")
    lines.append(f"  attribute TAP_SCAN_OUT   of {tdo} : signal is true;")
    lines.append(f"  attribute TAP_SCAN_CLOCK of {tck} : signal is "
                 f"(10.0e6, BOTH);")
    if tap["trst"]:
        lines.append(f"  attribute TAP_SCAN_RESET of {tap['trst']} : signal "
                     f"is true;")
    lines.append("")
    lines.append(f"  attribute INSTRUCTION_LENGTH of {entity} : entity is "
                 f"{ir_length};")
    # Opcodes sized to ir_length (all-1s BYPASS, all-0s EXTEST convention).
    ones = "1" * ir_length
    zeros = "0" * ir_length
    sample = ("0" * (ir_length - 1)) + "1"
    idcode = ("0" * (ir_length - 2)) + "10" if ir_length >= 2 else "10"
    lines.append(f"  attribute INSTRUCTION_OPCODE of {entity} : entity is")
    lines.append(f"    \"BYPASS ({ones}),\" &")
    lines.append(f"    \"EXTEST ({zeros}),\" &")
    lines.append(f"    \"SAMPLE ({sample}),\" &")
    lines.append(f"    \"PRELOAD ({sample}),\" &")
    lines.append(f"    \"IDCODE ({idcode})\";")
    lines.append(f"  attribute INSTRUCTION_CAPTURE of {entity} : entity is "
                 f"\"{sample}\";")
    lines.append("")
    lines.append(f"  attribute BOUNDARY_LENGTH of {entity} : entity is "
                 f"{len(cells)};")
    if cells:
        lines.append(f"  attribute BOUNDARY_REGISTER of {entity} : entity is")
        cell_lines = []
        for c in cells:
            if c.ccell is not None:
                inner = (f"{c.num} ({c.cell}, {c.port}, {c.function}, "
                         f"{c.safe}, {c.ccell}, {c.disval}, {c.rslt})")
            else:
                inner = (f"{c.num} ({c.cell}, {c.port}, {c.function}, "
                         f"{c.safe})")
            cell_lines.append(inner)
        # highest num first, matching the standard listing order
        cell_lines_sorted = [x for _, x in sorted(
            zip([c.num for c in cells], cell_lines), reverse=True)]
        rendered = " &\n".join(f"    \"{cl},\"" if i < len(cell_lines_sorted) - 1
                               else f"    \"{cl}\";"
                               for i, cl in enumerate(cell_lines_sorted))
        lines.append(rendered)
    lines.append(f"end {entity};")
    lines.append("")
    return "\n".join(lines)


# ── Top-level emit ─────────────────────────────────────────────────────

def _dft_dir(project: Path) -> Path:
    if _pl is not None:
        return _pl.dft_dir(project)
    return project / "phase2" / "stage2" / "dft"


def _plan_path(project: Path) -> Path:
    if _pl is not None:
        return _pl.report_path(project, "dft/bsdl_plan.json")
    return project / "reports" / "phase2" / "dft" / "bsdl_plan.json"


def emit(project: Path,
         netlist_rel: str,
         top: Optional[str],
         mode: str,
         ir_length: int,
         bsdl_out: Optional[str] = None) -> dict:
    """Parse ports, classify, and (if padded) emit BSDL + per-pad BSC plan.
    Returns the plan dict (also written to reports/phase2/dft/bsdl_plan.json)."""
    netlist = project / netlist_rel
    base = {
        "program": _PROGRAM,
        "version": _VERSION,
        "project_dir": str(project),
        "netlist": netlist_rel,
    }
    if not netlist.is_file():
        base.update({
            "verdict": "FAIL", "status": "FAIL",
            "padded": None,
            "reasons": [f"netlist not found: {netlist} — cannot read the top "
                        "I/O port list to build a boundary register"],
        })
        return base

    text = netlist.read_text(errors="replace")
    top_mod = find_top_module(text, top)
    if top_mod is None:
        base.update({
            "verdict": "FAIL", "status": "FAIL", "padded": None,
            "reasons": ["no `module` found in the netlist — cannot identify a "
                        "top module for boundary-scan extraction"],
        })
        return base

    ports = parse_top_ports(text, top_mod)
    pad_cells_present, pad_evidence = detect_pad_ring(text)
    classification, reasons = classify(ports, pad_cells_present, mode)

    base["top_module"] = top_mod
    base["port_count"] = len(ports)
    base["pad_cells_detected"] = pad_evidence
    base["classification"] = classification

    # N/A: no I/O ports OR a bare core — honest not-applicable.
    if classification in ("EMPTY", "BARE"):
        base.update({
            "padded": False,
            "boundary_length": 0,
            "bsdl_present": False,
            "verdict": "N_A", "status": "N_A",
            "reasons": reasons + [
                "no boundary scan applicable at this level — a bare core "
                "has no pad ring (honest N/A, not a failure)"],
        })
        return base

    # PADDED: build the boundary register + BSDL.
    cells, scanned = build_boundary_cells(ports)
    if not cells:
        base.update({
            "padded": True,
            "boundary_length": 0,
            "bsdl_present": False,
            "verdict": "FAIL", "status": "FAIL",
            "reasons": reasons + [
                "design classified PADDED but no boundary-scannable I/O pins "
                "were found (all ports were TAP/supply) — cannot build a "
                "boundary register"],
        })
        return base

    entity = re.sub(r"\W", "_", top_mod)
    bsdl_text = render_bsdl(entity, ports, cells, ir_length)
    bsdl_path = (Path(bsdl_out) if bsdl_out
                 else _dft_dir(project) / f"{entity}.bsdl")
    try:
        bsdl_path.parent.mkdir(parents=True, exist_ok=True)
        bsdl_path.write_text(bsdl_text)
        bsdl_written = True
    except OSError as exc:
        bsdl_written = False
        reasons.append(f"could not write BSDL file {bsdl_path}: {exc}")

    tap = _find_tap(ports)
    tap_present = all(tap[k] for k in ("tck", "tms", "tdi", "tdo"))
    if not tap_present:
        reasons.append(
            "WARNING: TAP pins (TCK/TMS/TDI/TDO) not all present on the top "
            "port list — the boundary register cannot be accessed without a "
            "1149.1 TAP (insert via eda_dft add_jtag). BSDL emitted for the "
            "pad ring, but the TAP linkage is incomplete.")

    per_pad = []
    for c in cells:
        per_pad.append({
            "num": c.num, "cell": c.cell, "port": c.port,
            "function": c.function, "safe": c.safe,
            "ccell": c.ccell, "disval": c.disval, "rslt": c.rslt,
        })

    base.update({
        "padded": True,
        "entity": entity,
        "boundary_length": len(cells),
        "boundary_scan_pins": scanned,
        "boundary_register": per_pad,
        "tap_present": tap_present,
        "tap_pins": {k: v for k, v in tap.items() if v},
        "ir_length": ir_length,
        "bsdl_file": str(bsdl_path),
        "bsdl_present": bsdl_written,
        "verdict": "PASS" if bsdl_written else "FAIL",
        "status": "PASS" if bsdl_written else "FAIL",
        "reasons": reasons + [
            f"emitted BSDL ({len(cells)} boundary cells over "
            f"{len(scanned)} pad pins) for padded design"],
    })
    return base


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit an IEEE 1149.1 BSDL + boundary-scan-cell-per-pad "
                    "plan from the design's top I/O port list.")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--netlist", default="phase2/stage2/dft/scan_netlist.v",
                    help="Path (relative to project_dir) to the top netlist / "
                         "RTL (default: phase2/stage2/dft/scan_netlist.v)")
    ap.add_argument("--top", default=None,
                    help="Top module name (default: auto-detect the "
                         "non-instantiated root module)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--padded", dest="mode", action="store_const",
                   const="padded", help="Force PADDED (emit BSDL)")
    g.add_argument("--bare", dest="mode", action="store_const",
                   const="bare", help="Force BARE core (N/A)")
    g.add_argument("--auto", dest="mode", action="store_const",
                   const="auto", help="Auto-detect (default)")
    ap.set_defaults(mode="auto")
    ap.add_argument("--ir-length", type=int, default=4,
                    help="Instruction-register length for the BSDL "
                         "INSTRUCTION_LENGTH (default 4)")
    ap.add_argument("--bsdl", default=None,
                    help="Explicit BSDL output path (default: "
                         "phase2/stage2/dft/<entity>.bsdl)")
    ap.add_argument("--json", default=None,
                    help="Plan JSON output path (default: "
                         "reports/phase2/dft/bsdl_plan.json)")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    if args.ir_length < 2:
        print("ERROR: --ir-length must be >= 2 (1149.1 IR minimum)",
              file=sys.stderr)
        return 2

    # HONEST disclosed-skip (flow step-11): when the scan netlist is ABSENT
    # (the runner renamed scan_netlist.v → scan_netlist_prelim.v because the
    # OSS Fault ATPG engine could not measure sign-off coverage) AND a sibling
    # dft_atpg_not_run.json honestly self-reports the skip
    # (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION), resolve to SKIPPED-CONDITION
    # (rc=2 → VACUOUS_PASS) instead of a FAIL — a BSDL plan cannot be emitted
    # without a scan netlist. Guarded on BOTH conditions — a real run (scan
    # netlist present) NEVER takes this path.
    _skip = dft_signoff_common.disclosed_atpg_skip(project)
    if _skip is not None and not (project / args.netlist).is_file():
        print(f"{_PROGRAM}: SKIPPED-CONDITION — DFT ATPG disclosed-skipped: "
              f"{_skip}")
        json_path = Path(args.json) if args.json else _plan_path(project)
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(json_path, json.dumps({
                "program": _PROGRAM,
                "version": _VERSION,
                "project_dir": str(project),
                "netlist": args.netlist,
                "verdict": "SKIPPED-CONDITION",
                "status": "SKIPPED-CONDITION",
                "reason": _skip,
                "reasons": [f"DFT ATPG disclosed-skipped: {_skip} — scan "
                            "netlist absent, no boundary register to emit; a "
                            "sibling sentinel honestly self-reports the skip"],
            }, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:  # pragma: no cover - IO edge
            print(f"WARN: could not write plan JSON {json_path}: {exc}",
                  file=sys.stderr)
        return 2

    plan = emit(project, args.netlist, args.top, args.mode,
                args.ir_length, args.bsdl)

    json_path = Path(args.json) if args.json else _plan_path(project)
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json_path, json.dumps(plan, indent=2, ensure_ascii=False)
                             + "\n")
    except OSError as exc:  # pragma: no cover - IO edge
        print(f"WARN: could not write plan JSON {json_path}: {exc}",
              file=sys.stderr)

    verdict = plan.get("verdict")
    print(f"{_PROGRAM}: top={plan.get('top_module')} "
          f"classification={plan.get('classification')} "
          f"boundary_length={plan.get('boundary_length')} verdict={verdict}",
          file=sys.stderr)
    print(json.dumps(plan, indent=2, ensure_ascii=False))

    # N_A and PASS are both exit 0 (N/A is honest, not a failure); FAIL is 1.
    return 0 if verdict in ("PASS", "N_A") else 1


if __name__ == "__main__":
    sys.exit(main())
