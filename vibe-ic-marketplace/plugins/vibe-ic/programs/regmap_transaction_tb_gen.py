#!/usr/bin/env python3
"""regmap_transaction_tb_gen.py — ORGANIC #186 part 2.

Deterministic, chip-AGNOSTIC **register-map transaction driver** for a
memory-mapped-IO top.  Closes the half of #186 that a byte-stream
`full_stack_tb_gen` structurally cannot reach: for an IC whose L3 declares NO
opcode/byte protocol but whose L4/L5 DO declare a register file, the emitted
full-stack TB drove nothing at all (`drive_byte` is a no-op without an inout
pad, the opcode list is empty), so `functional_coverage.scored_with_golden`
was 0 by construction no matter how correct the RTL was.

WHAT IS SCORED — AND WHY IT IS NOT A WEAKENED "FUNCTIONAL VECTOR"
-----------------------------------------------------------------
Every scored vector here compares a REAL simulated `read_data` and can
genuinely FAIL on a buggy design.  But the two qualifying oracle classes do
NOT draw their expected value from the same place, and that difference is
load-bearing enough to be counted separately (see `scored_with_golden` vs
`scored_self_referential` below):

  * `rw_storage_fixed_point` compares against a value derived from the DESIGN
    DOCUMENTS — golden-scored evidence.
  * `ro_write_ignore` compares against the DESIGN'S OWN baseline read. It is a
    SELF-CONSISTENCY oracle. MEASURED on a published design: forcing all nine
    `read_data` assignments to one constant left it at 12 of 12 PASS, i.e. a
    completely dead read path scored exactly as a correct one. It is real
    evidence of one specific property and it is NOT golden-scored coverage.

A third class is deliberately REFUSED.

  (1) ``ro_write_ignore`` — the docs declare the register READ-ONLY.  Golden:
      a write must not change what the register reads back.  Sequence:
      read, read (stability probe), write ~value, read.  Expected == the
      stable baseline; actual == the post-write read.  FAILS for real when the
      address decoder routes writes into read-only address space, a classic
      register-file defect.  The stability probe means a hardware-updated
      ("volatile") read-only register is reported UNVERIFIED instead of being
      scored against a golden that does not exist.

  (2) ``rw_storage_fixed_point`` — the docs declare the register R/W.  Golden:
      whatever the register reads back after a write is a settled, legal state,
      so writing THAT value back must reproduce it.  Sequence: write pattern,
      read a1, write a1, read a2; expected == a1, actual == a2.  FAILS for real
      when a register does not hold, when a write strobe corrupts neighbouring
      bits, or when two addresses alias.  Guarded against VACUITY: the vector is
      only scored when a second, different pattern reads back DIFFERENTLY
      (proving at least one bit is genuinely observable storage); an
      unresponsive address is reported UNVERIFIED, never scored.

  (3) REFUSED — naive whole-register write/read-back (`write V then expect to
      read V`).  MEASURED on real repo data: a correct register file with
      documented self-clearing command bits and read-as-zero reserved bits
      returns a DIFFERENT value by design (an all-ones write to a control
      register whose only storage bit is a mode select reads back just that
      bit).  Scoring it would FAIL correct silicon, so it is not scored.

  Also NOT synthesizable here, and honestly reported as such: the RESULT
  oracle of an algorithm-defined operation (write operand registers, kick a
  command, poll status, read the computed result).  The stimulus is
  synthesizable; the expected result is defined by the IC's algorithm, which no
  deterministic generator can fabricate.  That stays the `cap:` deferral the
  professional-TB / reference-TB paths already declare.

Registers come from the design's OWN documents: the structured
`L4_REGMAP.json` (synthesised address-range ENDPOINT pseudo-entries excluded —
their access class is a synthesis default, not a documented declaration) plus
the authored L4/L5 markdown register table, parsed by grammar (a hex address
cell + a bare access-keyword cell), exactly the way #186 part 1 treats the
authored L3 markdown port table as authoritative.

chip-AGNOSTIC: bus roles come from a closed set of standard interface role
spellings (the same lexicon shape `professional_tb_gen._is_register_mapped`
already uses); registers come from the project's own documents.  No chip,
vendor or SKU literal anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _watchdog
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl              # noqa: E402
import reset_clock_variant_alias as _rcv  # noqa: E402


# ---------------------------------------------------------------------------
# Bus-role lexicon (chip-AGNOSTIC — standard interface role spellings only)
# ---------------------------------------------------------------------------
_ADDR_TOKENS = frozenset({"addr", "address", "paddr", "haddr", "awaddr",
                          "araddr", "adr"})
_WDATA_TOKENS = frozenset({"wdata", "writedata", "din", "datain",
                           "pwdata", "hwdata"})
_RDATA_TOKENS = frozenset({"rdata", "readdata", "dout", "dataout",
                           "prdata", "hrdata"})
# Two-component spellings (`write_data` / `read_data`) carry the same role as
# the fused single-token spellings above.
_WDATA_PAIRS = (frozenset({"write", "data"}),)
_RDATA_PAIRS = (frozenset({"read", "data"}),)
_WE_PAIRS = (frozenset({"write", "enable"}), frozenset({"write", "en"}))
_CS_TOKENS = frozenset({"cs", "csb", "csn", "ncs", "chipselect", "sel",
                        "psel", "en", "enable", "ce", "cen", "valid", "req"})
_WE_TOKENS = frozenset({"we", "wen", "web", "wr", "pwrite", "hwrite", "rw",
                        "wnr"})
# Names whose polarity is INVERTED (asserted low).  Kept tiny and explicit so a
# mis-drive can never be silent.
_ACTIVE_LOW_SUFFIXES = ("_n", "_b", "n", "b")


def _comps(name: str) -> set:
    """Whole-word components of a signal name (split on _/digits/non-word)."""
    return {c for c in re.split(r"[_\W0-9]+", str(name).lower()) if c}


def _active_low(name: str) -> bool:
    n = str(name).lower()
    if n.endswith(("_n", "_b")):
        return True
    # bare `csn` / `csb` / `web` style
    return any(n.endswith(s) and n[:-len(s)] in
               (_CS_TOKENS | _WE_TOKENS) for s in _ACTIVE_LOW_SUFFIXES)


def detect_register_bus(ports: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Resolve the memory-mapped register-bus ROLES on a top port list.

    `ports` items are dicts with `name` / `direction` / `width` (int, >=1).
    Returns None unless the shape is unambiguously a register bus: exactly one
    address input bus, one read-data output bus, one write-data input bus, and
    a write-direction control (write-enable, or a combined read/write line).
    A chip-select is optional (an always-enabled slave is legal).

    chip-AGNOSTIC: role spellings only, no chip literal.
    """
    ins = [p for p in ports if str(p.get("direction")) == "input"]
    outs = [p for p in ports if str(p.get("direction")) == "output"]

    def pick(cands, tokens, pairs=(), *, multibit=None):
        hit = [p for p in cands
               if (_comps(p["name"]) & tokens)
               or any(pr <= _comps(p["name"]) for pr in pairs)]
        if multibit is True:
            hit = [p for p in hit if int(p.get("width") or 1) > 1]
        if multibit is False:
            hit = [p for p in hit if int(p.get("width") or 1) == 1]
        return hit[0] if len(hit) == 1 else None

    addr = pick(ins, _ADDR_TOKENS, multibit=True)
    rdata = pick(outs, _RDATA_TOKENS, _RDATA_PAIRS, multibit=True)
    wdata = pick(ins, _WDATA_TOKENS, _WDATA_PAIRS, multibit=True)
    if addr is None or rdata is None or wdata is None:
        return None
    we = pick(ins, _WE_TOKENS, _WE_PAIRS, multibit=False)
    if we is None:
        return None
    cs = pick(ins, _CS_TOKENS, multibit=False)

    clk = next((p for p in ins if _rcv.is_clock(p["name"])), None)
    rst = next((p for p in ins if _rcv.classify_reset(p["name"])), None)
    if clk is None:
        return None
    return {
        "clk": clk["name"],
        "reset": None if rst is None else rst["name"],
        "reset_active_low": bool(rst is not None
                                 and _rcv.classify_reset(rst["name"])
                                 == "active_low"),
        "address": addr["name"], "address_width": int(addr["width"]),
        "write_data": wdata["name"], "data_width": int(wdata["width"]),
        "read_data": rdata["name"],
        "we": we["name"], "we_active_low": _active_low(we["name"]),
        "cs": None if cs is None else cs["name"],
        "cs_active_low": bool(cs is not None and _active_low(cs["name"])),
    }


# ---------------------------------------------------------------------------
# Documented register map
# ---------------------------------------------------------------------------
# Access keywords, normalised.  A cell must be EXACTLY one of these (modulo
# markdown emphasis) for its row to count as a register-map row — the same
# "keyed on the VALUE column, so the header may be in any language" rule the
# #186 part-1 port-table reader uses.
_ACCESS_READ = frozenset({"r", "ro", "rc", "r/o", "read", "read-only",
                          "rw", "r/w", "rw1c", "r/w1c", "rwc", "r/wc"})
_ACCESS_WRITE = frozenset({"w", "wo", "w/o", "write", "write-only",
                           "rw", "r/w", "rw1c", "r/w1c", "rwc", "r/wc"})
_ACCESS_ANY = _ACCESS_READ | _ACCESS_WRITE

_MD_ROW_RE = re.compile(r"^[ \t]*\|(.+)\|[ \t]*$", re.MULTILINE)
_HEX_RE = re.compile(r"^0[xX]([0-9a-fA-F]+)$")
_HEX_RANGE_RE = re.compile(
    r"^0[xX]([0-9a-fA-F]+)\s*[-–~]\s*(?:0[xX])?([0-9a-fA-F]+)$")
_IDENT_RE = re.compile(r"^([A-Za-z_]\w*)")

# Layer documents whose register table is AUTHORITATIVE.  Keyed on the LAYER
# FILENAME (command-protocol / register-map layers), never on content, so a
# free-text prompt is never mistaken for a documented register map.
_REGMAP_DOC_GLOBS = (
    "phase1/input_doc/L4*", "phase1/input_doc/L5*",
    "input/docs/L4*", "input/docs/L5*",
)


def _norm_access(cell: str) -> Optional[str]:
    a = cell.strip().strip("`*_ ").lower()
    return a if a in _ACCESS_ANY else None


def access_can_read(access: str) -> bool:
    return str(access).strip().lower() in _ACCESS_READ


def access_can_write(access: str) -> bool:
    return str(access).strip().lower() in _ACCESS_WRITE


def parse_regmap_table(text: str) -> List[Dict[str, Any]]:
    """Registers from a MARKDOWN register table.

    A row qualifies only when (a) some cell is a bare hex address `0xNN` or a
    hex range `0xNN-0xMM`, and (b) some OTHER cell is a bare access keyword.
    An address RANGE whose name cell enumerates the same number of indexed
    names (`BLOCK0 ~ BLOCK15`) expands to one entry per address.  Rows with a
    range but no matching enumeration expand with an index suffix.

    chip-AGNOSTIC: markdown grammar + the closed access-keyword set.
    """
    out: List[Dict[str, Any]] = []
    for m in _MD_ROW_RE.finditer(text):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 3:
            continue
        addr_lo = addr_hi = None
        addr_idx = -1
        for i, c in enumerate(cells):
            bare = c.strip().strip("`*_ ")
            hit = _HEX_RE.match(bare)
            if hit:
                addr_lo = addr_hi = int(hit.group(1), 16)
                addr_idx = i
                break
            rng = _HEX_RANGE_RE.match(bare)
            if rng:
                addr_lo = int(rng.group(1), 16)
                addr_hi = int(rng.group(2), 16)
                addr_idx = i
                break
        if addr_lo is None or addr_hi < addr_lo:
            continue
        access = None
        for i, c in enumerate(cells):
            if i == addr_idx:
                continue
            a = _norm_access(c)
            if a:
                access = a
                break
        if access is None:
            continue
        name = ""
        for i, c in enumerate(cells):
            if i == addr_idx or _norm_access(c):
                continue
            hit = _IDENT_RE.match(c.strip().strip("`*_ "))
            if hit:
                name = hit.group(1)
                break
        span = addr_hi - addr_lo + 1
        if span == 1:
            out.append({"address_int": addr_lo, "name": name,
                        "access": access, "source": "doc_table"})
        else:
            base = re.sub(r"\d+$", "", name) or "REG"
            for k in range(span):
                out.append({"address_int": addr_lo + k,
                            "name": f"{base}{k}", "access": access,
                            "source": "doc_table"})
    return out


def _l4_json_registers(project: Path) -> List[Dict[str, Any]]:
    """Real registers from the structured L4 register-map JSON.

    Synthesised address-RANGE ENDPOINT pseudo-entries (`kind ==
    'indexed_register_address'`) are EXCLUDED: their access class is a
    synthesis default, not a documented per-register declaration.  MEASURED
    why this matters — on real repo data such an endpoint carried access `RO`
    for an address the documents declare write-only, so scoring it as
    read-only would FAIL a correct design.
    """
    out: List[Dict[str, Any]] = []
    p = _pl.generated_docs_dir(project) / "L4_REGMAP.json"
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return out
    for r in (data.get("registers") or []):
        if not isinstance(r, dict):
            continue
        if r.get("kind") == "indexed_register_address":
            continue
        acc = _norm_access(str(r.get("access") or ""))
        if acc is None:
            continue
        a = r.get("address_int")
        if not isinstance(a, int):
            try:
                a = int(str(r.get("address") or ""), 16)
            except ValueError:
                continue
        out.append({"address_int": a, "name": str(r.get("name") or ""),
                    "access": acc, "source": "L4_REGMAP.json"})
    return out


def _doc_table_registers(project: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for glob in _REGMAP_DOC_GLOBS:
        for f in sorted(project.glob(glob)):
            if not f.is_file():
                continue
            try:
                out.extend(parse_regmap_table(f.read_text(errors="ignore")))
            except OSError:
                continue
    return out


def load_documented_registers(project: Path) -> List[Dict[str, Any]]:
    """The documented register map, keyed by address.

    The authored markdown table wins over the structured JSON on a conflict:
    the JSON is a downstream extraction of that very table (the same ranking
    #186 part 1 applies to the L3 port table).
    """
    by_addr: Dict[int, Dict[str, Any]] = {}
    for r in _l4_json_registers(project):
        by_addr.setdefault(r["address_int"], r)
    for r in _doc_table_registers(project):
        by_addr[r["address_int"]] = r
    return [by_addr[a] for a in sorted(by_addr)]


# ---------------------------------------------------------------------------
# Testbench emission
# ---------------------------------------------------------------------------
# Probe steps, in emission order:
#   r0 — baseline read
#   r1 — immediate re-read (stability probe: is this register hardware-updated?)
#   p1 — read back after writing the complement of the baseline
#   p2 — read back after writing the baseline again (a SECOND, different pattern)
#   fp — read back after writing p2 (fixed-point probe on a settled value)
_PROBE_STEPS = ("r0", "r1", "p1", "p2", "fp")


def emit_tb(top_module: str, bus: Dict[str, Any],
            ports: List[Dict[str, Any]],
            registers: List[Dict[str, Any]]) -> str:
    """Emit a self-describing register-map transaction TB.

    The TB makes OBSERVATIONS only (a machine-parseable transcript); all
    scoring policy lives in `score_transcript` so it is unit-testable in
    Python and cannot drift between the TB text and the verdict.

    Probe order puts every read-only register FIRST: a write to a command
    register can legitimately change a status register, and probing status
    afterwards would make the flow attribute that to the design.
    """
    dw = int(bus["data_width"])
    aw = int(bus["address_width"])
    lines: List[str] = [
        "// Auto-generated register-map transaction TB — ORGANIC #186 part 2.",
        "// Drives real bus transactions derived from the design's OWN",
        "// documented register map; emits an observation transcript that",
        "// regmap_transaction_tb_gen.score_transcript scores against",
        "// doc-derived goldens. chip-AGNOSTIC.",
        "`timescale 1ns / 1ps",
        f"module tb_{top_module}_regmap;",
        f"  reg {bus['clk']} = 0;",
        f"  always #5 {bus['clk']} = ~{bus['clk']};",
    ]
    inst: List[str] = [f"    .{bus['clk']}({bus['clk']})"]
    driven = {bus["clk"]}
    for role in ("reset", "address", "write_data", "we", "cs"):
        nm = bus.get(role)
        if not nm:
            continue
        w = aw if role == "address" else (dw if role == "write_data" else 1)
        lines.append(f"  reg [{w - 1}:0] {nm} = 0;" if w > 1
                     else f"  reg {nm} = 0;")
        inst.append(f"    .{nm}({nm})")
        driven.add(nm)
    lines.append(f"  wire [{dw - 1}:0] {bus['read_data']};")
    inst.append(f"    .{bus['read_data']}({bus['read_data']})")
    driven.add(bus["read_data"])
    # Every remaining top port must still bind: inputs tied inactive, outputs
    # observed on a fresh wire.  A TB that silently omits a port would not
    # elaborate.
    for p in ports:
        nm = p["name"]
        if nm in driven:
            continue
        w = int(p.get("width") or 1)
        decl = f"[{w - 1}:0] " if w > 1 else ""
        if p.get("direction") == "input":
            lines.append(f"  reg {decl}{nm} = 0;")
        else:
            lines.append(f"  wire {decl}{nm};")
        inst.append(f"    .{nm}({nm})")
    lines.append("")
    lines.append(f"  {top_module} u_dut (")
    lines.append(",\n".join(inst))
    lines.append("  );")
    lines.append("")
    lines.append(f"  reg [{dw - 1}:0] obs;")
    lines.append("  integer k;")
    cs_on, cs_off = ("1'b0", "1'b1") if bus["cs_active_low"] else ("1'b1", "1'b0")
    we_on, we_off = ("1'b0", "1'b1") if bus["we_active_low"] else ("1'b1", "1'b0")
    csn, wen = bus.get("cs"), bus["we"]

    def _set_cs(v):
        return [f"      {csn} = {v};"] if csn else []

    # write task
    lines.append("  task bus_write;")
    lines.append(f"    input [{aw - 1}:0] a;")
    lines.append(f"    input [{dw - 1}:0] d;")
    lines.append("    begin")
    lines.append(f"      @(negedge {bus['clk']});")
    lines.append(f"      {bus['address']} = a; {bus['write_data']} = d;")
    lines.extend(_set_cs(cs_on))
    lines.append(f"      {wen} = {we_on};")
    lines.append(f"      @(negedge {bus['clk']});")
    lines.extend(_set_cs(cs_off))
    lines.append(f"      {wen} = {we_off};")
    lines.append("    end")
    lines.append("  endtask")
    lines.append("")
    # read task — holds the access for two clocks so a 1- or 2-cycle read
    # latency both land on a settled value.
    lines.append("  task bus_read;")
    lines.append(f"    input [{aw - 1}:0] a;")
    lines.append("    begin")
    lines.append(f"      @(negedge {bus['clk']});")
    lines.append(f"      {bus['address']} = a;")
    lines.extend(_set_cs(cs_on))
    lines.append(f"      {wen} = {we_off};")
    lines.append(f"      @(posedge {bus['clk']});")
    lines.append(f"      @(posedge {bus['clk']}); #1;")
    lines.append(f"      obs = {bus['read_data']};")
    lines.append(f"      @(negedge {bus['clk']});")
    lines.extend(_set_cs(cs_off))
    lines.append("    end")
    lines.append("  endtask")
    lines.append("")
    lines.append("  task probe;")
    lines.append(f"    input [{aw - 1}:0] a;")
    lines.append(f"    reg [{dw - 1}:0] r0;")
    lines.append(f"    reg [{dw - 1}:0] p2;")
    lines.append("    begin")
    lines.append("      bus_read(a); r0 = obs;")
    lines.append('      $display("REGMAP_PROBE addr=%0d step=r0 data=%0d",'
                 " a, obs);")
    lines.append("      bus_read(a);")
    lines.append('      $display("REGMAP_PROBE addr=%0d step=r1 data=%0d",'
                 " a, obs);")
    lines.append("      bus_write(a, ~r0);")
    lines.append("      bus_read(a);")
    lines.append('      $display("REGMAP_PROBE addr=%0d step=p1 data=%0d",'
                 " a, obs);")
    lines.append("      bus_write(a, r0);")
    lines.append("      bus_read(a); p2 = obs;")
    lines.append('      $display("REGMAP_PROBE addr=%0d step=p2 data=%0d",'
                 " a, obs);")
    lines.append("      bus_write(a, p2);")
    lines.append("      bus_read(a);")
    lines.append('      $display("REGMAP_PROBE addr=%0d step=fp data=%0d",'
                 " a, obs);")
    lines.append("    end")
    lines.append("  endtask")
    lines.append("")
    lines.append("  initial begin")
    rst = bus.get("reset")
    if rst:
        lvl0, lvl1 = ("0", "1") if bus["reset_active_low"] else ("1", "0")
        lines.append(f"    {rst} = 1'b{lvl0};")
        lines.append("    repeat (4) @(negedge %s);" % bus["clk"])
        lines.append(f"    {rst} = 1'b{lvl1};")
        lines.append("    repeat (2) @(negedge %s);" % bus["clk"])
    # read-only registers first (see docstring)
    ordered = ([r for r in registers if not access_can_write(r["access"])]
               + [r for r in registers if access_can_write(r["access"])])
    for r in ordered:
        lines.append(f"    probe({aw}'d{r['address_int']});"
                     f"  // {r['name']} [{r['access']}]")
    lines.append('    $display("REGMAP_PROBE_DONE");')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("")
    lines.append("  initial begin")
    lines.append("    #2000000;")
    lines.append('    $display("REGMAP_PROBE_TIMEOUT");')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
_OBS_RE = re.compile(
    r"REGMAP_PROBE addr=(\d+) step=(r0|r1|p1|p2|fp) data=(\d+)")


def parse_transcript(text: str) -> Dict[int, Dict[str, int]]:
    obs: Dict[int, Dict[str, int]] = {}
    for m in _OBS_RE.finditer(text):
        obs.setdefault(int(m.group(1)), {})[m.group(2)] = int(m.group(3))
    return obs


def _hexs(v: int, width: int) -> str:
    return "0x%0*X" % (max(1, (width + 3) // 4), v)


def score_transcript(registers: List[Dict[str, Any]],
                     obs: Dict[int, Dict[str, int]],
                     data_width: int) -> List[Dict[str, Any]]:
    """Score the observation transcript into full-stack `per_vector` entries.

    A vector carries a CONCRETE golden (`expected_bytes`) only when a
    doc-derived golden genuinely exists; everything else is emitted
    UNVERIFIED with the reason, never scored.
    """
    out: List[Dict[str, Any]] = []
    for reg in registers:
        a = reg["address_int"]
        nm = reg.get("name") or ""
        acc = reg["access"]
        o = obs.get(a) or {}
        base = {
            "vector_id": f"regmap_{_hexs(a, 8)}_{nm}" if nm
                         else f"regmap_{_hexs(a, 8)}",
            "address": _hexs(a, 8),
            "register": nm,
            "access": acc,
            "evidence": reg.get("source", "documented register map"),
        }
        if not all(s in o for s in _PROBE_STEPS):
            out.append({**base, "kind": "regmap_probe",
                        "expected_bytes": None, "actual_bytes": None,
                        "verdict": "UNVERIFIED",
                        "source": "no simulated observation for this address"})
            continue
        readable = access_can_read(acc)
        writable = access_can_write(acc)
        if readable and not writable:
            if o["r0"] != o["r1"]:
                out.append({**base, "kind": "ro_write_ignore",
                            "expected_bytes": None, "actual_bytes": None,
                            "verdict": "UNVERIFIED",
                            "source": ("read-only register is hardware-"
                                       "updated between two back-to-back "
                                       "reads — no stable doc golden")})
                continue
            exp = _hexs(o["r0"], data_width)
            act = _hexs(o["p1"], data_width)
            out.append({**base, "kind": "ro_write_ignore",
                        "expected_bytes": exp, "actual_bytes": act,
                        "verdict": "PASS" if exp == act else "FAIL",
                        "source": ("doc access class is read-only: a write "
                                   "must not change the read-back value")})
            continue
        if writable and readable:
            if o["p1"] == o["p2"]:
                out.append({**base, "kind": "rw_storage_fixed_point",
                            "expected_bytes": None, "actual_bytes": None,
                            "verdict": "UNVERIFIED",
                            "source": ("two different written patterns read "
                                       "back identically — no observable "
                                       "storage to score")})
                continue
            exp = _hexs(o["p2"], data_width)
            act = _hexs(o["fp"], data_width)
            out.append({**base, "kind": "rw_storage_fixed_point",
                        "expected_bytes": exp, "actual_bytes": act,
                        "verdict": "PASS" if exp == act else "FAIL",
                        "source": ("doc access class is read/write: the "
                                   "settled read-back value must be a fixed "
                                   "point of write-then-read")})
            continue
        out.append({**base, "kind": "write_only",
                    "expected_bytes": None, "actual_bytes": None,
                    "verdict": "UNVERIFIED",
                    "source": ("doc access class is write-only — no read "
                               "golden exists for this address")})
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def _rtl_top_ports(rtl_dir: Path, top_module: str
                   ) -> Tuple[List[Dict[str, Any]], Optional[Path]]:
    for f in sorted(rtl_dir.glob("**/*.v")) + sorted(rtl_dir.glob("**/*.sv")):
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        parsed = _rcv.parse_module_ports(txt, top_module)
        if parsed:
            out = []
            for d, w, n in parsed:
                out.append({"name": n, "direction": d,
                            "width": _width_of(w)})
            return out, f
    return [], None


def _width_of(width_decl: str) -> int:
    if not width_decl:
        return 1
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", width_decl)
    if not m:
        return 0        # parametric / unresolved
    return abs(int(m.group(1)) - int(m.group(2))) + 1


def generate(project: Path, top_module: str,
             out_dir: Optional[Path] = None,
             run: bool = True) -> Dict[str, Any]:
    """Emit (and optionally simulate + score) the register-map transaction TB.

    Returns a status dict; `status` is one of
    ``scored`` / ``emitted`` / ``skipped``.  Never raises on a missing tool or
    an unsuitable design — an honest ``skipped`` with a reason instead.
    """
    rtl_dir = _pl.rtl_dir(project)
    out_dir = out_dir or _pl.sim_full_stack_dir(project)
    if not rtl_dir.is_dir():
        return {"status": "skipped", "reason": "no rtl/ directory"}
    ports, top_file = _rtl_top_ports(rtl_dir, top_module)
    if not ports:
        return {"status": "skipped",
                "reason": f"top module {top_module!r} has no parseable ports"}
    bus = detect_register_bus(ports)
    if bus is None:
        return {"status": "skipped",
                "reason": "top interface is not a memory-mapped register bus"}
    registers = load_documented_registers(project)
    if not registers:
        return {"status": "skipped",
                "reason": "no documented register map (L4/L5)"}
    out_dir.mkdir(parents=True, exist_ok=True)
    tb_path = out_dir / f"tb_{top_module}_regmap.v"
    tb_path.write_text(emit_tb(top_module, bus, ports, registers))
    info: Dict[str, Any] = {
        "status": "emitted", "tb": str(tb_path), "bus": bus,
        "registers_documented": len(registers),
        "registers_readable": sum(1 for r in registers
                                  if access_can_read(r["access"])),
    }
    if not run:
        return info
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        info["reason"] = "iverilog/vvp not on PATH — TB emitted, not simulated"
        return info
    srcs = sorted(str(p) for p in
                  list(rtl_dir.glob("**/*.v")) + list(rtl_dir.glob("**/*.sv")))
    work = out_dir / "_regmap_work"
    work.mkdir(parents=True, exist_ok=True)
    vvp_out = work / "regmap.vvp"
    # Supervised by FORWARD PROGRESS rather than a wall-clock ceiling: a big
    # register map is a legitimately long elaboration, and `timeout=300` kills
    # it for making progress. `loop_watchdog_compliance_check` flags this call
    # site (and only this one — `vvp` is not on the long-tool list) and it was
    # RED on main before this change.
    try:
        comp = _watchdog.run_supervised(
            ["iverilog", "-g2012", "-o", str(vvp_out), str(tb_path), *srcs])
    except (OSError, subprocess.SubprocessError) as e:
        info["reason"] = f"iverilog invocation failed: {e}"
        return info
    if comp.outcome != "natural":
        info["reason"] = (f"iverilog did not finish on its own "
                          f"({comp.outcome}) after {comp.elapsed_s:.0f}s")
        info["compile_log"] = (comp.err or "")[-2000:]
        return info
    if comp.rc != 0:
        info["reason"] = "TB did not elaborate against rtl/"
        info["compile_log"] = (comp.err or "")[-2000:]
        return info
    try:
        sim = subprocess.run(["vvp", str(vvp_out)],
                             capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        info["reason"] = f"vvp invocation failed: {e}"
        return info
    transcript = sim.stdout or ""
    (work / "regmap.log").write_text(transcript)
    # The compiled image is a build artefact, not evidence — the TB source and
    # the transcript are. Drop it so a published run carries no stray binary.
    try:
        vvp_out.unlink()
    except OSError:  # pragma: no cover — best effort
        pass
    if "REGMAP_PROBE_TIMEOUT" in transcript:
        info["reason"] = "simulation hit the probe watchdog"
    obs = parse_transcript(transcript)
    per_vector = score_transcript(registers, obs, int(bus["data_width"]))
    scored = [v for v in per_vector if v.get("expected_bytes") is not None]
    # `scored_with_golden` is consumed by `benchmark_verify_report` and
    # `bit_level_full_stack_tb_check`, which document it as vectors "compared
    # against a CONCRETE golden" and as "the ONLY honest measure" of functional
    # coverage. `ro_write_ignore` does NOT meet that description: its expected
    # value is the design's OWN baseline read (`exp = o["r0"]`), so it is a
    # SELF-CONSISTENCY oracle, not a document-derived one.
    #
    # MEASURED, which is why this is split rather than argued: forcing all 9
    # `read_data` assignments in a published design to one constant left the
    # score at 12 of 12 PASS. A read path that is entirely dead scored the same
    # as a correct one, and that 12 was flowing into the benchmark's headline
    # honesty number.
    #
    # The oracle is NOT worthless and is NOT removed — "a write must not change
    # a read-only register's read-back" is a real property and still FAILs when
    # writes leak into read-only address space. It is counted under its own
    # name so a reader can see how much of a coverage figure is self-referential.
    # THE SPLIT ABOVE WAS NOT ENOUGH, and the gap is this file's to close.
    # It corrected THIS program's counters, but `functional_coverage` is
    # produced by a DIFFERENT walker (`bit_level_full_stack_tb_oracle_check`)
    # that classifies a vector by whether `expected_bytes` LOOKS concrete —
    # and a self-referential golden looks exactly as concrete as a documented
    # one, because it IS a concrete number, just the design's own. So the
    # published results.json carried `register_map_coverage.scored_with_golden
    # = 2` beside `functional_coverage.scored_with_golden = 3`, and the second
    # is the one `benchmark_verify_report` reads.
    #
    # A private constant in this module cannot be consulted by that walker, so
    # the VECTOR carries the fact. Any counter can now tell the two apart
    # without knowing this program's kind names, and the flag is derived from
    # `_SELF_REF_KINDS` in one place so the two cannot drift.
    _SELF_REF_KINDS = ("ro_write_ignore",)
    for _v in per_vector:
        if isinstance(_v, dict):
            _v["self_referential_golden"] = (
                _v.get("kind") in _SELF_REF_KINDS)
    golden = [v for v in scored if v.get("kind") not in _SELF_REF_KINDS]
    selfref = [v for v in scored if v.get("kind") in _SELF_REF_KINDS]
    # When every self-referential baseline is the SAME value, the class cannot
    # discriminate a working read path from a stuck-at-constant one. That is
    # not a FAIL — nothing observed is wrong — but it must be visible, because
    # it is exactly the state in which a perfect score means nothing.
    _baselines = {v.get("expected_bytes") for v in selfref}
    info.update({
        "status": "scored" if scored else "emitted",
        "per_vector": per_vector,
        "addresses_probed": len(obs),
        "scored_with_golden": len(golden),
        "scored_passed": sum(1 for v in golden if v["verdict"] == "PASS"),
        "scored_failed": sum(1 for v in golden if v["verdict"] == "FAIL"),
        "scored_self_referential": len(selfref),
        "self_referential_passed": sum(
            1 for v in selfref if v["verdict"] == "PASS"),
        "self_referential_failed": sum(
            1 for v in selfref if v["verdict"] == "FAIL"),
        "self_referential_undiscriminating": (
            len(selfref) > 1 and len(_baselines) == 1),
        "log": str(work / "regmap.log"),
    })
    return info


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--top", required=True)
    ap.add_argument("--no-run", action="store_true",
                    help="emit the TB but do not simulate")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    res = generate(Path(args.project_dir), args.top, run=not args.no_run)
    text = json.dumps(res, indent=2)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    return 0 if res.get("status") in ("scored", "emitted") else 1


if __name__ == "__main__":
    sys.exit(main())
