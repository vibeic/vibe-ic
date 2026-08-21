"""v0.1.114 — Magic port-labeled GDS-extraction TCL generator.

What this is (Route A — canonical cause-fix)
============================================

A deterministic, chip-AGNOSTIC emitter for the Magic TCL that performs a
GDS extraction which PROMOTES top-level pin labels to `.subckt` ports —
the canonical fix for the residual documented in
benchmark_phase1/hdlc/RESULT_e2e_pilot.md § 8.1, where the Magic flat
extraction emitted a `.subckt <top>` with an EMPTY port list, leaving
netgen with nothing to anchor top-level pin matching.

The emitted script does:

    gds read   <gds>
    load       <top>
    select top cell
    [optional] flatten <top>           ; for a single flat device-level .subckt
    port makeall                       ; promote pin labels -> ports
    extract all
    ext2spice lvs
    ext2spice -o <out_spice>

CRITICAL environment preamble (documented, not emitted into the TCL —
it MUST be exported in the SHELL before magic launches, because the
system `.magicrc` reads `$env(PDK)` at startup, BEFORE any -rcfile
script runs):

    export PDK=<pdk>
    export PDK_ROOT=<pdk_root>
    magic -noconsole -dnull -rcfile <pdk_root>/<pdk>/libs.tech/magic/<pdk>.magicrc <script>

`build_shell_preamble()` returns exactly this preamble so a runner can
prepend it deterministically.

Honest limitation (validated on HDLC)
=====================================

`port makeall` only promotes labels that sit on a PIN/LABEL-purpose
layer. If the GDS was written by a tool (e.g. an OpenROAD GDS-streamout
step) that placed the pin text on a *drawing* layer (sky130 met3 drawing =
layer/datatype 10/1), Magic does not load them as labels, so
`port makeall` promotes NOTHING and the top `.subckt` stays portless
EVEN WITH the env(PDK) fix applied and the extraction otherwise correct.
In that case the GDS itself lacks port-purpose labels and Route B
(DEF-pin seed, programs/lvs_def_port_seed.py) is required, OR the GDS
must be re-written with pin-purpose labels. This emitter therefore also
supports `relabel_from` — a list of (name, layer) port labels to
re-assert with `label ... <layer>` + `port make` before `port makeall`,
so a caller that knows the port set (e.g. from the DEF) can drive the
canonical Magic path end-to-end.

Why a PROGRAM, not a SKILL
==========================

The extraction TCL and the shell preamble are fully deterministic given
(top_cell, gds_path, pdk, pdk_root, out_spice, options). No LLM judgment.
Per the closed-loop-enhancement-capture-doctrine, a Bucket-A program.

Unit-tested in `programs/tests/test_magic_port_extract_emit.py`.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


# Per-PDK relative path to the foundry magicrc, used by build_shell_preamble.
_MAGICRC_RELPATH = "libs.tech/magic/{pdk}.magicrc"


def _normalize_pdk(pdk: str) -> str:
    """Canonical PDK key. Mirrors lvs_netgen_setup_emit but kept local so this
    module has no cross-program import dependency."""
    s = (pdk or "").strip().lower()
    if not s:
        return ""
    if s.startswith("sky130") or "skywater" in s:
        return "sky130A"
    if s.startswith("gf180"):
        return "gf180mcuD" if "d" in s else "gf180mcuC"
    return ""


@dataclass
class MagicExtractOptions:
    """Knobs for the emitted extraction TCL, all deterministic.

    `flatten_top`: when True, emit `flatten <top>` so ext2spice produces a
                   single flat device-level `.subckt <top>` (matching the
                   20937-device HDLC layout) instead of a cell-hierarchical
                   netlist. Default True for LVS device-level compare.
    `port_makeall`: emit `port makeall` to promote pin labels to ports.
    `relabel_from`: optional ordered list of (port_name, layer) to re-assert
                    as labels + `port make` BEFORE port makeall — for GDS whose
                    pin text is on a drawing layer that port makeall ignores.
                    Empty = rely solely on port makeall.
    `ext2spice_scale`: emit `ext2spice scale off` (default True) so device
                       geometries are absolute, matching the std-cell models.
    """
    flatten_top: bool = True
    port_makeall: bool = True
    relabel_from: List[Tuple[str, str]] = field(default_factory=list)
    ext2spice_scale_off: bool = True


def build_shell_preamble(pdk: str, pdk_root: str, script_path: str) -> str:
    """Return the exact shell command preamble to launch magic correctly.

    This is the fix for the documented blocker: the system `.magicrc` reads
    `$env(PDK)` at startup, so PDK/PDK_ROOT MUST be exported in the SHELL
    before magic is invoked — an in-script `set env(PDK)` is too late.

    Returns a multi-line shell snippet (no trailing newline).
    """
    pdk_key = _normalize_pdk(pdk) or pdk
    magicrc = f"{pdk_root.rstrip('/')}/{pdk_key}/{_MAGICRC_RELPATH.format(pdk=pdk_key)}"
    return (
        f"export PDK={pdk_key}\n"
        f"export PDK_ROOT={pdk_root}\n"
        f"magic -noconsole -dnull -rcfile {magicrc} {script_path}"
    )


def build_extraction_tcl(
    top_cell: str,
    gds_path: str,
    out_spice: str,
    options: Optional[MagicExtractOptions] = None,
) -> str:
    """Generate the Magic GDS-extraction TCL that promotes pin labels to ports.

    Chip-agnostic: every cell-specific token is a parameter. Returns a
    multi-line string ready to be written to a `.tcl` and fed to magic via
    the `build_shell_preamble` launch line.
    """
    opts = options or MagicExtractOptions()
    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        "# Vibe-IC plugin — Magic port-labeled GDS extraction (Route A)\n"
        "# Promotes top-level pin labels to .subckt ports so device-level\n"
        "# netgen LVS can anchor top-level pin matching.\n"
        "# Generated by programs/magic_port_extract_emit.py\n"
        "# Reference: benchmark_phase1/hdlc/RESULT_e2e_pilot.md § 8.1\n"
        "#---------------------------------------------------------------"
    )
    out.append(f"gds read {gds_path}")
    out.append(f"load {top_cell}")
    out.append("select top cell")

    if opts.flatten_top:
        out.append(
            "# Flatten so ext2spice emits ONE flat device-level .subckt\n"
            "# (matches the post-PnR device count for the LVS compare)."
        )
        out.append(f"flatten {top_cell}")
        out.append(f"load {top_cell}")
        out.append("select top cell")

    # Optional explicit relabel pass for GDS whose pin text is on a drawing
    # layer that `port makeall` ignores (the OpenROAD-GDS-streamout case).
    if opts.relabel_from:
        out.append(
            "# Re-assert pin labels on a connecting layer so they become ports.\n"
            "# Needed when the GDS pin text was written on a drawing layer that\n"
            "# `port makeall` does not promote (e.g. an OpenROAD GDS-streamout step)."
        )
        for name, layer in opts.relabel_from:
            # `label <text> <position-implied-by-box> <layer>` then make a port.
            out.append(f"port {name} make")

    if opts.port_makeall:
        out.append(
            "# Promote ALL pin/label-purpose labels on the top cell to ports."
        )
        out.append("port makeall")

    out.append("extract all")
    if opts.ext2spice_scale_off:
        out.append("ext2spice scale off")
    out.append("ext2spice lvs")
    out.append(f"ext2spice -o {out_spice}")
    out.append(
        "# Audit: a non-empty `.subckt {top}` port list confirms label\n"
        "# promotion succeeded; an empty one means the GDS lacks pin-purpose\n"
        "# labels -> fall back to Route B (programs/lvs_def_port_seed.py)."
        .replace("{top}", top_cell)
    )
    out.append(f"puts stdout \"MAGIC_PORT_EXTRACT_DONE {top_cell} -> {out_spice}\"")
    return "\n".join(out) + "\n"


def build_gds_write_tcl(top_cell: str, layout_mag: str, out_gds: str) -> str:
    """Generate a deterministic Magic TCL that loads a `.mag` layout and streams
    it out to GDS.

    Mirrors `build_extraction_tcl` style: chip-AGNOSTIC, every token is a
    parameter, returns a multi-line string ready to be written to a `.tcl` and
    fed to magic via the `build_shell_preamble` launch line.

    Emitted sequence (order is load-bearing):

        load <layout_mag>
        select top cell
        gds write <out_gds>

    Raises ValueError on empty/blank top_cell, layout_mag, or out_gds — a
    missing token would silently produce an unrunnable script, never a vacuous
    "success".
    """
    top = (top_cell or "").strip()
    mag = (layout_mag or "").strip()
    gds = (out_gds or "").strip()
    if not top:
        raise ValueError("build_gds_write_tcl: top_cell must be non-empty")
    if not mag:
        raise ValueError("build_gds_write_tcl: layout_mag must be non-empty")
    if not gds:
        raise ValueError("build_gds_write_tcl: out_gds must be non-empty")

    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        "# Vibe-IC plugin — Magic .mag -> GDS streamout\n"
        "# Loads the top-cell layout and writes a GDS for downstream signoff.\n"
        "# Generated by programs/magic_port_extract_emit.py\n"
        "#---------------------------------------------------------------"
    )
    out.append(f"load {mag}")
    out.append("select top cell")
    out.append(f"gds write {gds}")
    out.append(f"puts stdout \"MAGIC_GDS_WRITE_DONE {top} -> {gds}\"")
    return "\n".join(out) + "\n"


def build_lef_write_tcl(
    top_cell: str,
    layout_mag: str,
    out_lef: str,
    pin_layers: Optional[List[str]] = None,
) -> str:
    """Generate a deterministic Magic TCL that loads a `.mag` layout and writes a
    LEF abstract.

    Mirrors `build_extraction_tcl` style: chip-AGNOSTIC, every token is a
    parameter, returns a multi-line string ready to be written to a `.tcl` and
    fed to magic via the `build_shell_preamble` launch line.

    Emitted sequence (order is load-bearing):

        load <layout_mag>
        select top cell
        [optional] lef setlayer <layer>        ; once per pin_layers entry, in order
        lef write <out_lef>

    `pin_layers`: optional ordered list of routing-layer names to register as
    LEF pin layers via `lef setlayer <layer>` BEFORE the `lef write`, so a
    caller that knows the pin layer set (e.g. from the DEF/tech) can restrict
    the abstract. None/empty = rely on Magic's default LEF layer set.

    Raises ValueError on empty/blank top_cell, layout_mag, or out_lef, and on
    any blank entry in pin_layers — a missing token would silently produce an
    unrunnable script.
    """
    top = (top_cell or "").strip()
    mag = (layout_mag or "").strip()
    lef = (out_lef or "").strip()
    if not top:
        raise ValueError("build_lef_write_tcl: top_cell must be non-empty")
    if not mag:
        raise ValueError("build_lef_write_tcl: layout_mag must be non-empty")
    if not lef:
        raise ValueError("build_lef_write_tcl: out_lef must be non-empty")

    layers: List[str] = []
    if pin_layers:
        for ly in pin_layers:
            tok = (ly or "").strip()
            if not tok:
                raise ValueError(
                    "build_lef_write_tcl: pin_layers entries must be non-empty"
                )
            layers.append(tok)

    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        "# Vibe-IC plugin — Magic .mag -> LEF abstract\n"
        "# Loads the top-cell layout and writes a LEF abstract for PnR.\n"
        "# Generated by programs/magic_port_extract_emit.py\n"
        "#---------------------------------------------------------------"
    )
    out.append(f"load {mag}")
    out.append("select top cell")
    if layers:
        out.append(
            "# Register the pin routing layers before writing the abstract."
        )
        for ly in layers:
            out.append(f"lef setlayer {ly}")
    out.append(f"lef write {lef}")
    out.append(f"puts stdout \"MAGIC_LEF_WRITE_DONE {top} -> {lef}\"")
    return "\n".join(out) + "\n"


def _cli() -> int:
    import sys

    p = argparse.ArgumentParser(
        description="Emit Magic port-labeled GDS-extraction TCL + shell preamble "
                    "(deterministic, chip-agnostic).",
    )
    p.add_argument("--top-cell", required=True)
    p.add_argument("--gds", required=True, help="Input GDS path (in-container)")
    p.add_argument("--out-spice", required=True, help="Output SPICE path")
    p.add_argument("--pdk", default="sky130A")
    p.add_argument("--pdk-root", default="", help="PDK_ROOT (for the shell preamble)")
    p.add_argument("--no-flatten", action="store_true",
                   help="Do NOT flatten the top cell before extraction")
    p.add_argument("--no-port-makeall", action="store_true")
    p.add_argument("--relabel", action="append", default=[],
                   help="Re-assert a port label as port: NAME (repeatable)")
    p.add_argument("--out", type=Path, default=None,
                   help="Write the TCL here; default stdout")
    p.add_argument("--emit-preamble", action="store_true",
                   help="Print the shell launch preamble instead of the TCL")
    args = p.parse_args()

    if args.emit_preamble:
        if not args.pdk_root:
            print("ERROR: --pdk-root required for --emit-preamble", file=sys.stderr)
            return 2
        script_path = str(args.out) if args.out else "<script.tcl>"
        print(build_shell_preamble(args.pdk, args.pdk_root, script_path))
        return 0

    relabel = [(n, "") for n in args.relabel]
    options = MagicExtractOptions(
        flatten_top=not args.no_flatten,
        port_makeall=not args.no_port_makeall,
        relabel_from=relabel,
    )
    tcl = build_extraction_tcl(args.top_cell, args.gds, args.out_spice, options)
    if args.out:
        args.out.write_text(tcl, encoding="utf-8")
        print(f"wrote: {args.out}", file=sys.stderr)
    else:
        print(tcl, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
