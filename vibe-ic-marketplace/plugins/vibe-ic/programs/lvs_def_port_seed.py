"""v0.1.114 — DEF-pin port-seed generator for top-level netgen LVS pin matching.

What this is (Route B — tool-independent fallback)
===================================================

A deterministic, chip-AGNOSTIC parser that reads ANY OpenROAD/LEF-DEF
`PINS` section and emits the two artifacts needed to seed top-level pin
matching in a device-level netgen LVS run when the Magic GDS flat
extraction emits a `.subckt <top>` with an EMPTY port list:

  1. an ordered top-level port list (so the extracted layout SPICE
     `.subckt <top>` line can be rewritten to carry the SAME named ports
     as the schematic-side Verilog), and
  2. a netgen port-seed TCL fragment (`property` / `equate` directives)
     that an audit can source after the foundry setup.

Why this exists
===============

The HDLC pilot (benchmark_phase1/hdlc/RESULT_e2e_pilot.md § 8.1) reached
device-class-exact + device-count-exact device-level LVS (16393 = 16393,
all classes equivalent, 0 disconnected nodes) but `Final result: Top
level cell failed pin matching` — because the Magic flat extraction's
`.subckt hdlc_core` has NO ports, so netgen's name-matching partition has
nothing to anchor (flat 13725 layout nets vs 8507 schematic nets).

Route A (canonical) is a Magic `port makeall` extraction — but that only
promotes labels that sit on a *pin/label-purpose* layer; an OpenROAD
GDS-streamout step that placed the pin text on a *drawing* layer (sky130 met3
drawing = layer/datatype 10/1) yields nothing for `port makeall`, so the
top `.subckt` stays portless even with the env(PDK) fix applied. This
Route B program recovers the ports from the DEF — the authoritative,
always-present source of the top-level pin set — independent of Magic.

Why a PROGRAM, not a SKILL
==========================

The DEF `PINS` grammar is fixed (LEF/DEF 5.8). Parsing
`- <pin> + NET <net> ... + DIRECTION <dir>` and re-emitting an ordered
port list / netgen seed is fully deterministic — no LLM judgment. Per the
closed-loop-enhancement-capture-doctrine this is a Bucket-A program.

Reference
=========

  - LEF/DEF Language Reference 5.8, § PINS.
  - netgen tutorial 2: Interpreting LVS Results.
  - benchmark_phase1/hdlc/RESULT_e2e_pilot.md § 8.1.

Unit-tested in `programs/tests/test_lvs_def_port_seed.py`.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DefPin:
    """One top-level pin parsed from a DEF PINS section.

    `name`      — the pin name as it appears after `- ` (e.g. `tx_wdata[3]`).
    `net`       — the net the pin connects to (`+ NET <net>`); defaults to
                  `name` when the DEF omits it (rare but legal).
    `direction` — INPUT / OUTPUT / INOUT / FEEDTHRU, upper-cased; "" if absent.
    """
    name: str
    net: str
    direction: str


# A PINS entry starts with `- <pinName>` and continues (possibly across many
# physical lines) until the terminating `;`. We normalise whitespace and split
# on `;` so a single regex can scan each logical entry. The `+ NET` and
# `+ DIRECTION` tokens may appear in any order, so they are matched separately.
_PIN_START_RE = re.compile(r"-\s+(\S+)")
_NET_RE = re.compile(r"\+\s*NET\s+(\S+)")
_DIR_RE = re.compile(r"\+\s*DIRECTION\s+(\S+)")


def _extract_pins_block(def_text: str) -> str:
    """Return the text between `PINS <n> ;` and `END PINS` (exclusive).

    Returns "" if there is no PINS section. Robust to leading whitespace and
    to the count token on the PINS header line.
    """
    # `PINS <count> ;` — count is optional in some writers, so make it lax.
    m = re.search(r"(?m)^\s*PINS\b[^\n;]*;", def_text)
    if not m:
        return ""
    start = m.end()
    end_m = re.search(r"(?m)^\s*END\s+PINS\b", def_text[start:])
    if not end_m:
        # Unterminated PINS — take to EOF rather than crash.
        return def_text[start:]
    return def_text[start:start + end_m.start()]


def parse_def_pins(def_text: str) -> List[DefPin]:
    """Parse a DEF's PINS section into an ordered list of DefPin.

    Order is preserved exactly as the DEF lists them (DEF PINS order is the
    canonical top-level port order a writer like OpenROAD emits). Each logical
    entry begins at a `- <pin>` token and ends at the next `;`.

    Chip-agnostic: never special-cases any pin name. Bus bits such as
    `tx_wdata[3]` are kept verbatim (netgen treats each as its own port).
    """
    block = _extract_pins_block(def_text)
    if not block:
        return []

    pins: List[DefPin] = []
    # Split into logical entries on `;`. Each entry should contain exactly one
    # `- <pin>` start token; entries with none (blank/whitespace) are skipped.
    for raw_entry in block.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        # The pin name is the token right after the FIRST `- `.
        start_m = _PIN_START_RE.search(entry)
        if not start_m:
            continue
        name = start_m.group(1)
        net_m = _NET_RE.search(entry)
        dir_m = _DIR_RE.search(entry)
        net = net_m.group(1) if net_m else name
        direction = dir_m.group(1).upper() if dir_m else ""
        pins.append(DefPin(name=name, net=net, direction=direction))
    return pins


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------
def build_ordered_port_list(pins: List[DefPin]) -> List[str]:
    """Return the ordered list of pin NAMES, deduped (preserving first order).

    These are the tokens to append to a portless `.subckt <top>` line in the
    extracted layout SPICE so the layout carries the same named top ports as
    the schematic.
    """
    return list(dict.fromkeys(p.name for p in pins))


def build_subckt_line(top_cell: str, pins: List[DefPin]) -> str:
    """Return a port-labeled `.subckt <top> <p1> <p2> ...` line.

    SPICE node names cannot contain `[`/`]`; Magic/ngspice convention maps a
    DEF bus bit `tx_wdata[3]` to `tx_wdata.3` in the extracted netlist, but the
    SAFE general default for SEEDING is to keep the DEF spelling verbatim so the
    caller can choose the mapping. We keep verbatim here and expose
    `subckt_line_spice_safe` for the bracket-normalised variant.
    """
    ports = build_ordered_port_list(pins)
    return ".subckt {} {}".format(top_cell, " ".join(ports)) if ports else f".subckt {top_cell}"


def _spice_safe(name: str) -> str:
    """Map DEF bus-bit `a[3]` -> `a.3` (Magic ext2spice / ngspice convention)."""
    return name.replace("[", ".").replace("]", "")


def build_subckt_line_spice_safe(top_cell: str, pins: List[DefPin]) -> str:
    """Return a `.subckt` line with bus-bit brackets normalised to dots.

    Use this variant when injecting into a Magic-extracted SPICE whose internal
    node names already use the `.` bus convention.
    """
    ports = [_spice_safe(p) for p in build_ordered_port_list(pins)]
    return ".subckt {} {}".format(top_cell, " ".join(ports)) if ports else f".subckt {top_cell}"


def build_netgen_seed_tcl(top_cell: str, pins: List[DefPin],
                          spice_safe: bool = True) -> str:
    """Generate a netgen port-seed TCL fragment.

    Emits, for the named top circuit, a `property` annotation declaring the
    ordered port list plus per-pin `equate pins` hints keyed by name so that
    once BOTH circuits carry the same named ports netgen can anchor its
    partition. This fragment is sourced AFTER the foundry `<pdk>_setup.tcl`
    and the `lvs` circuit declarations.

    When `pins` is empty, emits a clear SKIPPED diagnostic.
    """
    norm = _spice_safe if spice_safe else (lambda s: s)
    ports = [norm(n) for n in build_ordered_port_list(pins)]

    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        "# Vibe-IC plugin — DEF-pin port-seed for top-level netgen LVS\n"
        "# Route B (tool-independent): recovers the top-level port set from\n"
        "# the DEF PINS section so a portless Magic-extracted .subckt can be\n"
        "# anchored for name-matching. Generated by\n"
        "# programs/lvs_def_port_seed.py\n"
        "# Reference: benchmark_phase1/hdlc/RESULT_e2e_pilot.md § 8.1\n"
        "#---------------------------------------------------------------"
    )

    if not ports:
        out.append(
            f"puts stdout \"LVS_PORT_SEED_SKIPPED: no PINS parsed for "
            f"'{top_cell}'; top-level pin matching cannot be seeded.\""
        )
        return "\n".join(out) + "\n"

    out.append("")
    out.append(
        f"# {len(ports)} top-level port(s) recovered from DEF PINS, in DEF order.\n"
        f"# Inject these into the layout .subckt {top_cell} line (see the\n"
        f"# companion ordered port list / --emit-subckt-line) so BOTH netgen\n"
        f"# circuits carry identical named ports before `lvs`."
    )
    out.append(f"set vibeic_top_ports_{_tcl_ident(top_cell)} [list \\")
    for i, p in enumerate(ports):
        sep = " \\" if i < len(ports) - 1 else ""
        out.append(f"    {p}{sep}")
    out.append("]")

    out.append("")
    out.append(
        "# Per-pin equate hints. `equate pins` is a no-op unless BOTH circuits\n"
        "# expose the port; it is harmless to declare and anchors matching\n"
        "# the moment the layout .subckt is re-emitted with ports."
    )
    for p in ports:
        out.append(f"equate pins \"{top_cell} {p}\" \"{top_cell} {p}\"")

    return "\n".join(out) + "\n"


def _tcl_ident(s: str) -> str:
    """Make a TCL-variable-safe identifier from a cell name."""
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def inject_ports_into_subckt(spice_text: str, top_cell: str,
                             pins: List[DefPin],
                             spice_safe: bool = True) -> str:
    """Rewrite a portless `.subckt <top_cell>` line to carry DEF-derived ports.

    Finds the line `.subckt <top_cell>` (with no trailing ports) and replaces
    it with the port-labeled version. If the `.subckt` line already has ports,
    it is left UNCHANGED (idempotent / never clobbers a real port list). If the
    top cell is not found, the text is returned unchanged (caller checks).

    GENERAL: matches any top cell name; no HDLC special-casing.
    """
    line = (build_subckt_line_spice_safe(top_cell, pins) if spice_safe
            else build_subckt_line(top_cell, pins))
    # Match a `.subckt <top>` that has NOTHING (or only whitespace) after the
    # cell name on that line.
    pat = re.compile(
        r"(?m)^\.subckt\s+" + re.escape(top_cell) + r"\s*$"
    )
    if not pat.search(spice_text):
        return spice_text  # already has ports, or top not present
    return pat.sub(line, spice_text, count=1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    import sys

    p = argparse.ArgumentParser(
        description="Seed top-level netgen LVS pin matching from a DEF PINS "
                    "section (deterministic, chip-agnostic).",
    )
    p.add_argument("--def-file", required=True, type=Path,
                   help="OpenROAD/LEF-DEF file with a PINS section")
    p.add_argument("--top-cell", required=True,
                   help="Top cell name for the emitted .subckt / seed TCL")
    p.add_argument("--emit", choices=["seed-tcl", "port-list", "subckt-line"],
                   default="seed-tcl",
                   help="What to emit: netgen seed TCL (default), the ordered "
                        "port list (one per line), or the .subckt line")
    p.add_argument("--no-spice-safe", action="store_true",
                   help="Keep DEF bus brackets verbatim (default maps a[3]->a.3)")
    p.add_argument("--inject-into", type=Path, default=None,
                   help="Path to an extracted SPICE; rewrite its portless "
                        ".subckt <top> line in place and print the result")
    p.add_argument("--out", type=Path, default=None,
                   help="Output path. Defaults to stdout.")
    args = p.parse_args()

    if not args.def_file.exists():
        print(f"ERROR: DEF not found: {args.def_file}", file=sys.stderr)
        return 2
    def_text = args.def_file.read_text(encoding="utf-8", errors="replace")
    pins = parse_def_pins(def_text)
    spice_safe = not args.no_spice_safe

    if args.inject_into is not None:
        if not args.inject_into.exists():
            print(f"ERROR: SPICE not found: {args.inject_into}", file=sys.stderr)
            return 2
        spice = args.inject_into.read_text(encoding="utf-8", errors="replace")
        result = inject_ports_into_subckt(spice, args.top_cell, pins,
                                          spice_safe=spice_safe)
        changed = result != spice
        text = result
        status = "rewrote" if changed else "no-op (ports present or top absent)"
        nports = len(build_ordered_port_list(pins))
        print(f"inject: {status} .subckt {args.top_cell} ({nports} ports)",
              file=sys.stderr)
    elif args.emit == "seed-tcl":
        text = build_netgen_seed_tcl(args.top_cell, pins, spice_safe=spice_safe)
    elif args.emit == "port-list":
        names = ([_spice_safe(n) for n in build_ordered_port_list(pins)]
                 if spice_safe else build_ordered_port_list(pins))
        text = "\n".join(names) + ("\n" if names else "")
    else:  # subckt-line
        text = ((build_subckt_line_spice_safe(args.top_cell, pins)
                 if spice_safe else build_subckt_line(args.top_cell, pins)) + "\n")

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote: {args.out}", file=sys.stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
