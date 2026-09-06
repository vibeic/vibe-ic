#!/usr/bin/env python3
"""digital_hardmacro_gen.py — the PRODUCER for flow step 37.5ip.

Assembles the four-view IP delivery kit the cell/IP path terminates in:

    phase3/stage4/hardmacro/<design>.gds   staged from step 37's sign-off GDS
    phase3/stage4/hardmacro/<design>.lef   written by MAGIC, from that GDS
    phase3/stage4/hardmacro/<design>.lib   interface Liberty, from DEF + PDK
    phase3/stage4/hardmacro/<design>.v     blackbox view, from DEF + PDK

WHY THIS PRODUCER EXISTS AT ALL
===============================
MEASURED on this tree before this program: a completed digital sign-off run
(`phase3/stage4/gds/<top>.gds` present, DRC/LVS/STA closed) contains NO `.lef`
ANYWHERE — `find <project> -name '*.lef'` returns nothing. The flow could
place an ANALOG hard macro (A8 emits a LEF, step 15 reads one) and nothing it
produced digitally could be placed by anybody.

UPSTREAM AGREES THIS IS THE IP TERMINAL, AND SAYS SO BY DELETION.
`librelane/flows/chip.py` is `class Chip(Classic)` plus a substitution table
that contains, with its comment intact:

    "Magic.WriteLEF": None,   # "This is not a macro, there's no need to
                              #  write a LEF"

The CHIP flow switches the LEF write OFF, so the LEF write is exactly what
makes the Classic flow an IP-DELIVERY flow.

THE ALGORITHM, IN WORDS, BEFORE IT IS CODED
===========================================
Upstream's `pad.tcl` states its placement algorithm as a numbered comment
before coding it, and three of its eight steps are REFUSALS. Same shape here:

  1. Resolve the design name from the DEF's own `DESIGN <name> ;`.
     No DEF, or no DESIGN statement -> REFUSE (the kit has no identity).
  2. Locate step 37's sign-off GDS. Absent, or carrying no geometry record
     -> REFUSE (there is no layout to deliver, and a hollow one is worse
     than none).
  3. The GDS top cell must be the design name. It is not -> REFUSE (the
     abstract views would name a cell the layout does not contain).
  4. Read the signal interface from the DEF `PINS` section — the SAME input
     `Magic.WriteLEF` takes (`inputs = [GDS, DEF]`). Read the primary power and
     ground rail NAMES from the selected PDK std-cell LEF. If those rails are
     absent from top-level PINS, expose them at geometry the routed DEF's
     matching `SPECIALNETS` actually carries. No PINS, no authoritative PDK
     rails, or no matching routed rail geometry -> REFUSE_NOT_INTEGRABLE (a
     macro with no physical supplies cannot be integrated, and inventing a
     rail name or rectangle would be fabrication).
  5. Stage the GDS into the kit. An existing kit file that already
     carries the supply interface this run derived is never
     overwritten; one that does NOT is REPLACED, and the replacement
     is named in the record and on the run's own output. A kit is a
     delivery: it may be repaired, and it may not be swapped in
     silence.
  6. Write the LEF BY CALLING MAGIC, through the PDK's own `.magicrc`,
     mirroring `librelane/scripts/magic/lef.tcl`: `gds read`, `load <top>`,
     `lef write -hide` (the abstract form, which is upstream's default).
     Magic is looked for in THIS environment first and then in the EDA
     container the flow dispatches its tools into, and the technology and
     the launch go to whichever side answered — see "WHERE MAGIC ACTUALLY
     IS". Reachable on NEITHER side, or the PDK has no magicrc there ->
     SKIP with a stated reason and rc 2. DO NOT WRITE A LEF WRITER.
  7. Emit the Liberty and Verilog views from the complete pin list of step 4.
  8. Write the JSON record, whatever happened.

WHAT THIS PRODUCER DELIBERATELY DOES NOT DO
===========================================
  * IT DOES NOT CHARACTERISE TIMING. The Liberty it writes is an INTERFACE
    view: cell, pg_pins, pins, directions, and NO timing arc. Step 37.5ip
    declares no characterisation step, and inventing a delay number would be
    the worst possible lie in this kit — integration STA would close on it.
    The Liberty says so in its own header, and `digital_hardmacro_check`
    reports the kit in its `PASS_TIMING_UNCHARACTERISED` tier.
  * IT DOES NOT SET THE ABSTRACTION POLICY BY GUESSING. `-hide` is written
    because upstream's own script writes it by default; `--full-lef` and
    `--pinonly` expose the other two knobs (`MAGIC_WRITE_FULL_LEF`,
    `MAGIC_WRITE_LEF_PINONLY`) and the choice is RECORDED in the JSON.
  * IT DOES NOT REPLACE THE INDEPENDENT OUTPUT CHECKER. It performs one narrow
    producer acceptance: the LEF and Liberty THIS INVOCATION WROTE must carry
    the exact POWER/GROUND interface this run derived, because Magic can
    successfully write a LEF after silently dropping a port. It grades nothing
    it did not write — a view left over from an earlier run is that run's
    output, and describing it in this run's refusal was MEASURED to make two
    opposite faults print one sentence (see `run`). The separate checker still
    owns identity, extent, registration, complete interface, pin geometry,
    obstruction policy, and timing-tier verdicts. This program is invoked by
    the RUNNER, never from the step's gate.

BETTER THAN UPSTREAM IN ONE STATED WAY
======================================
LibreLane's `pad.tcl` refuses by `exit 1` with a printed message and leaves no
machine-readable record. Every outcome here — PRODUCED, REFUSED, SKIPPED, and
the reason — is written to the `--json` report before this program returns, so
a refusal is a datum a later step can read and not a line somebody has to find
in a log.

Usage:
    python3 digital_hardmacro_gen.py <project_dir> [--json <out>]
                                     [--pdk-root <dir>] [--cell-lef <file>]
                                     [--metal-prefix <stem>]
                                     [--container <name>]
                                     [--full-lef] [--pinonly]

Exit codes:
    0 = the kit was produced, or was already present and complete.
    1 = a precondition of the KIT was violated: no DEF / no DESIGN name / no
        sign-off GDS / a GDS with no geometry / a top-cell name that is not
        the design / no interface in the DEF. Refusals, each named.
    2 = a CAPABILITY is absent (no Magic reachable, no magicrc for the PDK) or
        an argument / fatal IO error. A disclosed gap, never a silent success.

chip-AGNOSTIC: no chip, vendor, SKU or process-node literal.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
from typing import Dict, List, Optional, Tuple

import _container_exec  # noqa: E402  container-side deadlines
import _path_layout as _pl
import _watchdog  # noqa: E402  plugin-wide progress-stall process supervision
from _atomic_artefact import write_text as atomic_write_text
from hardmacro_supply_intent import lef_pg_pins, liberty_pg_pins

# SHARED READERS, imported rather than re-typed — the same rule the gate
# follows. `parse_def_pins` is the canonical DEF PINS reader in this tree and
# already preserves the DEF's own port ORDER, which is the order a netlist
# writer emits; a second reader here would drift from it.
try:
    from lvs_def_port_seed import parse_def_pins, _extract_pins_block
except ImportError:  # pragma: no cover - programs/ is always on sys.path
    parse_def_pins = None      # type: ignore[assignment]
    _extract_pins_block = None  # type: ignore[assignment]
try:
    from analog_a5_layout_check import _gds_geometry_count
except ImportError:  # pragma: no cover
    _gds_geometry_count = None  # type: ignore[assignment]
try:
    from digital_hardmacro_check import gds_top_cells, base_name
except ImportError:  # pragma: no cover
    gds_top_cells = None       # type: ignore[assignment]
    base_name = None           # type: ignore[assignment]
try:
    from magic_port_extract_emit import build_shell_preamble
except ImportError:  # pragma: no cover
    build_shell_preamble = None  # type: ignore[assignment]

PROGRAM = "digital_hardmacro_gen"
VERSION = "1.1.0"

RC_OK, RC_REFUSED, RC_NO_CAPABILITY = 0, 1, 2

_DEF_DESIGN_RE = re.compile(r"(?m)^\s*DESIGN\s+(\S+)\s*;")
_DEF_PIN_START_RE = re.compile(r"-\s+(\S+)")
_DEF_USE_RE = re.compile(r"\+\s*USE\s+(\w+)", re.IGNORECASE)
_PG_USES = {"POWER", "GROUND"}
_DEF_UNITS_RE = re.compile(
    r"(?m)^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
_PINS_HEADER_RE = re.compile(r"(?m)^(?P<indent>\s*)PINS\s+(?P<n>\d+)\s*;")
_PINS_END_RE = re.compile(r"(?m)^\s*END\s+PINS\s*$")
_SPECIALNETS_BLOCK_RE = re.compile(
    r"(?ms)^\s*SPECIALNETS\s+\d+\s*;(?P<body>.*?)^\s*END\s+SPECIALNETS\s*$")
_SPECIALNET_ENTRY_RE = re.compile(r"(?m)^\s*-\s+(?P<name>\S+)")
_SPECIALNET_ROUTE_RE = re.compile(
    r"\+\s*(?:ROUTED|NEW)\s+(?P<layer>\S+)"
    r"(?:\s+(?P<width>\d+))?"
    r"(?:\s+\+\s+SHAPE\s+\S+)?\s*"
    r"\(\s*(?P<x1>-?\d+)\s+(?P<y1>-?\d+)\s*\)\s*"
    r"\(\s*(?P<x2>\*|-?\d+)\s+(?P<y2>\*|-?\d+)\s*\)",
    re.IGNORECASE | re.DOTALL)
#: Candidate DEFs, most-final first. The routed DEF is what the sign-off GDS
#: was streamed from, so its PINS are the interface the layout actually has.
_DEF_CANDIDATES = (
    "phase3/stage3/pnr/routed.def",
    "phase3/stage3/pnr/filled.def",
    "phase3/stage4/gds/routed.def",
)


def _require(obj, what: str):
    if obj is None:
        raise RuntimeError(f"{what} unavailable; {PROGRAM} cannot run")
    return obj


@dataclass
class Record:
    program: str = PROGRAM
    version: str = VERSION
    status: str = "PRODUCED"
    design: str = ""
    reason: str = ""
    produced: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    #: The subset of `produced` that DISPLACED an earlier run's bytes, and the
    #: stated reason it was displaced. A kit is a delivery; replacing one is a
    #: decision this producer publishes, never a silent side effect.
    replaced: List[str] = field(default_factory=list)
    replaced_reason: str = ""
    lef_policy: dict = field(default_factory=dict)
    interface: dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# ── inputs ────────────────────────────────────────────────────────────────

def find_def(project: Path) -> Optional[Path]:
    for rel in _DEF_CANDIDATES:
        p = project / rel
        if p.is_file():
            return p
    hits = sorted((project / "phase3").rglob("*.def")) \
        if (project / "phase3").is_dir() else []
    return hits[-1] if hits else None


def find_signoff_gds(project: Path) -> Optional[Path]:
    gds_dir = _pl.gds_dir(project)
    if not gds_dir.is_dir():
        return None
    hits = sorted(gds_dir.glob("*.gds"))
    return hits[0] if hits else None


@dataclass
class Pin:
    name: str
    direction: str
    is_pg: bool
    #: The DEF's own `USE` token, upper-cased ("POWER" / "GROUND" / "SIGNAL"
    #: / ""). CARRIED AND NOT COLLAPSED INTO `is_pg`, and the reason was
    #: MEASURED on a real kit: the Liberty's `pg_type` was derived from the
    #: DEF *DIRECTION*, which is INPUT/OUTPUT/INOUT and can never hold the
    #: token "GROUND", so EVERY supply pin came out `primary_power` — two
    #: rails declared as one, which is the supply-domain merge this step's
    #: gate exists to refuse. Whether a rail is power or ground lives in
    #: `USE`, so `USE` is what must reach the emitter.
    use: str = ""


@dataclass(frozen=True)
class SupplyRail:
    """One primary std-cell rail, derived from the selected PDK LEF."""

    name: str
    use: str
    layer: str
    width_um: float


def discover_stdcell_rails(lef_text: str,
                           metal_prefix: str = "met") -> List[SupplyRail]:
    """Return the PDK's primary routing-metal POWER and GROUND rails.

    Std-cell LEFs can also declare well/substrate pins as POWER/GROUND.  Those
    are not the follow-pin rails a delivered macro exposes.  The selection is
    therefore structural and matches the PnR producer's rule: a full-cell-width
    rectangle on the PDK's routing-metal stem outranks a non-routing well
    rectangle, regardless of names.  No design, PDK, vendor, or rail allowlist
    is used.
    """
    prefix = (metal_prefix or "met").lower()
    best: Dict[str, Tuple[Tuple[bool, float], SupplyRail]] = {}
    macro_w: Optional[float] = None
    cur_pin: Optional[str] = None
    cur_use: Optional[str] = None
    cur_layer: Optional[str] = None

    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        if s.startswith("MACRO "):
            macro_w = None
            cur_pin = cur_use = cur_layer = None
            continue
        m = re.match(r"SIZE\s+([0-9.]+)\s+BY", s, re.IGNORECASE)
        if m:
            macro_w = float(m.group(1))
            continue
        m = re.match(r"PIN\s+(\S+)", s, re.IGNORECASE)
        if m:
            cur_pin = m.group(1)
            cur_use = cur_layer = None
            continue
        if cur_pin and re.match(
                rf"END\s+{re.escape(cur_pin)}\s*$", s, re.IGNORECASE):
            cur_pin = cur_use = cur_layer = None
            continue
        if cur_pin is None:
            continue
        m = re.match(r"USE\s+(\S+)", s, re.IGNORECASE)
        if m:
            cur_use = m.group(1).rstrip(";").upper()
            continue
        m = re.match(r"LAYER\s+(\S+)", s, re.IGNORECASE)
        if m:
            cur_layer = m.group(1).rstrip(";")
            continue
        m = re.match(
            r"RECT\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+"
            r"(-?[0-9.]+)\s+(-?[0-9.]+)", s, re.IGNORECASE)
        if not (m and cur_use in _PG_USES and cur_layer and cur_pin):
            continue
        x1, y1, x2, y2 = (float(v) for v in m.groups())
        xspan, height = abs(x2 - x1), abs(y2 - y1)
        if macro_w and xspan < 0.8 * macro_w:
            continue
        rail = SupplyRail(cur_pin, cur_use, cur_layer, height)
        key = (cur_layer.lower().startswith(prefix), height)
        if cur_use not in best or key > best[cur_use][0]:
            best[cur_use] = (key, rail)

    if not _PG_USES <= set(best):
        return []
    return [best["POWER"][1], best["GROUND"][1]]


def _specialnet_entries(def_text: str) -> Dict[str, Tuple[str, str]]:
    """``name -> (USE, entry text)`` from the routed DEF SPECIALNETS."""
    bm = _SPECIALNETS_BLOCK_RE.search(def_text or "")
    if not bm:
        return {}
    body = bm.group("body")
    starts = list(_SPECIALNET_ENTRY_RE.finditer(body))
    out: Dict[str, Tuple[str, str]] = {}
    for i, match in enumerate(starts):
        entry = body[match.start():starts[i + 1].start()
                     if i + 1 < len(starts) else len(body)]
        um = _DEF_USE_RE.search(entry)
        out[match.group("name")] = (
            um.group(1).upper() if um else "", entry)
    return out


def add_supply_pins_to_def(
        def_text: str, rails: List[SupplyRail]
        ) -> Tuple[Optional[str], List[Pin], str]:
    """Expose missing PDK rails as top-level DEF pins on routed PG geometry.

    The rail NAME/TYPE comes only from the selected std-cell LEF.  The physical
    pin rectangle comes only from the routed DEF's same-name, same-USE
    SPECIALNET.  If either authority is missing or contradictory the function
    returns a reason and no modified text; it never fabricates an integrable
    view from a plausible name or arbitrary coordinate.
    """
    pins = read_interface(def_text)
    existing = {p.name: p for p in pins}
    existing_pg = {(p.name, p.use) for p in pins if p.is_pg}
    missing = [r for r in rails if (r.name, r.use) not in existing_pg]
    if not missing:
        return def_text, pins, ""
    for rail in missing:
        prior = existing.get(rail.name)
        if prior is not None and not prior.is_pg:
            return None, pins, (
                f"top-level pin {rail.name!r} is a {prior.use or 'SIGNAL'} pin, "
                f"but the selected PDK std-cell LEF declares it USE {rail.use}")

    units_m = _DEF_UNITS_RE.search(def_text)
    head_m = _PINS_HEADER_RE.search(def_text)
    end_m = _PINS_END_RE.search(def_text, head_m.end() if head_m else 0)
    if not (units_m and head_m and end_m):
        return None, pins, (
            "the DEF has no usable UNITS/PINS block in which to expose the "
            "PDK supply rails")
    units = int(units_m.group(1))
    special = _specialnet_entries(def_text)
    additions: List[str] = []
    derived: List[Pin] = []
    indent = head_m.group("indent") + "    "

    for rail in missing:
        found = special.get(rail.name)
        if not found:
            return None, pins, (
                f"selected PDK std-cell rail {rail.name!r} ({rail.use}) has no "
                "same-name routed SPECIALNET in the signed-off DEF")
        net_use, entry = found
        if net_use != rail.use:
            return None, pins, (
                f"selected PDK std-cell rail {rail.name!r} is USE {rail.use}, "
                f"but the routed DEF SPECIALNET declares USE {net_use or 'NONE'}")
        rm = _SPECIALNET_ROUTE_RE.search(entry)
        if not rm:
            return None, pins, (
                f"routed SPECIALNET {rail.name!r} carries no segment from which "
                "a physical macro pin rectangle can be derived")
        x, y = int(rm.group("x1")), int(rm.group("y1"))
        width = (int(rm.group("width")) if rm.group("width")
                 else max(1, round(rail.width_um * units)))
        low = -(width // 2)
        high = low + width
        additions.append(
            f"{indent}- {rail.name} + NET {rail.name} + DIRECTION INOUT "
            f"+ USE {rail.use}\n"
            f"{indent}  + PORT\n"
            f"{indent}    + LAYER {rm.group('layer')} "
            f"( {low} {low} ) ( {high} {high} )\n"
            f"{indent}    + FIXED ( {x} {y} ) N ;\n")
        derived.append(Pin(rail.name, "INOUT", True, rail.use))

    new_head = (f"{head_m.group('indent')}PINS "
                f"{int(head_m.group('n')) + len(derived)} ;")
    out = (def_text[:head_m.start()] + new_head + def_text[head_m.end():
           end_m.start()] + "".join(additions) + def_text[end_m.start():])
    return out, pins + derived, ""


def read_interface(def_text: str) -> List[Pin]:
    """The macro's interface, from the DEF's own PINS section.

    `parse_def_pins` supplies name + direction (shared reader, DEF order
    preserved). `USE` is not on its `DefPin`, so the POWER/GROUND
    classification is read here over the SAME entry split that reader uses —
    `_extract_pins_block` — rather than by a second, differently-shaped scan
    that could disagree with it about what an entry is.
    """
    pins = _require(parse_def_pins, "parse_def_pins")(def_text)
    use_by_name: Dict[str, str] = {}
    block = _require(_extract_pins_block, "_extract_pins_block")(def_text)
    for entry in (block or "").split(";"):
        m = _DEF_PIN_START_RE.search(entry)
        if not m:
            continue
        um = _DEF_USE_RE.search(entry)
        use_by_name[m.group(1)] = (um.group(1).upper() if um else "")
    return [Pin(name=p.name, direction=(p.direction or "INOUT"),
                is_pg=use_by_name.get(p.name, "") in _PG_USES,
                use=use_by_name.get(p.name, ""))
            for p in pins]


def group_buses(pins: List[Pin]) -> List[Tuple[str, str, Optional[Tuple[int, int]]]]:
    """`[(base, direction, (msb, lsb) | None)]`, in DEF order.

    A DEF spells a bus as one entry per BIT (`dout[0]`, `dout[1]`); a Verilog
    port and a Liberty `bus` group are declared once with a range. The range
    is derived from the bits the DEF actually carries — never assumed to start
    at zero and never widened past what is there.
    """
    order: List[str] = []
    bits: Dict[str, List[int]] = {}
    dirs: Dict[str, str] = {}
    bit_re = re.compile(r"^(.*?)[\[<](\d+)[\]>]$")
    for p in pins:
        m = bit_re.match(p.name)
        base = m.group(1) if m else p.name
        if base not in bits:
            order.append(base)
            bits[base] = []
            dirs[base] = p.direction
        if m:
            bits[base].append(int(m.group(2)))
    out = []
    for base in order:
        idx = sorted(bits[base])
        out.append((base, dirs[base], (max(idx), min(idx)) if idx else None))
    return out


# ── emitters (LEF is NOT among them — Magic writes that) ──────────────────

_V_DIR = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}


def emit_verilog(design: str, pins: List[Pin]) -> str:
    """A blackbox simulation view.

    SUPPLY PORTS ARE OMITTED, deliberately and in line with what
    `digital_hardmacro_check` documents as the one narrow exception: a Verilog
    view of a hard macro carries the LOGICAL interface; supplies are physical
    and live in the LEF (`USE POWER`/`USE GROUND`) and the Liberty (`pg_pin`).
    """
    sig = [p for p in pins if not p.is_pg]
    ports = []
    for base, direction, rng in group_buses(sig):
        kw = _V_DIR.get(direction.upper(), "inout")
        width = f" [{rng[0]}:{rng[1]}]" if rng else ""
        ports.append(f"    {kw} wire{width} {base}")
    body = ",\n".join(ports)
    pg = ", ".join(p.name for p in pins if p.is_pg) or "none declared"
    return (f"// {design} — blackbox simulation view of a delivered hard macro.\n"
            f"// Emitted by {PROGRAM} from signed-off DEF + selected PDK; the logical\n"
            f"// interface only. Supply pins ({pg}) are physical and are\n"
            f"// declared in the LEF and the Liberty, not here.\n"
            f"(* blackbox *)\n"
            f"module {design} (\n{body}\n);\n"
            f"endmodule\n")


_LIB_DIR = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}


def emit_liberty(design: str, pins: List[Pin]) -> str:
    """An INTERFACE Liberty — cell, pg_pins, pins, directions, NO timing.

    THE OMISSION IS THE POINT AND IT IS DECLARED IN THE FILE. A fabricated
    delay would be the most damaging value in this whole kit: integration STA
    would close on it and report timing met against a number nobody measured.
    `digital_hardmacro_check` reads the absence and reports the kit in its
    `PASS_TIMING_UNCHARACTERISED` tier, so the caveat travels with the verdict.
    """
    lines = [
        f"/* {design} — INTERFACE Liberty view of a delivered hard macro.",
        f" * Emitted by {PROGRAM} from signed-off DEF + selected PDK.",
        " *",
        " * NO TIMING ARC IS DECLARED, AND THAT IS DELIBERATE. This view",
        " * states the interface only; no characterisation has been run, so",
        " * no delay, transition or leakage number is asserted. Integration",
        " * STA over this cell is NOT closed timing — it is timing against an",
        " * uncharacterised macro, and the gate for this step reports it as",
        " * such. Replace this file with a characterised Liberty before",
        " * anybody closes a chip on it.",
        " */",
        f"library ({design}) {{",
        '  delay_model : table_lookup ;',
        f"  cell ({design}) {{",
    ]
    for p in pins:
        if p.is_pg:
            # FROM `USE`, NEVER FROM `DIRECTION`. A DEF DIRECTION is
            # INPUT/OUTPUT/INOUT; it cannot spell "GROUND", so a pg_type
            # derived from it is `primary_power` for every supply pin there
            # is. Measured on a real kit: a DEF declaring `VDD + USE POWER`
            # and `VSS + USE GROUND` produced a Liberty declaring BOTH as
            # `primary_power` — the two rails merged into one domain, in the
            # view integration STA reads, written by this flow.
            kind = ("primary_ground" if p.use.upper() == "GROUND"
                    else "primary_power")
            lines.append(f"    pg_pin ({p.name}) {{ pg_type : {kind} ; }}")
    for base, direction, rng in group_buses([p for p in pins if not p.is_pg]):
        d = _LIB_DIR.get(direction.upper(), "inout")
        if rng:
            lines.append(f"    bus ({base}) {{ direction : {d} ; "
                         f"bus_type : bus_{base} ; }}")
        else:
            lines.append(f"    pin ({base}) {{ direction : {d} ; }}")
    lines += ["  }", "}", ""]
    return "\n".join(lines)


# ── the LEF: Magic, through the PDK's own magicrc ─────────────────────────

#: WHAT THIS MODULE MIRRORS FROM UPSTREAM, AND WHAT PINS IT THERE
#:
#: `build_lef_tcl` below follows upstream's LEF-writing script, and three of
#: its decisions are DEFAULTS READ OFF UPSTREAM rather than choices made here:
#: the abstract (`-hide`) form, the absence of `-pinonly`, and the read-views
#: route rather than the GDS-only one. A default that upstream changes and we
#: do not is a silent divergence in a signed-off artefact — the GDS-only route
#: was measured to produce a LEF with ZERO PINS on a real run.
UPSTREAM_MIRROR: Dict[str, str] = {
    "upstream": "librelane/scripts/magic/lef.tcl",
    "mirrors": (
        "the LEF write sequence and its three PDK-scoped knobs, whose upstream "
        "defaults this module bakes in: the abstract form unless the full-LEF "
        "flag is set, no pin-only unless its flag is set, and the read-views "
        "route rather than the GDS-only one."),
    "pinned_by": (
        "tests/test_upstream_mirror_magic_lef.py"
        "::test_upstream_lef_write_defaults_are_the_ones_this_module_bakes_in"),
}


def build_lef_tcl(top: str, gds: str, def_file: str, out_lef: str,
                  full_lef: bool, pinonly: bool) -> str:
    """The Magic TCL, following `librelane/scripts/magic/lef.tcl`.

    THE `def read` IS LOAD-BEARING AND IT WAS MEASURED. Upstream's script has
    two routes and `MAGIC_LEF_WRITE_USE_GDS` picks between them; its DEFAULT
    is FALSE — read the views and `read_def`, NOT the GDS alone. The first
    draft of this producer took the GDS-only route and the result, on a real
    signed-off run, was this:

        MACRO spm
          CLASS BLOCK ;
          SIZE 285.000 BY 285.000 ;
          OBS  …
        END spm

    A LEF WITH ZERO PINS. Magic reported `Unknown layer/datatype in boundary,
    layer=901 type=0` while reading it: the port labels are on layers this
    PDK's Magic technology does not map, so no label became a port and the
    abstract came out with an outline, obstructions, and nothing to connect
    to. `gds labels yes` + `port makeall` did not change it — still 0 pins.
    Adding `def read <routed.def>` produced 41 PINs, exactly the DEF's
    `PINS 41 ;` count, each with DIRECTION, USE and a PORT layer. No tech LEF
    is required; the technology from the PDK's own magicrc suffices.

    So: the GDS supplies the GEOMETRY, the DEF supplies the PORTS, and the
    abstraction knobs are upstream's own — `-hide` unless
    `MAGIC_WRITE_FULL_LEF`, plus `-pinonly` when `MAGIC_WRITE_LEF_PINONLY`.
    """
    opts = []
    if not full_lef:
        opts.append("-hide")       # upstream's default: the ABSTRACT view
    if pinonly:
        opts.append("-pinonly")
    tail = (" " + " ".join(opts)) if opts else ""
    return (f"# Emitted by {PROGRAM}; sequence follows librelane\n"
            f"# scripts/magic/lef.tcl. Geometry from the GDS, PORTS from the\n"
            f"# DEF — the GDS-only route yields an abstract with no pin at all.\n"
            f"drc off\n"
            f"gds read {gds}\n"
            f"load {top}\n"
            f"def read {def_file}\n"
            f"load {top}\n"
            f"select top cell\n"
            f"lef write {out_lef}{tail}\n"
            f"puts stdout \"DIGITAL_LEF_WRITE_DONE {top}\"\n")


def _magicrc_for(pdk_root: str) -> Optional[str]:
    """The PDK's OWN magicrc, located rather than reconstructed.

    The tool never re-derives PDK rules — upstream's rule 4. When no magicrc
    is found the capability is ABSENT and this program skips with that stated
    reason; it does not fall back to a default technology.

        IT USED TO PICK THE ALPHABETICALLY FIRST PDK AND CALL THAT THE DESIGN'S.
    The body was `sorted(root.glob("*/libs.tech/magic/*.magicrc"))[0]`, and
    MEASURED in the shipped image, where PDK_ROOT is the PARENT of every
    installed PDK -- which is what this program's own `--pdk-root` default
    reads:

        PDK_ROOT                             = /foss/pdks
        _magicrc_for("/foss/pdks")           -> gf180mcuD/.../gf180mcuD.magicrc
        _magicrc_for("/foss/pdks/sky130A")   -> None
        _magicrc_for("/foss/pdks/gf180mcuD") -> None

    Two defects in three lines, and they compound into a third:

    1. WITH THE CONVENTIONAL `PDK_ROOT`, EVERY DESIGN GOT ONE TECHNOLOGY --
       whichever sorts first. A design on any other PDK is abstracted against a
       technology that does not define its layers.
    2. PASSING THE CORRECT, SPECIFIC PDK DIRECTORY RETURNED None. The glob
       requires a `*/` level, so `<root>/<pdk>` -- the obviously right thing for
       a caller to pass -- found nothing and the capability read as ABSENT. The
       one call that could have been right was the one that failed.
    3. SO THE FAILURE IS SILENT. Magic does not refuse an unknown layer; it
       reports `Unknown layer/datatype` and writes a LEF with an OUTLINE AND NO
       PINS. That is the artefact `_LEF_HAS_PIN_RE` below already refuses to
       stage -- the pin-less abstract is the SYMPTOM and this was a cause.

    THE RULE NOW, and it refuses rather than guesses. `run()` receives
    `pdk_root` and reads the design name off the DEF; it has NO input naming the
    design's PDK, so it cannot choose correctly even in principle:

      * `<pdk_root>/libs.tech/magic/*.magicrc` -- pdk_root IS the PDK. Use it.
      * exactly ONE `*/libs.tech/magic/*.magicrc` -- only one technology is
        installed, so there is no choice to get wrong. Use it.
      * MORE THAN ONE -- REFUSE. Nothing here says which the design is on.

    Returning None is not a regression: it is the ABSENT capability this
    module already promises to skip on with a stated reason, instead of a wrong
    abstract that looks delivered.

    chip/PDK-AGNOSTIC: no PDK name appears here; the rule is about HOW MANY
    technologies are in scope, never which.
    """
    root = Path(pdk_root) if pdk_root else None
    if not root or not root.is_dir():
        return None
    own = sorted(root.glob("libs.tech/magic/*.magicrc"))
    if own:
        return str(own[0])
    hits = sorted(root.glob("*/libs.tech/magic/*.magicrc"))
    if len(hits) == 1:
        return str(hits[0])
    return None


def magicrc_candidates(pdk_root: str) -> List[str]:
    """Every magicrc `_magicrc_for` can see under `pdk_root`, for the message.

    A refusal that does not say WHAT it was choosing between is a refusal
    nobody can act on.
    """
    root = Path(pdk_root) if pdk_root else None
    if not root or not root.is_dir():
        return []
    own = sorted(root.glob("libs.tech/magic/*.magicrc"))
    return [str(x) for x in (own or sorted(
        root.glob("*/libs.tech/magic/*.magicrc")))]


# ── WHERE MAGIC ACTUALLY IS ───────────────────────────────────────────────
#
# THE MEASURED DEFECT THIS SECTION EXISTS TO CLOSE. The LEF write asked
# `shutil.which("magic")` and, on a real sign-off run, answered
#
#     ENV_UNAVAILABLE  digital_hardmacro_gen
#     [SKIPPED_NO_CAPABILITY] magic is not on PATH in this environment
#
# while that same run had already streamed its GDS out WITH MAGIC — its own
# provenance line reads `tool magic, version 8.3.681, exit_code 0`. Both
# statements were true of the environment each was made in, and that is the
# entire defect: the runner executes on the HOST and dispatches every EDA
# tool into the EDA CONTAINER, so a probe that reads THIS process's PATH
# interrogates the one environment the tools are known not to be in. The
# report is not "magic is missing", it is "I looked in the wrong place", and
# the two are indistinguishable to everybody downstream.
#
# THE PDK IS ON THE SAME SIDE AS THE TOOLS, so this was the same error three
# times over: the `magic` probe, the `_magicrc_for` glob (`/foss/pdks` does
# not exist on the host either) and the `magic` launch itself all read the
# host. Resolving a SITE once and doing all three there is what keeps them
# from disagreeing.
#
# The plugin has closed this class twice already — `_klayout_launch`
# .find_runner (host first, then `$VIBEIC_EDA_CONTAINER`) and
# `analog_pdk_deck_context.container_reader` (host read, then `docker exec
# cat`). This is that resolution for Magic, and it follows the same order.
# HOST FIRST is not a preference: it is what makes one program correct in
# both environments. Inside the image — where the plugin's own tests and an
# in-image flow run live — magic is on PATH and there is no docker client at
# all; on the host it is the container that has magic and the PDK.
#
# WHAT IT MUST STILL BE ABLE TO SAY IS NO. A probe that cannot report an
# absent tool is worse than one that reports it wrongly, so absence is
# resolved to None here and stated by the caller as the capability gap it is
# — never quietly turned into a pass.

#: The EDA container the flow dispatches tools into. Same env var and same
#: default `_klayout_launch` uses, so a per-run container name is set once.
#: `_eda_pin.default_container_name()` IS this expression, plus the part
#: that was missing: the default half derives from the pinned digest
#: instead of being the shared literal `vibeic-eda`.  MEASURED 2026-09-07
#: on 8hd-3 -- the container holding that shared name was running 0.3.46
#: while the pin demanded 0.3.47, and a run that attached to it recorded
#: image provenance PASS about the wrong image.  `VIBEIC_EDA_CONTAINER` is
#: read exactly as before and still wins.
DEFAULT_CONTAINER = _pin.default_container_name()


def _sh(argv: List[str], timeout: int = 900) -> Tuple[int, str, str]:
    """PROGRESS-SUPERVISED subprocess. The single monkeypatch surface for the
    tests.

    `timeout` is the STALL GRACE, not a runtime bound. It used to be
    `subprocess.run(timeout=)`, whose expiry returned rc 124 — a FAILING
    VERDICT about the subject derived from a number that describes this host,
    not the job. `docker cp` of a multi-gigabyte GDS on a loaded machine, or a
    `magic --version` behind a cold image pull, are slow for reasons that have
    nothing to do with whether they would have succeeded. The watchdog kills
    only a job whose CPU, I/O and output have ALL sat flat for `timeout`
    seconds — a job that is genuinely making no forward progress — and reports
    that under its own distinct rc, never as the tool's own failure."""
    try:
        res = _watchdog.run_host_supervised([str(a) for a in argv],
                                            stall_grace_s=float(timeout))
    except OSError as exc:
        # The launch itself failed (no such binary, not executable, …). The
        # supervisor resolves FileNotFoundError to `launch_error` itself; every
        # other OSError still arrives here, and kept its historical rc 127 so
        # callers that read "could not start" are unchanged.
        return 127, "", str(exc)
    if res.outcome == "launch_error":
        return 127, "", res.err
    return res.rc, res.out or "", res.err or ""


def choose_magicrc(own: List[str], nested: List[str]) -> Optional[str]:
    """THE rule for picking a technology, over listings from ANY filesystem.

    Written once and applied to both the host and the container listing: two
    copies of this rule would be free to disagree about which technology a
    design is abstracted against, which is the failure `_magicrc_for`'s own
    docstring records. See there for why more than one candidate REFUSES.
    """
    if own:
        return own[0]
    if len(nested) == 1:
        return nested[0]
    return None


class MagicSite:
    """The ONE environment magic, the PDK and the work files all live in.

    `container` empty (or the literal "host") means this process's own
    environment. Otherwise every read, every listing and the tool launch
    itself cross into that container, and the work files cross with
    `docker cp` — so the project may sit at any host path, mounted or not,
    including a pytest `tmp_path`.
    """

    def __init__(self, container: str = "") -> None:
        self.container = (container or "").strip()
        self.path: Optional[str] = None

    @property
    def in_container(self) -> bool:
        return self.container not in ("", "host")

    @property
    def where(self) -> str:
        return (f"container {self.container!r}" if self.in_container
                else "this environment")

    # ── probes ────────────────────────────────────────────────────────────
    def has_magic(self) -> bool:
        if not self.in_container:
            return shutil.which("magic") is not None
        return self.sh("command -v magic >/dev/null 2>&1", timeout=60)[0] == 0

    def magic_version(self) -> str:
        """The tool's own banner, from the binary this site would launch.

        Launched WITHOUT a shell in this environment, because that is how
        the LEF write launches it: a login shell resolves its own PATH and
        could answer for a different binary than the one that will run.
        """
        if self.in_container:
            rc, out, err = self.sh("magic --version", timeout=60)
        else:
            rc, out, err = _sh(["magic", "--version"], timeout=60)
        text = (out or err).strip()
        return text.splitlines()[-1] if rc == 0 and text else ""

    def _ls(self, pattern: str) -> List[str]:
        """Absolute paths matching `pattern`, LISTED WHERE THEY LIVE.

        Only lines that are absolute paths are kept. The image's profile
        prints a startup banner (`[INFO] Final PATH variable: ...`) on every
        LOGIN shell, ahead of the command's own output, and a listing that
        counted those lines as candidates would hand `choose_magicrc` a
        first entry that is not a technology file at all.
        """
        _rc, out, _err = self.sh(f"ls -1d {pattern} 2>/dev/null", timeout=60)
        return sorted(x.strip() for x in (out or "").splitlines()
                      if x.strip().startswith("/"))

    def magicrc(self, pdk_root: str) -> Optional[str]:
        """The technology file, chosen by `choose_magicrc` where it lives."""
        if not self.in_container:
            return _magicrc_for(pdk_root)
        if not pdk_root:
            return None
        q = shlex.quote(pdk_root.rstrip("/"))
        return choose_magicrc(self._ls(f"{q}/libs.tech/magic/*.magicrc"),
                              self._ls(f"{q}/*/libs.tech/magic/*.magicrc"))

    def magicrc_candidates(self, pdk_root: str) -> List[str]:
        if not self.in_container:
            return magicrc_candidates(pdk_root)
        if not pdk_root:
            return []
        q = shlex.quote(pdk_root.rstrip("/"))
        own = self._ls(f"{q}/libs.tech/magic/*.magicrc")
        return own or self._ls(f"{q}/*/libs.tech/magic/*.magicrc")

    # ── the work directory ────────────────────────────────────────────────
    def open(self, host_tmp: Path) -> Tuple[bool, str]:
        if not self.in_container:
            host_tmp.mkdir(parents=True, exist_ok=True)
            self.path = str(host_tmp)
            return True, ""
        rc, out, err = _sh(["docker", "exec", self.container, "mktemp", "-d"],
                           timeout=60)
        if rc != 0 or not out.strip():
            return False, (f"cannot open a working directory in "
                           f"{self.where}: {(err or out).strip()[:200]}")
        self.path = out.strip()
        return True, ""

    def put(self, src: Path, name: str) -> Tuple[bool, str]:
        dst = f"{self.path}/{name}"
        if not self.in_container:
            try:
                Path(dst).write_bytes(Path(src).read_bytes())
                return True, ""
            except OSError as exc:
                return False, str(exc)
        rc, out, err = _sh(["docker", "cp", str(src),
                            f"{self.container}:{dst}"], timeout=300)
        return (rc == 0), (err or out).strip()[:200]

    def put_text(self, text: str, name: str, host_tmp: Path
                 ) -> Tuple[bool, str]:
        tmp = host_tmp / f".stage_{name}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        return self.put(tmp, name)

    def get(self, name: str, dst: Path) -> Tuple[bool, str]:
        src = f"{self.path}/{name}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not self.in_container:
            try:
                dst.write_bytes(Path(src).read_bytes())
                return True, ""
            except OSError as exc:
                return False, str(exc)
        rc, out, err = _sh(["docker", "cp", f"{self.container}:{src}",
                            str(dst)], timeout=300)
        return (rc == 0 and dst.is_file()), (err or out).strip()[:200]

    def sh(self, cmd: str, timeout: int = 900) -> Tuple[int, str, str]:
        if not self.in_container:
            return _sh(["bash", "-lc", cmd], timeout=timeout)
        # THE DEADLINE GOES WHERE THE TOOL IS. A client-side timeout kills
        # the `docker exec` client and leaves the tool running, holding its
        # cores and never finishing the file the caller waits for — the
        # measured defect `_container_exec` exists for.
        try:
            cp = _container_exec.run_in_container(self.container, cmd,
                                                  deadline_s=int(timeout))
        except (subprocess.SubprocessError, OSError) as exc:
            # A wedged container, or no docker client at all: NOT a verdict
            # about the design. Surfaced as a non-zero rc with the reason.
            return 127, "", str(exc)
        return cp.returncode, cp.stdout or "", cp.stderr or ""

    def close(self) -> None:
        if self.path and self.in_container:
            _sh(["docker", "exec", self.container, "rm", "-rf", self.path],
                timeout=60)
            self.path = None


def find_magic_site(container: str = "") -> Optional[MagicSite]:
    """Resolve WHERE magic is: this environment first, then the container.

    None means the tool is genuinely absent from both, and the caller must
    then state the capability gap. Never returns a site whose magic it has
    not just seen answer.
    """
    here = MagicSite("")
    if here.has_magic():
        return here
    if shutil.which("docker") is None:
        return None
    name = (container or DEFAULT_CONTAINER).strip()
    if not name or name == "host":
        return None
    there = MagicSite(name)
    return there if there.has_magic() else None


def magic_absent_reason(container: str = "") -> str:
    """Why no magic could be reached — naming EVERY place that was looked."""
    name = (container or DEFAULT_CONTAINER).strip() or DEFAULT_CONTAINER
    if shutil.which("docker") is None:
        return ("magic is not on PATH in this environment and there is no "
                "docker client here to reach an EDA container with")
    return (f"magic is not on PATH in this environment and not on PATH "
            f"inside container {name!r} either")


def _cell_lef_candidates(site: Optional[MagicSite],
                         pdk_root: str) -> List[str]:
    """Std-cell LEF candidates under the selected PDK, where the PDK lives."""
    if not pdk_root:
        return []
    root = Path(pdk_root)
    if root.is_dir():
        return [str(p) for p in sorted(root.glob("libs.ref/*/lef/*.lef"))]
    if site is not None and site.in_container:
        q = shlex.quote(pdk_root.rstrip("/"))
        return site._ls(f"{q}/libs.ref/*/lef/*.lef")
    return []


def _read_site_text(site: Optional[MagicSite], path: str) -> Optional[str]:
    """Read a PDK file from the same host/container boundary Magic uses."""
    p = Path(path) if path else None
    if p is not None and p.is_file():
        try:
            return p.read_text(errors="replace")
        except OSError:
            return None
    if site is None or not site.in_container or not path:
        return None
    rc, out, _err = site.sh(f"cat {shlex.quote(path)}", timeout=120)
    return out if rc == 0 and out else None


def resolve_stdcell_rails(site: Optional[MagicSite], pdk_root: str,
                          cell_lef: str = "", metal_prefix: str = "met"
                          ) -> Tuple[List[SupplyRail], str, str]:
    """``(rails, source, reason)``; never chooses among ambiguous libraries."""
    source = cell_lef
    if not source:
        candidates = _cell_lef_candidates(site, pdk_root)
        if len(candidates) != 1:
            return [], "", (
                f"the selected PDK exposes {len(candidates)} std-cell LEF "
                f"candidate(s) under `libs.ref/*/lef/*.lef`; exactly one or an "
                f"explicit --cell-lef is required to derive supply rail names"
                + (f": {', '.join(candidates)}" if candidates else ""))
        source = candidates[0]
    text = _read_site_text(site, source)
    if text is None:
        return [], source, (
            f"the selected PDK std-cell LEF {source!r} could not be read in "
            f"{site.where if site is not None else 'this environment'}")
    rails = discover_stdcell_rails(text, metal_prefix)
    if not rails:
        return [], source, (
            f"the selected PDK std-cell LEF {source!r} does not establish one "
            "routing-metal USE POWER rail and one USE GROUND rail")
    return rails, source, ""


_LEF_HAS_PIN_RE = re.compile(r"(?m)^\s*PIN\s+\S+")


def magic_env_for(magicrc: str, pdk_root: str) -> Dict[str, str]:
    """`PDK` and `PDK_ROOT` as the SYSTEM magicrc expects to read them.

    MEASURED, on the real sign-off GDS, once magic could finally be reached:
    with `PDK_ROOT` set to the PDK DIRECTORY — which is what `--pdk-root`
    now carries, because naming the design's own PDK is what stopped the
    alphabetically-first technology being chosen — magic starts, exits 0 and
    writes NO LEF:

        Could not find file '/…/sky130A/sky130A/libs.tech/magic/sky130A.tech'

    The system magicrc composes `$PDK_ROOT/$PDK/...` and reads both at
    startup (`magic_port_extract_emit.build_shell_preamble` records the same
    constraint), so the two are read TOGETHER and neither can be set without
    the other. Both are derived from the technology file that was actually
    CHOSEN, so they cannot describe a different PDK from the one the
    abstract is written against.
    """
    rc = Path(magicrc)
    # <pdk_dir>/libs.tech/magic/<name>.magicrc — three levels up is the PDK.
    if len(rc.parents) >= 3:
        pdk_dir = rc.parents[2]
        return {"PDK": pdk_dir.name, "PDK_ROOT": str(pdk_dir.parent)}
    return {"PDK_ROOT": pdk_root}


def _accept_lef(produced: Path, out_lef: Path, rc: int,
                tool_output: str) -> Tuple[bool, str]:
    """The verdict on what magic wrote. ONE copy, whichever site wrote it.

    A PIN-LESS ABSTRACT IS WORSE THAN NO ABSTRACT — it is an outline and a
    set of obstructions with nothing to connect to, and it LOOKS like a
    delivered view. Same posture as the sibling producer
    `analog_hardmacro_gds_emit` takes on a hollow GDS: it is not left on
    disk. The gate would refuse it anyway; shipping it and letting the gate
    find it would mean the flow published a broken artefact.
    """
    if not produced.is_file() or produced.stat().st_size == 0:
        tail = (tool_output or "").strip().splitlines()[-3:]
        return False, (f"magic exited {rc} and wrote no LEF; "
                       f"last output: {' | '.join(tail) or '(none)'}")
    if not _LEF_HAS_PIN_RE.search(produced.read_text(errors="replace")):
        return False, (
            "magic wrote a LEF with NO `PIN` block — an outline and "
            "obstructions with nothing to connect to. The macro's ports "
            "did not reach Magic, so the abstract is not deliverable and "
            "has not been staged.")
    out_lef.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(produced, out_lef)
    return True, ""


def _write_lef_here(top: str, gds: Path, def_file: Path, out_lef: Path,
                    pdk_root: str, magicrc: str, full_lef: bool,
                    pinonly: bool, timeout_s: int) -> Tuple[bool, str]:
    """Magic in THIS process's environment — the path taken inside the image."""
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        staged = work / f"{top}.gds"
        shutil.copy(gds, staged)
        staged_def = work / f"{top}.def"
        shutil.copy(def_file, staged_def)
        script = work / "lef.tcl"
        script.write_text(build_lef_tcl(top, str(staged), str(staged_def),
                                        str(work / f"{top}.lef"),
                                        full_lef, pinonly))
        env = dict(os.environ)
        env.update(magic_env_for(magicrc, pdk_root))
        cmd = ["magic", "-noconsole", "-dnull", "-rcfile", magicrc,
               str(script)]
        # BLOCKING PROCESS POLICY: magic is a potentially long EDA run, so it
        # goes through the plugin-wide progress watchdog rather than a bare
        # host launch with a wall-clock timeout. `timeout_s` is the STALL
        # GRACE — how long every forward-progress signal may sit flat — and
        # NOT the hard ceiling it used to be. As a ceiling it was still a
        # runtime guess producing a verdict: a magic run legitimately longer
        # than the caller's number was killed and booked as "did not
        # complete". Two things had to change together, because either alone
        # is unsound:
        #   * the bound moved off the wall clock onto forward progress, and
        #   * the launch moved to `run_host_supervised`, which injects the
        #     /proc CPU+I/O probe. Without it the ONLY progress signal is
        #     captured output, so a magic that computes quietly for longer
        #     than the grace reads as hung — a fixed-runtime kill wearing the
        #     watchdog's name. The ceiling stays at the module default (a 24 h
        #     pathological-loop backstop), which is what it is for.
        def _popen(argv, **kwargs):
            return subprocess.Popen(argv, cwd=str(work), **kwargs)

        try:
            cp = _watchdog.run_host_supervised(
                cmd, env=env, stall_grace_s=float(timeout_s),
                popen_factory=_popen)
        except OSError as exc:
            return False, f"magic did not complete: {exc}"
        if cp.outcome != "natural":
            # stalled / ceiling / launch_error are NOT a LEF verdict: say which.
            return False, (f"magic did not complete: watchdog reported "
                           f"{cp.outcome} after {cp.elapsed_s:.0f}s")
        return _accept_lef(work / f"{top}.lef", out_lef, cp.rc,
                           cp.err or cp.out)


def _write_lef_in_container(site: "MagicSite", top: str, gds: Path,
                            def_file: Path, out_lef: Path, pdk_root: str,
                            magicrc: str, full_lef: bool, pinonly: bool,
                            timeout_s: int) -> Tuple[bool, str]:
    """Magic where the runner already dispatches every other EDA tool.

    The inputs cross with `docker cp` rather than through a bind mount: the
    project may sit at any host path, and a producer that only works for a
    mounted one fails silently on the paths it was not tried against.
    """
    with tempfile.TemporaryDirectory() as td:
        host_tmp = Path(td)
        ok, why = site.open(host_tmp)
        if not ok:
            return False, why
        try:
            for src, name in ((gds, f"{top}.gds"), (def_file, f"{top}.def")):
                ok, why = site.put(Path(src), name)
                if not ok:
                    return False, (f"could not stage {name} into "
                                   f"{site.where}: {why}")
            work = site.path or ""
            tcl = build_lef_tcl(top, f"{work}/{top}.gds", f"{work}/{top}.def",
                                f"{work}/{top}.lef", full_lef, pinonly)
            ok, why = site.put_text(tcl, "lef.tcl", host_tmp)
            if not ok:
                return False, f"could not stage lef.tcl into {site.where}: {why}"
            exports = " ".join(
                f"{k}={shlex.quote(v)}"
                for k, v in sorted(magic_env_for(magicrc, pdk_root).items()))
            cmd = (f"cd {shlex.quote(work)} && export {exports} && "
                   f"magic -noconsole -dnull -rcfile {shlex.quote(magicrc)} "
                   f"{shlex.quote(work + '/lef.tcl')}")
            rc, out, err = site.sh(cmd, timeout=timeout_s)
            if rc == _container_exec.TIMEOUT_EXPIRED_RC:
                return False, (f"magic did not complete: the {timeout_s}s "
                               f"deadline expired in {site.where}")
            produced = host_tmp / f"{top}.lef"
            got, why = site.get(f"{top}.lef", produced)
            if not got:
                tail = (err or out or "").strip().splitlines()[-3:]
                return False, (f"magic exited {rc} and wrote no LEF; "
                               f"last output: {' | '.join(tail) or '(none)'}")
            return _accept_lef(produced, out_lef, rc, err or out)
        finally:
            site.close()


def write_lef_with_magic(top: str, gds: Path, def_file: Path, out_lef: Path,
                         pdk_root: str, full_lef: bool, pinonly: bool,
                         timeout_s: int = 900, *, container: str = "",
                         site: Optional["MagicSite"] = None
                         ) -> Tuple[bool, str]:
    """(ok, reason). Never raises; a missing capability is a stated reason.

    `site` is resolved here when the caller has not resolved it already; the
    tool, its technology file and its work directory are then all read on
    that one side. See "WHERE MAGIC ACTUALLY IS" above for why asking THIS
    process's PATH answered a question nobody had asked.
    """
    if site is None:
        site = find_magic_site(container)
    if site is None:
        return False, magic_absent_reason(container)
    magicrc = site.magicrc(pdk_root)
    if magicrc is None:
        cands = site.magicrc_candidates(pdk_root)
        if len(cands) > 1:
            return False, (
                f"PDK_ROOT {pdk_root!r} holds {len(cands)} PDK technologies "
                f"and nothing here says which one this design is on, so no "
                f"magicrc was chosen: {', '.join(cands)}. Pass the PDK "
                f"DIRECTORY itself (the one holding `libs.tech/magic/`). "
                f"Choosing between them would abstract the design against a "
                f"technology that may not define its layers, which yields a "
                f"LEF with an outline and no pins rather than an error.")
        return False, (f"no `libs.tech/magic/*.magicrc` under PDK_ROOT "
                       f"{pdk_root!r} in {site.where}; the PDK's own "
                       f"technology file is the only one this program "
                       f"will use")
    if site.in_container:
        return _write_lef_in_container(site, top, gds, def_file, out_lef,
                                       pdk_root, magicrc, full_lef, pinonly,
                                       timeout_s)
    return _write_lef_here(top, gds, def_file, out_lef, pdk_root, magicrc,
                           full_lef, pinonly, timeout_s)


# ── the run ───────────────────────────────────────────────────────────────

def run(project: Path, pdk_root: str, full_lef: bool, pinonly: bool,
        container: str = "", cell_lef: str = "",
        metal_prefix: str = "met") -> Tuple[int, Record]:
    rec = Record()
    rec.lef_policy = {"writer": "magic:lef write",
                      "abstract": not full_lef,
                      "hide": not full_lef, "pinonly": pinonly,
                      "mirrors": "librelane/scripts/magic/lef.tcl"}

    # 1. identity, from the DEF's own DESIGN statement
    def_path = find_def(project)
    if def_path is None:
        rec.status, rec.reason = "REFUSED", "no DEF under phase3/"
        rec.notes.append(
            "The interface and the design name both come from the DEF. With "
            "no DEF there is no interface to publish and no name to publish "
            "it under; inventing either would be fabrication.")
        return RC_REFUSED, rec
    def_text = def_path.read_text(errors="replace")
    dm = _DEF_DESIGN_RE.search(def_text)
    if not dm:
        rec.status, rec.reason = "REFUSED", f"no `DESIGN <name> ;` in {def_path.name}"
        return RC_REFUSED, rec
    design = dm.group(1)
    rec.design = design

    # 2. the layout
    gds = find_signoff_gds(project)
    if gds is None:
        rec.status, rec.reason = "REFUSED", "no sign-off GDS under phase3/stage4/gds/"
        rec.notes.append("Step 37.5ip's declared input is step 37's GDS.")
        return RC_REFUSED, rec
    geom = _require(_gds_geometry_count, "_gds_geometry_count")(gds.read_bytes())
    if geom <= 0:
        rec.status, rec.reason = "REFUSED", (
            f"{gds.name} carries no geometry record — not a layout")
        return RC_REFUSED, rec

    # 3. the layout must contain the cell the abstracts will name
    tops = _require(gds_top_cells, "gds_top_cells")(gds.read_bytes())
    if design not in tops:
        rec.status, rec.reason = "REFUSED", (
            f"the DEF names design {design!r} and the GDS top cell(s) are "
            f"{tops!r}; the abstract views would name a cell the layout does "
            f"not contain")
        return RC_REFUSED, rec

    # 4. the interface. Top-level DEF PINS commonly omits PG: the rails live
    # in SPECIALNETS because OpenROAD treats them as a grid, not signal ports.
    # That is fine for this die and fatal for a hardmacro delivery unless the
    # rails become physical top-level pins in LEF and pg_pin groups in Liberty.
    pins = read_interface(def_text)
    if not pins:
        rec.status, rec.reason = "REFUSED", (
            f"{def_path.name} declares no PINS entry — a macro with no "
            f"interface cannot be connected to anything")
        return RC_REFUSED, rec
    effective_def_text = def_text
    site: Optional[MagicSite] = None
    pg_source = "DEF PINS"
    present_uses = {p.use for p in pins if p.is_pg}
    if not _PG_USES <= present_uses:
        # The PDK file can live only in the EDA container. Resolve the same
        # boundary Magic will use before reading either the tool or its inputs.
        site = find_magic_site(container)
        rails, rail_source, why = resolve_stdcell_rails(
            site, pdk_root, cell_lef, metal_prefix)
        if not rails:
            rec.status, rec.reason = "REFUSED_NOT_INTEGRABLE", why
            rec.interface = {
                "source": str(def_path),
                "pins": len(pins),
                "signal": [p.name for p in pins if not p.is_pg],
                "power_ground": [p.name for p in pins if p.is_pg],
                "integrable": False,
            }
            rec.notes.append(
                "No hardmacro kit was staged. A macro with no authoritative "
                "power and ground pins is not physically integrable; a "
                "plausible rail name is not a substitute for PDK evidence.")
            return RC_REFUSED, rec
        effective_def_text, pins, why = add_supply_pins_to_def(def_text, rails)
        if effective_def_text is None:
            rec.status, rec.reason = "REFUSED_NOT_INTEGRABLE", why
            rec.interface = {
                "source": str(def_path),
                "pins": len(pins),
                "signal": [p.name for p in pins if not p.is_pg],
                "power_ground": [p.name for p in pins if p.is_pg],
                "pdk_stdcell_lef": rail_source,
                "integrable": False,
            }
            rec.notes.append(
                "No hardmacro kit was staged. The selected PDK supplied rail "
                "names, but the signed-off DEF did not supply matching routed "
                "geometry, so publishing physical pin rectangles would be "
                "fabrication.")
            return RC_REFUSED, rec
        pg_source = rail_source
    rec.interface = {
        "source": str(def_path),
        "pins": len(pins),
        "signal": [p.name for p in pins if not p.is_pg],
        "power_ground": [p.name for p in pins if p.is_pg],
        "power_ground_source": pg_source,
        "power_ground_geometry_source": (
            str(def_path) + "#SPECIALNETS" if pg_source != "DEF PINS"
            else str(def_path) + "#PINS"),
        "integrable": True,
    }

    hm = _pl.phase3_stage4_dir(project) / "hardmacro"
    hm.mkdir(parents=True, exist_ok=True)
    gds_path = hm / f"{design}.gds"
    v_path = hm / f"{design}.v"
    lib_path = hm / f"{design}.lib"
    lef_path = hm / f"{design}.lef"
    expected_pg = {p.name: p.use.upper() for p in pins if p.is_pg}

    def _present(path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0

    def _pg_of(path: Path, reader) -> Optional[Dict[str, str]]:
        """The supply interface an ALREADY-PRESENT view carries.

        `None` means the view is not on disk at all — a distinction the caller
        needs, because "no view" and "a view with no rails" are different
        states. Bytes this producer cannot read report an empty interface: a
        view it cannot parse is not one it may republish as deliverable.
        """
        if not _present(path):
            return None
        try:
            text = path.read_text(errors="replace")
            return {str(p["pin"]): str(p["use"]).upper() for p in reader(text)}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    # A VIEW THIS RUN DID NOT WRITE IS NOT THIS RUN'S OUTPUT TO GRADE.
    #
    # MEASURED 2026-09-02 on `spm x gf180mcuD` and `subservient x gf180mcuD`,
    # both staged before #1991 taught this producer to expose the rails: every
    # view was already on disk, so every write was skipped, and the supply
    # acceptance below was then applied to those untouched bytes. It printed
    #
    #     the staged hardmacro views did not preserve the exact derived
    #     supply interface: expected {'VDD': 'POWER', 'VSS': 'GROUND'};
    #     LEF has {}; Liberty has {}
    #
    # about a file whose mtime the run never changed. Two opposite faults
    # print that one sentence — "magic dropped a port out of the LEF I just
    # wrote" (this producer's bug, #1991's subject) and "I wrote nothing and
    # am describing an older run's kit" (not this producer's output at all) —
    # and a reader cannot tell them apart. The second had no exit either: no
    # re-run healed the tree, only `rm -rf phase3/stage4/hardmacro` did, so
    # every cell published before 2026-09-01 was stuck at step 37.5ip.
    #
    # THE REFUSAL WAS NOT WRONG — a kit with no physical supplies is not
    # deliverable, and that check stays exactly as #1991 landed it. The
    # attribution was wrong. So an already-present view that does not carry
    # the interface THIS run derived is REPLACED rather than graded, and the
    # replacement is a decision this program STATES: a kit is a delivery, and
    # swapping one out from under a consumer in silence is the same fault
    # seen from the other side.
    pre_pg = {lef_path.name: _pg_of(lef_path, lef_pg_pins),
              lib_path.name: _pg_of(lib_path, liberty_pg_pins)}
    present_pre = {n: got for n, got in pre_pg.items() if got is not None}
    if present_pre:
        rec.interface["pre_existing_power_ground"] = present_pre
    stale = sorted(n for n, got in present_pre.items() if got != expected_pg)
    replacing = bool(stale)
    if replacing:
        rec.replaced_reason = (
            "a kit already on disk does not carry the supply interface this "
            f"run derived ({expected_pg}): "
            + "; ".join(f"{n} has {present_pre[n]}" for n in stale)
            + "; those views were written by an earlier run, so they are "
              "re-produced from this run's inputs instead of graded as its "
              "output")
        rec.notes.append("REPLACING AN EXISTING HARDMACRO KIT — "
                         + rec.replaced_reason + ".")

    def write_lef_view() -> Optional[Tuple[int, Record]]:
        """Stage the LEF, or return the run's early exit. `site` is resolved
        here on first need, exactly as before this returned a value."""
        nonlocal site
        if _present(lef_path) and not replacing:
            rec.skipped.append(f"{lef_path.name} (already present)")
            return None
        # THE TOOL IS RESOLVED BEFORE IT IS ASKED FOR ANYTHING, and the record
        # says which environment answered. "magic is not on PATH" was reported
        # by a run whose own provenance already carried a successful magic
        # invocation; naming the site makes the statements comparable.
        if site is None:
            site = find_magic_site(container)
        if site is None:
            ok, why = False, magic_absent_reason(container)
        else:
            rec.lef_policy["magic_site"] = site.where
            ver = site.magic_version()
            if ver:
                rec.lef_policy["magic_version"] = ver
            if effective_def_text == def_text:
                magic_def = def_path
                ok, why = write_lef_with_magic(
                    design, gds, magic_def, lef_path, pdk_root, full_lef,
                    pinonly, container=container, site=site)
            else:
                # A private working copy only. The signed-off routed DEF is an
                # immutable input and is never rewritten to make a delivery.
                with tempfile.TemporaryDirectory(prefix="digital-hm-pg-") as td:
                    magic_def = Path(td) / def_path.name
                    magic_def.write_text(effective_def_text, encoding="utf-8")
                    ok, why = write_lef_with_magic(
                        design, gds, magic_def, lef_path, pdk_root, full_lef,
                        pinonly, container=container, site=site)
        if not ok:
            rec.status, rec.reason = "SKIPPED_NO_CAPABILITY", why
            rec.notes.append(
                "The LEF is written by Magic and by nothing else — this "
                "program contains no LEF writer, on purpose. The kit is "
                "therefore INCOMPLETE, and `digital_hardmacro_check` will "
                "refuse it for the missing view.")
            if replacing:
                rec.notes.append(
                    "NOTHING WAS REPLACED. The stale kit is still on disk "
                    "exactly as it was: no replacement could be written, and "
                    "removing a delivery this run cannot re-produce would "
                    "leave the tree with less than it started with.")
            return RC_NO_CAPABILITY, rec
        if lef_path.name in present_pre:
            rec.replaced.append(lef_path.name)
        rec.produced.append(lef_path.name)
        return None

    def stage(path: Path, write) -> None:
        """Never overwrite a view this run agrees with; always replace one it
        does not. Re-running the flow must not silently displace a sign-off
        artefact — and must not be unable to repair one either."""
        if _present(path):
            if not replacing:
                rec.skipped.append(f"{path.name} (already present)")
                return
            rec.replaced.append(path.name)
        write(path)
        rec.produced.append(path.name)

    def stage_other_views() -> None:
        stage(gds_path, lambda q: shutil.copy(gds, q))
        stage(v_path, lambda q: atomic_write_text(q, emit_verilog(design, pins)))
        stage(lib_path,
              lambda q: atomic_write_text(q, emit_liberty(design, pins)))

    # ORDER IS A DECISION, AND IT DEPENDS ON WHETHER A DELIVERY IS AT RISK.
    #
    # On a tree with no kit (or a kit this run agrees with) the three
    # DEF-derived views are staged FIRST and an unreachable Magic then leaves
    # a deliberately INCOMPLETE kit for `digital_hardmacro_check` to refuse by
    # name — pinned by `test_absent_magicrc_is_a_capability_gap_not_a_failure`
    # and `test_a_path_without_magic_still_refuses_end_to_end`.
    #
    # When an existing kit is being REPLACED there is something to lose, so
    # the LEF goes first: `write_lef_with_magic` copies onto its output only
    # after it has accepted what Magic wrote, so a run that cannot reach Magic
    # leaves the old kit whole instead of three-quarters swapped.
    if replacing:
        early = write_lef_view()
        if early is not None:
            return early
        stage_other_views()
    else:
        stage_other_views()
        early = write_lef_view()
        if early is not None:
            return early

    # Magic may exit zero and still drop an individual DEF port, and catching
    # that is this producer's own narrow acceptance (#1991). It grades ONLY
    # the views this invocation wrote; a stale one cannot reach here, because
    # a stale one was replaced above. The independent gate still owns
    # identity, extent, registration, complete interface, pin geometry,
    # obstruction policy, and the timing tier.
    graded: Dict[str, Dict[str, str]] = {}
    for path, reader, key in (
            (lef_path, lef_pg_pins, "staged_lef_power_ground"),
            (lib_path, liberty_pg_pins, "staged_liberty_power_ground")):
        if path.name not in rec.produced:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:  # the gate will also reject the view
            rec.status, rec.reason = "REFUSED_NOT_INTEGRABLE", (
                f"could not re-read the supply interface this run wrote into "
                f"{path.name}: {exc}")
            rec.interface["integrable"] = False
            return RC_REFUSED, rec
        got = {str(p["pin"]): str(p["use"]).upper() for p in reader(text)}
        rec.interface[key] = got
        graded[path.name] = got
    bad = {n: got for n, got in graded.items() if got != expected_pg}
    if bad:
        rec.status, rec.reason = "REFUSED_NOT_INTEGRABLE", (
            "the hardmacro views THIS RUN WROTE did not preserve the exact "
            f"derived supply interface: expected {expected_pg}; "
            + "; ".join(f"{n} has {got}" for n, got in sorted(bad.items())))
        rec.interface["integrable"] = False
        rec.notes.append(
            "The four-view files remain evidence for the independent gate, "
            "but this producer does not label the kit deliverable: a tool "
            "success that drops either physical supply pin is not integration.")
        return RC_REFUSED, rec
    if not rec.produced:
        rec.notes.append(
            "NOTHING WAS WRITTEN. Every view was already on disk and already "
            "carried this run's derived supply interface, so the kit was left "
            "as it stands; this run graded none of it.")
    return RC_OK, rec


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=PROGRAM, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="write the JSON record here")
    ap.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", ""),
                    help="PDK_ROOT; the PDK's own magicrc is located under it")
    ap.add_argument("--cell-lef", default="",
                    help="the selected PDK std-cell LEF whose routing-metal "
                         "USE POWER/GROUND pins name the hardmacro rails")
    ap.add_argument("--metal-prefix", default="met",
                    help="selected PDK routing-layer stem used to distinguish "
                         "primary rails from well/substrate PG pins")
    ap.add_argument("--container", default=DEFAULT_CONTAINER,
                    help="the EDA container to reach magic and the PDK in "
                         "when neither is in THIS environment; 'host' or "
                         "empty confines the search to this one")
    ap.add_argument("--full-lef", action="store_true",
                    help="upstream MAGIC_WRITE_FULL_LEF: every internal shape "
                         "instead of an abstracted view")
    ap.add_argument("--pinonly", action="store_true",
                    help="upstream MAGIC_WRITE_LEF_PINONLY: only port-labelled "
                         "areas are pins; the rest of each net on that layer "
                         "becomes an obstruction")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return RC_NO_CAPABILITY

    try:
        rc, rec = run(args.project_dir, args.pdk_root, args.full_lef,
                      args.pinonly, args.container, args.cell_lef,
                      args.metal_prefix)
    except RuntimeError as exc:
        rc, rec = RC_NO_CAPABILITY, Record(status="ERROR", reason=str(exc))

    # THE RECORD IS WRITTEN ON EVERY PATH, INCLUDING EVERY REFUSAL. Upstream's
    # own refusals exit 1 with a printed message and no machine-readable
    # record; this is the one place this producer is deliberately better.
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(asdict(rec), indent=2,
                                          ensure_ascii=False) + "\n")

    print(f"[{rec.status}] {PROGRAM}"
          + (f" — {rec.reason}" if rec.reason else "")
          + (f"; produced {', '.join(rec.produced)}" if rec.produced else "")
          + (f"; REPLACED {', '.join(rec.replaced)}" if rec.replaced else ""),
          file=sys.stderr if rc else sys.stdout)
    for n in rec.notes:
        print(f"  {n}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
