#!/usr/bin/env python3
"""_full_stack_memory_binding.py — bind a full-stack TB to the DESIGN'S OWN
external memory port, and preload the firmware the design staged for it.

WHY
===
`step_full_stack_tb_gen` drives a DUT through one of three stimulus channels:
an inout pad (`drive_byte` over an open-drain wire), an L3 opcode byte stream,
or the register-map transaction driver. A design that has NONE of the three —
the runner's own words for this class are "CPU SoCs / pure datapath / reused-IP
glue", whose verification route it names as "gate-level synth + Phase 3 +
FIRMWARE EXECUTION, not a command-byte oracle" — gets a TB in which every
ordinary input keeps its `reg <name> = 0;` initial value for the whole
simulation. The clock and reset toggle; nothing else ever moves.

For a processor fed from an external memory that is not a weak TB, it is a TB
that cannot start the design: the core fetches 0x00000000 forever. The coverage
the flow then measures is a statement about the STIMULUS, not about the design,
and nothing in the record said so.

WHAT THIS DOES
==============
Two things, both chip-AGNOSTIC:

1. `resolve_memory_port_group` recognises an external memory port from the port
   list ALONE — a shared base token carrying an OUTPUT address and an INPUT
   read-data, optionally with write-data / write-enable / cycle-strobe. No chip,
   PDK or vendor name appears in the vocabulary.

2. `emit_memory_model_lines` emits a behavioural single-port synchronous memory
   bound to that group and `$readmemh`s the image the DESIGN staged under
   `input/firmware/`. The read-data port is ALREADY declared `reg` by the
   generator, so the model only ADDS an always-block that drives it: no existing
   declaration changes, and a design with no memory group or no staged image
   emits byte-for-byte what it emitted before.

DISCLOSURE IS NOT OPTIONAL
=========================
`describe_stimulus_binding` records which channel actually drove the DUT and,
when none did, NAMES the data inputs left at their initial value. A coverage
number measured against a TB that drove no data input must never be
indistinguishable from one measured against a TB that drove the design.

THE ONE ASSUMPTION, STATED
==========================
Read latency. A synchronous 1RW memory may return read data in the same cycle
or on the next edge; the port list cannot say which. The model implements the
REGISTERED (next-edge) convention and records `read_latency_cycles: 1` in the
binding, so a design needing combinational read is a disclosed mismatch rather
than a silent wrong answer. When the design declares the convention (a
`read_latency_cycles` in the firmware manifest) that declaration wins.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Direction affixes stripped before role/base extraction. Ordered longest-first
# so `io_` never loses to `i_`.
_DIR_PREFIXES = ("io_", "in_", "out_", "i_", "o_")
_DIR_SUFFIXES = ("_in", "_out", "_i", "_o")

# Role vocabulary. A role is the LAST underscore-separated token of the name
# after direction affixes are removed.
_ROLE_ADDR = {"addr", "address", "adr", "adrs"}
_ROLE_DATA = {"data", "dat", "rdata", "rdat", "wdata", "wdat",
              "q", "d", "dout", "din", "do", "di", "rd", "wd"}
_ROLE_WE = {"we", "wen", "wr", "write", "rw"}
_ROLE_STB = {"cyc", "stb", "en", "ce", "cs", "valid", "req", "sel"}

# A memory that would need more entries than this is not modelled: the emitted
# array would dominate simulator memory. Disclosed as a refusal, never silent.
_MAX_DEPTH = 1 << 22


def _strip_dir_affixes(name: str) -> str:
    n = name
    for p in _DIR_PREFIXES:
        if n.lower().startswith(p):
            n = n[len(p):]
            break
    for s in _DIR_SUFFIXES:
        if n.lower().endswith(s):
            n = n[: -len(s)]
            break
    return n


def _split_role(name: str):
    """-> (base, role) from the stripped name; role is the last token."""
    core = _strip_dir_affixes(name)
    if "_" not in core:
        return ("", core.lower())
    base, _, role = core.rpartition("_")
    return (base.lower(), role.lower())


def _width_bits(port: Dict[str, Any]) -> Optional[int]:
    """Bit width of a port, from an explicit width or an `[msb:lsb]` range."""
    for key in ("width", "bits", "size"):
        v = port.get(key)
        if isinstance(v, int) and v > 0:
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    for key in ("range", "msb_lsb", "decl", "width_decl"):
        v = port.get(key)
        if isinstance(v, str):
            m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", v)
            if m:
                return abs(int(m.group(1)) - int(m.group(2))) + 1
    msb, lsb = port.get("msb"), port.get("lsb")
    if isinstance(msb, int) and isinstance(lsb, int):
        return abs(msb - lsb) + 1
    return None


def resolve_memory_port_group(top_ports) -> Optional[Dict[str, Any]]:
    """Recognise an external memory port group from the port list alone.

    Requires, sharing one base token: an OUTPUT whose role is an address AND an
    INPUT whose role is a data word. Everything else (write-data, write-enable,
    cycle strobe) is optional and bound when present. Returns None when no such
    group exists — the caller then emits exactly what it emitted before.
    """
    if not isinstance(top_ports, (list, tuple)):
        return None
    buckets: Dict[str, Dict[str, Any]] = {}
    for p in top_ports:
        if not isinstance(p, dict):
            continue
        nm = (p.get("name") or "").strip()
        if not nm:
            continue
        direction = (p.get("direction") or p.get("mode") or "input").lower()
        base, role = _split_role(nm)
        if not base:
            continue
        b = buckets.setdefault(base, {"base": base})
        if role in _ROLE_ADDR and direction == "output":
            b["addr"] = nm
            b["addr_bits"] = _width_bits(p)
        elif role in _ROLE_DATA and direction == "input":
            b["rdata"] = nm
            b["data_bits"] = _width_bits(p)
        elif role in _ROLE_DATA and direction == "output":
            b["wdata"] = nm
        elif role in _ROLE_WE and direction == "output":
            b["we"] = nm
        elif role in _ROLE_STB and direction == "output":
            b["stb"] = nm
    # Deterministic pick: the richest group, ties broken by name, so the same
    # port list always yields the same binding.
    cands = [b for b in buckets.values() if b.get("addr") and b.get("rdata")]
    if not cands:
        return None
    cands.sort(key=lambda b: (-len([k for k in ("wdata", "we", "stb") if b.get(k)]),
                              b["base"]))
    g = cands[0]
    bits = g.get("addr_bits")
    if not isinstance(bits, int) or bits <= 0:
        return None
    depth = 1 << bits
    if depth > _MAX_DEPTH:
        g["refused"] = (f"address is {bits} bits → {depth} entries, over the "
                        f"{_MAX_DEPTH}-entry model limit")
        return g
    g["depth"] = depth
    return g


def find_firmware(project: Path) -> Optional[Dict[str, Any]]:
    """The firmware image the DESIGN staged, plus the ones it did not pick.

    `input/firmware/manifest.json` may declare `primary` (and optionally
    `read_latency_cycles`). Without a manifest the choice is the lexicographically
    first image, and the record says so — a picked-by-default image must never
    read as a picked-by-the-design one.
    """
    roots = [project / "input" / "firmware", project / "input" / "fw"]
    images: List[Path] = []
    for r in roots:
        if r.is_dir():
            images.extend(sorted(p for p in r.glob("*.hex") if p.is_file()))
    if not images:
        return None
    manifest_path = project / "input" / "firmware" / "manifest.json"
    primary, latency, basis = None, None, "lexicographically-first (no manifest)"
    if manifest_path.is_file():
        try:
            man = json.loads(manifest_path.read_text())
            want = man.get("primary")
            if isinstance(want, str):
                for im in images:
                    if im.name == want:
                        primary, basis = im, f"declared by {manifest_path.name}"
                        break
                if primary is None:
                    basis = (f"{manifest_path.name} names '{want}', which is not "
                             f"staged — fell back to lexicographically-first")
            lat = man.get("read_latency_cycles")
            if isinstance(lat, int) and lat in (0, 1):
                latency = lat
        except Exception:
            basis = f"{manifest_path.name} unreadable — lexicographically-first"
    if primary is None:
        primary = images[0]
    return {"image": primary,
            "image_name": primary.name,
            "selection_basis": basis,
            "read_latency_cycles": 1 if latency is None else latency,
            "read_latency_basis": ("design-declared" if latency is not None
                                   else "assumed registered (next-edge)"),
            "also_staged": [p.name for p in images if p != primary]}


def emit_memory_model_lines(group: Dict[str, Any], fw: Dict[str, Any],
                            clock_port: str) -> List[str]:
    """Behavioural 1RW synchronous memory bound to `group`, preloaded from `fw`.

    Purely ADDITIVE: the read-data port is already a `reg` in the generator's
    declarations, so this only adds the array, the preload and one always block.
    """
    depth = group["depth"]
    dbits = group.get("data_bits") or 8
    addr, rdata = group["addr"], group["rdata"]
    wdata, we, stb = group.get("wdata"), group.get("we"), group.get("stb")
    L: List[str] = ["",
                    "  // ---- firmware-backed external memory model -------------------",
                    f"  //  port group '{group['base']}' resolved from the DUT's own port",
                    f"  //  list: addr={addr} rdata={rdata}"
                    + (f" wdata={wdata}" if wdata else "")
                    + (f" we={we}" if we else "")
                    + (f" stb={stb}" if stb else ""),
                    f"  //  image  : {fw['image_name']}  ({fw['selection_basis']})",
                    f"  //  latency: {fw['read_latency_cycles']} cycle(s) "
                    f"({fw['read_latency_basis']})",
                    f"  reg [{dbits - 1}:0] fs_mem [0:{depth - 1}];",
                    "  integer fs_i;",
                    "  initial begin",
                    f"    for (fs_i = 0; fs_i < {depth}; fs_i = fs_i + 1)",
                    f"      fs_mem[fs_i] = {dbits}'h0;",
                    f'    $readmemh("{fw["image_name"]}", fs_mem);',
                    "  end"]
    guard = f"if ({stb}) begin" if stb else "begin"
    L.append(f"  always @(posedge {clock_port}) begin")
    L.append(f"    {guard}")
    if we and wdata:
        L.append(f"      if ({we}) fs_mem[{addr}] <= {wdata};")
    if fw["read_latency_cycles"] == 1:
        L.append(f"      {rdata} <= fs_mem[{addr}];")
    L.append("    end")
    L.append("  end")
    if fw["read_latency_cycles"] == 0:
        L.append(f"  always @(*) {rdata} = fs_mem[{addr}];")
    L.append("  // ---------------------------------------------------------------")
    return L


def describe_stimulus_binding(channel: str, *, group=None, fw=None,
                              undriven_inputs=None, reason: str = "") -> Dict[str, Any]:
    """The record that makes a TB which drove nothing distinguishable from one
    that drove the design."""
    rec: Dict[str, Any] = {
        "channel": channel,
        "drives_dut_data_inputs": channel != "none",
    }
    if group:
        rec["memory_port_group"] = {k: v for k, v in group.items()
                                    if k in ("base", "addr", "rdata", "wdata",
                                             "we", "stb", "depth", "refused")}
    if fw:
        rec["firmware"] = {k: v for k, v in fw.items() if k != "image"}
    if undriven_inputs:
        rec["undriven_data_inputs"] = sorted(undriven_inputs)
        rec["undriven_data_input_count"] = len(undriven_inputs)
    if reason:
        rec["reason"] = reason
    if channel == "none":
        rec["coverage_caveat"] = (
            "every DUT data input held its initial value for the whole "
            "simulation — a coverage number measured here describes the "
            "stimulus, not the design")
    return rec


# Where a simulation of the full-stack TB is actually launched from. `$readmemh`
# resolves its argument against the SIMULATOR'S cwd, not against the TB's
# directory, so an image that exists only beside the TB silently loads nothing —
# and a memory that silently stayed zero is exactly the failure this module
# exists to end. The image is therefore staged into every directory the flow is
# known to run a full-stack simulation from. Chip-AGNOSTIC: these are the
# plugin's own fixed layout paths, no design or vendor name.
_SIM_CWD_RELPATHS = (
    "phase2/stage1/sim/cov_build",    # verilator coverage build+run dir
    "phase2/stage1/sim_full_stack",   # beside the TB itself
    "phase2/stage1/sim",              # iverilog/vvp sims
)


def stage_firmware_for_sim(project: Path, fw: Dict[str, Any]) -> List[str]:
    """Copy the chosen image into each known simulation cwd. Returns the
    relative paths actually written, for the record."""
    src = fw.get("image")
    if not isinstance(src, Path) or not src.is_file():
        return []
    payload = src.read_bytes()
    written: List[str] = []
    for rel in _SIM_CWD_RELPATHS:
        dst_dir = project / rel
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            if not dst.is_file() or dst.read_bytes() != payload:
                dst.write_bytes(payload)
            written.append(f"{rel}/{src.name}")
        except OSError:
            # A directory the flow does not use on this run is not an error;
            # the ones that matter are recorded, and an empty list is visible.
            continue
    return written
