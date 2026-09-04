#!/usr/bin/env python3
"""lvs_power_aware_netlist_emit.py — the LVS ROOT FIX: power-aware gate netlist.

WHY THIS MODULE EXISTS
----------------------
The phase-3 LVS gap (GAP-E2E-9, tapeout-signoff roadmap P0) is that the yosys
gate netlist carries NO power ports (VPWR/VGND/VPB/VNB on sky130) while the
Magic-extracted layout carries per-cell power pins connected to the PDN rails.
netgen therefore either (a) reports `Top level cell failed pin matching` on a
sky130 OSS run — a POWER_PIN_ONLY mismatch the triage tier waives — or (b)
reaches `Circuits match uniquely` ONLY by ALTERING every std-cell's pin list to
drop the four power pins (`VPWR|(no matching pin)`, `disconnected node: VPWR`),
i.e. a match that never VERIFIES power connectivity. Either way the power
network is not LVS-checked, so a "tapeout-ready" claim is not honest
(`lvs_tapeout_signoff_check.py` correctly refuses to credit POWER_PIN_ONLY).

The ROOT FIX is to make the gate netlist power-aware — exactly what a
commercial `write_verilog -include_pwr_gnd` (or OpenLane's power-aware netlist)
emits: the PDK power rails are added as top-level ports AND every standard-cell
instance's power pins are connected to them, so the schematic's power
connectivity MIRRORS the extracted layout and netgen can reach a GENUINE,
power-verified match instead of a power-blind one.

This program is the deterministic emitter. It is chip-AGNOSTIC: the rails and
per-cell PG pins are derived from the PDK (never a design/chip literal), the
std-cell instances are found by the PDK's own library-cell name prefix, and the
transform is idempotent (a netlist that already carries the PG pins is left
unchanged).

PER-PDK POWER MODEL
-------------------
  sky130 (sky130_fd_sc_* / sky130_ef_sc_*):  VPWR VGND VPB VNB
  gf180  (gf180mcu_fd_sc_*):                  VDD  VSS  VNW VPW

  VPWR/VDD  — cell power pin      -> top power rail
  VGND/VSS  — cell ground pin     -> top ground rail
  VPB/VNW   — n-well body bias    -> tied to the power rail's well net
  VNB/VPW   — p-substrate bias    -> tied to the ground rail's well net

WHAT IT EMITS
-------------
For every module that instantiates PDK std-cells (the flat post-PnR netlist has
one such module):
  1. the four rails are declared as module-internal `wire`s;
  2. each std-cell instance gains `.VPWR(VPWR), .VGND(VGND), .VPB(VPB),
     .VNB(VNB)` (or the gf180 equivalent), including the empty-port spare/tie
     cells whose physical layout still carries power pins.

The rails are `global`-ised in the netgen setup (see `lvs_netgen_setup_emit.py`
Rule 1), so netgen connects them across the whole design AND the schematic's
top-level port list stays signal-only — matching a CORE-ONLY extracted layout
whose top exposes NO power ports. This is EMPIRICALLY LOAD-BEARING: adding the
rails as top-level PORTS instead makes netgen report `Netlists match uniquely
with port errors` / `Top level cell failed pin matching` (a top-level port-list
mismatch) against such a layout — verified live on the spm benchmark. The
opt-in `rails_as_ports=True` restores the OpenLane/Caravel pad-ring convention
(rails ALSO in the port list as `inout`) for flows whose extracted layout DOES
expose the rails as top pins.

§4.05 (load-bearing): this only ADDS power connectivity that the layout already
has; it never touches a signal net, so a real SIGNAL-net mismatch is untouched
and still FAILs. The transform is purely additive + idempotent.

Usage:
    python3 lvs_power_aware_netlist_emit.py --netlist IN.v --pdk sky130A \
        [--top NAME] [--out OUT.v]
    emit_power_aware_netlist(text, pdk, top=None) -> (new_text, stats)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Per-PDK standard-cell power model. `pg_pins` is the ordered list of the four
# std-cell power/body pins; `well_map` records which rail each body pin ties to
# (documentation only — the connection is name-for-name so the emitter simply
# wires every PG pin to a same-named top rail). Derived from the PDK library,
# never from a design.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PdkPowerModel:
    key: str
    pg_pins: Tuple[str, ...]          # cell power pins, e.g. (VPWR,VGND,VPB,VNB)
    cell_prefix_re: str               # regex a library-cell name must match


_PDK_POWER_MODELS: Dict[str, PdkPowerModel] = {
    # SkyWater sky130 high-density (and all sky130_fd_sc_* / sky130_ef_sc_*).
    "sky130A": PdkPowerModel(
        key="sky130A",
        pg_pins=("VPWR", "VGND", "VPB", "VNB"),
        cell_prefix_re=r"sky130_(?:fd|ef)_sc_[a-z0-9]+__",
    ),
    # GlobalFoundries gf180mcu (7t5v0 / 9t5v0 std-cell families).
    "gf180mcuC": PdkPowerModel(
        key="gf180mcuC",
        pg_pins=("VDD", "VSS", "VNW", "VPW"),
        cell_prefix_re=r"gf180mcu_fd_sc_[a-z0-9]+__",
    ),
    "gf180mcuD": PdkPowerModel(
        key="gf180mcuD",
        pg_pins=("VDD", "VSS", "VNW", "VPW"),
        cell_prefix_re=r"gf180mcu_fd_sc_[a-z0-9]+__",
    ),
    # IHP SG13G2 (open-source 130nm BiCMOS). TWO PG pins only — verified
    # from the shipped cell LEF, e.g. MACRO sg13g2_nor2_1 declares
    # PIN VDD (USE POWER) and PIN VSS (USE GROUND) and NO body/well pin.
    # That is consistent with this PDK being tapless: the well and
    # substrate ties are internal to each cell, so there is no VPB/VNB
    # (sky130) or VNW/VPW (gf180) body pin to model.
    "ihp-sg13g2": PdkPowerModel(
        key="ihp-sg13g2",
        pg_pins=("VDD", "VSS"),
        cell_prefix_re=r"sg13g2_",
    ),
}


def _normalize_pdk(pdk: str) -> str:
    """Map a loose PDK name to a canonical key (sky130A / gf180mcuC/D).

    Mirrors `lvs_netgen_setup_emit._normalize_pdk` so the two programs agree on
    which PDK a name denotes. Unknown → "" (caller emits a SKIPPED diagnostic)."""
    s = (pdk or "").strip().lower()
    if not s:
        return ""
    # Exact (case-insensitive) table hit first, so a PDK whose canonical
    # registry name is already a key needs no bespoke branch.
    for key in _PDK_POWER_MODELS:
        if key.lower() == s:
            return key
    if s.startswith("sky130") or "skywater" in s:
        return "sky130A"
    if s.startswith("gf180"):
        return "gf180mcuD" if s.endswith("d") or "mcud" in s else "gf180mcuC"
    if s.startswith("ihp") or s.startswith("sg13g2"):
        return "ihp-sg13g2"
    return ""


def model_from_cell_lef(cell_lef: "Path | str",
                        key: Optional[str] = None) -> Optional[PdkPowerModel]:
    """Derive a PdkPowerModel from a std-cell LEF's OWN declarations.

    WHY THIS EXISTS. `_PDK_POWER_MODELS` is a hardcoded table of three
    OPEN-SOURCE PDKs. A project-staged (i.e. every commercial) PDK resolves to
    the synthetic name `custom:pdk`, so `_normalize_pdk` returns "",
    `power_model_for` returns None, and the emitter SKIPS — leaving the gate
    netlist power-blind while the extracted layout is not. netgen then reports
    every std cell as `is a placeholder, treated as a black box` with the
    supply pins `(no matching pin)`, i.e. a whole-design LVS mismatch. So the
    documented LVS root fix was unavailable to exactly the PDKs that need it.

    A LEF already carries everything the model needs, declared by the PDK
    itself:
      * `PIN <name> ... USE POWER|GROUND` on each MACRO  -> `pg_pins`
      * the MACRO names themselves                       -> `cell_prefix_re`

    Pure LEF grammar, so no PDK/vendor/cell name is hardcoded and no naming
    convention is assumed — a library whose cells share no common prefix
    (typical of a commercial std-cell library) is matched by an alternation of
    its own MACRO names, longest-first so a shorter name can never shadow a
    longer one. Returns None when the LEF declares no supply pins or no
    macros, which the caller reports as a SKIP rather than guessing."""
    p = Path(cell_lef)
    try:
        text = p.read_text(errors="ignore")
    except OSError:
        return None

    macros: List[str] = []
    pg: List[str] = []          # insertion-ordered, de-duplicated
    cur_pin: Optional[str] = None
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"^MACRO\s+([A-Za-z_][\w$]*)", s)
        if m:
            macros.append(m.group(1))
            cur_pin = None
            continue
        m = re.match(r"^PIN\s+([A-Za-z_][\w$]*)", s)
        if m:
            cur_pin = m.group(1)
            continue
        if cur_pin and re.match(r"^USE\s+(POWER|GROUND)\b", s, re.IGNORECASE):
            if cur_pin not in pg:
                pg.append(cur_pin)
            cur_pin = None
    if not macros or not pg:
        return None

    # Longest-first: `INVD1` must not shadow `INVD12` in the alternation.
    alt = "|".join(re.escape(c)
                   for c in sorted(set(macros), key=lambda c: (-len(c), c)))
    return PdkPowerModel(key=key or f"lef:{p.name}",
                         pg_pins=tuple(pg),
                         cell_prefix_re=r"(?:" + alt + r")")


def power_model_for(pdk: str,
                    cell_lef: Optional["Path | str"] = None
                    ) -> Optional[PdkPowerModel]:
    """Return the PdkPowerModel for `pdk`, or None when unrecognised.

    `cell_lef` (optional) is the PDK's own std-cell LEF. It is consulted ONLY
    when the NAME does not resolve to a table entry, so every named-PDK lane
    (sky130A / gf180mcu* / ihp-sg13g2) is byte-for-byte unchanged and only the
    lane that previously returned None — the project-staged / commercial one —
    now gets a model, derived from that PDK's own declarations."""
    named = _PDK_POWER_MODELS.get(_normalize_pdk(pdk))
    if named is not None:
        return named
    if cell_lef:
        return model_from_cell_lef(cell_lef, key=(pdk or "").strip() or None)
    return None


@dataclass
class EmitStats:
    pdk: str = ""
    rails: List[str] = field(default_factory=list)
    modules_seen: int = 0
    modules_patched: int = 0
    instances_patched: int = 0
    instances_already_pg: int = 0
    skipped_reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "pdk": self.pdk,
            "rails": self.rails,
            "modules_seen": self.modules_seen,
            "modules_patched": self.modules_patched,
            "instances_patched": self.instances_patched,
            "instances_already_pg": self.instances_already_pg,
            "skipped_reason": self.skipped_reason,
        }


# A module spans `module <name> ( ... ) ; <body> endmodule`. Post-synthesis
# gate netlists are flat (no nested modules), so a non-greedy endmodule scan is
# exact.
_MODULE_RE = re.compile(
    r"(?P<head>\bmodule\s+(?P<name>\\?[^\s(]+)\s*"
    r"(?P<ports>\((?P<portlist>[^;]*?)\))?\s*;)"
    r"(?P<body>.*?)"
    r"(?P<end>\bendmodule\b)",
    re.DOTALL,
)


def _find_instance_conn_spans(body: str, cell_re: re.Pattern
                              ) -> List[Tuple[int, int, str, bool]]:
    """Locate every std-cell instance's connection-list parens in `body`.

    Returns (conn_open_idx, conn_close_idx, cell_name, already_has_pg) tuples,
    where conn_open_idx is the index of the '(' that opens the instance's port
    connection list and conn_close_idx the index of the matching ')'. `body`
    must be a single module body (no nested module). Balanced-paren scan handles
    `.A(net)` connections and `{a,b}` concatenations."""
    out: List[Tuple[int, int, str, bool]] = []
    # cell_name  inst_name  (   — the instance opener. Optional (* attr *) is
    # NOT consumed here (it precedes cell_name and does not disturb the match).
    opener = re.compile(
        r"(?P<cell>" + cell_re.pattern + r"[A-Za-z0-9_$]*)"
        r"\s+(?P<inst>\\?[^\s(]+)\s*\(")
    for m in opener.finditer(body):
        open_idx = m.end() - 1              # index of the '('
        depth = 0
        i = open_idx
        n = len(body)
        close_idx = -1
        while i < n:
            c = body[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
            i += 1
        if close_idx < 0:
            continue                        # unterminated — skip defensively
        conn = body[open_idx + 1:close_idx]
        already = bool(re.search(r"\.\s*(?:VPWR|VGND|VPB|VNB|VDD|VSS|VNW|VPW)"
                                 r"\s*\(", conn))
        out.append((open_idx, close_idx, m.group("cell"), already))
    return out


def _rail_connection_map(rails: List[str], tie_wells_to_rails: bool
                         ) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Return (conn_pairs, decl_rails) for the four PG pins.

    `rails` = model.pg_pins = (power, ground, well-of-power, well-of-ground),
    e.g. sky130 (VPWR, VGND, VPB, VNB) / gf180 (VDD, VSS, VNW, VPW).

    DEFAULT (`tie_wells_to_rails=False`) — name-for-name: each pin connects to a
    same-named wire and all four are declared. This is the part-1 model that
    matches a layout carrying four DISTINCT globalised rails.

    `tie_wells_to_rails=True` — the PHYSICAL sky130/gf180 well-tie: the n-well
    body pin (VPB/VNW) ties to the POWER rail and the p-substrate body pin
    (VNB/VPW) ties to the GROUND rail, so only the two real rails are declared.
    This mirrors a routed DEF whose power SPECIALNET carries the VPB pins and
    whose ground SPECIALNET carries the VNB pins (the wells are tied to the rails
    at the PDN), i.e. the layout a physically-correct Magic extraction produces —
    verified live: without it netgen reports 2 extra schematic-only well nets."""
    power, ground = rails[0], rails[1]
    # A TAPLESS PDK exposes only the two real rails and no body pins at all
    # (IHP SG13G2: PIN VDD / PIN VSS and nothing else). There is no well pin
    # to tie, so both models collapse to the same name-for-name mapping.
    # Without this the four-pin unpacking below raised IndexError on any
    # 2-pin model and the power-aware LVS upgrade could never be offered.
    if len(rails) < 4:
        return [(p, p) for p in rails], list(rails)
    wpow, wgnd = rails[2], rails[3]
    if tie_wells_to_rails:
        conn = [(power, power), (ground, ground), (wpow, power), (wgnd, ground)]
        return conn, [power, ground]
    return [(p, p) for p in rails], list(rails)


def _inject_module_rails(head: str, portlist: Optional[str],
                         rails: List[str], as_ports: bool) -> str:
    """Return the module header carrying the power rails.

    DEFAULT (`as_ports=False`) — the netgen-global flow: the rails are declared
    as module-internal `wire`s and left OUT of the port list. netgen's setup
    `global`-ises them (see lvs_netgen_setup_emit Rule 1), so they connect across
    the whole design AND the schematic's top-level port list stays signal-only —
    matching a CORE-ONLY extracted layout whose top exposes NO power ports.
    Adding them as top ports instead makes netgen report `port errors` (a
    top-level port-list mismatch) against such a layout — empirically verified.

    `as_ports=True` — the pad-ring / OpenLane convention: the rails are ALSO
    added to the port list and declared `inout`, for flows whose extracted
    layout DOES expose the rails as top-level pins (e.g. a Caravel wrapper). Both
    are idempotent. `rails` is the list of rails to DECLARE (two when the wells
    are tied to the rails, four otherwise)."""
    wire_decl = "\n  wire " + ", ".join(rails) + ";"
    if not as_ports:
        return head + wire_decl
    inout_decl = "".join(f"\n  inout {r};" for r in rails)
    if portlist is None:
        # `module foo ;` (no port list) — rare; give it one.
        new_head = re.sub(r"\bmodule\s+(\\?[^\s(]+)\s*;",
                          lambda mm: f"module {mm.group(1)} ("
                          + ", ".join(rails) + ");",
                          head, count=1)
        return new_head + inout_decl
    # Insert the rails just before the closing ')' of the port list.
    close = head.rfind(")")
    sep = "" if portlist.strip().endswith((",",)) or not portlist.strip() \
        else ",\n    "
    new_head = head[:close] + sep + ", ".join(rails) + head[close:]
    return new_head + inout_decl


def _patch_module(head: str, name: str, portlist: Optional[str], body: str,
                  model: PdkPowerModel, stats: EmitStats,
                  as_ports: bool, tie_wells_to_rails: bool = False
                  ) -> Tuple[str, bool]:
    """Patch one module: thread rails through the header and inject PG pins on
    each std-cell instance. Returns (new_head + new_body, changed)."""
    cell_re = re.compile(model.cell_prefix_re)
    spans = _find_instance_conn_spans(body, cell_re)
    if not spans:
        return head + body, False           # module has no std-cells → leave it

    pins = list(model.pg_pins)
    conn_pairs, decl_rails = _rail_connection_map(pins, tie_wells_to_rails)
    pg_full = ", ".join(f".{pin}({tgt})" for pin, tgt in conn_pairs)

    # Collect every insertion as (position, text), then assemble the new body in
    # a SINGLE forward pass (O(N)). Per-instance full-body slicing would be
    # O(N^2) and blows up on a 200k-instance fill-annotated netlist.
    inserts: List[Tuple[int, str]] = []     # (insert_at_index, text)
    for open_idx, close_idx, _cell, already in spans:
        if already:
            stats.instances_already_pg += 1
            continue
        conn = body[open_idx + 1:close_idx]
        # Insert right after the '(' — keeps every original signal connection.
        insert = pg_full if conn.strip() == "" else pg_full + ", "
        inserts.append((open_idx + 1, insert))
        stats.instances_patched += 1

    inserts.sort(key=lambda t: t[0])
    out_parts: List[str] = []
    last = 0
    for pos, txt in inserts:
        out_parts.append(body[last:pos])
        out_parts.append(txt)
        last = pos
    out_parts.append(body[last:])
    new_body = "".join(out_parts)

    # Idempotency is per rail, not keyed on the first one.  Multiple physical
    # libraries can share VDD/VSS while an IO library additionally declares
    # DVDD/DVSS; injecting the whole second list would redeclare VDD/VSS and
    # make the generated Verilog invalid.  Conversely, seeing VDD alone must
    # not make an absent VSS disappear from the model.
    scope = head + body
    missing_rails = []
    for rail in decl_rails:
        rr = re.escape(rail)
        declared = bool(
            re.search(r"\bwire\b[^;]*\b" + rr + r"\b", scope)
            or re.search(r"\binout\s+" + rr + r"\b", scope))
        if not declared:
            missing_rails.append(rail)
    new_head = (head if not missing_rails else
                _inject_module_rails(head, portlist, missing_rails, as_ports))
    return new_head + new_body, True


def emit_power_aware_netlist(text: str, pdk: str, top: Optional[str] = None,
                             rails_as_ports: bool = False,
                             tie_wells_to_rails: bool = False,
                             cell_lef: Optional["Path | str"] = None,
                             additional_lefs: Optional[List[object]] = None,
                             ) -> Tuple[str, Dict[str, object]]:
    """Transform a gate netlist into a POWER-AWARE netlist.

    `pdk`  : sky130A / gf180mcuC / gf180mcuD (loose names accepted).
    `top`  : if given, ONLY the named module is patched (plus any child module
             it instantiates that we also patch); if None, every module that
             instantiates PDK std-cells is patched.
    `rails_as_ports` : False (default) declares the rails as module-internal
             wires globalised by the netgen setup — the correct mode for a
             CORE-ONLY extracted layout (no power top ports). True ALSO adds them
             to the port list as `inout` (the pad-ring / Caravel convention).
    `tie_wells_to_rails` : False (default) keeps the four PG pins name-for-name
             (VPB→VPB, VNB→VNB) as four distinct globalised rails. True ties the
             well body pins to the rails (VPB→VPWR, VNB→VGND / VNW→VDD, VPW→VSS)
             and declares only the two real rails — the PHYSICAL sky130/gf180
             well-tie, which is what a routed DEF (power SPECIALNET carrying the
             VPB pins) extracts to. Use for a DEF-direct extracted layout so
             netgen reaches a genuine match (else 2 schematic-only well nets).
    Returns (new_text, stats_dict). Idempotent: a netlist that already carries
    the PG pins is returned with instances_patched=0. chip-AGNOSTIC."""
    stats = EmitStats(pdk=_normalize_pdk(pdk))
    model = power_model_for(pdk, cell_lef=cell_lef)
    if model is None:
        stats.skipped_reason = (
            f"unrecognised PDK '{pdk}' — no power model"
            + ("" if cell_lef else
               " and no cell LEF supplied to derive one from"))
        return text, stats.as_dict()
    if not stats.pdk:
        # A project-staged PDK has no canonical table key; record the model
        # that was actually used so the artifact never reads as "no PDK".
        stats.pdk = model.key
    models: List[Tuple[PdkPowerModel, bool]] = [(model, tie_wells_to_rails)]
    for index, lef in enumerate(additional_lefs or []):
        extra = model_from_cell_lef(lef, key=f"additional-lef:{index}")
        if extra is not None:
            models.append((extra, False))

    stats.rails = []
    for current, _tie in models:
        for rail in current.pg_pins:
            if rail not in stats.rails:
                stats.rails.append(rail)

    def _apply(source: str, current: PdkPowerModel,
               current_tie: bool) -> str:
        pieces: List[str] = []
        last = 0
        for m in _MODULE_RE.finditer(source):
            stats.modules_seen += 1
            pieces.append(source[last:m.start()])
            name = (m.group("name") or "").lstrip("\\")
            head = m.group("head")
            portlist = m.group("portlist")
            body = m.group("body")
            end = m.group("end")
            do_this = (top is None) or (name == top.lstrip("\\"))
            if do_this:
                patched, changed = _patch_module(
                    head, name, portlist, body, current, stats,
                    rails_as_ports, current_tie)
                if changed:
                    stats.modules_patched += 1
                pieces.append(patched + end)
            else:
                pieces.append(head + body + end)
            last = m.end()
        pieces.append(source[last:])
        return "".join(pieces)

    new_text = text
    for current, current_tie in models:
        new_text = _apply(new_text, current, current_tie)

    if stats.modules_seen == 0:
        stats.skipped_reason = "no module found in netlist"
    return new_text, stats.as_dict()


def emit_to_file(netlist: Path, pdk: str, out: Path,
                 top: Optional[str] = None,
                 rails_as_ports: bool = False,
                 tie_wells_to_rails: bool = False,
                 cell_lef: Optional["Path | str"] = None,
                 additional_lefs: Optional[List[object]] = None,
                 ) -> Dict[str, object]:
    """Read `netlist`, emit the power-aware version to `out`, return stats."""
    text = netlist.read_text(errors="replace")
    new_text, stats = emit_power_aware_netlist(
        text, pdk, top=top, rails_as_ports=rails_as_ports,
        tie_wells_to_rails=tie_wells_to_rails, cell_lef=cell_lef,
        additional_lefs=additional_lefs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(new_text)
    stats["output"] = str(out)
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit a POWER-AWARE gate netlist (VPWR/VGND rails + per-cell "
                    "PG connectivity) so netgen reaches a genuine power-verified "
                    "LVS match (the LVS root fix).")
    ap.add_argument("--netlist", required=True, type=Path,
                    help="input gate netlist (.v)")
    ap.add_argument("--pdk", required=True,
                    help="PDK: sky130A | gf180mcuC | gf180mcuD")
    ap.add_argument("--top", default=None,
                    help="only patch this module (default: every std-cell module)")
    ap.add_argument("--rails-as-ports", action="store_true",
                    help="also add the rails to the top port list as `inout` "
                         "(pad-ring/Caravel flows whose layout exposes power "
                         "pins); default declares them as globalised wires")
    ap.add_argument("--tie-wells-to-rails", action="store_true",
                    help="tie the well body pins to the rails (VPB→VPWR, "
                         "VNB→VGND) and declare only the two real rails — the "
                         "physical sky130/gf180 well-tie, for matching a "
                         "DEF-direct extracted layout")
    ap.add_argument("--out", type=Path, default=None,
                    help="output path (default: <netlist>.pwraware.v)")
    ap.add_argument("--json", dest="json_out", type=Path, default=None,
                    help="write the stats JSON here")
    ns = ap.parse_args(argv)

    if not ns.netlist.is_file():
        print(f"ERROR: netlist not found: {ns.netlist}", file=sys.stderr)
        return 2
    out = ns.out or ns.netlist.with_suffix(".pwraware.v")
    stats = emit_to_file(ns.netlist, ns.pdk, out, top=ns.top,
                         rails_as_ports=ns.rails_as_ports,
                         tie_wells_to_rails=ns.tie_wells_to_rails)
    txt = json.dumps(stats, indent=2)
    if ns.json_out:
        ns.json_out.parent.mkdir(parents=True, exist_ok=True)
        ns.json_out.write_text(txt + "\n")
    print(txt)
    # rc 0 only when we actually produced a power-aware netlist.
    if stats.get("skipped_reason"):
        return 1
    return 0 if stats.get("modules_patched", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
