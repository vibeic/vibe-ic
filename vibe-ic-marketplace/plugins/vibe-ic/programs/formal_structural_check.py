#!/usr/bin/env python3
"""formal_structural_check.py — Step 5: discharge STRUCTURAL clock/reset
declarations with a deterministic structural check (R-0915-144).

WHY THIS EXISTS
===============
Step 5 turns every L8 clock/reset declaration into a formal obligation. Some of
those declarations state a TEMPORAL behaviour (the reset is active-high; every
register is zero one cycle after it is asserted) and a property can prove or
refute them. Others state a STRUCTURAL fact about the RTL:

    clocks.N.edge   = posedge          which edge every flop samples on
    resets.N.name   = rst              which port the reset branch tests
    resets.N.sync   = synchronous      whether any flop resets asynchronously

MEASURED on spm run22 (lane icspm5, 2026-09-23): no temporal property can
falsify these in the cycle-based model the flow proves in. There is no "between
edges" in which an async reset could show itself, and a property that "proves"
a port name can only be one that cannot fail. They were handed to the
`formal-verify` expert and stayed EXPERT_FALLBACK_OUTSTANDING.

A structural fact gets a structural answer. This program reads the design
through the flow's OWN yosys (`proc` + `flatten` + `opt_dff`, so a synchronous
reset is folded into `$sdff`/`$sdffe`/`$sdffce` with its SRST net and an
asynchronous one is `$adff`/`$adffe`/`$dffsr`/`$aldff`) and answers each claim
from the netlist:

    clock_edge    every flop clocked by the declared clock port has the declared
                  CLK_POLARITY, at least one is, and NO flop is clocked through
                  logic or by an internal net (its edge cannot be stated).
    reset_port    the declared port exists as a 1-bit input and its
                  combinational cone reaches some flop's reset control.
    reset_sync    "synchronous": the reset's WHOLE combinational cone reaches
                  flops only through a sync reset (SRST) and never an async
                  control (ARST / SET / CLR / AD / ALOAD), a clock pin, a latch
                  or a memory.  "asynchronous": the reverse. Review M4: a reset
                  ORed into an $adff ARST used to be invisible.
    state_covered every flop output bit in the design belongs to one of the
                  registers the generated "all internal state is zero"
                  properties observe. This is what makes "ALL" true of the
                  property set: a register the RTL scan missed is named here,
                  and the obligation stays open instead of being claimed.

Each claim ends PASS, REFUTED (the netlist contradicts the declaration, and the
finding names the cells), NOT_DISCHARGED (the netlist does not show the fact
either way: a reset yosys could not fold, a latch, a memory, a cell this
program cannot classify) or NOT_APPLICABLE (the declared signal is not a 1-bit
input — e.g. an OUTPUT reset `o_rst_n` — so it is not this rule's subject).
Only PASS discharges; the others keep the obligation open and SAY WHY.

The answer is recorded as INVOKED_BY_PROGRAM with the netlist and log as
evidence. It is never recorded as an AI answer (R-0915-125(a)).

chip-AGNOSTIC: generic yosys cell types and the design's own declared names.
There is no vendor, SKU, IC or PDK literal anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
import _atomic_artefact as _aa  # noqa: E402  (vibe-ic#1082 — atomic writes)
import _progress_run as _pr  # noqa: E402

VERSION = "3.0.0"

STRUCTURAL_RULES = ("clock_edge", "reset_port", "reset_sync", "reset_polarity",
                    "state_covered")

PASS = "PASS"
REFUTED = "REFUTED"
NOT_DISCHARGED = "NOT_DISCHARGED"
#: The claim's subject is not a 1-bit input of the design (an OUTPUT reset,
#: a clock that is not a port). Not a refutation, and not a discharge: the
#: obligation goes to the expert with the reason (review H5).
NOT_APPLICABLE = "NOT_APPLICABLE"

#: Flop cell types and the control pins that make them asynchronous.
_SYNC_RESET_FFS = {"$sdff", "$sdffe", "$sdffce"}
_ASYNC_CONTROLS = {
    "$adff": ("ARST",), "$adffe": ("ARST",),
    "$dffsr": ("SET", "CLR"), "$dffsre": ("SET", "CLR"),
    "$aldff": ("AD", "ALOAD"), "$aldffe": ("AD", "ALOAD"),
}
_FF_TYPES = ({"$dff", "$dffe"} | _SYNC_RESET_FFS | set(_ASYNC_CONTROLS))
#: State the flop checks do not model. Present → a claim about "all state" or
#: about how a reset/clock reaches state is NOT_DISCHARGED, never PASS
#: (review H2): a latch or a memory is state no generated property observes.
_LATCH_TYPES = {"$dlatch", "$adlatch", "$dlatchsr", "$sr", "$ff"}
_MEMORY_PREFIX = ("$mem",)
#: Combinational word-level cells: the only cells a cone is traced THROUGH.
#: Anything that is neither this nor a known state cell is UNCLASSIFIED and
#: makes the claims below NOT_DISCHARGED — never PASS on what was not seen.
_COMB_TYPES = {
    "$not", "$pos", "$neg", "$and", "$or", "$xor", "$xnor",
    "$reduce_and", "$reduce_or", "$reduce_xor", "$reduce_xnor", "$reduce_bool",
    "$logic_not", "$logic_and", "$logic_or", "$shl", "$shr", "$sshl", "$sshr",
    "$shift", "$shiftx", "$lt", "$le", "$eq", "$ne", "$eqx", "$nex", "$ge",
    "$gt", "$add", "$sub", "$mul", "$div", "$mod", "$divfloor", "$modfloor",
    "$pow", "$mux", "$pmux", "$bmux", "$demux", "$bwmux", "$bweqx", "$lut",
    "$sop", "$concat", "$slice", "$tribuf", "$alu", "$lcu", "$macc", "$fa",
}
_ASYNC_PINS = ("ARST", "SET", "CLR", "AD", "ALOAD")
#: Cells that carry no signal at all. `flatten` leaves one `$scopeinfo` per
#: flattened instance (hierarchy metadata, no ports that drive anything); it is
#: neither state nor logic.
_METADATA_TYPES = {"$scopeinfo",
                   # formal / debug cells: they observe, they hold no state
                   "$assert", "$assume", "$cover", "$live", "$fair", "$check",
                   "$print"}

#: The netlist the checks read. `opt_dff` is what folds a synchronous reset mux
#: into `$sdff` with its SRST net (and absorbs an `if (!rst_n)` inverter into
#: SRST_POLARITY); without it a sync reset is an anonymous `$mux` select.
YOSYS_PASSES = ("proc; flatten; opt_expr; opt_clean; opt_dff; opt_clean")


def yosys_script(rtl_files: List[str], top: str, netlist: str,
                 simdef: str = "", passes: str = "") -> str:
    """The DUT read EXACTLY as the chip's synthesis reads it (R-0915-157):
    `_chip_synth_read.chip_read_lines` — `read_verilog -sv [-DSIMULATION ]` per
    file. No `-formal`, no proof define: the facts are about the chip."""
    import _chip_synth_read as _csr
    reads = "; ".join(_csr.chip_read_lines([Path(f) for f in rtl_files], simdef))
    return (f"{reads}; hierarchy -top {top}; "
            f"{passes or YOSYS_PASSES}; write_json {netlist}")


def _param_bit(value) -> Optional[int]:
    """A yosys JSON parameter as an int (binary string or int)."""
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s and set(s) <= {"0", "1"}:
        return int(s, 2)
    try:
        return int(s)
    except ValueError:
        return None


def _top_module(netlist: dict, top: str) -> Optional[Tuple[str, dict]]:
    mods = netlist.get("modules") or {}
    for name, mod in mods.items():
        attrs = mod.get("attributes") or {}
        if _param_bit(attrs.get("top", 0)) == 1:
            return name, mod
    if top in mods:
        return top, mods[top]
    return None


def _port_bit(mod: dict, name: str) -> Tuple[Optional[int], str]:
    """(bit id, "") for a 1-bit input port, else (None, why)."""
    port = (mod.get("ports") or {}).get(name)
    if port is None:
        return None, f"no port named {name!r} on the module"
    if port.get("direction") != "input":
        return None, f"port {name!r} is {port.get('direction')!r}, not an input"
    bits = port.get("bits") or []
    if len(bits) != 1 or not isinstance(bits[0], int):
        return None, f"port {name!r} is {len(bits)} bits wide, not 1"
    return bits[0], ""


def _kind(ctype: str) -> str:
    """ff | latch | memory | comb | metadata | unclassified."""
    if ctype in _FF_TYPES:
        return "ff"
    if ctype in _LATCH_TYPES:
        return "latch"
    if ctype.startswith(_MEMORY_PREFIX):
        return "memory"
    if ctype in _COMB_TYPES:
        return "comb"
    if ctype in _METADATA_TYPES:
        return "metadata"
    if ctype.startswith("$_") and not any(
            k in ctype for k in ("DFF", "DLATCH", "SR", "FF_", "ALDFF")):
        return "comb"
    return "unclassified"


def _bits(cell: dict, pin: str) -> List[int]:
    return [b for b in ((cell.get("connections") or {}).get(pin) or [])
            if isinstance(b, int)]


def _cells(mod: dict) -> List[Tuple[str, dict, str]]:
    return [(n, c, _kind(str(c.get("type"))))
            for n, c in (mod.get("cells") or {}).items()]


def _cone(mod: dict, start: int) -> set:
    """Every bit reachable from `start` through COMBINATIONAL cells only."""
    cone = {start}
    comb = [(c, c.get("port_directions") or {}) for _, c, k in _cells(mod)
            if k == "comb"]
    changed = True
    while changed:
        changed = False
        for c, dirs in comb:
            if c.get("type") == "$mux":
                # BIT-PRECISE for a mux: Y[i] depends on A[i], B[i], and on S
                # only when A[i] and B[i] are not the same constant. A reset
                # folded into a mux whose both arms are 0 at some bit (the
                # constant MSB of a shifted register) does not reach that bit.
                conn = c.get("connections") or {}
                a, b, sel, y = (conn.get("A") or [], conn.get("B") or [],
                                conn.get("S") or [], conn.get("Y") or [])
                s_in = bool(cone.intersection(x for x in sel if isinstance(x, int)))
                for i, yb in enumerate(y):
                    if not isinstance(yb, int) or yb in cone:
                        continue
                    ai = a[i] if i < len(a) else None
                    bi = b[i] if i < len(b) else None
                    same_const = (isinstance(ai, str) and ai == bi)
                    if ai in cone or bi in cone or (s_in and not same_const):
                        cone.add(yb)
                        changed = True
                continue
            ins = [b for p, d in dirs.items() if d == "input" for b in _bits(c, p)]
            if not cone.intersection(ins):
                continue
            for p, d in dirs.items():
                if d == "output":
                    for b in _bits(c, p):
                        if b not in cone:
                            cone.add(b)
                            changed = True
    return cone


def _drivers(mod: dict) -> Dict[int, dict]:
    """bit -> the cell that drives it."""
    out: Dict[int, dict] = {}
    for _, c, _k in _cells(mod):
        for p, d in (c.get("port_directions") or {}).items():
            if d == "output":
                for b in _bits(c, p):
                    out[b] = c
    return out


def _raw_undef_q(mod: dict) -> set:
    """Retain raw literal-undef provenance before optimizing its data away."""
    drivers = _drivers(mod)
    raw_q = {q for _, c, k in _cells(mod) if k == "ff" for q in _bits(c, "Q")}

    def literal_undef(bit):
        pending, visited = [bit], set()
        while pending:
            current = pending.pop()
            if isinstance(current, str):
                if current.lower() in {"x", "z"}:
                    return True
                continue
            if current in visited or current in raw_q:
                continue
            visited.add(current)
            driver = drivers.get(current)
            if driver is not None:
                pending.extend(b for pin, bits in (driver.get("connections") or {}).items()
                               if (driver.get("port_directions") or {}).get(pin) == "input"
                               for b in bits)
        return False

    undef_q = set()
    for _, cell, kind in _cells(mod):
        if kind == "ff":
            bad_value = any(isinstance(v, str) and any(x in v.lower() for x in "xz")
                            for p, v in (cell.get("parameters") or {}).items()
                            if p.endswith("_VALUE"))
            if bad_value or any(literal_undef(b) for p, bits in cell["connections"].items()
                                if p != "Q" for b in bits):
                undef_q.update(_bits(cell, "Q"))
    return undef_q


def _raw_reset_independence(mod: dict, signal: str, targets: list) -> dict:
    """Certify reset absence in a complete raw one-step transition fan-in.

    Literal undef stays undef. Known FF Q bits are shared-current-state cuts,
    not a claim that their sequential histories are independent of reset.
    Missing/ambiguous drivers, unknown boundaries and combinational feedback
    cannot supply this certificate. No SAT answer is synthesized here.
    """
    if not targets:
        return {}
    import hashlib
    reset, reset_error = _port_bit(mod, signal)
    cells = mod.get("cells") or {}
    drivers = {}
    inputs = {b for p in (mod.get("ports") or {}).values()
              if p.get("direction") == "input" for b in p.get("bits") or []}
    inouts = {b for p in (mod.get("ports") or {}).values()
              if p.get("direction") == "inout" for b in p.get("bits") or []}
    for name, cell in cells.items():
        for pin, bits in (cell.get("connections") or {}).items():
            if (cell.get("port_directions") or {}).get(pin) != "input":
                for b in bits:
                    if isinstance(b, int):
                        drivers.setdefault(b, []).append((name, pin))
    graph_sha = hashlib.sha256(json.dumps(mod, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    certificates = {}
    for name, index, current_q in targets:
        cell = cells[name]
        conn, dirs = cell.get("connections") or {}, cell.get("port_directions") or {}
        q = (conn.get("Q") or [])[index]
        roots = {p: (list(bits[index:index+1]) if p == "D" else list(bits))
                 for p, bits in conn.items() if p != "Q"}
        cert = {"status": "UNAVAILABLE", "scope": "one_step_shared_current_q",
                "signal": signal, "raw_reset_bit": reset, "raw_cell": name,
                "raw_q": q, "q_index": index, "current_q": current_q,
                "raw_module_sha256": graph_sha, "roots": roots}
        certificates[name, index] = cert
        try:
            if reset_error:
                raise ValueError(reset_error)
            required = {"D", "CLK", "Q"}
            kind = cell.get("type")
            if kind in {"$dffe", "$sdffe", "$sdffce", "$adffe", "$dffsre"}:
                required.add("EN")
            if kind in _SYNC_RESET_FFS:
                required.add("SRST")
            if kind in {"$adff", "$adffe"}:
                required.add("ARST")
            if kind in {"$dffsr", "$dffsre"}:
                required.update(("SET", "CLR"))
            if (kind not in {"$dff", "$dffe", "$sdff", "$sdffe", "$sdffce",
                             "$adff", "$adffe", "$dffsr", "$dffsre"}
                    or set(conn) != required or len(conn["D"]) != len(conn["Q"])
                    or dirs.get("Q") != "output"
                    or drivers.get(q) != [(name, "Q")] or q in inputs or q in inouts
                    or any(dirs.get(p) != "input" or not bits for p, bits in roots.items())):
                raise ValueError("unmodelled raw storage or D/Q/control identity")
            pending = [(b, False) for bits in roots.values() for b in bits]
            active, done, visited_cells, primary, cuts, undef = set(), set(), set(), set(), set(), set()
            reaches_reset = False
            while pending:
                bit, leaving = pending.pop()
                if isinstance(bit, str):
                    if bit not in {"0", "1", "x", "z"}:
                        raise ValueError("unknown raw literal")
                    if bit in {"x", "z"}:
                        undef.add(bit)
                    continue
                if not isinstance(bit, int):
                    raise ValueError("unknown raw bit")
                if bit == reset:
                    reaches_reset = True
                if leaving:
                    active.remove(bit)
                    done.add(bit)
                    continue
                if bit in done:
                    continue
                if bit in active:
                    raise ValueError("unclosed raw combinational feedback")
                source = drivers.get(bit, [])
                if bit in inouts or len(source) > 1 or (bit in inputs and source):
                    raise ValueError("ambiguous raw input/driver")
                if bit in inputs:
                    primary.add(bit)
                    done.add(bit)
                    continue
                if len(source) != 1:
                    raise ValueError("missing raw driver")
                owner, pin = source[0]
                driver = cells[owner]
                ports, directions = driver.get("connections") or {}, driver.get("port_directions") or {}
                if (directions.get(pin) != "output" or set(ports) != set(directions)
                        or any(d not in {"input", "output"} for d in directions.values())):
                    raise ValueError("unknown raw driver ports")
                if _kind(driver.get("type", "")) == "ff" and pin == "Q":
                    cuts.add(bit)
                    done.add(bit)
                    continue
                if driver.get("type") not in _COMB_TYPES:
                    raise ValueError("unknown/noncombinational raw boundary")
                fanin = [b for p, bits in ports.items() if directions[p] == "input" for b in bits]
                if not fanin or any(not bits for p, bits in ports.items() if directions[p] == "input"):
                    raise ValueError("missing raw combinational inputs")
                visited_cells.add(owner)
                active.add(bit)
                pending.append((bit, True))
                pending.extend((b, False) for b in fanin)
            cert.update(status="UNAVAILABLE" if reaches_reset else "CERTIFIED",
                        complete_raw_fanin=True, reset_reachable=reaches_reset,
                        visited_cells=sorted(visited_cells),
                        primary_input_bits=sorted(primary), current_q_cut_bits=sorted(cuts),
                        literal_undef_bits=sorted(undef))
            if reaches_reset:
                cert["reason"] = "declared reset reaches raw transition"
        except ValueError as exc:
            cert["reason"] = str(exc)
    return certificates


_INVERTERS = {"$not", "$logic_not", "$_NOT_"}
_BUFFERS = {"$pos", "$_BUF_"}


def _parity(drivers: Dict[int, dict], bit: int, port_bit: int) -> Optional[int]:
    """Inversions between `port_bit` and `bit` along a chain of 1-bit
    inverters/buffers, or None when the path is anything else (a gate, a mux,
    a second input) — then the polarity is not a netlist fact."""
    par, seen = 0, set()
    while bit != port_bit:
        if bit in seen:
            return None
        seen.add(bit)
        c = drivers.get(bit)
        if c is None:
            return None
        a = _bits(c, "A")
        if len(a) != 1:
            return None
        if c.get("type") in _INVERTERS:
            par ^= 1
        elif c.get("type") not in _BUFFERS:
            return None
        bit = a[0]
    return par


def _relevant_bits(mod: dict) -> set:
    """Bits that can influence a DESIGN OUTPUT. Formal and debug cells are
    sinks that do not count, so a flop that only feeds an `assert` (an
    `ifdef FORMAL` helper) is verification-only, not design state."""
    rel = {b for p in (mod.get("ports") or {}).values()
           if p.get("direction") == "output"
           for b in p.get("bits") or [] if isinstance(b, int)}
    live = [(c, c.get("port_directions") or {}) for _, c, k in _cells(mod)
            if k not in ("metadata",)]
    changed = True
    while changed:
        changed = False
        for c, dirs in live:
            outs = {b for p, d in dirs.items() if d == "output" for b in _bits(c, p)}
            if not outs & rel:
                continue
            for p, d in dirs.items():
                if d == "input":
                    for b in _bits(c, p):
                        if b not in rel:
                            rel.add(b)
                            changed = True
    return rel


def _reset_map(mod: dict, port_bit: int) -> Dict[str, list]:
    """How the port reaches state, by what it FORCES (review round 4, H3):
      sync    SRST reached — the reset forces the flop's value on the clock
      async   ARST reached — forced between clocks
      async_x SET/CLR/AD/ALOAD reached — asynchronous, polarity not a fact
      data    D reached (never SRST/ARST) — could be a reset to a non-constant
              value or plain data use: NOT classified
      clk     a clock pin
      opaque  a latch, memory or unclassified cell
    A reset that only reaches an ENABLE gates a load; it forces nothing and
    is not a reset of that flop."""
    cone = _cone(mod, port_bit)
    drivers = _drivers(mod)
    rel = _relevant_bits(mod)
    out = {k: [] for k in ("sync", "async", "async_x", "data", "clk", "opaque")}
    for n, c, k in _cells(mod):
        if k in ("comb", "metadata"):
            continue
        if k == "ff" and not rel.intersection(_bits(c, "Q")):
            # a verification-only helper is not the design (the SAME
            # relevance netlist_facts and the class gate use)
            continue
        dirs = c.get("port_directions") or {}
        hit = [p for p, d in dirs.items() if d == "input" and cone.intersection(_bits(c, p))]
        if not hit:
            continue
        params = c.get("parameters") or {}
        if k != "ff":
            out["opaque"].append({"cell": n, "type": c.get("type")})
        elif "SRST" in hit or "ARST" in hit:
            pin = "SRST" if "SRST" in hit else "ARST"
            par = _parity(drivers, _bits(c, pin)[0], port_bit) if _bits(c, pin) else None
            pol = _param_bit(params.get(f"{pin}_POLARITY"))
            eff = None if (par is None or pol is None) else (pol ^ par)
            if eff is None:
                # a GATED reset pin (e.g. `rst_n && clear`) is not a reset the
                # port forces — unclassified, never counted as forced (round 5)
                out["opaque"].append({"cell": n, "type": c.get("type")})
                continue
            out["sync" if pin == "SRST" else "async"].append({
                "cell": n, "type": c.get("type"),
                "polarity": (None if eff is None else
                             "active_high" if eff == 1 else "active_low"),
                "q": _bits(c, "Q")})
        elif any(p in _ASYNC_PINS for p in hit):
            out["async_x"].append({"cell": n, "type": c.get("type"), "polarity": None})
        elif "CLK" in hit:
            out["clk"].append({"cell": n, "type": c.get("type")})
        elif "D" in hit:
            out["data"].append({"cell": n, "type": c.get("type")})
        # EN only: a gated load, not a reset
    return out


def netlist_facts(netlist: dict, top: str) -> dict:
    """The design's STATE, read from the netlist (review round 4, M4): every
    flop that can influence an output, covered by public net names, each
    with its width in bits. `ok` is False — with the reason — when that
    cannot be stated: a latch, memory or unclassified cell, or a flop bit no
    public name holds wholly."""
    tm = _top_module(netlist, top)
    if tm is None:
        return {"ok": False, "why": f"top module {top!r} is not in the netlist"}
    _, mod = tm
    census = _state_census(mod, netlist)
    other = census["latch"] + census["memory"] + census["unclassified"]
    if other:
        return {"ok": False, "why": "state that is not a flop: " + ", ".join(other)}
    rel = _relevant_bits(mod)
    flops = [(n, c) for n, c, k in _cells(mod) if k == "ff"]
    state_bits = {b for _, c in flops for b in _bits(c, "Q") if b in rel}
    verif_only = sorted(n for n, c in flops if not rel.intersection(_bits(c, "Q")))
    names = []
    for nname, net in (mod.get("netnames") or {}).items():
        if _param_bit(net.get("hide_name", 0)) == 1:
            continue
        bits = [b for b in net.get("bits") or []]
        if bits and all(isinstance(b, int) and b in state_bits for b in bits):
            names.append((nname, bits))
    names.sort(key=lambda t: ("." in t[0], len(t[0]), t[0]))
    chosen, covered = [], set()
    for nname, bits in names:
        if set(bits) - covered:
            chosen.append({"name": nname, "width": len(bits)})
            covered |= set(bits)
    if state_bits - covered:
        return {"ok": False, "why": (f"{len(state_bits - covered)} flop bit(s) "
                                     f"are not wholly held by any public net")}
    if not chosen:
        return {"ok": False, "why": "the design has no state"}
    return {"ok": True, "why": "", "registers": chosen,
            "verification_only": verif_only}


def _state_census(mod: dict, netlist: dict) -> Dict[str, List[str]]:
    census: Dict[str, List[str]] = {"ff": [], "latch": [], "memory": [],
                                    "unclassified": []}
    for n, c, k in _cells(mod):
        if k in census:
            census[k].append(f"{n} ({c.get('type')})")
    for m in (mod.get("memories") or {}):
        census["memory"].append(f"{m} (memory)")
    return census


def sync_state_facts(netlist: dict, top: str, clock: str, *,
                     source_aliases: Optional[dict] = None) -> dict:
    """Full Q census for SYNC construction and direct clock observations.

    Async flops remain in the observation set: they are a counterexample to
    prove, never a reason to silently choose a smaller synchronous subset.
    Only clock observations may supply native source aliases; the SYNC HDL
    constructor keeps its existing dotted-name grammar. Reset/value claims
    continue to use their own applicability conditions.
    """
    tm = _top_module(netlist, top) if isinstance(netlist, dict) else None
    if tm is None:
        return {"ok": False, "why": "the current raw netlist is unavailable"}
    _, mod = tm
    census = _state_census(mod, netlist)
    other = census["latch"] + census["memory"] + census["unclassified"]
    if other:
        return {"ok": False, "why": "unsupported storage: " + ", ".join(other)}
    cbit, why = _port_bit(mod, clock)
    if cbit is None:
        return {"ok": False, "why": "unknown clock: " + why}
    drivers = _drivers(mod)
    flops = [(n, c) for n, c, k in _cells(mod) if k == "ff"]
    identities, state = [], set()
    for name, cell in flops:
        q = _bits(cell, "Q")
        clk = _bits(cell, "CLK")
        edge = _param_bit((cell.get("parameters") or {}).get("CLK_POLARITY"))
        source = (_chain_source(drivers, clk[0], False)[0]
                  if len(clk) == 1 else None)
        if not q or edge is None or source != cbit:
            return {"ok": False, "why": f"unknown Q/clock/edge for {name}"}
        if state.intersection(q):
            return {"ok": False, "why": f"multiply driven state at {name}"}
        identities.append({"cell": name, "type": cell["type"], "q": q,
                           "clock_edge": "posedge" if edge else "negedge"})
        state.update(q)
    if not state:
        return {"ok": False, "why": "the design has no state"}
    if len({x["clock_edge"] for x in identities}) != 1:
        return {"ok": False, "why": "state samples on different clock edges"}
    names = []
    for name, net in (mod.get("netnames") or {}).items():
        bits = net.get("bits") or []
        # Exactly the dotted grammar the existing default runner binds.
        # Clock-only observations never emit HDL references: native public
        # word/escaped aliases can instead bind to the pre-map source census.
        admitted = (name in source_aliases if source_aliases is not None else
                    re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", name))
        if (admitted and (source_aliases is None or not _param_bit(net.get("hide_name", 0)))
                and bits and all(isinstance(b, int) and b in state for b in bits)):
            if source_aliases is not None and len(bits) != source_aliases[name]["width"]:
                return {"ok": False, "why": f"source alias width disagrees for {name}"}
            names.append((name, bits))
    if source_aliases is not None:
        required = {n for n, a in source_aliases.items() if a.get("memory")}
        found = dict(names)
        if required - found.keys():
            return {"ok": False, "why": "missing source memory word alias: "
                    + ", ".join(sorted(required - found.keys()))}
        word_bits = [b for n in required for b in found[n]]
        if len(word_bits) != len(set(word_bits)):
            return {"ok": False, "why": "ambiguous source memory word/bit aliases"}
        # Retain every mandatory word even when an output aliases its Q bits.
        names.sort(key=lambda x: (x[0] not in required, "." in x[0], len(x[0]), x[0]))
    else:
        names.sort(key=lambda x: ("." in x[0], len(x[0]), x[0]))
    covered, registers = set(), []
    for name, bits in names:
        if set(bits) - covered:
            registers.append({"name": name, "width": len(bits), "q": bits})
            covered.update(bits)
    if covered != state:
        return {"ok": False, "why": f"missing exact alias for {len(state-covered)} Q bit(s)"}
    return {"ok": True, "why": "", "clock": clock,
            "clock_edge": identities[0]["clock_edge"],
            "identities": identities, "q_bits": sorted(state),
            "registers": registers}


def _clock_combinational_rom(mod: dict, name: str, memory: dict) -> bool:
    """Recognize the native constant-initializer/asynchronous-read ROM shape.

    Every port must belong to this closed shape: no runtime writer, clocked
    read, reset, partial/undefined initializer or unknown memory cell. Names
    and visibility do not establish immutability. The clock-only memory_map
    views still have to account for every sequential Q bit afterwards.
    """
    width, size, start = (memory[k] for k in ("width", "size", "start_offset"))
    ports = [c for _, c, kind in _cells(mod) if kind == "memory"
             and (c.get("parameters") or {}).get("MEMID") in (name, "\\" + name)]
    reads = [c for c in ports if c.get("type") == "$memrd_v2"]
    inits = [c for c in ports if c.get("type") == "$meminit"]
    if not reads or len(inits) != 1 or len(ports) != len(reads) + 1 or start < 0:
        return False
    init = inits[0]
    params, conn = init.get("parameters") or {}, init.get("connections") or {}
    address, data = conn.get("ADDR") or [], conn.get("DATA") or []
    if (set(conn) != {"ADDR", "DATA"}
            or _param_bit(params.get("WIDTH")) != width
            or _param_bit(params.get("WORDS")) != size
            or _param_bit(params.get("ABITS")) != len(address)
            or not address or any(b not in ("0", "1") for b in address)
            or int("".join(reversed(address)), 2) != start
            or len(data) != width * size or any(b not in ("0", "1") for b in data)):
        return False
    for read in reads:
        params, conn = read.get("parameters") or {}, read.get("connections") or {}
        address, data = conn.get("ADDR") or [], conn.get("DATA") or []
        if (set(conn) != {"ADDR", "DATA", "CLK", "EN", "ARST", "SRST"}
                or _param_bit(params.get("CLK_ENABLE")) != 0
                or _param_bit(params.get("WIDTH")) != width
                or _param_bit(params.get("ABITS")) != len(address)
                or not address or any(not isinstance(b, int) and b not in ("0", "1")
                                      for b in address)
                or len(data) != width or any(not isinstance(b, int) for b in data)
                or conn.get("CLK") != ["x"] or conn.get("EN") != ["1"]
                or conn.get("ARST") != ["0"] or conn.get("SRST") != ["0"]):
            return False
    return True


def _clock_memory_aliases(netlist: dict, top: str) -> Tuple[dict, str]:
    """Bind native memory_map word aliases to the original native declarations.

    No RTL parser or HDL observer is involved. Missing source locations,
    hidden sequential memories, collisions and unsupported native memory
    shapes refuse. Proven combinational ROMs need no sequential word aliases.
    This mapping is exclusively for clock observations, never reset/SYNC HDL.
    """
    tm = _top_module(netlist, top)
    if tm is None:
        return {}, "pre-map source census unavailable"
    mod = tm[1]
    aliases = {}
    for name, net in (mod.get("netnames") or {}).items():
        if not _param_bit(net.get("hide_name", 0)) and (net.get("attributes") or {}).get("src"):
            aliases[name] = {"width": len(net.get("bits") or []),
                             "src": net["attributes"]["src"]}
    memories = mod.get("memories") or {}
    if not memories:
        return {}, "no source memory declarations for native memory cells"
    for name, mem in memories.items():
        width, size, start = (mem.get(k) for k in ("width", "size", "start_offset"))
        src = (mem.get("attributes") or {}).get("src")
        if (not src
                or not all(isinstance(v, int) for v in (width, size, start))
                or width <= 0 or size <= 0):
            return {}, f"unsupported source memory declaration: {name}"
        if _clock_combinational_rom(mod, name, mem):
            continue
        if _param_bit(mem.get("hide_name", 0)):
            return {}, f"unsupported source memory declaration: {name}"
        for word in range(start, start + size):
            alias = f"{name}[{word}]"
            if alias in (mod.get("netnames") or {}) or alias in aliases:
                return {}, f"ambiguous source memory alias: {alias}"
            aliases[alias] = {"width": width, "src": src,
                              "memory": name, "word": word}
    return aliases, ""


def clock_edge_applicability(netlist: dict, raw_netlist: Optional[dict],
                             top: str, clock: str, *,
                             source_aliases: Optional[dict] = None) -> List[str]:
    """Claim-specific admission for a ``clock_edge`` observation.

    Clock polarity is independent of reset/value semantics.  In particular, a
    reset used in D or EN must not make a directly-clocked state bit's edge
    unknowable.  This route deliberately does *not* relax R-0915-155 for any
    other claim: it requires a complete, direct-clocked state census in both
    the optimized and no-``opt_dff`` reads, and refuses if their observable
    identities or edge differ.
    """
    optimized = sync_state_facts(netlist, top, clock, source_aliases=source_aliases)
    if not optimized.get("ok"):
        return ["clock_edge complete optimized-state census unavailable: "
                + str(optimized.get("why") or "unknown reason")]
    raw = sync_state_facts(raw_netlist, top, clock, source_aliases=source_aliases)
    if not raw.get("ok"):
        return ["clock_edge complete raw-state census unavailable: "
                + str(raw.get("why") or "unknown reason")]

    def observed(facts: dict) -> List[Tuple[str, int]]:
        return sorted((str(r["name"]), int(r["width"]))
                      for r in facts.get("registers") or [])

    fails = []
    if observed(raw) != observed(optimized):
        fails.append("clock_edge raw/optimized complete-state identities disagree")
    if raw.get("clock_edge") != optimized.get("clock_edge"):
        fails.append("clock_edge raw/optimized observed edges disagree")
    return fails


def _transition_pair(mod: dict, reset_bit: int,
                     payload_by_q: Optional[dict] = None,
                     observations: Optional[dict] = None) -> Tuple[dict, List[dict]]:
    """Two native combinational next-state models sharing every Q/data bit.

    Only the selected top reset differs (0 versus 1). Original combinational
    cells and literal undef bits are retained. The coarse FF priority below
    follows Yosys simlib: sdffe resets before enable; sdffce enables before
    reset; asynchronous controls precede enable; CLR precedes SET.
    """
    import copy
    flops = [(n, c) for n, c, k in _cells(mod) if k == "ff"]
    qbits = {b for _, c in flops for b in _bits(c, "Q")}
    free = qbits | {b for p in (mod.get("ports") or {}).values()
                    if p.get("direction") == "input" for b in p["bits"]
                    if isinstance(b, int) and b != reset_bit}
    nxt, maps, shared, cells, ports = 2, [{}, {}], {}, {}, {}
    role_inputs = {}

    def allocate():
        nonlocal nxt
        b = nxt
        nxt += 1
        return b

    for bit in sorted(free):
        shared[bit] = allocate()
        ports[f"input_{bit}"] = {"direction": "input", "bits": [shared[bit]]}

    def remap(bit, arm):
        if not isinstance(bit, int):
            return bit
        if bit == reset_bit:
            return str(arm)
        if bit in shared:
            return shared[bit]
        if bit not in maps[arm]:
            maps[arm][bit] = allocate()
        return maps[arm][bit]

    def gate(kind, a, b=None, select=None):
        y = allocate()
        conn = {"A": [a], "Y": [y]}
        params = {"A_SIGNED": 0, "A_WIDTH": 1, "Y_WIDTH": 1}
        if b is not None:
            conn["B"] = [b]
            params.update(B_SIGNED=0, B_WIDTH=1)
        if select is not None:
            conn["S"] = [select]
            params = {"WIDTH": 1}
        cells[f"transition_{y}"] = {"type": kind, "parameters": params,
            "port_directions": {p: "output" if p == "Y" else "input" for p in conn},
            "connections": conn}
        role_inputs[y] = [v for pin, values in conn.items() if pin != "Y" for v in values]
        return y

    def mux(a, b, s):
        return gate("$mux", a, b, s)

    drivers = _drivers(mod)
    cone = _cone(mod, reset_bit)
    for arm in (0, 1):
        for i, (_name, cell, kind) in enumerate(_cells(mod)):
            if kind == "comb":
                copied = copy.deepcopy(cell)
                copied["connections"] = {p: [remap(b, arm) for b in bits]
                                          for p, bits in cell["connections"].items()}
                cells[f"comb_{arm}_{i}"] = copied
                inputs = [v for pin, values in copied["connections"].items()
                          if copied["port_directions"].get(pin) == "input" for v in values]
                for pin, values in copied["connections"].items():
                    if copied["port_directions"].get(pin) == "output":
                        for value in values:
                            role_inputs[value] = inputs

    def both(a, b):
        return gate("$and", a, b)

    def either(a, b):
        return gate("$or", a, b)

    def inverse(a):
        return gate("$not", a)

    role_cache, role_provenance = {}, []

    def payload_free_guard(bit, q):
        """A new force guard cannot select a convenient shared data/Q value."""
        forbidden = {shared[v] for v in (payload_by_q or {}).get(q, set()) | qbits
                     if v in shared}
        pending, seen = [bit], set()
        while pending:
            value = pending.pop()
            if value in ("0", "1") or value in seen:
                continue
            if not isinstance(value, int) or value in forbidden:
                return False
            seen.add(value)
            if value in role_inputs:
                pending.extend(role_inputs[value])
            elif value not in shared.values():
                return False
        return True

    def input_bit(cell, pin, index):
        values = cell["connections"].get(pin) or []
        if index < len(values):
            return values[index]
        signed = _param_bit(cell.get("parameters", {}).get(pin + "_SIGNED"))
        return values[-1] if signed and values else "0"

    def payload_expression_support(bit, q, seen=frozenset()):
        """A shared payload expression may use only the existing payload roots."""
        if bit in ("0", "1"):
            return set()
        if not isinstance(bit, int) or bit in seen:
            return None
        if bit in free:
            return {bit} if bit in (payload_by_q or {}).get(q, set()) else None
        cell = drivers.get(bit)
        if cell is None or _kind(str(cell.get("type"))) != "comb":
            return None
        support = set()
        for pin, values in (cell.get("connections") or {}).items():
            if cell.get("port_directions", {}).get(pin) == "input":
                for value in values:
                    below = payload_expression_support(value, q, seen | {bit})
                    if below is None:
                        return None
                    support.update(below)
        return support

    def mask_control(bit, q, seen=frozenset()):
        """A control cannot be selected by a shared cofactor payload value.

        The native, reset-normalized next-state cofactors identify data/Q
        support common to both arms. Reading that payload to obtain a convenient
        zero/one is data selection, including when an ordinary mux has been
        lowered to Boolean gates. This test applies to every operator uniformly;
        no mux/gate spelling is blacklisted and no SAT cube is mined. Support is
        conservative, so an unclosed data/control distinction remains refused.
        """
        payload = (payload_by_q or {}).get(q)
        if payload is None:
            return False
        if bit == reset_bit:
            return True
        if not isinstance(bit, int):
            return bit not in {"x", "z"}
        if bit in free:
            return bit not in payload
        if bit in seen:
            return False
        cell = drivers.get(bit)
        if cell is None:
            return False
        conn = cell.get("connections") or {}
        seen = seen | {bit}
        return all(mask_control(value, q, seen)
                   for pin, values in conn.items()
                   if cell.get("port_directions", {}).get(pin) == "input"
                   for value in values)

    def combine_roles(kind, a, b):
        if kind == "$and":
            return (either(a[0], b[0]), both(a[1], b[1]),
                    either(both(a[2], b[1]), both(b[2], a[1])))
        return (both(a[0], b[0]), either(a[1], b[1]),
                either(both(a[2], b[0]), both(b[2], a[0])))

    def masked_roles(kind, data, select):
        return ((mux("1", data[0], select), mux("0", data[1], select),
                 mux("0", data[2], select)) if kind == "$and" else
                (mux(data[0], "0", select), mux(data[1], "1", select),
                 mux(data[2], "0", select)))

    def native_reduce(kind, values, arm):
        if not values:
            return "1" if kind == "$and" else "0"
        if len(values) == 1:
            return remap(values[0], arm)
        y = allocate()
        cells[f"transition_{y}"] = {"type": "$reduce_and" if kind == "$and" else "$reduce_or",
            "parameters": {"A_SIGNED": 0, "A_WIDTH": len(values), "Y_WIDTH": 1},
            "port_directions": {"A": "input", "Y": "output"},
            "connections": {"A": [remap(value, arm) for value in values], "Y": [y]}}
        return y

    def reduced_roles(kind, values, arm, q, seen, cofactor=None):
        control = [v for v in values if isinstance(v, int) and v in cone]
        data = [v for v in values if not (isinstance(v, int) and v in cone)]
        if control and data and all(mask_control(v, q) for v in control):
            role_provenance.append({"kind": "native vector reduction",
                "control_bits": control, "branch_roles": "dominating Boolean mask / unchanged vector data"})
            return masked_roles(kind, reduced_roles(kind, data, arm, q, seen, cofactor),
                                native_reduce(kind, control, arm))
        result = ("0", "1", "0") if kind == "$and" else ("1", "0", "0")
        for value in values:
            result = combine_roles(kind, result, d_roles(value, arm, q, seen, cofactor))
        return result

    def d_roles(bit, arm, q, seen=frozenset(), cofactor=None):
        """Conditional source roles, without solving for convenient data values.

        The three predicates mean force-zero, force-one, and retain-Q. A mux
        keeps its original branch selection. A Boolean mask uses its original
        reset-dependent operand as the control: AND's zero and OR's one are
        dominating values, independent of the other (unconstrained) data
        operand. Two reset-dependent operands are composed from their roles;
        neither arbitrary SAT cubes nor a data value chosen by a witness become
        a new control. Every resulting force/hold implication is checked by
        native SAT against the original next-state value below.
        """
        if cofactor is not None and bit == cofactor[0]:
            return ("1", "0", "0") if cofactor[1] == "0" else ("0", "1", "0")
        key = (bit, arm, q, cofactor)
        if key in role_cache:
            return role_cache[key]
        empty = ("0", "0", "0")
        if bit in ("0", "1"):
            return ("1", "0", "0") if bit == "0" else ("0", "1", "0")
        if bit == q:
            return ("0", "0", "1")
        if not isinstance(bit, int) or bit in qbits or bit in seen:
            return empty
        cell = drivers.get(bit) or {}
        conn, kind = cell.get("connections") or {}, cell.get("type")
        try:
            i = conn["Y"].index(bit)
            seen = seen | {bit}
            if kind in {"$pos", "$not"}:
                zero, one, held = d_roles(input_bit(cell, "A", i), arm, q, seen, cofactor)
                answer = (one, zero, "0") if kind == "$not" else (zero, one, held)
            elif kind in {"$mux", "$bwmux"}:
                select = conn["S"][i if kind == "$bwmux" else 0]
                a = d_roles(input_bit(cell, "A", i), arm, q, seen, cofactor)
                b = d_roles(input_bit(cell, "B", i), arm, q, seen, cofactor)
                answer = tuple(mux(x, y, remap(select, arm)) for x, y in zip(a, b))
                role_provenance.append({"output_bit": bit, "kind": kind,
                    "control_bits": [select], "branch_roles": "original A/B selection"})
            elif kind in {"$and", "$or", "$xor", "$xnor"}:
                left, right = input_bit(cell, "A", i), input_bit(cell, "B", i)
                a, b = d_roles(left, arm, q, seen, cofactor), d_roles(right, arm, q, seen, cofactor)
                controls = [v for v in (left, right) if isinstance(v, int) and v in cone]
                if len(controls) == 1 and kind in {"$and", "$or"} and mask_control(controls[0], q):
                    control = controls[0]
                    data = b if control == left else a
                    select = remap(control, arm)
                    # Annihilator versus transparent branch, not a cube over
                    # the other operand. The data branch stays free/shared.
                    answer = masked_roles(kind, data, select)
                    role_provenance.append({"output_bit": bit, "kind": kind,
                        "control_bits": [control],
                        "branch_roles": "dominating Boolean mask / unchanged data"})
                elif kind == "$and":
                    if len(controls) == 1:
                        role_provenance.append({"output_bit": bit, "kind": kind,
                            "control_bits": [], "branch_roles": "shared cofactor payload is not a mask control"})
                    answer = combine_roles(kind, a, b)
                elif kind == "$or":
                    answer = combine_roles(kind, a, b)
                else:
                    def xor_roles(x, y):
                        zero = either(both(x[0], y[0]), both(x[1], y[1]))
                        one = either(both(x[0], y[1]), both(x[1], y[0]))
                        held = either(both(x[2], y[0]), both(y[2], x[0]))
                        return (one, zero, "0") if kind == "$xnor" else (zero, one, held)

                    answer = xor_roles(a, b)
                    if cofactor is None:
                        # Keep correlations with an original shared payload expression.
                        # BOTH values must force the same result, so this is not
                        # a SAT witness choosing lucky data. The original value
                        # model and all native role/undef/priority proofs remain.
                        for atom in (value for value in {left, right}
                                     if payload_expression_support(value, q)):
                            halves = [xor_roles(
                                d_roles(left, arm, q, seen, (atom, value)),
                                d_roles(right, arm, q, seen, (atom, value)))
                                for value in ("0", "1")]
                            guards = [both(halves[0][j], halves[1][j]) for j in (0, 1)]
                            independent = [payload_free_guard(guard, q) for guard in guards]
                            answer = tuple(either(answer[j], guards[j]) if independent[j] else answer[j]
                                           for j in (0, 1)) + (answer[2],)
                            if any(independent):
                                role_provenance.append({"output_bit": bit, "kind": kind,
                                    "cofactored_shared_payload_bit": atom,
                                    "branch_roles": "both payload values; payload-independent force guard"})
            elif kind in {"$logic_and", "$logic_or"}:
                # Logical operands use vector truth (nonzero), not bit zero.
                left, right = conn.get("A") or [], conn.get("B") or []
                a = reduced_roles("$or", left, arm, q, seen, cofactor)
                b = reduced_roles("$or", right, arm, q, seen, cofactor)
                dependent = [values for values in (left, right) if any(
                    isinstance(v, int) and v in cone for v in values)]
                op = "$and" if kind == "$logic_and" else "$or"
                if len(dependent) == 1 and all(mask_control(v, q) for v in dependent[0]):
                    control = dependent[0]
                    data = b if control is left else a
                    answer = masked_roles(op, data, native_reduce("$or", control, arm))
                    role_provenance.append({"output_bit": bit, "kind": kind,
                        "control_bits": control, "branch_roles": "native vector truth / unchanged data"})
                else:
                    answer = combine_roles(op, a, b)
            elif kind in {"$reduce_xor", "$reduce_xnor"}:
                # Fold source roles, never data values: parity is forced only
                # when every operand has a force role in the same domain.
                answer = ("1", "0", "0")
                for source in conn.get("A") or []:
                    a, b = answer, d_roles(source, arm, q, seen, cofactor)
                    answer = (either(both(a[0], b[0]), both(a[1], b[1])),
                              either(both(a[0], b[1]), both(a[1], b[0])),
                              either(both(a[2], b[0]), both(b[2], a[0])))
                if kind == "$reduce_xnor":
                    answer = (answer[1], answer[0], "0")
                role_provenance.append({"output_bit": bit, "kind": kind,
                    "branch_roles": "parity composition of original operand force/retain roles"})
            elif kind in {"$reduce_and", "$reduce_or", "$reduce_bool", "$logic_not"}:
                answer = reduced_roles("$and" if kind == "$reduce_and" else "$or",
                                       conn.get("A") or [], arm, q, seen, cofactor)
                if kind == "$logic_not":
                    answer = (answer[1], answer[0], "0")
            elif kind in {"$slice", "$concat"}:
                if kind == "$slice":
                    offset = cell.get("parameters", {}).get("OFFSET", 0)
                    offset = int(offset, 2) if isinstance(offset, str) else int(offset)
                    source = input_bit(cell, "A", i + offset)
                else:
                    width = len(conn.get("A") or [])
                    source = input_bit(cell, "A", i) if i < width else input_bit(cell, "B", i - width)
                answer = d_roles(source, arm, q, seen, cofactor)
            else:
                answer = empty
        except (IndexError, KeyError, ValueError):
            answer = empty
        role_cache[key] = answer
        return answer

    rows = []
    for name, cell in flops:
        kind = cell["type"]
        conn, params = cell.get("connections") or {}, cell.get("parameters") or {}
        hit = [p for p, bits in conn.items() if p != "Q" and cone.intersection(
            b for b in bits if isinstance(b, int))]
        clk = _bits(cell, "CLK")
        source = _chain_source(drivers, clk[0], False)[0] if len(clk) == 1 else None
        input_clocks = {b for p in (mod.get("ports") or {}).values()
                        if p.get("direction") == "input" and len(p["bits"]) == 1
                        for b in p["bits"]}
        for i, q in enumerate(conn.get("Q") or []):
            row = {"cell": name, "type": kind, "q": q, "bit_index": i,
                   "clock": conn.get("CLK"), "clock_polarity": params.get("CLK_POLARITY"),
                   "controls": {p: conn[p] for p in ("D", "EN", "SRST", "ARST", "SET", "CLR") if p in conn},
                   "parameters": params, "reset_reaches": hit}
            rows.append(row)
            if (kind not in {"$dff", "$dffe", "$sdff", "$sdffe", "$sdffce", "$adff", "$adffe", "$dffsr", "$dffsre"}
                    or not isinstance(q, int) or i >= len(conn.get("D") or [])
                    or source not in input_clocks or "CLK" in hit
                    or _param_bit(params.get("CLK_POLARITY")) is None):
                row["unsupported"] = "unmodelled storage, clock or D/Q identity"
                continue

            def active(pin, arm, index=0):
                values = conn.get(pin) or []
                polarity = _param_bit(params.get(pin + "_POLARITY"))
                if index >= len(values) or polarity is None:
                    raise ValueError("unknown " + pin + " polarity/width")
                v = remap(values[index], arm)
                return v if polarity else gate("$not", v)

            def reset_value(pin):
                value = params.get(pin + "_VALUE")
                if isinstance(value, int):
                    return str((value >> i) & 1)
                if not isinstance(value, str) or len(value) <= i or value[-1-i] not in "01xz":
                    raise ValueError("unknown " + pin + " value/width")
                return value[-1-i]

            outputs = []
            role_provenance = []
            try:
                for arm in (0, 1):
                    d, held = remap(conn["D"][i], arm), shared[q]
                    zero, one, hold = d_roles(conn["D"][i], arm, q)

                    def apply_branch(value, select):
                        nonlocal d, zero, one, hold
                        d = mux(d, value, select)
                        zero = mux(zero, "1" if value == "0" else "0", select)
                        one = mux(one, "1" if value == "1" else "0", select)
                        hold = mux(hold, "0", select)

                    def apply_enable(select):
                        nonlocal d, zero, one, hold
                        d = mux(held, d, select)
                        zero, one = mux("0", zero, select), mux("0", one, select)
                        hold = mux("1", hold, select)

                    if "EN" in conn and kind != "$sdffce":
                        en = active("EN", arm)
                        apply_enable(en)
                    if "SRST" in conn or "ARST" in conn:
                        pin = "SRST" if "SRST" in conn else "ARST"
                        rst = active(pin, arm)
                        apply_branch(reset_value(pin), rst)
                    if kind == "$sdffce":
                        en = active("EN", arm)
                        apply_enable(en)
                    if kind in {"$dffsr", "$dffsre"}:
                        st, cl = active("SET", arm, i), active("CLR", arm, i)
                        apply_branch("1", st)
                        apply_branch("0", cl)
                    force = either(zero, one)
                    # Force takes precedence over an algebraically coincident
                    # hold predicate; the roles must be disjoint and exhaustive.
                    hold = both(hold, inverse(force))
                    data = inverse(either(force, hold))
                    outputs.append((d, force, zero, one, hold, data))
            except ValueError as exc:
                row["unsupported"] = str(exc)
                continue
            n0, f0 = outputs[0][:2]
            n1, f1 = outputs[1][:2]
            names = {"n0": n0, "n1": n1,
                "retain0": gate("$eq", n0, shared[q]),
                "retain1": gate("$eq", n1, shared[q]),
                "equal": gate("$eq", n0, n1),
                "high_violation": gate("$and", f0, gate("$not", f1)),
                "low_violation": gate("$and", f1, gate("$not", f0))}
            for arm, (value, force, zero, one, hold, data) in enumerate(outputs):
                roles = {"force_zero": zero, "force_one": one,
                         "retain": hold, "data": data}
                for role, guard in roles.items():
                    names[f"{role}_guard{arm}"] = guard
                    if role != "data":
                        expected = (gate("$eq", value, shared[q]) if role == "retain" else
                                    gate("$eq", value, "1" if role == "force_one" else "0"))
                        names[f"{role}_valid{arm}"] = either(inverse(guard), expected)
                names[f"roles_disjoint{arm}"] = inverse(either(
                    both(zero, one), either(both(force, hold), both(either(force, hold), data))))
                names[f"roles_cover{arm}"] = either(either(zero, one), either(hold, data))
                pin = "SRST" if "SRST" in conn else "ARST" if "ARST" in conn else None
                if "EN" in conn and pin:
                    blocked = both(inverse(active("EN", arm)), active(pin, arm))
                    reset_constant = reset_value(pin)
                    differs = inverse(gate("$eq", shared[q], reset_constant))
                    expected = shared[q] if kind == "$sdffce" else reset_constant
                    names[f"priority_domain{arm}"] = blocked
                    names[f"priority_discriminating{arm}"] = both(blocked, differs)
                    names[f"priority_valid{arm}"] = either(
                        inverse(blocked), gate("$eq", value, expected))
            row["query_ports"] = {k: f"q{len(rows)-1}_{k}" for k in names}
            for key, bit in names.items():
                ports[row["query_ports"][key]] = {"direction": "output", "bits": [bit]}
            row["priority"] = ("EN > SRST > D" if kind == "$sdffce" else
                               "CLR > SET > EN > D" if kind in {"$dffsr", "$dffsre"} else
                               "ARST > EN > D" if "ARST" in conn else
                               "SRST > EN > D" if "SRST" in conn else "EN > D")
            row["role_provenance"] = list({json.dumps(p, sort_keys=True): p
                                            for p in role_provenance}.values())
    for name, bit in (observations or {}).items():
        for arm in (0, 1):
            ports[f"observe_{name}_{arm}"] = {"direction": "output", "bits": [remap(bit, arm)]}
    module = {"attributes": {"top": 1}, "ports": ports, "cells": cells,
              "netnames": {n: {"hide_name": 0, "bits": p["bits"], "attributes": {}}
                           for n, p in ports.items()}}
    return {"modules": {"transition_pair": module}}, rows


def _native_text(value) -> str:
    """Return a stable text form for subprocess streams, including timeout bytes."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _native_query_run(argv: List[str], timeout: int = 120, *,
                      container: Optional[str] = None, command: Optional[str] = None
                      ) -> Tuple[int, str, str, dict]:
    """Supervise native progress and reap the exact owned container job.

    ``timeout`` is a recorded budget, never a clock kill. Individual SAT
    queries retain their solver limit and every terminal marker remains in
    the evidence. A stalled batch is incomplete, including its partial output.
    """
    supervision = "host_process_and_progress"
    try:
        import _container_exec as ce
        if container and not ce.local_exec_mode("formal_structural_check"):
            if not command:
                raise ValueError("container native query requires its exact command")
            supervision = "container_identity_and_progress"
            process = ce.run_in_container_supervised(container, command, ceiling_s=timeout)
        else:
            process = _pr.run(argv, capture_output=True, text=True, hard_ceiling_s=timeout)
        return process.returncode, _native_text(process.stdout), _native_text(process.stderr), {
            "termination": "STALLED" if process.returncode == _pr.RC_STALLED else "COMPLETED",
            "native_exit_code": process.returncode, "supervision": supervision,
            "recorded_budget_seconds": timeout}
    except _pr.Stalled as exc:
        return _pr.RC_STALLED, _native_text(exc.stdout), _native_text(exc.stderr), {
            "termination": "STALLED", "native_exit_code": _pr.RC_STALLED,
            "supervision": supervision, "error": str(exc), "signals": exc.signals}
    except subprocess.TimeoutExpired as exc:
        stdout = getattr(exc, "stdout", None)
        if stdout is None:
            stdout = exc.output
        return 124, _native_text(stdout), _native_text(exc.stderr), {
            "termination": "TIMEOUT", "native_exit_code": 124,
            "timeout_seconds": timeout, "error": str(exc)}
    except OSError as exc:
        return 127, "", "", {"termination": "TOOL_UNAVAILABLE", "native_exit_code": 127,
                               "error": str(exc)}


def _native_artifacts(work_dir: Path, stem: str, stdout: str, stderr: str, run: dict) -> dict:
    """Persist distinct native streams and return compact readback metadata."""
    stdout_path = work_dir / f"{stem}.stdout"
    stderr_path = work_dir / f"{stem}.stderr"
    log_path = work_dir / f"{stem}.log"
    _aa.write_text(stdout_path, stdout)
    _aa.write_text(stderr_path, stderr)
    _aa.write_text(log_path, stdout + stderr)
    return dict(run, stdout_sha256=file_sha256(stdout_path), stderr_sha256=file_sha256(stderr_path),
                log_sha256=file_sha256(log_path), stdout_bytes=len(stdout.encode("utf-8")),
                stderr_bytes=len(stderr.encode("utf-8")))


def _query_result(body: str) -> str:
    if "SAT proof finished - no model found: SUCCESS!" in body:
        return "PROVED"
    if "SAT proof finished - model found: FAIL!" in body:
        return "REFUTED"
    if "SAT solving finished - no model found." in body:
        return "NO_UNDEF"
    if "SAT solving finished - model found:" in body:
        return "HAS_UNDEF"
    return "UNKNOWN"


def _transition_query_progress(log: str, planned: List[str]) -> dict:
    """Read only terminal-marked queries; started/truncated work remains UNKNOWN."""
    bodies = {}
    terminals = set()
    current = None
    for line in log.splitlines(keepends=True):
        record, separator, identifier = line.rstrip().partition(" ")
        if (separator and identifier and len(identifier.split()) == 1 and
                record in {"VIBEIC_TRANSITION_QUERY", "VIBEIC_TRANSITION_COMPLETE"}):
            if record == "VIBEIC_TRANSITION_QUERY":
                current = identifier
                bodies[current] = ""
            else:
                terminals.add(identifier)
        elif current is not None:
            bodies[current] += line
    by_identity = {}
    for ident in planned:
        if ident in terminals and ident in bodies:
            by_identity[ident] = {"status": "COMPLETED", "result": _query_result(bodies[ident])}
        elif ident in bodies:
            by_identity[ident] = {"status": "UNKNOWN", "result": "UNKNOWN",
                                  "reason": "query started without native terminal marker"}
        else:
            by_identity[ident] = {"status": "NOT_STARTED", "result": "UNKNOWN"}
    return {"planned": len(planned), "started": sum(k in bodies for k in planned),
            "completed": sum(v["status"] == "COMPLETED" for v in by_identity.values()),
            "unknown": sorted(k for k, v in by_identity.items() if v["status"] == "UNKNOWN"),
            "not_started": sorted(k for k, v in by_identity.items() if v["status"] == "NOT_STARTED"),
            "by_identity": by_identity}


def _cofactor_payload_support(model: dict, rows: List[dict], work_dir: Path,
                              container: Optional[str] = None) -> Tuple[dict, dict]:
    """Native cofactor support, conservatively bounding shared payload roots.

    Only combinational constant propagation/cleanup runs here. Q and data are
    shared free inputs, and the two reset values were already substituted by
    the existing paired producer. No data assignment or assumption is added.
    A remaining structural dependency may overapproximate functional support;
    it can refuse an ambiguous mask, never supply a lucky-data force proof.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    initial = work_dir / "cofactor_support_input.json"
    normalized = work_dir / "cofactor_support_normalized.json"
    prior_normalized = normalized.stat() if normalized.exists() else None
    ys, log_path = work_dir / "cofactor_support.ys", work_dir / "cofactor_support.log"
    _aa.write_json(initial, model)
    _aa.write_text(ys, f"read_json {initial.resolve()}\nhierarchy -top transition_pair\n"
                   f"opt_expr\nopt_clean\nwrite_json {normalized.resolve()}\n")
    if container:
        import _container_exec as ce
        argv = ce.exec_argv(container, f"yosys -Q -T -s {ys.resolve()}", tag="formal_structural_check")
    else:
        argv = ["yosys", "-Q", "-T", "-s", str(ys.resolve())]
    rc, stdout, stderr, run = _native_query_run(
        argv, container=container, command=f"yosys -Q -T -s {ys.resolve()}")
    log = stdout + stderr
    native = _native_artifacts(work_dir, "cofactor_support", stdout, stderr, run)
    info = {"native_exit_code": rc, "status": "UNAVAILABLE", "rows": [],
            "input_sha256": file_sha256(initial), "script_sha256": file_sha256(ys),
            "log_sha256": native["log_sha256"], "native_run": native,
            "scope": "native normalized structural support; conservative"}
    payloads = {}
    try:
        if rc:
            return info, payloads
        mod = json.loads(normalized.read_text())["modules"]["transition_pair"]
        info["normalized_sha256"] = file_sha256(normalized)
        current_normalized = normalized.stat()
        info["normalization_output_current"] = (prior_normalized is None or
            (current_normalized.st_ino, current_normalized.st_mtime_ns, current_normalized.st_ctime_ns) !=
            (prior_normalized.st_ino, prior_normalized.st_mtime_ns, prior_normalized.st_ctime_ns))
        roots = {port["bits"][0]: int(name[len("input_"):])
                 for name, port in mod["ports"].items()
                 if port["direction"] == "input" and name.startswith("input_")
                 and len(port["bits"]) == 1}
        drivers, memo = _drivers(mod), {}

        def support(bit, seen=frozenset()):
            if not isinstance(bit, int):
                return set()
            if bit in roots:
                return {roots[bit]}
            if bit in memo:
                return memo[bit]
            if bit in seen or bit not in drivers:
                return None
            cell = drivers[bit]
            found = set()
            for pin, values in (cell.get("connections") or {}).items():
                if cell.get("port_directions", {}).get(pin) == "input":
                    for value in values:
                        below = support(value, seen | {bit})
                        if below is None:
                            memo[bit] = None
                            return None
                        found.update(below)
            memo[bit] = found
            return found

        for row in rows:
            if row.get("unsupported"):
                continue
            pair = [support(mod["ports"][row["query_ports"][f"n{arm}"]]["bits"][0])
                    for arm in (0, 1)]
            if any(value is None for value in pair):
                info["rows"].append({"q": row["q"], "status": "UNAVAILABLE"})
                continue
            shared = pair[0] & pair[1]
            payloads[row["q"]] = shared
            info["rows"].append({"q": row["q"], "status": "NATIVE_NORMALIZED_COFACTOR_SUPPORT",
                "cofactor0_bits": sorted(pair[0]), "cofactor1_bits": sorted(pair[1]),
                "shared_payload_bits": sorted(shared),
                "total_force_arms": [arm for arm in (0, 1) if any(
                    mod["ports"].get(row["query_ports"].get(f"{role}_guard{arm}"), {}).get("bits") == ["1"]
                    for role in ("force_zero", "force_one"))]})
        info["status"] = "NATIVE_NORMALIZED_COFACTOR_SUPPORT"
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        info["reason"] = str(exc)
    return info, payloads


def _reset_row_cone_eligibility(model: dict) -> dict:
    """Off-cone removal is exact only when every input assignment extends.

    A single-driver DAG of total native Boolean functions has that property,
    including undef sources. Feedback, multiple drivers or other cell kinds
    retain the original whole-module SAT queries, which may constrain shared
    inputs outside a row's cone. This selects an optimization, never credit.
    """
    mod = model["modules"]["transition_pair"]
    total = {"$and", "$or", "$xor", "$xnor", "$not", "$mux", "$eq", "$ne",
             "$eqx", "$nex", "$logic_not", "$logic_and", "$logic_or",
             "$reduce_and", "$reduce_or", "$reduce_xor", "$reduce_xnor",
             "$reduce_bool", "$add", "$sub", "$mul", "$shiftx"}
    # Native add/sub/mul are finite-width total functions. shiftx is total in
    # Yosys's undef-aware value domain (out-of-range bits remain undef).
    # Cone selection never defines those bits: the existing undef queries
    # and every role/priority arm still run with -enable_undef.
    cells = mod.get("cells") or {}
    if any(p.get("direction") not in {"input", "output"} for p in mod["ports"].values()):
        return {"eligible": False, "reason": "unknown-native-pin-direction"}
    inputs = {b for p in mod["ports"].values() if p["direction"] == "input"
              for b in p["bits"] if isinstance(b, int)}
    drivers = {}
    for name, cell in cells.items():
        if cell["type"] not in total:
            return {"eligible": False, "reason": "non-total-or-unsupported-cell"}
        if any(cell.get("port_directions", {}).get(pin) not in {"input", "output"}
               for pin in cell["connections"]):
            return {"eligible": False, "reason": "unknown-native-pin-direction"}
        for pin, bits in cell["connections"].items():
            if cell["port_directions"][pin] == "output":
                for bit in bits:
                    if not isinstance(bit, int) or bit in inputs or bit in drivers:
                        return {"eligible": False, "reason": "non-unique-output-driver"}
                    drivers[bit] = name
    dependencies, users = {}, {name: set() for name in cells}
    for name, cell in cells.items():
        dependencies[name] = {drivers[b]
            for pin, bits in cell["connections"].items()
            if cell["port_directions"][pin] == "input"
            for b in bits if b in drivers}
        for driver in dependencies[name]:
            users[driver].add(name)
    pending = [name for name, deps in dependencies.items() if not deps]
    visited = 0
    while pending:
        driver = pending.pop()
        visited += 1
        for user in users[driver]:
            dependencies[user].remove(driver)
            if not dependencies[user]:
                pending.append(user)
    return {"eligible": visited == len(cells),
            "reason": "single-driver-total-boolean-dag" if visited == len(cells)
                      else "combinational-feedback"}


def _priority_load_retention(mod: dict, reset_bit: int, rows: List[dict],
                             work_dir: Path, container: Optional[str] = None) -> dict:
    """Certify priority-load control with an existing Q-retaining fallback.

    A disabled load may expose a lower-priority shift; the two data cofactors
    need not agree. Cut ALL reset paths at one original mux-select strobe,
    prove its load value is monotonically controlled by reset, and prove an unrestricted
    discriminating load-versus-source-retention witness. The load payload
    cannot depend on target Q or the declared reset. This is a retention role,
    never a reset force or a post-reset state assumption.
    """
    import copy
    import hashlib
    empty = {"status": "NOT_APPLICABLE", "certificates": []}
    senses = {r.get("polarity") for r in rows if r.get("classification") == "RESET_FORCE"}
    if len(senses) != 1 or not senses <= {"active_high", "active_low"}:
        return empty
    active = int(next(iter(senses)) == "active_high")
    targets = [r for r in rows if r.get("classification") == "UNRESOLVED_DATA_DEPENDENCE"
               and not r.get("unsupported") and set(r.get("controls", {})) <= {"D", "EN"}]
    if not targets:
        return empty
    drivers = _drivers(mod)
    qbits = {q for _, c, k in _cells(mod) if k == "ff" for q in _bits(c, "Q")}
    inputs = {b for p in mod.get("ports", {}).values() if p.get("direction") == "input"
              for b in p.get("bits", [])}
    reset_cone = _cone(mod, reset_bit)

    fingerprints = {}

    def fingerprint(bit, seen=frozenset()):
        # Identical combinational expressions are the same cut even if proc
        # emitted duplicate cells. Q/data roots retain their exact identity.
        if not isinstance(bit, int) or bit in inputs or bit in qbits:
            return str(bit)
        if bit in fingerprints:
            return fingerprints[bit]
        cell = drivers.get(bit)
        if bit in seen or cell is None or _kind(cell.get("type", "")) != "comb":
            return None
        outputs = [(pin, i) for pin, values in cell["connections"].items()
                   if cell["port_directions"].get(pin) == "output"
                   for i, value in enumerate(values) if value == bit]
        signature = [cell["type"], cell.get("parameters", {}), outputs,
            [(pin, [fingerprint(v, seen | {bit}) for v in values])
             for pin, values in sorted(cell["connections"].items())
             if cell["port_directions"].get(pin) == "input"]]
        digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        fingerprints[bit] = digest
        return digest

    def fanin(roots, cut=frozenset()):
        pending, seen = list(roots), set()
        while pending:
            bit = pending.pop()
            # Literal undef is a dependency terminal, never a defined value.
            # Both cut transitions must separately pass native definedness;
            # this also permits optimizer-inserted don't-cares behind EN.
            if bit in seen or bit in ("0", "1", "x", "z"):
                continue
            if not isinstance(bit, int):
                return None
            seen.add(bit)
            if bit in cut or bit in qbits or bit in inputs:
                continue
            cell = drivers.get(bit)
            if cell is None or _kind(cell.get("type", "")) != "comb":
                return None
            pending.extend(v for pin, values in cell.get("connections", {}).items()
                           if cell.get("port_directions", {}).get(pin) == "input" for v in values)
        return seen

    groups = {}
    for row in targets:
        roots = [row["controls"]["D"][row["bit_index"]], *row["controls"].get("EN", [])]
        full = fanin(roots)
        if full is None:
            continue
        choices = set()
        for bit in full:
            cell = drivers.get(bit, {})
            if cell.get("type") in {"$mux", "$bwmux"}:
                choices.update(s for s in cell["connections"]["S"] if s in reset_cone)
        for cut in sorted(choices):
            cell = drivers.get(cut, {})
            outputs = [v for pin, values in cell.get("connections", {}).items()
                       if cell.get("port_directions", {}).get(pin) == "output" for v in values]
            aliases = {b for b in full if isinstance(b, int) and fingerprint(b) == fingerprint(cut)}
            # Every alias being cut must have a dedicated one-bit driver.
            if any([v for pin, values in drivers.get(b, {}).get("connections", {}).items()
                    if drivers[b]["port_directions"].get(pin) == "output" for v in values] != [b]
                   for b in aliases):
                continue
            remaining = fanin(roots, aliases)
            if outputs == [cut] and remaining is not None and reset_bit not in remaining:
                groups.setdefault((cut, tuple(sorted(aliases))), []).append(row)
    if not groups:
        return empty
    original, _ = _transition_pair(mod, reset_bit, observations={str(c): c for c, _ in groups})
    if not _reset_row_cone_eligibility(original)["eligible"]:
        return empty
    certificates, runs = [], []
    for (cut, aliases), selected in groups.items():
        directory = work_dir / f"cut_{cut}"
        directory.mkdir(parents=True, exist_ok=True)
        cut_mod = copy.deepcopy(mod)
        cut_mod["cells"] = {n: c for n, c in cut_mod["cells"].items()
                            if not any(c == drivers[b] for b in aliases)}
        for cell in cut_mod["cells"].values():
            cell["connections"] = {pin: [cut if v in aliases else v for v in values]
                                   for pin, values in cell["connections"].items()}
        cut_mod["ports"]["priority_load_strobe"] = {"direction": "input", "bits": [cut]}
        value_model, value_rows = _transition_pair(cut_mod, cut)
        support, payloads = _cofactor_payload_support(value_model, value_rows, directory, container)
        if (support.get("native_exit_code") != 0 or not support.get("normalization_output_current")
                or support.get("status") != "NATIVE_NORMALIZED_COFACTOR_SUPPORT"):
            runs.append({"cut": cut, "support": support, "status": "INCOMPLETE"})
            continue
        model, cut_rows = _transition_pair(cut_mod, cut, payloads)
        if not _reset_row_cone_eligibility(model)["eligible"]:
            continue
        module = model["modules"]["transition_pair"]
        # Combine the actual reset pair and the strobe pair, sharing roots by
        # their original input/Q identity, never by an accidental wire number.
        shared = {p["bits"][0]: module["ports"][name]["bits"][0]
                  for name, p in original["modules"]["transition_pair"]["ports"].items()
                  if p["direction"] == "input"}
        next_bit = 1 + max(v for c in module["cells"].values()
                           for values in c["connections"].values() for v in values if isinstance(v, int))

        def remap(value):
            nonlocal next_bit
            if not isinstance(value, int):
                return value
            if value not in shared:
                shared[value] = next_bit
                next_bit += 1
            return shared[value]

        actual = original["modules"]["transition_pair"]
        for name, cell in actual["cells"].items():
            copied = copy.deepcopy(cell)
            copied["connections"] = {p: [remap(v) for v in values]
                                     for p, values in cell["connections"].items()}
            module["cells"]["actual_reset_" + name] = copied
        for arm in (0, 1):
            p = actual["ports"][f"observe_{cut}_{arm}"]
            module["ports"][f"strobe_{arm}"] = {"direction": "output", "bits": [remap(p["bits"][0])]}
        module["netnames"] = {}

        def gate(kind, a, b=None):
            nonlocal next_bit
            y = next_bit
            next_bit += 1
            con = {"A": [a], "Y": [y]}
            params = {"A_SIGNED": 0, "A_WIDTH": 1, "Y_WIDTH": 1}
            if b is not None:
                con["B"] = [b]
                params.update(B_SIGNED=0, B_WIDTH=1)
            module["cells"][f"load_role_{y}"] = {"type": kind, "parameters": params,
                "connections": con, "port_directions": {p: "output" if p == "Y" else "input" for p in con}}
            return y

        def port(name, bit):
            module["ports"][name] = {"direction": "output", "bits": [bit]}
            return name

        specs, queries = {}, {}
        support_by_q = {r["q"]: r for r in support["rows"]}
        qrows = {r["q"]: r for r in cut_rows if not r.get("unsupported")}
        for row in selected:
            q = row["q"]
            pair = qrows.get(q)
            data = support_by_q.get(q, {})
            if pair is None or data.get("status") != "NATIVE_NORMALIZED_COFACTOR_SUPPORT":
                continue
            for load in (0, 1):
                if q in data.get(f"cofactor{load}_bits", [q]):
                    continue
                fallback = 1 - load
                ports = pair["query_ports"]
                on = [module["ports"][f"strobe_{arm}"]["bits"][0] for arm in (0, 1)]
                if not load:
                    on = [gate("$not", v) for v in on]
                suppression = gate("$or", gate("$not", on[active]), on[1-active])
                activation = gate("$or", gate("$not", on[1-active]), on[active])
                guard = module["ports"][ports[f"retain_guard{fallback}"]]["bits"][0]
                loaded = module["ports"][ports[f"n{load}"]]["bits"][0]
                current = module["ports"][f"input_{q}"]["bits"][0]
                different = gate("$ne", loaded, current)
                witnesses = [gate("$and", gate("$and", on[arm], gate("$not", on[1-arm])),
                                  gate("$and", guard, different)) for arm in (1-active, active)]
                key = f"q{q}_load{load}"
                checks = {"suppression": (port(key+"_suppression", suppression), "1"),
                          "activation": (port(key+"_activation", activation), "1"),
                          "suppression_retention": (port(key+"_suppression_witness", witnesses[0]), "0"),
                          "activation_retention": (port(key+"_activation_witness", witnesses[1]), "0"),
                          "defined_load": (ports[f"n{load}"], None),
                          "defined_fallback": (ports[f"n{fallback}"], None),
                          "load_zero": (ports[f"n{load}"], "0"),
                          "load_one": (ports[f"n{load}"], "1"),
                          "retention_valid": (ports[f"retain_valid{fallback}"], "1")}
                for arm in (0, 1):
                    for proof in ("roles_disjoint", "roles_cover"):
                        checks[f"{proof}{arm}"] = ports[f"{proof}{arm}"], "1"
                specs[key] = row, load, data, checks
                queries.update({key+"_"+name: value for name, value in checks.items()})
        if not queries:
            continue
        model_path = directory / "priority_load_pair.json"
        _aa.write_json(model_path, model)
        script = [f"read_json {model_path.resolve()}", "hierarchy -top transition_pair",
                  "log VIBEIC_TRANSITION_QUERY domain", "sat -enable_undef -set-def-inputs",
                  "log VIBEIC_TRANSITION_COMPLETE domain"]
        for ident, (name, value) in queries.items():
            option = f"-set-any-undef {name}" if value is None else f"-prove {name} {value}"
            script += ["select -module transition_pair", f"select w:{name} %ci*",
                       "log VIBEIC_TRANSITION_QUERY " + ident,
                       f"sat -timeout 10 -enable_undef -set-def-inputs {option} -show-inputs -show {name}",
                       "log VIBEIC_TRANSITION_COMPLETE " + ident, "select -clear"]
        ys = directory / "priority_load.ys"
        _aa.write_text(ys, "\n".join(script)+"\n")
        command = f"yosys -Q -T -s {ys.resolve()}"
        if container:
            import _container_exec as ce
            argv = ce.exec_argv(container, command, tag="formal_structural_check")
        else:
            argv = ["yosys", "-Q", "-T", "-s", str(ys.resolve())]
        rc, stdout, stderr, run = _native_query_run(argv, container=container, command=command)
        native = _native_artifacts(directory, "priority_load", stdout, stderr, run)
        progress = _transition_query_progress(stdout+stderr, ["domain", *queries])
        complete = (rc == 0 and progress["completed"] == progress["planned"] and not progress["unknown"]
                    and progress["by_identity"]["domain"]["result"] == "HAS_UNDEF")
        runs.append({"cut": cut, "native_exit_code": rc, "native_run": native,
                     "query_progress": progress, "support": support,
                     "model_sha256": file_sha256(model_path), "script_sha256": file_sha256(ys)})
        for key, (row, load, data, checks) in specs.items():
            answers = {name: progress["by_identity"][key+"_"+name]["result"] for name in checks}
            expected = {name: "PROVED" for name in checks}
            expected.update(defined_load="NO_UNDEF", defined_fallback="NO_UNDEF",
                            load_zero="REFUTED", load_one="REFUTED")
            directions = [name for name, opposite in (("suppression", "activation"), ("activation", "suppression"))
                          if answers[name] == "PROVED" and answers[opposite] == "REFUTED"
                          and answers[name+"_retention"] == "REFUTED"
                          and answers[opposite+"_retention"] == "PROVED"]
            directional = {"suppression", "activation", "suppression_retention", "activation_retention"}
            if complete and len(directions) == 1 and all(answers[k] == v for k, v in expected.items() if k not in directional):
                certificates.append({"q": row["q"], "status": "CERTIFIED", "cut_strobe": cut, "cut_aliases": list(aliases),
                    "load_strobe_value": load, "active_reset_value": active,
                    "scope": "unrestricted one-step shared current Q and data",
                    "complete_reset_fanin_cut": True, "target_q_absent_from_load_support": True,
                    "post_reset_state_restriction": False, "load_support": data[f"cofactor{load}_bits"],
                    "direction": directions[0], "directional_control": answers[directions[0]],
                    "discriminating_retention": answers[directions[0]+"_retention"],
                    "queries": answers, "query_prefix": key, "work_dir": str(directory)})
    progress = {"planned": sum(r.get("query_progress", {}).get("planned", 0) for r in runs),
                "completed": sum(r.get("query_progress", {}).get("completed", 0) for r in runs)}
    return {"status": "COMPLETED" if all(r.get("native_exit_code") == 0 for r in runs) else "INCOMPLETE",
            "native_exit_code": 0 if runs and all(r.get("native_exit_code") == 0 for r in runs) else None,
            "query_progress": progress, "runs": runs, "certificates": certificates}


def _post_reset_independence(model: dict, rows: List[dict], work_dir: Path,
                             container: Optional[str] = None) -> dict:
    """Prove residual data independence after a measured synchronous reset edge.

    A total-force query proves Q(t+1)=constant for *all* current Q/data. Those
    constants therefore overapproximate the post-reset state: every other Q
    and every data input stays free. A second native query may prove the two
    reset cofactors equal on that reachable domain. This is a composed,
    post-reset fact, never independence for arbitrary pre-reset state.

    Only already-defined residual transition rows are eligible. A
    partial force, opposite edge/clock, literal undef or unfinished query
    cannot supply a premise. The original mixed-data refusal remains live.
    """
    mod = model["modules"]["transition_pair"]
    forces = [r for r in rows if r.get("classification") == "RESET_FORCE"]
    polarities = {r.get("polarity") for r in forces}
    candidates = [r for r in rows if not r.get("unsupported") and
                  r.get("classification") == "UNRESOLVED_DATA_DEPENDENCE"]
    if len(polarities) != 1 or not candidates:
        return {"status": "NOT_APPLICABLE", "certificates": []}
    polarity = next(iter(polarities))
    if polarity not in {"active_high", "active_low"}:
        return {"status": "NOT_APPLICABLE", "certificates": []}
    arm = int(polarity == "active_high")

    def clock(row):
        bits = row.get("clock") or []
        edge = _param_bit(row.get("parameters", {}).get("CLK_POLARITY"))
        if len(bits) != 1 or not isinstance(bits[0], int) or edge not in (0, 1):
            return None
        return bits[0], edge

    groups = {}
    for row in candidates:
        key = clock(row)
        if key is None or any(p in row.get("controls", {}) for p in _ASYNC_PINS):
            continue
        premises = []
        for force in forces:
            if (clock(force) != key or force.get("timing") != "synchronous" or not force.get("total_force")
                    or any(p in force.get("controls", {}) for p in _ASYNC_PINS)):
                continue
            a = force.get("native_queries", {})
            values = [v for v, name in ((0, "zero"), (1, "one")) if a.get(f"{name}{arm}") == "PROVED"]
            port = f"input_{force['q']}"
            if (a.get(f"undef{arm}") != "NO_UNDEF" or len(values) != 1 or
                    mod.get("ports", {}).get(port, {}).get("direction") != "input" or
                    len(mod["ports"][port]["bits"]) != 1):
                continue
            premises.append({"q": force["q"], "port": port, "value": values[0],
                             "query": f"{'zero' if values[0] == 0 else 'one'}{arm}"})
        if premises:
            groups.setdefault(key, {"premises": premises, "rows": []})["rows"].append(row)
    if not groups:
        return {"status": "NOT_APPLICABLE", "certificates": []}
    work_dir.mkdir(parents=True, exist_ok=True)
    model_path = work_dir / "transition_pair.json"
    _aa.write_json(model_path, model)
    script = [f"read_json {model_path.resolve()}", "hierarchy -top transition_pair"]
    specs, domains = {}, {}
    cone = _reset_row_cone_eligibility(model)
    for group_index, (key, group) in enumerate(sorted(groups.items())):
        sets = " ".join(f"-set {p['port']} {p['value']}" for p in group["premises"])
        domain = f"post_{group_index}_domain"
        domains[key] = domain
        script += ["log VIBEIC_TRANSITION_QUERY " + domain,
                   f"sat -timeout 10 -enable_undef -set-def-inputs {sets}",
                   "log VIBEIC_TRANSITION_COMPLETE " + domain]
        for row_index, row in enumerate(group["rows"]):
            ident = f"post_{group_index}_{row_index}_equal"
            specs[ident] = key, row
            port = row["query_ports"]["equal"]
            if cone["eligible"]:
                script += ["select -module transition_pair", f"select w:{port} %ci*"]
            script += ["log VIBEIC_TRANSITION_QUERY " + ident,
                       f"sat -timeout 10 -enable_undef -set-def-inputs {sets} -prove {port} 1 -show-inputs -show {port}",
                       "log VIBEIC_TRANSITION_COMPLETE " + ident]
            if cone["eligible"]:
                script.append("select -clear")
    ys = work_dir / "post_reset.ys"
    _aa.write_text(ys, "\n".join(script) + "\n")
    inner = f"yosys -Q -T -s {ys.resolve()}"
    if container:
        import _container_exec as ce
        argv = ce.exec_argv(container, inner, tag="formal_structural_check")
    else:
        argv = ["yosys", "-Q", "-T", "-s", str(ys.resolve())]
    rc, stdout, stderr, run = _native_query_run(argv, container=container, command=inner)
    native = _native_artifacts(work_dir, "post_reset", stdout, stderr, run)
    progress = _transition_query_progress(stdout + stderr, [*domains.values(), *specs])
    complete = (rc == 0 and progress["completed"] == progress["planned"] and not progress["unknown"]
                and all(a["result"] != "UNKNOWN" for a in progress["by_identity"].values()))
    certificates = []
    for ident, (key, row) in specs.items():
        answer = progress["by_identity"][ident]
        domain = progress["by_identity"][domains[key]]
        if complete and domain["result"] == "HAS_UNDEF" and answer["result"] == "PROVED":
            certificates.append({"q": row["q"], "status": "CERTIFIED",
                "rule": "POST_RESET_COFACTOR_INDEPENDENCE", "active_reset_value": arm,
                "scope": "current state immediately follows an asserted reset edge on the same clock and edge",
                "clock": key[0], "clock_polarity": key[1], "premises": groups[key]["premises"],
                "domain_query": domains[key], "equality_query": ident,
                "other_current_q_and_data": "free; no input or scratch-value restriction"})
    return {"status": "COMPLETED" if complete else "INCOMPLETE", "native_exit_code": rc,
            "native_run": native, "query_progress": progress, "certificates": certificates,
            "model_sha256": file_sha256(model_path), "script_sha256": file_sha256(ys)}


def reset_control_mapping(netlist: dict, raw: Optional[dict], top: str,
                          signal: str, work_dir: Path,
                          container: Optional[str] = None) -> dict:
    """Classify all current identities using native paired-cofactor queries.

    This is the reset mapping of this existing owner, not a new flow gate.
    UNSUPPORTED/UNKNOWN identities remain named and prevent full polarity PASS.
    SAT countermodels classify functions; they are not a DUT formal FAIL.
    Raw undef may instead carry a complete-graph one-step reset-independence
    certificate; its value and native query population remain unchanged.
    """
    result = {"signal": signal, "rows": [], "unresolved": [], "complete": False,
              "shared_current_q_and_data": True}
    tm = _top_module(netlist, top)
    if tm is None:
        return dict(result, unresolved=["missing current netlist"])
    _, mod = tm
    # opt_dff can replace a reset-only Q by a constant, or merge source Q
    # identities. That optimized representation cannot supply the complete
    # independent current-state denominator. Use the SAME invocation's raw
    # proc/flatten twin as one whole model in that case; do not invent an
    # optimized Q, drop the identity, or combine unrelated state snapshots.
    raw_tm = _top_module(raw, top) if isinstance(raw, dict) else None
    raw_undef_q = _raw_undef_q(raw_tm[1]) if raw_tm is not None else set()
    result["state_model"] = "optimized_current_source"
    if raw_tm is not None:
        raw_mod = raw_tm[1]
        raw_q_bits = {q for _, c, k in _cells(raw_mod) if k == "ff" for q in _bits(c, "Q")}
        optimized_q = {q for _, c, k in _cells(mod) if k == "ff" for q in _bits(c, "Q")}
        projection = {q: set() for q in raw_q_bits}
        values = {q: set() for q in raw_q_bits}
        for name, net in (raw_mod.get("netnames") or {}).items():
            other = (mod.get("netnames") or {}).get(name, {}).get("bits") or []
            for index, q in enumerate(net.get("bits") or []):
                if q in raw_q_bits and index < len(other):
                    target = other[index]
                    if target in optimized_q:
                        projection[q].add(target)
                    elif isinstance(target, str):
                        values[q].add(target)
        targets = [next(iter(bits)) for bits in projection.values() if len(bits) == 1]
        result["optimized_identity_projection"] = [
            {"raw_q": q, "optimized_q": sorted(projection[q]),
             "optimized_constants": sorted(values[q])} for q in sorted(raw_q_bits)]
        explained = all((len(projection[q]) == 1 and not values[q]) or
                        (not projection[q] and len(values[q]) == 1 and values[q] <= {"0", "1"})
                        for q in raw_q_bits)
        result["optimized_projection_explained"] = explained
        if raw_undef_q or (explained and (any(values.values()) or len(set(targets)) != len(targets))):
            mod = raw_mod
            result["state_model"] = "raw_pre_cleanup_current_source"
            result["state_model_reason"] = ("raw literal undef must remain in the paired transition model" if raw_undef_q else
                "optimization eliminated or merged original current-Q identities")
    bit, why = _port_bit(mod, signal)
    if bit is None:
        return dict(result, unresolved=[why])
    census = _state_census(mod, netlist)
    unsupported = census["latch"] + census["memory"] + census["unclassified"]
    if unsupported:
        return dict(result, unresolved=unsupported)
    value_model, value_rows = _transition_pair(mod, bit)
    payload_analysis, payload_by_q = _cofactor_payload_support(
        value_model, value_rows, work_dir, container)
    result["payload_analysis"] = payload_analysis
    payload_rows = {r["q"]: r for r in payload_analysis["rows"]}
    model, rows = _transition_pair(mod, bit, payload_by_q)
    for row in rows:
        row["payload_support"] = payload_rows.get(row["q"], {"status": "UNAVAILABLE"})
        if not row.get("unsupported") and row["q"] not in payload_by_q:
            result["unresolved"].append(f"{row['cell']}.Q[{row['bit_index']}]: shared cofactor payload support unavailable")
    result["rows"] = rows
    # Map every raw Q bit into current Q using an exact common alias/index.
    identities = []
    current_q = {r["q"] for r in rows}
    if raw_tm is None:
        result["unresolved"].append("missing raw state census")
    else:
        raw_mod = raw_tm[1]
        raw_census = _state_census(raw_mod, raw)
        result["unresolved"] += raw_census["latch"] + raw_census["memory"] + raw_census["unclassified"]
        aliases = {}
        raw_q = {q for _, c, k in _cells(raw_mod) if k == "ff" for q in _bits(c, "Q")}
        undef_q = raw_undef_q
        for name, net in (raw_mod.get("netnames") or {}).items():
            other = (mod.get("netnames") or {}).get(name, {}).get("bits") or []
            for i, qb in enumerate(net.get("bits") or []):
                if isinstance(qb, int) and i < len(other) and other[i] in current_q:
                    aliases.setdefault(qb, set()).add(other[i])
        raw_sources = {}
        for qb in raw_q:
            for target in aliases.get(qb, set()):
                raw_sources.setdefault(target, set()).add(qb)
        row_by_q = {r["q"]: r for r in rows}
        cert_targets = [(name, i, next(iter(aliases[qb])))
                        for name, cell, kind in _cells(raw_mod) if kind == "ff"
                        for i, qb in enumerate(cell.get("connections", {}).get("Q") or [])
                        if qb in undef_q and len(aliases.get(qb, set())) == 1
                        and len(raw_sources[next(iter(aliases[qb]))]) == 1
                        and not row_by_q[next(iter(aliases[qb]))].get("unsupported")]
        certificates = _raw_reset_independence(raw_mod, signal, cert_targets)
        for name, cell, kind in _cells(raw_mod):
            if kind == "ff":
                for i, qb in enumerate(cell.get("connections", {}).get("Q") or []):
                    mapped = aliases.get(qb, set())
                    identities.append({"cell": name, "q_index": i,
                                       "raw_q": qb, "current_q": sorted(mapped),
                                       "literal_undef_in_transition": qb in undef_q})
                    if qb in undef_q:
                        for row in rows:
                            if row["q"] in mapped:
                                # Keep an earlier clock/storage/identity refusal:
                                # raw undef cannot erase it and admit a certificate.
                                if not row.get("unsupported"):
                                    row["unsupported"] = "literal-X/undef retained from raw next-state transition"
                                cert = certificates.get((name, i))
                                if cert is not None:
                                    identities[-1]["reset_independence_certificate"] = cert
                                    row["reset_independence_certificate"] = cert
                                    if (cert.get("complete_raw_fanin") and cert.get("reset_reachable") and
                                            payload_analysis.get("status") == "NATIVE_NORMALIZED_COFACTOR_SUPPORT" and
                                            payload_analysis.get("native_exit_code") == 0 and
                                            payload_analysis.get("native_run", {}).get("termination") == "COMPLETED" and
                                            payload_analysis.get("normalization_output_current") and
                                            row["payload_support"].get("total_force_arms") and
                                            row["unsupported"] == "literal-X/undef retained from raw next-state transition"):
                                        row["raw_undef_native_candidate"] = True
                    if len(mapped) != 1:
                        result["unresolved"].append(f"{name}.Q[{i}]: missing/ambiguous current Q identity")
    result["raw_identities"] = identities
    work_dir.mkdir(parents=True, exist_ok=True)
    model_path = work_dir / "transition_pair.json"
    _aa.write_json(model_path, model)
    row_cone = _reset_row_cone_eligibility(model)
    result["native_row_cone"] = row_cone
    script = [f"read_json {model_path.resolve()}", "hierarchy -top transition_pair",
              "log VIBEIC_TRANSITION_QUERY domain",
              "sat -timeout 10 -enable_undef -set-def-inputs -show-inputs",
              "log VIBEIC_TRANSITION_COMPLETE domain"]
    specs = {}
    for i, row in enumerate(rows):
        if row.get("unsupported") and not row.get("raw_undef_native_candidate"):
            continue
        ports = row["query_ports"]
        # Import the complete fan-in of every value/guard observed for this
        # storage bit. Union all roots before expanding Yosys's selection
        # stack; expanding only its last root leaves other drivers unmodeled.
        # Shared current-Q/data inputs remain module inputs, with the same
        # defined-input constraints. Counterexamples show all shared inputs
        # and this row's modeled outputs, never unmodeled unrelated outputs.
        observed = sorted(set(ports.values()))
        if row_cone["eligible"]:
            script += ["select -module transition_pair",
                       "select " + " ".join("w:" + p for p in observed) + " %% %ci*"]
        row["native_witness_scope"] = {"shared_inputs": "all module inputs",
            "outputs": observed if row_cone["eligible"] else "all module outputs"}
        queries = {"undef0": ("n0", None), "undef1": ("n1", None),
            "zero0": ("n0", "0"), "one0": ("n0", "1"),
            "zero1": ("n1", "0"), "one1": ("n1", "1"),
            "retain0": ("retain0", "1"), "retain1": ("retain1", "1"),
            "equal": ("equal", "1"), "high": ("high_violation", "0"),
            "low": ("low_violation", "0")}
        for arm in (0, 1):
            for role in ("force_zero", "force_one", "retain", "data"):
                queries[f"{role}_reachable{arm}"] = (f"{role}_guard{arm}", "0")
                if role != "data":
                    queries[f"{role}_valid{arm}"] = (f"{role}_valid{arm}", "1")
            for proof in ("roles_disjoint", "roles_cover"):
                queries[f"{proof}{arm}"] = (f"{proof}{arm}", "1")
            if f"priority_domain{arm}" in ports:
                queries[f"priority_domain{arm}"] = (f"priority_domain{arm}", "0")
                queries[f"priority_discriminating{arm}"] = (f"priority_discriminating{arm}", "0")
                queries[f"priority_valid{arm}"] = (f"priority_valid{arm}", "1")
        for key, (port, value) in queries.items():
            ident = f"{i}_{key}"
            specs[ident] = (i, key)
            script.append("log VIBEIC_TRANSITION_QUERY " + ident)
            option = f"-set-any-undef {ports[port]}" if value is None else f"-prove {ports[port]} {value}"
            shown = (" ".join("-show " + p for p in observed)
                     if row_cone["eligible"] else "-show-outputs")
            script.append(f"sat -timeout 10 -enable_undef -set-def-inputs {option} -show-inputs {shown}")
            script.append("log VIBEIC_TRANSITION_COMPLETE " + ident)
        if row_cone["eligible"]:
            script.append("select -clear")
    ys = work_dir / "transition_pair.ys"
    _aa.write_text(ys, "\n".join(script) + "\n")
    inner = f"yosys -Q -T -s {ys.resolve()}"
    if container:
        import _container_exec as ce
        argv = ce.exec_argv(container, inner, tag="formal_structural_check")
    else:
        argv = ["yosys", "-Q", "-T", "-s", str(ys.resolve())]
    rc, stdout, stderr, run = _native_query_run(
        argv, container=container, command=f"yosys -Q -T -s {ys.resolve()}")
    log = stdout + stderr
    native = _native_artifacts(work_dir, "transition_pair", stdout, stderr, run)
    progress = _transition_query_progress(log, ["domain", *specs])
    domain = progress["by_identity"]["domain"]
    domain_reachable = (domain["status"] == "COMPLETED" and
                        domain["result"] == "HAS_UNDEF")
    if not domain_reachable:
        result["unresolved"].append("paired current-Q/data domain has no measured reachable witness")
    answers = {ident: detail["result"] for ident, detail in progress["by_identity"].items()
               if ident != "domain"}
    for i, row in enumerate(rows):
        a = {key: answers.get(f"{i}_{key}", "UNKNOWN") for j, key in specs.values() if j == i}
        row["native_queries"] = a
        row["classification"] = "UNSUPPORTED"
        row["conditional_roles"] = [{"reset_value": arm,
            "role": role.upper(), "guard_port": row.get("query_ports", {}).get(f"{role}_guard{arm}"),
            "reachable": a.get(f"{role}_reachable{arm}") == "REFUTED",
            "domain_query": a.get(f"{role}_reachable{arm}", "UNKNOWN"),
            "implication_query": (a.get(f"{role}_valid{arm}", "UNKNOWN") if role != "data" else
                                  "RESIDUAL_DATA_NOT_RESET_FORCE")}
            for arm in (0, 1) for role in ("force_zero", "force_one", "retain", "data")]
        role_proofs = [a.get(f"{role}_valid{arm}") for arm in (0, 1)
                       for role in ("force_zero", "force_one", "retain")]
        role_proofs += [a.get(f"{proof}{arm}") for arm in (0, 1)
                        for proof in ("roles_disjoint", "roles_cover")]
        row["priority_domains"] = [{"reset_value": arm,
            "domain_query": a[f"priority_domain{arm}"],
            "domain_reachable": a[f"priority_domain{arm}"] == "REFUTED",
            "discriminating_query": a[f"priority_discriminating{arm}"],
            "discriminating": a[f"priority_discriminating{arm}"] == "REFUTED",
            "implication_query": a[f"priority_valid{arm}"],
            "credit": ("FEASIBLE_DIFFERING_NEXT_STATE" if
                       a[f"priority_discriminating{arm}"] == "REFUTED" else
                       "NOT_DISCRIMINATING")}
            for arm in (0, 1) if f"priority_domain{arm}" in a]
        role_proofs += [a[f"priority_valid{arm}"] for arm in (0, 1)
                        if f"priority_valid{arm}" in a]
        # The inactive arm may be undefined or defined but nonconstant. Only
        # the whole raw model may prove the opposite arm is a total, defined force for
        # every free current-Q/data/control input, with its actual priority.
        raw_force = []
        if (row.get("raw_undef_native_candidate") and domain_reachable and rc == 0
                and a and "UNKNOWN" not in a.values()):
            for arm in (0, 1):
                active_proofs = [a.get(f"{role}_valid{arm}") for role in
                                 ("force_zero", "force_one", "retain")]
                active_proofs += [a.get(f"{proof}{arm}") for proof in
                                  ("roles_disjoint", "roles_cover")]
                active_proofs += [a[f"priority_valid{v}"] for v in (0, 1)
                                  if f"priority_valid{v}" in a]
                for value, role in ((0, "force_zero"), (1, "force_one")):
                    if (a.get(f"undef{arm}") == "NO_UNDEF" and
                            (a.get(f"undef{1-arm}") == "HAS_UNDEF" or
                             (a.get(f"undef{1-arm}") == "NO_UNDEF" and
                              a.get(f"zero{1-arm}") == "REFUTED" and
                              a.get(f"one{1-arm}") == "REFUTED" and
                              all(proof == "PROVED" for proof in role_proofs))) and
                            a.get(f"{'zero' if value == 0 else 'one'}{arm}") == "PROVED" and
                            a.get(f"{role}_reachable{arm}") == "REFUTED" and
                            all(proof == "PROVED" for proof in active_proofs) and
                            all(a.get(f"{other}_reachable{arm}") == "PROVED" for other in
                                ("force_one" if value == 0 else "force_zero", "retain", "data"))):
                        raw_force.append((arm, value))
        if (row.get("reset_independence_certificate", {}).get("status") == "CERTIFIED"
                and row.get("unsupported") == "literal-X/undef retained from raw next-state transition"):
            row["classification"] = "NO_DEPENDENCE"
            row["proof_basis"] = "complete_raw_transition_fanin"
            row["reason"] = "declared reset absent from complete raw one-step transition fan-in; literal undef retained"
        elif len(raw_force) == 1:
            arm, value = raw_force[0]
            row["classification"] = "RESET_FORCE"
            row["polarity"] = "active_high" if arm else "active_low"
            row["total_force"] = True
            row["timing"] = "asynchronous" if any(p in row["reset_reaches"] for p in _ASYNC_PINS) else "synchronous"
            row["proof_basis"] = "native_raw_paired_reset_domain"
            row["raw_reset_domain_proof"] = {"status": "CERTIFIED",
                "proof_basis": row["proof_basis"], "scope": "one_step_shared_current_q",
                "active_reset_value": arm, "inactive_reset_value": 1-arm,
                "force_value": value, "active_definedness": a[f"undef{arm}"],
                "inactive_definedness": a[f"undef{1-arm}"], "queries": dict(a)}
            row["reason"] = "native raw active reset arm is a total defined force; raw literal undef retained"
        elif row.get("unsupported") or rc or not a or "UNKNOWN" in a.values():
            row["reason"] = row.get("unsupported") or f"native transition query unavailable (rc={rc})"
        elif any(a[k] != "NO_UNDEF" for k in ("undef0", "undef1")):
            row["reason"] = "literal-X or undefined next-state cofactor"
        elif any(proof != "PROVED" for proof in role_proofs):
            row["reason"] = "conditional role implication, disjointness or full-domain partition not proved"
        elif a["equal"] == "PROVED":
            row["classification"] = ("LOCAL_CLEAR" if not row["reset_reaches"] and
                any(p in row["controls"] for p in ("SRST", "ARST", "SET", "CLR")) else "NO_DEPENDENCE")
        elif set(row["reset_reaches"]) <= {"EN"}:
            row["classification"] = "RETENTION_CONTROL"
        elif (all(a.get(f"{role}_reachable{arm}") == "PROVED" for arm in (0, 1)
                  for role in ("force_zero", "force_one")) and
              {a["retain0"], a["retain1"]} == {"PROVED", "REFUTED"} and
              all(a.get(f"{value}{arm}") == "REFUTED" for arm in (0, 1)
                  if a[f"retain{arm}"] == "REFUTED" for value in ("zero", "one"))):
            # Raw proc preserves enable as a D/feedback mux. One complete
            # cofactor retains Q, the other is defined ordinary data, and
            # neither has a feasible constant-force domain. This is the
            # same retention role as an explicit EN pin, not a reset force.
            row["classification"] = "RETENTION_CONTROL"
            row["proof_basis"] = "native_full_domain_retention_cofactor"
        elif (a["zero0"] == "PROVED" or a["one0"] == "PROVED") and (
                a["zero1"] == "PROVED" or a["one1"] == "PROVED"):
            row["classification"] = "DATA_VALUE"
        else:
            high = a["high"] == "PROVED" and a["low"] == "REFUTED"
            low = a["low"] == "PROVED" and a["high"] == "REFUTED"
            constant_high = a["zero1"] == "PROVED" or a["one1"] == "PROVED"
            constant_low = a["zero0"] == "PROVED" or a["one0"] == "PROVED"
            if high or low or constant_high != constant_low:
                row["classification"] = "RESET_FORCE"
                row["polarity"] = "active_high" if high or (not low and constant_high) else "active_low"
                row["total_force"] = constant_high if row["polarity"] == "active_high" else constant_low
                row["timing"] = "asynchronous" if any(p in row["reset_reaches"] for p in _ASYNC_PINS) else "synchronous"
            else:
                row["classification"] = "UNRESOLVED_DATA_DEPENDENCE"
                row["reason"] = "paired dependence has no closed reset-force sense/priority"
                if all(a.get(f"{role}_reachable{arm}") == "PROVED" for arm in (0, 1)
                       for role in ("force_zero", "force_one")):
                    row["native_relation"] = {"name": "DEFINED_NONFORCING_RESET_DEPENDENCE",
                        "proof_basis": "native_paired_cofactor_queries",
                        "scope": "one_step_shared_current_q",
                        "arms": [{"reset_value": arm, "definedness": a[f"undef{arm}"],
                                  "roles": [r for r in row["conditional_roles"] if r["reset_value"] == arm]}
                                 for arm in (0, 1)],
                        "partition_and_priority_queries": {k: v for k, v in a.items() if
                            k.startswith(("roles_disjoint", "roles_cover", "priority_"))},
                        "reason": "both cofactors are defined and roles close, but neither has a feasible force domain; data/retention dependence does not establish reset-force intent"}
                    row["reason"] = "DEFINED_NONFORCING_RESET_DEPENDENCE: native data/retention roles do not establish reset-force sense"
        if row["classification"] in {"UNSUPPORTED", "UNRESOLVED_DATA_DEPENDENCE"}:
            result["unresolved"].append(f"{row['cell']}.Q[{row['bit_index']}]: {row.get('reason')}")
    if (rc == 0 and domain_reachable and progress["completed"] == progress["planned"]
            and not progress["unknown"]):
        loads = _priority_load_retention(mod, bit, rows, work_dir / "priority_load", container)
        result["priority_load_retention"] = loads
        load_by_q = {c["q"]: c for c in loads["certificates"]}
        for row in rows:
            if row["q"] not in load_by_q:
                continue
            old = f"{row['cell']}.Q[{row['bit_index']}]: {row.get('reason')}"
            row["classification"] = "RETENTION_CONTROL"
            row["proof_basis"] = "native_priority_load_retention"
            row["priority_load_certificate"] = load_by_q[row["q"]]
            row["reason"] = "native reset control of a priority load with a discriminating source-Q-retaining fallback"
            result["unresolved"] = [u for u in result["unresolved"] if u != old]
        post = _post_reset_independence(model, rows, work_dir / "post_reset", container)
        result["post_reset_independence"] = post
        by_q = {c["q"]: c for c in post["certificates"]}
        for row in rows:
            if row["q"] not in by_q:
                continue
            # The certificate has a reset-prefix precondition. It is useful
            # native evidence, but cannot answer the unrestricted structural
            # obligation for the first assertion edge. Preserve its refusal.
            row["post_reset_certificate"] = by_q[row["q"]]
            old = f"{row['cell']}.Q[{row['bit_index']}]: {row.get('reason')}"
            row["reason"] = ("POST_RESET_COFACTOR_INDEPENDENCE: reset-independent in the immediate poststate of an asserted reset edge; "
                             "unrestricted first-edge force sense remains unresolved")
            new = f"{row['cell']}.Q[{row['bit_index']}]: {row['reason']}"
            result["unresolved"] = [new if u == old else u for u in result["unresolved"]]
    result.update(complete=not result["unresolved"], native_exit_code=rc,
                  native_run=native, query_progress=progress,
                  paired_domain_reachable=domain_reachable,
                  model_sha256=file_sha256(model_path), script_sha256=file_sha256(ys),
                  log_sha256=native["log_sha256"],
                  work_dir=str(work_dir), query_count=len(specs))
    return result


def check_claim(netlist: dict, top: str, claim: dict,
                reset_mapping: Optional[dict] = None) -> dict:
    """Answer ONE structural claim from a yosys JSON netlist. Pure.

    Only what was SEEN passes. Every answer is read from the netlist, never
    from RTL text: which flops a reset forces and with what polarity (the
    SRST/ARST cell parameters, through a chain of inverters only), which flops
    are design state (they can influence an output), which clock pins the
    clock reaches. A cone this program cannot classify is NOT_DISCHARGED —
    never PASS, and never REFUTED (review rounds 2-4)."""
    rule = claim.get("rule")
    signal = str(claim.get("signal") or "")
    value = str(claim.get("value") or "")
    out = {"rule": rule, "signal": signal, "value": value}
    tm = _top_module(netlist, top)
    if tm is None:
        return dict(out, verdict=NOT_DISCHARGED,
                    finding=f"top module {top!r} is not in the netlist")
    mod_name, mod = tm
    out["module"] = mod_name
    census = _state_census(mod, netlist)
    other_state = census["latch"] + census["memory"] + census["unclassified"]
    cells = _cells(mod)
    flops = [(n, c) for n, c, k in cells if k == "ff"]
    if rule == "state_covered":
        want = [n for n in value.split(",") if n]
        facts = netlist_facts(netlist, top)
        if not facts["ok"]:
            return dict(out, verdict=NOT_DISCHARGED, finding=facts["why"])
        have = sorted(r["name"] for r in facts["registers"])
        out["flops"] = len(flops)
        out["verification_only"] = facts["verification_only"]
        if sorted(want) != have:
            return dict(out, verdict=NOT_DISCHARGED, observed=sorted(want),
                        netlist_state=have,
                        finding=(f"the observed registers {sorted(want)} are not "
                                 f"the netlist's design state {have}"))
        return dict(out, verdict=PASS,
                    finding=(f"the observed registers are exactly the netlist's "
                             f"design state {have} (all {len(flops)} flop(s); "
                             f"verification-only: {facts['verification_only']}); "
                             f"no latch, memory or unclassified cell"))
    bit, why = _port_bit(mod, signal)
    if bit is None:
        return dict(out, verdict=NOT_APPLICABLE,
                    finding=f"{why}; not the subject of rule {rule}")
    input_bits = {b for p in (mod.get("ports") or {}).values()
                  if p.get("direction") == "input"
                  for b in p.get("bits") or [] if isinstance(b, int)}
    cone = _cone(mod, bit)
    if rule == "clock_edge":
        want = {"posedge": 1, "negedge": 0}.get(value)
        if want is None:
            return dict(out, verdict=NOT_DISCHARGED,
                        finding=f"edge {value!r} has no structural rule")
        direct, via_logic, internal = [], [], []
        for n, c in flops:
            clk = _bits(c, "CLK")
            if bit in clk:
                direct.append((n, c))
            elif cone.intersection(clk):
                via_logic.append(n)
            elif not input_bits.intersection(clk):
                internal.append(n)
        # a memory port or a LATCH whose clock/enable the clock reaches
        other_clk = [n for n, c, k in cells if k in ("memory", "unclassified", "latch")
                     and (cone.intersection(_bits(c, "CLK"))
                          or cone.intersection(_bits(c, "EN")))]
        out["flops_clocked"] = len(direct)
        wrong = [n for n, c in direct
                 if _param_bit((c.get("parameters") or {})
                               .get("CLK_POLARITY")) != want]
        if wrong:
            return dict(out, verdict=REFUTED, cells=sorted(wrong),
                        finding=(f"{len(wrong)} of {len(direct)} flop(s) "
                                 f"clocked by {signal!r} do not sample on "
                                 f"{value}"))
        odd = sorted(via_logic + internal + other_clk)
        if odd:
            return dict(out, verdict=NOT_DISCHARGED, cells=odd,
                        finding=("state clocked through logic, by an internal "
                                 "net, or a latch/memory the clock reaches, "
                                 "whose edge this check cannot state: "
                                 + ", ".join(odd)))
        if not direct:
            return dict(out, verdict=NOT_DISCHARGED,
                        finding=f"no flop is clocked by port {signal!r}")
        return dict(out, verdict=PASS,
                    finding=(f"all {len(direct)} flop(s) clocked by "
                             f"{signal!r} have CLK_POLARITY={want} ({value}); "
                             f"no state is clocked through logic or an "
                             f"internal net"))
    rm = _reset_map(mod, bit)
    if reset_mapping is not None and rule in {"reset_port", "reset_sync", "reset_polarity"}:
        rows = reset_mapping.get("rows") or []
        force = [r for r in rows if r.get("classification") == "RESET_FORCE"]
        unresolved = reset_mapping.get("unresolved") or []
        out["reset_control_mapping"] = reset_mapping
        wrong = [r for r in force if rule == "reset_polarity" and r.get("polarity") != value]
        if wrong:
            return dict(out, verdict=REFUTED, cells=sorted({r["cell"] for r in wrong}),
                        finding="native paired next-state force sense contradicts declared polarity")
        if rule == "reset_sync":
            opposite = "asynchronous" if value == "synchronous" else "synchronous"
            bad = [r for r in force if r.get("timing") == opposite]
            # Preserve the existing structural timing counterevidence even
            # when a literal-X value prevents full function classification.
            old_bad = (rm["async"] + rm["async_x"] if value == "synchronous" else
                       rm["sync"] if value == "asynchronous" else [])
            if bad or old_bad:
                return dict(out, verdict=REFUTED,
                            cells=sorted({r["cell"] for r in bad + old_bad}),
                            finding="actual reset timing contradicts the declared timing")
        if rule == "reset_port" and force:
            return dict(out, verdict=PASS,
                        finding=f"native paired model identifies {len(force)} reset-forced Q bit(s)")
        if unresolved or not force or (rule == "reset_polarity" and value not in {"active_high", "active_low"}) or (
                rule == "reset_sync" and value not in {"synchronous", "asynchronous"}):
            return dict(out, verdict=NOT_DISCHARGED,
                        finding="reset-force identity/sense/priority is not fully closed: " +
                        ("; ".join(unresolved) or "no reset-forced state or unsupported claim value"))
        basis = ("native paired queries and raw one-step independence certificates" if any(
            r.get("proof_basis") == "complete_raw_transition_fanin" for r in rows) else "native paired queries")
        return dict(out, verdict=PASS,
                    finding=f"complete current-Q reset mapping ({basis}) closes {rule}={value} for every reset-force group")
    forced = rm["sync"] + rm["async"] + rm["async_x"]
    out["sync_reset_flops"] = len(rm["sync"])
    out["async_reset_flops"] = len(rm["async"]) + len(rm["async_x"])
    unclass = rm["clk"] + rm["opaque"]
    if rule == "reset_port":
        if forced:
            return dict(out, verdict=PASS,
                        finding=(f"port {signal!r} forces the reset of "
                                 f"{len(forced)} flop(s)"))
        return dict(out, verdict=NOT_DISCHARGED,
                    finding=(f"port {signal!r} exists but forces no flop's "
                             f"reset in the netlist"))
    if rule == "reset_polarity":
        if value not in ("active_high", "active_low"):
            return dict(out, verdict=NOT_DISCHARGED,
                        finding=f"polarity {value!r} has no structural rule")
        wrong = sorted(f["cell"] for f in forced
                       if f.get("polarity") not in (None, value))
        if wrong:
            return dict(out, verdict=REFUTED, cells=wrong,
                        finding=(f"{len(wrong)} flop(s) are reset by {signal!r} "
                                 f"{'active-low' if value == 'active_high' else 'active-high'}"
                                 f", against the declared {value}"))
        unknown = sorted(f["cell"] for f in forced if f.get("polarity") is None)
        unknown += sorted(f["cell"] for f in rm["data"])
        if unknown or unclass:
            return dict(out, verdict=NOT_DISCHARGED,
                        cells=unknown + [u["cell"] for u in unclass],
                        finding=("the reset reaches state whose polarity is not "
                                 "a netlist fact (through a gate, a set/clear "
                                 "pin, a clock pin, a latch or a memory)"))
        if not forced:
            return dict(out, verdict=NOT_DISCHARGED,
                        finding=f"{signal!r} forces no flop's reset")
        return dict(out, verdict=PASS,
                    finding=(f"every one of the {len(forced)} flop(s) {signal!r} "
                             f"resets is reset {value} (SRST/ARST polarity)"))
    if rule == "reset_sync":
        if value == "synchronous":
            if rm["async"] or rm["async_x"]:
                cells_ = sorted(f["cell"] for f in rm["async"] + rm["async_x"])
                return dict(out, verdict=REFUTED, cells=cells_,
                            finding=(f"{len(cells_)} flop(s) are reset "
                                     f"ASYNCHRONOUSLY by {signal!r} (directly "
                                     f"or through logic)"))
            if unclass:
                return dict(out, verdict=NOT_DISCHARGED,
                            cells=sorted(u["cell"] for u in unclass),
                            finding=(f"{signal!r} reaches a clock pin or state "
                                     f"this check does not model"))
            if not rm["sync"]:
                return dict(out, verdict=NOT_DISCHARGED,
                            finding=(f"{signal!r} forces no flop through a "
                                     f"synchronous reset in the netlist"))
            return dict(out, verdict=PASS,
                        finding=(f"{signal!r} resets {len(rm['sync'])} flop(s), "
                                 f"all synchronously; its whole combinational "
                                 f"cone reaches no async control, clock pin, "
                                 f"latch or memory"))
        if value == "asynchronous":
            # REFUTED only on a FORCED synchronous reset (SRST). A reset that
            # reaches a D pin is not classified (NOT_DISCHARGED); one that only
            # gates an ENABLE is not a reset at all (review round 4, H3).
            if rm["sync"]:
                cells_ = sorted(f["cell"] for f in rm["sync"])
                return dict(out, verdict=REFUTED, cells=cells_,
                            finding=(f"{len(cells_)} flop(s) are reset "
                                     f"SYNCHRONOUSLY by {signal!r} (SRST)"))
            if unclass or rm["data"]:
                return dict(out, verdict=NOT_DISCHARGED,
                            cells=sorted(u["cell"] for u in unclass + rm["data"]),
                            finding=(f"{signal!r} reaches a D input, a clock pin "
                                     f"or unmodelled state; whether that is a "
                                     f"reset is not classified"))
            if not (rm["async"] or rm["async_x"]):
                return dict(out, verdict=NOT_DISCHARGED,
                            finding=(f"{signal!r} controls no flop through an "
                                     f"asynchronous reset in the netlist"))
            return dict(out, verdict=PASS,
                        finding=(f"{signal!r} resets "
                                 f"{len(rm['async']) + len(rm['async_x'])} "
                                 f"flop(s), all asynchronously; it forces no "
                                 f"synchronous reset"))
        return dict(out, verdict=NOT_DISCHARGED,
                    finding=f"sync value {value!r} has no structural rule")
    return dict(out, verdict=NOT_DISCHARGED,
                finding=f"rule {rule!r} is not a structural rule")


# ── R-0915-155 — THE APPLICABILITY GATE ─────────────────────────────────────
#
# Five review rounds each found a new design class the program answered
# wrongly (a descended wrapper, a synchronizer, a gated clear, a folded
# register, an array element, a second clock). The ruling: the program closes
# ONLY the class it can prove soundly, and says NOT_DISCHARGED — the flow's
# designed expert fallback — for everything else. Never PASS, never REFUTED,
# never ERROR outside the class. The gate is evaluated on the proof's OWN
# netlist(s) BEFORE any closure; every failing precondition is named.
#
# THE CLASS:
#   C1  one clock domain: every flop's CLK is the declared clock port through
#       a pure BUFFER chain, and every flop samples on the same edge;
#   C2  every reset pin of every flop (SRST/ARST/SET/CLR/ALOAD) is driven by a
#       declared reset port through a pure inverter/buffer chain — so no flop
#       Q (a synchronizer) and no gate (a qualified clear) is in any reset path;
#   C3  a declared reset reaches NOTHING but those reset pins (no D, no EN, no
#       clock) — the only use of a reset is to reset;
#   C4  no latch, memory, array, $anyinit or unclassified cell;
#   C5  no register the structural read folds away that the proof keeps: the
#       design-state census of a read WITHOUT opt_dff (as `prep -noff` keeps
#       flops) must equal the census the checks use;
#   C6  every observed register name is a plain identifier (no `[ ]`, no
#       hierarchy dot) — an observer is refused, never truncated.
RAW_PASSES = "proc; flatten; opt_clean"
_RESET_PINS = ("SRST", "ARST", "SET", "CLR", "ALOAD")
# Plain = `[A-Za-z_][A-Za-z0-9_]*` ONLY. `$` (and so every escaped identifier)
# is outside: an observer pragma, a select pattern and a wire name cannot all
# carry it faithfully (round-6 review: `a$b` bound to `dut.a`).
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _chain_source(drivers: Dict[int, dict], bit: int, allow_inv: bool
                  ) -> Tuple[Optional[int], int]:
    """Follow `bit` back through 1-bit buffers (and inverters if allowed) to
    the first bit no such cell drives. Returns (source bit, inversions)."""
    par, seen = 0, set()
    while bit not in seen:
        seen.add(bit)
        c = drivers.get(bit)
        if c is None:
            return bit, par
        a = _bits(c, "A")
        t = c.get("type")
        if len(a) != 1 or not (t in _BUFFERS or (allow_inv and t in _INVERTERS)):
            return bit, par
        if t in _INVERTERS:
            par ^= 1
        bit = a[0]
    return None, par


def applicability(netlist: dict, top: str, clock: str, resets: List[str],
                  raw_netlist: Optional[dict] = None) -> List[str]:
    """The R-0915-155 preconditions this design FAILS (empty = inside the
    class). Pure; read from the netlist only."""
    tm = _top_module(netlist, top)
    if tm is None:
        return [f"top module {top!r} is not in the netlist"]
    _, mod = tm
    fails: List[str] = []
    census = _state_census(mod, netlist)
    other = census["latch"] + census["memory"] + census["unclassified"]
    if other:
        fails.append("C4 state that is not a flop: " + ", ".join(sorted(other)))
    drivers = _drivers(mod)
    # C1-C3 look at DESIGN state only — the SAME relevance netlist_facts uses
    # (one definition). A verification-only helper (an `ifdef FORMAL` register
    # feeding an assert) is not the design (round 6, low).
    rel = _relevant_bits(mod)
    flops = [(n, c) for n, c, k in _cells(mod)
             if k == "ff" and rel.intersection(_bits(c, "Q"))]
    relevant_cells = {n for n, _ in flops}
    cbit, why = _port_bit(mod, clock)
    if cbit is None:
        fails.append(f"C1 the clock {clock!r}: {why}")
    else:
        bad = []
        for n, c in flops:
            clk = _bits(c, "CLK")
            src = _chain_source(drivers, clk[0], allow_inv=False)[0] if len(clk) == 1 else None
            if src != cbit:
                bad.append(n)
        if bad:
            fails.append(f"C1 flop(s) not clocked by {clock!r} through a pure "
                         f"buffer chain: " + ", ".join(sorted(bad)))
        edges = {_param_bit((c.get("parameters") or {}).get("CLK_POLARITY"))
                 for _, c in flops}
        if len(edges) > 1:
            fails.append("C1 flops sample on both clock edges")
    rbits = {}
    for r in resets:
        b, why = _port_bit(mod, r)
        if b is None:
            fails.append(f"C2 the reset {r!r}: {why}")
        else:
            rbits[b] = r
    for n, c in flops:
        for pin in _RESET_PINS:
            for b in _bits(c, pin):
                src = _chain_source(drivers, b, allow_inv=True)[0]
                if src not in rbits:
                    fails.append(f"C2 {n} ({c.get('type')}) {pin} is not driven "
                                 f"by a declared reset through a pure "
                                 f"inverter/buffer chain")
                    break
    for b, r in rbits.items():
        cone = _cone(mod, b)
        for n, c, k in _cells(mod):
            if k in ("comb", "metadata"):
                continue
            if k == "ff" and n not in relevant_cells:
                continue
            for p, d in (c.get("port_directions") or {}).items():
                if d != "input" or not cone.intersection(_bits(c, p)):
                    continue
                if k == "ff" and p in _RESET_PINS:
                    continue
                fails.append(f"C3 the reset {r!r} reaches {n}.{p} "
                             f"({c.get('type')}) — not a reset pin")
                break
    facts = netlist_facts(netlist, top)
    if facts.get("ok"):
        odd = [r["name"] for r in facts["registers"] if not _IDENT_RE.match(r["name"])]
        if odd:
            fails.append("C6 register name(s) that are not plain identifiers: "
                         + ", ".join(sorted(odd)))
        if raw_netlist is not None:
            raw = netlist_facts(raw_netlist, top)
            if not raw.get("ok"):
                fails.append(f"C5 the unoptimised read cannot state the design's "
                             f"state: {raw.get('why')}")
            elif sorted(r["name"] for r in raw["registers"]) != sorted(
                    r["name"] for r in facts["registers"]):
                fails.append(
                    "C5 the structural read folds away register(s) the proof "
                    "keeps: " + ", ".join(sorted(
                        set(r["name"] for r in raw["registers"])
                        ^ set(r["name"] for r in facts["registers"]))))
    elif not other:
        fails.append(f"C4 {facts.get('why')}")
    return fails


def temporal_applicability(netlist: dict, top: str) -> List[str]:
    """Extra precondition for the TEMPORAL claims, which the harness samples on
    the clock's POSEDGE: every flop must sample on the posedge."""
    tm = _top_module(netlist, top)
    if tm is None:
        return [f"top module {top!r} is not in the netlist"]
    neg = sorted(n for n, c, k in _cells(tm[1]) if k == "ff" and _param_bit(
        (c.get("parameters") or {}).get("CLK_POLARITY")) != 1)
    return ([f"T1 flop(s) not on the posedge the properties sample: "
             + ", ".join(neg)] if neg else [])


def file_sha256(path: Path) -> Optional[str]:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def run_yosys(rtl_files: List[Path], top: str, work_dir: Path,
              container: Optional[str], simdef: str = "",
              tag: str = "", passes: str = "") -> Tuple[int, str, Path]:
    """Write the netlist with the flow's yosys. Returns (rc, log, netlist).

    `container=None` runs on this filesystem (the in-image route CI and the
    flow take); a name runs `docker exec` through the ONE guarded builder.
    `defines` are the proof task's own `-D` flags; `tag` names the files so
    one elaboration per task can sit side by side.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    netlist = work_dir / f"formal_structural_netlist{tag}.json"
    if netlist.exists():
        netlist.unlink()
    script = yosys_script([str(Path(f).resolve()) for f in rtl_files], top,
                          str(netlist.resolve()), simdef, passes)
    ys = work_dir / f"formal_structural_check{tag}.ys"
    _aa.write_text(ys, script.replace("; ", "\n") + "\n")
    inner = (f"export PATH=/foss/tools/bin:/foss/tools/yosys/bin:$PATH; "
             f"cd {work_dir.resolve()} && yosys -q -s {ys.name}")
    if container:
        import _container_exec as _ce
        argv = _ce.exec_argv(container, inner, tag="formal_structural_check")
    else:
        argv = ["bash", "-lc", inner]
    try:
        p = subprocess.run(argv, capture_output=True, text=True)
        rc, log = p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError as exc:
        rc, log = 127, f"[formal_structural_check] {exc}\n"
    _aa.write_text(work_dir / f"formal_structural_check{tag}.log", log)
    return rc, log, netlist


def elaborations(rtl_files: List[Path], top: str, work_dir: Path,
                 container: Optional[str] = None,
                 simdef: str = "", *, memory_clock: bool = False) -> List[dict]:
    """ONE elaboration: the chip's read of the DUT (R-0915-157), with its
    UNOPTIMISED twin (no opt_dff — flops kept as `prep -noff` keeps them) for
    the C5 census comparison. There is no second build to compare: the proof
    reads the DUT this same way."""
    def _load(rc, path):
        if rc == 0 and path.is_file():
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                return None
        return None
    # Lower BOTH twins only for clock claims. The reset/cofactor/role read
    # retains its original passes and memory refusal.
    passes = YOSYS_PASSES.replace("flatten;", "flatten; memory_map;") if memory_clock else YOSYS_PASSES
    raw_passes = RAW_PASSES.replace("flatten;", "flatten; memory_map;") if memory_clock else RAW_PASSES
    tag = "_clock" if memory_clock else ""
    rc, _log, path = run_yosys(rtl_files, top, work_dir, container, simdef,
                              tag=tag, passes=passes)
    rrc, _rl, rpath = run_yosys(rtl_files, top, work_dir, container, simdef,
                                tag=tag + "_raw", passes=raw_passes)
    return [{"defines": f"chip read ({simdef.strip() or 'no -D'})", "rc": rc,
             "path": path, "netlist": _load(rc, path), "raw": _load(rrc, rpath),
             "raw_path": rpath, "raw_rc": rrc}]


def _reset_memory_binding(source: dict, lowered: dict, top: str, clock: str) -> dict:
    """Complete source/word/Q binding for the bounded reset-only lowering.

    This is admission to the existing native next-state role proof, not reset
    evidence itself. Keep every source word and scalar Q in both twins. A
    missing, merged, ambiguous or unsupported identity refuses the whole route.
    Clock observations and temporal HDL constructors do not use this route.
    """
    proof = {"inside": False, "failed_preconditions": [], "source_aliases": {},
             "constant_combinational_roms": {}, "views": {}}
    fails = proof["failed_preconditions"]
    original = _top_module(source.get("raw"), top) if source.get("raw") else None
    optimized = _top_module(source.get("netlist"), top) if source.get("netlist") else None
    if original is None or optimized is None:
        fails.append("missing original raw/optimized memory census")
        return proof
    original, optimized = original[1], optimized[1]
    memories = original.get("memories") or {}
    if not memories or memories != (optimized.get("memories") or {}):
        fails.append("source raw/optimized memory declarations disagree")
        return proof
    aliases = proof["source_aliases"]
    roms = proof["constant_combinational_roms"]
    for name, memory in memories.items():
        width, size, start = (memory.get(k) for k in ("width", "size", "start_offset"))
        src = (memory.get("attributes") or {}).get("src")
        if (not src or not all(type(v) is int for v in (width, size, start))
                or width <= 0 or size <= 0):
            fails.append(f"unsupported source reset memory: {name}")
            continue
        raw_rom = _clock_combinational_rom(original, name, memory)
        optimized_rom = _clock_combinational_rom(
            optimized, name, (optimized.get("memories") or {})[name])
        if raw_rom and optimized_rom:
            # A completely initialized, asynchronous-read, writer-free ROM is
            # combinational logic, not resettable state.  Require the closed
            # native shape independently in both source views before excluding
            # it from the sequential word/write-clock/Q population below.
            roms[name] = {"width": width, "size": size, "start_offset": start,
                          "src": src, "raw": True, "optimized": True}
            continue
        if raw_rom != optimized_rom:
            fails.append(f"source reset ROM classification disagrees: {name}")
        if _param_bit(memory.get("hide_name", 0)):
            fails.append(f"unsupported source reset memory: {name}")
            continue
        for word in range(start, start + size):
            alias = f"{name}[{word}]"
            if alias in aliases or alias in (original.get("netnames") or {}):
                fails.append(f"ambiguous source reset word alias: {alias}")
            aliases[alias] = {"memory": name, "word": word, "width": width, "src": src}
    source_q = {q for _, c, k in _cells(original) if k == "ff" for q in _bits(c, "Q")}
    covered = set()
    for name, net in sorted((original.get("netnames") or {}).items()):
        bits = net.get("bits") or []
        if (not _param_bit(net.get("hide_name", 0)) and (net.get("attributes") or {}).get("src")
                and bits and all(b in source_q for b in bits) and set(bits) - covered):
            if name in aliases or covered.intersection(bits):
                fails.append(f"ambiguous source scalar reset alias: {name}")
                continue
            aliases[name] = {"width": len(bits), "src": net["attributes"]["src"], "source_q": bits}
            covered.update(bits)
    if covered != source_q:
        fails.append("source scalar Q identities are not completely named")
    clocks = set()
    written = set()
    for name, cell, kind in _cells(original):
        if kind in ("latch", "unclassified"):
            fails.append(f"unsupported original reset state: {name}")
        if kind != "memory":
            continue
        params = cell.get("parameters") or {}
        memid = str(params.get("MEMID", "")).lstrip("\\")
        if memid not in memories:
            fails.append(f"unbound original memory port: {name}")
        if memid in roms:
            continue
        if cell["type"] == "$memwr_v2" and _param_bit(params.get("CLK_ENABLE")) == 1:
            clk = _bits(cell, "CLK")
            edge = _param_bit(params.get("CLK_POLARITY"))
            if len(clk) != 1 or edge not in (0, 1):
                fails.append(f"unknown source memory write clock: {name}")
            else:
                clocks.add((clk[0], edge))
                written.add(memid)
        elif cell["type"] != "$memrd" or _param_bit(params.get("CLK_ENABLE")) != 0:
            fails.append(f"unsupported source reset memory port: {name}")
    sequential_memories = set(memories) - set(roms)
    if (not sequential_memories or written != sequential_memories
            or len(clocks) != 1):
        fails.append("source memories lack one complete synchronous write-clock population")
    input_clocks = {b for p in original.get("ports", {}).values() if p.get("direction") == "input"
                    and len(p.get("bits", [])) == 1 for b in p["bits"] if isinstance(b, int)}
    if clocks and next(iter(clocks))[0] not in input_clocks:
        fails.append("source memory clock is not a direct one-bit input")
    if clock and (not clocks or _port_bit(original, clock)[0] != next(iter(clocks))[0]):
        fails.append("source memory clock disagrees with declared clock")
    for view, key, rc_key in (("raw", "raw", "raw_rc"), ("optimized", "netlist", "rc")):
        netlist = lowered.get(key)
        tm = _top_module(netlist, top) if netlist else None
        if lowered.get(rc_key) != 0 or tm is None:
            fails.append(f"missing native lowered {view} state")
            continue
        mod = tm[1]
        census = _state_census(mod, netlist)
        if census["memory"] or census["latch"] or census["unclassified"]:
            fails.append(f"unsupported native lowered {view} state")
        qbits = []
        for name, cell, kind in _cells(mod):
            if kind != "ff":
                continue
            q = (cell.get("connections") or {}).get("Q") or []
            if not q or any(not isinstance(b, int) for b in q):
                fails.append(f"undefined native {view} Q identity: {name}")
            qbits.extend(q)
            clk = _bits(cell, "CLK")
            observed_clock = (clk[0], _param_bit((cell.get("parameters") or {}).get("CLK_POLARITY"))) if len(clk) == 1 else None
            if observed_clock not in clocks:
                fails.append(f"native {view} Q clock disagrees with source: {name}")
        word_bits = {}
        for name, alias in aliases.items():
            net = (mod.get("netnames") or {}).get(name, {})
            bits = net.get("bits") or []
            if (_param_bit(net.get("hide_name", 0)) or len(bits) != alias["width"] or
                    any(not isinstance(b, int) or b not in qbits for b in bits)):
                fails.append(f"missing exact native {view} source alias: {name}")
            word_bits[name] = bits
        population = [b for bits in word_bits.values() for b in bits]
        if (len(qbits) != len(set(qbits)) or len(population) != len(set(population)) or
                set(population) != set(qbits) or len(population) != len(qbits)):
            fails.append(f"incomplete or ambiguous native {view} source/word/Q population")
        proof["views"][view] = {"q_bits": qbits, "q_count": len(qbits), "aliases": word_bits}
    proof["inside"] = not fails
    return proof


def check(rtl_files: List[Path], top: str, claims: List[dict],
          work_dir: Path, container: Optional[str] = None,
          simdef: str = "",
          klass: Optional[dict] = None) -> dict:
    """Answer every claim on EVERY proof elaboration. A claim passes only if
    it passes in all of them; elaborations that disagree are NOT_DISCHARGED.
    Returns the evidence record."""
    elabs = elaborations(rtl_files, top, work_dir, container, simdef)
    record = {
        "program": "formal_structural_check", "version": VERSION,
        "top": top, "rtl_files": [str(f) for f in rtl_files],
        # WHAT WAS MEASURED, by content — so a reader (and the read-back in
        # formal_property_run) can refuse evidence about some other RTL.
        "rtl_sha256": {str(f): file_sha256(Path(f)) for f in rtl_files},
        "elaborations": [{"defines": e["defines"], "yosys_rc": e["rc"],
                          "netlist": e["path"].name if e["path"].is_file() else None,
                          "netlist_sha256": (file_sha256(e["path"])
                                             if e["path"].is_file() else None)}
                         for e in elabs],
        "yosys_passes": YOSYS_PASSES,
        "yosys_rc": max(e["rc"] for e in elabs),
    }
    # R-0915-155 — the shared applicability gate, on EVERY elaboration, before
    # any reset/value or temporal claim is answered.  ``clock_edge`` has its
    # own complete-state route below: knowing a directly observed clock edge
    # does not require a reset to be used only as a reset, nor plain observer
    # spelling.  The shared record remains intact for its existing consumers.
    fails: List[str] = []
    if klass is not None:
        for e in elabs:
            if e["netlist"] is None:
                fails.append(f"no netlist for defines {e['defines']!r}")
                continue
            for f in applicability(e["netlist"], top, klass.get("clock", ""),
                                   list(klass.get("resets") or []), e["raw"]):
                if f not in fails:
                    fails.append(f)
        record["applicability"] = {"class": "R-0915-155", "inside": not fails,
                                   "failed_preconditions": fails}
    clock_fails: List[str] = []
    clock_elabs = elabs
    if klass is not None and any(c.get("rule") == "clock_edge" for c in claims):
        source_aliases = None
        raw_top = _top_module(elabs[0]["raw"], top) if elabs[0]["raw"] else None
        if raw_top and _state_census(raw_top[1], elabs[0]["raw"])["memory"]:
            source_aliases, why = _clock_memory_aliases(elabs[0]["raw"], top)
            if why:
                clock_fails.append("clock_edge " + why)
            else:
                clock_elabs = elaborations(rtl_files, top, work_dir, container,
                                            simdef, memory_clock=True)
                record["clock_edge_source_aliases"] = source_aliases
                record["clock_edge_elaborations"] = [{
                    "yosys_passes": YOSYS_PASSES.replace("flatten;", "flatten; memory_map;"),
                    "raw_passes": RAW_PASSES.replace("flatten;", "flatten; memory_map;"),
                    "source_rtl_sha256": record["rtl_sha256"],
                    "source_raw_netlist": str(elabs[0]["raw_path"]),
                    "source_raw_netlist_sha256": file_sha256(elabs[0]["raw_path"]),
                    **{view: {"path": str(e[key]), "sha256": file_sha256(e[key]),
                              "yosys_rc": e[rc_key],
                              "state": sync_state_facts(e[net_key], top, klass.get("clock", ""),
                                                        source_aliases=source_aliases)}
                       for view, key, rc_key, net_key in (
                           ("optimized", "path", "rc", "netlist"),
                           ("raw", "raw_path", "raw_rc", "raw"))}}
                    for e in clock_elabs]
        for e in clock_elabs:
            if e["netlist"] is None:
                clock_fails.append(f"no netlist for defines {e['defines']!r}")
                continue
            for f in clock_edge_applicability(e["netlist"], e["raw"], top,
                                              klass.get("clock", ""),
                                              source_aliases=source_aliases):
                if f not in clock_fails:
                    clock_fails.append(f)
        record["clock_edge_applicability"] = {
            "class": "complete-state direct-clock observation",
            "inside": not clock_fails,
            "failed_preconditions": clock_fails,
        }
    reset_elabs = elabs
    reset_fails = fails
    reset_rules = {"reset_port", "reset_sync", "reset_polarity"}
    raw_top = _top_module(elabs[0]["raw"], top) if elabs[0]["raw"] else None
    if raw_top and raw_top[1].get("memories") and any(c.get("rule") in reset_rules for c in claims):
        # Separate native twins: the original reads and the clock route remain
        # intact. Only reset claims may consume this source-bound construction.
        candidate_elabs = []
        reset_fails = []
        proofs = []
        for e in elabs:
            passes = YOSYS_PASSES.replace("flatten;", "flatten; memory_map;")
            raw_passes = RAW_PASSES.replace("flatten;", "flatten; memory_map;")
            rc, _, path = run_yosys(rtl_files, top, work_dir, container, simdef,
                                    tag="_reset_memory", passes=passes)
            rrc, _, rpath = run_yosys(rtl_files, top, work_dir, container, simdef,
                                      tag="_reset_memory_raw", passes=raw_passes)
            def load(code, p):
                try:
                    return json.loads(p.read_text()) if code == 0 else None
                except (OSError, ValueError):
                    return None
            lowered = dict(e, rc=rc, path=path, raw_rc=rrc, raw_path=rpath,
                           netlist=load(rc, path), raw=load(rrc, rpath))
            proof = _reset_memory_binding(e, lowered, top, (klass or {}).get("clock", ""))
            if record["rtl_sha256"] != {str(f): file_sha256(Path(f)) for f in rtl_files}:
                proof["inside"] = False
                proof["failed_preconditions"].append("source changed during reset memory elaboration")
            if proof["inside"] and klass is not None:
                proof["failed_preconditions"] += [f for f in applicability(
                    lowered["netlist"], top, klass.get("clock", ""),
                    list(klass.get("resets") or []), lowered["raw"])
                    if not f.startswith(("C2 ", "C3 ", "C6 "))]
                proof["inside"] = not proof["failed_preconditions"]
            proof["source_binding"] = {"rtl_sha256": record["rtl_sha256"],
                "original_raw_sha256": file_sha256(e["raw_path"]),
                "original_optimized_sha256": file_sha256(e["path"]),
                "raw_sha256": file_sha256(rpath), "optimized_sha256": file_sha256(path),
                "raw_path": str(rpath), "optimized_path": str(path),
                "raw_rc": rrc, "optimized_rc": rc,
                "raw_passes": raw_passes, "optimized_passes": passes}
            proofs.append(proof)
            reset_fails += proof["failed_preconditions"]
            candidate_elabs.append(lowered)
        record["reset_memory_construction"] = proofs
        if not reset_fails:
            reset_elabs = candidate_elabs
    mappings = {}
    for i, e in enumerate(reset_elabs):
        if e["netlist"] is not None:
            for signal in sorted({c.get("signal", "") for c in claims if c.get("rule") in
                                  {"reset_port", "reset_sync", "reset_polarity"}}):
                mappings[i, signal] = reset_control_mapping(
                    e["netlist"], e["raw"], top, signal,
                    work_dir / f"reset_transition_{i}_{signal.encode().hex()}", container)
                mappings[i, signal]["source_binding"] = {
                    "rtl_sha256": record["rtl_sha256"], "defines": e["defines"],
                    "optimized_netlist_sha256": file_sha256(e["path"]),
                    "raw_netlist_sha256": file_sha256(e["raw_path"]),
                    "scope": "same-invocation source next-state roles; not optimized-state coverage"}
    results = []
    for claim in claims:
        answers = []
        for i, e in enumerate(elabs):
            reset_claim = claim.get("rule") in {"reset_port", "reset_sync", "reset_polarity"}
            clock_claim = claim.get("rule") == "clock_edge"
            # Each exception is owned by a claim-specific complete-state
            # constructor.  No claim borrows another claim's exception.
            if clock_claim:
                blocked = bool(clock_fails)
            elif reset_claim:
                blocked = any(not f.startswith(("C2 ", "C3 ", "C6 ")) for f in reset_fails)
            else:
                blocked = bool(fails)
            if blocked:
                blocked_fails = clock_fails if clock_claim else reset_fails if reset_claim else fails
                answers.append(dict(claim, verdict=NOT_DISCHARGED, finding=(
                    "outside the claim's supported class: " + "; ".join(blocked_fails))))
                continue
            if e["netlist"] is None:
                answers.append(dict(claim, verdict=NOT_DISCHARGED, finding=(
                    f"yosys did not produce a netlist (rc={e['rc']}, defines "
                    f"{e['defines']!r}); nothing was measured")))
            else:
                observed = (clock_elabs[i]["netlist"] if clock_claim else
                            reset_elabs[i]["netlist"] if reset_claim else e["netlist"])
                answers.append(check_claim(observed, top, claim,
                    mappings.get((i, claim.get("signal", ""))) if reset_claim else None))
        verdicts = {a["verdict"] for a in answers}
        if len(verdicts) == 1:
            results.append(answers[0])
        else:
            results.append(dict(claim, verdict=NOT_DISCHARGED,
                                per_elaboration=answers,
                                finding=("the proof's elaborations disagree: "
                                         + "; ".join(f"{e['defines'] or '(none)'}: "
                                                     f"{a['verdict']}"
                                                     for e, a in zip(elabs, answers)))))
    record["claims"] = results
    record["verdict"] = (PASS if results and all(
        r["verdict"] == PASS for r in results) else
        REFUTED if any(r["verdict"] == REFUTED for r in results)
        else NOT_DISCHARGED)
    return record


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--rtl", type=Path, nargs="+", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--claim", action="append", default=[],
                    help="rule:signal[:value], e.g. clock_edge:clk:posedge")
    ap.add_argument("--work-dir", type=Path, default=Path("."))
    ap.add_argument("--container", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    claims = []
    for spec in args.claim:
        parts = spec.split(":")
        claims.append({"rule": parts[0], "signal": parts[1] if len(parts) > 1
                       else "", "value": parts[2] if len(parts) > 2 else ""})
    rec = check(args.rtl, args.top, claims, args.work_dir, args.container)
    out = json.dumps(rec, indent=2, ensure_ascii=False)
    if args.json:
        _aa.write_text(Path(args.json), out + "\n")
    print(out)
    return 0 if rec["verdict"] == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
