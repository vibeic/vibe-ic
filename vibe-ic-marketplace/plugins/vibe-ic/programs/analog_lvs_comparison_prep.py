#!/usr/bin/env python3
"""analog_lvs_comparison_prep.py — COMPARISON-SIDE preparation for an open-PDK
per-block LVS run (A6). Deterministic, chip-AGNOSTIC, no PDK literal.

WHY THIS EXISTS, MEASURED. A PDK's own KLayout LVS runset is a sign-off engine:
it extracts the block GDS with the PDK's real device recognition and compares it
against the block's source netlist. Handed this campaign's two analog blocks it
refused both, and every one of the three reasons was a MISMATCH OF CONVENTION
between what the flow writes and what a sign-off deck reads — not a design
defect. The blocks were structurally correct the whole time (once prepared, the
deck reports zero mismatched nets, devices and pins for both).

  1. THE SOURCE NETLIST INSTANTIATES DEVICES AS SUBCIRCUITS. A PDK model is a
     `.subckt`, so a netlist meant for SIMULATION correctly writes
     `Xmn1 d g s b sg13_hv_nmos w=.. l=..`. A netlist meant for COMPARISON must
     use the element letter (`M`/`R`/`C`/…), because that is how every SPICE
     reader — including the PDK deck's own — decides that a line IS a device.
     Read as subcircuit calls, the 11 devices of one block became 9 empty
     circuits and the top cell paired against NOTHING: the cross-reference read
     `CIRCUIT ldo <-> None`. The design netlist is NEVER touched; only the copy
     handed to the comparator is rewritten, and the role→letter mapping is taken
     from the design's OWN `role_models` provenance, so no model name is
     hard-coded here.

  2. THE MODEL LIBRARIES ARE NOT PARSEABLE AS NETLISTS, AND LVS DOES NOT NEED
     THEM. The `.lib` lines a simulation netlist carries made the deck's SPICE
     reader abort on the first Verilog-A-ish model card ("Expected a word string
     here"), so the run died before extraction. LVS compares topology; it never
     evaluates a model.

  3. EVERY LABELLED NET BECAME A TOP-LEVEL PIN. A generator labels internal nets
     because that is what makes a layout debuggable, and a flat extraction turns
     each label into a pin — so a block with 4 declared ports presented 9, and
     the deck (correctly, in strict port mode) called that a port mismatch. The
     comparison-side layout keeps only the texts naming a DECLARED port; the
     shipped GDS keeps all of its labels.

The parameter law that closes the last gap is not new: the drawn mask sits on
the manufacturing grid while a derived netlist parameter may not, so the
comparison side is quantized to the grid (`grid_snap_spice_params`, LVS
COMPARISON GRID in `magic_gencell_layout_lib`). Here it was the difference
between a resistor drawn at l=115.38u and declared at l=115.384u, which the deck
reported as two `MatchWithWarning` devices and three mismatched nets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from magic_gencell_layout_lib import grid_snap_spice_params  # noqa: E402
from _atomic_artefact import write_text as _atomic_write_text  # noqa: E402 - vibe-ic#1082

#: role → SPICE element letter. Universal SPICE, not a PDK table: the roles are
#: the design's own vocabulary (its `role_models` provenance) and the letters
#: are the ones every SPICE reader keys on.
ROLE_ELEMENT = {
    "nmos": "M", "pmos": "M", "mos": "M", "fet": "M",
    "res": "R", "resistor": "R",
    "cap": "C", "capacitor": "C",
    "ind": "L", "inductor": "L",
    "diode": "D",
    "bjt": "Q", "npn": "Q", "pnp": "Q",
}

_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\s+(\S+)\s*(.*)$")
_INCLUDE_RE = re.compile(r"(?i)^\s*\.(lib|include)\b")
_ROLE_PAIR_RE = re.compile(r"['\"](\w+)['\"]\s*:\s*['\"]([^'\"]+)['\"]")
_ROLE_BLOCK_RE = re.compile(r"role_models\s*=\s*\{([^}]*)\}")
_XCALL_RE = re.compile(r"(?i)^(\s*)x(\S+)\s+(.*)$")


def declared_ports(text: str, block: str) -> List[str]:
    """The block's own port list, from its `.subckt` line. [] when absent.

    This is the ONLY definition of "what is a pin" the preparation uses. It
    comes from the design, so a block that grows a port needs no change here.
    """
    for m in _SUBCKT_RE.finditer(text):
        if m.group(1).lower() == block.lower():
            return m.group(2).split()
    return []


def role_models(text: str) -> Dict[str, str]:
    """`{role: model}` from the netlist's own `role_models` provenance line."""
    m = _ROLE_BLOCK_RE.search(text)
    if not m:
        return {}
    return {k: v for k, v in _ROLE_PAIR_RE.findall(m.group(1))}


def model_element_letters(roles: Dict[str, str]) -> Dict[str, str]:
    """`{model_name_lower: element_letter}` for the roles we can place.

    A role this table does not know is left out, so its device calls are left
    ALONE rather than rewritten under a guessed letter — the same refuse-don't-
    guess rule the DRC engine dispatch uses for an unknown deck extension.
    """
    out: Dict[str, str] = {}
    for role, model in roles.items():
        letter = ROLE_ELEMENT.get(str(role).strip().lower())
        if letter and model:
            out[str(model).strip().lower()] = letter
    return out


def _split_call(rest: str) -> Optional[Tuple[List[str], str, List[str]]]:
    """`(nets, model, params)` of a subcircuit call's argument list.

    The model is the LAST bare (non `key=value`) token: everything before it is
    a net, everything after is a parameter. Positional parsing by terminal count
    would need a per-model terminal table — the one thing a chip-agnostic
    program must not carry.
    """
    toks = rest.split()
    bare = [i for i, t in enumerate(toks) if "=" not in t]
    if not bare:
        return None
    mi = bare[-1]
    if mi == 0:
        return None
    return toks[:mi], toks[mi], toks[mi + 1:]


def device_calls_to_elements(text: str, letters: Dict[str, str],
                             instance_letters: Optional[Dict[str, str]] = None,
                             instance_block: Optional[str] = None
                             ) -> Tuple[str, int]:
    """Rewrite `X<name> <nets> <model> <params>` to `<letter><name> …`.

    Returns (text, n_rewritten). A call whose model is not in `letters` is
    passed through untouched.
    """
    out: List[str] = []
    n = 0
    selected = instance_block is None
    for line in text.splitlines():
        begin = _SUBCKT_RE.match(line)
        if instance_block is not None and begin:
            selected = begin.group(1).lower() == instance_block.lower()
        elif instance_block is not None and re.match(r"(?i)^\s*\.ends\b", line):
            selected = False
        m = _XCALL_RE.match(line)
        if m:
            parts = _split_call(m.group(3))
            if parts:
                nets, model, params = parts
                letter = letters.get(model.lower()) or (
                    (instance_letters or {}).get(m.group(2).lower()) if selected else None)
                if letter:
                    out.append(("%s%s%s %s %s %s" % (
                        m.group(1), letter, m.group(2), " ".join(nets),
                        model, " ".join(params))).rstrip())
                    n += 1
                    continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), n


def strip_model_libraries(text: str) -> Tuple[str, int]:
    """Drop `.lib` / `.include` cards. Returns (text, n_dropped)."""
    keep, n = [], 0
    for line in text.splitlines():
        if _INCLUDE_RE.match(line):
            n += 1
            continue
        keep.append(line)
    return "\n".join(keep) + ("\n" if text.endswith("\n") else ""), n


def topology_instance_letters(text: str, block: str, topology: dict) -> Dict[str, str]:
    """Use declared device identities, roles and exact terminal order as fallback."""
    if not isinstance(topology, dict) or str(topology.get("block", "")).lower() != block.lower():
        raise ValueError("comparison topology does not declare this block")
    devices = topology.get("devices")
    if not isinstance(devices, list):
        raise ValueError("comparison topology has no declared device list")
    declared = {}
    for device in devices:
        if not isinstance(device, dict) or not isinstance(device.get("name"), str):
            raise ValueError("comparison topology device identity absent")
        name = device["name"].lower()
        if name in declared:
            raise ValueError("comparison topology has duplicate device identity: " + name)
        declared[name] = device
    selected, out = False, {}
    for line in text.splitlines():
        begin = _SUBCKT_RE.match(line)
        if begin:
            selected = begin.group(1).lower() == block.lower()
        elif re.match(r"(?i)^\s*\.ends\b", line):
            selected = False
        call = _XCALL_RE.match(line) if selected else None
        if not call or call.group(2).lower() not in declared:
            continue
        device = declared[call.group(2).lower()]
        parts = _split_call(call.group(3))
        nets = device.get("nets")
        if (parts is None or not isinstance(nets, list) or
                not all(isinstance(net, str) for net in nets) or
                [net.lower() for net in parts[0]] != [net.lower() for net in nets]):
            raise ValueError("comparison topology terminals differ for " + call.group(2))
        letter = ROLE_ELEMENT.get(str(device.get("role", "")).lower())
        if letter:
            out[call.group(2).lower()] = letter
    return out


def prepare_source_netlist(text: str, block: str, grid_um: float = 0.01,
                           topology: Optional[dict] = None
                           ) -> Tuple[str, Dict[str, int]]:
    """The comparison-side copy of a block's source netlist.

    Strips the model libraries, rewrites subcircuit-form device calls to element
    form using the design's own role declaration, and quantizes w/l to the
    layout grid. Returns (text, stats). The design netlist is never modified —
    callers write this to a separate file.
    """
    text, n_lib = strip_model_libraries(text)
    letters = model_element_letters(role_models(text))
    instances = topology_instance_letters(text, block, topology) if not letters and topology is not None else {}
    text, n_dev = device_calls_to_elements(text, letters, instances, block)
    text = "\n".join(grid_snap_spice_params(l, grid_um)
                     for l in text.splitlines()) + "\n"
    stats = {"model_libraries_dropped": n_lib,
                  "device_calls_rewritten": n_dev,
                  "models_mapped": len(letters)}
    if instances:
        stats["topology_instances_mapped"] = len(instances)
    return text, stats


#: KLayout script that writes a comparison-side copy of a block GDS keeping only
#: the TOP cell's texts that name a declared port. Child cells are untouched —
#: a device gencell's own terminal labels are how the extractor names a device's
#: pins, and stripping them cost the resistor terminal identity in the first
#: measured attempt. Variables: `gds`, `out`, `ports` (newline-separated).
PORT_ONLY_LAYOUT_SCRIPT = r"""
import pya
ly = pya.Layout(); ly.read(gds)
want = set(p for p in str(ports).split("\n") if p)
tops = set(t.name for t in ly.top_cells())
kept = dropped = 0
for c in ly.each_cell():
    if c.name not in tops:
        continue
    for li in ly.layer_indexes():
        rm = []
        for s in c.shapes(li).each():
            if s.is_text():
                if s.text.string in want:
                    kept += 1
                else:
                    rm.append(s); dropped += 1
        for s in rm:
            c.shapes(li).erase(s)
ly.write(out)
print("PORT_ONLY kept=%d dropped=%d" % (kept, dropped))
"""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("netlist")
    ap.add_argument("--block", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--grid-um", type=float, default=0.01)
    ap.add_argument("--topology", help="explicit declared device roles when netlist role provenance is absent")
    a = ap.parse_args(argv)
    src = Path(a.netlist).read_text()
    topology = json.loads(Path(a.topology).read_text()) if a.topology else None
    text, stats = prepare_source_netlist(src, a.block, a.grid_um, topology)
    # Atomic (vibe-ic#1082): the prepared deck is the comparison INPUT of the
    # LVS run that follows; a half-written one would compare a truncated
    # netlist and report the truncation as a mismatch.
    _atomic_write_text(a.out, text)
    ports = declared_ports(src, a.block)
    print("LVS_PREP ports=%s %s" % (",".join(ports), stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
