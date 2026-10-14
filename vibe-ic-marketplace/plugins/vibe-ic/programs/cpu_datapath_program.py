#!/usr/bin/env python3
"""cpu_datapath_program.py — a CPU data-path case the flow builds itself (Step 5).

ENFORCEMENT: producer helper — builds a program image and a self-checking
testbench, decides no step. `full_stack_functional_tb` runs what this builds
through the full-stack top and records it; `bit_level_full_stack_tb_check`
re-derives both from the design input and judges the transcript.

WHY THIS EXISTS (R-0929-STEP5-BAR, root as IC expert, 2026-09-29)
================================================================
Step 5 may count the public ISA suites (R-0929-OWNER-SUB-ACCEPT (1): same RTL,
a test-only memory PARAMETER) only when "at least one CPU data-path case (a real
program: fetch, execute, load/store over the delivered memory) executes and
passes through chip_top at the delivered memory size". MEASURED on subservient
(FULLSTACKTB replay): none existed. The ISA suites do not fit the delivered
1 KiB, the firmware images the input names are absent, and the one data-path
program that had run (an expert cocotb hook: 5 + 7 = 12 stored over the shared
byte SRAM) drove the bare CORE with its program words hand-written into the
testbench.

WHAT IT BUILDS
==============
From the design input and the design's own declaration only (§4.05):
  * the ISA base the Phase-1 datasheet layer extracted (`L1.isa_base`, RV32I /
    RV32E) — nothing else is assembled;
  * the delivered memory: `memsize_bytes`, the SRAM role -> port map and read
    latency the implementation declared (`sram_interface`), the register-file
    reservation when the register file shares that SRAM, the reset vector
    (declaration / core_parameters / an L8 constant) and reset polarity;
a short RV32I program is ASSEMBLED here (the encoder below, not a word list
typed into a testbench), laid at the reset vector, and written as a `$readmemh`
image. It fetches from the reset vector, computes A + B, STORES the word, LOADS
it back, adds A to the loaded value and stores that — so the second word is
right only if the load path returned the first. The expected bytes come from
`reference_execute`, an interpreter of the same encodings, never from the DUT.

The testbench owns a plain byte SRAM of exactly the delivered size, preset to a
non-zero pattern (a zero-register or unwritten-lane mistake cannot read as
right), serves reads at the declared latency, and judges five checks:
  reset_vector_fetch  every byte of the image, from the reset vector on,
                      read after release (enable-qualified)
  store_word          the stored A + B word
  load_store_word     the word computed from the LOADED value
  byte_lanes_written  every byte of both words written by the DUT
  write_discipline    no write outside the data words / register-file
                      reservation, no out-of-range address, no X on an
                      enable while the design is out of reset, no X data
                      written
It prints `ORACLE_TB_DONE pass=k/5` and the case's `[TB <name>] PASS|FAIL`,
the grammar `full_stack_functional_tb.score_transcript` already scores.

Fail-closed: a design whose input states no RV32 base, no delivered memory size,
no SRAM role map, no read latency or no reset vector gets NO program — a named
refusal, never a guessed binding.

chip-AGNOSTIC: no design, PDK or port literal; port names come from the
design's declaration, widths from its RTL port list. The operands are flow
constants; the ISA is a public standard.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _path_layout as _pl

CASE_NAME = "cpu_datapath_program"
SCHEMA = "vibeic.cpu_datapath_program.v1"
#: Flow constants. The answer is computed by `reference_execute`.
OPERAND_A = 5
OPERAND_B = 7
#: The byte every SRAM location holds before the image is loaded.
FILL_BYTE = 0xA5
#: Clock budget after reset release. A bit-serial RV32 core spends O(10^2)
#: cycles per instruction; eight instructions fit well inside this.
CYCLE_CAP = 200000
#: Cycles watched after the last expected store (a stray write after it FAILs).
SETTLE_CYCLES = 64
RESET_HOLD_CYCLES = 10
CHECKS = ("reset_vector_fetch", "store_word", "load_store_word",
          "byte_lanes_written", "write_discipline")

_DECLARATION_REL = "plugin_output/declaration.json"
#: `L1.isa_base` tokens this program is valid for (x1..x5 exist in both).
_RV32_BASES = ("RV32I", "RV32E")
_RESET_PC_KEYS = ("reset_pc", "reset_vector", "RESET_PC", "RESET_VECTOR")
_HEX_RE = re.compile(r"^\s*0[xX]([0-9a-fA-F_]+)\s*$")
_DEC_RE = re.compile(r"^\s*(\d+)\s*$")
#: declaration `sram_interface` key -> role.
_ROLE_KEYS = {
    "raddr": ("read_address", "raddr", "address", "addr"),
    "waddr": ("write_address", "waddr"),
    "wdata": ("write_data", "wdata"),
    "rdata": ("read_data", "rdata"),
    "we": ("write_enable", "we", "wen"),
    "ren": ("read_enable", "ren"),
}
_LATENCY_KEYS = ("read_latency_cycles", "read_data_latency_cycles",
                 "read_data_valid_after_request_cycles")
_RF_KEYS = ("rf_reserved_high_bytes", "register_file_reserved_high_bytes")
_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


# ---------------------------------------------------------------------------
# RV32I encoder + reference interpreter (the public ISA, nothing else)
# ---------------------------------------------------------------------------
def _imm12(imm: int) -> int:
    if not -2048 <= imm <= 2047:
        raise ValueError(f"immediate {imm} does not fit 12 signed bits")
    return imm & 0xFFF


def enc_addi(rd: int, rs1: int, imm: int) -> int:
    return (_imm12(imm) << 20) | (rs1 << 15) | (0 << 12) | (rd << 7) | 0x13


def enc_add(rd: int, rs1: int, rs2: int) -> int:
    return (rs2 << 20) | (rs1 << 15) | (0 << 12) | (rd << 7) | 0x33


def enc_sw(rs2: int, rs1: int, imm: int) -> int:
    i = _imm12(imm)
    return (((i >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) \
        | (2 << 12) | ((i & 0x1F) << 7) | 0x23


def enc_lw(rd: int, rs1: int, imm: int) -> int:
    return (_imm12(imm) << 20) | (rs1 << 15) | (2 << 12) | (rd << 7) | 0x03


def enc_jal(rd: int, offset: int) -> int:
    if offset % 2 or not -(1 << 20) <= offset < (1 << 20):
        raise ValueError(f"jal offset {offset} is not encodable")
    o = offset & 0x1FFFFF
    return ((((o >> 20) & 1) << 31) | (((o >> 1) & 0x3FF) << 21)
            | (((o >> 11) & 1) << 20) | (((o >> 12) & 0xFF) << 12)
            | (rd << 7) | 0x6F)


def _sx(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def reference_execute(mem: bytearray, pc: int, max_steps: int = 1000
                      ) -> Tuple[bytearray, List[int], int]:
    """Run the image in `mem` from `pc` until a `jal x0, 0` self-loop.

    Interprets exactly the encodings above (ADDI/ADD/SW/LW/JAL) and REFUSES any
    other word, so the answer is the ISA's, not a guess. Returns (memory,
    registers, steps)."""
    mem = bytearray(mem)
    x = [0] * 32
    for step in range(max_steps):
        if pc + 4 > len(mem):
            raise ValueError(f"pc {pc:#x} left the memory")
        w = int.from_bytes(mem[pc:pc + 4], "little")
        op, rd = w & 0x7F, (w >> 7) & 0x1F
        f3, rs1, rs2 = (w >> 12) & 7, (w >> 15) & 0x1F, (w >> 20) & 0x1F
        nxt = pc + 4
        if op == 0x13 and f3 == 0:
            val = (x[rs1] + _sx(w >> 20, 12)) & 0xFFFFFFFF
        elif op == 0x33 and f3 == 0 and (w >> 25) == 0:
            val = (x[rs1] + x[rs2]) & 0xFFFFFFFF
        elif op == 0x23 and f3 == 2:
            a = (x[rs1] + _sx(((w >> 25) << 5) | ((w >> 7) & 0x1F), 12)) \
                & 0xFFFFFFFF
            if a + 4 > len(mem) or a % 4:
                raise ValueError(f"store to {a:#x} is outside/misaligned")
            mem[a:a + 4] = x[rs2].to_bytes(4, "little")
            val, rd = None, 0
        elif op == 0x03 and f3 == 2:
            a = (x[rs1] + _sx(w >> 20, 12)) & 0xFFFFFFFF
            if a + 4 > len(mem) or a % 4:
                raise ValueError(f"load from {a:#x} is outside/misaligned")
            val = int.from_bytes(mem[a:a + 4], "little")
        elif op == 0x6F:
            off = _sx((((w >> 31) & 1) << 20) | (((w >> 12) & 0xFF) << 12)
                      | (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1),
                      21)
            val = nxt
            nxt = (pc + off) & 0xFFFFFFFF
            if off == 0:
                return mem, x, step
        else:
            raise ValueError(f"word {w:#010x} at {pc:#x} is not an encoding "
                             f"this interpreter models")
        if val is not None and rd:
            x[rd] = val
        pc = nxt
    raise ValueError(f"no self-loop within {max_steps} instructions")


def assemble(data_addr: int) -> List[Tuple[int, str]]:
    """The program: (word, listing) pairs. Absolute data addressing off x0."""
    a, b = OPERAND_A, OPERAND_B
    return [
        (enc_addi(1, 0, a), f"addi x1, x0, {a}"),
        (enc_addi(2, 0, b), f"addi x2, x0, {b}"),
        (enc_add(3, 1, 2), "add  x3, x1, x2"),
        (enc_sw(3, 0, data_addr), f"sw   x3, {data_addr:#x}(x0)"),
        (enc_lw(4, 0, data_addr), f"lw   x4, {data_addr:#x}(x0)"),
        (enc_add(5, 4, 1), "add  x5, x4, x1"),
        (enc_sw(5, 0, data_addr + 4), f"sw   x5, {data_addr + 4:#x}(x0)"),
        (enc_jal(0, 0), "jal  x0, 0        # park"),
    ]


# ---------------------------------------------------------------------------
# DESIGN FACTS — from the design input and the design's own declaration
# ---------------------------------------------------------------------------
def _json(path: Path) -> Optional[dict]:
    try:
        d = json.loads(Path(path).read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _declaration(project: Path) -> dict:
    d = _json(Path(project) / _DECLARATION_REL) or {}
    return d.get("fields") if isinstance(d.get("fields"), dict) else d


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = _HEX_RE.match(v)
        if m:
            return int(m.group(1).replace("_", ""), 16)
        m = _DEC_RE.match(v)
        if m:
            return int(m.group(1))
    return None


def isa_base(project: Path) -> Tuple[Optional[str], str]:
    """The ONE RV32 base the Phase-1 datasheet layer extracted, or a refusal."""
    l1 = _json(_pl.generated_docs_dir(project) / "L1_DATASHEET.json") or {}
    raw = l1.get("isa_base")
    toks = [raw] if isinstance(raw, str) else list(raw or [])
    toks = sorted({str(t).strip().upper() for t in toks if str(t).strip()})
    if not toks:
        return None, "the design input states no ISA base (L1.isa_base)"
    if len(toks) != 1:
        return None, f"the design input states {len(toks)} ISA bases {toks}"
    if toks[0] not in _RV32_BASES:
        return None, (f"ISA base {toks[0]} is not one this program is "
                      f"assembled for ({', '.join(_RV32_BASES)})")
    return toks[0], "L1_DATASHEET.isa_base"


def reset_vector(project: Path, decl: dict) -> Tuple[Optional[int], str]:
    core = decl.get("core_parameters")
    for where, src in (("declaration", decl),
                       ("declaration core_parameters",
                        core if isinstance(core, dict) else {})):
        for k in _RESET_PC_KEYS:
            v = _int(src.get(k))
            if v is not None:
                return v, f"{where} {k}"
    l8 = _json(_pl.generated_docs_dir(project) / "L8_RTL_CONSTANTS.json") or {}
    rows: List[dict] = []

    def _walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("name"), str):
                rows.append(o)
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
    _walk(l8)
    for r in rows:
        if str(r.get("name")).strip() in _RESET_PC_KEYS:
            v = _int(r.get("default", r.get("value")))
            if v is not None:
                return v, f"L8_RTL_CONSTANTS {r.get('name')}"
    return None, ("no reset vector declared (declaration reset_pc / "
                  "core_parameters RESET_PC, or an L8_RTL_CONSTANTS row)")


def sram_roles(decl: dict) -> Tuple[Optional[Dict[str, Any]], str]:
    """role -> port, read latency and register-file reservation, as DECLARED."""
    si = decl.get("sram_interface")
    if not isinstance(si, dict):
        return None, ("the declaration states no `sram_interface` role map, so "
                      "no memory port can be bound without guessing from names")
    low = {str(k).strip().lower(): v for k, v in si.items()}
    roles: Dict[str, str] = {}
    for role, keys in _ROLE_KEYS.items():
        for k in keys:
            v = low.get(k)
            if isinstance(v, str) and _ID_RE.match(v.strip()):
                roles[role] = v.strip()
                break
    for need in ("raddr", "wdata", "rdata", "we"):
        if need not in roles:
            return None, (f"the declared sram_interface names no {need} port")
    lat = next((_int(low.get(k)) for k in _LATENCY_KEYS
                if _int(low.get(k)) is not None), None)
    if lat is None or lat < 0:
        return None, ("the declared sram_interface states no non-negative "
                      "read latency")
    rf = next((_int(low.get(k)) for k in _RF_KEYS
               if _int(low.get(k)) is not None), None)
    return {"ports": roles, "read_latency": lat, "rf_reserved": rf}, \
        "declaration sram_interface"


#: A memory-size parameter, by the vocabulary cores use for it. Only the
#: parameters the delivered top actually declares are read.
_MEM_PARAM_RE = re.compile(
    r"^(?:mem(?:ory)?_?size(?:_?bytes)?|mem_?bytes|s?ram_?size(?:_?bytes)?)$",
    re.IGNORECASE)
_PARAM_NAME_RE = re.compile(
    r"\bparameter\b(?:\s+(?:integer|int|logic|bit|reg|signed|unsigned))*"
    r"\s*(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)\s*=")


def elaborated_memory(project: Path, dut_module: str, memsize: int,
                      decl: dict, top_text: Optional[str] = None
                      ) -> Tuple[Optional[Dict[str, Any]], str]:
    """The memory-size parameter the delivered top ELABORATES, checked against
    the declared `memsize_bytes` -- or a refusal naming the mismatch.

    Review wave 58 (S5DP): the builder took the delivered size from the
    declaration alone. The same check `_l10_execution.isa_conformance_credit`
    makes is made here: the RTL default (or the chip top's instance override
    of it) and `core_parameters` must equal it. A core with no memory-size
    parameter has nothing to disagree with and says so."""
    import _l10_execution as _l10x
    rtl = _pl.rtl_dir(project)
    files = sorted(list(rtl.glob("*.v")) + list(rtl.glob("*.sv"))) \
        if rtl.is_dir() else []
    head = re.compile(r"\bmodule\s+" + re.escape(dut_module)
                      + r"\b(.*?)\bendmodule\b", re.S)
    names: List[str] = []
    for f in files:
        m = head.search(_l10x._HDL_COMMENT_RE.sub(
            " ", f.read_text(errors="replace")))
        if m:
            names = [n for n in _PARAM_NAME_RE.findall(m.group(1))
                     if _MEM_PARAM_RE.match(n)]
            break
    core = decl.get("core_parameters")
    core = core if isinstance(core, dict) else {}
    names += [k for k in core if _MEM_PARAM_RE.match(str(k))
              and k not in names]
    if not names:
        return {"parameter": None, "basis": (
            f"`{dut_module}` declares no memory-size parameter; the delivered "
            f"size is the declaration's {memsize}")}, "no memory parameter"
    over: Dict[str, str] = {}
    if top_text:
        im = re.search(r"\b" + re.escape(dut_module)
                       + r"\s*#\s*\((.*?)\)\s*[A-Za-z_]\w*\s*\(",
                       _l10x._HDL_COMMENT_RE.sub(" ", top_text), re.S)
        if im:
            over = {a: b.strip() for a, b in re.findall(
                r"\.\s*([A-Za-z_]\w*)\s*\(([^()]*)\)", im.group(1))}
    rows = []
    for n in names:
        default, where = _l10x._module_parameter_default(files, dut_module, n)
        value = over.get(n, default)
        got = _l10x._int_literal(value) if value is not None else None
        if n in core and _l10x._int_literal(core.get(n)) != memsize:
            return None, (f"the declaration states core_parameters {n}="
                          f"{core.get(n)!r}, not its memsize_bytes {memsize}")
        if value is None and n not in core:
            continue
        if value is not None and got is None:
            return None, (f"the elaborated {n} ({value!r}) does not resolve to "
                          f"a number, so the delivered memory size is unknown")
        if got is not None and got != memsize:
            return None, (
                f"the delivered top elaborates {n}={got} ("
                + ("chip-top instance override" if n in over
                   else f"RTL default in {where}")
                + f"), but the declaration states memsize_bytes={memsize}: "
                f"the testbench would model a memory the die does not have")
        rows.append({"parameter": n, "elaborated": got,
                     "source": ("chip-top override" if n in over
                                else f"RTL default ({where})")})
    return {"parameter": rows}, "memory parameter matches the declaration"


def design_facts(project: Path, dut_module: str,
                 ports: List[Tuple[str, str, str]],
                 top_text: Optional[str] = None
                 ) -> Tuple[Optional[Dict[str, Any]], str]:
    """Everything the image and the testbench need, or the first refusal."""
    project = Path(project)
    base, why = isa_base(project)
    if base is None:
        return None, why
    decl = _declaration(project)
    if not decl:
        return None, f"no {_DECLARATION_REL}"
    memsize = _int(decl.get("memsize_bytes"))
    if not memsize or memsize <= 0:
        return None, "the declaration states no delivered memsize_bytes"
    clk = decl.get("clock_port_name")
    pol = str(decl.get("reset_polarity") or "").strip().lower()
    if not (isinstance(clk, str) and _ID_RE.match(clk)):
        return None, "the declaration states no clock_port_name"
    if pol not in ("active_high", "active_low"):
        return None, f"declaration reset_polarity {pol!r} is not active_high/low"
    sram, why = sram_roles(decl)
    if sram is None:
        return None, why
    mem_param, why = elaborated_memory(project, dut_module, memsize, decl,
                                       top_text)
    if mem_param is None:
        return None, why
    rv, rv_src = reset_vector(project, decl)
    if rv is None:
        return None, rv_src
    pmap = {n: (str(d or "").strip().lower(), str(w or "")) for d, w, n in ports}
    widths: Dict[str, int] = {}
    for role, name in sram["ports"].items():
        want = "input" if role == "rdata" else "output"
        if name not in pmap:
            return None, (f"the declared {role} port `{name}` is not a port of "
                          f"`{dut_module}`")
        if not pmap[name][0].startswith(want):
            return None, (f"the declared {role} port `{name}` is not an "
                          f"{want} of `{dut_module}`")
        m = re.match(r"^\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*$", pmap[name][1])
        widths[role] = (abs(int(m.group(1)) - int(m.group(2))) + 1) if m \
            else (1 if not pmap[name][1].strip() else 0)
        if widths[role] == 0:
            return None, (f"the width of `{name}` ({pmap[name][1]!r}) does not "
                          f"resolve to a number")
    if widths["wdata"] != 8 or widths["rdata"] != 8:
        return None, ("the declared memory port is not byte-wide "
                      f"(write {widths['wdata']}, read {widths['rdata']} bit); "
                      "a word-SRAM model is not implemented")
    need_aw = max(1, (memsize - 1).bit_length())
    for role in ("raddr", "waddr"):
        if role in widths and widths[role] < need_aw:
            return None, (f"the {role} port is {widths[role]} bit, too narrow "
                          f"for the declared {memsize}-byte memory")
    for role in ("we", "ren"):
        if role in widths and widths[role] != 1:
            return None, f"the {role} port is not a single bit"
    rst = [n for n, (d, _w) in pmap.items()
           if d.startswith("input") and n != clk
           and n not in sram["ports"].values()
           and re.search(r"(?:^|_)(?:rst|reset)(?:_?n|_b)?(?:$|_)", n, re.I)]
    if clk not in pmap or not pmap[clk][0].startswith("input"):
        return None, f"clock port `{clk}` is not an input of `{dut_module}`"
    if len(rst) != 1:
        return None, f"the reset input of `{dut_module}` is not unique: {rst}"
    ties = [n for n, (d, _w) in pmap.items()
            if d.startswith("input") and n not in (clk, rst[0])
            and n not in sram["ports"].values()]
    rf = sram["rf_reserved"]
    rf_src = "declaration sram_interface"
    if rf is None:
        if str(decl.get("rf_storage") or "").strip().lower() == "shared_sram":
            rf, rf_src = 32 * 4, ("declaration rf_storage shared_sram: 32 "
                                  "registers x 4 bytes at the top")
        else:
            rf, rf_src = 0, "no register file in the SRAM is declared"
    return {
        "isa_base": base, "memsize": memsize, "clock": clk, "reset": rst[0],
        "reset_active_high": pol == "active_high", "tie_low_inputs": ties,
        "ports": dict(sram["ports"]), "widths": widths,
        "read_latency": sram["read_latency"], "reset_pc": rv,
        "reset_pc_source": rv_src, "rf_reserved": rf, "rf_source": rf_src,
        "memory_parameter": mem_param,
    }, "design facts from L1.isa_base, the declaration and the RTL ports"


# ---------------------------------------------------------------------------
# BUILD — image + testbench
# ---------------------------------------------------------------------------
def build(project: Path, dut_module: str, ports: List[Tuple[str, str, str]],
          name: str = CASE_NAME, top_text: Optional[str] = None
          ) -> Tuple[Optional[Dict[str, Any]], str]:
    """{tb, hex, program, expected, facts} or (None, refusal). Deterministic:
    the gate calls it again and compares bytes. `top_text` is the full-stack
    top's source, whose instance override of the memory parameter wins."""
    facts, why = design_facts(project, dut_module, ports, top_text)
    if facts is None:
        return None, why
    ms, base, rf = facts["memsize"], facts["reset_pc"], facts["rf_reserved"]
    top_free = ms - rf
    prog_len = len(assemble(0)) * 4
    data = ((base + prog_len + 15) // 16) * 16 + 16
    if base % 4 or base + prog_len > top_free:
        return None, (f"the program ({prog_len} bytes at the reset vector "
                      f"{base:#x}) does not fit below the register-file "
                      f"reservation at {top_free:#x}")
    if data + 8 > top_free or data > 2047 - 4:
        return None, (f"no data word fits between the program and the "
                      f"register-file reservation ({data:#x}..{top_free:#x})")
    prog = assemble(data)
    mem = bytearray([FILL_BYTE] * ms)
    for i, (w, _t) in enumerate(prog):
        mem[base + 4 * i: base + 4 * i + 4] = w.to_bytes(4, "little")
    after, _regs, steps = reference_execute(mem, base)
    expected = [int.from_bytes(after[data:data + 4], "little"),
                int.from_bytes(after[data + 4:data + 8], "little")]
    hex_lines = [f"@{base:08x}"]
    for w, _t in prog:
        hex_lines += [f"{b:02x}" for b in w.to_bytes(4, "little")]
    hex_text = "\n".join(hex_lines) + "\n"
    tb = _emit_tb(name, dut_module, facts, data, expected, prog_len)
    return {
        "name": name, "tb_text": tb, "hex_name": f"{name}.hex",
        "hex_text": hex_text,
        "program": [{"addr": f"{base + 4 * i:#06x}", "word": f"{w:#010x}",
                     "asm": t} for i, (w, t) in enumerate(prog)],
        "data_address": data, "expected_words": [f"{e:#010x}" for e in
                                                 expected],
        "reference_steps": steps, "facts": facts,
        "delivered_memsize_bytes": ms,
    }, "built"


def _emit_tb(name: str, dut: str, f: Dict[str, Any], data: int,
             expected: List[int], prog_len: int) -> str:
    p, lat, ms = f["ports"], int(f["read_latency"]), int(f["memsize"])
    aw = max(1, (ms - 1).bit_length())
    raw = int(f["widths"]["raddr"])
    waw = int(f["widths"].get("waddr", raw))
    on, off = ("1'b1", "1'b0") if f["reset_active_high"] else ("1'b0", "1'b1")
    conns = [f".{f['clock']}(clk)", f".{f['reset']}(rst)",
             f".{p['raddr']}(raddr)", f".{p['wdata']}(wdata)",
             f".{p['rdata']}(rdata)", f".{p['we']}(we)"]
    if "waddr" in p:
        conns.append(f".{p['waddr']}(waddr)")
    if "ren" in p:
        conns.append(f".{p['ren']}(ren)")
    conns += [f".{t}(1'b0)" for t in f["tie_low_inputs"]]
    waddr_decl = (f"  wire [{waw - 1}:0] waddr;" if "waddr" in p
                  else f"  wire [{raw - 1}:0] waddr = raddr;")
    ren_decl = "  wire ren;" if "ren" in p else "  wire ren = 1'b1;"
    # A continuous-read SRAM has no clocked read pipeline. Keep writes and
    # the enable-qualified address / fetch scoreboard on the rising edge for
    # both protocols; only the memory's read-data timing changes.
    if lat == 0:
        read_decl = ""
        read_capture = ""
        read_init = ""
        read_logic = """  // Continuous read data; writes still occur at the rising edge.
  always @* begin
    rdata = 8'h00;
    if (ren === 1'b1 && (^raddr !== 1'bx) && raddr < MEMSIZE)
      rdata = mem[raddr];
  end
"""
    else:
        read_decl = "  reg [7:0] rpipe [0:LAT-1];"
        read_capture = "          rpipe[0] <= mem[raddr];"
        read_init = "    for (i = 0; i < LAT; i = i + 1) rpipe[i] = 8'h00;"
        read_logic = """  generate if (LAT > 1) begin : g_pipe
    genvar k;
    for (k = 1; k < LAT; k = k + 1) begin : g_stage
      always @(posedge clk) rpipe[k] <= rpipe[k-1];
    end
  end endgenerate
  always @* rdata = rpipe[LAT-1];
"""
    rf_lo = ms - int(f["rf_reserved"])
    e0, e1 = expected
    return f"""// VIBEIC_TB_ORACLE: GENERATED by cpu_datapath_program
// CPU data-path case (R-0929-STEP5-BAR): a real {f['isa_base']} program --
// fetch from the reset vector, execute, store, load back, store -- over a
// byte SRAM of exactly the delivered {ms} bytes. The image is assembled by
// the flow (`{name}.hex`); the expected words come from the flow's reference
// interpreter of the same encodings, never from the design.
`timescale 1ns/1ps
module {name};
  localparam integer MEMSIZE = {ms};
  localparam integer RESET_PC = {int(f['reset_pc'])};
  localparam integer DATA = {data};
  localparam integer PROG_LEN = {prog_len};
  localparam integer RF_LO = {rf_lo};
  localparam integer LAT = {lat};
  localparam integer CYCLE_CAP = {CYCLE_CAP};
  localparam [31:0] EXP0 = 32'h{e0:08x};
  localparam [31:0] EXP1 = 32'h{e1:08x};
  reg clk = 1'b0;
  reg rst = {on};
  reg released = 1'b0;
  always #5 clk = ~clk;
  wire [{raw - 1}:0] raddr;
{waddr_decl}
  wire [7:0] wdata;
  wire we;
{ren_decl}
  reg [7:0] rdata = 8'h00;
  reg [7:0] mem [0:MEMSIZE-1];
{read_decl}
  reg [7:0] lane_written;
  // Every byte of the image, from the reset vector on, must be presented on
  // the read address (enable-qualified when a read enable exists): an address
  // idling at the reset vector is not a fetch of the program (review wave 58).
  reg [PROG_LEN-1:0] fetched_bytes;
  integer i, cyc, settle, stray, oob, xctl, xdat, fetched, npass;
  {dut} u_dut ({', '.join(conns)});
  // Clocked writes and enable-qualified request / fetch monitoring. Read
  // data follows the declaration's LAT protocol below. Nothing is judged
  // while in reset.
  always @(posedge clk) begin
    if (released) begin
      if (we === 1'bx || we === 1'bz || ren === 1'bx || ren === 1'bz)
        xctl = xctl + 1;
      if (ren === 1'b1) begin
        if (^raddr === 1'bx || raddr >= MEMSIZE) oob = oob + 1;
        else begin
{read_capture}
          if (raddr >= RESET_PC && raddr < RESET_PC + PROG_LEN)
            fetched_bytes[raddr - RESET_PC] = 1'b1;
        end
      end
      if (we === 1'b1) begin
        if (^waddr === 1'bx || waddr >= MEMSIZE) oob = oob + 1;
        else begin
          if (^wdata === 1'bx) xdat = xdat + 1;
          mem[waddr] <= wdata;
          if (waddr >= DATA && waddr < DATA + 8)
            lane_written[waddr - DATA] = 1'b1;
          else if (waddr < RF_LO) stray = stray + 1;
        end
      end
    end
  end
{read_logic}
  function [31:0] word_at(input integer a);
    word_at = {{mem[a+3], mem[a+2], mem[a+1], mem[a]}};
  endfunction
  initial begin
    stray = 0; oob = 0; xctl = 0; xdat = 0; fetched = 0; npass = 0;
    settle = 0; lane_written = 8'h00; fetched_bytes = {{PROG_LEN{{1'b0}}}};
    for (i = 0; i < MEMSIZE; i = i + 1) mem[i] = 8'h{FILL_BYTE:02x};
{read_init}
    $readmemh("{name}.hex", mem);
    repeat ({RESET_HOLD_CYCLES}) @(posedge clk);
    @(negedge clk);
    rst = {off};
    released = 1'b1;
    for (cyc = 0; cyc < CYCLE_CAP && settle < {SETTLE_CYCLES};
         cyc = cyc + 1) begin
      @(posedge clk);
      #1;
      if (word_at(DATA + 4) === EXP1 && lane_written[7:4] === 4'hf)
        settle = settle + 1;
    end
    $display("DATAPATH_TRACE cycles=%0d word0=%h word1=%h lanes=%b stray=%0d oob=%0d xctl=%0d xdat=%0d",
             cyc, word_at(DATA), word_at(DATA + 4), lane_written, stray, oob,
             xctl, xdat);
    fetched = (fetched_bytes === {{PROG_LEN{{1'b1}}}});
    if (fetched) npass = npass + 1;
    $display("DATAPATH_CHECK reset_vector_fetch %s (%0d of %0d image bytes read from the reset vector on)",
             fetched ? "PASS" : "MISS", $countones(fetched_bytes), PROG_LEN);
    if (word_at(DATA) === EXP0) npass = npass + 1;
    $display("DATAPATH_CHECK store_word %s (%h, expected %h)",
             word_at(DATA) === EXP0 ? "PASS" : "MISS", word_at(DATA), EXP0);
    if (word_at(DATA + 4) === EXP1) npass = npass + 1;
    $display("DATAPATH_CHECK load_store_word %s (%h, expected %h)",
             word_at(DATA + 4) === EXP1 ? "PASS" : "MISS", word_at(DATA + 4),
             EXP1);
    if (lane_written === 8'hff) npass = npass + 1;
    $display("DATAPATH_CHECK byte_lanes_written %s (%b)",
             lane_written === 8'hff ? "PASS" : "MISS", lane_written);
    if (stray == 0 && oob == 0 && xctl == 0 && xdat == 0) npass = npass + 1;
    $display("DATAPATH_CHECK write_discipline %s (stray=%0d oob=%0d xctl=%0d xdat=%0d)",
             (stray == 0 && oob == 0 && xctl == 0 && xdat == 0) ? "PASS" : "MISS",
             stray, oob, xctl, xdat);
    $display("ORACLE_TB_DONE pass=%0d/{len(CHECKS)}", npass);
    if (npass == {len(CHECKS)})
      $display("[TB {name}] PASS — {f['isa_base']} fetch/execute/store/load over the delivered %0d-byte SRAM", MEMSIZE);
    else
      $display("[TB {name}] FAIL — %0d of {len(CHECKS)} data-path check(s) held", npass);
    $finish;
  end
endmodule
"""
