"""v0.1.49 — Netgen supplementary LVS setup-file generator.

What this is
============

A deterministic emitter for the Netgen TCL fragment that gets sourced
AFTER the foundry-provided `<pdk>_setup.tcl` and BEFORE `lvs <c1> <c2>`,
to close the open-source-SkyWater-style net-level LVS gap documented
in the spm pilot `RESULT_tier4_5_lvs_attempts.md` and validated by
external review.

Why a PROGRAM, not a SKILL
==========================

The Netgen-side gap closure rules are deterministic:

  1. Power-net globalisation — `global vccd1 vssd1` etc. — is a fixed
     list per PDK. Magic's `ext2spice` does NOT mark power as `.global`,
     so Netgen sees a separate VPWR-per-instance flat net; the standard
     remediation is a `global` declaration per power name.

  2. Stdcell-library `<lib>__<cell>` ↔ `<cell>` equate is already in
     the foundry setup (e.g. `sky130A_setup.tcl`), so we MUST NOT
     duplicate it — but we DO want to surface that we relied on it.

  3. Symmetric-MOS source-drain `permute default` is in the foundry
     setup too.

  4. Optional `flatten class` directives — used when the layout vs
     schematic differ in stdcell-hierarchy granularity (e.g. yosys
     flatten vs ext2spice subckt). Off by default; opt-in.

  5. Conditional `ignore class` for tap / fill / decap — already in
     the foundry setup, gated by `MAGIC_EXT_USE_GDS=1`. We surface
     a comment so an audit can see we're aware.

All five rules are deterministic. A skill (LLM authoring) is not
needed; the user supplies (PDK, list of power nets, options), and
the program emits the fragment. This follows the
[[closed-loop-enhancement-capture-doctrine]]: deterministic rule → Bucket A program.

Reference
=========

  - Foundry setup: `<PDK>/libs.tech/netgen/<pdk>_setup.tcl`
  - Netgen tutorial 2: Interpreting LVS Results
  - spm pilot empirical evidence:
      `RESULT_tier4_5_lvs_attempts.md` (4 prior open-source attempts)
      `PHASE_C_CLEANUP_RESULT.md` § Tier 4.5 LVS net-level gap

Unit-tested in `programs/tests/test_lvs_netgen_setup_emit.py`.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Per-PDK power-net default lists. These are the names Magic's `ext2spice`
# emits as ordinary nets (which Netgen then sees as separate per-instance
# nets unless they are declared `global`). Magic itself does support a
# `.global` directive on ext2spice when MAGIC_GLOBAL is set, but the
# default open-source flow doesn't.
# ---------------------------------------------------------------------------
PDK_POWER_NETS: Dict[str, List[str]] = {
    # SKY130A (Open Process Design Kit, SkyWater 130nm).
    # vccd1/vssd1: chipignite user-area 1.8V digital domain.
    # vccd2/vssd2: chipignite user-area 1.8V digital domain (2nd).
    # vdda1/2, vssa1/2: user-area 3.3V analog domains.
    # vddio/vssio: I/O ring 3.3V.
    # VPWR/VGND/VPB/VNB: per-cell std-cell PG pins (Liberty convention).
    "sky130A": [
        "vccd1", "vssd1", "vccd2", "vssd2",
        "vdda1", "vssa1", "vdda2", "vssa2",
        "vddio", "vssio",
        "VPWR", "VGND", "VPB", "VNB",
    ],
    # GF180 — single-domain VDD/VSS plus per-cell PG.
    "gf180mcuC": ["VDD", "VSS", "VPWR", "VGND"],
    "gf180mcuD": ["VDD", "VSS", "VPWR", "VGND"],
}


# ---------------------------------------------------------------------------
# Per-PDK std-cell library name -> regex used by foundry setup to detect
# tap/fill/decap. Reused here to emit an audit comment so a reader knows
# which cells were considered for `ignore class` waiving by the foundry
# setup (we don't emit those rules — the foundry setup already does, gated
# on MAGIC_EXT_USE_GDS=1).
# ---------------------------------------------------------------------------
PDK_STDCELL_PG_HINT: Dict[str, str] = {
    "sky130A": "sky130_fd_sc_*",
    "gf180mcuC": "gf180mcu_fd_sc_mcu*",
    "gf180mcuD": "gf180mcu_fd_sc_mcu*",
}


@dataclass
class LvsSetupOptions:
    """Knobs that change what's emitted, all deterministic.

    `extra_power_nets`: project-specific power names (e.g. an analog block's
                       private VBN_REF) added on top of the PDK defaults.
    `flatten_top_circuits`: pair of top circuit names to `flatten class`
                           BEFORE the lvs comparison. Use when layout
                           is hierarchy-flat (yosys+flatten) but schematic
                           is hierarchy-preserved (Magic ext2spice).
                           Empty list = no flatten directives emitted.
    `equate_stdcell_lib_to_short_name`: True (default) trusts the foundry
                           setup's wildcard `<lib>__<cell>` → `<cell>`
                           equate (no-op emit, just a comment). False
                           emits an explicit equate (rarely needed).
    `audit_comments`: include `puts stdout` lines that announce each
                     supplementary rule is being applied — invaluable
                     during a debug session, off by default for a clean
                     production batch run.
    """
    extra_power_nets: List[str] = field(default_factory=list)
    flatten_top_circuits: Tuple[str, str] = ("", "")
    equate_stdcell_lib_to_short_name: bool = True
    audit_comments: bool = False


def _normalize_pdk(pdk: str) -> str:
    """Return a canonical PDK key (sky130A / gf180mcuC / gf180mcuD).

    Accepts the loose names a user might type: "sky130", "sky130a", "SkyWater",
    "gf180", "gf180mcu". Defaults to sky130A if the input is sky130-like.
    Unknown PDKs return "" — the caller emits a SKIPPED diagnostic.
    """
    s = (pdk or "").strip().lower()
    if not s:
        return ""
    if s.startswith("sky130") or "skywater" in s:
        return "sky130A"
    if s.startswith("gf180"):
        if "d" in s:
            return "gf180mcuD"
        return "gf180mcuC"
    return ""


def build_supplementary_setup_tcl(
    pdk: str,
    options: Optional[LvsSetupOptions] = None,
) -> str:
    """Generate the supplementary Netgen LVS setup TCL fragment.

    Returns a multi-line string ready to be written next to (or after)
    the foundry `<pdk>_setup.tcl`. When `pdk` is unrecognised, returns
    a minimal SKIPPED-style fragment with a clear `puts stdout` so the
    audit trail records that no PDK-specific globalisation was applied.
    """
    opts = options or LvsSetupOptions()
    pdk_key = _normalize_pdk(pdk)

    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        "# Vibe-IC plugin v0.1.49 — supplementary Netgen LVS setup\n"
        "# Closes the open-source SkyWater-style net-level gap by\n"
        "# globalising power nets and (optionally) flattening top\n"
        "# circuits to match the layout vs schematic hierarchy.\n"
        "# Generated by programs/lvs_netgen_setup_emit.py\n"
        "# Reference: spm pilot RESULT_tier4_5_lvs_attempts.md\n"
        "#---------------------------------------------------------------"
    )

    if not pdk_key:
        out.append(
            f"puts stdout \"LVS_SETUP_SKIPPED: unknown PDK '{pdk}'; "
            "no power-net globalisation applied. Net-level LVS may "
            "report spurious unconnected-power mismatches.\""
        )
        return "\n".join(out) + "\n"

    # --- Rule 1 — global power-net declarations -------------------------
    power_nets = list(PDK_POWER_NETS.get(pdk_key, [])) + list(opts.extra_power_nets)
    # Deduplicate while preserving order (Python 3.7+ dict).
    power_nets = list(dict.fromkeys(power_nets))

    out.append("")
    out.append(
        "# Rule 1 — globalise power/ground nets. Magic ext2spice does NOT\n"
        "# mark these as .global, so Netgen otherwise sees a per-instance\n"
        "# flat net per VPWR/VGND/etc., which falsely diverges from a\n"
        "# Yosys structural netlist that shares one wire across cells."
    )
    for net in power_nets:
        out.append(f"global {net}")
    if opts.audit_comments:
        out.append(
            f"puts stdout \"LVS_SETUP_APPLIED: {len(power_nets)} "
            f"global power-net(s) for {pdk_key}\""
        )

    # --- Rule 2 — stdcell lib<->shortname equate (foundry-provided) ------
    out.append("")
    if opts.equate_stdcell_lib_to_short_name:
        sc_hint = PDK_STDCELL_PG_HINT.get(pdk_key, "<stdcell lib>")
        out.append(
            f"# Rule 2 — stdcell library-name equivalence is ALREADY emitted\n"
            f"# by the foundry {pdk_key}_setup.tcl wildcard loop matching\n"
            f"# `{sc_hint}`. No duplicate emit (would cause Netgen\n"
            f"# re-declaration warnings on the cross-name mapping)."
        )
    else:
        out.append(
            "# Rule 2 — explicit stdcell library-name equivalence suppressed\n"
            "# by option; trust the foundry setup's wildcard loop."
        )

    # --- Rule 3 — symmetric-MOS permute (foundry-provided) ---------------
    out.append("")
    out.append(
        "# Rule 3 — symmetric-MOS source-drain permutation plus the\n"
        "# foundry-wide default-symmetric directive are already in the\n"
        "# foundry setup. No supplementary emit needed."
    )

    # --- Rule 4 — optional flatten directives ----------------------------
    out.append("")
    fa, fb = opts.flatten_top_circuits
    if fa and fb:
        out.append(
            "# Rule 4 — flatten the top circuits BEFORE comparison. Use\n"
            "# when layout (Magic ext2spice) preserves stdcell subckt\n"
            "# hierarchy but schematic (yosys+flatten) is fully flat.\n"
            "# Flatten BOTH sides so device-level compare runs at the\n"
            "# same granularity on each."
        )
        out.append(f"flatten class \"-circuit1 {fa}\"")
        out.append(f"flatten class \"-circuit2 {fb}\"")
        if opts.audit_comments:
            out.append(
                f"puts stdout \"LVS_SETUP_APPLIED: flatten {fa}/{fb}\""
            )
    else:
        out.append("# Rule 4 — flatten directives NOT emitted (opt-in).")

    # --- Rule 5 — tap/fill ignore (audit-only comment) -------------------
    out.append("")
    out.append(
        "# Rule 5 — tap/fill/decap `ignore class` is conditionally emitted\n"
        "# by the foundry setup when MAGIC_EXT_USE_GDS=1. Set the env var\n"
        "# (or `--magic-ext-use-gds`) before invoking netgen if your\n"
        "# extracted layout contains tap cells the schematic does not."
    )

    return "\n".join(out) + "\n"


def _cli() -> int:
    """Command-line entrypoint — emit the TCL fragment to stdout or a file."""
    p = argparse.ArgumentParser(
        description="Emit Netgen LVS supplementary setup TCL (deterministic).",
    )
    p.add_argument("--pdk", required=True,
                   help="PDK name: sky130A | gf180mcuC | gf180mcuD")
    p.add_argument("--extra-power-net", action="append", default=[],
                   help="Additional power-net name to globalise (repeatable)")
    p.add_argument("--flatten-top-a", default="",
                   help="Top circuit name in circuit1 (layout) to flatten")
    p.add_argument("--flatten-top-b", default="",
                   help="Top circuit name in circuit2 (schematic) to flatten")
    p.add_argument("--no-equate-stdcell", action="store_true",
                   help="Suppress audit comment about stdcell lib→short equate")
    p.add_argument("--audit-comments", action="store_true",
                   help="Include puts stdout audit lines")
    p.add_argument("--out", type=Path, default=None,
                   help="Output path. Defaults to stdout.")
    args = p.parse_args()

    options = LvsSetupOptions(
        extra_power_nets=args.extra_power_net,
        flatten_top_circuits=(args.flatten_top_a, args.flatten_top_b),
        equate_stdcell_lib_to_short_name=not args.no_equate_stdcell,
        audit_comments=args.audit_comments,
    )
    text = build_supplementary_setup_tcl(args.pdk, options)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote: {args.out}", file=__import__("sys").stderr)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
